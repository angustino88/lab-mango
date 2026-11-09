"""HTTP transport views for the Support Desk feature."""

from typing import Any

from django.http import FileResponse, HttpResponse
from drf_api_contracts import ResponseContract
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import SAFE_METHODS, IsAuthenticated
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework_api_key.permissions import HasAPIKey

from core.common.api.options import OptionsAPIView, OptionsQueryMixin, SizeClass
from core.support_desk.contracts import (
    ActivityEventType,
    AttachmentScanStatus,
    CommentVisibility,
)
from core.support_desk.exceptions import (
    AttachmentInfectedError,
    AttachmentRestrictedError,
    AttachmentScanPendingError,
    RecordNotFoundError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.api.base import SupportAPIView, operation
from core.support_desk.features.tickets.api.filters import TICKET_FILTERS, TicketListQuerySerializer
from core.support_desk.features.tickets.api.permissions import IsSupportAdmin, IsSupportAgent
from core.support_desk.features.tickets.api.serializers import (
    AdminCannedResponseCreateSerializer,
    AdminCannedResponseUpdateSerializer,
    AdminCategoryCreateSerializer,
    AdminCategoryUpdateSerializer,
    AdminLabelCreateSerializer,
    AdminLabelUpdateSerializer,
    AdminPriorityCreateSerializer,
    AdminPriorityUpdateSerializer,
    AdminSettingsUpdateSerializer,
    AdminStatusCreateSerializer,
    AdminStatusUpdateSerializer,
    AdminTeamCreateSerializer,
    AdminTeamUpdateSerializer,
    AdminTransitionCreateSerializer,
    AdminTransitionUpdateSerializer,
    AttachmentUploadRequestSerializer,
    CannedResponseSerializer,
    CategorySerializer,
    CommentCreateRequestSerializer,
    CommentUpdateRequestSerializer,
    CsatRequestSerializer,
    LabelSerializer,
    LinkResourceRequestSerializer,
    PrioritySerializer,
    QueueStatsQuerySerializer,
    QueueStatsSerializer,
    ResourceTicketSummarySerializer,
    StatusOptionsQuerySerializer,
    StatusSerializer,
    StatusTransitionSerializer,
    SupportPublicSettingsSerializer,
    SupportSettingsSerializer,
    TeamSerializer,
    TicketActivitySerializer,
    TicketAssignRequestSerializer,
    TicketAttachmentSerializer,
    TicketCommentSerializer,
    TicketCreateRequestSerializer,
    TicketDetailSerializer,
    TicketLinkRequestSerializer,
    TicketLinkSerializer,
    TicketListSerializer,
    TicketResourceLinkSerializer,
    TicketTransitionRequestSerializer,
    TicketUpdateRequestSerializer,
    UnlinkResourceRequestSerializer,
    WatcherRequestSerializer,
    WatcherSerializer,
)
from core.support_desk.features.tickets.application import (
    AddAttachmentInput,
    AddCommentInput,
    AssignTicketInput,
    CreateCannedResponseInput,
    CreateCategoryInput,
    CreateLabelInput,
    CreatePriorityInput,
    CreateStatusInput,
    CreateTeamInput,
    CreateTicketInput,
    CreateTransitionInput,
    DeleteAttachmentInput,
    DeleteCommentInput,
    LinkResourceInput,
    LinkTicketsInput,
    SubmitCsatInput,
    TransitionTicketInput,
    UnlinkResourceInput,
    UnlinkTicketsInput,
    UpdateCannedResponseInput,
    UpdateCategoryInput,
    UpdateCommentInput,
    UpdateLabelInput,
    UpdatePriorityInput,
    UpdateSettingsInput,
    UpdateStatusInput,
    UpdateTeamInput,
    UpdateTicketInput,
    UpdateTransitionInput,
    WatcherInput,
    add_attachment,
    add_comment,
    add_watcher,
    assign_ticket,
    create_canned_response,
    create_category,
    create_label,
    create_priority,
    create_status,
    create_team,
    create_ticket,
    create_transition,
    delete_attachment,
    delete_canned_response,
    delete_category,
    delete_comment,
    delete_label,
    delete_priority,
    delete_team,
    delete_transition,
    link_resource,
    link_tickets,
    list_canned_responses_for,
    remove_watcher,
    render_canned_response,
    submit_csat,
    transition_ticket,
    unlink_resource,
    unlink_tickets,
    update_canned_response,
    update_category,
    update_comment,
    update_label,
    update_priority,
    update_settings,
    update_status,
    update_team,
    update_ticket,
    update_transition,
)
from core.support_desk.features.tickets.application.policies import (
    can_view_internal_notes,
    can_view_restricted_attachments,
    can_view_ticket,
)
from core.support_desk.features.tickets.queries import (
    get_category_options,
    get_label_options,
    get_priority_options,
    get_queue_stats,
    get_resource_ticket_summary,
    get_status_options,
    get_team_options,
    get_ticket_by_key,
    list_categories,
    list_labels,
    list_priorities,
    list_statuses,
    list_teams,
    list_tickets,
)
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.canned_response import CannedResponse
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.transition import SupportStatusTransition


class TicketListCreateAPIView(SupportAPIView):
    """List support tickets with rich filtering, or create a new support ticket."""

    get_contract = operation("TicketList", TicketListSerializer, query=TicketListQuerySerializer, many=True)
    post_contract = operation("TicketCreate", TicketDetailSerializer, request=TicketCreateRequestSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        filters, error = self.validate_query()
        if error is not None:
            return error
        return self._execute(lambda: TICKET_FILTERS.apply(list_tickets(request.user), filters))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        raw_links = data.get("linked_resources", [])
        linked_resources = tuple((item["resource_type"], item["resource_id"]) for item in raw_links)
        cmd = CreateTicketInput(
            subject=data["subject"],
            description=data["description"],
            category_id=data["category_id"],
            priority_id=data.get("priority_id"),
            linked_resources=linked_resources,
            assignee_id=data.get("assignee_id"),
            on_behalf_of_id=data.get("on_behalf_of_id"),
            idempotency_key=data.get("idempotency_key"),
            ticket_type=data.get("ticket_type"),
            impact=data.get("impact", ""),
            urgency=data.get("urgency", ""),
            source=data.get("source", "web"),
            external_reference=data.get("external_reference", ""),
            due_date=data.get("due_date"),
            team_id=data.get("team_id"),
            labels=tuple(data.get("labels", ())),
            parent_key=data.get("parent_key"),
            watcher_ids=tuple(data.get("watcher_ids", ())),
        )
        return self._execute(
            lambda: create_ticket(cmd, actor=request.user),
            project=lambda ticket: get_ticket_by_key(ticket.key),
        )


class TicketDetailAPIView(SupportAPIView):
    """Retrieve full ticket projection or update mutable fields."""

    get_contract = operation("TicketDetail", TicketDetailSerializer)
    patch_contract = operation("TicketUpdate", TicketDetailSerializer, request=TicketUpdateRequestSerializer)

    def _get_ticket_or_raise(self, key: str):
        ticket = get_ticket_by_key(key, viewer=self.request.user)
        if not ticket:
            raise TicketNotFoundError(f"Ticket {key} not found.")
        return ticket

    def handle_get(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: self._get_ticket_or_raise(key))

    def handle_patch(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = UpdateTicketInput(
            ticket_key=key,
            version=data["version"],
            subject=data.get("subject"),
            description=data.get("description"),
            category_id=data.get("category_id"),
            priority_id=data.get("priority_id"),
            ticket_type=data.get("ticket_type"),
            impact=data.get("impact"),
            urgency=data.get("urgency"),
            external_reference=data.get("external_reference"),
            due_date=data.get("due_date"),
            clear_due_date="due_date" in data and data["due_date"] is None,
            team_id=data.get("team_id"),
            clear_team="team_id" in data and data["team_id"] is None,
            labels=tuple(data["labels"]) if "labels" in data else None,
            parent_key=data.get("parent_key") or None,
            clear_parent="parent_key" in data and not data["parent_key"],
        )
        return self._execute(
            lambda: update_ticket(cmd, actor=request.user),
            project=lambda ticket: get_ticket_by_key(ticket.key),
        )


class TicketAssignAPIView(SupportAPIView):
    """Assign or reassign a support ticket to an agent."""

    post_contract = operation("TicketAssign", TicketDetailSerializer, request=TicketAssignRequestSerializer)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = AssignTicketInput(
            ticket_key=key,
            assignee_id=data["assignee_id"],
            version=data.get("version"),
        )
        return self._execute(
            lambda: assign_ticket(cmd, actor=request.user),
            project=lambda ticket: get_ticket_by_key(ticket.key),
        )


class TicketTransitionAPIView(SupportAPIView):
    """Execute a validated lifecycle status transition on a ticket."""

    post_contract = operation("TicketTransition", TicketDetailSerializer, request=TicketTransitionRequestSerializer)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = TransitionTicketInput(
            ticket_key=key,
            to_status_id=data["to_status_id"],
            version=data["version"],
            reason=data.get("reason", ""),
            resolution_summary=data.get("resolution_summary", ""),
            root_cause=data.get("root_cause", ""),
            resolution_code=data.get("resolution_code", ""),
        )
        return self._execute(
            lambda: transition_ticket(cmd, actor=request.user),
            project=lambda ticket: get_ticket_by_key(ticket.key),
        )


class TicketResourceLinkAPIView(SupportAPIView):
    """Link or unlink a Lab Mango resource on a support ticket."""

    post_contract = operation(
        "TicketResourceLinkCreate",
        TicketResourceLinkSerializer,
        request=LinkResourceRequestSerializer,
        created=True,
    )
    delete_contract = operation(delete=True, request=UnlinkResourceRequestSerializer)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = LinkResourceInput(
            ticket_key=key,
            resource_type=data["resource_type"],
            resource_id=str(data["resource_id"]),
        )
        return self._execute(lambda: link_resource(cmd, actor=request.user))

    def handle_delete(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        resource_type = request.data.get("resource_type") or request.query_params.get("resource_type")
        resource_id = request.data.get("resource_id") or request.query_params.get("resource_id")
        reason = request.data.get("reason") or request.query_params.get("reason", "")
        if not resource_type or not resource_id:
            return self.respond_problem(
                "bad_request",
                code="validation_failed",
                detail="resource_type and resource_id are required to unlink a resource.",
            )
        cmd = UnlinkResourceInput(
            ticket_key=key,
            resource_type=resource_type,
            resource_id=str(resource_id),
            reason=reason,
        )
        return self._execute(lambda: unlink_resource(cmd, actor=request.user), delete=True)


class TicketCommentListCreateAPIView(SupportAPIView):
    """List comments visible to current actor, or post a new comment."""

    get_contract = operation("TicketCommentList", TicketCommentSerializer, many=True)
    post_contract = operation("TicketCommentCreate", TicketCommentSerializer, request=CommentCreateRequestSerializer, created=True)

    def handle_get(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        ticket = get_ticket_by_key(key, viewer=request.user)
        if not ticket:
            return self.respond_problem("not_found")
        show_internal = can_view_internal_notes(request.user)
        comments = [c for c in ticket.comments.all() if c.deleted_at is None]
        if not show_internal:
            comments = [c for c in comments if c.visibility == CommentVisibility.PUBLIC.value]
        return self.respond(comments)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = AddCommentInput(
            ticket_key=key,
            body=data["body"],
            visibility=data.get("visibility", CommentVisibility.PUBLIC.value),
        )
        return self._execute(lambda: add_comment(cmd, actor=request.user))


class TicketCommentDetailAPIView(SupportAPIView):
    """Edit or soft-delete a comment within the allowed edit window."""

    patch_contract = operation("TicketCommentUpdate", TicketCommentSerializer, request=CommentUpdateRequestSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, key: str, comment_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = UpdateCommentInput(comment_id=comment_id, body=data["body"])
        return self._execute(lambda: update_comment(cmd, actor=request.user))

    def handle_delete(self, request: Request, key: str, comment_id: int, *args: Any, **kwargs: Any) -> Response:
        cmd = DeleteCommentInput(comment_id=comment_id)
        return self._execute(lambda: delete_comment(cmd, actor=request.user), delete=True)


class TicketAttachmentListCreateAPIView(SupportAPIView):
    """Upload a file attachment to a ticket."""

    parser_classes = [MultiPartParser, FormParser]
    post_contract = operation(
        "TicketAttachmentCreate",
        TicketAttachmentSerializer,
        request=AttachmentUploadRequestSerializer,
        created=True,
    )

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        uploaded_file = data["file"]
        cmd = AddAttachmentInput(
            ticket_key=key,
            filename=uploaded_file.name,
            content_type=getattr(uploaded_file, "content_type", "application/octet-stream"),
            size=uploaded_file.size,
            file=uploaded_file,
            comment_id=data.get("comment_id"),
            is_restricted=data.get("is_restricted", False),
        )
        return self._execute(lambda: add_attachment(cmd, actor=request.user))


class TicketAttachmentDetailAPIView(SupportAPIView):
    """Soft-delete an attachment from a ticket."""

    delete_contract = operation(delete=True)

    def handle_delete(self, request: Request, key: str, attachment_id: int, *args: Any, **kwargs: Any) -> Response:
        cmd = DeleteAttachmentInput(attachment_id=attachment_id)
        return self._execute(lambda: delete_attachment(cmd, actor=request.user), delete=True)


@extend_schema_view(
    get=extend_schema(
        responses={
            (200, "application/octet-stream"): OpenApiResponse(
                response=OpenApiTypes.BINARY, description="Clean attachment binary (stored content type)"
            ),
            401: ResponseContract.unauthorized().schema,
            403: OpenApiResponse(
                response=ResponseContract.problem(403).schema,
                description="Restricted attachment requires support staff",
            ),
            404: OpenApiResponse(
                response=ResponseContract.problem(404).schema,
                description="Attachment is missing, deleted, hidden, or has no binary",
            ),
            409: OpenApiResponse(
                response=ResponseContract.problem(409).schema, description="Attachment scan is pending"
            ),
            422: OpenApiResponse(
                response=ResponseContract.problem(422).schema, description="Attachment is quarantined as infected"
            ),
        },
    ),
)
class TicketAttachmentDownloadAPIView(SupportAPIView):
    """Download an attachment file with security verification."""

    def handle_get(self, request: Request, attachment_id: int, *args: Any, **kwargs: Any) -> HttpResponse:
        attachment = (
            TicketAttachment.objects.select_related("ticket")
            .filter(pk=attachment_id, deleted_at__isnull=True)
            .first()
        )
        if not attachment:
            raise RecordNotFoundError(f"Attachment {attachment_id} not found.")

        if not can_view_ticket(request.user, attachment.ticket):
            raise RecordNotFoundError(f"Attachment {attachment_id} not found.")

        if attachment.is_restricted and not can_view_restricted_attachments(request.user):
            raise AttachmentRestrictedError("This attachment is restricted to support staff.")

        if attachment.scan_status == AttachmentScanStatus.INFECTED.value:
            raise AttachmentInfectedError("File is quarantined due to suspected malware.")
        if attachment.scan_status == AttachmentScanStatus.PENDING.value:
            raise AttachmentScanPendingError("File is still being scanned. Try again shortly.")

        if not attachment.file or not attachment.file.storage.exists(attachment.file.name):
            raise RecordNotFoundError("Attachment binary could not be found.")

        return FileResponse(
            attachment.file.open("rb"),
            as_attachment=True,
            filename=attachment.filename,
            content_type=attachment.content_type,
        )


class TicketActivityListAPIView(SupportAPIView):
    """Read the immutable audit trail of a support ticket."""

    get_contract = operation("TicketActivityList", TicketActivitySerializer, many=True)

    def handle_get(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        ticket = get_ticket_by_key(key, viewer=request.user)
        if not ticket:
            return self.respond_problem("not_found")
        show_internal = can_view_internal_notes(request.user)
        acts = list(ticket.activities.all())
        if not show_internal:
            acts = [
                a
                for a in acts
                if not (
                    a.event_type == ActivityEventType.COMMENT_ADDED.value
                    and (a.payload or {}).get("visibility") == CommentVisibility.INTERNAL.value
                )
            ]
        return self.respond(acts)


class ResourceTicketHistoryAPIView(SupportAPIView):
    """Retrieve full incident history and open/total counts for a traceable lab resource."""

    get_contract = operation("ResourceTicketSummary", ResourceTicketSummarySerializer)

    def handle_get(self, request: Request, resource_type: str, resource_id: str, *args: Any, **kwargs: Any) -> Response:
        summary = get_resource_ticket_summary(resource_type, resource_id, viewer=request.user)
        return self.respond(summary)


# ---------------------------------------------------------------------------
# Options Selectors (/options) strictly conforming to flat {id, sku, name} standard (ADR 002)
# ---------------------------------------------------------------------------


class CategoryOptionsAPIView(OptionsAPIView):
    """Options selector endpoint for active categories."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "tickets"
    schema_tags = ("Support Desk",)

    def select(self, *, actor, filters):
        return get_category_options(actor=actor, **filters)


class PriorityOptionsAPIView(OptionsAPIView):
    """Options selector endpoint for active priorities."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "tickets"
    schema_tags = ("Support Desk",)

    def select(self, *, actor, filters):
        return get_priority_options(actor=actor, **filters)


class StatusOptionsAPIView(OptionsAPIView):
    """Options selector endpoint for active statuses."""

    query_serializer = StatusOptionsQuerySerializer
    size_class = SizeClass.SMALL
    owner = "tickets"
    schema_tags = ("Support Desk",)

    def select(self, *, actor, filters):
        return get_status_options(actor=actor, **filters)


class TeamOptionsAPIView(OptionsAPIView):
    """Options selector endpoint for active teams."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.SMALL
    owner = "tickets"
    schema_tags = ("Support Desk",)

    def select(self, *, actor, filters):
        return get_team_options(actor=actor, **filters)


class LabelOptionsAPIView(OptionsAPIView):
    """Options selector endpoint for labels."""

    query_serializer = OptionsQueryMixin
    size_class = SizeClass.LARGE
    owner = "tickets"
    schema_tags = ("Support Desk",)

    def select(self, *, actor, filters):
        return get_label_options(actor=actor, **filters)


# ---------------------------------------------------------------------------
# Collaboration: watchers, ticket links, satisfaction, dashboard, canned responses
# ---------------------------------------------------------------------------


class TicketWatcherAPIView(SupportAPIView):
    """Subscribe to (POST) or unsubscribe from (DELETE) a ticket. Agents may manage other users via ``user_id``."""

    post_contract = operation("TicketWatcherAdd", WatcherSerializer, request=WatcherRequestSerializer, created=True)
    delete_contract = operation(delete=True, request=WatcherRequestSerializer)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = WatcherInput(ticket_key=key, user_id=serializer.validated_data.get("user_id"))
        return self._execute(lambda: add_watcher(cmd, actor=request.user))

    def handle_delete(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        raw = request.data.get("user_id") or request.query_params.get("user_id")
        cmd = WatcherInput(ticket_key=key, user_id=int(raw) if raw else None)
        return self._execute(lambda: remove_watcher(cmd, actor=request.user), delete=True)


class TicketLinkListCreateAPIView(SupportAPIView):
    """Link this ticket to another (relates to / duplicates / blocks / caused by)."""

    get_contract = operation("TicketLinkList", TicketLinkSerializer, many=True)
    post_contract = operation("TicketLinkCreate", TicketLinkSerializer, request=TicketLinkRequestSerializer, created=True)

    def handle_get(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        ticket = get_ticket_by_key(key, viewer=request.user)
        if not ticket:
            return self.respond_problem("not_found")
        links = sorted([*ticket.outgoing_links.all(), *ticket.incoming_links.all()], key=lambda x: (x.created_at, x.pk))
        return self.respond(links)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = LinkTicketsInput(ticket_key=key, target_key=data["target_key"], link_type=data["link_type"])
        return self._execute(lambda: link_tickets(cmd, actor=request.user))


class TicketLinkDetailAPIView(SupportAPIView):
    """Remove a ticket link."""

    delete_contract = operation(delete=True)

    def handle_delete(self, request: Request, key: str, link_id: int, *args: Any, **kwargs: Any) -> Response:
        cmd = UnlinkTicketsInput(ticket_key=key, link_id=link_id)
        return self._execute(lambda: unlink_tickets(cmd, actor=request.user), delete=True)


class TicketCsatAPIView(SupportAPIView):
    """Requester satisfaction rating (1-5) for a resolved ticket."""

    post_contract = operation("TicketCsat", TicketDetailSerializer, request=CsatRequestSerializer)

    def handle_post(self, request: Request, key: str, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        data = serializer.validated_data
        cmd = SubmitCsatInput(ticket_key=key, score=data["score"], comment=data.get("comment", ""))
        return self._execute(
            lambda: submit_csat(cmd, actor=request.user),
            project=lambda ticket: get_ticket_by_key(ticket.key, viewer=request.user),
        )


class QueueStatsAPIView(SupportAPIView):
    """Agent dashboard: open workload, SLA health, throughput, CSAT."""

    permission_classes = [IsSupportAgent]

    get_contract = operation("SupportQueueStats", QueueStatsSerializer, query=QueueStatsQuerySerializer)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        query, error = self.validate_query()
        if error is not None:
            return error
        days = (query or {}).get("days", 30)
        return self.respond(get_queue_stats(viewer=request.user, days=days))


class CannedResponseListAPIView(SupportAPIView):
    """Canned responses the calling agent may use; ``?ticket=KEY`` renders the placeholders."""

    permission_classes = [IsSupportAgent]

    get_contract = operation("CannedResponseList", CannedResponseSerializer, many=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        responses = list_canned_responses_for(request.user)
        ticket_key = request.query_params.get("ticket")
        data = CannedResponseSerializer(responses, many=True).data
        if ticket_key:
            ticket = get_ticket_by_key(ticket_key, viewer=request.user)
            if not ticket:
                return self.respond_problem("not_found")
            for item, response in zip(data, responses, strict=True):
                item["rendered_body"] = render_canned_response(response, ticket=ticket, actor=request.user)
        return self.respond(data)


# ---------------------------------------------------------------------------
# Admin Configuration Endpoints (Requires IsSupportAdmin)
# ---------------------------------------------------------------------------


class AdminSupportAPIView(SupportAPIView):
    """Administrative configuration (workflow, canned responses, settings): admin-only for every method."""

    permission_classes = [IsSupportAdmin]
    schema_tags = ("Support Desk Administration",)


class SupportCatalogAPIView(SupportAPIView):
    """ADR 002 catalogs (categories, priorities, statuses, teams, labels).

    Reads are open to any API key or authenticated user, writes require a support administrator.
    Which rows and fields a reader sees is decided by the catalog queries and serializers.
    """

    schema_tags = ("Support Desk Administration",)

    def get_permissions(self):
        if self.request.method in SAFE_METHODS:
            return [(HasAPIKey | IsAuthenticated)()]
        return [IsSupportAdmin()]


class AdminCategoryListCreateAPIView(SupportCatalogAPIView):
    """List all categories or create a new category."""

    get_contract = operation("AdminCategoryList", CategorySerializer, many=True)
    post_contract = operation("AdminCategoryCreate", CategorySerializer, request=AdminCategoryCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(list_categories(viewer=request.user)))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateCategoryInput(**serializer.validated_data)
        return self._execute(lambda: create_category(cmd, actor=request.user))


class AdminCategoryDetailAPIView(SupportCatalogAPIView):
    """Update or delete a category."""

    patch_contract = operation("AdminCategoryUpdate", CategorySerializer, request=AdminCategoryUpdateSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, category_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateCategoryInput(category_id=category_id, **serializer.validated_data)
        return self._execute(lambda: update_category(cmd, actor=request.user))

    def handle_delete(self, request: Request, category_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_category(category_id, actor=request.user), delete=True)


class AdminPriorityListCreateAPIView(SupportCatalogAPIView):
    """List all priorities or create a new priority."""

    get_contract = operation("AdminPriorityList", PrioritySerializer, many=True)
    post_contract = operation("AdminPriorityCreate", PrioritySerializer, request=AdminPriorityCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(list_priorities(viewer=request.user)))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreatePriorityInput(**serializer.validated_data)
        return self._execute(lambda: create_priority(cmd, actor=request.user))


class AdminPriorityDetailAPIView(SupportCatalogAPIView):
    """Update or delete a priority."""

    patch_contract = operation("AdminPriorityUpdate", PrioritySerializer, request=AdminPriorityUpdateSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, priority_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdatePriorityInput(priority_id=priority_id, **serializer.validated_data)
        return self._execute(lambda: update_priority(cmd, actor=request.user))

    def handle_delete(self, request: Request, priority_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_priority(priority_id, actor=request.user), delete=True)


class AdminStatusListCreateAPIView(SupportCatalogAPIView):
    """List all workflow statuses or create a new status."""

    get_contract = operation("AdminStatusList", StatusSerializer, many=True)
    post_contract = operation("AdminStatusCreate", StatusSerializer, request=AdminStatusCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(list_statuses(viewer=request.user)))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateStatusInput(**serializer.validated_data)
        return self._execute(lambda: create_status(cmd, actor=request.user))


class AdminStatusDetailAPIView(SupportCatalogAPIView):
    """Update a workflow status."""

    patch_contract = operation("AdminStatusUpdate", StatusSerializer, request=AdminStatusUpdateSerializer)

    def handle_patch(self, request: Request, status_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateStatusInput(status_id=status_id, **serializer.validated_data)
        return self._execute(lambda: update_status(cmd, actor=request.user))


class AdminTransitionListCreateAPIView(AdminSupportAPIView):
    """List all status transitions or define a new allowed transition."""

    get_contract = operation("AdminTransitionList", StatusTransitionSerializer, many=True)
    post_contract = operation("AdminTransitionCreate", StatusTransitionSerializer, request=AdminTransitionCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(
            list(
                SupportStatusTransition.objects.select_related("from_status", "to_status")
                .all()
                .order_by("from_status__sort_order", "to_status__sort_order")
            )
        )

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateTransitionInput(**serializer.validated_data)
        return self._execute(lambda: create_transition(cmd, actor=request.user))


class AdminTransitionDetailAPIView(AdminSupportAPIView):
    """Update or remove a status transition."""

    patch_contract = operation("AdminTransitionUpdate", StatusTransitionSerializer, request=AdminTransitionUpdateSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, transition_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateTransitionInput(transition_id=transition_id, **serializer.validated_data)
        return self._execute(lambda: update_transition(cmd, actor=request.user))

    def handle_delete(self, request: Request, transition_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_transition(transition_id, actor=request.user), delete=True)


class SupportSettingsAPIView(SupportAPIView):
    """Client-facing subset of the Support Desk settings that drives ticket forms and actions."""

    get_contract = operation("SupportSettingsDetail", SupportPublicSettingsSerializer)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(SupportSettings.get_solo())


class AdminSettingsAPIView(AdminSupportAPIView):
    """View and update global Support Desk configuration settings."""

    get_contract = operation("AdminSettingsDetail", SupportSettingsSerializer)
    patch_contract = operation("AdminSettingsUpdate", SupportSettingsSerializer, request=AdminSettingsUpdateSerializer)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(SupportSettings.get_solo())

    def handle_patch(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateSettingsInput(**serializer.validated_data)
        return self._execute(lambda: update_settings(cmd, actor=request.user))


class AdminTeamListCreateAPIView(SupportCatalogAPIView):
    """List all support teams or create a new team."""

    get_contract = operation("AdminTeamList", TeamSerializer, many=True)
    post_contract = operation("AdminTeamCreate", TeamSerializer, request=AdminTeamCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(list_teams(viewer=request.user)))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateTeamInput(**serializer.validated_data)
        return self._execute(lambda: create_team(cmd, actor=request.user))


class AdminTeamDetailAPIView(SupportCatalogAPIView):
    """Update or delete a support team."""

    patch_contract = operation("AdminTeamUpdate", TeamSerializer, request=AdminTeamUpdateSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, team_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateTeamInput(team_id=team_id, **serializer.validated_data)
        return self._execute(lambda: update_team(cmd, actor=request.user))

    def handle_delete(self, request: Request, team_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_team(team_id, actor=request.user), delete=True)


class AdminLabelListCreateAPIView(SupportCatalogAPIView):
    """List all labels or create a new label."""

    get_contract = operation("AdminLabelList", LabelSerializer, many=True)
    post_contract = operation("AdminLabelCreate", LabelSerializer, request=AdminLabelCreateSerializer, created=True)

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(list_labels(viewer=request.user)))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateLabelInput(**serializer.validated_data)
        return self._execute(lambda: create_label(cmd, actor=request.user))


class AdminLabelDetailAPIView(SupportCatalogAPIView):
    """Rename, recolour or delete a label."""

    patch_contract = operation("AdminLabelUpdate", LabelSerializer, request=AdminLabelUpdateSerializer)
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, label_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateLabelInput(label_id=label_id, **serializer.validated_data)
        return self._execute(lambda: update_label(cmd, actor=request.user))

    def handle_delete(self, request: Request, label_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_label(label_id, actor=request.user), delete=True)


class AdminCannedResponseListCreateAPIView(AdminSupportAPIView):
    """List all canned responses or create a new one."""

    get_contract = operation("AdminCannedResponseList", CannedResponseSerializer, many=True)
    post_contract = operation(
        "AdminCannedResponseCreate",
        CannedResponseSerializer,
        request=AdminCannedResponseCreateSerializer,
        created=True,
    )

    def handle_get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self.respond(list(CannedResponse.objects.select_related("team")))

    def handle_post(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = CreateCannedResponseInput(**serializer.validated_data)
        return self._execute(lambda: create_canned_response(cmd, actor=request.user))


class AdminCannedResponseDetailAPIView(AdminSupportAPIView):
    """Update or delete a canned response."""

    patch_contract = operation(
        "AdminCannedResponseUpdate",
        CannedResponseSerializer,
        request=AdminCannedResponseUpdateSerializer,
    )
    delete_contract = operation(delete=True)

    def handle_patch(self, request: Request, response_id: int, *args: Any, **kwargs: Any) -> Response:
        serializer, error = self.validate_request()
        if error is not None:
            return error
        cmd = UpdateCannedResponseInput(response_id=response_id, **serializer.validated_data)
        return self._execute(lambda: update_canned_response(cmd, actor=request.user))

    def handle_delete(self, request: Request, response_id: int, *args: Any, **kwargs: Any) -> Response:
        return self._execute(lambda: delete_canned_response(response_id, actor=request.user), delete=True)
