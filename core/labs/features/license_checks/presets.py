"""Check templates offered in the web app. A preset is an ordinary configuration, copied on create.

Each preset is written against captured output of the tool on a lab computer; the agent ships the
same definitions (``agent/src/core/licensing/presets.py``) and trusts their executables.
"""

VECTOR_LICENSE_CLIENT = {
    "key": "vector-license-client",
    "name": "Vector License Client",
    "vendor": "Vector",
    "description": (
        "New Vector License Model, read with 'Vector.LicenseClient -listlicenses' (Vector KB0021758). "
        "Covers licenses on Vector devices (CANcase, VN interfaces), Keyman dongles and the PC. "
        "The carrier is found by its Vector device name (hardware ID kind 'vector_device')."
    ),
    "interval_minutes": 360,
    "probe": {
        "type": "command",
        "executable": r"C:\Program Files\Vector License Client\Vector.LicenseClient.exe",
        "args": ["-listlicenses"],
        "timeout_s": 20,
        "encoding": "auto",
    },
    "extract": {
        "format": "xml",
        "records": ".//VectorLicense",
        "fields": {
            "product_name": "ProductText",
            "product_code": "MaterialNumber",
            "max_version": "MaxVersion",
            "expires_at": "ExpirationDateString",
            "final_expires_at": "FinalExpirationDateString",
            "carrier_id": "DeviceName",
            "license_serial": "VectorLicenseId",
            "is_reactivatable": "IsReactivatable",
            "carrier_type": "BindingType",
        },
        "date_formats": ["iso"],
        "never_values": ["9999-12-31"],
    },
    "carrier": {
        "type": "mapped",
        "type_map": {"DEVICE": "device", "DONGLE": "dongle", "PC": "computer"},
        "default_type": "computer",
        "hardware_id_kind": "vector_device",
    },
}

PRESETS = {VECTOR_LICENSE_CLIENT["key"]: VECTOR_LICENSE_CLIENT}
