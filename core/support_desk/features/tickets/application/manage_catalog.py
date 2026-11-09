"""Admin command use cases for teams, labels and canned responses."""

from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils.text import slugify

from core.support_desk.exceptions import (
    ConfigurationInUseError,
    PermissionDeniedError,
    RecordNotFoundError,
    SupportDeskError,
)
from core.support_desk.features.tickets.application.policies import can_manage_configuration, is_support_agent
from core.support_desk.models.canned_response import CannedResponse
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket

User = get_user_model()

_ADMIN_ONLY = "Only administrators can manage support teams, labels and canned responses."


def _require_admin(actor: Any) -> None:
    if not can_manage_configuration(actor):
        raise PermissionDeniedError(_ADMIN_ONLY)


# --- Teams -----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateTeamInput:
    name: str
    code: str = ""
    description: str = ""
    lead_id: int | None = None
    member_ids: tuple[int, ...] = ()
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class UpdateTeamInput:
    team_id: int
    name: str | None = None
    code: str | None = None
    description: str | None = None
    lead_id: int | None = None
    clear_lead: bool = False
    member_ids: tuple[int, ...] | None = None
    is_active: bool | None = None


def _active_users(ids: tuple[int, ...]) -> list[Any]:
    users = list(User.objects.filter(pk__in=ids, is_active=True))
    missing = set(ids) - {u.pk for u in users}
    if missing:
        raise RecordNotFoundError(f"Users not found: {sorted(missing)}")
    return users


def create_team(command: CreateTeamInput, *, actor: Any) -> SupportTeam:
    _require_admin(actor)
    lead = None
    if command.lead_id:
        (lead,) = _active_users((command.lead_id,))
    members = _active_users(command.member_ids)
    with transaction.atomic():
        team = SupportTeam.objects.create(
            name=command.name,
            code=command.code or slugify(command.name)[:50],
            description=command.description,
            lead=lead,
            is_active=command.is_active,
        )
        team.members.set(members)
    return team


def update_team(command: UpdateTeamInput, *, actor: Any) -> SupportTeam:
    _require_admin(actor)
    team = SupportTeam.objects.filter(pk=command.team_id).first()
    if not team:
        raise RecordNotFoundError(f"Team {command.team_id} not found.")
    with transaction.atomic():
        if command.name is not None:
            team.name = command.name
        if command.code is not None:
            team.code = command.code
        if command.description is not None:
            team.description = command.description
        if command.is_active is not None:
            team.is_active = command.is_active
        if command.clear_lead:
            team.lead = None
        elif command.lead_id is not None:
            (team.lead,) = _active_users((command.lead_id,))
        team.save()
        if command.member_ids is not None:
            team.members.set(_active_users(command.member_ids))
    return team


def delete_team(team_id: int, *, actor: Any) -> None:
    _require_admin(actor)
    team = SupportTeam.objects.filter(pk=team_id).first()
    if not team:
        raise RecordNotFoundError(f"Team {team_id} not found.")
    if SupportTicket.objects.filter(team=team).exists():
        raise ConfigurationInUseError("Cannot delete a team that owns tickets. Deactivate it instead.")
    team.delete()


# --- Labels ----------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateLabelInput:
    name: str
    color_hex: str = ""


@dataclass(frozen=True, slots=True)
class UpdateLabelInput:
    label_id: int
    name: str | None = None
    color_hex: str | None = None


def create_label(command: CreateLabelInput, *, actor: Any) -> SupportLabel:
    _require_admin(actor)
    if SupportLabel.objects.filter(name__iexact=command.name.strip()).exists():
        raise SupportDeskError(f"Label '{command.name}' already exists.")
    return SupportLabel.objects.create(name=command.name, color_hex=command.color_hex)


def update_label(command: UpdateLabelInput, *, actor: Any) -> SupportLabel:
    _require_admin(actor)
    label = SupportLabel.objects.filter(pk=command.label_id).first()
    if not label:
        raise RecordNotFoundError(f"Label {command.label_id} not found.")
    if command.name is not None:
        clash = SupportLabel.objects.filter(name__iexact=command.name.strip()).exclude(pk=label.pk).exists()
        if clash:
            raise SupportDeskError(f"Label '{command.name}' already exists.")
        label.name = command.name
    if command.color_hex is not None:
        label.color_hex = command.color_hex
    label.save()
    return label


def delete_label(label_id: int, *, actor: Any) -> None:
    _require_admin(actor)
    deleted, _ = SupportLabel.objects.filter(pk=label_id).delete()
    if not deleted:
        raise RecordNotFoundError(f"Label {label_id} not found.")


# --- Canned responses --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateCannedResponseInput:
    title: str
    body: str
    team_id: int | None = None
    is_active: bool = True


@dataclass(frozen=True, slots=True)
class UpdateCannedResponseInput:
    response_id: int
    title: str | None = None
    body: str | None = None
    team_id: int | None = None
    clear_team: bool = False
    is_active: bool | None = None


def _team_or_none(team_id: int | None) -> SupportTeam | None:
    if team_id is None:
        return None
    team = SupportTeam.objects.filter(pk=team_id).first()
    if not team:
        raise RecordNotFoundError(f"Team {team_id} not found.")
    return team


def create_canned_response(command: CreateCannedResponseInput, *, actor: Any) -> CannedResponse:
    _require_admin(actor)
    return CannedResponse.objects.create(
        title=command.title,
        body=command.body,
        team=_team_or_none(command.team_id),
        is_active=command.is_active,
        created_by=actor,
    )


def update_canned_response(command: UpdateCannedResponseInput, *, actor: Any) -> CannedResponse:
    _require_admin(actor)
    response = CannedResponse.objects.filter(pk=command.response_id).first()
    if not response:
        raise RecordNotFoundError(f"Canned response {command.response_id} not found.")
    if command.title is not None:
        response.title = command.title
    if command.body is not None:
        response.body = command.body
    if command.is_active is not None:
        response.is_active = command.is_active
    if command.clear_team:
        response.team = None
    elif command.team_id is not None:
        response.team = _team_or_none(command.team_id)
    response.save()
    return response


def delete_canned_response(response_id: int, *, actor: Any) -> None:
    _require_admin(actor)
    deleted, _ = CannedResponse.objects.filter(pk=response_id).delete()
    if not deleted:
        raise RecordNotFoundError(f"Canned response {response_id} not found.")


def render_canned_response(response: CannedResponse, *, ticket: SupportTicket, actor: Any) -> str:
    """Substitute the documented placeholders. Unknown placeholders are left untouched."""
    from core.support_desk.features.tickets.application.shared import actor_display_name

    values = {
        "{{requester_name}}": actor_display_name(ticket.requester),
        "{{ticket_key}}": ticket.key,
        "{{agent_name}}": actor_display_name(actor),
    }
    body = response.body
    for placeholder, value in values.items():
        body = body.replace(placeholder, value)
    return body


def list_canned_responses_for(actor: Any) -> list[CannedResponse]:
    """Agents see global responses plus those of teams they belong to (admins see all)."""
    if not is_support_agent(actor):
        raise PermissionDeniedError("Only support agents can use canned responses.")
    qs = CannedResponse.objects.filter(is_active=True).select_related("team")
    if can_manage_configuration(actor):
        return list(qs)
    from django.db.models import Q

    return list(qs.filter(Q(team__isnull=True) | Q(team__members=actor)).distinct())
