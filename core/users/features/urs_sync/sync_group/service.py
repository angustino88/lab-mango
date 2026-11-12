"""Synchronize URS group membership into Django groups and reconcile user activity.

Phases:

1. **Fetch** — one HTTPS call per URS group. No transaction and no lock is held during network I/O.
   A response that is not the expected shape marks the group ``failed``; it is never read as "empty".
2. **Apply** — one transaction holding a PostgreSQL transaction advisory lock. Race guard: concurrent
   runs (Celery beat and the admin action) serialize on that lock, and the apply is set-based, so a
   second run with the same URS data converges to the same state. Activity changes go through the
   users lifecycle command, which locks the user row before the Entra identity row.

URS is the source of truth: every successfully fetched group is applied in full, at once (owner
decision 2026-11-12). Optional safety check, off unless ``URS_SYNC_SAFETY_BRAKE`` is on: a group that
would lose all of its members, or more than ``URS_SYNC_MAX_REMOVAL_RATIO`` of them when it has at least
``URS_SYNC_BRAKE_MIN_MEMBERS``, is not applied (``blocked``) unless the run is forced by an operator.

URS member names are ``domain\\account``. The domain is dropped: the owner confirmed that one account
name identifies one person across domains. Names are matched case-insensitively; the database enforces
one account per lower-case username.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field

import requests
from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.auth.validators import UnicodeUsernameValidator
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.db.models import Count
from django.db.models.functions import Lower
from django.utils import timezone

from core.users.features.urs_sync.mapping import ensure_linked_group
from core.users.models import URSGroup, User
from core.users.public import SetUserActiveInput, set_user_active

logger = logging.getLogger(__name__)

_LOCK_KEY = "users.urs_sync.apply"
_USERNAME_MAX_LENGTH: int = User._meta.get_field("username").max_length or 150
_username_validator = UnicodeUsernameValidator()


@dataclass(frozen=True, slots=True)
class _FetchedGroup:
    urs_group_pk: int
    group_id: int
    name: str
    usernames: frozenset[str]
    invalid_members: int


@dataclass(slots=True)
class SyncReport:
    """Counts for one run. Group names are listed per outcome."""

    applied: list[str] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    users_created: int = 0
    memberships_added: int = 0
    memberships_removed: int = 0
    users_activated: int = 0
    users_deactivated: int = 0
    skipped_unmanaged: int = 0
    invalid_members: int = 0

    def summary(self) -> str:
        return (
            f"applied={len(self.applied)} blocked={len(self.blocked)} failed={len(self.failed)} "
            f"created={self.users_created} added={self.memberships_added} removed={self.memberships_removed} "
            f"activated={self.users_activated} deactivated={self.users_deactivated} "
            f"skipped_unmanaged={self.skipped_unmanaged} invalid_members={self.invalid_members}"
        )


def sync_urs_group(queryset: Iterable[URSGroup], *, force: bool = False) -> SyncReport:
    """Fetch every URS group in ``queryset`` and apply the successfully fetched ones.

    ``force=True`` applies groups the safety check would block. Only operators may request it.
    """
    report = SyncReport()
    urs_api_url: str = settings.URS_API_URL
    access_token: str = settings.URS_ACCESS_TOKEN
    if not access_token:
        logger.error("URS sync skipped: URS_ACCESS_TOKEN is not configured")
        return report
    if not urs_api_url or not urs_api_url.strip():
        logger.error("URS sync skipped: URS_API_URL is not configured")
        return report

    fetched: list[_FetchedGroup] = []
    failures: dict[int, str] = {}
    for urs_group in queryset:
        name = str(urs_group)
        if urs_group.group_id is None:
            # Older URS groups may predate automatic linking; create their Django group now.
            urs_group.group = ensure_linked_group(urs_group.pk)
            urs_group.group_id = urs_group.group.pk
        result = _fetch_members(urs_group, url=urs_api_url, access_token=access_token)
        if isinstance(result, str):
            failures[urs_group.pk] = result
            report.failed.append(name)
            continue
        usernames, invalid = result
        report.invalid_members += invalid
        fetched.append(
            _FetchedGroup(
                urs_group_pk=urs_group.pk,
                group_id=urs_group.group_id,
                name=name,
                usernames=usernames,
                invalid_members=invalid,
            )
        )

    _apply(fetched, failures, report=report, force=force)
    logger.info("URS sync finished: %s", report.summary())
    return report


def _fetch_members(urs_group: URSGroup, *, url: str, access_token: str) -> tuple[frozenset[str], int] | str:
    """Return ``(lower-case usernames, invalid member count)`` or a failure message."""
    payload = {"serviceId": urs_group.urs_group_id, "AccessToken": access_token}
    try:
        response = requests.post(
            url=url,
            data=json.dumps(payload),
            headers={"Content-Type": "application/json"},
            verify=settings.URS_API_VERIFY_SSL,
            timeout=settings.URS_API_TIMEOUT_S,
        )
    except requests.RequestException as exc:
        logger.warning("URS sync request failed for group %s: %s", urs_group, type(exc).__name__)
        return f"URS request failed ({type(exc).__name__})."
    if response.status_code != 200:
        logger.warning("URS sync error for group %s: HTTP %s", urs_group, response.status_code)
        return f"URS returned HTTP {response.status_code}."
    try:
        body = json.loads(response.text)
    except ValueError:
        return "URS response is not JSON."
    info = body.get("Info") if isinstance(body, dict) else None
    members = info.get("UserMembers") if isinstance(info, dict) else None
    if not isinstance(members, list):
        return "URS response has no Info.UserMembers list."

    usernames: set[str] = set()
    invalid = 0
    for member in members:
        username = _parse_member(member)
        if username is None:
            invalid += 1
        else:
            usernames.add(username)
    if invalid:
        logger.warning("URS group %s: %s member name(s) could not be used", urs_group, invalid)
    return frozenset(usernames), invalid


def _parse_member(member: object) -> str | None:
    r"""``"apac\nbo0hc"`` -> ``"nbo0hc"``; ``None`` when the value cannot be a username."""
    if not isinstance(member, str):
        return None
    _domain, separator, account = member.rpartition("\\")
    account = account.strip().lower()
    if not separator or not account or len(account) > _USERNAME_MAX_LENGTH:
        return None
    try:
        _username_validator(account)
    except ValidationError:
        return None
    return account


def _lock_apply() -> None:
    number = int.from_bytes(hashlib.sha256(_LOCK_KEY.encode()).digest()[:8], "big", signed=True)
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(%s)", [number])


def _apply(fetched: list[_FetchedGroup], failures: dict[int, str], *, report: SyncReport, force: bool) -> None:
    """Apply fetched groups and record every group's outcome, in one locked transaction."""
    now = timezone.now()
    with transaction.atomic():
        _lock_apply()
        for urs_group_pk, message in failures.items():
            _record(urs_group_pk, URSGroup.SyncStatus.FAILED, message, now)
        if not fetched:
            return

        users_by_name = _load_users({name for group in fetched for name in group.usernames})
        superuser_ids = set(User.objects.filter(is_superuser=True).values_list("pk", flat=True))
        groups = {group.pk: group for group in Group.objects.filter(pk__in=[f.group_id for f in fetched])}
        affected_ids: set[int] = set()
        any_applied = False

        for item in fetched:
            group = groups.get(item.group_id)
            if group is None:
                _record(item.urs_group_pk, URSGroup.SyncStatus.FAILED, "Linked Django group no longer exists.", now)
                report.failed.append(item.name)
                continue
            existing = set(group.user_set.values_list("pk", flat=True))
            known_members: set[int] = set()
            missing: list[str] = []
            for username in sorted(item.usernames):
                user = users_by_name.get(username)
                if user is None:
                    missing.append(username)
                elif user.is_urs_managed:
                    known_members.add(user.pk)
                else:
                    report.skipped_unmanaged += 1
                    logger.warning("URS sync skipped account %s: it is not URS-managed", user.pk)
            keep = known_members | (existing & superuser_ids)
            removals = existing - keep
            brake_on = settings.URS_SYNC_SAFETY_BRAKE and not force
            blocked_reason = _blocked_reason(existing, removals, item.usernames) if brake_on else None
            if blocked_reason is not None:
                _record(item.urs_group_pk, URSGroup.SyncStatus.BLOCKED, blocked_reason, now)
                report.blocked.append(item.name)
                logger.warning("URS sync blocked for group %s: %s", item.name, blocked_reason)
                continue

            for username in missing:
                user, created = _create_stub(username)
                users_by_name[username] = user
                report.users_created += int(created)
                if user.is_urs_managed:
                    keep.add(user.pk)
                else:
                    report.skipped_unmanaged += 1
            additions = keep - existing
            if removals:
                group.user_set.remove(*removals)
            if additions:
                group.user_set.add(*additions)
            affected_ids.update(removals, additions)
            report.memberships_added += len(additions)
            report.memberships_removed += len(removals)
            message = f"+{len(additions)} -{len(removals)}" + (" (forced)" if force else "")
            if item.invalid_members:
                message += f", {item.invalid_members} unusable member name(s)"
            _record(item.urs_group_pk, URSGroup.SyncStatus.APPLIED, message, now)
            report.applied.append(item.name)
            any_applied = True

        if any_applied:
            _reconcile_activity(affected_ids, superuser_ids, report=report)


def _blocked_reason(existing: set[int], removals: set[int], usernames: frozenset[str]) -> str | None:
    if not existing:
        return None
    if not usernames:
        return f"URS returned no members; {len(existing)} current member(s) were kept."
    min_members: int = settings.URS_SYNC_BRAKE_MIN_MEMBERS
    max_ratio: float = settings.URS_SYNC_MAX_REMOVAL_RATIO
    if len(existing) >= min_members and len(removals) / len(existing) > max_ratio:
        return (
            f"Sync would remove {len(removals)} of {len(existing)} member(s) "
            f"(limit {max_ratio:.0%}); nothing was changed."
        )
    return None


def _load_users(usernames: set[str]) -> dict[str, User]:
    if not usernames:
        return {}
    users = User.objects.annotate(lower_username=Lower("username")).filter(lower_username__in=usernames)
    return {user.lower_username: user for user in users}


def _create_stub(username: str) -> tuple[User, bool]:
    """Create a URS-managed stub without a usable password; race-safe on the case-insensitive constraint."""
    try:
        with transaction.atomic():
            user = User(username=username, is_urs_managed=True)
            user.set_unusable_password()
            user.save()
            # Stub accounts have no Entra binding, so there is no users routing key to publish.
            return user, True
    except IntegrityError as exc:
        constraint = getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None)
        if constraint not in {"users_user_username_ci_unique", "users_user_username_key"}:
            raise
        return User.objects.annotate(lower_username=Lower("username")).get(lower_username=username), False


def _reconcile_activity(affected_ids: set[int], superuser_ids: set[int], *, report: SyncReport) -> None:
    """Activate URS-managed users who have a group and deactivate those who have none."""
    affected_ids = affected_ids | set(
        User.objects.filter(is_urs_managed=True, groups__isnull=True, is_active=True)
        .exclude(pk__in=superuser_ids)
        .values_list("pk", flat=True)
    )
    rows = (
        User.objects.filter(pk__in=affected_ids, is_urs_managed=True)
        .annotate(num_groups=Count("groups"))
        .values_list("pk", "is_active", "num_groups")
    )
    for user_id, is_active, num_groups in sorted(rows):
        if num_groups > 0 and not is_active:
            set_user_active(data=SetUserActiveInput(user_id=user_id, is_active=True))
            report.users_activated += 1
        elif num_groups == 0 and is_active and user_id not in superuser_ids:
            set_user_active(data=SetUserActiveInput(user_id=user_id, is_active=False))
            report.users_deactivated += 1


def _record(urs_group_pk: int, status: str, message: str, now) -> None:
    URSGroup.objects.filter(pk=urs_group_pk).update(
        last_sync_at=now,
        last_sync_status=status,
        last_sync_message=message[:500],
    )
