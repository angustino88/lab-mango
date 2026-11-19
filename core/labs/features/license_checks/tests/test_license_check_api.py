"""License-check configuration API: roles (D7), validation, revisions, targets, observations."""

import copy

import pytest
from rest_framework.test import APIClient

from core.common.domain.errors import ValidationFailed
from core.labs.features.license_checks.config import validate_configuration
from core.labs.features.license_checks.presets import VECTOR_LICENSE_CLIENT
from core.labs.features.license_checks.queries.checks import agent_check_definitions
from core.labs.models import EquipmentAssignment, LicenseCheck
from core.users.models import User
from tests.factories import BenchFactory, ComputingEquipmentFactory, grant_labs_role

pytestmark = pytest.mark.django_db

CHECKS = "/api/labs/license-checks"


def client_for(role):
    user = User.objects.create_user(username=f"license-{role}")
    grant_labs_role(user, role)
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def admin():
    return client_for("admin")


@pytest.fixture
def coordinator():
    return client_for("coord")


def preset_config():
    return {name: copy.deepcopy(VECTOR_LICENSE_CLIENT[name]) for name in ("probe", "extract", "carrier")}


def test_vector_preset_is_a_valid_configuration():
    probe, extract, carrier = validate_configuration(**preset_config())
    assert carrier["type_map"] == {"DEVICE": "device", "DONGLE": "dongle", "PC": "computer"}
    assert extract["fields"]["license_serial"] == "VectorLicenseId"


@pytest.mark.parametrize(
    "path,value,field",
    [
        (("probe", "executable"), r"Vector.LicenseClient.exe", "probe.executable"),
        (("probe", "executable"), r"C:\Program Files\..\Windows\cmd.exe", "probe.executable"),
        (("probe", "type"), "powershell", "probe.type"),
        (("probe", "timeout_s"), 600, "probe.timeout_s"),
        (("extract", "format"), "values", "extract.format"),
        (("carrier", "hardware_id_kind"), "", "carrier.hardware_id_kind"),
        (("carrier", "hardware_id_kind"), "pnp_id", "carrier.hardware_id_kind"),
    ],
)
def test_configurations_the_agent_would_reject_fail_on_write(path, value, field):
    config = preset_config()
    config[path[0]][path[1]] = value
    with pytest.raises(ValidationFailed) as error:
        validate_configuration(**config)
    assert field in error.value.details


def test_text_regex_must_name_its_groups():
    config = preset_config()
    config["probe"] = {"type": "file", "path": r"C:\ProgramData\Tool\license.lic"}
    config["carrier"] = {"type": "computer"}
    config["extract"] = {"format": "text", "records": r"FEATURE (?P<name>\S+)", "fields": {"product_name": "product"}}
    with pytest.raises(ValidationFailed):
        validate_configuration(**config)
    config["extract"]["records"] = r"FEATURE (?P<product>\S+)"
    assert validate_configuration(**config)[1]["records"] == r"FEATURE (?P<product>\S+)"


def test_admin_creates_from_preset_and_coordinator_may_not(admin, coordinator):
    bench = BenchFactory()
    body = {"preset_key": "vector-license-client", "targets": [{"kind": "bench", "target_id": bench.pk}]}
    denied = coordinator.post(CHECKS, body, format="json")
    assert denied.status_code == 403, denied.data
    response = admin.post(CHECKS, body, format="json")
    assert response.status_code == 201, response.data
    data = response.data["data"]
    assert (data["key"], data["revision"], data["preset_key"]) == ("vector-license-client", 1, "vector-license-client")
    assert data["targets"] == [{"id": bench.pk, "kind": {"value": "bench", "label": "Bench"}, "name": bench.name}]
    assert admin.post(CHECKS, body, format="json").status_code == 409
    assert admin.get(f"{CHECKS}/presets").data["data"]["items"][0]["key"] == "vector-license-client"


def test_coordinator_changes_targets_and_schedule_but_not_what_runs(admin, coordinator):
    check_id = admin.post(CHECKS, {"preset_key": "vector-license-client"}, format="json").data["data"]["id"]
    computer = ComputingEquipmentFactory()
    patched = coordinator.patch(
        f"{CHECKS}/{check_id}",
        {"interval_minutes": 60, "targets": [{"kind": "equipment", "target_id": computer.pk}]},
        format="json",
    )
    assert patched.status_code == 200, patched.data
    assert patched.data["data"]["revision"] == 2  # the interval reaches the agent
    probe = dict(VECTOR_LICENSE_CLIENT["probe"], args=["-listlicenses", "-verbose"])
    assert coordinator.patch(f"{CHECKS}/{check_id}", {"probe": probe}, format="json").status_code == 403
    changed = admin.patch(f"{CHECKS}/{check_id}", {"probe": probe}, format="json")
    assert changed.status_code == 200 and changed.data["data"]["revision"] == 3
    assert admin.patch(f"{CHECKS}/{check_id}", {"is_enabled": False}, format="json").data["data"]["revision"] == 3
    assert coordinator.delete(f"{CHECKS}/{check_id}").status_code == 403
    assert admin.delete(f"{CHECKS}/{check_id}").status_code == 204


def test_invalid_configuration_is_a_field_error(admin):
    config = preset_config()
    config["probe"]["executable"] = "relative.exe"
    response = admin.post(CHECKS, {"key": "custom", "name": "Custom", **config}, format="json")
    assert response.status_code == 422, response.data
    assert not LicenseCheck.objects.exists()


def test_targets_resolve_through_bench_station_and_room():
    computer = ComputingEquipmentFactory()
    bench = BenchFactory()
    EquipmentAssignment.objects.create(equipment=computer, bench=bench, assigned_at="2026-11-01T00:00:00Z")
    check = LicenseCheck.objects.create(key="by-category", name="By category", probe={}, extract={}, carrier={})
    assert agent_check_definitions(computing_id=computer.pk) == []
    check.targets.create(category=computer.kind.category)
    assert [c["key"] for c in agent_check_definitions(computing_id=computer.pk)] == ["by-category"]
    check.targets.all().delete()
    check.targets.create(bench=bench)
    assert [c["key"] for c in agent_check_definitions(computing_id=computer.pk)] == ["by-category"]


def test_observation_list_filters(admin):
    assert admin.get("/api/labs/license-observations", {"is_attention_required": "true"}).status_code == 200
    assert admin.get("/api/labs/license-observations", {"status": "nope"}).status_code == 400
