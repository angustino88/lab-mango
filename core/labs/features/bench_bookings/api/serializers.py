"""Explicit bench booking transport fields; all writes go through commands."""

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.filtering import CSVField, PositiveIDField, QueryDateTimeField, StrictBooleanField
from core.common.api.options import OptionsQueryMixin
from core.common.api.pagination import PageNumberQuerySerializer
from core.common.api.search import SearchQueryMixin
from core.common.api.summary_serializers import UserReferenceSerializer
from core.common.api.temporal_query import TemporalBoundField, TemporalRangeQueryMixin
from core.labs.features.base.serializers import (
    AppModelSerializer,
    ChoiceReferenceSerializer,
    NamedReferenceSerializer,
    UIDNamedReferenceSerializer,
    to_choice_reference,
)
from core.labs.features.bench_bookings.application import BookingPeriod
from core.labs.features.bench_bookings.queries.availability import MAX_WINDOW as MAX_AVAILABILITY_WINDOW
from core.labs.features.bench_bookings.queries.slot_watches import slot_availability
from core.labs.models import (
    BenchBooking,
    BenchSlotWatch,
    BookingApprovalStatus,
    BookingStatus,
    LabProject,
    SlotWatchStatus,
)
from core.users.public import LabsPermission, has_permission

_ORDERING_HELP = (
    "Use unique comma-separated fields from starts_at, ends_at, created_at, id; "
    "prefix a field with '-' for descending."
)


class BenchBookingCreateSerializer(serializers.Serializer):
    bench_id = serializers.IntegerField(min_value=1)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    reason = serializers.CharField(allow_blank=False, trim_whitespace=True)
    project_id = serializers.IntegerField(min_value=1)


class BenchBookingUpdateSerializer(serializers.Serializer):
    """Partial update payload; the command enforces which fields may change in each state."""

    bench_id = serializers.IntegerField(min_value=1, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True)
    project_id = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    status = serializers.CharField(read_only=True)


class BenchBookingCancelActionSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, default="Cancelled by user")


class BenchBookingRejectActionSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=True,
        allow_blank=False,
        trim_whitespace=True,
        max_length=500,
    )


class BenchBookingSerializer(AppModelSerializer):
    creator = UserReferenceSerializer(read_only=True, allow_null=True)
    bench = UIDNamedReferenceSerializer(read_only=True)
    project = NamedReferenceSerializer(read_only=True, allow_null=True)
    status = serializers.SerializerMethodField(read_only=True)
    approval_status = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = BenchBooking
        fields = (
            "id",
            "booking_code",
            "creator",
            "bench",
            "starts_at",
            "ends_at",
            "completed_at",
            "status",
            "approval_status",
            "project",
            "reason",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    def to_representation(self, instance):
        """The booking code is a login credential for the agent: only its creator and coordinators see it.

        Without a request in the context (internal projection) the row is returned unchanged.
        """
        data = super().to_representation(instance)
        request = self.context.get("request")
        actor = getattr(request, "user", None)
        if request is not None and not (
            getattr(actor, "is_authenticated", False)
            and (instance.creator_id == actor.pk or has_permission(actor, LabsPermission.BENCH_BOOKING_MANAGE_ANY))
        ):
            data["booking_code"] = ""
        return data

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "status", None), BookingStatus.choices)

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_approval_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(getattr(obj, "approval_status", None))


class BenchBookingListQuerySerializer(TemporalRangeQueryMixin, PageNumberQuerySerializer):
    """Allowlisted list filters and ordering, including strict calendar-window bounds."""

    temporal_range_fields = ("starts_at_after", "starts_at_before")

    view_side = serializers.ChoiceField(choices=("my_booking", "booking_calendar"), required=False)
    creator_id = serializers.IntegerField(required=False, min_value=1)
    bench_id = serializers.IntegerField(required=False, min_value=1)
    project_id = serializers.IntegerField(required=False, min_value=1)
    status = serializers.CharField(required=False)
    approval_status = serializers.CharField(required=False)
    booking_code = serializers.CharField(required=False)
    q = serializers.CharField(required=False)
    ordering = serializers.CharField(
        required=False,
        allow_blank=False,
        trim_whitespace=False,
        help_text=(
            "Comma-separated ordering fields: starts_at, ends_at, created_at, id; prefix with '-' for descending. "
            "Defaults to -starts_at,-id. An id tie-breaker is added when omitted."
        ),
    )
    starts_at_after = TemporalBoundField(
        required=False,
        help_text=(
            "Inclusive lower bound. Accepts strict YYYY-MM-DD in Django TIME_ZONE or an offset-aware "
            "RFC3339 datetime (YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM))."
        ),
    )
    starts_at_before = TemporalBoundField(
        required=False,
        help_text=(
            "Exclusive upper bound. Accepts strict YYYY-MM-DD in Django TIME_ZONE or an offset-aware "
            "RFC3339 datetime (YYYY-MM-DDTHH:MM:SS[.fraction](Z|±HH:MM)). A date-only value is midnight "
            "at the start of that date; to include November 2–8, use starts_at_after=2026-11-02 and "
            "starts_at_before=2026-11-09."
        ),
    )

    def to_internal_value(self, data):
        """Reject duplicate singleton keys before QueryDict's last-value coercion."""
        if hasattr(data, "getlist"):
            duplicate_keys = [key for key in data if len(data.getlist(key)) > 1]
            if duplicate_keys:
                raise serializers.ValidationError(
                    {
                        key: serializers.ErrorDetail("This parameter must not be repeated.", code="invalid_query")
                        for key in duplicate_keys
                    }
                )
            # DRF drops blank optional values from form-style input, which would make
            # ``?ordering=`` silently fall back to the default order.
            if data.get("ordering") == "":
                raise serializers.ValidationError(
                    {"ordering": serializers.ErrorDetail(_ORDERING_HELP, code="invalid_query")}
                )
        return super().to_internal_value(data)

    def validate_ordering(self, value):
        allowed = {"starts_at", "ends_at", "created_at", "id"}
        fields = value.split(",")
        normalized = [field[1:] if field.startswith("-") else field for field in fields]
        if any(not field or field != field.strip() or field not in allowed for field in normalized) or len(
            set(normalized)
        ) != len(normalized):
            raise serializers.ValidationError(_ORDERING_HELP, code="invalid_query")
        return fields


class LabProjectQuerySerializer(SearchQueryMixin, PageNumberQuerySerializer):
    search_target = "search"
    # default=None: query strings are HTML input, where an absent boolean would otherwise become False.
    is_active = serializers.BooleanField(required=False, allow_null=True, default=None, source="active")


class LabProjectOptionsQuerySerializer(OptionsQueryMixin):
    active_on = serializers.DateField(required=False, help_text="Date within project start_date and end_date.")


class LabProjectSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source="project_name", read_only=True)
    is_active = serializers.BooleanField(source="active", read_only=True)
    start_date = serializers.DateField(source="starts_on", read_only=True, allow_null=True)
    end_date = serializers.DateField(source="ends_on", read_only=True, allow_null=True)

    class Meta:
        model = LabProject
        fields = ("id", "name", "code", "is_active", "start_date", "end_date")
        read_only_fields = fields
        ref_name = "LabProject"


class BenchBookingCheckPeriodSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()


class BenchBookingCheckRequestSerializer(serializers.Serializer):
    """The create body, or a change to ``booking_id``. Omitted fields of a change keep the booking's values.

    ``reason`` is accepted so the create body can be sent unchanged; it is not checked here.
    """

    booking_id = serializers.IntegerField(min_value=1, required=False)
    bench_id = serializers.IntegerField(min_value=1, required=False)
    starts_at = serializers.DateTimeField(required=False)
    ends_at = serializers.DateTimeField(required=False)
    project_id = serializers.IntegerField(min_value=1, required=False)
    reason = serializers.CharField(required=False, allow_blank=True)
    occurrences = serializers.ListField(
        child=BenchBookingCheckPeriodSerializer(),
        required=False,
        min_length=1,
        max_length=10,
        help_text="A series for a new booking: up to 10 periods, checked one by one. Replaces starts_at/ends_at.",
    )
    suggest_alternatives = serializers.BooleanField(
        required=False,
        default=False,
        help_text="For a period that is not bookable: up to two other benches of the same type, then this bench's "
        "next free slot of the same length within a day.",
    )

    def validate(self, attrs):
        if "booking_id" not in attrs and "bench_id" not in attrs:
            raise serializers.ValidationError({"bench_id": "This field is required."})
        return attrs

    def to_command_kwargs(self) -> dict:
        data = dict(self.validated_data)
        data.pop("reason", None)
        data["occurrences"] = tuple(BookingPeriod(**period) for period in data.get("occurrences", ()))
        return data


class BenchBookingProblemSerializer(serializers.Serializer):
    code = serializers.CharField(read_only=True, help_text="Same code the create or update call returns.")
    field = serializers.CharField(read_only=True, allow_null=True)
    message = serializers.CharField(read_only=True)


class BenchBookingAlternativeSerializer(serializers.Serializer):
    bench = UIDNamedReferenceSerializer(read_only=True)
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)


class BenchBookingCheckResultSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)
    is_bookable = serializers.BooleanField(read_only=True)
    approval_status = serializers.SerializerMethodField(
        help_text="Approval the booking would have after the write; null when the period is invalid."
    )
    problems = BenchBookingProblemSerializer(many=True, read_only=True)
    alternatives = BenchBookingAlternativeSerializer(
        many=True, read_only=True, help_text="Empty unless suggest_alternatives was sent. Free now, not held."
    )

    @extend_schema_field(ChoiceReferenceSerializer(allow_null=True))
    def get_approval_status(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.approval_status, BookingApprovalStatus.choices)


class BenchBookingCheckSerializer(serializers.Serializer):
    """Advice for now: create and update check again under their locks."""

    results = BenchBookingCheckResultSerializer(many=True, read_only=True)
    can_book_all = serializers.BooleanField(read_only=True, help_text="Whether every period is bookable now.")


class BenchSlotWatchPolicySerializer(serializers.Serializer):
    is_enabled = serializers.BooleanField(read_only=True)
    lead_minutes = serializers.IntegerField(read_only=True)
    max_active = serializers.IntegerField(read_only=True)


class BenchBookingPolicySerializer(serializers.Serializer):
    """The booking rules for the caller. ``max_horizon_days`` null means no limit."""

    time_zone = serializers.CharField(read_only=True)
    min_duration_minutes = serializers.IntegerField(read_only=True)
    start_grace_minutes = serializers.IntegerField(read_only=True)
    approval_required_above_minutes = serializers.IntegerField(read_only=True)
    max_horizon_days = serializers.IntegerField(read_only=True, allow_null=True)
    is_computing_required = serializers.BooleanField(read_only=True)
    can_book_during_operator_downtime = serializers.BooleanField(read_only=True)
    can_manage_others_bookings = serializers.BooleanField(read_only=True)
    can_approve = serializers.BooleanField(read_only=True)
    slot_watch = BenchSlotWatchPolicySerializer(read_only=True)


class BenchAvailabilityQuerySerializer(serializers.Serializer):
    starts_at = QueryDateTimeField(help_text="Window start, RFC 3339 with offset.")
    ends_at = QueryDateTimeField(help_text="Window end (exclusive). The window is at most 14 days.")
    bench_id = CSVField(PositiveIDField(), max_items=20, required=False, help_text="Only these benches.")
    type_id = CSVField(PositiveIDField(), required=False)
    bench_group_id = CSVField(PositiveIDField(), required=False)
    setup_location_id = CSVField(PositiveIDField(), required=False, help_text="Station ids.")
    has_computing = StrictBooleanField(required=False)
    q = serializers.CharField(required=False, min_length=1, max_length=100, help_text="Bench name or SKU.")
    mode = serializers.ChoiceField(
        choices=(("fully_free", "Free for the whole window"), ("any_free", "Some free time in the window")),
        required=False,
        default="fully_free",
    )
    min_free_minutes = serializers.IntegerField(
        required=False, min_value=10, max_value=20160, help_text="With mode=any_free: the shortest useful free period."
    )
    limit = serializers.IntegerField(required=False, min_value=1, max_value=20, default=10)

    def validate(self, attrs):
        if attrs["ends_at"] <= attrs["starts_at"]:
            raise serializers.ValidationError({"ends_at": "The window must end after it starts."}, code="invalid")
        if attrs["ends_at"] - attrs["starts_at"] > MAX_AVAILABILITY_WINDOW:
            raise serializers.ValidationError({"ends_at": "The window is at most 14 days."}, code="invalid")
        if "min_free_minutes" in attrs and attrs["mode"] != "any_free":
            raise serializers.ValidationError({"min_free_minutes": "Use with mode=any_free."}, code="invalid")
        return attrs

    @staticmethod
    def to_query_kwargs(validated_data) -> dict:
        data = dict(validated_data)
        mode = data.pop("mode")
        renamed = {"bench_id": "bench_ids", "type_id": "type_ids", "bench_group_id": "bench_group_ids"}
        kwargs = {renamed.get(key, key): value for key, value in data.items() if key != "setup_location_id"}
        kwargs["setup_location_ids"] = data.get("setup_location_id", ())
        kwargs["only_fully_free"] = mode == "fully_free"
        return kwargs


class AvailabilityPeriodSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField(read_only=True)
    ends_at = serializers.DateTimeField(read_only=True)


class AvailabilityBusyPeriodSerializer(AvailabilityPeriodSerializer):
    reason = serializers.SerializerMethodField(help_text="booking or downtime. Holders are never shown.")

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_reason(self, obj) -> dict[str, str] | None:
        return to_choice_reference(obj.reason, (("booking", "Booked"), ("downtime", "Downtime")))


class BenchAvailabilitySerializer(serializers.Serializer):
    bench = UIDNamedReferenceSerializer(read_only=True)
    station = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    room = UIDNamedReferenceSerializer(read_only=True, allow_null=True)
    type = NamedReferenceSerializer(read_only=True, allow_null=True)
    has_computing = serializers.BooleanField(read_only=True)
    is_fully_free = serializers.BooleanField(read_only=True)
    is_favorite = serializers.BooleanField(read_only=True)
    next_free_at = serializers.DateTimeField(read_only=True, allow_null=True)
    free_periods = AvailabilityPeriodSerializer(many=True, read_only=True)
    busy_periods = AvailabilityBusyPeriodSerializer(many=True, read_only=True)


class BenchAvailabilityResultSerializer(serializers.Serializer):
    """Ranked: fully free first, then favorites, then the longest free period."""

    window_starts_at = serializers.DateTimeField(read_only=True)
    window_ends_at = serializers.DateTimeField(read_only=True)
    is_truncated = serializers.BooleanField(read_only=True, help_text="More benches matched than were returned.")
    benches = BenchAvailabilitySerializer(many=True, read_only=True)


class BenchSlotWatchCreateSerializer(serializers.Serializer):
    """Watch one bench for free time inside [starts_at, ends_at). Notify-only; nothing is held.

    Delivery channels are decided by the server (web always; email and Teams when enabled and reachable).
    """

    bench_id = serializers.IntegerField(min_value=1)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()

    def to_command_kwargs(self) -> dict:
        data = self.validated_data
        return {"bench_id": data["bench_id"], "range_start": data["starts_at"], "range_end": data["ends_at"]}


class BenchSlotWatchListQuerySerializer(PageNumberQuerySerializer):
    status = serializers.ChoiceField(choices=SlotWatchStatus.choices, required=False)
    updated_after = serializers.DateTimeField(
        required=False,
        help_text="Only alerts changed at or after this time, e.g. recently notified follows (status=fulfilled).",
    )


class SlotBusyPeriodSerializer(serializers.Serializer):
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    is_mine = serializers.BooleanField(help_text="The viewer's own booking. Other bookings are anonymous.")


class SlotAvailabilitySerializer(serializers.Serializer):
    """Live view of the watched time: who-free (anonymous) busy blocks, next free gap, and demand."""

    window_starts_at = serializers.DateTimeField()
    window_ends_at = serializers.DateTimeField()
    busy_periods = SlotBusyPeriodSerializer(many=True)
    next_free_starts_at = serializers.DateTimeField(allow_null=True)
    next_free_ends_at = serializers.DateTimeField(allow_null=True)
    watcher_count = serializers.IntegerField(help_text="Other users with an active alert on this bench and time.")


class BenchSlotWatchSerializer(AppModelSerializer):
    bench = UIDNamedReferenceSerializer(read_only=True)
    starts_at = serializers.DateTimeField(source="range_start", read_only=True)
    ends_at = serializers.DateTimeField(source="range_end", read_only=True)
    availability = serializers.SerializerMethodField(
        help_text="For active alerts: busy blocks, next free time and how many others are watching."
    )
    followed_booking_id = serializers.IntegerField(
        source="target_booking_id",
        read_only=True,
        allow_null=True,
        help_text="Set when this alert follows one booking: you get one alert when it ends, whichever way.",
    )
    status = serializers.SerializerMethodField()

    class Meta:
        model = BenchSlotWatch
        ref_name = "BenchSlotWatch"
        fields = (
            "id",
            "bench",
            "starts_at",
            "ends_at",
            "followed_booking_id",
            "availability",
            "status",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(ChoiceReferenceSerializer)
    def get_status(self, obj: BenchSlotWatch) -> dict[str, str] | None:
        return to_choice_reference(obj.status, SlotWatchStatus.choices)

    @extend_schema_field(SlotAvailabilitySerializer(allow_null=True))
    def get_availability(self, obj: BenchSlotWatch) -> dict | None:
        availability = slot_availability(obj)
        return SlotAvailabilitySerializer(availability).data if availability else None
