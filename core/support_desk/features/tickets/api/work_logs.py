"""List and manage work logs scoped to a support ticket."""

from datetime import datetime
from uuid import UUID

from django.db.models import QuerySet
from drf_api_contracts import OperationContract, ResponseContract
from drf_spectacular.utils import OpenApiParameter
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from core.common.api.pagination import PageNumberQuerySerializer, with_page_query
from core.common.api.strict_json import StrictObjectJSONParser
from core.common.api.summary_serializers import UserReferenceSerializer, embedded_resource, user_display_name
from core.common.domain.errors import BadRequest
from core.support_desk.features.tickets.api.base import SupportAPIView, operation
from core.support_desk.features.tickets.application.policies import can_manage_work_log
from core.support_desk.features.tickets.application.shared import get_ticket_for_actor
from core.support_desk.features.tickets.application.work_logs import (
    AddWorkLogInput,
    DeleteWorkLogInput,
    UpdateWorkLogInput,
    add_work_log,
    delete_work_log,
    update_work_log,
)
from core.support_desk.features.tickets.queries.work_log_reports import (
    list_work_log_contributors,
    summarize_work_logs,
    work_logs_for_report,
)
from core.support_desk.models.work_log import MAX_WORK_LOG_MINUTES, MIN_WORK_LOG_MINUTES, TicketWorkLog


@embedded_resource
class TicketWorkLogSerializer(serializers.ModelSerializer):
    etag = serializers.CharField(read_only=True)
    started_at = serializers.DateTimeField(read_only=True)
    description = serializers.CharField(read_only=True)
    author = UserReferenceSerializer(read_only=True)
    can_manage = serializers.SerializerMethodField()

    class Meta:
        model = TicketWorkLog
        fields: tuple[str, ...] = (
            "id",
            "author",
            "time_spent_minutes",
            "started_at",
            "description",
            "created_at",
            "updated_at",
            "can_manage",
            "etag",
        )

    def get_can_manage(self, obj: TicketWorkLog) -> bool:
        return can_manage_work_log(self.context["request"].user, obj)


class WorkLogRequestSerializer(serializers.Serializer):
    time_spent_minutes = serializers.IntegerField(min_value=MIN_WORK_LOG_MINUTES, max_value=MAX_WORK_LOG_MINUTES)
    started_at = serializers.DateTimeField(required=False)
    description = serializers.CharField(required=False, allow_blank=True, max_length=4000)

    def validate_time_spent_minutes(self, value: int) -> int:
        if type(self.initial_data["time_spent_minutes"]) is not int:
            raise serializers.ValidationError("Enter a whole number.", code="invalid_type")
        return value

    def validate_started_at(self, value: datetime) -> datetime:
        raw = self.initial_data["started_at"]
        try:
            parsed = datetime.fromisoformat(raw) if isinstance(raw, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.tzinfo is None:
            raise serializers.ValidationError("Include a timezone offset.", code="invalid_format")
        return value

    def validate_description(self, value: str) -> str:
        if not isinstance(self.initial_data["description"], str):
            raise serializers.ValidationError("Enter text.", code="invalid_type")
        return value


class MergePatchJSONParser(StrictObjectJSONParser):
    media_type = "application/merge-patch+json"


IDEMPOTENCY_KEY = OpenApiParameter(
    "Idempotency-Key",
    UUID,
    OpenApiParameter.HEADER,
    required=True,
    description="UUID replay key valid for 24 hours.",
)
IF_MATCH = OpenApiParameter(
    "If-Match",
    str,
    OpenApiParameter.HEADER,
    required=True,
    description="Current work log ETag.",
)
ETAG = OpenApiParameter(
    "ETag",
    str,
    OpenApiParameter.HEADER,
    response=[200, 201],
    description="Current work log ETag.",
)


class TicketWorkLogListCreateAPIView(SupportAPIView):
    """List or log effort on a ticket visible to the caller."""

    parser_classes = [StrictObjectJSONParser]
    get_contract = operation("TicketWorkLogList", TicketWorkLogSerializer, query=PageNumberQuerySerializer, many=True)
    post_contract = operation(
        "TicketWorkLogCreate",
        TicketWorkLogSerializer,
        request=WorkLogRequestSerializer,
        created=True,
        parameters=[
            IDEMPOTENCY_KEY,
            ETAG,
            OpenApiParameter("Idempotency-Replayed", bool, OpenApiParameter.HEADER, response=[201]),
        ],
    )

    def handle_get(self, request: Request, key: str) -> Response:
        _, error = self.validate_query()
        if error is not None:
            return error

        def list_work_logs() -> QuerySet[TicketWorkLog]:
            ticket = get_ticket_for_actor(key, request.user)
            return ticket.work_logs.select_related("author").all()

        return self._execute(list_work_logs)

    def handle_post(self, request: Request, key: str) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        assert serializer is not None
        header = request.headers.get("Idempotency-Key")
        if header is None:
            raise BadRequest("Idempotency-Key is required.", code="idempotency_key_required")
        try:
            replay_key = UUID(header)
            if len(header) != 36 or str(replay_key) != header.lower():
                raise ValueError("Expected a hyphenated UUID")
        except ValueError as error:
            raise BadRequest("Idempotency-Key must be a UUID.", code="invalid_idempotency_key") from error
        command = AddWorkLogInput(ticket_key=key, **serializer.validated_data)
        body, replayed = add_work_log(
            command,
            actor=request.user,
            idempotency_key=replay_key,
            project_response=lambda entry: self.respond(entry).data,
        )
        entry = body["data"]
        response = Response(body, status=201)
        response["Location"] = request.build_absolute_uri(f"{request.path}/{entry['id']}")
        response["ETag"] = entry["etag"]
        if replayed:
            response["Idempotency-Replayed"] = "true"
        return response


class TicketWorkLogDetailAPIView(SupportAPIView):
    """Retrieve an entry, or allow its author or support staff to change it."""

    parser_classes = [StrictObjectJSONParser, MergePatchJSONParser]
    get_contract = operation("TicketWorkLogDetail", TicketWorkLogSerializer, parameters=[ETAG])
    patch_contract = OperationContract(
        request=WorkLogRequestSerializer,
        success=ResponseContract.success("TicketWorkLogUpdate", TicketWorkLogSerializer),
        bad_request=ResponseContract.bad_request(),
        forbidden=ResponseContract.forbidden(),
        not_found=ResponseContract.not_found(),
        validation_error=ResponseContract.problem(422),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=[IF_MATCH, ETAG],
    )
    delete_contract = OperationContract(
        success=ResponseContract.no_content(),
        forbidden=ResponseContract.forbidden(),
        not_found=ResponseContract.not_found(),
        precondition_failed=ResponseContract.problem(412),
        precondition_required=ResponseContract.problem(428),
        parameters=[IF_MATCH],
    )

    def _detail_response(self, work_log: TicketWorkLog) -> Response:
        response = self.respond(work_log)
        response["ETag"] = work_log.etag
        return response

    def handle_get(self, request: Request, key: str, work_log_id: int) -> Response:
        ticket = get_ticket_for_actor(key, request.user)
        work_log = ticket.work_logs.select_related("author").filter(pk=work_log_id).first()
        if work_log is None:
            return self.respond_problem("not_found")
        return self._detail_response(work_log)

    def handle_patch(self, request: Request, key: str, work_log_id: int) -> Response:
        serializer, error = self.validate_request(partial=True)
        if error is not None:
            return error
        assert serializer is not None
        command = UpdateWorkLogInput(
            ticket_key=key,
            work_log_id=work_log_id,
            if_match=request.headers.get("If-Match"),
            **serializer.validated_data,
        )
        return self._execute(lambda: update_work_log(command, actor=request.user), project=self._detail_response)

    def handle_delete(self, request: Request, key: str, work_log_id: int) -> Response:
        command = DeleteWorkLogInput(ticket_key=key, work_log_id=work_log_id, if_match=request.headers.get("If-Match"))
        return self._execute(lambda: delete_work_log(command, actor=request.user), delete=True)


class WorkLogReportQuerySerializer(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["mine", "team", "ticket"], default="mine", required=False)
    ticket_key = serializers.CharField(required=False, max_length=32)
    team_id = serializers.IntegerField(required=False, min_value=1)
    author_id = serializers.IntegerField(required=False, min_value=1)
    started_after = serializers.DateTimeField(required=False, help_text="Inclusive lower bound.")
    started_before = serializers.DateTimeField(required=False, help_text="Exclusive upper bound.")

    def validate(self, attrs):
        scope = attrs["scope"]
        if ("ticket_key" in attrs) != (scope == "ticket"):
            raise serializers.ValidationError({"ticket_key": "Supply a ticket key only for ticket reports."})
        if "team_id" in attrs and scope != "team":
            raise serializers.ValidationError({"team_id": "Team filtering is available only for team reports."})
        if "author_id" in attrs and scope == "mine":
            raise serializers.ValidationError({"author_id": "Personal reports are already scoped to your entries."})
        start, end = attrs.get("started_after"), attrs.get("started_before")
        if start and end and start >= end:
            raise serializers.ValidationError({"started_before": "Must be later than started_after."})
        return attrs


@embedded_resource
class WorkLogTicketSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    key = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True)


@embedded_resource
class WorkLogReportEntrySerializer(TicketWorkLogSerializer):
    ticket = WorkLogTicketSerializer(read_only=True)

    class Meta(TicketWorkLogSerializer.Meta):
        fields = (*TicketWorkLogSerializer.Meta.fields, "ticket")


class WorkLogReportSummarySerializer(serializers.Serializer):
    total_minutes = serializers.IntegerField(min_value=0, read_only=True)
    my_minutes = serializers.IntegerField(min_value=0, read_only=True)
    entry_count = serializers.IntegerField(min_value=0, read_only=True)
    ticket_count = serializers.IntegerField(min_value=0, read_only=True)
    contributor_count = serializers.IntegerField(min_value=0, read_only=True)


@embedded_resource
class WorkLogContributorSerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()
    total_minutes = serializers.IntegerField(min_value=0, read_only=True)
    entry_count = serializers.IntegerField(min_value=0, read_only=True)
    ticket_count = serializers.IntegerField(min_value=0, read_only=True)

    def get_name(self, obj) -> str:
        return user_display_name(obj)


class WorkLogReportListAPIView(SupportAPIView):
    """Paginated work log entries matching the report scope and filters."""

    get_contract = operation(
        "WorkLogReportList",
        WorkLogReportEntrySerializer,
        query=with_page_query(WorkLogReportQuerySerializer),
        many=True,
    )

    def handle_get(self, request: Request) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        assert filters is not None
        logs = work_logs_for_report(request.user, filters).select_related("author", "ticket")
        return self.respond(logs)


class WorkLogReportSummaryAPIView(SupportAPIView):
    """Totals for all entries in a report, independent of pagination."""

    get_contract = OperationContract(
        query=WorkLogReportQuerySerializer,
        success=ResponseContract.success("WorkLogReportSummary", WorkLogReportSummarySerializer),
        bad_request=ResponseContract.bad_request(),
        forbidden=ResponseContract.forbidden(),
        not_found=ResponseContract.not_found(),
    )

    def handle_get(self, request: Request) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        assert filters is not None
        return self.respond(summarize_work_logs(work_logs_for_report(request.user, filters), request.user))


class WorkLogContributorsAPIView(SupportAPIView):
    """Paginated totals by contributor, ordered by effort."""

    get_contract = operation(
        "WorkLogContributors",
        WorkLogContributorSerializer,
        query=with_page_query(WorkLogReportQuerySerializer),
        many=True,
    )

    def handle_get(self, request: Request) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        assert filters is not None
        return self.respond(list_work_log_contributors(work_logs_for_report(request.user, filters)))
