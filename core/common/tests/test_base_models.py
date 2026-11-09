"""
Tests for UserStampedModel and TimestampedSoftDeleteMixin.

UserStampedModel is tested through websocket.Notification, a concrete model
that inherits it and is already migrated.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.utils import timezone

from core.common.models import TimestampedSoftDeleteMixin
from core.users.tests.factories import UserFactory
from core.websocket.models import Notification


def _new_notification() -> Notification:
    return Notification(message="test", expiry_date=timezone.now() + timedelta(days=1))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_request(user):
    """Build a minimal mock request object with an authenticated user."""

    class _MockRequest:
        user: object  # satisfies mypy

    req = _MockRequest()
    req.user = user
    return req


def make_anon_request():
    """Build a minimal mock request with an anonymous user."""

    class _AnonUser:
        is_authenticated = False

    class _MockRequest:
        user = _AnonUser()

    return _MockRequest()


# ---------------------------------------------------------------------------
# UserStampedModel
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestUserStampedModel:
    def test_creator_set_on_first_save(self, db):
        user = UserFactory()
        note = _new_notification()
        note.save(request=make_request(user))
        note.refresh_from_db()

        assert note.creator_id == user.pk  # type: ignore[attr-defined]

    def test_last_modified_by_updated_on_each_save(self, db):
        user1 = UserFactory()
        user2 = UserFactory()

        note = _new_notification()
        note.save(request=make_request(user1))
        assert note.last_modified_by_id == user1.pk  # type: ignore[attr-defined]

        note.message = "updated"
        note.save(request=make_request(user2))
        assert note.last_modified_by_id == user2.pk  # type: ignore[attr-defined]

    def test_creator_not_overwritten_on_update(self, db):
        user1 = UserFactory()
        user2 = UserFactory()

        note = _new_notification()
        note.save(request=make_request(user1))
        original_creator_id = note.creator_id

        note.message = "updated"
        note.save(request=make_request(user2))
        # creator must not change
        assert note.creator_id == original_creator_id

    def test_explicit_actor_is_saved_with_update_fields(self, db):
        creator = UserFactory()
        editor = UserFactory()
        note = _new_notification()
        note.save(actor=creator)

        note.message = "updated"
        note.save(actor=editor, update_fields=["message"])
        note.refresh_from_db()

        assert note.creator_id == creator.pk
        assert note.last_modified_by_id == editor.pk
        assert note.message == "updated"

    def test_save_without_request_sets_no_user(self, db):
        note = _new_notification()
        note.save()  # no request kwarg
        assert note.creator_id is None
        assert note.last_modified_by_id is None

    def test_save_with_anonymous_user_sets_no_user(self, db):
        note = _new_notification()
        note.save(request=make_anon_request())
        assert note.creator_id is None
        assert note.last_modified_by_id is None


class TestTimestampedSoftDeleteMixin:
    """Tests for the timestamp-based soft-delete contract."""

    def _make_instance(self, *, deleted_at=None):
        concrete = type(
            "TimestampedFakeModel",
            (TimestampedSoftDeleteMixin,),
            {
                "__module__": __name__,
                "Meta": type("Meta", (), {"app_label": "common", "abstract": False}),
            },
        )
        obj = concrete.__new__(concrete)  # type: ignore[call-overload]
        obj.pk = 1
        obj.deleted_at = deleted_at
        return obj

    def test_soft_delete_sets_timestamp_and_saves_only_timestamp(self):
        obj = self._make_instance()
        with patch.object(type(obj), "save") as mock_save:
            deleted_count, details = obj.soft_delete()

        assert obj.deleted_at is not None
        assert deleted_count == 1
        assert details == {"common.TimestampedFakeModel": 1}
        mock_save.assert_called_once_with(actor=None, using=None, update_fields=("deleted_at",))

    def test_soft_delete_is_idempotent(self):
        deleted_at = timezone.now()
        obj = self._make_instance(deleted_at=deleted_at)
        with patch.object(type(obj), "save") as mock_save:
            result = obj.soft_delete()

        assert result == (0, {})
        assert obj.deleted_at == deleted_at
        mock_save.assert_not_called()

    def test_restore_clears_timestamp(self):
        obj = self._make_instance(deleted_at=timezone.now())
        with patch.object(type(obj), "save") as mock_save:
            restored = obj.restore()

        assert restored is True
        assert obj.deleted_at is None
        mock_save.assert_called_once_with(actor=None, using=None, update_fields=("deleted_at",))

    def test_instance_delete_is_soft_delete(self):
        obj = self._make_instance()
        with patch.object(type(obj), "save"):
            count, details = obj.delete()

        assert obj.deleted_at is not None
        assert count == 1
        assert details == {"common.TimestampedFakeModel": 1}

    def test_hard_delete_calls_django_model_delete(self):
        obj = self._make_instance()
        with patch("django.db.models.Model.delete", return_value=(1, {"common.TimestampedFakeModel": 1})) as delete:
            result = obj.hard_delete()

        assert result == (1, {"common.TimestampedFakeModel": 1})
        delete.assert_called_once_with(obj, using=None, keep_parents=False)
