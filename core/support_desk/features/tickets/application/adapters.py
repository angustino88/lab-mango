"""Resource adapters for Lab Mango traceable entities."""

from typing import Any

from core.support_desk.contracts import ResourceAdapter, ResourceChangeBadge, ResourceReferenceDTO, ResourceType
from core.support_desk.exceptions import ResourceNotFoundError
from core.support_desk.models.resource_link import TicketResourceLink


class RoomAdapter:
    """Adapter for Room resources."""

    resource_type = ResourceType.ROOM.value

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        try:
            from core.labs.features.locations.public import get_room

            room = get_room(room_id=int(resource_id))
            if not room:
                return None
            name = getattr(room, "name", "")
            code = getattr(room, "code", name)
            location = getattr(room, "location", None)
            location_name = getattr(location, "name", "") if location else ""
            return ResourceReferenceDTO(
                resource_type=self.resource_type,
                resource_id=str(resource_id),
                name=name,
                code=code,
                parent_context=f"Location: {location_name}" if location_name else "",
                detail_url=f"/labs/rooms/{resource_id}",
                is_active=getattr(room, "is_active", True),
            )
        except Exception:
            return None

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        if not user or not user.is_authenticated:
            return False
        return self.get_reference(resource_id) is not None

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        from core.labs.features.locations.public import list_rooms

        results = []
        rooms = list_rooms().filter(name__icontains=query)[:20]
        for room in rooms:
            ref = self.get_reference(room.pk)
            if ref and self.can_view(room.pk, user):
                results.append(ref)
        return results

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        ref = self.get_reference(resource_id)
        if not ref:
            raise ResourceNotFoundError(f"Room with id {resource_id} not found.")
        return {
            "name": ref.name,
            "code": ref.code,
            "parent_context": ref.parent_context,
            "detail_url": ref.detail_url,
        }


class StationAdapter:
    """Adapter for Station resources."""

    resource_type = ResourceType.STATION.value

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        try:
            from core.labs.features.locations.public import get_station

            station = get_station(station_id=int(resource_id))
            if not station:
                return None
            name = getattr(station, "name", "")
            code = getattr(station, "code", name)
            room = getattr(station, "room", None)
            room_name = getattr(room, "name", "") if room else ""
            return ResourceReferenceDTO(
                resource_type=self.resource_type,
                resource_id=str(resource_id),
                name=name,
                code=code,
                parent_context=f"Room: {room_name}" if room_name else "",
                detail_url=f"/labs/stations/{resource_id}",
                is_active=getattr(station, "is_active", True),
            )
        except Exception:
            return None

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        if not user or not user.is_authenticated:
            return False
        return self.get_reference(resource_id) is not None

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        from core.labs.features.locations.public import list_stations

        results = []
        stations = list_stations().filter(name__icontains=query)[:20]
        for station in stations:
            ref = self.get_reference(station.pk)
            if ref and self.can_view(station.pk, user):
                results.append(ref)
        return results

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        ref = self.get_reference(resource_id)
        if not ref:
            raise ResourceNotFoundError(f"Station with id {resource_id} not found.")
        return {
            "name": ref.name,
            "code": ref.code,
            "parent_context": ref.parent_context,
            "detail_url": ref.detail_url,
        }


class BenchAdapter:
    """Adapter for Bench resources."""

    resource_type = ResourceType.BENCH.value

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        try:
            from core.labs.features.benches.public import get_bench

            bench = get_bench(bench_id=int(resource_id))
            if not bench:
                return None
            name = getattr(bench, "name", "")
            sku = getattr(bench, "sku", name)
            station = getattr(bench, "station", None)
            station_name = getattr(station, "name", "") if station else ""
            room = getattr(station, "room", None) if station else None
            room_name = getattr(room, "name", "") if room else ""
            parent = []
            if station_name:
                parent.append(f"Station: {station_name}")
            if room_name:
                parent.append(f"Room: {room_name}")

            return ResourceReferenceDTO(
                resource_type=self.resource_type,
                resource_id=str(resource_id),
                name=name,
                code=sku,
                parent_context=", ".join(parent),
                detail_url=f"/labs/benches/{resource_id}",
                is_active=not getattr(bench, "is_delete", False),
            )
        except Exception:
            return None

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        if not user or not user.is_authenticated:
            return False
        return self.get_reference(resource_id) is not None

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        from core.labs.features.benches.public import list_benches

        results = []
        benches = list_benches().filter(name__icontains=query)[:20]
        for bench in benches:
            ref = self.get_reference(bench.pk)
            if ref and self.can_view(bench.pk, user):
                results.append(ref)
        return results

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        ref = self.get_reference(resource_id)
        if not ref:
            raise ResourceNotFoundError(f"Bench with id {resource_id} not found.")
        return {
            "name": ref.name,
            "code": ref.code,
            "parent_context": ref.parent_context,
            "detail_url": ref.detail_url,
        }


class EquipmentAdapter:
    """Adapter for Equipment resources."""

    resource_type = ResourceType.EQUIPMENT.value

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        try:
            from core.labs.features.equipment.public import list_equipment

            eq = list_equipment().filter(pk=int(resource_id)).first()
            if not eq:
                return None
            name = getattr(eq, "name", "")
            sku = getattr(eq, "sku", name)
            bench = getattr(eq, "bench", None)
            bench_name = getattr(bench, "name", "") if bench else ""
            return ResourceReferenceDTO(
                resource_type=self.resource_type,
                resource_id=str(resource_id),
                name=name,
                code=sku,
                parent_context=f"Bench: {bench_name}" if bench_name else "",
                detail_url=f"/labs/equipment/{resource_id}",
                is_active=not getattr(eq, "is_delete", False),
            )
        except Exception:
            return None

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        if not user or not user.is_authenticated:
            return False
        return self.get_reference(resource_id) is not None

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        from core.labs.features.equipment.public import list_equipment

        results = []
        items = list_equipment().filter(name__icontains=query)[:20]
        for eq in items:
            ref = self.get_reference(eq.pk)
            if ref and self.can_view(eq.pk, user):
                results.append(ref)
        return results

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        ref = self.get_reference(resource_id)
        if not ref:
            raise ResourceNotFoundError(f"Equipment with id {resource_id} not found.")
        return {
            "name": ref.name,
            "code": ref.code,
            "parent_context": ref.parent_context,
            "detail_url": ref.detail_url,
        }


class LicenseAdapter:
    """Adapter for License resources."""

    resource_type = ResourceType.LICENSE.value

    def get_reference(self, resource_id: str | int) -> ResourceReferenceDTO | None:
        try:
            from core.labs.features.licenses.public import get_license

            lic = get_license(license_id=int(resource_id))
            if not lic:
                return None
            name = getattr(lic, "software_name", getattr(lic, "name", ""))
            sku = getattr(lic, "sku", "")
            vendor = getattr(lic, "vendor", "")
            return ResourceReferenceDTO(
                resource_type=self.resource_type,
                resource_id=str(resource_id),
                name=name,
                code=sku,
                parent_context=f"Vendor: {vendor}" if vendor else "",
                detail_url=f"/labs/licenses/{resource_id}",
                is_active=not getattr(lic, "is_delete", False),
            )
        except Exception:
            return None

    def can_view(self, resource_id: str | int, user: Any) -> bool:
        if not user or not user.is_authenticated:
            return False
        return self.get_reference(resource_id) is not None

    def search(self, query: str, user: Any) -> list[ResourceReferenceDTO]:
        from core.labs.features.licenses.public import list_licenses

        results = []
        licenses = list_licenses().filter(software_name__icontains=query)[:20]
        for lic in licenses:
            ref = self.get_reference(lic.pk)
            if ref and self.can_view(lic.pk, user):
                results.append(ref)
        return results

    def snapshot(self, resource_id: str | int) -> dict[str, Any]:
        ref = self.get_reference(resource_id)
        if not ref:
            raise ResourceNotFoundError(f"License with id {resource_id} not found.")
        return {
            "name": ref.name,
            "code": ref.code,
            "parent_context": ref.parent_context,
            "detail_url": ref.detail_url,
        }


_ADAPTERS: dict[str, ResourceAdapter] = {
    ResourceType.ROOM.value: RoomAdapter(),
    ResourceType.STATION.value: StationAdapter(),
    ResourceType.BENCH.value: BenchAdapter(),
    ResourceType.EQUIPMENT.value: EquipmentAdapter(),
    ResourceType.LICENSE.value: LicenseAdapter(),
}


def get_adapter(resource_type: str) -> ResourceAdapter:
    """Lookup registered resource adapter by type."""
    adapter = _ADAPTERS.get(resource_type)
    if adapter is None:
        raise ResourceNotFoundError(f"No adapter registered for resource type '{resource_type}'.")
    return adapter


def compute_resource_badge(
    link: TicketResourceLink,
    live_ref: ResourceReferenceDTO | None,
) -> ResourceChangeBadge:
    """Determine the badge indicating how the live resource compares to snapshot."""
    if not link.is_active:
        return ResourceChangeBadge.UNLINKED
    if live_ref is None:
        return ResourceChangeBadge.DELETED
    if not live_ref.is_active:
        return ResourceChangeBadge.ARCHIVED
    snapshot = link.snapshot or {}
    if live_ref.name and snapshot.get("name") and live_ref.name != snapshot.get("name"):
        return ResourceChangeBadge.RENAMED
    if (
        live_ref.parent_context
        and snapshot.get("parent_context")
        and live_ref.parent_context != snapshot.get("parent_context")
    ):
        return ResourceChangeBadge.MOVED
    return ResourceChangeBadge.NONE
