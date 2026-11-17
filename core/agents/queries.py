"""Read-side selectors and derived views for agent identities and their enrollment grants."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from django.conf import settings
from django.db import models
from django.db.models import QuerySet
from django.utils import timezone

from core.agents.models import AgentIdentity, EnrollmentGrant


class AgentHealth(models.TextChoices):
    """Operator-facing liveness, derived from state and ``last_seen_at``; never persisted."""

    ONLINE = "online", "Online"
    STALE = "stale", "Stale"
    OFFLINE = "offline", "Offline"
    NEVER_SEEN = "never_seen", "Never seen"
    AWAITING_ENROLLMENT = "awaiting_enrollment", "Awaiting enrollment"
    RETIRED = "retired", "Retired"


class GrantStatus(models.TextChoices):
    """Lifecycle of one enrollment grant, derived from its timestamps."""

    USABLE = "usable", "Usable"
    REDEEMED = "redeemed", "Redeemed"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


def agent_health(identity: AgentIdentity, *, now: datetime | None = None) -> str:
    """Classify an identity's liveness for display; thresholds come from ``AGENT_HEALTH_*_S``."""
    if identity.state == AgentIdentity.State.PENDING:
        return AgentHealth.AWAITING_ENROLLMENT
    if identity.state != AgentIdentity.State.ACTIVE:
        return AgentHealth.RETIRED
    if identity.last_seen_at is None:
        return AgentHealth.NEVER_SEEN
    age = ((now or timezone.now()) - identity.last_seen_at).total_seconds()
    if age <= settings.AGENT_HEALTH_ONLINE_S:
        return AgentHealth.ONLINE
    if age <= settings.AGENT_HEALTH_OFFLINE_S:
        return AgentHealth.STALE
    return AgentHealth.OFFLINE


def grant_status(grant: EnrollmentGrant, *, now: datetime | None = None) -> str:
    if grant.used_at is not None:
        return GrantStatus.REDEEMED
    if grant.revoked_at is not None:
        return GrantStatus.REVOKED
    if grant.expires_at <= (now or timezone.now()):
        return GrantStatus.EXPIRED
    return GrantStatus.USABLE


def agent_list(
    *,
    equipment_ids: Sequence[int] = (),
    equipment_uid: UUID | None = None,
    states: Sequence[str] = (),
) -> QuerySet[AgentIdentity]:
    """Agents newest first (pk tie-breaker keeps pages stable), optionally narrowed."""
    agents = AgentIdentity.objects.select_related("equipment")
    if equipment_ids:
        agents = agents.filter(equipment_id__in=equipment_ids)
    if equipment_uid is not None:
        agents = agents.filter(equipment__uid=equipment_uid)
    if states:
        agents = agents.filter(state__in=states)
    return agents.order_by("-created", "-pk")


def agent_grants(agent_id: int) -> QuerySet[EnrollmentGrant]:
    """Grant history of one agent, newest first; the clear grant is never stored."""
    return EnrollmentGrant.objects.filter(agent_id=agent_id).select_related("creator").order_by("-created", "-pk")
