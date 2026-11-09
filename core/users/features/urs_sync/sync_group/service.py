import json
import logging

import requests
from django.conf import settings
from django.contrib.auth.models import Group
from django.db.models import Count
from django.db.models.functions import Lower

from core.users.models import User
from core.users.public import SetUserActiveInput, set_user_active

logger = logging.getLogger(__name__)


def sync_urs_group(queryset) -> None:
    """Sync URS group membership with Django groups.

    - Adds users in URS API response to the corresponding Django group.
    - Removes users no longer in URS from the group (batch operation).
    - Creates stub accounts for new URS usernames not yet in DB.
    - Deactivates non-superuser URS-managed users with zero groups after sync.
    """
    urs_api_url: str = getattr(settings, "URS_API_URL", "https://rb-pandora-n1.bosch.com:15000/service/info")
    verify_ssl: bool = getattr(settings, "URS_API_VERIFY_SSL", True)
    access_token: str = getattr(settings, "URS_ACCESS_TOKEN", "")
    if not access_token:
        logger.error("URS sync skipped: URS_ACCESS_TOKEN is not configured")
        return
    if not urs_api_url or not urs_api_url.strip():
        logger.error("URS sync skipped: URS_API_URL is not configured")
        return
    desired_memberships: dict[int, set[int]] = {}
    successful_group_ids: set[int] = set()
    new_memberships: dict[int, set[str]] = {}
    groups = list(queryset.select_related("group"))
    for urs_group in groups:
        payload = {
            "serviceId": urs_group.urs_group_id,
            "AccessToken": access_token,
        }
        try:
            response = requests.post(
                url=urs_api_url,
                data=json.dumps(payload),
                headers={"Content-Type": "application/json"},
                verify=verify_ssl,
                timeout=30,
            )
            if response.status_code != 200:
                logger.warning(
                    "URS sync error for group %s: HTTP %s",
                    urs_group.urs_group_name,
                    response.status_code,
                )
                continue

            info = json.loads(response.text).get("Info", {})
            raw_members: list[str] = info.get("UserMembers", [])

            # Parse "apac\\nbo0hc" -> "nbo0hc"
            urs_member_username_set: set[str] = {m.split("\\")[1].lower() for m in raw_members if "\\" in m}

            matching_users = User.objects.annotate(lower_username=Lower("username")).filter(
                lower_username__in=urs_member_username_set, is_urs_managed=True
            )
            urs_member_set: set[User] = set(matching_users)
            persisted_usernames = set(matching_users.values_list("lower_username", flat=True))

            if not urs_group.group:
                continue

            desired_memberships[urs_group.group_id] = {user.pk for user in urs_member_set}
            successful_group_ids.add(urs_group.group_id)

            # Create stub accounts for new usernames not in DB
            # Superusers are locally managed and retain membership regardless of URS.
            desired_memberships[urs_group.group_id].update(
                urs_group.group.user_set.filter(is_superuser=True).values_list("pk", flat=True)
            )
            new_memberships[urs_group.group_id] = urs_member_username_set - persisted_usernames

        except Exception:
            logger.exception("Error syncing URS group %s", urs_group.urs_group_name)

    _apply_desired_memberships(desired_memberships, successful_group_ids, new_memberships)


def _apply_desired_memberships(
    desired_memberships: dict[int, set[int]],
    successful_group_ids: set[int],
    new_memberships: dict[int, set[str]],
) -> None:
    """Apply only successfully fetched group snapshots, then reconcile activity.

    No network I/O occurs here. Membership changes are set-based and each user
    activity transition runs in the users command's short locked transaction.
    """
    if not successful_group_ids:
        return
    groups = Group.objects.filter(pk__in=successful_group_ids).prefetch_related("user_set")
    affected_ids: set[int] = set()
    for group in groups:
        desired = desired_memberships.get(group.pk, set())
        for username in sorted(new_memberships.get(group.pk, set())):
            new_user, created = User.objects.get_or_create(username=username)
            if created:
                # Stub accounts have no Entra binding, so there is no users routing key to publish.
                new_user.set_unusable_password()
                new_user.save(update_fields=("password",))
            desired.add(new_user.pk)
        existing = {user.pk for user in group.user_set.all()}
        remove_ids = existing - desired
        add_ids = desired - existing
        if remove_ids:
            group.user_set.remove(*remove_ids)
            affected_ids.update(remove_ids)
        if add_ids:
            group.user_set.add(*add_ids)
            affected_ids.update(add_ids)

    # Include all URS-managed users affected through the successful memberships,
    # plus eligible orphaned accounts whose final group count is now zero.
    affected_ids.update(
        User.objects.filter(is_urs_managed=True, groups__isnull=True, is_active=True)
        .exclude(is_superuser=True)
        .values_list("pk", flat=True)
    )
    active_by_id = dict(User.objects.filter(pk__in=affected_ids, is_urs_managed=True).values_list("pk", "is_active"))
    group_counts = dict(
        User.objects.filter(pk__in=affected_ids).annotate(num_groups=Count("groups")).values_list("pk", "num_groups")
    )
    for user_id in sorted(affected_ids):
        current_active = active_by_id.get(user_id)
        if current_active is None:
            continue
        has_groups = group_counts.get(user_id, 0) > 0
        if has_groups and not current_active:
            set_user_active(
                data=SetUserActiveInput(user_id=user_id, is_active=True),
            )
        elif not has_groups and current_active:
            is_superuser = User.objects.filter(pk=user_id, is_superuser=True).exists()
            if not is_superuser:
                set_user_active(
                    data=SetUserActiveInput(user_id=user_id, is_active=False),
                )
