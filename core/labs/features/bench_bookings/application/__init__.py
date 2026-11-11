"""Supported bench booking commands and their frozen inputs."""

from .check_agent_booking_login import CheckAgentBookingLoginInput, check_agent_booking_login
from .check_in_agent_booking import CheckInAgentBookingInput, check_in_agent_booking
from .create_booking import CreateBenchBookingInput, create_bench_booking
from .decide_booking_approval import (
    DecideBenchBookingApprovalInput,
    DecideBenchBookingApprovalResult,
    decide_bench_booking_approval,
)
from .state_transitions import (
    activate_bench_booking_for_computing_activity,
    activate_bench_bookings,
    reconcile_bench_booking_statuses,
)
from .update_agent_booking_end_time import AgentBookingEndTimeInput, update_agent_booking_end_time
from .update_booking import UpdateBenchBookingInput, update_bench_booking

__all__ = [
    "CheckAgentBookingLoginInput",
    "CheckInAgentBookingInput",
    "CreateBenchBookingInput",
    "DecideBenchBookingApprovalInput",
    "DecideBenchBookingApprovalResult",
    "AgentBookingEndTimeInput",
    "UpdateBenchBookingInput",
    "activate_bench_booking_for_computing_activity",
    "activate_bench_bookings",
    "check_agent_booking_login",
    "check_in_agent_booking",
    "create_bench_booking",
    "decide_bench_booking_approval",
    "reconcile_bench_booking_statuses",
    "update_bench_booking",
    "update_agent_booking_end_time",
]
