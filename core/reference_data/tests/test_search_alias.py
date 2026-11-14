"""Catalog lists search with `q`; `search` still works for one release and is announced (QRY-7, CMP-3)."""

import pytest


@pytest.mark.django_db
def test_catalog_list_accepts_q_and_announces_the_deprecated_alias(api_client):
    from core.labs.features.equipment.tests.roles import grant_labs_role
    from core.labs.models import Country
    from tests.factories import UserFactory

    Country.objects.create(name="Vietnam", code="VN")
    Country.objects.create(name="Germany", code="DE")
    api_client.force_authenticate(grant_labs_role(UserFactory(), "coord"))
    url = "/api/labs/locations/reference-data/countries"

    by_q = api_client.get(url, {"q": "viet"})
    assert by_q.status_code == 200, by_q.content
    assert [row["name"] for row in by_q.json()["data"]] == ["Vietnam"]
    assert "Deprecation" not in by_q

    by_alias = api_client.get(url, {"search": "viet"})
    assert [row["name"] for row in by_alias.json()["data"]] == ["Vietnam"]
    assert by_alias["Deprecation"] == "true"
