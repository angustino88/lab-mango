"""Opt-in isolated PostgreSQL schema for bench/station regression tests.

Load as a pytest plugin only with config.settings.feature_test. Build just the
feature models and their forward dependencies, keeping broken legacy migration
imports and unrelated computing indexes out of this narrowly scoped test.
"""

from uuid import uuid4

import pytest
from django.conf import settings
from django.db import connection


@pytest.fixture(scope="session")
def django_db_setup(django_db_blocker):
    if settings.SETTINGS_MODULE != "config.settings.feature_test":
        raise RuntimeError("The feature database plugin requires isolated feature_test settings.")
    from rest_framework_api_key.models import APIKey

    from core.labs.models import (
        ActiveLaboratoryObservation,
        ActiveUserObservation,
        Bench,
        BenchFavorite,
        BenchGroup,
        BenchType,
        BookingVolumeObservation,
        EquipmentAssignment,
        EquipmentEvent,
        ExpensePayment,
        LaboratoryVisitEvent,
        LabSessionLog,
        PurchaseItemResource,
        PurchaseTransaction,
        Station,
        StationSlot,
        StationStatusRecord,
        StationType,
        StorageQuotaMeasurement,
        VisitorVolumeObservation,
    )

    pending = [
        Bench, BenchFavorite, BenchGroup, BenchType, EquipmentAssignment, EquipmentEvent,
        Station, StationSlot, StationStatusRecord, StationType,
        ActiveLaboratoryObservation, ActiveUserObservation, BookingVolumeObservation,
        ExpensePayment, LaboratoryVisitEvent, LabSessionLog, PurchaseItemResource,
        PurchaseTransaction, StorageQuotaMeasurement, VisitorVolumeObservation,
        APIKey,
    ]
    models = set()
    while pending:
        model = pending.pop()
        if model in models:
            continue
        models.add(model)
        for field in (*model._meta.local_fields, *model._meta.local_many_to_many):
            if field.is_relation and field.related_model is not None:
                pending.append(field.related_model)

    name = f"test_labmango_features_{uuid4().hex}"
    original_name = connection.settings_dict["NAME"]
    with django_db_blocker.unblock():
        # Only the dedicated synthetic-role loopback cluster is permitted here.
        assert connection.settings_dict["HOST"] == "127.0.0.1"
        assert connection.settings_dict["USER"] == "labmango_feature_test"
        with connection._nodb_cursor() as cursor:
            cursor.execute(f"CREATE DATABASE {connection.ops.quote_name(name)}")
        connection.close()
        connection.settings_dict["NAME"] = name
        try:
            with connection.cursor() as cursor:
                cursor.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
            with connection.schema_editor() as editor:
                for model in sorted(models, key=lambda item: item._meta.label):
                    editor.create_model(model)
            yield
        finally:
            connection.close()
            connection.settings_dict["NAME"] = original_name
            with connection._nodb_cursor() as cursor:
                cursor.execute(f"DROP DATABASE {connection.ops.quote_name(name)}")
