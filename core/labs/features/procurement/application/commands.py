"""Atomic purchase and acquisition-cost allocation commands."""

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import DatabaseError, IntegrityError, connection, transaction

from core.labs.features.procurement.exceptions import (
    PurchaseAllocationConflict,
    PurchaseDraftConflict,
    PurchaseDraftValidationFailed,
    PurchaseETagRequired,
    PurchaseNotFound,
    PurchasePreconditionFailed,
)
from core.labs.models import (
    Purchase,
    PurchaseAuditEvent,
    PurchaseItem,
    PurchaseItemResource,
    PurchasePriority,
    PurchaseTransaction,
)
from core.labs.models.procurement.purchase import PURCHASE_RESOURCE_MODELS, PurchaseStatus


def _save_actor_stamped(instance, actor):
    """Persist a model carrying legacy stamps through the actor-aware base."""
    instance.save(actor=actor)


@dataclass(frozen=True)
class PurchaseLineInput:
    description: str
    quantity: int = 1
    unit_price: Decimal = Decimal("0.00")
    notes: str = ""


@dataclass(frozen=True)
class CreatePurchaseItemInput:
    purchase_id: int
    description: str
    quantity: int = 1
    unit_price: Decimal = Decimal("0.00")
    notes: str = ""


@dataclass(frozen=True)
class CreatePurchaseInput:
    supplier: str
    purchase_date: date
    total_amount: Decimal
    purchase_order_number: str = ""
    currency: str = "EUR"
    status: str = "draft"
    notes: str = ""
    items: tuple[PurchaseLineInput, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class CreatePurchaseItemResourceInput:
    purchase_item_id: int
    resource_type_id: int
    resource_id: int
    acquisition_price: Decimal


@dataclass(frozen=True)
class CreatePurchaseTransactionInput:
    purchase_id: int
    transaction_type: str
    amount: Decimal
    settled_at: datetime
    reference: str = ""
    notes: str = ""


@dataclass(frozen=True)
class DraftLineInput:
    description: str
    quantity: int
    unit_price: Decimal
    notes: str = ""
    purpose: str | None = None
    priority_id: int | None = None
    unit: str | None = None


@dataclass(frozen=True)
class UpdatePurchaseDraftInput:
    purchase_id: int
    if_match: str | None
    changes: dict[str, object]
    request_id: str


@dataclass(frozen=True)
class CreateDraftLineInput:
    purchase_id: int
    if_match: str | None
    line: DraftLineInput
    request_id: str


@dataclass(frozen=True)
class UpdateDraftLineInput:
    purchase_id: int
    item_id: int
    if_match: str | None
    changes: dict[str, object]
    request_id: str


@dataclass(frozen=True)
class DeleteDraftLineInput:
    purchase_id: int
    item_id: int
    if_match: str | None
    request_id: str


def purchase_etag(purchase: Purchase) -> str:
    return f'"purchase-{purchase.pk}-v{purchase.version}"'


def item_etag(item: PurchaseItem) -> str:
    return f'"item-{item.pk}-v{item.version}"'


def _require_match(if_match: str | None, current: str) -> None:
    if if_match is None:
        raise PurchaseETagRequired("If-Match is required for this operation.")
    tags = _parse_if_match(if_match)
    if tags == "*":
        return
    if current in tags:
        return
    raise PurchasePreconditionFailed("The purchase draft has changed; reload and retry.")


def _parse_if_match(value: str) -> list[str] | str:
    tags: list[str] = []
    index = 0
    length = len(value)
    while index < length:
        while index < length and value[index] in " \t":
            index += 1
        if index == length:
            break
        if value[index] == "*":
            index += 1
            while index < length and value[index] in " \t":
                index += 1
            if index != length or tags:
                raise PurchaseDraftValidationFailed("If-Match must contain valid entity tags.")
            return "*"
        start = index
        if value.startswith("W/", index):
            index += 2
        if index >= length or value[index] != '"':
            raise PurchaseDraftValidationFailed("If-Match must contain quoted entity tags.")
        index += 1
        while index < length and value[index] != '"':
            if value[index] in "\r\n":
                raise PurchaseDraftValidationFailed("If-Match contains an invalid entity tag.")
            index += 1
        if index == length:
            raise PurchaseDraftValidationFailed("If-Match contains an unterminated entity tag.")
        index += 1
        tag = value[start:index]
        if tag.startswith("W/"):
            raise PurchasePreconditionFailed("The purchase draft has changed; reload and retry.")
        tags.append(tag)
        while index < length and value[index] in " \t":
            index += 1
        if index < length:
            if value[index] != ",":
                raise PurchaseDraftValidationFailed("If-Match must separate entity tags with commas.")
            index += 1
            if index == length:
                raise PurchaseDraftValidationFailed("If-Match must end with an entity tag.")
    if not tags:
        raise PurchaseDraftValidationFailed("If-Match must contain at least one entity tag.")
    return tags


def _set_lock_timeout() -> None:
    if connection.vendor == "postgresql":
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '3s'")
        except DatabaseError as exc:
            raise PurchaseDraftConflict("Purchase is busy; retry the request.") from exc


def _validate_draft_line(line: DraftLineInput, *, existing_priority_id: int | None = None) -> PurchasePriority | None:
    errors: dict[str, str] = {}
    if not line.description.strip() or len(line.description) > 255:
        errors["description"] = "Enter a description of at most 255 characters."
    if line.quantity < 1 or line.quantity > 1_000_000:
        errors["quantity"] = "Quantity must be between 1 and 1,000,000."
    if not line.unit_price.is_finite() or line.unit_price < 0 or line.unit_price.as_tuple().exponent < -2:
        errors["unit_price"] = "Unit price must be non-negative with at most two decimal places."
    if len(str(line.unit_price).replace(".", "").replace("-", "")) > 14:
        errors["unit_price"] = "Unit price exceeds the supported precision."
    if line.notes and len(line.notes) > 2_000:
        errors["notes"] = "Remark must be at most 2,000 characters."
    if line.purpose is not None:
        line_purpose = line.purpose.strip()
        if len(line_purpose) > 2_000 or (
            line_purpose and any(ord(char) < 32 and char not in "\t\n\r" for char in line_purpose)
        ):
            errors["purpose"] = "Purpose must be at most 2,000 characters and contain no control characters."
        elif not line_purpose:
            errors["purpose"] = "Purpose cannot be blank when provided."
    if line.unit is not None and not line.unit.strip():
        errors["unit"] = "Unit cannot be blank when provided."
    if line.unit is not None and len(line.unit.strip()) > 32:
        errors["unit"] = "Unit must be at most 32 characters."
    priority = None
    if line.priority_id is not None:
        priority = PurchasePriority.objects.filter(pk=line.priority_id).first()
        if priority is None or (not priority.is_active and line.priority_id != existing_priority_id):
            errors["priority_id"] = "Select an active purchase priority."
    if errors:
        raise PurchaseDraftValidationFailed("Purchase line validation failed.", details=errors)
    return priority


def _audit_snapshot(purchase: Purchase, item: PurchaseItem | None = None) -> dict[str, object]:
    result: dict[str, object] = {
        "supplier": purchase.supplier,
        "purchase_date": purchase.purchase_date.isoformat() if purchase.purchase_date else None,
        "purchase_order_number": purchase.purchase_order_number,
        "currency": purchase.currency,
        "total_amount": format(purchase.total_amount, ".2f"),
        "notes": purchase.notes,
    }
    if item is not None:
        result.update(
            {
                "quantity": item.quantity,
                "unit_price": format(item.unit_price, ".2f"),
                "line_value": format(item.quantity * item.unit_price, ".2f"),
                "description": item.description,
                "notes": item.notes,
                "purpose": item.purpose,
                "unit": item.unit,
                "priority": ({"id": item.priority_id, "code": item.priority.code} if item.priority_id else None),
            }
        )
    return result


def _record_audit(
    *,
    purchase: Purchase,
    item: PurchaseItem | None,
    item_id: int | None = None,
    action: str,
    actor,
    request_id: str,
    before,
    after,
) -> None:
    PurchaseAuditEvent.objects.create(
        purchase=purchase,
        item_id=item.pk if item else item_id,
        action=action,
        actor=actor,
        request_id=request_id,
        before=before,
        after=after,
    )


def _locked_draft(purchase_id: int) -> Purchase:
    _set_lock_timeout()
    try:
        purchase = Purchase.objects.select_for_update().filter(pk=purchase_id).first()
    except DatabaseError as exc:
        if "lock timeout" in str(exc).lower() or getattr(exc.__cause__, "pgcode", None) == "55P03":
            raise PurchaseDraftConflict("Purchase is busy; retry the request.") from exc
        raise
    if purchase is None:
        raise PurchaseNotFound("Purchase not found.")
    if purchase.status != PurchaseStatus.DRAFT:
        raise PurchaseDraftConflict("Only draft purchases can be edited.")
    return purchase


@transaction.atomic
def update_purchase_draft(command: UpdatePurchaseDraftInput, *, actor) -> Purchase:
    purchase = _locked_draft(command.purchase_id)
    _require_match(command.if_match, purchase_etag(purchase))
    allowed = {"supplier", "purchase_date", "purchase_order_number", "currency", "total_amount", "notes"}
    if set(command.changes) - allowed:
        raise PurchaseDraftValidationFailed("Unsupported purchase fields.")
    before = _audit_snapshot(purchase)
    if "currency" in command.changes:
        if not isinstance(command.changes["currency"], str):
            raise PurchaseDraftValidationFailed("Currency must be a valid ISO 4217 code.", details={"currency": "Invalid currency."})
        try:
            Purchase._meta.get_field("currency").run_validators(command.changes["currency"])
        except ValidationError as exc:
            raise PurchaseDraftValidationFailed("Currency must be a valid ISO 4217 code.", details={"currency": "Invalid currency."}) from exc
    currency = command.changes.get("currency", purchase.currency)
    if currency != purchase.currency and (
        purchase.items.filter(resource_allocations__isnull=False).exists()
        or purchase.transactions.exists()
    ):
        raise PurchaseDraftConflict("Currency cannot change after allocation or transaction activity.")
    if "total_amount" in command.changes:
        try:
            total_amount = Decimal(command.changes["total_amount"])
        except (TypeError, ValueError, ArithmeticError) as exc:
            raise PurchaseDraftValidationFailed("Purchase total must be a decimal amount.", details={"total_amount": "Invalid decimal."}) from exc
        if not total_amount.is_finite() or total_amount < 0 or total_amount.as_tuple().exponent < -2:
            raise PurchaseDraftValidationFailed("Purchase total must be non-negative with at most two decimal places.", details={"total_amount": "Invalid amount."})
        command.changes["total_amount"] = total_amount
    if "supplier" in command.changes and (
        not str(command.changes["supplier"]).strip() or len(str(command.changes["supplier"])) > 255
    ):
        raise PurchaseDraftValidationFailed("Supplier cannot be blank.", details={"supplier": "This field may not be blank."})
    if "purchase_order_number" in command.changes and len(str(command.changes["purchase_order_number"])) > 100:
        raise PurchaseDraftValidationFailed("Purchase order number is too long.", details={"purchase_order_number": "At most 100 characters."})
    if "notes" in command.changes and len(str(command.changes["notes"])) > 2_000:
        raise PurchaseDraftValidationFailed("Notes must be at most 2,000 characters.", details={"notes": "Too long."})
    purchase.last_modified_by = actor
    changed = False
    for field_name, value in command.changes.items():
        if getattr(purchase, field_name) != value:
            setattr(purchase, field_name, value)
            changed = True
    if changed:
        purchase.version += 1
        update_fields = set(command.changes) | {"version", "last_modified_by", "modified"}
        purchase.save(actor=actor, update_fields=update_fields)
        after = _audit_snapshot(purchase)
        _record_audit(
            purchase=purchase,
            item=None,
            action="update",
            actor=actor,
            request_id=command.request_id,
            before=before,
            after=after,
        )
    return purchase


@transaction.atomic
def create_draft_line(command: CreateDraftLineInput, *, actor) -> PurchaseItem:
    purchase = _locked_draft(command.purchase_id)
    if purchase.items.count() >= 500:
        raise PurchaseDraftValidationFailed("A purchase cannot have more than 500 lines.", details={"items": "Line limit exceeded."})
    priority = _validate_draft_line(command.line)
    item = PurchaseItem(
        purchase=purchase,
        description=command.line.description.strip(),
        quantity=command.line.quantity,
        unit_price=command.line.unit_price,
        notes=command.line.notes.strip(),
        purpose=command.line.purpose.strip() if command.line.purpose else command.line.purpose,
        priority=priority,
        unit=command.line.unit.strip() if command.line.unit else command.line.unit,
        creator=actor,
        last_modified_by=actor,
    )
    item.full_clean()
    item.save(actor=actor)
    purchase.version += 1
    purchase.last_modified_by = actor
    purchase.save(actor=actor)
    _record_audit(purchase=purchase, item=item, action="create", actor=actor, request_id=command.request_id, before=None, after=_audit_snapshot(purchase, item))
    return item


@transaction.atomic
def update_draft_line(command: UpdateDraftLineInput, *, actor) -> PurchaseItem:
    purchase = _locked_draft(command.purchase_id)
    item = PurchaseItem.objects.select_for_update().filter(pk=command.item_id, purchase_id=purchase.pk).first()
    if item is None:
        raise PurchaseNotFound("Purchase line not found.")
    _require_match(command.if_match, item_etag(item))
    if item.resource_allocations.exists():
        raise PurchaseDraftConflict("Allocated purchase lines cannot be edited.")
    allowed = {"description", "quantity", "unit_price", "notes", "purpose", "priority_id", "unit"}
    if set(command.changes) - allowed:
        raise PurchaseDraftValidationFailed("Unsupported purchase line fields.")
    before = _audit_snapshot(purchase, item)
    values = {
        "description": item.description,
        "quantity": item.quantity,
        "unit_price": item.unit_price,
        "notes": item.notes,
        "purpose": item.purpose,
        "priority_id": item.priority_id,
        "unit": item.unit,
    }
    values.update(command.changes)
    if "priority_id" in values:
        values["priority_id"] = int(values["priority_id"]) if values["priority_id"] is not None else None
    line = DraftLineInput(**values)
    priority = _validate_draft_line(line, existing_priority_id=item.priority_id)
    changed = any(getattr(item, key) != value for key, value in command.changes.items() if key != "priority_id")
    changed = changed or ("priority_id" in command.changes and item.priority_id != command.changes["priority_id"])
    if changed:
        item.description = line.description.strip()
        item.quantity = line.quantity
        item.unit_price = line.unit_price
        item.notes = line.notes.strip()
        item.purpose = line.purpose.strip() if line.purpose else line.purpose
        item.priority = priority
        item.unit = line.unit.strip() if line.unit else line.unit
        item.version += 1
        item.last_modified_by = actor
        item_update_fields = set(command.changes)
        if "priority_id" in item_update_fields:
            item_update_fields.remove("priority_id")
            item_update_fields.add("priority")
        item_update_fields.update({"version", "last_modified_by", "modified"})
        item.full_clean()
        item.save(actor=actor, update_fields=item_update_fields)
        purchase.version += 1
        purchase.last_modified_by = actor
        purchase.save(actor=actor)
        after = _audit_snapshot(purchase, item)
        _record_audit(
            purchase=purchase,
            item=item,
            action="update",
            actor=actor,
            request_id=command.request_id,
            before=before,
            after=after,
        )
    return item


@transaction.atomic
def delete_draft_line(command: DeleteDraftLineInput, *, actor) -> None:
    purchase = _locked_draft(command.purchase_id)
    item = PurchaseItem.objects.select_for_update().filter(pk=command.item_id, purchase_id=purchase.pk).first()
    if item is None:
        raise PurchaseNotFound("Purchase line not found.")
    _require_match(command.if_match, item_etag(item))
    if item.resource_allocations.exists():
        raise PurchaseDraftConflict("Allocated purchase lines cannot be removed.")
    before = _audit_snapshot(purchase, item)
    item_id = item.pk
    item.delete()
    purchase.version += 1
    purchase.last_modified_by = actor
    purchase.save(actor=actor)
    _record_audit(
        purchase=purchase,
        item=None,
        item_id=item_id,
        action="delete",
        actor=actor,
        request_id=command.request_id,
        before=before,
        after=None,
    )


@transaction.atomic
def create_purchase(command: CreatePurchaseInput, *, actor) -> Purchase:
    if command.total_amount < 0:
        raise ValidationError({"total_amount": "Purchase total must be non-negative."})
    if len(command.currency) != 3:
        raise ValidationError({"currency": "Currency must be an ISO 4217 three-letter code."})
    if command.status not in PurchaseStatus.values:
        raise ValidationError({"status": "Select a valid purchase status."})
    if not command.supplier.strip():
        raise ValidationError({"supplier": "Supplier cannot be blank."})
    purchase = Purchase(
        supplier=command.supplier,
        purchase_order_number=command.purchase_order_number,
        purchase_date=command.purchase_date,
        currency=command.currency,
        total_amount=command.total_amount,
        status=command.status,
        notes=command.notes,
        creator=actor,
        last_modified_by=actor,
    )
    _save_actor_stamped(purchase, actor)
    for item_input in command.items:
        if not item_input.description.strip() or item_input.quantity < 1 or item_input.unit_price < 0:
            raise ValidationError({"items": "Purchase item descriptions, quantities, and prices are invalid."})
        item = PurchaseItem(
            purchase=purchase,
            description=item_input.description,
            quantity=item_input.quantity,
            unit_price=item_input.unit_price,
            notes=item_input.notes,
            creator=actor,
            last_modified_by=actor,
        )
        _save_actor_stamped(item, actor)
    return purchase


@transaction.atomic
def create_purchase_item(command: CreatePurchaseItemInput, *, actor) -> PurchaseItem:
    purchase = Purchase.objects.select_for_update().get(pk=command.purchase_id)
    if not command.description.strip() or command.quantity < 1 or command.unit_price < 0:
        raise ValidationError({"items": "Purchase item descriptions, quantities, and prices are invalid."})
    item = PurchaseItem(
        purchase=purchase,
        description=command.description,
        quantity=command.quantity,
        unit_price=command.unit_price,
        notes=command.notes,
        creator=actor,
        last_modified_by=actor,
    )
    item.full_clean()
    _save_actor_stamped(item, actor)
    if purchase.status == PurchaseStatus.DRAFT:
        purchase.version += 1
        purchase.save(actor=actor, update_fields={"version", "modified"})
    return item


@transaction.atomic
def create_purchase_item_resource(
    command: CreatePurchaseItemResourceInput,
    *,
    actor,
) -> PurchaseItemResource:
    # All purchase writers acquire the aggregate root before its lines. Fetch the
    # parent id without a lock, then lock parent and line in the shared order.
    item_purchase_id = PurchaseItem.objects.values_list("purchase_id", flat=True).get(pk=command.purchase_item_id)
    purchase = Purchase.objects.select_for_update().get(pk=item_purchase_id)
    item = PurchaseItem.objects.select_for_update().get(pk=command.purchase_item_id, purchase_id=purchase.pk)
    resource_type = ContentType.objects.get(pk=command.resource_type_id)
    if (resource_type.app_label, resource_type.model) not in PURCHASE_RESOURCE_MODELS:
        raise ValidationError({"resource_type": "This resource type cannot be allocated to a purchase item."})
    allocation = PurchaseItemResource(
        purchase_item=item,
        resource_type=resource_type,
        resource_id=command.resource_id,
        acquisition_price=command.acquisition_price,
        creator=actor,
        last_modified_by=actor,
    )
    allocation.full_clean()
    try:
        with transaction.atomic():
            _save_actor_stamped(allocation, actor)
    except IntegrityError as exc:
        # Only the named uniqueness guard represents a duplicate-resource race.
        cause = exc.__cause__
        constraint_name = getattr(getattr(cause, "diag", None), "constraint_name", None)
        if constraint_name != "purchase_resource_unique":
            raise
        raise PurchaseAllocationConflict("The resource is already allocated to a purchase.") from exc
    return allocation


@transaction.atomic
def create_purchase_transaction(
    command: CreatePurchaseTransactionInput,
    *,
    actor,
) -> PurchaseTransaction:
    purchase = Purchase.objects.select_for_update().get(pk=command.purchase_id)
    record = PurchaseTransaction(
        purchase=purchase,
        transaction_type=command.transaction_type,
        amount=command.amount,
        settled_at=command.settled_at,
        reference=command.reference,
        notes=command.notes,
        creator=actor,
        last_modified_by=actor,
    )
    record.full_clean()
    _save_actor_stamped(record, actor)
    return record


__all__ = [
    "CreateDraftLineInput", "CreatePurchaseInput", "CreatePurchaseItemInput", "CreatePurchaseItemResourceInput",
    "CreatePurchaseTransactionInput", "DeleteDraftLineInput", "DraftLineInput", "PurchaseLineInput",
    "UpdateDraftLineInput", "UpdatePurchaseDraftInput", "create_draft_line", "create_purchase",
    "create_purchase_item", "create_purchase_item_resource", "create_purchase_transaction", "delete_draft_line",
    "item_etag", "purchase_etag", "update_draft_line", "update_purchase_draft",
]
