"""POST /api/labs/equipment/actions/match: equipment by specification requirements and free time."""

from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from core.labs.models import (
    Equipment,
    EquipmentCategory,
    EquipmentKind,
    EquipmentLoan,
    EquipmentLoanBatch,
    EquipmentManufacturer,
    EquipmentProductModel,
    EquipmentType,
    ProductModelSpecification,
    ResourceDowntime,
    SpecificationDefinition,
)
from core.users.tests.factories import UserFactory
from tests.factories import grant_labs_role

URL = "/api/labs/equipment/actions/match"


@pytest.fixture()
def operator(db):
    client = APIClient()
    user = grant_labs_role(UserFactory(username="match-operator"), "coord")
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture()
def catalog(db):
    category = EquipmentCategory.objects.create(name="Oscilloscope", definition="Scopes")
    kind = EquipmentKind.objects.create(category=category, name="Digital scope")
    equipment_type = EquipmentType.objects.create(kind=kind, name="Bench scope")
    maker = EquipmentManufacturer.objects.create(name="Acme")
    maker.categories.add(category)
    bandwidth = SpecificationDefinition.objects.create(name="Bandwidth", unit="MHz", value_type="number")
    channels = SpecificationDefinition.objects.create(name="Channels", value_type="number")
    interface = SpecificationDefinition.objects.create(name="Interface", value_type="text")
    usb_power = SpecificationDefinition.objects.create(name="USB power", value_type="boolean")

    def model(name, **specs):
        product = EquipmentProductModel.objects.create(manufacturer=maker, equipment_type=equipment_type, name=name)
        for definition, value in specs.items():
            ProductModelSpecification.objects.create(
                product_model=product, definition=locals_map[definition], value=value
            )
        return product

    locals_map = {"bandwidth": bandwidth, "channels": channels, "interface": interface, "usb_power": usb_power}
    big = model("Big scope", bandwidth="1000", channels="4", interface="USB, LAN", usb_power="yes")
    small = model("Small scope", bandwidth="200", channels="2", interface="USB")
    blank = model("Blank scope", channels="4")

    def unit(sku, product):
        return Equipment.objects.create(sku=sku, name=sku, kind=kind, product_model=product)

    return {
        "category": category,
        "bandwidth": bandwidth,
        "channels": channels,
        "interface": interface,
        "usb_power": usb_power,
        "big": unit("SC-BIG", big),
        "small": unit("SC-SMALL", small),
        "blank": unit("SC-BLANK", blank),
    }


def _req(definition, op, value, **extra):
    return {"spec_definition_id": definition.pk, "op": op, "value": value, **extra}


def _post(client, **body):
    return client.post(URL, body, format="json")


def _names(response):
    return [item["equipment"]["name"] for item in response.json()["data"]["matches"]]


@pytest.mark.django_db
class TestMatching:
    def test_generated_number_column(self, catalog):
        spec = ProductModelSpecification.objects.get(definition=catalog["bandwidth"], value="1000")
        text = ProductModelSpecification.objects.get(definition=catalog["interface"], value="USB")

        assert spec.value_number == Decimal("1000")
        assert text.value_number is None

    def test_number_requirements_with_unit_conversion(self, operator, catalog):
        response = _post(
            operator,
            category_id=catalog["category"].pk,
            requirements=[
                _req(catalog["bandwidth"], "gte", 1, unit="GHz"),
                _req(catalog["channels"], "gte", 4),
            ],
        )

        assert response.status_code == 200
        assert _names(response) == ["SC-BIG"]
        match = response.json()["data"]["matches"][0]
        assert match["is_full_match"] is True
        assert match["score"] == "1.00"
        assert [item["status"]["value"] for item in match["requirements"]] == ["matched", "matched"]
        assert match["requirements"][0]["actual"] == "1000 MHz"

    def test_near_matches_show_missed_and_unknown(self, operator, catalog):
        response = _post(
            operator,
            requirements=[_req(catalog["bandwidth"], "gte", 500), _req(catalog["channels"], "gte", 4)],
            include_near_matches=True,
        )

        matches = {item["equipment"]["name"]: item for item in response.json()["data"]["matches"]}
        assert list(matches)[0] == "SC-BIG"
        assert matches["SC-BLANK"]["is_full_match"] is False
        assert [item["status"]["value"] for item in matches["SC-BLANK"]["requirements"]] == ["unknown", "matched"]
        assert "SC-SMALL" not in matches  # misses both required requirements

    def test_near_matches_miss_at_most_one(self, operator, catalog):
        response = _post(
            operator,
            requirements=[
                _req(catalog["bandwidth"], "gte", 500),
                _req(catalog["channels"], "gte", 4),
                _req(catalog["interface"], "contains", "lan"),
            ],
            include_near_matches=True,
        )

        assert _names(response) == ["SC-BIG"]

    def test_optional_requirement_only_ranks(self, operator, catalog):
        response = _post(
            operator,
            requirements=[
                _req(catalog["channels"], "gte", 2),
                _req(catalog["interface"], "contains", "lan", required=False),
            ],
        )

        assert _names(response)[0] == "SC-BIG"
        assert set(_names(response)) == {"SC-BIG", "SC-SMALL", "SC-BLANK"}

    def test_text_in_between_and_boolean(self, operator, catalog):
        text = _post(operator, requirements=[_req(catalog["interface"], "in", ["usb", "gpib"])])
        between = _post(operator, requirements=[_req(catalog["bandwidth"], "between", [100, 300])])
        boolean = _post(operator, requirements=[_req(catalog["usb_power"], "eq", True)])

        assert _names(text) == ["SC-SMALL"]
        assert _names(between) == ["SC-SMALL"]
        assert _names(boolean) == ["SC-BIG"]

    def test_window_excludes_loaned_and_down_units(self, operator, catalog):
        starts_at = timezone.now() + timedelta(days=1)
        batch = EquipmentLoanBatch.objects.create(borrower_name="Someone", created_by=operator.user)
        EquipmentLoan.objects.create(
            equipment=catalog["big"],
            batch=batch,
            handed_over_at=timezone.now(),
            handed_over_by=operator.user,
            due_at=starts_at,
        )
        ResourceDowntime.for_new_resource(catalog["small"], condition="out_of_service", starts_at=starts_at).save()

        response = _post(
            operator,
            requirements=[_req(catalog["channels"], "gte", 2)],
            available_from=starts_at.isoformat(),
            available_until=(starts_at + timedelta(hours=8)).isoformat(),
        )

        assert _names(response) == ["SC-BLANK"]

    def test_retired_units_are_left_out(self, operator, catalog):
        Equipment.objects.filter(pk=catalog["big"].pk).update(lifecycle_state="retired")

        assert "SC-BIG" not in _names(_post(operator, requirements=[_req(catalog["channels"], "gte", 2)]))

    def test_limit_marks_truncation(self, operator, catalog):
        data = _post(operator, requirements=[_req(catalog["channels"], "gte", 2)], limit=1).json()["data"]

        assert len(data["matches"]) == 1
        assert data["is_truncated"] is True

    def test_query_count_does_not_grow_with_units(self, operator, catalog):
        body = {"requirements": [_req(catalog["channels"], "gte", 2)]}
        operator.post(URL, body, format="json")
        with CaptureQueriesContext(connection) as few:
            operator.post(URL, body, format="json")
        for index in range(5):
            Equipment.objects.create(
                sku=f"SC-MORE-{index}",
                name=f"SC-MORE-{index}",
                kind=catalog["big"].kind,
                product_model=catalog["big"].product_model,
            )
        with CaptureQueriesContext(connection) as many:
            operator.post(URL, body, format="json")

        assert len(many) == len(few)

    @pytest.mark.parametrize(
        "requirement",
        [
            {"op": "contains", "value": "1"},
            {"op": "gte", "value": "fast"},
            {"op": "gte", "value": 1, "unit": "V"},
            {"op": "between", "value": [1]},
        ],
    )
    def test_invalid_requirement_is_422(self, operator, catalog, requirement):
        response = _post(operator, requirements=[{"spec_definition_id": catalog["bandwidth"].pk, **requirement}])

        assert response.status_code == 422

    def test_unknown_definition_is_422(self, operator, catalog):
        response = _post(operator, requirements=[{"spec_definition_id": 999999, "op": "eq", "value": 1}])

        assert response.status_code == 422

    def test_half_window_is_rejected(self, operator, catalog):
        response = _post(operator, available_from=timezone.now().isoformat())

        assert response.status_code in (400, 422)

    def test_member_is_forbidden(self, catalog):
        client = APIClient()
        client.force_authenticate(user=grant_labs_role(UserFactory(username="match-member"), "member"))

        assert _post(client).status_code == 403
