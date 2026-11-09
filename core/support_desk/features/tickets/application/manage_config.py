"""Admin configuration command use cases for categories, priorities, statuses, and settings."""

from dataclasses import dataclass
from typing import Any

from django.db import transaction
from django.utils.text import slugify

from core.support_desk.contracts import SystemState, TicketType
from core.support_desk.exceptions import (
    ConfigurationInUseError,
    PermissionDeniedError,
    RecordNotFoundError,
    SupportDeskError,
)
from core.support_desk.features.tickets.application.policies import can_manage_configuration
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.transition import SupportStatusTransition


@dataclass(frozen=True, slots=True)
class CreateCategoryInput:
    name: str
    description: str = ""
    sort_order: int = 0
    is_active: bool = True
    code: str = ""
    default_team_id: int | None = None


@dataclass(frozen=True, slots=True)
class UpdateCategoryInput:
    category_id: int
    name: str | None = None
    description: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    code: str | None = None
    default_team_id: int | None = None
    clear_default_team: bool = False


def _resolve_team(team_id: int | None) -> SupportTeam | None:
    if team_id is None:
        return None
    team = SupportTeam.objects.filter(pk=team_id).first()
    if not team:
        raise RecordNotFoundError(f"Team {team_id} not found.")
    return team


def create_category(command: CreateCategoryInput, *, actor: Any) -> SupportCategory:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage categories.")
    return SupportCategory.objects.create(
        name=command.name,
        description=command.description,
        sort_order=command.sort_order,
        is_active=command.is_active,
        code=command.code or slugify(command.name)[:50],
        default_team=_resolve_team(command.default_team_id),
    )


def update_category(command: UpdateCategoryInput, *, actor: Any) -> SupportCategory:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage categories.")
    cat = SupportCategory.objects.filter(pk=command.category_id).first()
    if not cat:
        raise RecordNotFoundError(f"Category {command.category_id} not found.")

    if command.name is not None:
        cat.name = command.name
    if command.description is not None:
        cat.description = command.description
    if command.sort_order is not None:
        cat.sort_order = command.sort_order
    if command.is_active is not None:
        cat.is_active = command.is_active
    if command.code is not None:
        cat.code = command.code
    if command.clear_default_team:
        cat.default_team = None
    elif command.default_team_id is not None:
        cat.default_team = _resolve_team(command.default_team_id)

    cat.save()
    return cat


def delete_category(category_id: int, *, actor: Any) -> None:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage categories.")
    cat = SupportCategory.objects.filter(pk=category_id).first()
    if not cat:
        raise RecordNotFoundError(f"Category {category_id} not found.")
    if SupportTicket.objects.filter(category=cat).exists():
        raise ConfigurationInUseError("Cannot delete category in use by existing tickets. Deactivate it instead.")
    cat.delete()


@dataclass(frozen=True, slots=True)
class CreatePriorityInput:
    name: str
    rank: int
    is_default: bool = False
    is_active: bool = True
    code: str = ""
    color_hex: str = ""
    response_target_minutes: int | None = None
    resolution_target_minutes: int | None = None


@dataclass(frozen=True, slots=True)
class UpdatePriorityInput:
    priority_id: int
    name: str | None = None
    rank: int | None = None
    is_default: bool | None = None
    is_active: bool | None = None
    code: str | None = None
    color_hex: str | None = None
    response_target_minutes: int | None = None
    resolution_target_minutes: int | None = None
    clear_response_target: bool = False
    clear_resolution_target: bool = False


def _validate_sla_targets(response: int | None, resolution: int | None) -> None:
    if response is not None and resolution is not None and response > resolution:
        raise SupportDeskError("The response target cannot be longer than the resolution target.")


def create_priority(command: CreatePriorityInput, *, actor: Any) -> SupportPriority:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage priorities.")
    with transaction.atomic():
        if command.is_default:
            SupportPriority.objects.filter(is_default=True).update(is_default=False)
        _validate_sla_targets(command.response_target_minutes, command.resolution_target_minutes)
        return SupportPriority.objects.create(
            name=command.name,
            rank=command.rank,
            is_default=command.is_default,
            is_active=command.is_active,
            code=command.code or slugify(command.name)[:50],
            color_hex=command.color_hex,
            response_target_minutes=command.response_target_minutes,
            resolution_target_minutes=command.resolution_target_minutes,
        )


def update_priority(command: UpdatePriorityInput, *, actor: Any) -> SupportPriority:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage priorities.")
    pri = SupportPriority.objects.filter(pk=command.priority_id).first()
    if not pri:
        raise RecordNotFoundError(f"Priority {command.priority_id} not found.")

    with transaction.atomic():
        if command.name is not None:
            pri.name = command.name
        if command.rank is not None:
            pri.rank = command.rank
        if command.is_active is not None:
            pri.is_active = command.is_active
        if command.code is not None:
            pri.code = command.code
        if command.color_hex is not None:
            pri.color_hex = command.color_hex
        if command.clear_response_target:
            pri.response_target_minutes = None
        elif command.response_target_minutes is not None:
            pri.response_target_minutes = command.response_target_minutes
        if command.clear_resolution_target:
            pri.resolution_target_minutes = None
        elif command.resolution_target_minutes is not None:
            pri.resolution_target_minutes = command.resolution_target_minutes
        _validate_sla_targets(pri.response_target_minutes, pri.resolution_target_minutes)
        if command.is_default is not None:
            if command.is_default:
                SupportPriority.objects.exclude(pk=pri.pk).filter(is_default=True).update(is_default=False)
            pri.is_default = command.is_default
        pri.save()
    return pri


def delete_priority(priority_id: int, *, actor: Any) -> None:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage priorities.")
    pri = SupportPriority.objects.filter(pk=priority_id).first()
    if not pri:
        raise RecordNotFoundError(f"Priority {priority_id} not found.")
    if SupportTicket.objects.filter(priority=pri).exists():
        raise ConfigurationInUseError("Cannot delete priority in use by existing tickets. Deactivate it instead.")
    pri.delete()


@dataclass(frozen=True, slots=True)
class CreateStatusInput:
    name: str
    system_state: str
    is_initial: bool = False
    is_active: bool = True
    sort_order: int = 0
    color_hex: str = ""
    is_final: bool = False
    pauses_sla: bool = False


@dataclass(frozen=True, slots=True)
class UpdateStatusInput:
    status_id: int
    name: str | None = None
    system_state: str | None = None
    is_initial: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
    color_hex: str | None = None
    is_final: bool | None = None
    pauses_sla: bool | None = None


def _validate_status_flags(system_state: str, *, is_final: bool, is_initial: bool, pauses_sla: bool) -> None:
    if is_final and system_state != SystemState.DONE.value:
        raise SupportDeskError("A final (closed) status must belong to the 'done' system state.")
    if is_initial and system_state != SystemState.OPEN.value:
        raise SupportDeskError("The initial status must belong to the 'open' system state.")
    if pauses_sla and system_state == SystemState.DONE.value:
        raise SupportDeskError("A 'done' status cannot pause SLA clocks.")


def create_status(command: CreateStatusInput, *, actor: Any) -> SupportStatus:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage statuses.")
    _validate_status_flags(
        command.system_state,
        is_final=command.is_final,
        is_initial=command.is_initial,
        pauses_sla=command.pauses_sla,
    )
    with transaction.atomic():
        if command.is_initial:
            SupportStatus.objects.filter(is_initial=True).update(is_initial=False)
        return SupportStatus.objects.create(
            name=command.name,
            system_state=command.system_state,
            is_initial=command.is_initial,
            is_active=command.is_active,
            sort_order=command.sort_order,
            color_hex=command.color_hex,
            is_final=command.is_final,
            pauses_sla=command.pauses_sla,
        )


def update_status(command: UpdateStatusInput, *, actor: Any) -> SupportStatus:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage statuses.")
    st = SupportStatus.objects.filter(pk=command.status_id).first()
    if not st:
        raise RecordNotFoundError(f"Status {command.status_id} not found.")

    with transaction.atomic():
        if command.name is not None:
            st.name = command.name
        if command.system_state is not None:
            st.system_state = command.system_state
        if command.sort_order is not None:
            st.sort_order = command.sort_order
        if command.is_active is not None:
            st.is_active = command.is_active
        if command.color_hex is not None:
            st.color_hex = command.color_hex
        if command.is_final is not None:
            st.is_final = command.is_final
        if command.pauses_sla is not None:
            st.pauses_sla = command.pauses_sla
        if command.is_initial is not None:
            if command.is_initial:
                SupportStatus.objects.exclude(pk=st.pk).filter(is_initial=True).update(is_initial=False)
            st.is_initial = command.is_initial
        _validate_status_flags(
            st.system_state,
            is_final=st.is_final,
            is_initial=st.is_initial,
            pauses_sla=st.pauses_sla,
        )
        st.save()
    return st


@dataclass(frozen=True, slots=True)
class CreateTransitionInput:
    from_status_id: int
    to_status_id: int
    allowed_roles: list[str]
    requires_reason: bool = False
    requires_resolution: bool = False


@dataclass(frozen=True, slots=True)
class UpdateTransitionInput:
    transition_id: int
    allowed_roles: list[str] | None = None
    requires_reason: bool | None = None
    requires_resolution: bool | None = None


def create_transition(command: CreateTransitionInput, *, actor: Any) -> SupportStatusTransition:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage status transitions.")
    from_status = SupportStatus.objects.filter(pk=command.from_status_id).first()
    to_status = SupportStatus.objects.filter(pk=command.to_status_id).first()
    if not from_status or not to_status:
        raise SupportDeskError("Invalid source or target status for transition.")

    return SupportStatusTransition.objects.create(
        from_status=from_status,
        to_status=to_status,
        allowed_roles=command.allowed_roles,
        requires_reason=command.requires_reason,
        requires_resolution=command.requires_resolution,
    )


def update_transition(command: UpdateTransitionInput, *, actor: Any) -> SupportStatusTransition:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage status transitions.")
    tr = SupportStatusTransition.objects.filter(pk=command.transition_id).first()
    if not tr:
        raise RecordNotFoundError(f"Transition {command.transition_id} not found.")

    if command.allowed_roles is not None:
        tr.allowed_roles = command.allowed_roles
    if command.requires_reason is not None:
        tr.requires_reason = command.requires_reason
    if command.requires_resolution is not None:
        tr.requires_resolution = command.requires_resolution
    tr.save()
    return tr


def delete_transition(transition_id: int, *, actor: Any) -> None:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can manage status transitions.")
    SupportStatusTransition.objects.filter(pk=transition_id).delete()


@dataclass(frozen=True, slots=True)
class UpdateSettingsInput:
    reopen_window_days: int | None = None
    auto_close_days: int | None = None
    max_attachment_size_bytes: int | None = None
    allowed_attachment_extensions: list[str] | None = None
    max_attachments_per_ticket: int | None = None
    comment_edit_window_minutes: int | None = None
    requesters_can_set_priority: bool | None = None
    sla_enabled: bool | None = None
    sla_at_risk_percent: int | None = None
    csat_enabled: bool | None = None
    csat_window_days: int | None = None
    default_ticket_type: str | None = None


def update_settings(command: UpdateSettingsInput, *, actor: Any) -> SupportSettings:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError("Only administrators can update support desk settings.")
    settings = SupportSettings.get_solo()

    if command.reopen_window_days is not None:
        settings.reopen_window_days = command.reopen_window_days
    if command.auto_close_days is not None:
        settings.auto_close_days = command.auto_close_days
    if command.max_attachment_size_bytes is not None:
        settings.max_attachment_size_bytes = command.max_attachment_size_bytes
    if command.allowed_attachment_extensions is not None:
        settings.allowed_attachment_extensions = command.allowed_attachment_extensions
    if command.max_attachments_per_ticket is not None:
        settings.max_attachments_per_ticket = command.max_attachments_per_ticket
    if command.comment_edit_window_minutes is not None:
        settings.comment_edit_window_minutes = command.comment_edit_window_minutes

    for field in (
        "requesters_can_set_priority",
        "sla_enabled",
        "sla_at_risk_percent",
        "csat_enabled",
        "csat_window_days",
        "default_ticket_type",
    ):
        value = getattr(command, field)
        if value is not None:
            setattr(settings, field, value)
    if not 1 <= settings.sla_at_risk_percent <= 100:
        raise SupportDeskError("sla_at_risk_percent must be between 1 and 100.")
    if settings.default_ticket_type not in {t.value for t in TicketType}:
        raise SupportDeskError(f"Invalid default ticket type '{settings.default_ticket_type}'.")

    settings.updated_by = actor
    settings.save()
    return settings
