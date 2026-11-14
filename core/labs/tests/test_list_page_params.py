"""Every paginated labs list accepts ``page`` and ``page_size`` beside its own filters.

``validate_query()`` returns the paging values with the filters whenever a query serializer declares them
(``with_page_query``, ``PageNumberQuerySerializer``). A handler that forwards the validated values to a
selector must drop them first, or the request fails with a 500 (``list_downtimes() got an unexpected
keyword argument 'page'``). The endpoints are discovered from the URL configuration so a new paginated
list is covered without editing this file.
"""

import pytest
from django.contrib.auth import get_user_model
from django.urls import get_resolver
from rest_framework.test import APIClient

pytestmark = pytest.mark.django_db

PREFIX = "api/labs/"


def _routes(patterns, prefix=""):
    for pattern in patterns:
        route = prefix + str(pattern.pattern)
        if hasattr(pattern, "url_patterns"):
            yield from _routes(pattern.url_patterns, route)
        else:
            yield route, pattern


def _paginated_list_paths() -> list[str]:
    paths = set()
    for route, pattern in _routes(get_resolver().url_patterns):
        if not route.startswith(PREFIX) or "<" in route or "(" in route:
            continue
        contract = getattr(getattr(pattern.callback, "cls", None), "get_contract", None)
        success = getattr(getattr(contract, "responses", None), "success", None)
        if getattr(success, "is_paginated", False):
            paths.add("/" + route)
    return sorted(paths)


PAGINATED_LISTS = _paginated_list_paths()

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
    assert "/api/labs/downtimes" in PAGINATED_LISTS
    assert len(PAGINATED_LISTS) >= 20


@pytest.mark.parametrize("path", PAGINATED_LISTS)
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
