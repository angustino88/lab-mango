"""Session log write commands: the agent pushes one completed session after logout."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from core.labs.features.lab_sessions.contracts import SessionLogRecord
from core.labs.features.lab_sessions.exceptions import (
    SessionLogConflict,
    SessionLogEquipmentUnavailable,
    SessionLogInvalid,
)
from core.labs.models import Equipment, LabSessionLog

# Owner decision O19 (docs/proposals/finance-and-lab-analytics.md). Times come from the agent's
# computer clock and are checked against the server clock.
MAX_CLOCK_AHEAD = timedelta(minutes=5)
MAX_SESSION_AGE = timedelta(days=7)

_UNIQUE_REPORT_CONSTRAINT = "unique_session_report_per_agent"
_COMPARED_FIELDS = (
    "login_time",
    "logout_time",
    "active_duration_seconds",
    "remote_user",
    "remote_ip",
    "remote_host",
    "booking_code",
)


@dataclass(frozen=True)
class RecordSessionLogInput:
    """One completed session. ``equipment_id`` and ``agent_id`` come from the signing agent, never the body."""

    equipment_id: int
    agent_id: str
    event_id: UUID
    login_time: datetime
    logout_time: datetime
    active_duration_seconds: float
    remote_user: str
    remote_ip: str | None = None
    remote_host: str | None = None
    booking_code: str | None = None
    agent_version: str = ""


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip() or None


@dataclass(frozen=True)
class _SessionValues:
    """Values exactly as the model stores them, so a replay compares equal to the stored row."""

    login_time: datetime
    logout_time: datetime
    active_duration_seconds: float
    remote_user: str | None
    remote_ip: str | None
    remote_host: str | None
    booking_code: str | None

    def as_fields(self) -> dict[str, object]:
        return {name: getattr(self, name) for name in _COMPARED_FIELDS}


def _normalized_values(command: RecordSessionLogInput) -> _SessionValues:
    remote_ip = _blank_to_none(command.remote_ip)
    if remote_ip is not None:
        try:
            remote_ip = LabSessionLog._meta.get_field("remote_ip").clean(remote_ip, None)
        except ValidationError as error:
            raise SessionLogInvalid(details={"remote_ip": error.messages[0]}) from error
    return _SessionValues(
        login_time=command.login_time,
        logout_time=command.logout_time,
        active_duration_seconds=float(command.active_duration_seconds),
        remote_user=_blank_to_none(command.remote_user),
        remote_ip=remote_ip,
        remote_host=_blank_to_none(command.remote_host),
        booking_code=_blank_to_none(command.booking_code),
    )


def _ensure_within_limits(values: _SessionValues, *, now: datetime) -> None:
    login_time, logout_time = values.login_time, values.logout_time
    active = values.active_duration_seconds
    errors: dict[str, str] = {}
    if values.remote_user is None:
        errors["remote_user"] = "Remote user is required."
    if logout_time <= login_time:
        errors["logout_time"] = "Logout time must be after login time."
    elif logout_time > now + MAX_CLOCK_AHEAD:
        errors["logout_time"] = "Logout time is in the future; check the computer clock."
    if login_time < now - MAX_SESSION_AGE:
        errors["login_time"] = "Login time is more than 7 days ago; check the computer clock."
    if active < 0:
        errors["active_duration_seconds"] = "Active time cannot be negative."
    elif logout_time > login_time and active > (logout_time - login_time).total_seconds():
        errors["active_duration_seconds"] = "Active time cannot exceed the time between login and logout."
    if errors:
        raise SessionLogInvalid(details=errors)


def _record(session_log: LabSessionLog, values: _SessionValues, *, created: bool) -> SessionLogRecord:
    # Built from the validated values: on a replay they equal the stored row, and they are never null.
    return SessionLogRecord(
        id=session_log.pk,
        event_id=session_log.event_id,
        login_time=values.login_time,
        logout_time=values.logout_time,
        booking_code=values.booking_code,
        created=created,
    )


def _replay(stored: LabSessionLog, values: _SessionValues) -> SessionLogRecord:
    if any(getattr(stored, name) != getattr(values, name) for name in _COMPARED_FIELDS):
        raise SessionLogConflict()
    return _record(stored, values, created=False)


def _find_stored(key: dict[str, object]) -> LabSessionLog | None:
    return LabSessionLog.objects.filter(**key).first()


def record_session_log(
    command: RecordSessionLogInput, *, actor: object, now: datetime | None = None
) -> SessionLogRecord:
    """Store one completed session, or return the stored one when the agent repeats the push.

    Race guard: ``unique_session_report_per_agent`` (computer, agent id, event id). Two identical
    pushes arriving together both try the insert; the loser's ``IntegrityError`` is mapped by
    constraint name and answered from the winner's row. Idempotent on that natural key: equal values
    return the stored record, different values raise ``SessionLogConflict``. ``actor`` is the agent
    principal, not a user, so the record carries no creator (as in ``sync_computing_activity``).
    """
    now = now or timezone.now()
    values = _normalized_values(command)
    _ensure_within_limits(values, now=now)
    key = {
        "computing_equipment_id": command.equipment_id,
        "agent_id": command.agent_id,
        "event_id": command.event_id,
    }

    with transaction.atomic():
        # Soft deletion only; a computer deleted after this read still identifies the session.
        if not Equipment.objects.filter(pk=command.equipment_id, deleted_at__isnull=True).exists():
            raise SessionLogEquipmentUnavailable()

        stored = _find_stored(key)
        if stored is not None:
            return _replay(stored, values)

        session_log = LabSessionLog(
            **key,
            **values.as_fields(),
            agent_version=command.agent_version.strip(),
            reported_at=now,
        )
        try:
            with transaction.atomic():
                session_log.save(actor=None)
        except IntegrityError as error:
            constraint = getattr(getattr(error.__cause__, "diag", None), "constraint_name", None)
            if constraint != _UNIQUE_REPORT_CONSTRAINT:
                raise
            return _replay(LabSessionLog.objects.get(**key), values)
        except ValidationError as error:
            raise SessionLogInvalid(details={k: v[0] for k, v in error.message_dict.items()}) from error
    return _record(session_log, values, created=True)


__all__ = ["MAX_CLOCK_AHEAD", "MAX_SESSION_AGE", "RecordSessionLogInput", "record_session_log"]
