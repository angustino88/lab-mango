"""Serializers and query contracts for the laboratory dashboard API."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.pagination import PageNumberQuerySerializer
from core.labs.models import Bench, ComputingActivityStatus


class DashboardQueryFilterSerializer(PageNumberQuerySerializer):
    """Query parameter validation for dashboard bench listing."""

    search = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Case-insensitive text search across bench name, SKU, location, host, and remote user.",
    )
    bench_group = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Filter benches by bench group identifier.",
    )
    lifecycle_status = serializers.ChoiceField(
        choices=Bench.LIFECYCLE_STATUSES,
        required=False,
        help_text="Filter by lifecycle status (planned, in_service, out_of_service, retired).",
    )
    activity_status = serializers.ChoiceField(
        choices=ComputingActivityStatus.choices,
        required=False,
        help_text="Filter by computing activity status (free, active, inactive, offline, maintaining).",
    )
    is_booked = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Filter by whether the bench has an ongoing active booking.",
    )
    is_favorite = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Filter by whether the authenticated user has bookmarked this bench.",
    )
    location = serializers.IntegerField(
        required=False,
        min_value=1,
        help_text="Filter by physical station or room identifier.",
    )
    has_computing = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Filter by whether the bench has active computing equipment assigned.",
    )
    is_mapped = serializers.BooleanField(
        required=False,
        default=None,
        allow_null=True,
        help_text="Filter by whether the bench has a physical location or station mapping.",
    )


class DashboardBenchGroupSerializer(serializers.Serializer):
    """Logical bench group descriptor."""

    id = serializers.IntegerField()
    name = serializers.CharField()
    description = serializers.CharField(allow_blank=True, default="")


class DashboardBenchTypeSerializer(serializers.Serializer):
    """Bench specialization type descriptor."""

    id = serializers.IntegerField()
    name = serializers.CharField()


class DashboardLocationSerializer(serializers.Serializer):
    """Physical location placement details."""

    station_id = serializers.IntegerField(allow_null=True)
    station_name = serializers.CharField(allow_null=True, allow_blank=True)
    room_id = serializers.IntegerField(allow_null=True)
    room_name = serializers.CharField(allow_null=True, allow_blank=True)
    building_name = serializers.CharField(allow_null=True, allow_blank=True)
    slot_label = serializers.CharField(allow_null=True, allow_blank=True)


class DashboardUserSerializer(serializers.Serializer):
    """User summary descriptor for booking ownership and activity."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.CharField(allow_blank=True, default="")


class DashboardBookingSerializer(serializers.Serializer):
    """Booking information descriptor."""

    id = serializers.IntegerField()
    booking_code = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    status = serializers.CharField()
    user = DashboardUserSerializer(allow_null=True)


class DashboardComputingSerializer(serializers.Serializer):
    """Attached computing equipment and real-time remote session state."""

    id = serializers.IntegerField()
    sku = serializers.CharField(allow_blank=True, default="")
    name = serializers.CharField(allow_blank=True, default="")
    ip_address = serializers.CharField(allow_null=True)
    os_name = serializers.CharField(allow_blank=True)
    rdp_file_url = serializers.CharField(allow_null=True)
    activity_status = serializers.CharField()
    remote_user = serializers.CharField(allow_blank=True)
    remote_user_display_name = serializers.CharField(allow_blank=True)
    remote_ip = serializers.CharField(allow_null=True)


class DashboardBookingDetailSerializer(serializers.Serializer):
    """Dashboard detail schedule fields without booking-user identity."""

    id = serializers.IntegerField()
    booking_code = serializers.CharField()
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    status = serializers.CharField()


class DashboardComputingDetailSerializer(serializers.Serializer):
    """Dashboard detail computing summary without remote-access data."""

    id = serializers.IntegerField()
    sku = serializers.CharField(allow_blank=True, default="")
    name = serializers.CharField(allow_blank=True, default="")
    activity_status = serializers.CharField()
    last_agent_report_at = serializers.DateTimeField(allow_null=True)
    is_stale = serializers.BooleanField(allow_null=True)


class DashboardEquipmentReferenceSerializer(serializers.Serializer):
    """Compact standard reference shape for attached equipment and licenses."""

    id = serializers.IntegerField()
    sku = serializers.CharField(allow_blank=True, default="")
    name = serializers.CharField(allow_blank=True, default="")


class DashboardEquipmentCategoryReferenceSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField(allow_blank=True)


class DashboardEquipmentActivitySerializer(serializers.Serializer):
    status = serializers.CharField()
    last_agent_report_at = serializers.DateTimeField(allow_null=True)
    is_stale = serializers.BooleanField(allow_null=True)


def _equipment_activity_summary(equipment: Any) -> dict[str, Any] | None:
    if getattr(equipment, "computing_profile", None) is None:
        return None
    activity = getattr(equipment, "activity", None)
    heartbeat = activity.last_agent_report_at if activity else None
    stale = None if heartbeat is None else heartbeat < timezone.now() - timedelta(minutes=10)
    return {
        "status": activity.status if activity else "offline",
        "last_agent_report_at": heartbeat,
        "is_stale": stale,
    }


class DashboardEquipmentItemSerializer(serializers.Serializer):
    """Assigned equipment resource descriptor."""

    id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    category = serializers.SerializerMethodField()
    role = serializers.CharField()
    position = serializers.IntegerField()
    assigned_at = serializers.DateTimeField()
    computing_activity = serializers.SerializerMethodField()
    licenses = DashboardEquipmentReferenceSerializer(many=True)

    @extend_schema_field(DashboardEquipmentCategoryReferenceSerializer(allow_null=True))
    def get_category(self, obj: Any) -> dict[str, Any] | None:
        if isinstance(obj, dict):
            return obj.get("category")
        category = getattr(getattr(obj, "kind", None), "category", None)
        return {"id": category.pk, "name": category.name} if category else None

    @extend_schema_field(DashboardEquipmentActivitySerializer(allow_null=True))
    def get_computing_activity(self, obj: Any) -> dict[str, Any] | None:
        if isinstance(obj, dict):
            return obj.get("computing_activity")
        return _equipment_activity_summary(obj)


class DashboardEquipmentCategoryGroupSerializer(serializers.Serializer):
    id = serializers.IntegerField(allow_null=True)
    name = serializers.CharField()
    equipment = DashboardEquipmentItemSerializer(many=True)


class DashboardBenchSerializer(serializers.Serializer):
    """Comprehensive representation of a bench item on the operational dashboard."""

    include_remote_details = True

    id = serializers.IntegerField()
    sku = serializers.CharField()
    name = serializers.CharField()
    lifecycle_status = serializers.CharField()
    bench_group = DashboardBenchGroupSerializer(allow_null=True)
    bench_type = DashboardBenchTypeSerializer(allow_null=True)
    location = DashboardLocationSerializer(allow_null=True)
    is_favorite = serializers.BooleanField(default=False)
    current_booking = DashboardBookingSerializer(allow_null=True)
    computing = DashboardComputingSerializer(allow_null=True)
    samples = DashboardEquipmentReferenceSerializer(many=True)
    licenses = DashboardEquipmentReferenceSerializer(many=True)
    assigned_equipment_count = serializers.IntegerField()
    image_url = serializers.CharField(allow_null=True)
    updated_at = serializers.DateTimeField()

    def to_representation(self, instance: Any) -> dict[str, Any]:
        if isinstance(instance, dict):
            return super().to_representation(instance)

        bench_group_data = None
        if instance.bench_group_id:
            group = instance.bench_group
            bench_group_data = {
                "id": group.id,
                "name": group.name,
                "description": group.description or "",
            }

        bench_type_data = None
        if instance.type_id:
            btype = instance.type
            bench_type_data = {
                "id": btype.id,
                "name": btype.name,
            }

        station = getattr(instance, "setup_location", None)
        room = getattr(station, "room", None) if station else None
        building = getattr(room, "building", None) if room else None
        slot = getattr(instance, "station_slot", None)

        location_data = None
        if station or slot:
            location_data = {
                "station_id": station.id if station else None,
                "station_name": station.name if station else None,
                "room_id": room.id if room else None,
                "room_name": room.name if room else None,
                "building_name": building.name if building else None,
                "slot_label": (slot.label or slot.slot_code) if slot else None,
            }

        active_bookings = getattr(instance, "_active_bookings", None)
        current_booking_data = None
        if active_bookings:
            booking = active_bookings[0]
            current_booking_data = {
                "id": booking.id,
                "booking_code": booking.booking_code,
                "starts_at": booking.starts_at,
                "ends_at": booking.ends_at,
                "status": booking.status,
            }
            if self.include_remote_details:
                creator = getattr(booking, "creator", None)
                display_name = (
                    getattr(creator, "display_name", "") or getattr(creator, "username", "") if creator else ""
                )
                current_booking_data["user"] = (
                    {
                        "id": creator.id,
                        "username": creator.username,
                        "display_name": display_name,
                    }
                    if creator
                    else None
                )

        active_assignments = getattr(instance, "_active_equipment_assignments", None)
        computing_data = None
        samples_data: list[dict[str, Any]] = []
        licenses_map: dict[int, dict[str, Any]] = {}

        if active_assignments:
            for assignment in active_assignments:
                equipment = assignment.equipment
                if equipment is None:
                    continue

                # Computing
                computing = getattr(equipment, "computing_profile", None)
                if computing_data is None and computing is not None:
                    activity = getattr(equipment, "activity", None)
                    computing_data = {
                        "id": equipment.id,
                        "sku": equipment.sku or "",
                        "name": equipment.name or "",
                        "activity_status": activity.status if activity else "offline",
                    }
                    if self.include_remote_details:
                        rdp_url = None
                        if computing.rdp_file:
                            request = self.context.get("request")
                            rdp_url = (
                                request.build_absolute_uri(computing.rdp_file.url)
                                if request
                                else computing.rdp_file.url
                            )
                        computing_data.update(
                            {
                                "ip_address": computing.ip_address,
                                "os_name": computing.os_name or "",
                                "rdp_file_url": rdp_url,
                                "remote_user": activity.remote_user if activity else "",
                                "remote_user_display_name": activity.remote_user_display_name if activity else "",
                                "remote_ip": str(activity.remote_ip) if (activity and activity.remote_ip) else None,
                            }
                        )
                    else:
                        heartbeat = activity.last_agent_report_at if activity else None
                        computing_data["last_agent_report_at"] = heartbeat
                        computing_data["is_stale"] = (
                            None if heartbeat is None else heartbeat < timezone.now() - timedelta(minutes=10)
                        )

                # Samples
                kind = getattr(equipment, "kind", None)
                category = getattr(kind, "category", None) if kind else None
                is_sample = bool(
                    category and (category.effective_key == "sample" or category.name.lower() in ("sample", "samples"))
                )

                if is_sample:
                    samples_data.append({
                        "id": equipment.id,
                        "sku": equipment.sku or "",
                        "name": equipment.name or "",
                    })

                # Licenses
                active_lic_assignments = getattr(equipment, "_active_license_assignments", None)
                if active_lic_assignments is None:
                    try:
                        active_lic_assignments = equipment.license_assignments.filter(
                            unassigned_at__isnull=True,
                            license__deleted_at__isnull=True,
                        ).select_related("license")
                    except Exception:
                        active_lic_assignments = []

                for lic_assign in active_lic_assignments:
                    lic = getattr(lic_assign, "license", None)
                    if lic and lic.id not in licenses_map:
                        licenses_map[lic.id] = {
                            "id": lic.id,
                            "sku": lic.sku or "",
                            "name": lic.name or "",
                        }

        equipment_count = getattr(instance, "equipment_count", None)
        if equipment_count is None:
            equipment_count = len(active_assignments) if active_assignments is not None else 0

        image_url = None
        if instance.image:
            request = self.context.get("request")
            image_url = (
                request.build_absolute_uri(instance.image.url)
                if request
                else instance.image.url
            )

        return {
            "id": instance.id,
            "sku": instance.sku,
            "name": instance.name,
            "lifecycle_status": instance.lifecycle_status,
            "bench_group": bench_group_data,
            "bench_type": bench_type_data,
            "location": location_data,
            "is_favorite": bool(getattr(instance, "is_favorite", False)),
            "current_booking": current_booking_data,
            "computing": computing_data,
            "samples": samples_data,
            "licenses": list(licenses_map.values()),
            "assigned_equipment_count": equipment_count,
            "image_url": image_url,
            "updated_at": instance.modified,
        }


class DashboardOperationalSummarySerializer(serializers.Serializer):
    """Aggregate metrics and status distributions for dashboard summary."""

    total_benches = serializers.IntegerField(
        help_text="Total number of active, non-deleted laboratory benches."
    )
    active_bookings_count = serializers.IntegerField(
        help_text="Total number of currently active bench bookings."
    )
    favorited_benches_count = serializers.IntegerField(
        help_text="Number of benches favorited by the current user."
    )
    lifecycle_distribution = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Breakdown of bench counts by lifecycle status.",
    )
    activity_distribution = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Breakdown of computing equipment counts by operational activity status.",
    )
    utilization_rate = serializers.FloatField(
        help_text="Percentage of benches currently reserved or in-progress.",
    )


class DashboardBenchDetailSerializer(DashboardBenchSerializer):
    """Detailed operational bench representation including equipment and upcoming schedule."""

    include_remote_details = False

    current_booking = DashboardBookingDetailSerializer(allow_null=True)
    computing = DashboardComputingDetailSerializer(allow_null=True)
    description = serializers.CharField(allow_blank=True, default="")
    documentation_url = serializers.CharField(allow_blank=True, default="")
    criticality = serializers.CharField(allow_blank=True, default="")
    equipment_by_category = DashboardEquipmentCategoryGroupSerializer(many=True)
    upcoming_bookings = DashboardBookingDetailSerializer(many=True)

    def to_representation(self, instance: Any) -> dict[str, Any]:
        data = super().to_representation(instance)

        data["description"] = getattr(instance, "description", "") or ""
        data["documentation_url"] = getattr(instance, "documentation_url", "") or ""
        data["criticality"] = getattr(instance, "criticality", "") or ""

        equipment_groups: dict[int | None, dict[str, Any]] = {}
        for assignment in getattr(instance, "_active_equipment_assignments", []):
            equipment = assignment.equipment
            if equipment is None:
                continue
            category = getattr(getattr(equipment, "kind", None), "category", None)
            category_id = category.pk if category else None
            group = equipment_groups.setdefault(
                category_id,
                {"id": category_id, "name": category.name if category else "Uncategorized", "equipment": []},
            )
            active_licenses = getattr(equipment, "_active_license_assignments", [])
            group["equipment"].append(
                {
                    "id": equipment.id,
                    "sku": equipment.sku,
                    "name": equipment.name,
                    "category": {"id": category_id, "name": category.name} if category else None,
                    "role": assignment.role,
                    "position": assignment.position,
                    "assigned_at": assignment.assigned_at,
                    "computing_activity": _equipment_activity_summary(equipment),
                    "licenses": [
                        {
                            "id": item.license.id,
                            "sku": item.license.sku or "",
                            "name": item.license.name or "",
                        }
                        for item in active_licenses
                        if item.license is not None
                    ],
                }
            )
        data["equipment_by_category"] = sorted(
            equipment_groups.values(), key=lambda group: (group["name"].casefold(), group["id"] or 0)
        )

        upcoming_list = []
        for booking in getattr(instance, "_upcoming_bookings", []):
            booking_data = {
                "id": booking.id,
                "booking_code": booking.booking_code,
                "starts_at": booking.starts_at,
                "ends_at": booking.ends_at,
                "status": booking.status,
            }
            if self.include_remote_details:
                creator = getattr(booking, "creator", None)
                display_name = (
                    getattr(creator, "display_name", "") or getattr(creator, "username", "") if creator else ""
                )
                booking_data["user"] = (
                    {
                        "id": creator.id,
                        "username": creator.username,
                        "display_name": display_name,
                    }
                    if creator
                    else None
                )
            upcoming_list.append(booking_data)
        data["upcoming_bookings"] = upcoming_list

        return data


__all__ = (
    "DashboardBenchDetailSerializer",
    "DashboardBenchGroupSerializer",
    "DashboardBenchSerializer",
    "DashboardBenchTypeSerializer",
    "DashboardBookingSerializer",
    "DashboardComputingSerializer",
    "DashboardEquipmentItemSerializer",
    "DashboardEquipmentCategoryGroupSerializer",
    "DashboardEquipmentReferenceSerializer",
    "DashboardLocationSerializer",
    "DashboardOperationalSummarySerializer",
    "DashboardQueryFilterSerializer",
    "DashboardUserSerializer",
)
