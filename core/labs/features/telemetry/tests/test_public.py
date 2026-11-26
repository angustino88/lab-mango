"""The telemetry public facade exports exactly its supported surface."""

import dataclasses

from core.labs.features.telemetry import public


def test_public_exports_are_explicit():
    assert set(public.__all__) == {
        "CurrentConditions",
        "IngestOperation",
        "IngestReading",
        "IngestResult",
        "Placement",
        "TargetRef",
        "current_conditions",
        "ingest_samples",
        "resolve_placement",
    }
    for name in public.__all__:
        assert hasattr(public, name)


def test_placement_is_an_immutable_dto():
    placement = public.Placement(room_id=1, station_id=None)
    assert dataclasses.is_dataclass(placement)
    try:
        placement.room_id = 2  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        return
    raise AssertionError("Placement must be frozen")
