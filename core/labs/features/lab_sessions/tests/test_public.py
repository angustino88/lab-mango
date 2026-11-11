"""The lab sessions public surface other packages may rely on."""

import inspect

from core.labs.features.lab_sessions import public
from core.labs.features.lab_sessions.public import (
    RecordSessionLogInput,
    SessionLogConflict,
    SessionLogEquipmentUnavailable,
    SessionLogInvalid,
    SessionLogRecord,
    record_session_log,
)


def test_public_exports():
    assert set(public.__all__) == {
        "MAX_CLOCK_AHEAD",
        "MAX_SESSION_AGE",
        "RecordSessionLogInput",
        "SessionLogConflict",
        "SessionLogEquipmentUnavailable",
        "SessionLogInvalid",
        "SessionLogRecord",
        "record_session_log",
    }


def test_input_and_result_are_frozen():
    for cls in (RecordSessionLogInput, SessionLogRecord):
        assert getattr(cls, "__dataclass_params__").frozen, cls.__name__


def test_actor_is_keyword_only():
    parameter = inspect.signature(record_session_log).parameters["actor"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY


def test_error_codes_are_stable():
    assert SessionLogConflict.code == "session_log_conflict"
    assert SessionLogEquipmentUnavailable.code == "equipment_unavailable"
    assert SessionLogInvalid.code == "validation_failed"


def test_limits_match_owner_decision():
    assert public.MAX_CLOCK_AHEAD.total_seconds() == 5 * 60
    assert public.MAX_SESSION_AGE.days == 7
