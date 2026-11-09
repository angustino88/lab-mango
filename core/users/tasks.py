
from config.celery_app import app as celery_app
from core.users.features.urs_sync.sync_group.service import sync_urs_group
from core.users.models import URSGroup


@celery_app.task()
def scan_urs_group():
    """Celery task: sync all active URS groups with Django groups."""
    urs_groups = URSGroup.objects.filter(active=True)
    sync_urs_group(urs_groups)
