"""Unit tests for Support Desk application commands and business rules."""

from datetime import timedelta

import pytest
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, CommentVisibility, SystemState
from core.support_desk.exceptions import (
    AttachmentSizeLimitExceededError,
    AttachmentTypeNotAllowedError,
    CommentAuthorMismatchError,
    CommentEditWindowExpiredError,
    ConcurrencyConflictError,
    ConfigurationInUseError,
    DuplicateResourceLinkError,
    MissingResolutionSummaryError,
    MissingTransitionReasonError,
    PermissionDeniedError,
    ReopenWindowExpiredError,
    TicketCreationDisabledError,
)
from core.support_desk.features.tickets.application import (
    AddAttachmentInput,
    AddCommentInput,
    AssignTicketInput,
    CreateCategoryInput,
    CreateTicketInput,
    LinkResourceInput,
    TransitionTicketInput,
    UnlinkResourceInput,
    UpdateCommentInput,
    UpdateTicketInput,
    add_attachment,
    add_comment,
    assign_ticket,
    create_category,
    create_ticket,
    delete_category,
    link_resource,
    transition_ticket,
    unlink_resource,
    update_comment,
    update_ticket,
)
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.ticket import SupportTicket
from tests.factories import BenchFactory, UserFactory


@pytest.mark.django_db
class TestTicketCreation:
    def test_create_ticket_success_and_auto_sequence(self, support_setup, requester_user):
        cmd = CreateTicketInput(
            subject="Oscilloscope broken",
            description="Screen flickers and fails to calibrate.",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
        )
        ticket = create_ticket(cmd, actor=requester_user)

        assert ticket.id is not None
        assert ticket.key == f"SUP-{ticket.number:06d}"
        assert ticket.status.system_state == SystemState.OPEN.value
        assert ticket.requester == requester_user
        assert ticket.version == 1

        # Check activity entry was created
        act = TicketActivity.objects.filter(ticket=ticket, event_type=ActivityEventType.CREATED.value).first()
        assert act is not None
        assert act.actor == requester_user

        # Check outbox notifications were queued
        assert NotificationOutbox.objects.filter(payload__ticket_key=ticket.key).exists()

        # Second ticket gets next sequence
        ticket2 = create_ticket(cmd, actor=requester_user)
        assert ticket2.number == ticket.number + 1
        assert ticket2.key == f"SUP-{ticket2.number:06d}"

    def test_idempotency_key_prevents_duplicate(self, support_setup, requester_user):
        cmd = CreateTicketInput(
            subject="Idempotent test",
            description="Desc",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
            idempotency_key="idemp-key-12345",
        )
        t1 = create_ticket(cmd, actor=requester_user)
        t2 = create_ticket(cmd, actor=requester_user)
        assert t1.id == t2.id
        assert SupportTicket.objects.filter(idempotency_key="idemp-key-12345").count() == 1

    def test_create_ticket_disabled_if_no_category(self, support_setup, requester_user):
        SupportCategory.objects.all().update(is_active=False)
        cmd = CreateTicketInput(
            subject="Test",
            description="Desc",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
        )
        with pytest.raises(TicketCreationDisabledError):
            create_ticket(cmd, actor=requester_user)

    def test_create_on_behalf_of_other_user(self, support_setup, agent_user, requester_user):
        other_user = UserFactory(username="other_person")
        cmd = CreateTicketInput(
            subject="Reported on behalf",
            description="Created by agent for requester",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
            on_behalf_of_id=other_user.id,
        )
        ticket = create_ticket(cmd, actor=agent_user)
        assert ticket.created_by == agent_user
        assert ticket.requester == other_user

    def test_requester_cannot_create_on_behalf(self, support_setup, requester_user):
        other_user = UserFactory(username="other_person_2")
        cmd = CreateTicketInput(
            subject="Unauthorized behalf",
            description="Desc",
            category_id=support_setup["category"].id,
            priority_id=support_setup["priority_med"].id,
            on_behalf_of_id=other_user.id,
        )
        with pytest.raises(PermissionDeniedError):
            create_ticket(cmd, actor=requester_user)


@pytest.mark.django_db
class TestTicketUpdateAndConcurrency:
    def test_update_ticket_success(self, support_setup, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Initial",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        updated = update_ticket(
            UpdateTicketInput(
                ticket_key=ticket.key,
                version=ticket.version,
                subject="Updated subject",
            ),
            actor=requester_user,
        )
        assert updated.subject == "Updated subject"
        assert updated.version == 2

    def test_update_ticket_concurrency_conflict(self, support_setup, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Initial",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        with pytest.raises(ConcurrencyConflictError):
            update_ticket(
                UpdateTicketInput(
                    ticket_key=ticket.key,
                    version=ticket.version - 1,  # Stale version
                    subject="Stale update",
                ),
                actor=requester_user,
            )


@pytest.mark.django_db
class TestTicketAssignment:
    def test_agent_can_assign(self, support_setup, agent_user, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Assign me",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        assigned = assign_ticket(
            AssignTicketInput(ticket_key=ticket.key, assignee_id=agent_user.id),
            actor=agent_user,
        )
        assert assigned.assignee == agent_user
        assert TicketActivity.objects.filter(ticket=ticket, event_type=ActivityEventType.ASSIGNED.value).exists()

    def test_requester_cannot_assign(self, support_setup, requester_user, agent_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Assign attempt",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        with pytest.raises(PermissionDeniedError):
            assign_ticket(
                AssignTicketInput(ticket_key=ticket.key, assignee_id=agent_user.id),
                actor=requester_user,
            )


@pytest.mark.django_db
class TestTicketLifecycleTransitions:
    def test_full_lifecycle_and_reopen(self, support_setup, agent_user, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Lifecycle test",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        # Open -> In Progress (agent)
        t1 = transition_ticket(
            TransitionTicketInput(
                ticket_key=ticket.key,
                to_status_id=support_setup["status_active"].id,
                version=ticket.version,
            ),
            actor=agent_user,
        )
        assert t1.status == support_setup["status_active"]

        # In Progress -> Resolved without summary fails
        with pytest.raises(MissingResolutionSummaryError):
            transition_ticket(
                TransitionTicketInput(
                    ticket_key=ticket.key,
                    to_status_id=support_setup["status_resolved"].id,
                    version=t1.version,
                    resolution_summary="",
                ),
                actor=agent_user,
            )

        # In Progress -> Resolved with summary succeeds
        t2 = transition_ticket(
            TransitionTicketInput(
                ticket_key=ticket.key,
                to_status_id=support_setup["status_resolved"].id,
                version=t1.version,
                resolution_summary="Replaced fuse",
                root_cause="Overvoltage spike",
            ),
            actor=agent_user,
        )
        assert t2.status == support_setup["status_resolved"]
        assert t2.resolved_at is not None

        # Reopen without reason fails
        with pytest.raises(MissingTransitionReasonError):
            transition_ticket(
                TransitionTicketInput(
                    ticket_key=ticket.key,
                    to_status_id=support_setup["status_open"].id,
                    version=t2.version,
                    reason="",
                ),
                actor=requester_user,
            )

        # Reopen with reason succeeds
        t3 = transition_ticket(
            TransitionTicketInput(
                ticket_key=ticket.key,
                to_status_id=support_setup["status_open"].id,
                version=t2.version,
                reason="Issue reoccurred immediately",
            ),
            actor=requester_user,
        )
        assert t3.status == support_setup["status_open"]
        assert t3.reopen_count == 1
        assert TicketActivity.objects.filter(ticket=ticket, event_type=ActivityEventType.REOPENED.value).exists()

    def test_reopen_outside_window_rejected(self, support_setup, requester_user, agent_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Old resolved ticket",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        ticket.status = support_setup["status_resolved"]
        ticket.resolved_at = timezone.now() - timedelta(days=20)  # Configured window is 14 days
        ticket.save()

        with pytest.raises(ReopenWindowExpiredError):
            transition_ticket(
                TransitionTicketInput(
                    ticket_key=ticket.key,
                    to_status_id=support_setup["status_open"].id,
                    version=ticket.version,
                    reason="Too late",
                ),
                actor=requester_user,
            )


@pytest.mark.django_db
class TestTicketComments:
    def test_add_public_and_internal_comment(self, support_setup, requester_user, agent_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Comment test",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        # Requester adds public comment
        c1 = add_comment(
            AddCommentInput(ticket_key=ticket.key, body="Any updates?"),
            actor=requester_user,
        )
        assert c1.visibility == CommentVisibility.PUBLIC.value

        # Requester cannot add internal note
        with pytest.raises(PermissionDeniedError):
            add_comment(
                AddCommentInput(ticket_key=ticket.key, body="Internal note attempt", visibility=CommentVisibility.INTERNAL.value),
                actor=requester_user,
            )

        # Agent adds internal note
        c2 = add_comment(
            AddCommentInput(ticket_key=ticket.key, body="Internal diagnostic note", visibility=CommentVisibility.INTERNAL.value),
            actor=agent_user,
        )
        assert c2.visibility == CommentVisibility.INTERNAL.value

    def test_edit_comment_window_and_ownership(self, support_setup, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Comment edit test",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        c = add_comment(
            AddCommentInput(ticket_key=ticket.key, body="Original message"),
            actor=requester_user,
        )

        # Edit within window succeeds
        c_edited = update_comment(
            UpdateCommentInput(comment_id=c.id, body="Edited message"),
            actor=requester_user,
        )
        assert c_edited.body == "Edited message"
        assert c_edited.edited_at is not None

        # Another user cannot edit
        other_user = UserFactory()
        with pytest.raises(CommentAuthorMismatchError):
            update_comment(
                UpdateCommentInput(comment_id=c.id, body="Intruder edit"),
                actor=other_user,
            )

        # Edit outside 15 min window fails
        c.created_at = timezone.now() - timedelta(minutes=20)
        c.save(update_fields=["created_at"])
        with pytest.raises(CommentEditWindowExpiredError):
            update_comment(
                UpdateCommentInput(comment_id=c.id, body="Too late edit"),
                actor=requester_user,
            )


@pytest.mark.django_db
class TestTicketAttachments:
    def test_attachment_type_and_real_bytes_validation(self, support_setup, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Attachment test",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )

        # Valid text file
        att = add_attachment(
            AddAttachmentInput(
                ticket_key=ticket.key,
                filename="log.txt",
                content_type="text/plain",
                size=12,
                content=b"Sample log...",
            ),
            actor=requester_user,
        )
        assert att.id is not None
        assert att.filename == "log.txt"

        # Disallowed extension (.exe)
        with pytest.raises(AttachmentTypeNotAllowedError):
            add_attachment(
                AddAttachmentInput(
                    ticket_key=ticket.key,
                    filename="malicious.exe",
                    content_type="application/octet-stream",
                    size=10,
                    content=b"MZ\x90\x00\x03\x00\x00\x00",
                ),
                actor=requester_user,
            )

        # Executable disguised as .png
        with pytest.raises(AttachmentTypeNotAllowedError):
            add_attachment(
                AddAttachmentInput(
                    ticket_key=ticket.key,
                    filename="fake.png",
                    content_type="image/png",
                    size=10,
                    content=b"MZ\x90\x00fake",
                ),
                actor=requester_user,
            )

    def test_attachment_size_limit(self, support_setup, requester_user):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Large file test",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )
        support_setup["settings"].max_attachment_size_bytes = 100
        support_setup["settings"].save()

        with pytest.raises(AttachmentSizeLimitExceededError):
            add_attachment(
                AddAttachmentInput(
                    ticket_key=ticket.key,
                    filename="big.txt",
                    content_type="text/plain",
                    size=200,
                    content=b"A" * 200,
                ),
                actor=requester_user,
            )


@pytest.mark.django_db
class TestResourceTraceability:
    def test_link_and_unlink_resource_preserves_snapshot(self, support_setup, requester_user, agent_user):
        bench = BenchFactory(name="Traceable Bench")
        ticket = create_ticket(
            CreateTicketInput(
                subject="Bench issue",
                description="Desc",
                category_id=support_setup["category"].id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )

        link = link_resource(
            LinkResourceInput(ticket_key=ticket.key, resource_type="bench", resource_id=str(bench.id)),
            actor=requester_user,
        )
        assert link.is_active is True
        assert link.snapshot.get("name") == "Traceable Bench"

        # Duplicate link raises conflict
        with pytest.raises(DuplicateResourceLinkError):
            link_resource(
                LinkResourceInput(ticket_key=ticket.key, resource_type="bench", resource_id=str(bench.id)),
                actor=requester_user,
            )

        # Agent unlinks resource
        unlinked = unlink_resource(
            UnlinkResourceInput(
                ticket_key=ticket.key,
                resource_type="bench",
                resource_id=str(bench.id),
                reason="Linked by mistake",
            ),
            actor=agent_user,
        )
        assert unlinked.is_active is False
        assert unlinked.unlink_reason == "Linked by mistake"
        # Snapshot is retained forever for historical traceability
        assert unlinked.snapshot.get("name") == "Traceable Bench"


@pytest.mark.django_db
class TestAdminConfiguration:
    def test_delete_in_use_category_rejected(self, support_setup, requester_user, admin_user):
        cat = create_category(
            CreateCategoryInput(name="In Use Category"),
            actor=admin_user,
        )
        create_ticket(
            CreateTicketInput(
                subject="Ticket in category",
                description="Desc",
                category_id=cat.id,
                priority_id=support_setup["priority_med"].id,
            ),
            actor=requester_user,
        )

        with pytest.raises(ConfigurationInUseError):
            delete_category(cat.id, actor=admin_user)
