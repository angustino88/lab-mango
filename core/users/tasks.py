from config.celery_app import app as celery_app
from core.users.features.urs_sync.sync_group.service import sync_urs_group
from core.users.models import URSGroup


@celery_app.task()
def scan_urs_group():
    """Celery task: sync all active URS groups with Django groups. Deployed name; do not rename."""
    urs_groups = URSGroup.objects.filter(active=True).select_related("group").order_by("pk")
    sync_urs_group(urs_groups)


@celery_app.task(name="users.urs_sync.sync_selected_groups")
def sync_selected_urs_groups(urs_group_ids: list[int], force: bool = False) -> str:
    """Celery task queued from Django admin for the selected groups; ``force`` skips the safety check."""
    urs_groups = URSGroup.objects.filter(pk__in=urs_group_ids).select_related("group").order_by("pk")
    return sync_urs_group(urs_groups, force=force).summary()
