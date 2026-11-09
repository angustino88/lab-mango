"""Triage helpers: priority derivation (impact x urgency), labels, and parent validation."""

from collections.abc import Iterable
from typing import Any

from core.support_desk.contracts import IMPACT_CHOICES, URGENCY_CHOICES, Impact, Urgency
from core.support_desk.exceptions import InvalidFieldValueError, InvalidParentTicketError, TicketCreationDisabledError
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
