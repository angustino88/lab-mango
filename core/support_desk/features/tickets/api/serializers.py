"""Serializers for Support Desk API endpoints."""

from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from core.common.api.options import OptionsQueryMixin
from core.common.api.summary_serializers import (
    RelationSerializer,
    UserReferenceSerializer,
    choice_field,
    embedded_resource,
)
from core.support_desk.contracts import (
    IMPACT_CHOICES,
    LINK_INVERSE_LABELS,
    LINK_TYPE_CHOICES,
    RESOLUTION_CODE_CHOICES,
    TICKET_SOURCE_CHOICES,
    TICKET_TYPE_CHOICES,
    URGENCY_CHOICES,
    CommentVisibility,
    ResourceType,
    SystemState,
    TicketSource,
)
from core.support_desk.features.tickets.application.adapters import compute_resource_badge, get_adapter
from core.support_desk.features.tickets.application.policies import (
    can_view_internal_notes,
    can_view_restricted_attachments,
)
from core.support_desk.features.tickets.application.sla import sla_summary
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.attachment import TicketAttachment
from core.support_desk.models.canned_response import CannedResponse
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.comment import TicketComment
from core.support_desk.models.label import SupportLabel
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.resource_link import TicketResourceLink
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.team import SupportTeam
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.ticket_link import TicketLink
from core.support_desk.models.transition import SupportStatusTransition


class StatusOptionsQuerySerializer(OptionsQueryMixin):
    """Query parameter validation for support status selector."""

    system_state = serializers.ChoiceField(choices=SystemState.choices(), required=False)


class TeamSummarySerializer(serializers.ModelSerializer):
    """REL-3 relation to a team; the code is read from the team catalog."""

    class Meta:
        model = SupportTeam
        fields = ("id", "name")


class TeamSerializer(serializers.ModelSerializer):
    lead = UserReferenceSerializer(read_only=True)
    members = UserReferenceSerializer(many=True, read_only=True)

    class Meta:
        model = SupportTeam
        fields = ("id", "name", "code", "description", "lead", "members", "is_active", "created_at")


class LabelSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportLabel
        fields = ("id", "name", "color_hex")


class CannedResponseSerializer(serializers.ModelSerializer):
    team = TeamSummarySerializer(read_only=True)

    class Meta:
        model = CannedResponse
        fields = ("id", "title", "body", "team", "is_active", "created_at", "updated_at")


class CategorySerializer(serializers.ModelSerializer):
    default_team = TeamSummarySerializer(read_only=True)

    class Meta:
        model = SupportCategory
        fields = ("id", "name", "code", "description", "default_team", "sort_order", "is_active", "created_at")


class PrioritySerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportPriority
        fields = (
            "id",
            "name",
            "code",
            "rank",
            "color_hex",
            "response_target_minutes",
            "resolution_target_minutes",
            "is_default",
            "is_active",
            "created_at",
        )


class StatusSerializer(serializers.ModelSerializer):
    system_state = choice_field(SystemState.choices())
    is_sla_paused = serializers.BooleanField(source="pauses_sla", read_only=True)

    class Meta:
        model = SupportStatus
        fields = (
            "id",
            "name",
            "system_state",
            "color_hex",
            "is_initial",
            "is_final",
            "is_sla_paused",
            "sort_order",
            "is_active",
            "created_at",
        )


class StatusTransitionSerializer(serializers.ModelSerializer):
    from_status = RelationSerializer(read_only=True)  # REL-3, REL-5
    to_status = RelationSerializer(read_only=True)
    from_status_id = serializers.IntegerField(write_only=True)
    to_status_id = serializers.IntegerField(write_only=True)
    is_reason_required = serializers.BooleanField(source="requires_reason", read_only=True)
    is_resolution_required = serializers.BooleanField(source="requires_resolution", read_only=True)

    class Meta:
        model = SupportStatusTransition
        fields = (
            "id",
            "from_status",
            "from_status_id",
            "to_status",
            "to_status_id",
            "allowed_roles",
            "is_reason_required",
            "is_resolution_required",
            "created_at",
        )


class SupportSettingsSerializer(serializers.ModelSerializer):
    can_requesters_set_priority = serializers.BooleanField(source="requesters_can_set_priority", read_only=True)
    is_sla_enabled = serializers.BooleanField(source="sla_enabled", read_only=True)
    is_csat_enabled = serializers.BooleanField(source="csat_enabled", read_only=True)
    default_ticket_type = choice_field(TICKET_TYPE_CHOICES)

    class Meta:
        model = SupportSettings
        fields = (
            "reopen_window_days",
            "auto_close_days",
            "max_attachment_size_bytes",
            "allowed_attachment_extensions",
            "max_attachments_per_ticket",
            "comment_edit_window_minutes",
            "can_requesters_set_priority",
            "is_sla_enabled",
            "sla_at_risk_percent",
            "is_csat_enabled",
            "csat_window_days",
            "default_ticket_type",
            "updated_at",
        )


class LinkedResourceSerializer(serializers.Serializer):
    """REL-13 polymorphic relation to the linked resource; ``id`` is the resource's own identifier."""

    id = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    type = serializers.ChoiceField(choices=ResourceType.choices(), read_only=True)


@embedded_resource
class TicketResourceLinkSerializer(serializers.ModelSerializer):
    """A resource link owned by the ticket (REL-15)."""

    resource = serializers.SerializerMethodField()
    linked_by = UserReferenceSerializer(read_only=True)
    unlinked_by = UserReferenceSerializer(read_only=True)
    badge = serializers.SerializerMethodField()
    snapshot = serializers.SerializerMethodField()

    class Meta:
        model = TicketResourceLink
        fields = (
            "id",
            "resource",
            "snapshot",
            "is_active",
            "linked_at",
            "linked_by",
            "unlinked_at",
            "unlinked_by",
            "unlink_reason",
            "badge",
        )

    @extend_schema_field(LinkedResourceSerializer)
    def get_resource(self, obj: TicketResourceLink) -> dict[str, Any]:
        snapshot = self.get_snapshot(obj)
        name = snapshot.get("name") or f"{obj.resource_type} #{obj.resource_id}"
        return {"id": obj.resource_id, "name": name, "type": obj.resource_type}

    def get_badge(self, obj: TicketResourceLink) -> str:
        try:
            adapter = get_adapter(obj.resource_type)
            live_ref = adapter.get_reference(obj.resource_id)
            return compute_resource_badge(obj, live_ref).value
        except Exception:
            return ""

    def get_snapshot(self, obj: TicketResourceLink) -> dict[str, Any]:
        user = self.context.get("request").user if "request" in self.context else None
        # Resource visibility rule: if requester cannot view resource, redact snapshot details
        if user and not user.is_superuser:
            try:
                adapter = get_adapter(obj.resource_type)
                if not adapter.can_view(obj.resource_id, user):
                    return {"name": f"{obj.resource_type} #{obj.resource_id}", "restricted": True}
            except Exception:
                pass
        return obj.snapshot or {}


@embedded_resource
class TicketCommentSerializer(serializers.ModelSerializer):
    author = UserReferenceSerializer(read_only=True)
    visibility = choice_field([(v.value, v.value.capitalize()) for v in CommentVisibility])

    class Meta:
        model = TicketComment
        fields = (
            "id",
            "author",
            "body",
            "visibility",
            "created_at",
            "edited_at",
        )


@embedded_resource
class TicketAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserReferenceSerializer(read_only=True)
    scan_status = choice_field(TicketAttachment._meta.get_field("scan_status").choices)
    download_url = serializers.SerializerMethodField()

    class Meta:
        model = TicketAttachment
        fields = (
            "id",
            "filename",
            "content_type",
            "size",
            "is_restricted",
            "scan_status",
            "created_at",
            "uploaded_by",
            "download_url",
        )

    def get_download_url(self, obj: TicketAttachment) -> str:
        return f"/api/support/attachments/{obj.id}/download"


@embedded_resource
class TicketActivitySerializer(serializers.ModelSerializer):
    event_type = choice_field(TicketActivity._meta.get_field("event_type").choices)
    correlation_key = serializers.CharField(source="correlation_id", read_only=True)  # NAM-8

    class Meta:
        model = TicketActivity
        fields = (
            "id",
            "event_type",
            "actor_name",
            "occurred_at",
            "payload",
            "correlation_key",
        )


class WatcherSerializer(serializers.Serializer):
    user = UserReferenceSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)


class TicketRefSerializer(serializers.Serializer):
    """REL-3 relation to another ticket; ``name`` is ``"<key>: <subject>"``."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.SerializerMethodField()

    class Meta:
        ref_name = "TicketRef"

    def get_name(self, obj: SupportTicket) -> str:
        return f"{obj.key}: {obj.subject}"


@embedded_resource
class TicketLinkSerializer(serializers.ModelSerializer):
    """A link seen from one ticket's point of view (``direction`` + the other ticket)."""

    link_type = choice_field(LINK_TYPE_CHOICES)
    direction = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()
    ticket = serializers.SerializerMethodField()

    class Meta:
        model = TicketLink
        fields = ("id", "link_type", "direction", "label", "ticket", "created_at")

    def _outgoing(self, obj: TicketLink) -> bool:
        ticket_id = self.context.get("ticket_id")
        if ticket_id is not None:
            return obj.source_id == ticket_id

        ticket_key = self.context.get("ticket_key")
        if ticket_key is None:
            request = self.context.get("request")
            if request is not None:
                parser_context = getattr(request, "parser_context", None) or {}
                kwargs = parser_context.get("kwargs", {})
                if not kwargs and hasattr(request, "resolver_match") and request.resolver_match:
                    kwargs = request.resolver_match.kwargs
                ticket_key = kwargs.get("key")

        if ticket_key is not None:
            if getattr(obj.target, "key", None) == ticket_key:
                return False
            if getattr(obj.source, "key", None) == ticket_key:
                return True

        return True

    def get_direction(self, obj: TicketLink) -> str:
        return "outgoing" if self._outgoing(obj) else "incoming"

    def get_label(self, obj: TicketLink) -> str:
        if self._outgoing(obj):
            return obj.link_type.replace("_", " ")
        return LINK_INVERSE_LABELS.get(obj.link_type, obj.link_type)

    @extend_schema_field(TicketRefSerializer)
    def get_ticket(self, obj: TicketLink) -> dict[str, Any]:
        other = obj.target if self._outgoing(obj) else obj.source
        return TicketRefSerializer(other).data


class TicketListSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    priority = PrioritySerializer(read_only=True)
    status = StatusSerializer(read_only=True)
    requester = UserReferenceSerializer(read_only=True)
    assignee = UserReferenceSerializer(read_only=True)
    team = TeamSummarySerializer(read_only=True)
    labels = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    sla = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "key",
            "number",
            "subject",
            "ticket_type",
            "source",
            "impact",
            "urgency",
            "category",
            "priority",
            "status",
            "requester",
            "assignee",
            "team",
            "labels",
            "due_date",
            "created_at",
            "updated_at",
            "last_activity_at",
            "resolved_at",
            "closed_at",
            "sla",
            "version",
        )

    def get_sla(self, obj: SupportTicket) -> dict[str, Any]:
        # at_risk_percent is cached on the serializer context to avoid one settings query per row.
        if "sla_at_risk_percent" not in self.context:
            self.context["sla_at_risk_percent"] = SupportSettings.get_solo().sla_at_risk_percent
        return sla_summary(obj, at_risk_percent=self.context["sla_at_risk_percent"])


class TicketDetailSerializer(serializers.ModelSerializer):
    category = CategorySerializer(read_only=True)
    priority = PrioritySerializer(read_only=True)
    status = StatusSerializer(read_only=True)
    requester = UserReferenceSerializer(read_only=True)
    created_by = UserReferenceSerializer(read_only=True)
    assignee = UserReferenceSerializer(read_only=True)
    resolved_by = UserReferenceSerializer(read_only=True)
    team = TeamSummarySerializer(read_only=True)
    labels = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    parent = TicketRefSerializer(read_only=True)
    children = TicketRefSerializer(many=True, read_only=True)
    ticket_links = serializers.SerializerMethodField()
    watchers = WatcherSerializer(many=True, read_only=True)
    is_watching = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    resource_links = TicketResourceLinkSerializer(many=True, read_only=True)
    comments = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()
    activities = serializers.SerializerMethodField()

    class Meta:
        model = SupportTicket
        fields = (
            "id",
            "key",
            "number",
            "subject",
            "description",
            "ticket_type",
            "source",
            "impact",
            "urgency",
            "external_reference",
            "due_date",
            "category",
            "priority",
            "status",
            "requester",
            "created_by",
            "assignee",
            "team",
            "labels",
            "parent",
            "children",
            "ticket_links",
            "watchers",
            "is_watching",
            "created_at",
            "updated_at",
            "last_activity_at",
            "first_response_at",
            "resolved_at",
            "closed_at",
            "resolved_by",
            "reopen_count",
            "resolution_code",
            "resolution_summary",
            "root_cause",
            "csat_score",
            "csat_comment",
            "csat_submitted_at",
            "sla",
            "version",
            "resource_links",
            "comments",
            "attachments",
            "activities",
        )

    def _user(self) -> Any:
        request = self.context.get("request")
        return request.user if request is not None else None

    def get_sla(self, obj: SupportTicket) -> dict[str, Any]:
        return sla_summary(obj)

    def get_is_watching(self, obj: SupportTicket) -> bool:
        user = self._user()
        return bool(user and any(w.user_id == user.pk for w in obj.watchers.all()))

    def get_ticket_links(self, obj: SupportTicket) -> list[dict[str, Any]]:
        links = [*obj.outgoing_links.all(), *obj.incoming_links.all()]
        links.sort(key=lambda link: (link.created_at, link.pk))
        return TicketLinkSerializer(links, many=True, context={**self.context, "ticket_id": obj.pk}).data

    def get_comments(self, obj: SupportTicket) -> list[dict[str, Any]]:
        user = self.context.get("request").user if "request" in self.context else None
        show_internal = can_view_internal_notes(user) if user else False
        qs = [c for c in obj.comments.all() if c.deleted_at is None]
        if not show_internal:
            qs = [c for c in qs if c.visibility == CommentVisibility.PUBLIC.value]
        return TicketCommentSerializer(qs, many=True, context=self.context).data

    def get_attachments(self, obj: SupportTicket) -> list[dict[str, Any]]:
        user = self.context.get("request").user if "request" in self.context else None
        show_restricted = can_view_restricted_attachments(user) if user else False
        qs = [a for a in obj.attachments.all() if a.deleted_at is None]
        if not show_restricted:
            qs = [a for a in qs if not a.is_restricted]
        return TicketAttachmentSerializer(qs, many=True, context=self.context).data

    def get_activities(self, obj: SupportTicket) -> list[dict[str, Any]]:
        user = self.context.get("request").user if "request" in self.context else None
        show_internal = can_view_internal_notes(user) if user else False
        acts = list(obj.activities.all())
        # Filter internal comments from activity payloads for requesters
        if not show_internal:
            filtered = []
            for act in acts:
                if act.event_type == "comment_added" and act.payload.get("visibility") == "internal":
                    continue
                filtered.append(act)
            acts = filtered
        return TicketActivitySerializer(acts, many=True).data


# Mutation input serializers


class LinkedResourceItemSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=ResourceType.choices())
    resource_id = serializers.CharField(max_length=64)


class TicketCreateRequestSerializer(serializers.Serializer):
    subject = serializers.CharField(max_length=200)
    description = serializers.CharField()
    category_id = serializers.IntegerField()
    priority_id = serializers.IntegerField(
        required=False,
        allow_null=True,
        help_text="Optional: derived from impact/urgency, then the default priority, when omitted.",
    )
    ticket_type = serializers.ChoiceField(choices=TICKET_TYPE_CHOICES, required=False)
    impact = serializers.ChoiceField(choices=IMPACT_CHOICES, required=False, allow_blank=True, default="")
    urgency = serializers.ChoiceField(choices=URGENCY_CHOICES, required=False, allow_blank=True, default="")
    source = serializers.ChoiceField(
        choices=[c for c in TICKET_SOURCE_CHOICES if c[0] != TicketSource.SYSTEM.value],
        required=False,
        default=TicketSource.WEB.value,
    )
    external_reference = serializers.CharField(required=False, allow_blank=True, max_length=128, default="")
    due_date = serializers.DateField(required=False, allow_null=True)
    team_id = serializers.IntegerField(required=False, allow_null=True)
    labels = serializers.ListField(child=serializers.CharField(max_length=50), required=False, default=list)
    parent_key = serializers.CharField(required=False, allow_null=True, max_length=32)
    watcher_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    linked_resources = LinkedResourceItemSerializer(many=True, required=False, default=list)
    assignee_id = serializers.IntegerField(required=False, allow_null=True)
    on_behalf_of_id = serializers.IntegerField(required=False, allow_null=True)
    idempotency_key = serializers.CharField(required=False, max_length=128, allow_null=True)


class TicketUpdateRequestSerializer(serializers.Serializer):
    version = serializers.IntegerField(required=True)
    subject = serializers.CharField(max_length=200, required=False)
    description = serializers.CharField(required=False)
    category_id = serializers.IntegerField(required=False)
    priority_id = serializers.IntegerField(required=False)
    ticket_type = serializers.ChoiceField(choices=TICKET_TYPE_CHOICES, required=False)
    impact = serializers.ChoiceField(choices=IMPACT_CHOICES, required=False, allow_blank=True)
    urgency = serializers.ChoiceField(choices=URGENCY_CHOICES, required=False, allow_blank=True)
    external_reference = serializers.CharField(required=False, allow_blank=True, max_length=128)
    due_date = serializers.DateField(required=False, allow_null=True)
    team_id = serializers.IntegerField(required=False, allow_null=True)
    labels = serializers.ListField(child=serializers.CharField(max_length=50), required=False)
    parent_key = serializers.CharField(required=False, allow_null=True, allow_blank=True, max_length=32)


class TicketAssignRequestSerializer(serializers.Serializer):
    assignee_id = serializers.IntegerField(allow_null=True, required=True)
    version = serializers.IntegerField(required=False, allow_null=True)


class TicketTransitionRequestSerializer(serializers.Serializer):
    to_status_id = serializers.IntegerField(required=True)
    version = serializers.IntegerField(required=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    resolution_summary = serializers.CharField(required=False, allow_blank=True, default="")
    root_cause = serializers.CharField(required=False, allow_blank=True, default="")
    resolution_code = serializers.ChoiceField(choices=RESOLUTION_CODE_CHOICES, required=False, allow_blank=True, default="")


class WatcherRequestSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False, allow_null=True, help_text="Defaults to the caller.")


class TicketLinkRequestSerializer(serializers.Serializer):
    target_key = serializers.CharField(max_length=32)
    link_type = serializers.ChoiceField(choices=LINK_TYPE_CHOICES)


class CsatRequestSerializer(serializers.Serializer):
    score = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(required=False, allow_blank=True, default="")


class QueueStatsQuerySerializer(serializers.Serializer):
    days = serializers.IntegerField(required=False, min_value=1, max_value=365, default=30)


class QueueStatsPriorityItemSerializer(serializers.Serializer):
    priority_id = serializers.IntegerField(help_text="Primary key of the support priority.")
    name = serializers.CharField(help_text="Name of the priority.")
    rank = serializers.IntegerField(help_text="Rank of the priority for ordering.")
    count = serializers.IntegerField(help_text="Number of open tickets with this priority.")


class QueueStatsTeamItemSerializer(serializers.Serializer):
    team_id = serializers.IntegerField(allow_null=True, help_text="Primary key of the support team, or null if unassigned.")
    name = serializers.CharField(allow_blank=True, help_text="Name of the team.")
    count = serializers.IntegerField(help_text="Number of open tickets assigned to this team.")


class QueueStatsAssigneeItemSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(help_text="Primary key of the assigned user.")
    username = serializers.CharField(help_text="Username of the assignee.")
    count = serializers.IntegerField(help_text="Number of open tickets assigned to this user.")


class QueueStatsSlaSerializer(serializers.Serializer):
    response_breached = serializers.IntegerField(help_text="Count of tickets that breached response SLA.")
    resolution_breached = serializers.IntegerField(help_text="Count of tickets that breached resolution SLA.")
    overdue_resolution = serializers.IntegerField(help_text="Count of open tickets overdue for resolution.")
    paused = serializers.IntegerField(help_text="Count of tickets currently in SLA pause.")


class QueueStatsSerializer(serializers.Serializer):
    """Aggregate statistics and SLA metrics for the agent support queue dashboard."""

    window_days = serializers.IntegerField(help_text="Window in days used for recent throughput metrics.")
    open_total = serializers.IntegerField(help_text="Total number of active, non-done tickets.")
    unassigned = serializers.IntegerField(help_text="Total number of tickets without an assignee.")
    mine_open = serializers.IntegerField(help_text="Total number of open tickets assigned to the calling agent.")
    by_state = serializers.DictField(child=serializers.IntegerField(), help_text="Ticket count grouped by system state.")
    by_type = serializers.DictField(child=serializers.IntegerField(), help_text="Open ticket count grouped by ticket type.")
    by_priority = QueueStatsPriorityItemSerializer(many=True, help_text="Breakdown of open tickets by priority.")
    by_team = QueueStatsTeamItemSerializer(many=True, help_text="Breakdown of open tickets by team.")
    by_assignee = QueueStatsAssigneeItemSerializer(many=True, help_text="Breakdown of open tickets by assignee (top 20).")
    sla = QueueStatsSlaSerializer(help_text="Current SLA breach and pause counters.")
    created = serializers.IntegerField(help_text="Total tickets created within the window.")
    resolved = serializers.IntegerField(help_text="Total tickets resolved within the window.")
    reopened = serializers.IntegerField(help_text="Total tickets reopened within the window.")
    avg_first_response_minutes = serializers.FloatField(allow_null=True, help_text="Average first response time in minutes.")
    avg_resolution_minutes = serializers.FloatField(allow_null=True, help_text="Average resolution time in minutes.")
    csat_average = serializers.FloatField(allow_null=True, help_text="Average CSAT rating within the window (1.0 to 5.0).")
    csat_responses = serializers.IntegerField(help_text="Number of CSAT ratings submitted within the window.")


class LinkResourceRequestSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=ResourceType.choices())
    resource_id = serializers.CharField(max_length=64)


class UnlinkResourceRequestSerializer(serializers.Serializer):
    resource_type = serializers.ChoiceField(choices=ResourceType.choices())
    resource_id = serializers.CharField(max_length=64)
    reason = serializers.CharField(required=False, allow_blank=True, default="")


class CommentCreateRequestSerializer(serializers.Serializer):
    body = serializers.CharField()
    visibility = serializers.ChoiceField(
        choices=[v.value for v in CommentVisibility],
        default=CommentVisibility.PUBLIC.value,
        required=False,
    )


class CommentUpdateRequestSerializer(serializers.Serializer):
    body = serializers.CharField()


class AttachmentUploadRequestSerializer(serializers.Serializer):
    file = serializers.FileField()
    comment_id = serializers.IntegerField(required=False, allow_null=True)
    is_restricted = serializers.BooleanField(required=False, default=False)


class ResourceTicketDTOItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    key = serializers.CharField()
    subject = serializers.CharField()
    status_name = serializers.CharField()
    system_state = serializers.CharField()
    priority_name = serializers.CharField()
    priority_rank = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    is_link_active = serializers.BooleanField()


class ResourceTicketSummarySerializer(serializers.Serializer):
    open_count = serializers.IntegerField()
    total_count = serializers.IntegerField()
    tickets = ResourceTicketDTOItemSerializer(many=True)


# Admin configuration request serializers


@extend_schema_field({"type": "string", "pattern": r"^[-a-zA-Z0-9_]*$", "maxLength": 50})
class _OptionalCodeField(serializers.SlugField):
    """Document blank codes without changing SlugField validation or defaults."""


class AdminCategoryCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    code = _OptionalCodeField(required=False, allow_blank=True, max_length=50, default="")
    default_team_id = serializers.IntegerField(required=False, allow_null=True)
    description = serializers.CharField(required=False, allow_blank=True, default="")
    sort_order = serializers.IntegerField(required=False, default=0)
    is_active = serializers.BooleanField(required=False, default=True)


class AdminCategoryUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    code = serializers.SlugField(required=False, allow_blank=True, max_length=50)
    default_team_id = serializers.IntegerField(required=False)
    clear_default_team = serializers.BooleanField(required=False)
    description = serializers.CharField(required=False, allow_blank=True)
    sort_order = serializers.IntegerField(required=False)
    is_active = serializers.BooleanField(required=False)


_HEX = r"^(#[0-9A-Fa-f]{6})?$"


class AdminPriorityCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    rank = serializers.IntegerField(min_value=1)
    code = _OptionalCodeField(required=False, allow_blank=True, max_length=50, default="")
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True, default="")
    response_target_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    resolution_target_minutes = serializers.IntegerField(required=False, allow_null=True, min_value=1)
    is_default = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)


class AdminPriorityUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50, required=False)
    rank = serializers.IntegerField(required=False, min_value=1)
    code = serializers.SlugField(required=False, allow_blank=True, max_length=50)
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True)
    response_target_minutes = serializers.IntegerField(required=False, min_value=1)
    resolution_target_minutes = serializers.IntegerField(required=False, min_value=1)
    clear_response_target = serializers.BooleanField(required=False)
    clear_resolution_target = serializers.BooleanField(required=False)
    is_default = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)


class AdminStatusCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True, default="")
    is_final = serializers.BooleanField(required=False, default=False)
    pauses_sla = serializers.BooleanField(required=False, default=False)
    system_state = serializers.ChoiceField(choices=SystemState.choices())
    is_initial = serializers.BooleanField(required=False, default=False)
    is_active = serializers.BooleanField(required=False, default=True)
    sort_order = serializers.IntegerField(required=False, default=0)


class AdminStatusUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50, required=False)
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True)
    is_final = serializers.BooleanField(required=False)
    pauses_sla = serializers.BooleanField(required=False)
    system_state = serializers.ChoiceField(choices=SystemState.choices(), required=False)
    is_initial = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
    sort_order = serializers.IntegerField(required=False)


class AdminTransitionCreateSerializer(serializers.Serializer):
    from_status_id = serializers.IntegerField()
    to_status_id = serializers.IntegerField()
    allowed_roles = serializers.ListField(child=serializers.CharField(), required=False, default=list)
    requires_reason = serializers.BooleanField(required=False, default=False)
    requires_resolution = serializers.BooleanField(required=False, default=False)


class AdminTransitionUpdateSerializer(serializers.Serializer):
    allowed_roles = serializers.ListField(child=serializers.CharField(), required=False)
    requires_reason = serializers.BooleanField(required=False)
    requires_resolution = serializers.BooleanField(required=False)


class AdminSettingsUpdateSerializer(serializers.Serializer):
    reopen_window_days = serializers.IntegerField(required=False)
    auto_close_days = serializers.IntegerField(required=False)
    max_attachment_size_bytes = serializers.IntegerField(required=False)
    allowed_attachment_extensions = serializers.ListField(child=serializers.CharField(), required=False)
    max_attachments_per_ticket = serializers.IntegerField(required=False)
    comment_edit_window_minutes = serializers.IntegerField(required=False)
    requesters_can_set_priority = serializers.BooleanField(required=False)
    sla_enabled = serializers.BooleanField(required=False)
    sla_at_risk_percent = serializers.IntegerField(required=False, min_value=1, max_value=100)
    csat_enabled = serializers.BooleanField(required=False)
    csat_window_days = serializers.IntegerField(required=False, min_value=0)
    default_ticket_type = serializers.ChoiceField(choices=TICKET_TYPE_CHOICES, required=False)


class AdminTeamCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    code = _OptionalCodeField(required=False, allow_blank=True, max_length=50, default="")
    description = serializers.CharField(required=False, allow_blank=True, default="")
    lead_id = serializers.IntegerField(required=False, allow_null=True)
    member_ids = serializers.ListField(child=serializers.IntegerField(), required=False, default=list)
    is_active = serializers.BooleanField(required=False, default=True)


class AdminTeamUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100, required=False)
    code = serializers.SlugField(required=False, max_length=50)
    description = serializers.CharField(required=False, allow_blank=True)
    lead_id = serializers.IntegerField(required=False)
    clear_lead = serializers.BooleanField(required=False)
    member_ids = serializers.ListField(child=serializers.IntegerField(), required=False)
    is_active = serializers.BooleanField(required=False)


class AdminLabelCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50)
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True, default="")


class AdminLabelUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=50, required=False)
    color_hex = serializers.RegexField(_HEX, required=False, allow_blank=True)


class AdminCannedResponseCreateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    body = serializers.CharField()
    team_id = serializers.IntegerField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False, default=True)


class AdminCannedResponseUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120, required=False)
    body = serializers.CharField(required=False)
    team_id = serializers.IntegerField(required=False)
    clear_team = serializers.BooleanField(required=False)
    is_active = serializers.BooleanField(required=False)
