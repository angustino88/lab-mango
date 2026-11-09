"""Procurement API permissions: lab admins and API keys have full access; other users are denied."""

import itertools
from unittest.mock import patch

import pytest
from django.contrib.auth.models import Group

from core.users.models import URSGroup

pytestmark = pytest.mark.django_db

_URS_SEQUENCE = itertools.count(1000)
_PURCHASES_URL = "/api/labs/purchases"
_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


def _client_with_role(api_client, user, role):
    group, _ = Group.objects.get_or_create(name=f"lab-{role}")
    URSGroup.objects.create(
        group=group,
        urs_group_id=next(_URS_SEQUENCE),
        labs_role=role,
    )
    user.groups.add(group)
    api_client.force_authenticate(user=user)
    return api_client


class TestProcurementAccess:
    def test_admin_can_read_purchases(self, api_client, user):
        client = _client_with_role(api_client, user, "admin")
        assert client.get(_PURCHASES_URL).status_code == 200

    def test_coordinator_can_read_purchases(self, api_client, user):
        client = _client_with_role(api_client, user, "coord")
        assert client.get(_PURCHASES_URL).status_code == 200

    def test_plain_user_cannot_create_purchase(self, api_client, user):
        api_client.force_authenticate(user=user)
        response = api_client.post(_PURCHASES_URL, {}, format="json")
        assert response.status_code == 403

    def test_api_key_can_read_purchases(self, api_client):
        with patch(_PATCH_APIKEY, return_value=True):
            response = api_client.get(_PURCHASES_URL)
        assert response.status_code == 200, response.content
