"""Validation of license-check configurations, with the rules the agent applies.

The agent supports a closed catalog of probes (``command``, ``file``, ``registry``) and declarative
extraction formats; it rejects anything else and reports the run as ``rejected``. The backend
applies the same rules on write so a coordinator sees the problem in the web app instead.
Agent-side only: the allowed folders on the computer and the trusted-path rule while TLS is off.
"""

from __future__ import annotations

import re
from typing import Any

from core.common.domain.errors import ValidationFailed

PROBE_TYPES = ("command", "file", "registry")
EXTRACT_FORMATS = ("xml", "json", "text", "values")
CARRIER_TYPES = ("computer", "device", "dongle", "server", "equipment")
MAPPED_CARRIER = "mapped"
# IDs a license tool reports for the hardware holding its licenses. ``pnp_id`` is for device monitoring
# only: no license tool reports a Windows PnP instance path. Add a kind when a new tool names its carrier.
CARRIER_ID_KINDS = ("vector_device",)
TARGET_FIELDS = (
    "product_name",
    "product_code",
    "max_version",
    "expires_at",
    "final_expires_at",
    "carrier_id",
    "license_serial",
    "is_reactivatable",
    "carrier_type",
)
ENCODINGS = ("auto", "utf-8", "utf-16", "cp437", "cp1252", "latin-1")
MAX_ARGS = 16
MAX_ARG_LENGTH = 256
MAX_TIMEOUT_S = 60
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:\\")


def _fail(field: str, message: str) -> None:
    raise ValidationFailed(message, details={field: message})


def _string(data: dict, name: str, field: str, *, default: str = "", required: bool = False, limit: int = 512) -> str:
    value = data.get(name, default)
    if value is None:
        value = default
    if not isinstance(value, str) or len(value) > limit or "\x00" in value:
        _fail(field, f"Must be text of at most {limit} characters.")
    value = value.strip()
    if required and not value:
        _fail(field, "This field is required.")
    return value


def _strings(data: dict, name: str, field: str, *, limit: int, item_limit: int) -> list[str]:
    value = data.get(name) or []
    if not isinstance(value, list) or len(value) > limit:
        _fail(field, f"Must be a list of at most {limit} items.")
    for item in value:
        if not isinstance(item, str) or len(item) > item_limit or "\x00" in item:
            _fail(field, f"Items must be text of at most {item_limit} characters.")
    return list(value)


def _windows_path(value: str, field: str) -> str:
    if not _WINDOWS_ABSOLUTE.match(value) or ".." in value.replace("/", "\\").split("\\"):
        _fail(field, "Use an absolute Windows path (for example C:\\Program Files\\...) without '..'.")
    return value


def validate_probe(data: Any) -> dict:
    if not isinstance(data, dict):
        _fail("probe", "Must be an object.")
    kind = _string(data, "type", "probe.type", required=True)
    if kind not in PROBE_TYPES:
        _fail("probe.type", f"Use one of: {', '.join(PROBE_TYPES)}.")
    timeout = data.get("timeout_s", 20)
    if not isinstance(timeout, int) or isinstance(timeout, bool) or not 1 <= timeout <= MAX_TIMEOUT_S:
        _fail("probe.timeout_s", f"Use 1 to {MAX_TIMEOUT_S} seconds.")
    encoding = _string(data, "encoding", "probe.encoding", default="auto", limit=32).lower()
    if encoding not in ENCODINGS:
        _fail("probe.encoding", f"Use one of: {', '.join(ENCODINGS)}.")
    probe: dict[str, Any] = {"type": kind, "timeout_s": timeout, "encoding": encoding}
    if kind == "command":
        probe["executable"] = _windows_path(
            _string(data, "executable", "probe.executable", required=True), "probe.executable"
        )
        if not probe["executable"].lower().endswith(".exe"):
            _fail("probe.executable", "The executable must be an .exe file.")
        probe["args"] = _strings(data, "args", "probe.args", limit=MAX_ARGS, item_limit=MAX_ARG_LENGTH)
    elif kind == "file":
        probe["path"] = _windows_path(_string(data, "path", "probe.path", required=True), "probe.path")
    else:
        hive = _string(data, "hive", "probe.hive", default="HKLM", limit=8).upper()
        if hive != "HKLM":
            _fail("probe.hive", "Only HKLM can be read.")
        probe["hive"] = hive
        probe["key"] = _string(data, "key", "probe.key", required=True)
        probe["values"] = _strings(data, "values", "probe.values", limit=32, item_limit=128)
        if not probe["values"]:
            _fail("probe.values", "Name at least one registry value.")
    return probe


def validate_extract(data: Any, probe: dict) -> dict:
    if not isinstance(data, dict):
        _fail("extract", "Must be an object.")
    fmt = _string(data, "format", "extract.format", required=True)
    if fmt not in EXTRACT_FORMATS:
        _fail("extract.format", f"Use one of: {', '.join(EXTRACT_FORMATS)}.")
    if (fmt == "values") != (probe["type"] == "registry"):
        _fail("extract.format", "Format 'values' is used with, and only with, registry probes.")
    fields = data.get("fields")
    if not isinstance(fields, dict) or not fields:
        _fail("extract.fields", "Map license fields to source fields.")
    unknown = sorted(set(fields) - set(TARGET_FIELDS))
    if unknown:
        _fail("extract.fields", f"Unknown fields: {', '.join(unknown)}.")
    if "product_name" not in fields:
        _fail("extract.fields", "'product_name' is required.")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 256 for value in fields.values()):
        _fail("extract.fields", "Field sources must be non-empty text.")
    records = _string(data, "records", "extract.records", required=fmt != "values", limit=1024)
    if fmt == "text":
        try:
            pattern = re.compile(records)
        except re.error as error:
            _fail("extract.records", f"Not a valid regular expression: {error}.")
        missing = sorted(set(fields.values()) - set(pattern.groupindex))
        if missing:
            _fail("extract.records", f"The expression has no named groups: {', '.join(missing)}.")
    return {
        "format": fmt,
        "records": records,
        "fields": {name: value.strip() for name, value in fields.items()},
        "date_formats": _strings(data, "date_formats", "extract.date_formats", limit=8, item_limit=64) or ["iso"],
        "never_values": _strings(data, "never_values", "extract.never_values", limit=16, item_limit=64),
    }


def validate_carrier(data: Any, extract: dict) -> dict:
    if not isinstance(data, dict):
        _fail("carrier", "Must be an object.")
    kind = _string(data, "type", "carrier.type", required=True)
    if kind not in (*CARRIER_TYPES, MAPPED_CARRIER):
        _fail("carrier.type", f"Use one of: {', '.join((*CARRIER_TYPES, MAPPED_CARRIER))}.")
    carrier: dict[str, Any] = {"type": kind}
    possible = {kind}
    if kind == MAPPED_CARRIER:
        type_map = data.get("type_map") or {}
        if (
            not isinstance(type_map, dict)
            or not type_map
            or len(type_map) > 16
            or any(not isinstance(k, str) or not k.strip() or v not in CARRIER_TYPES for k, v in type_map.items())
        ):
            _fail("carrier.type_map", "Map the tool's values to carrier types.")
        default_type = _string(data, "default_type", "carrier.default_type", default="computer", limit=16)
        if default_type not in CARRIER_TYPES:
            _fail("carrier.default_type", f"Use one of: {', '.join(CARRIER_TYPES)}.")
        if "carrier_type" not in extract["fields"]:
            _fail("extract.fields", "A mapped carrier needs a 'carrier_type' field.")
        carrier["type_map"] = {k.strip().upper(): v for k, v in type_map.items()}
        carrier["default_type"] = default_type
        possible = set(carrier["type_map"].values()) | {default_type}
    if possible & {"device", "dongle"}:
        hardware_id_kind = _string(data, "hardware_id_kind", "carrier.hardware_id_kind", limit=32)
        if hardware_id_kind not in CARRIER_ID_KINDS:
            _fail(
                "carrier.hardware_id_kind", f"Device and dongle carriers need one of: {', '.join(CARRIER_ID_KINDS)}."
            )
        if "carrier_id" not in extract["fields"]:
            _fail("extract.fields", "Device and dongle carriers need a 'carrier_id' field.")
        carrier["hardware_id_kind"] = hardware_id_kind
    if "equipment" in possible:
        carrier["equipment_uid"] = _string(data, "equipment_uid", "carrier.equipment_uid", required=True, limit=64)
    return carrier


def validate_configuration(probe: Any, extract: Any, carrier: Any) -> tuple[dict, dict, dict]:
    """Normalised ``(probe, extract, carrier)``; raises ``ValidationFailed`` naming the field."""
    clean_probe = validate_probe(probe)
    clean_extract = validate_extract(extract, clean_probe)
    return clean_probe, clean_extract, validate_carrier(carrier, clean_extract)
