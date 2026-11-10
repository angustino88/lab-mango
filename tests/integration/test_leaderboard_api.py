"""
Integration tests for leaderboard & analytics feature.

Uses Django test client with test DB. No live server required.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from rest_framework.test import APIClient

from tests.factories import (
    UserFactory,
)


@pytest.fixture()
def analytics_user(db):
    return UserFactory(username="analyticsuser")


@pytest.fixture()
def analytics_client(analytics_user):
    client = APIClient()
    client.force_authenticate(user=analytics_user)
    return client


_PATCH_APIKEY = "rest_framework_api_key.permissions.HasAPIKey.has_permission"


# ---------------------------------------------------------------------------
# GET /api/labs/leaderboard/persona
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestLeaderboardPersona:
    async def test_unauthenticated_returns_401_or_403(self):
        from django.test import AsyncClient

        response = await AsyncClient().get("/api/labs/leaderboard/persona")
        assert response.status_code in (401, 403)

    async def test_authenticated_returns_200(self):
        from django.test import AsyncClient

        with patch(_PATCH_APIKEY, return_value=True):
            response = await AsyncClient().get("/api/labs/leaderboard/persona")
        assert response.status_code == 200

    async def test_with_date_range(self):
        from django.test import AsyncClient

        with patch(_PATCH_APIKEY, return_value=True):
            response = await AsyncClient().get(
                "/api/labs/leaderboard/persona",
                {"start_date": "2026-04-01", "end_date": "2026-04-20"},
            )
        assert response.status_code == 200

    async def test_blank_display_name_returns_200(self, db):
        from asgiref.sync import sync_to_async
        from django.test import AsyncClient

        await sync_to_async(UserFactory)(username="blank-display-name", display_name="")
        with patch(_PATCH_APIKEY, return_value=True):
            response = await AsyncClient().get(
                "/api/labs/leaderboard/persona",
                {"start_date": "2026-10-01", "end_date": "2026-10-01"},
            )
        assert response.status_code == 200

    def test_compute_leaderboard_persona_scopes_users_to_session_window(self, db):
        from datetime import datetime
        from datetime import timezone as dt_timezone

        from core.labs.features.leaderboard.queries.selectors import compute_leaderboard_persona
        from tests.factories import LabSessionLogFactory

        active_user = UserFactory(username="active-pilot", display_name="Active Pilot")
        UserFactory(username="inactive-user", display_name="Inactive User")

        start = datetime(2026, 4, 1, 0, 0, tzinfo=dt_timezone.utc)
        end = datetime(2026, 4, 30, 23, 59, tzinfo=dt_timezone.utc)

        LabSessionLogFactory(
            remote_user=active_user.username,
            login_time=datetime(2026, 4, 10, 8, 0, tzinfo=dt_timezone.utc),
            logout_time=datetime(2026, 4, 10, 12, 0, tzinfo=dt_timezone.utc),
        )

        results = compute_leaderboard_persona(start, end)
        usernames = [r["username"] for r in results]
        assert "active-pilot" in usernames
        assert "inactive-user" not in usernames


# ---------------------------------------------------------------------------
# GET /api/labs/leaderboard/lab
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestLeaderboardLab:
    async def test_unauthenticated_returns_401_or_403(self):
        from django.test import AsyncClient

        response = await AsyncClient().get("/api/labs/leaderboard/lab")
        assert response.status_code in (401, 403)

    async def test_authenticated_returns_200(self):
        from django.test import AsyncClient

        with patch(_PATCH_APIKEY, return_value=True):
            response = await AsyncClient().get("/api/labs/leaderboard/lab")
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /api/labs/profile/<id>
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestLabProfile:
    async def test_unauthenticated_returns_401_or_403(self):
        from django.test import AsyncClient

        for url in ("/api/labs/profile/1", "/api/labs/benches/1/profile"):
            response = await AsyncClient().get(url)
            assert response.status_code in (401, 403)

    async def test_nonexistent_lab_returns_404(self):
        from django.test import AsyncClient

        with patch(_PATCH_APIKEY, return_value=True):
            response_canon = await AsyncClient().get("/api/labs/benches/99999/profile")
            assert response_canon.status_code == 404

            response_alias = await AsyncClient().get("/api/labs/profile/99999")
            assert response_alias.status_code == 404
            assert response_alias.headers.get("Deprecation") == "true"
            assert "Sunset" in response_alias.headers
            assert "/api/labs/benches/99999/profile" in response_alias.headers.get("Link", "")


# ---------------------------------------------------------------------------
# GET /api/labs/users/profile/<id>
# ---------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
class TestUserProfile:
    async def test_unauthenticated_returns_401_or_403(self):
        from django.test import AsyncClient

        for url in ("/api/labs/users/profile/1", "/api/labs/leaderboard/users/1/profile"):
            response = await AsyncClient().get(url)
            assert response.status_code in (401, 403)

    async def test_nonexistent_user_returns_404(self):
        from django.test import AsyncClient

        with patch(_PATCH_APIKEY, return_value=True):
            response_canon = await AsyncClient().get("/api/labs/leaderboard/users/99999/profile")
            assert response_canon.status_code == 404

            response_alias = await AsyncClient().get("/api/labs/users/profile/99999")
            assert response_alias.status_code == 404
            assert response_alias.headers.get("Deprecation") == "true"
            assert "Sunset" in response_alias.headers
            assert "/api/labs/leaderboard/users/99999/profile" in response_alias.headers.get("Link", "")
