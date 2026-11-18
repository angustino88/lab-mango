"""Signed license-check routes: the checks a computer runs, and run intake with matching and effects."""

import json
import uuid
from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from core.agents.tests.signing import signed_headers
from core.labs.features.license_checks.presets import VECTOR_LICENSE_CLIENT
from core.labs.models import (
    Equipment,
    EquipmentAssignment,
    License,
    LicenseAssignment,
    LicenseCheck,
    LicenseCheckRun,
    LicenseCheckTarget,
    LicenseObservation,
    LicenseStatusRecord,
    ResourceChangeLog,
)
from core.labs.models.resource.equipment.hardware_id import EquipmentHardwareId
from core.labs.models.resource.license.license import LicenseCategory, LicenseProduct, LicenseType, LicenseVendor
from tests.factories import BenchFactory, EquipmentKindFactory

CHECKS = "/agent/license-checks"
KEY = VECTOR_LICENSE_CLIENT["key"]
REPORT = f"{CHECKS}/{KEY}/actions/report"
CANCASE = "007113-585343"
SERIAL = "55100045010"


def fetch(identity, key, *, etag=""):
    headers: dict[str, Any] = signed_headers(key, identity.agent_uid, b"", method="GET", path=CHECKS)
    if etag:
        headers["HTTP_IF_NONE_MATCH"] = etag
    return APIClient().get(CHECKS, **headers)


def send(identity, key, body, *, idempotency_key=None, path=REPORT):
    raw = json.dumps(body).encode()
    headers: dict[str, Any] = signed_headers(key, identity.agent_uid, raw, method="POST", path=path)
    headers["HTTP_IDEMPOTENCY_KEY"] = str(idempotency_key or uuid.uuid4())
    return APIClient().post(path, data=raw, content_type="application/json", **headers)


def vector_license(**changes):
    item = {
        "observation_key": f"vector-license-client:serial:{SERIAL}",
        "vendor": "Vector",
        "product_code": "55100",
        "product_name": "CANalyzer PRO",
        "carrier": {"type": "device", "hardware_id": {"kind": "vector_device", "value": CANCASE}},
        "expires_at": "2027-04-09T23:59:59+07:00",
        "final_expires_at": None,
        "max_version": "15.0",
        "is_reactivatable": True,
        "license_serial": SERIAL,
    }
    item.update(changes)
    return item


def run(check, *licenses, sequence=1, status="ok", revision=None):
    body = {
        "revision": revision or check.revision,
        "sequence": sequence,
        "status": status,
        "started_at": "2026-11-18T15:35:11+07:00",
        "reported_at": "2026-11-18T08:35:12Z",
        "duration_ms": 412,
        "is_complete": status == "ok",
        "licenses": list(licenses),
    }
    if status != "ok":
        body["error"] = {"code": "timeout", "message": "The tool did not answer."}
    return body


@pytest.fixture
def bench_setup(enrolled):
    """The enrolled computer on a bench with a CANcase; a Vector check targets the bench."""
    identity, _, _ = enrolled
    computer = Equipment.objects.get(pk=identity.equipment_id)
    bench = BenchFactory()
    cancase = Equipment.objects.create(
        sku="CANCASE-1", name="CANcase 1", kind=EquipmentKindFactory(name="CAN interface")
    )
    now = timezone.now()
    for unit in (computer, cancase):
        EquipmentAssignment.objects.create(equipment=unit, bench=bench, assigned_at=now)
    EquipmentHardwareId.objects.create(equipment=cancase, kind="vector_device", value=CANCASE)
    check = LicenseCheck.objects.create(
        key=KEY,
        name=VECTOR_LICENSE_CLIENT["name"],
        vendor="Vector",
        probe=VECTOR_LICENSE_CLIENT["probe"],
        extract=VECTOR_LICENSE_CLIENT["extract"],
        carrier=VECTOR_LICENSE_CLIENT["carrier"],
    )
    LicenseCheckTarget.objects.create(license_check=check, bench=bench)
    vendor = LicenseVendor.objects.create(name="Vector")
    license_record = License.objects.create(
        sku="LIC-CANALYZER",
        name="CANalyzer PRO",
        serial_number=SERIAL,
        expiry_date=now + timedelta(days=30),
        max_version="14.0",
        product=LicenseProduct.objects.create(name="CANalyzer", vendor=vendor),
        vendor=vendor,
        type=LicenseType.objects.create(name="Device locked"),
        category=LicenseCategory.objects.create(name="Software"),
    )
    LicenseAssignment.objects.create(license=license_record, equipment=cancase)
    return check, cancase, license_record, bench


def test_checks_are_served_to_targeted_computers_with_etag(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, *_ = bench_setup
    response = fetch(identity, key)
    assert response.status_code == 200, response.data
    checks = response.json()["data"]["checks"]
    assert [c["key"] for c in checks] == [KEY]
    assert checks[0]["revision"] == check.revision and checks[0]["probe"]["args"] == ["-listlicenses"]
    assert fetch(identity, key, etag=response["ETag"]).status_code == 304

    check.is_enabled = False
    check.save()
    assert fetch(identity, key, etag=response["ETag"]).json()["data"]["checks"] == []


def test_capability_is_advertised(db):
    data = APIClient().get("/agent/info").json()["data"]
    assert "license_checks" in data["capabilities"]
    assert data["endpoints"]["license_checks"] == CHECKS


def test_matched_license_updates_expiry_and_version_with_change_log(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, cancase, license_record, _ = bench_setup

    response = send(identity, key, run(check, vector_license()))

    assert response.status_code == 200, response.data
    assert response.json()["data"]["result"]["value"] == "applied"
    observation = LicenseObservation.objects.get()
    assert (observation.status, observation.license_id, observation.carrier_equipment_id) == (
        "matched",
        license_record.pk,
        cancase.pk,
    )
    license_record.refresh_from_db()
    assert license_record.expiry_date.isoformat() == "2027-04-09T16:59:59+00:00"
    assert license_record.max_version == "15.0"
    logs = ResourceChangeLog.objects.filter(resource_object_id=str(license_record.pk)).order_by("field_name")
    assert [log.field_name for log in logs] == ["expiry_date", "max_version"]
    assert logs[0].metadata["agent_uid"] == str(identity.agent_uid) and logs[0].creator is None

    # An identical later run changes nothing in the inventory.
    assert send(identity, key, run(check, vector_license(), sequence=2)).json()["data"]["result"]["value"] == "applied"
    assert ResourceChangeLog.objects.filter(resource_object_id=str(license_record.pk)).count() == 2


def test_exact_retry_is_replayed_and_a_reused_key_conflicts(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, *_ = bench_setup
    idempotency_key = uuid.uuid4()
    body = run(check, vector_license())
    assert send(identity, key, body, idempotency_key=idempotency_key).status_code == 200
    replay = send(identity, key, body, idempotency_key=idempotency_key)
    assert replay.status_code == 200 and replay["Idempotency-Replayed"] == "true"
    changed = run(check, vector_license(max_version="16.0"))
    assert send(identity, key, changed, idempotency_key=idempotency_key).json()["error"]["code"] == (
        "idempotency_key_reused"
    )
    assert LicenseCheckRun.objects.count() == 1


def test_stale_and_outdated_runs_are_recorded_without_effects(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, _, license_record, _ = bench_setup
    assert (
        send(identity, key, run(check, vector_license(), sequence=10)).json()["data"]["result"]["value"] == "applied"
    )
    stale = send(identity, key, run(check, vector_license(max_version="99.0"), sequence=5))
    assert stale.json()["data"]["result"]["value"] == "stale"
    check.revision = 2
    check.save()
    outdated = send(identity, key, run(check, vector_license(max_version="99.0"), sequence=11, revision=1))
    assert outdated.json()["data"]["result"]["value"] == "outdated_revision"
    license_record.refresh_from_db()
    assert license_record.max_version == "15.0"


def test_failed_run_keeps_licenses_and_complete_run_removes_missing(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, *_ = bench_setup
    send(identity, key, run(check, vector_license()))
    failed = send(identity, key, run(check, sequence=2, status="failed"))
    assert failed.json()["data"]["result"]["value"] == "recorded"
    assert LicenseObservation.objects.get().removed_at is None
    assert LicenseCheckRun.objects.get(sequence=2).error_code == "timeout"
    send(identity, key, run(check, sequence=3))
    assert LicenseObservation.objects.get().removed_at is not None


def test_carrier_away_from_this_computer_is_shown_but_never_updates(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, cancase, license_record, _ = bench_setup
    EquipmentAssignment.objects.filter(equipment=cancase).update(unassigned_at=timezone.now())

    send(identity, key, run(check, vector_license()))

    assert LicenseObservation.objects.get().status == "carrier_not_at_computer"
    license_record.refresh_from_db()
    assert license_record.max_version == "14.0"


@pytest.mark.parametrize(
    "change,status",
    [
        ({"license_serial": "UNKNOWN-1"}, "unregistered"),
        (
            {"carrier": {"type": "device", "hardware_id": {"kind": "vector_device", "value": "999-999"}}},
            "carrier_unlinked",
        ),
    ],
)
def test_unknown_license_or_carrier_is_listed_for_a_coordinator(enrolled, bench_setup, change, status):
    identity, key, _ = enrolled
    check, *_ = bench_setup
    send(identity, key, run(check, vector_license(**change)))
    assert LicenseObservation.objects.get().status == status


def test_license_assigned_to_another_unit_is_a_mismatch(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, cancase, license_record, _ = bench_setup
    other = Equipment.objects.create(sku="CANCASE-2", name="CANcase 2", kind=cancase.kind)
    LicenseAssignment.objects.filter(license=license_record).update(equipment=other)
    send(identity, key, run(check, vector_license()))
    assert LicenseObservation.objects.get().status == "carrier_mismatch"


def test_past_expiry_records_expired_and_renewal_ends_it(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, _, license_record, _ = bench_setup
    send(identity, key, run(check, vector_license(expires_at="2020-01-01T00:00:00Z")))
    latest = LicenseStatusRecord.objects.filter(license=license_record).order_by("-created", "-id").first()
    assert latest.status == "expired" and latest.metadata["source"] == "license_check"
    send(identity, key, run(check, vector_license(), sequence=2))
    latest = LicenseStatusRecord.objects.filter(license=license_record).order_by("-created", "-id").first()
    assert latest.status == "assigned"


def test_untargeted_check_is_not_found_and_body_rules_apply(enrolled, bench_setup):
    identity, key, _ = enrolled
    check, *_ = bench_setup
    LicenseCheckTarget.objects.all().delete()
    assert send(identity, key, run(check, vector_license())).status_code == 404
    check.is_lab_wide = True
    check.save()
    body = run(check, vector_license())
    body["is_complete"] = False
    assert send(identity, key, body).status_code == 422
    body = run(check, vector_license(), status="failed")
    assert send(identity, key, body).status_code == 422
