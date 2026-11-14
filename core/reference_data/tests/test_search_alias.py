"""Catalog lists search with `q`; the former `search` alias is removed (QRY-7)."""

import pytest


@pytest.mark.django_db
def test_catalog_list_searches_with_q_only(api_client):
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

    removed = api_client.get(url, {"search": "viet"})
    assert removed.status_code == 400, removed.content
