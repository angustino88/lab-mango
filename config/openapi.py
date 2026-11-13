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
    # Downtime resource types (core.labs.features.downtime.application.targets.RESOURCE_MODELS).
    "DowntimeResourceTypeEnum": ["room", "station", "bench", "equipment"],
    # Downtime window state (core.labs.features.downtime.queries.STATES); keeps the agents StateEnum name.
    "DowntimeStateEnum": ["scheduled", "current", "ended", "cancelled"],
    "EquipmentConditionEnum": "core.labs.models.EquipmentCondition",
    "EquipmentDisplayStatusEnum": "core.labs.models.EquipmentDisplayStatus",
    "EquipmentLifecycleStateEnum": "core.labs.models.EquipmentLifecycleState",
    "LicenseStatusEnum": "core.labs.models.LicenseStatus",
    "PurchaseStatusEnum": "core.labs.models.procurement.purchase.PurchaseStatus",
    "ResourceAuditResultEnum": "core.labs.models.auditing.resource_audit.ResourceAudit.Result",
    "ResourceTypeEnum": "core.support_desk.contracts.ResourceType.choices",
    "RoomStatusEnum": "core.labs.models.RoomStatus",
    "SourceEnum": "core.support_desk.contracts.TicketSource.choices",
    # Deprecated station slot ``status`` input values (stations/api/serializers.py LEGACY_SLOT_STATUS).
    "LegacyStationSlotStatusEnum": [
        "available",
        "in_service",
        "maintenance",
        "occupied",
        "out_of_service",
        "reserved",
        "retired",
    ],
    # Agent identity state: pinned so the downtime "state" field does not rename it.
    "StateEnum": "core.agents.models.agent_identity.AgentIdentity.State",
    "StationSlotStatusEnum": "core.labs.models.resource.location.station_slot.StationSlotStatus",
    "SystemStateEnum": "core.support_desk.contracts.SystemState.choices",
    "TicketTypeEnum": "core.support_desk.contracts.TicketType.choices",
    "UrgencyEnum": "core.support_desk.contracts.Urgency.choices",
}
