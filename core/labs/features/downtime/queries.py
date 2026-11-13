"""Read-only downtime selectors."""

from django.db.models import QuerySet
from django.utils import timezone

from core.labs.models import ResourceDowntime

from .application.targets import RESOURCE_MODELS

STATES = ("scheduled", "current", "ended", "cancelled")
_MODEL_TYPES = {model._meta.model_name: name for name, model in RESOURCE_MODELS.items()}


def resource_type_of(window: ResourceDowntime) -> str:
    """The API resource type (``room``, ``station``, ``bench``, ``equipment``) of a window's link."""
    return _MODEL_TYPES.get(window.resource_content_type.model, window.resource_content_type.model)


def state_of(window: ResourceDowntime) -> str:
    now = timezone.now()
    if window.cancelled_at is not None:
        return "cancelled"
    if window.starts_at > now:
        return "scheduled"
    if window.ends_at is not None and window.ends_at <= now:
        return "ended"
    return "current"


def list_downtimes(*, resource_type=None, resource_id=None, state=None) -> QuerySet[ResourceDowntime]:
    queryset = ResourceDowntime.objects.get_queryset().select_related("resource_content_type", "creator", "ended_by")
    if resource_type is not None:
        model = RESOURCE_MODELS[resource_type]
        queryset = queryset.filter(
            resource_content_type__app_label=model._meta.app_label,
            resource_content_type__model=model._meta.model_name,
        )
        if resource_id is not None:
            queryset = queryset.filter(resource_object_id=str(resource_id))
    now = timezone.now()
    if state == "cancelled":
        queryset = queryset.filter(cancelled_at__isnull=False)
    elif state == "scheduled":
        queryset = queryset.not_cancelled().filter(starts_at__gt=now)
    elif state == "current":
        queryset = queryset.current(now)
    elif state == "ended":
        queryset = queryset.not_cancelled().filter(ends_at__lte=now)
    return queryset.order_by("-starts_at", "-pk")


def get_downtime(*, downtime_id: int) -> ResourceDowntime:
    return list_downtimes().get(pk=downtime_id)


__all__ = ["STATES", "get_downtime", "list_downtimes", "resource_type_of", "state_of"]
