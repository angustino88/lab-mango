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
    # Hardware ID kinds (equipment and agent observations): pinned so ``kind`` does not rename KindEnum.
    "EquipmentHardwareIdKindEnum": "core.labs.models.EquipmentHardwareIdKind",
    "EquipmentLifecycleStateEnum": "core.labs.models.EquipmentLifecycleState",
    # Telemetry target / install-location type (core.labs.models.telemetry.target.TelemetryTargetType). The same
    # choice set is published as ``type``, ``target_type`` and ``install_location_type``; pinned so it keeps one name.
    "InstallLocationTypeEnum": "core.labs.models.telemetry.target.TelemetryTargetType",
    "LicenseStatusEnum": "core.labs.models.LicenseStatus",
    # Downtime ``kind`` (planned / unplanned): pinned so other ``kind`` enums do not rename it.
    "KindEnum": "core.labs.models.resource.base.downtime.DowntimeKind",
    # Routing sync change-feed ``mode`` (core/routing/queries/selectors.py): pinned so the workbook import
    # ``mode`` field does not rename it.
    "ModeEnum": ["delta", "reset"],
    "PurchaseStatusEnum": "core.labs.models.procurement.purchase.PurchaseStatus",
    "ResourceAuditResultEnum": "core.labs.models.auditing.resource_audit.ResourceAudit.Result",
    "ResourceTypeEnum": "core.support_desk.contracts.ResourceType.choices",
    # Routing sync change ``op`` (core/routing): pinned so the equipment match ``op`` does not rename it.
    "OpEnum": ["upsert", "delete"],
    # Equipment match requirement ``op``.
    "SpecRequirementOpEnum": "core.labs.features.equipment.api.matching.SPEC_REQUIREMENT_OPS",
    "SourceEnum": "core.support_desk.contracts.TicketSource.choices",
    # Agent identity state is distinct from downtime state.
    "StateEnum": "core.agents.models.agent_identity.AgentIdentity.State",
    "StationSlotStatusEnum": "core.labs.models.resource.location.station_slot.StationSlotStatus",
    "SystemStateEnum": "core.support_desk.contracts.SystemState.choices",
    "TicketTypeEnum": "core.support_desk.contracts.TicketType.choices",
    "UrgencyEnum": "core.support_desk.contracts.Urgency.choices",
    # Workbook import upload ``mode`` (workbook_import/contracts.py MODES): pinned so it does not take the
    # routing-sync ``ModeEnum`` name.
    "WorkbookImportModeEnum": "core.labs.features.workbook_import.contracts.MODE_CHOICES",
}
