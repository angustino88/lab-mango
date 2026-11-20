"""Read-only selectors for device profiles and metric definitions."""

from django.db.models import Count, Q, QuerySet

from core.labs.models.telemetry import DeviceProfile, MetricDefinition


def list_device_profiles(*, key=None, status=None, protocol=None, search=None) -> QuerySet[DeviceProfile]:
    queryset = DeviceProfile.objects.select_related("creator", "last_modified_by").annotate(
        channel_count=Count("modbus_channels", distinct=True)
    )
    if key:
        queryset = queryset.filter(key=key)
    if status:
        queryset = queryset.filter(status=status)
    if protocol:
        queryset = queryset.filter(protocol=protocol)
    if search:
        term = search.strip()
        queryset = queryset.filter(Q(key__icontains=term) | Q(model__icontains=term) | Q(manufacturer__icontains=term))
    return queryset.order_by("key", "-version")


def get_device_profile(*, profile_id: int) -> DeviceProfile:
    return list_device_profiles().get(pk=profile_id)


def list_metrics() -> QuerySet[MetricDefinition]:
    return MetricDefinition.objects.filter(is_active=True).order_by("key")


__all__ = ["get_device_profile", "list_device_profiles", "list_metrics"]
