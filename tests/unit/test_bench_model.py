import pytest
from django.core.exceptions import FieldDoesNotExist, ValidationError
from django.db import IntegrityError, models, transaction

from core.common.models import TimestampedSoftDeleteManager, TimestampedSoftDeleteQuerySet
from core.labs.models.resource.bench import Bench, BenchFavorite, BenchGroup, BenchType
from core.labs.models.resource.location.room import Room
from core.labs.models.resource.location.station import Station


def test_bench_setup_location_path_is_derived_from_station():
    room = Room(pk=1, sku="RM-01")
    station = Station(pk=1, sku="ST-01", room=room)
    bench = Bench(sku="BN-01", setup_location=station)

    assert bench.setup_location_path == "RM-01-ST-01"
    assert Bench(sku="BN-02").setup_location_path == ""


@pytest.mark.parametrize("model", [BenchGroup, BenchType])
def test_bench_reference_data(model):
    instance = model(name="Functional testing")

    assert str(instance) == "Functional testing"
    assert instance.description == ""
    assert instance.active is True
    assert model._meta.get_field("name").unique
    with pytest.raises(ValidationError):
        model._meta.get_field("name").clean("", instance)


@pytest.mark.parametrize(
    ("name", "sku", "expected"),
    [("Test setup", "BN-01", "Test setup"), ("", "BN-01", "BN-01"), ("", "", "Unnamed bench")],
)
def test_bench_display_name(name, sku, expected):
    assert str(Bench(name=name, sku=sku)) == expected


def test_bench_uses_timestamped_deletion():
    assert isinstance(Bench.objects, TimestampedSoftDeleteManager)
    assert isinstance(Bench.objects.all(), TimestampedSoftDeleteQuerySet)
    assert "deleted_at" in str(Bench.objects.all().query)
    assert "IS NULL" in str(Bench.objects.all().query)
    assert not Bench.all_objects.all().query.where
    with pytest.raises(FieldDoesNotExist):
        Bench._meta.get_field("is_delete")


@pytest.mark.parametrize("field_name", ["setup_location", "type", "bench_group"])
def test_bench_references_are_protected(field_name):
    field = Bench._meta.get_field(field_name)

    assert field.remote_field.on_delete is models.PROTECT
    assert field.null and field.blank


@pytest.mark.parametrize("field_name", ["label", "location_name", "location_url", "station", "unit", "technical_user"])
def test_bench_has_no_legacy_fields(field_name):
    with pytest.raises(FieldDoesNotExist):
        Bench._meta.get_field(field_name)


@pytest.mark.parametrize("method_name", ["get_current_equipment", "get_status", "get_lab_audit"])
def test_bench_has_no_legacy_record_creation_helpers(method_name):
    assert not hasattr(Bench, method_name)


def test_bench_documentation_url_validation():
    bench = Bench(sku="BN-01")
    field = Bench._meta.get_field("documentation_url")

    assert field.clean("https://example.com/bench", bench) == "https://example.com/bench"
    assert field.clean("", bench) == ""
    with pytest.raises(ValidationError):
        field.clean("not a URL", bench)


def test_favorite_requires_a_bench_and_uses_normal_deletion():
    field = BenchFavorite._meta.get_field("bench")

    assert not field.null and not field.blank
    assert field.remote_field.on_delete is models.CASCADE
    assert BenchFavorite.delete is models.Model.delete
    with pytest.raises(FieldDoesNotExist):
        BenchFavorite._meta.get_field("is_delete")


@pytest.mark.django_db
def test_bench_soft_delete_and_restore():
    bench = Bench.objects.create(sku="BN-01")

    assert bench.delete() == (1, {"labs.Bench": 1})
    assert not Bench.objects.filter(pk=bench.pk).exists()
    assert Bench.all_objects.get(pk=bench.pk).deleted_at is not None
    assert bench.restore()
    assert Bench.objects.filter(pk=bench.pk).exists()


@pytest.mark.django_db
def test_virtual_benches_can_share_a_setup_location():
    station = Station.objects.create(sku="ST-01")
    first = Bench.objects.create(sku="BN-01", setup_location=station)
    second = Bench.objects.create(sku="BN-02", setup_location=station)

    assert {first.pk, second.pk} == set(Bench.objects.values_list("pk", flat=True))


@pytest.mark.django_db
@pytest.mark.parametrize("model", [BenchGroup, BenchType])
def test_reference_names_cannot_be_empty_in_database(model):
    with pytest.raises(IntegrityError), transaction.atomic():
        model.objects.create(name="")


@pytest.mark.django_db
def test_favorite_uniqueness_and_removal(user):
    bench = Bench.objects.create(sku="BN-01")
    favorite = BenchFavorite.objects.create(user=user, bench=bench)

    with pytest.raises(IntegrityError), transaction.atomic():
        BenchFavorite.objects.create(user=user, bench=bench)

    favorite.delete()
    assert not BenchFavorite.objects.filter(user=user, bench=bench).exists()
    assert Bench.objects.filter(pk=bench.pk).exists()
    BenchFavorite.objects.create(user=user, bench=bench)
