"""Declared sheets and columns of the data workbook (template v2).

One declaration drives both the downloadable template and the importer, so the two cannot drift.
Column names of the v1 data-collection template are accepted as aliases, so files filled in with it
still import. Sheets are listed in import order: references, then spaces, then equipment.
"""

from __future__ import annotations

from dataclasses import dataclass

TEMPLATE_VERSION = "2.0"
FIRST_DATA_ROW = 4
HEADER_ROW = 2
MAX_DATA_ROWS = 5000

TEXT = "text"
INT = "int"
DECIMAL = "decimal"
BOOL = "bool"
DATE = "date"
URL = "url"
UTILITIES = "utilities"
CHOICE = "choice"

# Hidden "Lists" sheet: one column per choice list, values from row 2.
LISTS_SHEET = "Lists"
CHOICE_LISTS: dict[str, tuple[str, ...]] = {
    "lifecycle": ("Planned", "In service", "Retired"),
    "space_lifecycle": ("In service", "Retired"),
    "equipment_lifecycle": ("Planned", "In service"),
    "access": ("Open", "Restricted"),
    "condition": ("Operational", "In maintenance", "Out of service"),
    "slot_status": ("In service", "Out of service", "Retired"),
    "yes_no": ("Yes", "No"),
}
CHOICE_VALUES: dict[str, dict[str, str]] = {
    "lifecycle": {"planned": "planned", "in service": "in_service", "retired": "retired"},
    "space_lifecycle": {"in service": "in_service", "retired": "retired"},
    "equipment_lifecycle": {"planned": "planned", "in service": "in_service"},
    "access": {"open": "open", "restricted": "restricted"},
    "condition": {
        "operational": "operational",
        "in maintenance": "in_maintenance",
        "out of service": "out_of_service",
    },
    "slot_status": {"in service": "in_service", "out of service": "out_of_service", "retired": "retired"},
}


def list_range(list_key: str) -> str:
    column = list(CHOICE_LISTS).index(list_key)
    letter = chr(ord("A") + column)
    return f"{LISTS_SHEET}!${letter}$2:${letter}${len(CHOICE_LISTS[list_key]) + 1}"


def sheet_range(sheet: str, column: str = "A") -> str:
    return f"'{sheet}'!${column}${FIRST_DATA_ROW}:${column}${FIRST_DATA_ROW + MAX_DATA_ROWS - 1}"


@dataclass(frozen=True, slots=True)
class Column:
    key: str
    header: str
    kind: str = TEXT
    required: bool = False
    hint: str = ""
    choices: str | None = None  # dropdown range (reference sheet column or Lists column)
    choice_list: str | None = None  # CHOICE: key in CHOICE_VALUES
    aliases: tuple[str, ...] = ()
    width: int = 18
    max_length: int | None = None
    # Read by the importer but only for the v1 template (not written to the v2 template).
    legacy: bool = False


@dataclass(frozen=True, slots=True)
class Sheet:
    key: str
    name: str
    group: str
    description: str
    columns: tuple[Column, ...]
    aliases: tuple[str, ...] = ()
    # Shown in the template for dropdowns and reference, never written by the importer.
    read_only: bool = False
    # Detail sheet of an equipment category (category key), merged into the Equipment rows.
    detail_category: str | None = None


def _yes_no(key: str, header: str, hint: str = "Yes or No") -> Column:
    return Column(key, header, BOOL, hint=hint, choices=list_range("yes_no"), width=10)


def _numbered(key: str, header: str, count: int, choices: str | None, hint: str) -> tuple[Column, ...]:
    return tuple(
        Column(
            key,
            f"{header} {n}",
            hint=hint if n == 1 else "Optional",
            choices=choices,
            aliases=(header,) if n == 1 else (),
        )
        for n in range(1, count + 1)
    )


_SKU = Column(
    "sku", "Asset Tag", required=True, hint="Unique code (SKU)", aliases=("Asset Tag (SKU)",), max_length=255, width=20
)
_NAME = Column("name", "Name", hint="Display name", max_length=255, width=24)
_DEPARTMENT = Column("department", "Department", hint="Pick from Departments", choices=sheet_range("Departments"))
_GROUP = Column("group", "Group", hint="Pick from Groups", choices=sheet_range("Groups"))
_OWNER = Column("owner", "Owner ID", hint="User ID (login name), pick from Users", choices=sheet_range("Users"))
_REMARK = Column("remark", "Remarks", hint="Short note, max 255", max_length=255, width=24)
_ACTIVE = _yes_no("active", "Active", "Yes or No (default Yes)")
_LIFECYCLE = Column(
    "lifecycle_status",
    "Lifecycle",
    CHOICE,
    hint="Planned, In service (default) or Retired",
    choices=list_range("lifecycle"),
    choice_list="lifecycle",
)
_SPACE_LIFECYCLE = Column(
    "lifecycle_status",
    "Lifecycle",
    CHOICE,
    hint="In service (default) or Retired",
    choices=list_range("space_lifecycle"),
    choice_list="space_lifecycle",
)
_ACCESS = Column(
    "access_policy",
    "Access",
    CHOICE,
    hint="Open (default) or Restricted",
    choices=list_range("access"),
    choice_list="access",
)
_CONDITION = Column(
    "condition",
    "Condition",
    CHOICE,
    hint="Operational (default). In maintenance / Out of service open a downtime from now",
    choices=list_range("condition"),
    choice_list="condition",
)
_LEGACY_STATUS = Column("legacy_status", "Status", legacy=True)
_INTERFACES = _numbered("interfaces", "Interface", 4, sheet_range("Lookups", "A"), "Pick from Lookups > Interfaces")
_DIMENSIONS = (
    Column("length_mm", "Length (mm)", INT),
    Column("width_mm", "Width (mm)", INT),
    Column("height_mm", "Height (mm)", INT),
    Column("material", "Material", hint="Pick from Lookups > Materials", choices=sheet_range("Lookups", "B")),
)
_DETAIL_SKU = Column(
    "sku",
    "Asset Tag",
    required=True,
    hint="Asset tag of a row in Equipment with this category",
    choices=sheet_range("Equipment"),
    width=20,
)
# v1 detail sheets repeat these from Equipment with formulas; they are read and ignored.
_DETAIL_AUTO = (
    Column("_auto_name", "Name", legacy=True),
    Column("_auto_manufacturer", "Manufacturer", legacy=True),
    Column("_auto_model", "Product Model", legacy=True),
)

SHEETS: tuple[Sheet, ...] = (
    # ---- A. Reference data ------------------------------------------------------------------
    Sheet(
        "users",
        "Users",
        "A Reference",
        "Users who can be picked as owner. Filled from the system; not imported",
        (Column("username", "User ID", required=True, hint="Login name"), Column("full_name", "Full Name")),
        read_only=True,
    ),
    Sheet(
        "departments",
        "Departments",
        "A Reference",
        "Organisation departments",
        (
            Column("name", "Name", required=True, hint="Unique", max_length=255),
            Column("description", "Description"),
            _ACTIVE,
        ),
    ),
    Sheet(
        "groups",
        "Groups",
        "A Reference",
        "Teams inside a department",
        (
            Column("name", "Name", required=True, hint="Unique", max_length=255),
            Column("department", "Department", hint="Pick from Departments", choices=sheet_range("Departments")),
            Column("description", "Description"),
            _ACTIVE,
        ),
    ),
    Sheet(
        "countries",
        "Countries",
        "A Reference",
        "Countries used by rooms",
        (
            Column("code", "Code", required=True, hint="Short code, e.g. DE", max_length=10),
            Column("name", "Name", required=True, max_length=100),
        ),
    ),
    Sheet(
        "cities",
        "Cities",
        "A Reference",
        "Cities and their country",
        (
            Column("name", "City", required=True, max_length=100),
            Column(
                "country",
                "Country",
                hint="Country name or code, pick from Countries",
                choices=sheet_range("Countries", "B"),
            ),
        ),
    ),
    Sheet(
        "buildings",
        "Buildings",
        "A Reference",
        "Buildings and their city",
        (
            Column("name", "Building", required=True, max_length=100),
            Column("city", "City", hint="Pick from Cities", choices=sheet_range("Cities")),
            Column("address", "Address", max_length=255),
        ),
    ),
    Sheet(
        "station_types",
        "Station Types",
        "A Reference",
        "Kinds of station (rack, table ...)",
        (Column("name", "Name", required=True, max_length=255),),
    ),
    Sheet(
        "bench_groups",
        "Bench Groups",
        "A Reference",
        "What a bench is used for (radar, video ...)",
        (Column("name", "Name", required=True, max_length=255), Column("description", "Description"), _ACTIVE),
    ),
    Sheet(
        "bench_types",
        "Bench Types",
        "A Reference",
        "Kinds of bench setup",
        (Column("name", "Name", required=True, max_length=255), Column("description", "Description"), _ACTIVE),
    ),
    Sheet(
        "screen_sizes",
        "Screen Sizes",
        "A Reference",
        "Monitor sizes",
        (
            Column("size", "Label", required=True, hint='Shown in the dropdown, e.g. 27"', max_length=255),
            Column("diagonal_in", "Diagonal (inch)", DECIMAL),
        ),
    ),
    Sheet(
        "resolutions",
        "Resolutions",
        "A Reference",
        "Monitor resolutions",
        (
            Column("resolution", "Label", required=True, hint="e.g. QHD", max_length=255),
            Column("width_px", "Width (px)", INT),
            Column("height_px", "Height (px)", INT),
        ),
    ),
    Sheet(
        "lookups",
        "Lookups",
        "A Reference",
        "Simple name lists: one column per list, one value per row",
        (
            Column("interfaces", "Interfaces", max_length=255),
            Column("materials", "Materials", max_length=255),
            Column("protocols", "Network Protocols", hint="Max 25 characters", max_length=25),
            Column("customers", "Customers", max_length=255),
            Column("characteristics", "Characteristics", max_length=255),
            Column("technical_users", "Technical Users", hint="Computer login used for remote access", max_length=255),
            Column("station_types", "Station Types", legacy=True, max_length=255),
        ),
    ),
    Sheet(
        "equipment_categories",
        "Equipment Categories",
        "A Reference",
        "The fixed category list (provided by the system; not imported). Detail Sheet holds the category fields",
        (Column("name", "Name", required=True), Column("key", "Code"), Column("detail_sheet", "Detail Sheet")),
        read_only=True,
    ),
    Sheet(
        "equipment_kinds",
        "Equipment Kinds",
        "A Reference",
        "Second level of the equipment tree",
        (
            Column(
                "category",
                "Category",
                required=True,
                hint="Pick from Equipment Categories",
                choices=sheet_range("Equipment Categories"),
            ),
            Column("name", "Name", required=True, max_length=120),
            _ACTIVE,
        ),
    ),
    Sheet(
        "equipment_types",
        "Equipment Types",
        "A Reference",
        "Third level, belongs to a kind",
        (
            Column(
                "category",
                "Category",
                hint="Needed only when the kind name exists in several categories",
                choices=sheet_range("Equipment Categories"),
            ),
            Column(
                "kind",
                "Kind",
                required=True,
                hint="Pick from Equipment Kinds",
                choices=sheet_range("Equipment Kinds", "B"),
            ),
            Column("name", "Name", required=True, max_length=120),
            _ACTIVE,
        ),
    ),
    Sheet(
        "manufacturers",
        "Manufacturers",
        "A Reference",
        "Manufacturers and the categories they supply",
        (
            Column("name", "Name", required=True, max_length=120),
            *(
                Column(
                    "categories",
                    f"Category {n}",
                    hint="Pick from Equipment Categories" if n == 1 else "Optional",
                    choices=sheet_range("Equipment Categories"),
                )
                for n in (1, 2, 3)
            ),
            _ACTIVE,
        ),
    ),
    Sheet(
        "product_models",
        "Product Models",
        "A Reference",
        "Models of a manufacturer",
        (
            Column(
                "manufacturer",
                "Manufacturer",
                required=True,
                hint="Pick from Manufacturers",
                choices=sheet_range("Manufacturers"),
            ),
            Column(
                "kind",
                "Kind",
                hint="Needed only when the type name exists under several kinds",
                choices=sheet_range("Equipment Kinds", "B"),
            ),
            Column(
                "equipment_type",
                "Equipment Type",
                required=True,
                hint="Pick from Equipment Types",
                choices=sheet_range("Equipment Types", "C"),
            ),
            Column("name", "Model Name", required=True, max_length=120),
            _ACTIVE,
            Column("default_power_draw_w", "Default Power Draw (W)", INT, hint="Copied to new units of this model"),
            Column("default_weight_kg", "Default Weight (kg)", DECIMAL, hint="Copied to new units of this model"),
        ),
    ),
    # ---- B. Spaces --------------------------------------------------------------------------
    Sheet(
        "rooms",
        "Rooms",
        "B Spaces",
        "Rooms and labs",
        (
            _SKU,
            _NAME,
            Column("label", "Short Label", hint="e.g. A101"),
            _DEPARTMENT,
            _GROUP,
            _OWNER,
            Column("country", "Country", hint="Pick from Countries", choices=sheet_range("Countries", "B")),
            Column("city", "City", hint="Pick from Cities", choices=sheet_range("Cities")),
            Column("building", "Building", hint="Pick from Buildings", choices=sheet_range("Buildings")),
            Column("floor", "Floor", hint="e.g. 1 or B1", max_length=50),
            Column("length_m", "Length (m)", DECIMAL),
            Column("width_m", "Width (m)", DECIMAL),
            Column("usable_height_m", "Usable Height (m)", DECIMAL),
            Column("layout_rows", "Grid Rows", INT, hint="Slot rows; with Grid Columns the room slots are created"),
            Column("layout_columns", "Grid Columns", INT, hint="Slot columns"),
            Column("floor_plan_revision", "Floor Plan Revision", max_length=64),
            Column("floor_plan_url", "Floor Plan Link", URL),
            Column("map_url", "Map Link", URL),
            Column("max_occupancy", "Max Occupancy (people)", INT),
            Column("power_capacity_w", "Power Capacity (W)", INT),
            Column("cooling_capacity_w", "Cooling Capacity (W)", INT),
            Column("network_port_capacity", "Network Ports", INT),
            Column("utilities", "Utilities", UTILITIES, hint="Separate by commas; name=value for amounts"),
            _SPACE_LIFECYCLE,
            _ACCESS,
            _CONDITION,
            _REMARK,
        ),
    ),
    Sheet(
        "stations",
        "Stations",
        "B Spaces",
        "Stations and racks",
        (
            _SKU,
            _NAME,
            Column("label", "Short Label", hint="e.g. R1C1"),
            _DEPARTMENT,
            _GROUP,
            _OWNER,
            Column("type", "Station Type", hint="Pick from Station Types", choices=sheet_range("Station Types")),
            Column("room", "Room Asset Tag", hint="Pick from Rooms", choices=sheet_range("Rooms")),
            Column("slot", "Room Slot Code", hint="Room slot code, e.g. R1C2 (from the room grid)"),
            Column("position_x", "Position X (mm)", DECIMAL),
            Column("position_y", "Position Y (mm)", DECIMAL),
            Column("position_z", "Position Z (mm)", DECIMAL),
            Column("height_mm", "Height (mm)", INT),
            Column("width_mm", "Width (mm)", INT),
            Column("depth_mm", "Depth (mm)", INT),
            Column("orientation_degrees", "Rotation (degrees)", INT, hint="0 to 359"),
            Column("max_load_kg", "Max Load (kg)", INT),
            Column("bench_capacity", "Bench Capacity", INT),
            Column("max_concurrent_users", "Max Users", INT),
            Column("usable_surface_mm2", "Usable Surface (mm²)", INT),
            Column("power_capacity_w", "Power Capacity (W)", INT),
            Column("power_reserved_w", "Power Reserved (W)", INT),
            Column("cooling_capacity_w", "Cooling Capacity (W)", INT),
            Column("network_port_capacity", "Network Ports", INT),
            Column("utilities", "Utilities", UTILITIES, hint="Separate by commas; name=value for amounts"),
            Column("safety_classification", "Safety Class", max_length=64),
            _SPACE_LIFECYCLE,
            _ACCESS,
            _CONDITION,
            _REMARK,
        ),
    ),
    Sheet(
        "station_slots",
        "Station Slots",
        "B Spaces",
        "Bench positions inside a station",
        (
            Column(
                "station",
                "Station Asset Tag",
                required=True,
                hint="Pick from Stations",
                choices=sheet_range("Stations"),
            ),
            Column(
                "position_index",
                "Position No.",
                INT,
                required=True,
                hint="0 = first; lower than the station's Bench Capacity",
                aliases=("Position No. (starts at 0)",),
            ),
            Column("slot_code", "Slot Code", required=True, hint="Max 32", max_length=32),
            Column("label", "Label", hint="e.g. Top shelf", max_length=100),
            Column(
                "status",
                "Status",
                CHOICE,
                hint="In service (default), Out of service or Retired",
                choices=list_range("slot_status"),
                choice_list="slot_status",
            ),
            Column("width_mm", "Width (mm)", INT),
            Column("depth_mm", "Depth (mm)", INT),
            Column("height_mm", "Height (mm)", INT),
            Column("max_load_kg", "Max Load (kg)", INT),
            Column("power_capacity_w", "Power Capacity (W)", INT),
            Column("network_port_count", "Network Ports", INT),
            Column("utilities", "Utilities", UTILITIES, hint="Separate by commas"),
            *(
                Column(
                    "compatible_bench_types",
                    f"Compatible Bench Type {n}",
                    hint="Pick from Bench Types" if n == 1 else "Optional",
                    choices=sheet_range("Bench Types"),
                )
                for n in (1, 2, 3)
            ),
        ),
    ),
    Sheet(
        "benches",
        "Benches",
        "B Spaces",
        "Benches and workspaces",
        (
            _SKU,
            _NAME,
            Column(
                "group",
                "Group",
                hint="Pick from Groups. The department comes from the group",
                choices=sheet_range("Groups"),
            ),
            _OWNER,
            Column(
                "bench_group",
                "Bench Group",
                hint="What the bench is for. Pick from Bench Groups",
                choices=sheet_range("Bench Groups"),
                aliases=("Function Group",),
            ),
            Column("type", "Bench Type", hint="Pick from Bench Types", choices=sheet_range("Bench Types")),
            Column("description", "Description"),
            Column("documentation_url", "Documentation Link", URL),
            Column("station", "Station Asset Tag", hint="Pick from Stations", choices=sheet_range("Stations")),
            Column("station_slot", "Station Slot Code", hint="Slot code from Station Slots"),
            _LIFECYCLE,
            _CONDITION,
            Column("criticality", "Criticality", hint="e.g. High, Medium, Low", max_length=32),
            Column("requested_power_w", "Requested Power (W)", INT),
            Column("requested_load_kg", "Requested Load (kg)", INT),
            Column("requested_cooling_w", "Requested Cooling (W)", INT),
            Column("required_utilities", "Required Utilities", UTILITIES, hint="Separate by commas"),
            Column("commissioning_date", "Commissioning Date", DATE, hint="YYYY-MM-DD"),
            _REMARK,
            Column("department", "Department", legacy=True),
        ),
    ),
    # ---- C. Equipment -----------------------------------------------------------------------
    Sheet(
        "equipment",
        "Equipment",
        "C Equipment",
        "Every unit once, general data. Category fields go to the category's detail sheet",
        (
            _SKU,
            _NAME,
            Column(
                "category",
                "Category",
                required=True,
                hint="Pick from Equipment Categories",
                choices=sheet_range("Equipment Categories"),
            ),
            Column(
                "kind",
                "Kind",
                required=True,
                hint="Must belong to the category",
                choices=sheet_range("Equipment Kinds", "B"),
            ),
            Column("type", "Type", hint="Must belong to the kind", choices=sheet_range("Equipment Types", "C")),
            Column("manufacturer", "Manufacturer", choices=sheet_range("Manufacturers")),
            Column(
                "product_model",
                "Product Model",
                hint="A model of the manufacturer",
                choices=sheet_range("Product Models", "D"),
            ),
            Column("serial_number", "Serial Number", max_length=255),
            Column("firmware_version", "Firmware Version", max_length=255),
            Column(
                "log_label",
                "LOG Label",
                hint="Label that already exists on the unit",
                aliases=("Previous / Legacy Label",),
                max_length=255,
            ),
            _DEPARTMENT,
            _GROUP,
            _OWNER,
            Column(
                "lifecycle_state",
                "Lifecycle",
                CHOICE,
                hint="Planned (on order) or In service (default)",
                choices=list_range("equipment_lifecycle"),
                choice_list="equipment_lifecycle",
            ),
            _CONDITION,
            Column(
                "storage_room",
                "Storage Room",
                hint="Room asset tag where the unit is kept (not on a bench)",
                choices=sheet_range("Rooms"),
            ),
            Column("replacement_date", "Replacement Date", DATE, hint="YYYY-MM-DD (YYYY-Qn is accepted)"),
            Column("warranty_until", "Warranty Until", DATE, hint="YYYY-MM-DD"),
            Column("power_draw_w", "Power Draw (W)", INT, hint="Nameplate consumption"),
            Column("weight_kg", "Weight (kg)", DECIMAL),
            _yes_no("calibration_required", "Calibration Required"),
            Column("details", "Details", hint="Free text notes", width=30),
            Column("remark", "Remarks", legacy=True),
            _LEGACY_STATUS,
        ),
    ),
    Sheet(
        "computing",
        "Computing",
        "C Detail sheet",
        "Computing details: one row per unit of the category",
        (
            _DETAIL_SKU,
            *_DETAIL_AUTO,
            Column("hostname", "Hostname", hint="DNS name of the computer", max_length=255),
            Column("mac_address", "MAC Address", hint="AA:BB:CC:DD:EE:FF"),
            Column(
                "technical_user",
                "Technical User",
                hint="Pick from Lookups > Technical Users",
                choices=sheet_range("Lookups", "F"),
            ),
            Column("os_name", "Operating System", legacy=True),
        ),
        detail_category="computing",
    ),
    Sheet(
        "display",
        "Display",
        "C Detail sheet",
        "Display details: one row per unit of the category",
        (
            _DETAIL_SKU,
            *_DETAIL_AUTO,
            Column("size", "Screen Size", hint="Pick from Screen Sizes", choices=sheet_range("Screen Sizes")),
            Column("resolution", "Resolution", hint="Pick from Resolutions", choices=sheet_range("Resolutions")),
            *_INTERFACES,
        ),
        detail_category="display",
    ),
    Sheet(
        "instrument",
        "Instrument",
        "C Detail sheet",
        "Instrument details: one row per unit of the category",
        (_DETAIL_SKU, *_DETAIL_AUTO, *_INTERFACES),
        detail_category="instrument",
    ),
    Sheet(
        "power",
        "Power",
        "C Detail sheet",
        "Power supply details: one row per unit of the category",
        (
            _DETAIL_SKU,
            *_DETAIL_AUTO,
            Column("channels", "Channels", INT, hint="Number of outputs"),
            Column("power_rating", "Power Rating (W)", INT, hint="Output capacity in W"),
            *_INTERFACES,
        ),
        detail_category="power",
    ),
    Sheet(
        "networking",
        "Networking",
        "C Detail sheet",
        "Networking details: one row per unit of the category",
        (
            _DETAIL_SKU,
            *_DETAIL_AUTO,
            Column(
                "protocol",
                "Network Protocol",
                hint="Pick from Lookups > Network Protocols",
                choices=sheet_range("Lookups", "C"),
            ),
            Column("mac_address", "MAC Address", hint="AA:BB:CC:DD:EE:FF"),
        ),
        detail_category="networking",
    ),
    Sheet(
        "sample",
        "Sample",
        "C Detail sheet",
        "Sample details: one row per unit of the category",
        (
            _DETAIL_SKU,
            *_DETAIL_AUTO,
            Column("customer", "Customer", hint="Pick from Lookups > Customers", choices=sheet_range("Lookups", "D")),
            *_INTERFACES,
            *_numbered(
                "characteristics",
                "Characteristic",
                4,
                sheet_range("Lookups", "E"),
                "Pick from Lookups > Characteristics",
            ),
        ),
        detail_category="sample",
    ),
    Sheet(
        "mechanical",
        "Mechanical",
        "C Detail sheet",
        "Mechanical details: one row per unit of the category",
        (_DETAIL_SKU, *_DETAIL_AUTO, *_DIMENSIONS),
        detail_category="mechanical",
    ),
    Sheet(
        "furniture",
        "Furniture",
        "C Detail sheet",
        "Furniture details: one row per unit of the category",
        (_DETAIL_SKU, *_DETAIL_AUTO, *_DIMENSIONS),
        detail_category="furniture",
    ),
    Sheet(
        "bench_placements",
        "Bench Placements",
        "C Equipment",
        "Which unit stands on which bench (now)",
        (
            Column(
                "bench", "Bench Asset Tag", required=True, hint="Pick from Benches", choices=sheet_range("Benches")
            ),
            Column(
                "equipment",
                "Equipment Asset Tag",
                required=True,
                hint="Pick from Equipment. One bench per unit",
                choices=sheet_range("Equipment"),
            ),
            Column("role", "Role", hint="Free text (default: default)", max_length=64),
            Column("position", "Position No.", INT, hint="Order on the bench"),
            Column("assigned_on", "Assigned On", legacy=True),
            Column("unassigned_on", "Unassigned On", legacy=True),
            Column("monitor", "Monitored", legacy=True),
        ),
        aliases=("Equipment Assignments",),
    ),
)

SHEETS_BY_KEY = {sheet.key: sheet for sheet in SHEETS}

# v1 sheets this version does not import yet; data in them is reported, never silently dropped.
NOT_YET_IMPORTED = (
    "Room Slots",
    "Specification Names",
    "Specifications",
    "Licenses",
    "License Assignments",
    "Purchases",
    "Purchase Items",
    "Costs",
)
# Columns of the v1 template that only support filling it in; never imported, never reported.
TEMPLATE_ONLY_COLUMNS = ("Data Check", "Cost Rows Expected", "Detail Sheet", "Open Details", "Sheet Key")
# Sheets of the v1 template that only support filling it in.
TEMPLATE_ONLY = ("README", "Summary", "Lists", "Field Map", "Tag Lists", "Pick Lists", "Pick Lists 2", "_Meta")


def normalize_header(value: str) -> str:
    text = value.strip()
    if text.endswith("*"):
        text = text[:-1]
    return " ".join(text.lower().split())


def find_sheet(name: str) -> Sheet | None:
    wanted = normalize_header(name)
    for sheet in SHEETS:
        if wanted in {normalize_header(sheet.name), *(normalize_header(alias) for alias in sheet.aliases)}:
            return sheet
    return None


def template_columns(sheet: Sheet) -> tuple[Column, ...]:
    return tuple(column for column in sheet.columns if not column.legacy)


__all__ = [
    "CHOICE_LISTS",
    "CHOICE_VALUES",
    "FIRST_DATA_ROW",
    "HEADER_ROW",
    "LISTS_SHEET",
    "MAX_DATA_ROWS",
    "NOT_YET_IMPORTED",
    "SHEETS",
    "SHEETS_BY_KEY",
    "TEMPLATE_ONLY",
    "TEMPLATE_ONLY_COLUMNS",
    "TEMPLATE_VERSION",
    "Column",
    "Sheet",
    "find_sheet",
    "normalize_header",
    "template_columns",
]
