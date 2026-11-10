"""A unique disposable database; dependency tables plus the actual additive migration."""

import importlib
from uuid import uuid4

import pytest
from django.apps import apps
from django.conf import settings
from django.db import connection
from django.db.migrations.state import ProjectState


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    if settings.SETTINGS_MODULE != "tests.notification_postgres_settings":
        pytest.skip("Requires explicitly opted-in disposable notification PostgreSQL settings.")
    assert connection.settings_dict["HOST"] == "127.0.0.1"
    assert connection.settings_dict["PORT"] == "55439"
    assert connection.settings_dict["USER"] == "notification_disposable_test"
    from core.labs.models import BookingNotification

    pending = [BookingNotification]
    models = set()
    while pending:
        model = pending.pop()
        if model in models:
            continue
        models.add(model)
        for field in (*model._meta.local_fields, *model._meta.local_many_to_many):
            if field.is_relation and field.related_model is not None:
                pending.append(field.related_model)
    models.remove(BookingNotification)
    name = "test_notification_disposable_" + uuid4().hex
    original_name = connection.settings_dict["NAME"]
    with django_db_blocker.unblock():
        with connection._nodb_cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {connection.ops.quote_name(name)}")
        connection.close()
        connection.settings_dict["NAME"] = name
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            with connection.schema_editor() as editor:
                for model in sorted(models, key=lambda value: value._meta.label):
                    editor.create_model(model)
            state = ProjectState.from_apps(apps)
            state.remove_model("labs", "bookingnotification")
            migration = importlib.import_module("core.labs.migrations.0005_booking_notification").Migration("0005", "labs")
            with connection.schema_editor() as editor:
                migration.apply(state, editor)
            yield
        finally:
            connection.close()
            connection.settings_dict["NAME"] = original_name
            with connection._nodb_cursor() as cursor:
                cursor.execute(f"DROP DATABASE {connection.ops.quote_name(name)}")
