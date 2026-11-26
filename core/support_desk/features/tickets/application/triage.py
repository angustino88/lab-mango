"""Triage helpers: category/priority resolution, context sanitization, labels, and parent validation."""

from collections.abc import Iterable, Mapping
from typing import Any

from core.support_desk.contracts import (
    CLIENT_CONTEXT_ALLOWED_KEYS,
    CLIENT_CONTEXT_MAX_VALUE_LENGTH,
    IMPACT_CHOICES,
    PAGE_PATH_MAX_LENGTH,
    URGENCY_CHOICES,
    Impact,
    Urgency,
)
from core.support_desk.exceptions import InvalidFieldValueError, InvalidParentTicketError, TicketCreationDisabledError
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.ticket import SupportTicket

_IMPACT_VALUES = {value for value, _ in IMPACT_CHOICES}
_URGENCY_VALUES = {value for value, _ in URGENCY_CHOICES}


def validate_impact_urgency(impact: str | None, urgency: str | None) -> None:
    if impact not in (None, "") and impact not in _IMPACT_VALUES:
        raise InvalidFieldValueError(f"Invalid impact '{impact}'.")
    if urgency not in (None, "") and urgency not in _URGENCY_VALUES:
        raise InvalidFieldValueError(f"Invalid urgency '{urgency}'.")


def resolve_category(*, explicit_id: int | None, ticket_type: str) -> SupportCategory:
    """Resolve an active category: explicit ID, else type-matched code, else general, else first active."""
    qs = SupportCategory.objects.select_related("default_team").filter(is_active=True)
    if explicit_id is not None:
        category = qs.filter(pk=explicit_id).first()
        if not category:
            raise TicketCreationDisabledError(f"Category {explicit_id} is not active or does not exist.")
        return category

    for candidate_code in (ticket_type, "general"):
        category = qs.filter(code__iexact=candidate_code).order_by("sort_order", "id").first()
        if category:
            return category

    category = qs.order_by("sort_order", "id").first()
    if not category:
        raise TicketCreationDisabledError(
            "Ticket creation is disabled until an administrator defines at least one active category."
        )
    return category


def sanitize_page_path(raw: str | None) -> str:
    """Validate and normalize an optional relative web app route path (stripping query/fragment)."""
    if not raw:
        return ""
    value = raw.strip()
    if not value:
        return ""
    if "://" in value or value.startswith("//"):
        raise InvalidFieldValueError("page_path must be a relative route starting with '/'.")
    # Strip query string and fragment so sensitive tokens or query parameters are never stored.
    value = value.split("#", 1)[0].split("?", 1)[0].strip()
    if not value:
        return ""
    if not value.startswith("/"):
        raise InvalidFieldValueError("page_path must start with '/'.")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise InvalidFieldValueError("page_path contains invalid control characters.")
    if ".." in value.split("/"):
        raise InvalidFieldValueError("page_path must not contain parent directory traversal segments.")
    if len(value) > PAGE_PATH_MAX_LENGTH:
        raise InvalidFieldValueError(f"page_path must not exceed {PAGE_PATH_MAX_LENGTH} characters.")
    return value


def sanitize_client_context(raw: Mapping[str, Any] | None) -> dict[str, str]:
    """Validate and normalize an allowlisted map of non-sensitive client diagnostics."""
    if not raw:
        return {}
    if not isinstance(raw, Mapping):
        raise InvalidFieldValueError("client_context must be a JSON object.")

    cleaned: dict[str, str] = {}
    for key, raw_value in raw.items():
        if not isinstance(key, str) or key not in CLIENT_CONTEXT_ALLOWED_KEYS:
            allowed = ", ".join(sorted(CLIENT_CONTEXT_ALLOWED_KEYS))
            raise InvalidFieldValueError(f"Unsupported client_context key '{key}'. Allowed keys: {allowed}.")
        if raw_value is None:
            continue
        if not isinstance(raw_value, str):
            raise InvalidFieldValueError(f"client_context['{key}'] must be a string.")
        value = raw_value.strip()
        if not value:
            continue
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
            raise InvalidFieldValueError(f"client_context['{key}'] contains invalid control characters.")
        if len(value) > CLIENT_CONTEXT_MAX_VALUE_LENGTH:
            raise InvalidFieldValueError(
                f"client_context['{key}'] must not exceed {CLIENT_CONTEXT_MAX_VALUE_LENGTH} characters."
            )
        cleaned[key] = value
    return cleaned


def derive_priority(impact: str | None, urgency: str | None) -> SupportPriority | None:
    """Map an impact x urgency pair onto the configured active priorities (ITIL priority matrix).

    ``impact`` and ``urgency`` run 1 (high) to 3 (low); their sum minus one yields a score from 1 (most urgent)
    to 5 (least urgent) which is spread evenly across the active priorities ordered by ``rank``.
    A missing dimension counts as medium. Returns ``None`` if neither dimension is given.
    """
    if not impact and not urgency:
        return None
    score = int(impact or Impact.MEDIUM.value) + int(urgency or Urgency.MEDIUM.value) - 1
    priorities = list(SupportPriority.objects.filter(is_active=True).order_by("rank", "id"))
    if not priorities:
        return None
    position = int((score - 1) * (len(priorities) - 1) / 4 + 0.5)
    return priorities[position]


def resolve_priority(*, explicit_id: int | None, impact: str | None, urgency: str | None) -> SupportPriority:
    """Pick the priority for a new ticket: explicit -> derived from impact/urgency -> configured default."""
    if explicit_id:
        priority = SupportPriority.objects.filter(pk=explicit_id, is_active=True).first()
        if not priority:
            raise TicketCreationDisabledError(f"Priority {explicit_id} is not active or does not exist.")
        return priority
    derived = derive_priority(impact, urgency)
    if derived:
        return derived
    default = SupportPriority.objects.filter(is_default=True, is_active=True).first()
    if default:
        return default
    raise TicketCreationDisabledError(
        "No priority supplied and no default priority is configured. Provide priority_id, impact/urgency, "
        "or ask an administrator to mark a default priority."
    )


def normalize_label_names(names: Iterable[str]) -> list[str]:
    seen: dict[str, None] = {}
    for raw in names:
        name = (raw or "").strip().lower()
        if name:
            seen[name[:50]] = None
    return list(seen)


def get_or_create_labels(names: Iterable[str]) -> list[SupportLabel]:
    labels = []
    for name in normalize_label_names(names):
        label, _ = SupportLabel.objects.get_or_create(name__iexact=name, defaults={"name": name})
        labels.append(label)
    return labels


def validate_parent(ticket: SupportTicket | None, parent: SupportTicket) -> None:
    """Allow a single level of nesting and forbid cycles."""
    if ticket is not None and ticket.pk == parent.pk:
        raise InvalidParentTicketError("A ticket cannot be its own parent.")
    if parent.parent_id is not None:
        raise InvalidParentTicketError("Sub-tickets cannot be nested more than one level deep.")
    if ticket is not None and ticket.pk and ticket.children.exists():
        raise InvalidParentTicketError("A ticket that already has sub-tickets cannot become a sub-ticket.")


def label_names(ticket: SupportTicket) -> list[str]:
    return sorted(label.name for label in ticket.labels.all())


def serialize_change(old: Any, new: Any) -> dict[str, Any]:
    return {"old": old, "new": new}
