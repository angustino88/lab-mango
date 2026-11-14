"""URL routes for Support Desk ticket feature."""

from django.urls import path

from core.common.api.deprecation import deprecated_alias

from . import views


def _ticket_action(verb: str):
    return lambda key, **_: f"/api/support/tickets/{key}/actions/{verb}"


# ACT-1: non-CRUD ticket operations are actions; the old paths stay for one release (VER-3).
DeprecatedTicketAssign = deprecated_alias(
    views.TicketAssignAPIView,
    successor=_ticket_action("assign"),
    description="Deprecated alias; use POST /api/support/tickets/{key}/actions/assign.",
)
DeprecatedTicketTransition = deprecated_alias(
    views.TicketTransitionAPIView,
    successor=_ticket_action("transition"),
    description="Deprecated alias; use POST /api/support/tickets/{key}/actions/transition.",
)
DeprecatedTicketCsat = deprecated_alias(
    views.TicketCsatAPIView,
    successor=_ticket_action("submit-csat"),
    description="Deprecated alias; use POST /api/support/tickets/{key}/actions/submit-csat.",
)

urlpatterns = [
    # Ticket collections and detail
    path("tickets", views.TicketListCreateAPIView.as_view(), name="ticket-list-create"),
    path("tickets/stats", views.QueueStatsAPIView.as_view(), name="ticket-queue-stats"),
    path("tickets/<str:key>", views.TicketDetailAPIView.as_view(), name="ticket-detail"),
    path("tickets/<str:key>/actions/assign", views.TicketAssignAPIView.as_view(), name="ticket-assign"),
    path("tickets/<str:key>/actions/transition", views.TicketTransitionAPIView.as_view(), name="ticket-transition"),
    path("tickets/<str:key>/actions/submit-csat", views.TicketCsatAPIView.as_view(), name="ticket-csat"),
    path("tickets/<str:key>/assign", DeprecatedTicketAssign.as_view(), name="ticket-assign-deprecated"),
    path("tickets/<str:key>/transitions", DeprecatedTicketTransition.as_view(), name="ticket-transition-deprecated"),
    path("tickets/<str:key>/resources", views.TicketResourceLinkAPIView.as_view(), name="ticket-resources"),
    path("tickets/<str:key>/comments", views.TicketCommentListCreateAPIView.as_view(), name="ticket-comments"),
    path("tickets/<str:key>/comments/<int:comment_id>", views.TicketCommentDetailAPIView.as_view(), name="ticket-comment-detail"),
    path("tickets/<str:key>/attachments", views.TicketAttachmentListCreateAPIView.as_view(), name="ticket-attachments"),
    path("tickets/<str:key>/attachments/<int:attachment_id>", views.TicketAttachmentDetailAPIView.as_view(), name="ticket-attachment-detail"),
    path("tickets/<str:key>/watchers", views.TicketWatcherAPIView.as_view(), name="ticket-watchers"),
    path("tickets/<str:key>/links", views.TicketLinkListCreateAPIView.as_view(), name="ticket-links"),
    path("tickets/<str:key>/links/<int:link_id>", views.TicketLinkDetailAPIView.as_view(), name="ticket-link-detail"),
    path("tickets/<str:key>/csat", DeprecatedTicketCsat.as_view(), name="ticket-csat-deprecated"),
    path("tickets/<str:key>/activity", views.TicketActivityListAPIView.as_view(), name="ticket-activity"),

    # Direct attachments download
    path("attachments/<int:attachment_id>/download", views.TicketAttachmentDownloadAPIView.as_view(), name="ticket-attachment-download"),

    # Resource ticket history
    path("resources/<str:resource_type>/<str:resource_id>/tickets", views.ResourceTicketHistoryAPIView.as_view(), name="resource-ticket-history"),

    # Categories catalog and options
    path("categories", views.AdminCategoryListCreateAPIView.as_view(), name="category-list-create"),
    path("categories/options", views.CategoryOptionsAPIView.as_view(), name="support-categories-options"),
    path("categories/<int:category_id>", views.AdminCategoryDetailAPIView.as_view(), name="category-detail"),

    # Priorities catalog and options
    path("priorities", views.AdminPriorityListCreateAPIView.as_view(), name="priority-list-create"),
    path("priorities/options", views.PriorityOptionsAPIView.as_view(), name="support-priorities-options"),
    path("priorities/<int:priority_id>", views.AdminPriorityDetailAPIView.as_view(), name="priority-detail"),

    # Statuses catalog and options
    path("statuses", views.AdminStatusListCreateAPIView.as_view(), name="status-list-create"),
    path("statuses/options", views.StatusOptionsAPIView.as_view(), name="support-statuses-options"),
    path("statuses/<int:status_id>", views.AdminStatusDetailAPIView.as_view(), name="status-detail"),

    # Teams catalog and options
    path("teams", views.AdminTeamListCreateAPIView.as_view(), name="team-list-create"),
    path("teams/options", views.TeamOptionsAPIView.as_view(), name="support-teams-options"),
    path("teams/<int:team_id>", views.AdminTeamDetailAPIView.as_view(), name="team-detail"),

    # Labels catalog and options
    path("labels", views.AdminLabelListCreateAPIView.as_view(), name="label-list-create"),
    path("labels/options", views.LabelOptionsAPIView.as_view(), name="support-labels-options"),
    path("labels/<int:label_id>", views.AdminLabelDetailAPIView.as_view(), name="label-detail"),

    path("canned-responses", views.CannedResponseListAPIView.as_view(), name="canned-response-list"),

    # Admin configuration (workflow, canned responses, settings)
    path("admin/transitions", views.AdminTransitionListCreateAPIView.as_view(), name="admin-transition-list-create"),
    path("admin/transitions/<int:transition_id>", views.AdminTransitionDetailAPIView.as_view(), name="admin-transition-detail"),
    path("admin/canned-responses", views.AdminCannedResponseListCreateAPIView.as_view(), name="admin-canned-response-list-create"),
    path("admin/canned-responses/<int:response_id>", views.AdminCannedResponseDetailAPIView.as_view(), name="admin-canned-response-detail"),
    path("admin/settings", views.AdminSettingsAPIView.as_view(), name="admin-settings"),
]
