"""OpenAPI module configuration.

Module ownership is discovered from registered Django feature URL modules.

drf-spectacular discovers choices automatically. Explicit overrides below keep
published component names stable and resolve naming collisions. References
remain strings so settings can import this module before Django loads models.
"""

ENUM_NAME_OVERRIDES: dict[str, str | list[str]] = {
    "AuditResultInputEnum": [
        "PASS",
        "FAIL",
        "NOT_ASSESSED",
        "OK",
        "NOK",
    ],
    "BookingStatusEnum": "core.labs.models.BookingStatus",
    "ComputingActivityStatusEnum": "core.labs.models.ComputingActivityStatus",
    "EquipmentStatusEnum": "core.labs.models.EquipmentStatus",
    "LicenseStatusEnum": "core.labs.models.LicenseStatus",
    "PurchaseStatusEnum": "core.labs.models.procurement.purchase.PurchaseStatus",
    "ResourceAuditResultEnum": "core.labs.models.auditing.resource_audit.ResourceAudit.Result",
    "ResourceTypeEnum": "core.support_desk.contracts.ResourceType.choices",
    "RoomStatusEnum": "core.labs.models.RoomStatus",
    "SourceEnum": "core.support_desk.contracts.TicketSource.choices",
    "StationSlotStatusEnum": "core.labs.models.resource.location.station_slot.StationSlotStatus",
    "SystemStateEnum": "core.support_desk.contracts.SystemState.choices",
    "TicketTypeEnum": "core.support_desk.contracts.TicketType.choices",
    "UrgencyEnum": "core.support_desk.contracts.Urgency.choices",
}
