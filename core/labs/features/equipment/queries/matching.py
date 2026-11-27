"""Find equipment whose product model meets specification requirements and that is free in a window.

Query budget, whatever the number of units: definitions (1), the ranked page with counts (1), the page's
specification values (1) and current placement (1). Requirements are evaluated in SQL as correlated EXISTS
subqueries on ``ProductModelSpecification``; numbers use the generated ``value_number`` column and its index.
"""

import re
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, QuerySet, Value, When

from core.labs.models import (
    Booking,
    Equipment,
    EquipmentAssignment,
    EquipmentBooking,
    EquipmentLifecycleState,
    EquipmentLoan,
    ProductModelSpecification,
    SpecificationDefinition,
)
from core.labs.models.resource.base.downtime import condition_expression, outer_windows
from core.labs.models.resource.equipment.specification import FALSE_VALUES, NUMERIC_VALUE_PATTERN, TRUE_VALUES

MAX_REQUIREMENTS = 10
MAX_RESULTS = 50
MAX_WINDOW = timedelta(days=31)
NUMBER_OPS = frozenset({"eq", "neq", "gte", "lte", "between", "in"})
TEXT_OPS = frozenset({"eq", "neq", "in", "contains"})
BOOLEAN_OPS = frozenset({"eq", "neq"})
MATCHED, MISSED, UNKNOWN = "matched", "missed", "unknown"

# SI prefixes accepted when a requirement's unit differs from the definition's unit ("GHz" against "MHz").
SI_PREFIXES = {
    "p": Decimal("1e-12"),
    "n": Decimal("1e-9"),
    "u": Decimal("1e-6"),
    "µ": Decimal("1e-6"),
    "μ": Decimal("1e-6"),
    "m": Decimal("1e-3"),
    "k": Decimal("1e3"),
    "K": Decimal("1e3"),
    "M": Decimal("1e6"),
    "G": Decimal("1e9"),
    "T": Decimal("1e12"),
}


@dataclass(frozen=True, slots=True)
class SpecRequirement:
    definition_id: int
    op: str
    value: Any
    unit: str = ""
    required: bool = True


@dataclass(frozen=True, slots=True)
class MatchEquipmentInput:
    requirements: Sequence[SpecRequirement] = ()
    category_id: int | None = None
    kind_id: int | None = None
    type_id: int | None = None
    manufacturer_id: int | None = None
    product_model_id: int | None = None
    department_id: int | None = None
    room_id: int | None = None
    available_from: datetime | None = None
    available_until: datetime | None = None
    include_near_matches: bool = False
    limit: int = 20


@dataclass(frozen=True, slots=True)
class RequirementResult:
    definition_id: int
    name: str
    status: str
    actual: str | None


@dataclass(frozen=True, slots=True)
class EquipmentMatch:
    equipment: Any
    product_model: Any
    score: Decimal
    is_full_match: bool
    requirements: list[RequirementResult] = field(default_factory=list)
    location: str = ""
    condition: str = ""
    is_on_loan: bool = False


@dataclass(frozen=True, slots=True)
class MatchResult:
    matches: list[EquipmentMatch]
    is_truncated: bool


@dataclass(frozen=True, slots=True)
class _Compiled:
    requirement: SpecRequirement
    definition: SpecificationDefinition
    condition: Q


def match_equipment(*, data: MatchEquipmentInput) -> MatchResult:
    """Units in service whose product model meets the requirements, best first.

    Full matches meet every required requirement. With ``include_near_matches``, units missing exactly one
    required requirement follow. Optional requirements only raise the rank. With a window, units with an open
    loan, an overlapping reservation or an overlapping downtime window are left out.
    """
    compiled = _compile(data.requirements)
    required = [item for item in compiled if item.requirement.required]
    optional = [item for item in compiled if not item.requirement.required]

    queryset = _candidates(data)
    if data.available_from is not None and data.available_until is not None:
        queryset = _free_in(queryset, data.available_from, data.available_until)
    queryset = queryset.annotate(
        matched_required=_count(required),
        matched_optional=_count(optional),
        current_condition=condition_expression(Equipment),
        is_on_loan=Exists(EquipmentLoan.objects.filter(equipment_id=OuterRef("pk"), returned_at__isnull=True)),
    )
    threshold = len(required) - (1 if data.include_near_matches and required else 0)
    if threshold > 0:
        queryset = queryset.filter(matched_required__gte=threshold)
    rows = list(
        queryset.select_related("product_model").order_by("-matched_required", "-matched_optional", "name", "pk")[
            : data.limit + 1
        ]
    )
    is_truncated = len(rows) > data.limit
    rows = rows[: data.limit]
    values = _spec_values(rows, compiled)
    locations = _locations(rows)
    matches = [
        _project(row, compiled=compiled, values=values, locations=locations, required_count=len(required))
        for row in rows
    ]
    return MatchResult(matches=matches, is_truncated=is_truncated)


def _compile(requirements: Sequence[SpecRequirement]) -> list[_Compiled]:
    if len(requirements) > MAX_REQUIREMENTS:
        raise ValidationError({"requirements": f"Send at most {MAX_REQUIREMENTS} requirements."})
    ids = {item.definition_id for item in requirements}
    definitions = SpecificationDefinition.objects.in_bulk(ids)
    compiled = []
    for index, requirement in enumerate(requirements):
        definition = definitions.get(requirement.definition_id)
        if definition is None:
            raise ValidationError({f"requirements.{index}.definition_id": "Select an existing specification."})
        try:
            condition = _condition(requirement, definition)
        except ValidationError as error:
            raise ValidationError({f"requirements.{index}": error.messages}) from error
        compiled.append(_Compiled(requirement, definition, condition))
    return compiled


def _condition(requirement: SpecRequirement, definition: SpecificationDefinition) -> Q:
    """The ``ProductModelSpecification`` filter one requirement stands for."""
    kind = definition.value_type
    op = requirement.op
    if kind == SpecificationDefinition.ValueType.NUMBER:
        if op not in NUMBER_OPS:
            raise ValidationError(f"Use one of {', '.join(sorted(NUMBER_OPS))} for a number specification.")
        factor = _unit_factor(requirement.unit, definition.unit)
        if op == "between":
            low, high = (_number(item) * factor for item in _pair(requirement.value))
            return Q(value_number__gte=low, value_number__lte=high)
        if op == "in":
            return Q(value_number__in=[_number(item) * factor for item in _items(requirement.value)])
        number = _number(requirement.value) * factor
        return {
            "eq": Q(value_number=number),
            "neq": ~Q(value_number=number) & Q(value_number__isnull=False),
            "gte": Q(value_number__gte=number),
            "lte": Q(value_number__lte=number),
        }[op]
    if kind == SpecificationDefinition.ValueType.BOOLEAN:
        if op not in BOOLEAN_OPS:
            raise ValidationError("Use eq or neq for a yes/no specification.")
        wanted = _boolean(requirement.value)
        values = TRUE_VALUES if wanted == (op == "eq") else FALSE_VALUES
        return Q(value__iregex=r"^(" + "|".join(sorted(values)) + r")$")
    if op not in TEXT_OPS:
        raise ValidationError(f"Use one of {', '.join(sorted(TEXT_OPS))} for a text specification.")
    if op == "in":
        query = Q()
        for item in _items(requirement.value):
            query |= Q(value__iexact=str(item))
        return query
    text = _text(requirement.value)
    return {"eq": Q(value__iexact=text), "neq": ~Q(value__iexact=text), "contains": Q(value__icontains=text)}[op]


def _unit_factor(given: str, unit: str) -> Decimal:
    """Factor turning a value in ``given`` into ``unit``; same unit or no unit is 1. Only SI prefixes convert."""
    given, unit = (given or "").strip(), (unit or "").strip()
    if not given or given == unit:
        return Decimal(1)

    def split(text: str) -> list[tuple[Decimal, str]]:
        options = [(Decimal(1), text)]
        if len(text) > 1 and text[0] in SI_PREFIXES:
            options.append((SI_PREFIXES[text[0]], text[1:]))
        return options

    for given_scale, given_base in split(given):
        for unit_scale, unit_base in split(unit):
            if given_base == unit_base:
                return given_scale / unit_scale
    raise ValidationError(f"Cannot convert {given} to {unit or 'a unitless value'}.")


def _number(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValidationError("Enter a number.")
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except InvalidOperation as error:
        raise ValidationError("Enter a number.") from error


def _boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    raise ValidationError("Enter yes or no.")


def _text(value: Any) -> str:
    if not isinstance(value, str | int | float) or isinstance(value, bool) or not str(value).strip():
        raise ValidationError("Enter a value.")
    return str(value).strip()


def _items(value: Any) -> list[Any]:
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise ValidationError("Send a list of 1 to 20 values.")
    return value


def _pair(value: Any) -> tuple[Any, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValidationError("Send [minimum, maximum].")
    return value[0], value[1]


def _candidates(data: MatchEquipmentInput) -> QuerySet[Equipment]:
    queryset = Equipment.objects.filter(
        lifecycle_state=EquipmentLifecycleState.IN_SERVICE, product_model__isnull=False
    )
    for name, value in (
        ("kind__category_id", data.category_id),
        ("kind_id", data.kind_id),
        ("type_id", data.type_id),
        ("manufacturer_id", data.manufacturer_id),
        ("product_model_id", data.product_model_id),
        ("department_id", data.department_id),
    ):
        if value is not None:
            queryset = queryset.filter(**{name: value})
    if data.room_id is not None:
        placed = EquipmentAssignment.objects.filter(equipment_id=OuterRef("pk"), unassigned_at__isnull=True).filter(
            Q(room_id=data.room_id) | Q(station__room_id=data.room_id) | Q(bench__setup_location__room_id=data.room_id)
        )
        queryset = queryset.filter(Exists(placed))
    return queryset


def _free_in(queryset: QuerySet[Equipment], starts_at: datetime, ends_at: datetime) -> QuerySet[Equipment]:
    """Leave out units busy at any moment of ``[starts_at, ends_at)``. An unreturned loan stays busy until returned."""
    loaned = EquipmentLoan.objects.filter(
        equipment_id=OuterRef("pk"), returned_at__isnull=True, handed_over_at__lt=ends_at
    )
    reserved = EquipmentBooking.objects.filter(
        equipment_id=OuterRef("pk"),
        status__in=Booking.ACTIVE_STATUSES,
        approval_status__in=Booking.RESERVING_APPROVAL_STATUSES,
        starts_at__lt=ends_at,
        ends_at__gt=starts_at,
    )
    down = outer_windows(Equipment).overlapping(starts_at, ends_at)
    return queryset.exclude(Exists(loaned)).exclude(Exists(reserved)).exclude(Exists(down))


def _count(items: list[_Compiled]):
    if not items:
        return Value(0, output_field=IntegerField())
    total: Any = None
    for item in items:
        meets = Exists(
            ProductModelSpecification.objects.filter(
                item.condition, product_model_id=OuterRef("product_model_id"), definition_id=item.definition.pk
            )
        )
        term = Case(When(meets, then=Value(1)), default=Value(0), output_field=IntegerField())
        total = term if total is None else total + term
    return total


def _spec_values(rows: Sequence[Equipment], compiled: list[_Compiled]) -> dict[int, dict[int, str]]:
    model_ids = {row.product_model_id for row in rows}
    definition_ids = {item.definition.pk for item in compiled}
    values: dict[int, dict[int, str]] = defaultdict(dict)
    if not model_ids or not definition_ids:
        return values
    for model_id, definition_id, value in ProductModelSpecification.objects.filter(
        product_model_id__in=model_ids, definition_id__in=definition_ids
    ).values_list("product_model_id", "definition_id", "value"):
        values[model_id][definition_id] = value
    return values


def _locations(rows: Sequence[Equipment]) -> dict[int, str]:
    """Current placement name per unit: bench, else station, else room, else the location note."""
    if not rows:
        return {}
    locations: dict[int, str] = {}
    for equipment_id, bench, station, room, note in (
        EquipmentAssignment.objects.filter(equipment_id__in=[row.pk for row in rows], unassigned_at__isnull=True)
        .order_by("equipment_id", "-assigned_at", "-pk")
        .values_list("equipment_id", "bench__name", "station__name", "room__name", "location_note")
    ):
        locations.setdefault(equipment_id, next((place for place in (bench, station, room, note) if place), ""))
    return locations


def _project(row, *, compiled, values, locations, required_count) -> EquipmentMatch:
    model_values = values.get(row.product_model_id, {})
    results = []
    for item in compiled:
        actual = model_values.get(item.definition.pk)
        if actual is None:
            status = UNKNOWN
        else:
            status = MATCHED if _meets(item, actual) else MISSED
        unit = f" {item.definition.unit}" if actual is not None and item.definition.unit else ""
        results.append(
            RequirementResult(
                item.definition.pk, item.definition.name, status, f"{actual}{unit}" if actual is not None else None
            )
        )
    total = len(compiled)
    met = sum(1 for result in results if result.status == MATCHED)
    score = (Decimal(met) / Decimal(total)).quantize(Decimal("0.01")) if total else Decimal(1)
    return EquipmentMatch(
        equipment=row,
        product_model=row.product_model,
        score=score,
        is_full_match=row.matched_required == required_count,
        requirements=results,
        location=locations.get(row.pk, ""),
        condition=row.current_condition,
        is_on_loan=row.is_on_loan,
    )


def _meets(item: _Compiled, actual: str) -> bool:
    """The SQL condition evaluated on one stored value, for the per-requirement status of a returned unit.

    Numbers follow the generated column: a value that is not a plain decimal has no number and never matches.
    """
    requirement, definition = item.requirement, item.definition
    if definition.value_type == SpecificationDefinition.ValueType.NUMBER:
        if not re.match(NUMERIC_VALUE_PATTERN, actual):
            return False
        number = Decimal(actual.strip().replace(",", "."))
        factor = _unit_factor(requirement.unit, definition.unit)
        if requirement.op == "between":
            low, high = (_number(value) * factor for value in _pair(requirement.value))
            return low <= number <= high
        if requirement.op == "in":
            return number in {_number(value) * factor for value in _items(requirement.value)}
        target = _number(requirement.value) * factor
        return {"eq": number == target, "neq": number != target, "gte": number >= target, "lte": number <= target}[
            requirement.op
        ]
    if definition.value_type == SpecificationDefinition.ValueType.BOOLEAN:
        is_true = actual.strip().lower() in TRUE_VALUES
        return (
            is_true == _boolean(requirement.value)
            if requirement.op == "eq"
            else is_true != _boolean(requirement.value)
        )
    text = actual.strip().lower()
    if requirement.op == "in":
        return text in {str(value).strip().lower() for value in _items(requirement.value)}
    wanted = _text(requirement.value).lower()
    return {"eq": text == wanted, "neq": text != wanted, "contains": wanted in text}[requirement.op]
