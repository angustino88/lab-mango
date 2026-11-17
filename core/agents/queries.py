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
from core.labs.features.equipment.public import monitoring_interfaces
from core.labs.features.monitoring.public import DEVICE_FRESHNESS_SECONDS, MAX_DEVICES_PER_COLLECTOR

MAX_OBSERVATION_BODY_BYTES = 262144


class AgentHealth(models.TextChoices):
    """Liveness of an active agent, derived from ``last_seen_at``; never persisted.

    Health describes only an enrolled (active) agent. Pending, revoked and decommissioned agents have
    no health: their lifecycle ``state`` says everything, and the two must not be merged.
    """

    ONLINE = "online", "Online"
    DELAYED = "delayed", "Delayed"
    OFFLINE = "offline", "Offline"


class GrantStatus(models.TextChoices):
    """Lifecycle of one enrollment grant, derived from its timestamps."""

    USABLE = "usable", "Usable"
    REDEEMED = "redeemed", "Redeemed"
    REVOKED = "revoked", "Revoked"
    EXPIRED = "expired", "Expired"


def agent_health(identity: AgentIdentity, *, now: datetime | None = None) -> str | None:
    """Online within ``AGENT_HEALTH_ONLINE_S``, delayed until ``AGENT_HEALTH_OFFLINE_S``, else offline.

    An active agent that has never sent a heartbeat is offline. Non-active agents return ``None``.
    """
    if identity.state != AgentIdentity.State.ACTIVE:
        return None
    if identity.last_seen_at is None:
        return AgentHealth.OFFLINE
    age = ((now or timezone.now()) - identity.last_seen_at).total_seconds()
    if age <= settings.AGENT_HEALTH_ONLINE_S:
        return AgentHealth.ONLINE
    if age <= settings.AGENT_HEALTH_OFFLINE_S:
        return AgentHealth.DELAYED
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


def monitoring_policy(identity: AgentIdentity) -> dict[str, object]:
    """Reporting contract for one enrolled agent.

    Agents must apply at least one batch per collector within ``freshness_seconds``; an
    incremental batch with no devices is a valid keep-alive.
    """
    return {
        "generation_key": identity.monitoring_generation_key,
        "max_devices": MAX_DEVICES_PER_COLLECTOR,
        "max_body_bytes": MAX_OBSERVATION_BODY_BYTES,
        "freshness_seconds": DEVICE_FRESHNESS_SECONDS,
        "interface_names": monitoring_interfaces(),
    }
