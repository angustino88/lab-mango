"""Application command use cases for support tickets."""

from core.support_desk.features.tickets.application.add_attachment import (
    AddAttachmentInput,
    add_attachment,
)
from core.support_desk.features.tickets.application.add_comment import (
    AddCommentInput,
    add_comment,
)
from core.support_desk.features.tickets.application.assign_ticket import (
    AssignTicketInput,
    assign_ticket,
)
from core.support_desk.features.tickets.application.create_ticket import (
    CreateTicketInput,
    create_ticket,
)
from core.support_desk.features.tickets.application.delete_attachment import (
    DeleteAttachmentInput,
    delete_attachment,
)
from core.support_desk.features.tickets.application.delete_comment import (
    DeleteCommentInput,
    delete_comment,
)
from core.support_desk.features.tickets.application.link_resource import (
    LinkResourceInput,
    link_resource,
)
from core.support_desk.features.tickets.application.manage_catalog import (
    CreateCannedResponseInput,
    CreateLabelInput,
    CreateTeamInput,
    UpdateCannedResponseInput,
    UpdateLabelInput,
    UpdateTeamInput,
    create_canned_response,
    create_label,
    create_team,
    delete_canned_response,
    delete_label,
    delete_team,
    list_canned_responses_for,
    render_canned_response,
    update_canned_response,
    update_label,
    update_team,
)
from core.support_desk.features.tickets.application.manage_config import (
    CreateCategoryInput,
    CreatePriorityInput,
    CreateStatusInput,
    CreateTransitionInput,
    UpdateCategoryInput,
    UpdatePriorityInput,
    UpdateSettingsInput,
    UpdateStatusInput,
    UpdateTransitionInput,
    create_category,
    create_priority,
    create_status,
    create_transition,
    delete_category,
    delete_priority,
    delete_transition,
    update_category,
    update_priority,
    update_settings,
    update_status,
    update_transition,
)
from core.support_desk.features.tickets.application.submit_csat import SubmitCsatInput, submit_csat
from core.support_desk.features.tickets.application.ticket_links import (
    LinkTicketsInput,
    UnlinkTicketsInput,
    link_tickets,
    unlink_tickets,
)
from core.support_desk.features.tickets.application.transition_ticket import (
    TransitionTicketInput,
    transition_ticket,
)
from core.support_desk.features.tickets.application.unlink_resource import (
    UnlinkResourceInput,
    unlink_resource,
)
from core.support_desk.features.tickets.application.update_comment import (
    UpdateCommentInput,
    update_comment,
)
from core.support_desk.features.tickets.application.update_ticket import (
    UpdateTicketInput,
    update_ticket,
)
from core.support_desk.features.tickets.application.watchers import WatcherInput, add_watcher, remove_watcher

__all__ = [
    "AddAttachmentInput",
    "AddCommentInput",
    "AssignTicketInput",
    "CreateCannedResponseInput",
    "CreateCategoryInput",
    "CreateLabelInput",
    "CreatePriorityInput",
    "CreateStatusInput",
    "CreateTeamInput",
    "CreateTicketInput",
    "CreateTransitionInput",
    "DeleteAttachmentInput",
    "DeleteCommentInput",
    "LinkResourceInput",
    "LinkTicketsInput",
    "SubmitCsatInput",
    "TransitionTicketInput",
    "UnlinkResourceInput",
    "UnlinkTicketsInput",
    "UpdateCannedResponseInput",
    "UpdateCategoryInput",
    "UpdateCommentInput",
    "UpdateLabelInput",
    "UpdatePriorityInput",
    "UpdateSettingsInput",
    "UpdateStatusInput",
    "UpdateTeamInput",
    "UpdateTicketInput",
    "UpdateTransitionInput",
    "WatcherInput",
    "add_attachment",
    "add_comment",
    "add_watcher",
    "assign_ticket",
    "create_canned_response",
    "create_category",
    "create_label",
    "create_priority",
    "create_status",
    "create_team",
    "create_ticket",
    "create_transition",
    "delete_attachment",
    "delete_canned_response",
    "delete_category",
    "delete_comment",
    "delete_label",
    "delete_priority",
    "delete_team",
    "delete_transition",
    "link_resource",
    "link_tickets",
    "list_canned_responses_for",
    "remove_watcher",
    "render_canned_response",
    "submit_csat",
    "transition_ticket",
    "unlink_resource",
    "unlink_tickets",
    "update_canned_response",
    "update_category",
    "update_comment",
    "update_label",
    "update_priority",
    "update_settings",
    "update_status",
    "update_team",
    "update_ticket",
    "update_transition",
]
