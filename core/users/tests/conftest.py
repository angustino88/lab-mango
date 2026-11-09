import pytest
from asgiref.sync import sync_to_async
from django.contrib.auth import get_user_model
from django.test import AsyncClient, Client
from rest_framework_simplejwt.tokens import RefreshToken

from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

User = get_user_model()


@pytest.fixture
def user(db) -> User:
    return UserFactory(username="testuser", password="testpass123")


@pytest.fixture
def admin_user(db) -> User:
    return UserFactory(
        username="adminlab",
        password="adminlab",
        is_staff=True,
        is_superuser=True,
    )


@pytest.fixture
def inactive_user(db) -> User:
    return UserFactory(username="inactive", password="testpass123", is_active=False)


@pytest.fixture
def group(db):
    return GroupFactory(name="test-group")


@pytest.fixture
def urs_group(db, group):
    return URSGroupFactory(group=group)


@pytest.fixture
def api_client() -> AsyncClient:
    return AsyncClient()


@pytest.fixture
def auth_client(db) -> AsyncClient:
    """AsyncClient pre-authenticated as a regular user."""
    client = AsyncClient()
    return client


@pytest.fixture
def sync_client() -> Client:
    return Client()


async def make_access_token(user) -> str:
    """Create a JWT access token for a user — safe to call from async test bodies.

    token_blacklist writes an OutstandingToken row on creation, so this must
    be wrapped in sync_to_async when called from an async context.
    """
    def _create():
        refresh = RefreshToken.for_user(user)
        return str(refresh.access_token)
    return await sync_to_async(_create)()
