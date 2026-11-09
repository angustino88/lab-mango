"""Public exports supported by the bench booking feature."""

from core.labs.features.bench_bookings import public


def test_agent_end_time_command_is_exported():
    assert "AgentBookingEndTimeInput" in public.__all__
    assert "update_agent_booking_end_time" in public.__all__
    assert public.AgentBookingEndTimeInput is not None
    assert public.update_agent_booking_end_time is not None
