"""Supported command, query, DTO, and exception entry points for the dashboard feature."""

from .contracts import (
    DashboardBenchDetailDTO,
    DashboardBenchGroupDTO,
    DashboardBenchItemDTO,
    DashboardBenchTypeDTO,
    DashboardBookingDTO,
    DashboardComputingDTO,
    DashboardEquipmentCategoryDTO,
    DashboardEquipmentItemDTO,
    DashboardEquipmentReferenceDTO,
    DashboardLocationDTO,
    DashboardSummaryDTO,
    DashboardUserDTO,
)
from .exceptions import (
    DashboardError,
    DashboardFilterError,
    DashboardResourceNotFound,
)
from .queries import (
    get_dashboard_bench_detail,
    get_dashboard_summary,
    list_dashboard_benches,
)

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
    "DashboardError",
    "DashboardFilterError",
    "DashboardLocationDTO",
    "DashboardResourceNotFound",
    "DashboardSummaryDTO",
    "DashboardUserDTO",
    "get_dashboard_bench_detail",
    "get_dashboard_summary",
    "list_dashboard_benches",
)
