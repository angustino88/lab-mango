"""Baseline Support Desk configuration provisioned on a fresh database.

Statuses, priorities and categories are admin-defined so a lab can rename them, recolour them and tune
SLA targets without a deploy, but a new installation must accept tickets straight away. Each group
below is created only while its table is empty. Once any row exists (seeded or created by an
administrator) that group is left alone, so admin edits, renames and deactivations are never reverted.

Business logic never depends on these names: it reads ``SystemState``, ``is_initial``, ``is_final``,
``pauses_sla``, priority ``rank`` and the SLA minute targets.

Registered from ``SupportDeskConfig.ready()`` and run by ``provision_reference_data`` (and so at the end
of every ``migrate``, see ``core/reference_data/signals.py``).
"""

from typing import Final

from django.db import transaction

from core.support_desk.contracts import SupportRole, SystemState
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.transition import SupportStatusTransition

PROVISIONER_KEY: Final = "support_desk.default_configuration"

_REQUESTER = SupportRole.REQUESTER.value
_AGENT = SupportRole.AGENT.value
_ADMIN = SupportRole.ADMIN.value
_STAFF: Final = [_AGENT, _ADMIN]
_EVERYONE: Final = [_REQUESTER, _AGENT, _ADMIN]

OPEN: Final = "Open"
IN_PROGRESS: Final = "In Progress"
WAITING: Final = "Waiting for Customer"
RESOLVED: Final = "Resolved"
CLOSED: Final = "Closed"

DEFAULT_STATUSES: Final[tuple[dict[str, object], ...]] = (
    {
        "name": OPEN,
        "system_state": SystemState.OPEN.value,
        "is_initial": True,
        "color_hex": "#1677FF",
        "sort_order": 10,
    },
    {"name": IN_PROGRESS, "system_state": SystemState.ACTIVE.value, "color_hex": "#FA8C16", "sort_order": 20},
    {
        "name": WAITING,
        "system_state": SystemState.WAITING.value,
        "pauses_sla": True,
        "color_hex": "#722ED1",
        "sort_order": 30,
    },
    {"name": RESOLVED, "system_state": SystemState.DONE.value, "color_hex": "#52C41A", "sort_order": 40},
    {
        "name": CLOSED,
        "system_state": SystemState.DONE.value,
        "is_final": True,
        "color_hex": "#8C8C8C",
        "sort_order": 50,
    },
)

# (from, to, allowed roles, requires reason, requires resolution summary)
DEFAULT_TRANSITIONS: Final[tuple[tuple[str, str, list[str], bool, bool], ...]] = (
    (OPEN, IN_PROGRESS, _STAFF, False, False),
    (OPEN, WAITING, _STAFF, False, False),
    (OPEN, RESOLVED, _STAFF, False, True),
    (OPEN, CLOSED, _STAFF, True, False),  # cancelled / duplicate / raised by mistake
    (IN_PROGRESS, WAITING, _STAFF, False, False),
    (IN_PROGRESS, RESOLVED, _STAFF, False, True),
    (WAITING, IN_PROGRESS, _STAFF, False, False),
    (WAITING, RESOLVED, _STAFF, False, True),
    (RESOLVED, OPEN, _EVERYONE, True, False),  # reopen; requesters are limited by the reopen window
    (RESOLVED, CLOSED, _STAFF, False, False),
)

DEFAULT_PRIORITIES: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "Critical",
        "code": "critical",
        "rank": 1,
        "color_hex": "#F5222D",
        "response_target_minutes": 30,
        "resolution_target_minutes": 4 * 60,
    },
    {
        "name": "High",
        "code": "high",
        "rank": 2,
        "color_hex": "#FA541C",
        "response_target_minutes": 2 * 60,
        "resolution_target_minutes": 24 * 60,
    },
    {
        "name": "Medium",
        "code": "medium",
        "rank": 3,
        "color_hex": "#FAAD14",
        "is_default": True,
        "response_target_minutes": 8 * 60,
        "resolution_target_minutes": 3 * 24 * 60,
    },
    {
        "name": "Low",
        "code": "low",
        "rank": 4,
        "color_hex": "#52C41A",
        "response_target_minutes": 24 * 60,
        "resolution_target_minutes": 7 * 24 * 60,
    },
)

DEFAULT_CATEGORIES: Final[tuple[dict[str, object], ...]] = (
    {
        "name": "General",
        "code": "general",
        "description": "Requests that do not fit a more specific category.",
        "sort_order": 0,
    },
)


def provision_support_desk_defaults(*, using: str) -> None:
    """Create the baseline workflow, priorities and category for every group whose table is empty.

    Idempotent and safe to run concurrently: rows are created with ``get_or_create`` on their natural
    key, and the database unique constraints (status name, transition pair, active priority and
    category names) reject a second concurrent insert.
    """
    with transaction.atomic(using=using):
        if not SupportStatus.objects.using(using).exists():
            _create_workflow(using)
        if not SupportPriority.objects.using(using).exists():
            for row in DEFAULT_PRIORITIES:
                values = dict(row)
                SupportPriority.objects.using(using).get_or_create(
                    name=values.pop("name"), is_active=True, defaults=values
                )
        if not SupportCategory.objects.using(using).exists():
            for row in DEFAULT_CATEGORIES:
                values = dict(row)
                SupportCategory.objects.using(using).get_or_create(
                    name=values.pop("name"), is_active=True, defaults=values
                )


def _create_workflow(using: str) -> None:
    statuses: dict[str, SupportStatus] = {}
    for row in DEFAULT_STATUSES:
        values = dict(row)
        name = str(values.pop("name"))
        statuses[name], _ = SupportStatus.objects.using(using).get_or_create(name=name, defaults=values)
    for from_name, to_name, roles, requires_reason, requires_resolution in DEFAULT_TRANSITIONS:
        SupportStatusTransition.objects.using(using).get_or_create(
            from_status=statuses[from_name],
            to_status=statuses[to_name],
            defaults={
                "allowed_roles": list(roles),
                "requires_reason": requires_reason,
                "requires_resolution": requires_resolution,
            },
        )
