"""Neutral DTOs and data shapes for the laboratory dashboard domain."""

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class DashboardBenchGroupDTO:
    id: int
    name: str
    description: str


@dataclass(frozen=True)
class DashboardBenchTypeDTO:
    id: int
    name: str


@dataclass(frozen=True)
class DashboardLocationDTO:
    station_id: int | None
    station_name: str | None
    room_id: int | None
    room_name: str | None
    building_name: str | None
    slot_label: str | None


@dataclass(frozen=True)
class DashboardUserDTO:
    id: int
    username: str
    display_name: str


@dataclass(frozen=True)
class DashboardBookingDTO:
    id: int
    booking_code: str
    starts_at: datetime
    ends_at: datetime
    status: str
    user: DashboardUserDTO | None


@dataclass(frozen=True)
class DashboardEquipmentReferenceDTO:
    id: int
    sku: str
    name: str


@dataclass(frozen=True)
class DashboardComputingDTO:
    id: int
    ip_address: str | None
    os_name: str
    rdp_file_url: str | None
    activity_status: str
    remote_user: str
    remote_user_display_name: str
    remote_ip: str | None
    sku: str = ""
    name: str = ""


@dataclass(frozen=True)
class DashboardEquipmentItemDTO:
    id: int
    sku: str
    name: str
    category: dict[str, int | str] | None
    role: str
    position: int
    assigned_at: datetime
    computing_activity: dict[str, object] | None
    licenses: list[DashboardEquipmentReferenceDTO] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardEquipmentCategoryDTO:
    id: int | None
    name: str
    equipment: list[DashboardEquipmentItemDTO]


@dataclass(frozen=True)
class DashboardBenchItemDTO:
    id: int
    sku: str
    name: str
    lifecycle_status: str
    bench_group: DashboardBenchGroupDTO | None
    bench_type: DashboardBenchTypeDTO | None
    location: DashboardLocationDTO | None
    is_favorite: bool
    current_booking: DashboardBookingDTO | None
    computing: DashboardComputingDTO | None
    assigned_equipment_count: int
    image_url: str | None
    updated_at: datetime
    samples: list[DashboardEquipmentReferenceDTO] = field(default_factory=list)
    licenses: list[DashboardEquipmentReferenceDTO] = field(default_factory=list)


@dataclass(frozen=True)
class DashboardSummaryDTO:
    total_benches: int
    active_bookings_count: int
    favorited_benches_count: int
    lifecycle_distribution: dict[str, int]
    activity_distribution: dict[str, int]
    utilization_rate: float


@dataclass(frozen=True)
class DashboardBenchDetailDTO:
    id: int
    sku: str
    name: str
    lifecycle_status: str
    bench_group: DashboardBenchGroupDTO | None
    bench_type: DashboardBenchTypeDTO | None
    location: DashboardLocationDTO | None
    is_favorite: bool
    current_booking: DashboardBookingDTO | None
    computing: DashboardComputingDTO | None
    assigned_equipment_count: int
    image_url: str | None
    updated_at: datetime
    description: str
    documentation_url: str
    criticality: str
    equipment_by_category: list[DashboardEquipmentCategoryDTO]
    upcoming_bookings: list[DashboardBookingDTO]
    samples: list[DashboardEquipmentReferenceDTO] = field(default_factory=list)
    licenses: list[DashboardEquipmentReferenceDTO] = field(default_factory=list)


__all__ = (
    "DashboardBenchDetailDTO",
    "DashboardBenchGroupDTO",
    "DashboardBenchItemDTO",
    "DashboardBenchTypeDTO",
    "DashboardBookingDTO",
    "DashboardComputingDTO",
    "DashboardEquipmentItemDTO",
    "DashboardEquipmentCategoryDTO",
    "DashboardEquipmentReferenceDTO",
    "DashboardLocationDTO",
    "DashboardSummaryDTO",
    "DashboardUserDTO",
)
