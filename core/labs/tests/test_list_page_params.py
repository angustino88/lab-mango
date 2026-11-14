"""Every paginated list accepts ``page`` and ``page_size`` beside its own filters.

``validate_query()`` returns the paging values with the filters whenever a query serializer declares them
(``with_page_query``, ``PageNumberQuerySerializer``). A handler that forwards the validated values to a
selector must drop them first, or the request fails with a 500 (``list_downtimes() got an unexpected
keyword argument 'page'``). The endpoints are discovered from the URL configuration so a new paginated
list is covered without editing this file.
"""

import re

import pytest
from django.contrib.auth import get_user_model
from django.urls import get_resolver
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PREFIX = "api/"


def _routes(patterns, prefix=""):
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if hasattr(pattern, "url_patterns"):
            yield from _routes(pattern.url_patterns, route)
        else:
            yield route, pattern


_PLACEHOLDERS = {"int": "999999", "uuid": "00000000-0000-0000-0000-000000000001"}


def _fill(route: str) -> str:
    """Replace path converters with a placeholder that matches them (``<int:id>`` -> ``999999``)."""
    return re.sub(r"<(?:(\w+):)?\w+>", lambda match: _PLACEHOLDERS.get(match.group(1), "x"), route)


def _paginated_list_paths() -> dict[str, bool]:
    """Path -> whether it needs a parent object (its route had path converters)."""
    paths: dict[str, bool] = {}
    for route, pattern in _routes(get_resolver().url_patterns):
        if not route.startswith(PREFIX) or "(" in route:
            continue
        contract = getattr(getattr(pattern.callback, "cls", None), "get_contract", None)
        success = getattr(getattr(contract, "responses", None), "success", None)
        if getattr(success, "is_paginated", False):
            paths["/" + _fill(route)] = "<" in route
    return dict(sorted(paths.items()))


PAGINATED_LISTS = _paginated_list_paths()
COLLECTIONS = [path for path, nested in PAGINATED_LISTS.items() if not nested]
NESTED = [path for path, nested in PAGINATED_LISTS.items() if nested]

# Lists that reject a request without one of their own parameters.
REQUIRED_QUERY = {"/api/labs/equipment/facets": {"dimension": "kind"}}


@pytest.fixture
def admin_client():
    client = APIClient()
    client.raise_request_exception = False
    user = get_user_model().objects.create_user(username="list-page-params-admin", is_staff=True, is_superuser=True)
    client.force_authenticate(user)
    return client


def test_paginated_lists_are_discovered():
    # Guards the discovery itself: an empty parametrization would silently pass.
    assert "/api/labs/downtimes" in COLLECTIONS
    assert len(COLLECTIONS) >= 20
    assert len(NESTED) >= 10


@pytest.mark.parametrize("path", COLLECTIONS)
def test_list_accepts_page_and_page_size(admin_client, path):
    response = admin_client.get(path, {**REQUIRED_QUERY.get(path, {}), "page": 1, "page_size": 100})

    assert response.status_code == 200, response.content
    assert response.json()["meta"]["pagination"]["page_size"] == 100


@pytest.mark.parametrize(
    ("path", "filters"),
    [
        ("/api/labs/downtimes", {"resource_type": "station", "resource_id": 1}),
        ("/api/labs/downtimes", {"state": "current"}),
    ],
)
def test_filtered_list_accepts_page_and_page_size(admin_client, path, filters):
    response = admin_client.get(path, {**filters, "page": 1, "page_size": 100})

    assert response.status_code == 200, response.content


@pytest.mark.parametrize("path", NESTED)
def test_nested_list_accepts_page_and_page_size(admin_client, path):
    """Without a parent row the list answers 404, never a 500 or a rejected paging query."""
    response = admin_client.get(path, {"page": 1, "page_size": 100})

    assert response.status_code in (200, 404), response.content
