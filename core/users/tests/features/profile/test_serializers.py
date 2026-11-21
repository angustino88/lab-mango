"""Unit tests for UserSerializer display_name fallback."""

from core.users.features.profile.serializers import UserSerializer
from core.users.models import User


def test_user_serializer_prefers_display_name():
    user = User(username="uah2hc", display_name="Display Name", name="Full Name", first_name="First", last_name="Last")
    assert UserSerializer(user).data["display_name"] == "Display Name"


def test_user_serializer_falls_back_to_name_then_full_name():
    user_with_name = User(username="uah2hc", display_name="", name="Name Field", first_name="First", last_name="Last")
    assert UserSerializer(user_with_name).data["display_name"] == "Name Field"

    user_with_first_last = User(username="uah2hc", display_name="", name="", first_name="Nguyen", last_name="An")
    assert UserSerializer(user_with_first_last).data["display_name"] == "Nguyen An"

    user_without_names = User(username="uah2hc", display_name="", name="")
    assert UserSerializer(user_without_names).data["display_name"] == ""
