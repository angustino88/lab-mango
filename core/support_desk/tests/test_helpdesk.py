"""Tests for the professional helpdesk capabilities: visibility, SLA, triage, watchers, links, CSAT."""

from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from core.support_desk.contracts import ActivityEventType, SlaState, SystemState
from core.support_desk.exceptions import (
    CsatNotAllowedError,
    DuplicateTicketLinkError,
    InvalidFieldValueError,
    InvalidParentTicketError,
    InvalidTicketLinkError,
    PermissionDeniedError,
    SupportDeskError,
    TicketCreationDisabledError,
    TicketNotFoundError,
)
from core.support_desk.features.tickets.api.serializers import TicketListSerializer
from core.support_desk.features.tickets.application import (
    AddAttachmentInput,
    AddCommentInput,
    CreatePriorityInput,
    CreateStatusInput,
    CreateTeamInput,
    CreateTicketInput,
    LinkResourceInput,
    LinkTicketsInput,
    SubmitCsatInput,
    TransitionTicketInput,
    UnlinkTicketsInput,
    UpdateTicketInput,
    WatcherInput,
    add_attachment,
    add_comment,
    add_watcher,
    create_priority,
    create_status,
    create_team,
    create_ticket,
    link_resource,
    link_tickets,
    remove_watcher,
    submit_csat,
    transition_ticket,
    unlink_tickets,
    update_ticket,
)
from core.support_desk.features.tickets.application.policies import visible_tickets
from core.support_desk.features.tickets.application.sla import sla_summary
from core.support_desk.features.tickets.application.tasks import (
    flag_sla_breaches,
    process_notification_outbox,
    scan_pending_attachments,
)
from core.support_desk.features.tickets.queries import get_queue_stats, get_ticket_by_key, list_tickets
from core.support_desk.models.activity import TicketActivity
from core.support_desk.models.outbox import NotificationOutbox
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.ticket import SupportTicket
from core.support_desk.models.transition import SupportStatusTransition
from core.users.tests.factories import UserFactory


@pytest.fixture
def sla_setup(support_setup):
    """Adds SLA-bearing priorities and a 'Waiting for Customer' status that pauses the clocks."""
    critical = SupportPriority.objects.create(
        name="Critical", rank=1, response_target_minutes=30, resolution_target_minutes=240, is_active=True
    )
    normal = SupportPriority.objects.create(
        name="Normal", rank=2, response_target_minutes=60, resolution_target_minutes=480, is_active=True
    )
    waiting = SupportStatus.objects.create(
        name="Waiting for Customer",
        system_state=SystemState.WAITING.value,
        pauses_sla=True,
        sort_order=5,
    )
    s = support_setup
    SupportStatusTransition.objects.create(
        from_status=s["status_active"], to_status=waiting, allowed_roles=["agent", "admin"]
    )
    SupportStatusTransition.objects.create(
        from_status=waiting, to_status=s["status_active"], allowed_roles=["agent", "admin", "requester"]
    )
    SupportStatusTransition.objects.create(
        from_status=waiting, to_status=s["status_resolved"], allowed_roles=["agent", "admin"], requires_resolution=True
    )
    return {**s, "critical": critical, "normal": normal, "waiting": waiting}


def _new_ticket(setup, actor, **kw):
    cmd = CreateTicketInput(
        subject=kw.pop("subject", "Broken thing"),
        description="desc",
        category_id=setup["category"].id,
        priority_id=kw.pop("priority_id", setup["priority_med"].id),
        **kw,
    )
    return create_ticket(cmd, actor=actor)


def _move(ticket, status, actor, **kw):
    ticket.refresh_from_db()
    return transition_ticket(
        TransitionTicketInput(ticket_key=ticket.key, to_status_id=status.id, version=ticket.version, **kw), actor=actor
    )


# --------------------------------------------------------------------------- visibility


@pytest.mark.django_db
class TestVisibility:
    def test_requester_only_sees_own_created_or_watched_tickets(self, support_setup, requester_user, agent_user):
        other = UserFactory(username="other")
        mine = _new_ticket(support_setup, requester_user, subject="mine")
        theirs = _new_ticket(support_setup, other, subject="theirs")
        watched = _new_ticket(support_setup, other, subject="watched")
        add_watcher(WatcherInput(ticket_key=watched.key, user_id=requester_user.pk), actor=agent_user)

        seen = set(list_tickets(requester_user).values_list("key", flat=True))
        assert seen == {mine.key, watched.key}
        assert theirs.key not in seen
        assert set(list_tickets(agent_user).values_list("key", flat=True)) == {mine.key, theirs.key, watched.key}

    def test_anonymous_sees_nothing(self, support_setup, requester_user):
        from django.contrib.auth.models import AnonymousUser

        _new_ticket(support_setup, requester_user)
        assert visible_tickets(SupportTicket.objects.all(), AnonymousUser()).count() == 0

    def test_get_ticket_by_key_hides_foreign_ticket(self, support_setup, requester_user):
        other = UserFactory(username="other")
        theirs = _new_ticket(support_setup, other)
        assert get_ticket_by_key(theirs.key, viewer=requester_user) is None
        assert get_ticket_by_key(theirs.key, viewer=other) is not None

    def test_commands_reject_foreign_tickets_as_not_found(self, support_setup, requester_user):
        other = UserFactory(username="other")
        theirs = _new_ticket(support_setup, other)
        with pytest.raises(TicketNotFoundError):
            add_comment(AddCommentInput(ticket_key=theirs.key, body="hi"), actor=requester_user)
        with pytest.raises(TicketNotFoundError):
            add_attachment(
                AddAttachmentInput(ticket_key=theirs.key, filename="a.txt", content_type="text/plain", size=1, content=b"x"),
                actor=requester_user,
            )
        with pytest.raises(TicketNotFoundError):
            link_resource(LinkResourceInput(ticket_key=theirs.key, resource_type="room", resource_id="1"), actor=requester_user)
        with pytest.raises(TicketNotFoundError):
            update_ticket(UpdateTicketInput(ticket_key=theirs.key, version=1, subject="x"), actor=requester_user)
        with pytest.raises(TicketNotFoundError):
            add_watcher(WatcherInput(ticket_key=theirs.key), actor=requester_user)

    def test_list_serializer_has_no_n_plus_one(self, sla_setup, requester_user, agent_user):
        for i in range(6):
            _ = _new_ticket(sla_setup, requester_user, subject=f"t{i}", labels=()) if False else _new_ticket(
                sla_setup, agent_user, subject=f"t{i}", on_behalf_of_id=requester_user.pk, labels=("a", f"b{i}")
            )
        request = type("R", (), {"user": agent_user})()
        with CaptureQueriesContext(connection) as ctx:
            data = TicketListSerializer(list_tickets(agent_user), many=True, context={"request": request}).data
            assert len(data) == 6
        assert len(ctx) <= 5, f"expected a constant number of queries, got {len(ctx)}"


# --------------------------------------------------------------------------- priority & triage


@pytest.mark.django_db
class TestPriorityAndTriage:
    def test_priority_derived_from_impact_and_urgency(self, sla_setup, requester_user):
        crit = _new_ticket(sla_setup, requester_user, priority_id=None, impact="1", urgency="1")
        low = _new_ticket(sla_setup, requester_user, priority_id=None, impact="3", urgency="3")
        ranks = sorted(SupportPriority.objects.filter(is_active=True).values_list("rank", flat=True))
        assert crit.priority.rank == ranks[0]
        assert low.priority.rank == ranks[-1]

    def test_falls_back_to_default_priority(self, sla_setup, requester_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=None)
        assert t.priority_id == sla_setup["priority_med"].id

    def test_no_priority_and_no_default_is_rejected(self, sla_setup, requester_user):
        SupportPriority.objects.update(is_default=False)
        with pytest.raises(TicketCreationDisabledError):
            _new_ticket(sla_setup, requester_user, priority_id=None)

    def test_requester_priority_ignored_when_restricted(self, sla_setup, requester_user):
        cfg = sla_setup["settings"]
        cfg.requesters_can_set_priority = False
        cfg.save()
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id, impact="3", urgency="3")
        assert t.priority_id != sla_setup["critical"].id

    def test_requester_cannot_set_agent_only_fields(self, sla_setup, requester_user):
        with pytest.raises(PermissionDeniedError):
            _new_ticket(sla_setup, requester_user, labels=("x",))

    def test_invalid_choice_values_rejected(self, sla_setup, requester_user):
        with pytest.raises(InvalidFieldValueError):
            _new_ticket(sla_setup, requester_user, ticket_type="bogus")
        with pytest.raises(InvalidFieldValueError):
            _new_ticket(sla_setup, requester_user, impact="9")

    def test_category_default_team_routes_ticket_and_notifies_members(self, sla_setup, requester_user, agent_user, admin_user):
        team = create_team(CreateTeamInput(name="CAN Tooling", member_ids=(agent_user.pk,)), actor=admin_user)
        cat = sla_setup["category"]
        cat.default_team = team
        cat.save()
        t = _new_ticket(sla_setup, requester_user)
        assert t.team_id == team.id
        notified = set(
            NotificationOutbox.objects.filter(payload__event_name="ticket_created", channel="in_app").values_list(
                "recipient_id", flat=True
            )
        )
        assert agent_user.pk in notified

    def test_agent_triage_update_labels_team_parent_and_clear(self, sla_setup, requester_user, agent_user, admin_user):
        team = create_team(CreateTeamInput(name="Infra"), actor=admin_user)
        parent = _new_ticket(sla_setup, requester_user, subject="parent")
        child = _new_ticket(sla_setup, requester_user, subject="child")
        child = update_ticket(
            UpdateTicketInput(
                ticket_key=child.key,
                version=child.version,
                ticket_type="problem",
                team_id=team.id,
                labels=("Vendor-RMA", " calibration ", "vendor-rma"),
                parent_key=parent.key,
                external_reference="RMA-42",
            ),
            actor=agent_user,
        )
        assert child.ticket_type == "problem" and child.team_id == team.id
        assert sorted(child.labels.values_list("name", flat=True)) == ["calibration", "vendor-rma"]
        assert child.parent_id == parent.id and child.external_reference == "RMA-42"
        change_event = TicketActivity.objects.filter(ticket=child, event_type=ActivityEventType.UPDATED.value).last()
        assert change_event.payload["changes"]["labels"]["new"] == ["calibration", "vendor-rma"]

        child = update_ticket(
            UpdateTicketInput(ticket_key=child.key, version=child.version, clear_team=True, clear_parent=True, labels=()),
            actor=agent_user,
        )
        assert child.team_id is None and child.parent_id is None and child.labels.count() == 0

    def test_requester_cannot_triage(self, sla_setup, requester_user):
        t = _new_ticket(sla_setup, requester_user)
        with pytest.raises(PermissionDeniedError):
            update_ticket(UpdateTicketInput(ticket_key=t.key, version=t.version, labels=("x",)), actor=requester_user)

    def test_parent_rules(self, sla_setup, requester_user, agent_user):
        a, b, c = (_new_ticket(sla_setup, requester_user, subject=s) for s in "abc")
        b = update_ticket(UpdateTicketInput(ticket_key=b.key, version=b.version, parent_key=a.key), actor=agent_user)
        with pytest.raises(InvalidParentTicketError):  # grandchild
            update_ticket(UpdateTicketInput(ticket_key=c.key, version=c.version, parent_key=b.key), actor=agent_user)
        a.refresh_from_db()
        with pytest.raises(InvalidParentTicketError):  # parent with children cannot become a child
            update_ticket(UpdateTicketInput(ticket_key=a.key, version=a.version, parent_key=c.key), actor=agent_user)
        with pytest.raises(InvalidParentTicketError):  # self parent
            update_ticket(UpdateTicketInput(ticket_key=c.key, version=c.version, parent_key=c.key), actor=agent_user)


# --------------------------------------------------------------------------- SLA


@pytest.mark.django_db
class TestSla:
    def test_deadlines_computed_on_create(self, sla_setup, requester_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        assert t.response_due_at == t.created_at + timedelta(minutes=30)
        assert t.resolution_due_at == t.created_at + timedelta(minutes=240)

    def test_no_deadlines_when_priority_has_no_targets_or_sla_disabled(self, sla_setup, requester_user):
        t = _new_ticket(sla_setup, requester_user)  # "Medium" has no targets
        assert t.response_due_at is None and t.resolution_due_at is None
        cfg = sla_setup["settings"]
        cfg.sla_enabled = False
        cfg.save()
        t2 = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        assert t2.resolution_due_at is None

    def test_pause_resume_pushes_deadlines(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user, priority_id=s["critical"].id)
        t = _move(t, s["status_active"], agent_user)
        original_resolution = t.resolution_due_at
        t = _move(t, s["waiting"], agent_user)
        assert t.sla_paused_at is not None
        assert sla_summary(t)["state"] == SlaState.PAUSED.value

        # pretend the customer took 2 hours to answer
        SupportTicket.objects.filter(pk=t.pk).update(sla_paused_at=timezone.now() - timedelta(hours=2))
        t = _move(t, s["status_active"], agent_user)
        assert t.sla_paused_at is None
        assert 7190 <= t.sla_paused_seconds <= 7210
        assert abs((t.resolution_due_at - original_resolution) - timedelta(seconds=t.sla_paused_seconds)) < timedelta(seconds=1)
        kinds = set(TicketActivity.objects.filter(ticket=t).values_list("event_type", flat=True))
        assert {ActivityEventType.SLA_PAUSED.value, ActivityEventType.SLA_RESUMED.value} <= kinds

    def test_requester_reply_resumes_clock(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user, priority_id=s["critical"].id)
        t = _move(t, s["status_active"], agent_user)
        t = _move(t, s["waiting"], agent_user)
        SupportTicket.objects.filter(pk=t.pk).update(sla_paused_at=timezone.now() - timedelta(hours=1))
        add_comment(AddCommentInput(ticket_key=t.key, body="here you go"), actor=requester_user)
        t.refresh_from_db()
        assert t.status_id == s["status_active"].id
        assert t.sla_paused_at is None and t.sla_paused_seconds >= 3590
        event = TicketActivity.objects.filter(ticket=t, event_type=ActivityEventType.STATUS_CHANGED.value).last()
        assert event.payload["from_status"] == "Waiting for Customer"  # was hard-coded "Pending"

    def test_first_response_only_counts_public_agent_replies(self, sla_setup, requester_user, agent_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        add_comment(AddCommentInput(ticket_key=t.key, body="note", visibility="internal"), actor=agent_user)
        t.refresh_from_db()
        assert t.first_response_at is None
        add_comment(AddCommentInput(ticket_key=t.key, body="on it"), actor=agent_user)
        t.refresh_from_db()
        assert t.first_response_at is not None

    def test_breach_task_flags_once_and_notifies(self, sla_setup, requester_user, agent_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        SupportTicket.objects.filter(pk=t.pk).update(
            response_due_at=timezone.now() - timedelta(minutes=5),
            resolution_due_at=timezone.now() - timedelta(minutes=1),
            assignee=agent_user,
        )
        assert flag_sla_breaches() == 2
        assert flag_sla_breaches() == 0  # idempotent
        t.refresh_from_db()
        assert t.response_breached_at and t.resolution_breached_at
        assert TicketActivity.objects.filter(ticket=t, event_type=ActivityEventType.SLA_BREACHED.value).count() == 2
        assert NotificationOutbox.objects.filter(payload__event_name="sla_breached", recipient=agent_user).exists()
        assert sla_summary(t)["state"] == SlaState.BREACHED.value

    def test_breach_task_skips_paused_and_done_tickets(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        paused = _new_ticket(s, requester_user, priority_id=s["critical"].id)
        done = _new_ticket(s, requester_user, priority_id=s["critical"].id)
        past = timezone.now() - timedelta(hours=1)
        SupportTicket.objects.filter(pk=paused.pk).update(sla_paused_at=past, resolution_due_at=past, response_due_at=past)
        done = _move(done, s["status_active"], agent_user)
        done = _move(done, s["status_resolved"], agent_user, resolution_summary="fixed")
        SupportTicket.objects.filter(pk=done.pk).update(resolution_due_at=past, response_due_at=past)
        assert flag_sla_breaches() == 0

    def test_priority_change_rebases_deadlines(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user, priority_id=s["normal"].id)
        assert t.resolution_due_at == t.created_at + timedelta(minutes=480)
        t = update_ticket(
            UpdateTicketInput(ticket_key=t.key, version=t.version, priority_id=s["critical"].id), actor=agent_user
        )
        assert t.resolution_due_at == t.created_at + timedelta(minutes=240)

    def test_reopen_restarts_resolution_clock_and_clears_resolution_fields(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user, priority_id=s["critical"].id)
        t = _move(t, s["status_active"], agent_user)
        t = _move(t, s["status_resolved"], agent_user, resolution_summary="done", resolution_code="fixed")
        assert t.resolved_by_id == agent_user.pk and t.resolution_code == "fixed"
        SupportTicket.objects.filter(pk=t.pk).update(resolution_breached_at=timezone.now())
        t = _move(t, s["status_open"], requester_user, reason="still broken")
        assert t.resolved_at is None and t.resolved_by_id is None and t.resolution_code == ""
        assert t.resolution_breached_at is None
        assert t.resolution_due_at > timezone.now() + timedelta(minutes=200)
        assert t.reopen_count == 1

    def test_invalid_resolution_code_rejected(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user)
        t = _move(t, s["status_active"], agent_user)
        with pytest.raises(InvalidFieldValueError):
            _move(t, s["status_resolved"], agent_user, resolution_summary="x", resolution_code="nope")

    def test_closing_stamps_closed_at_via_is_final_flag(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user)
        t = _move(t, s["status_active"], agent_user)
        t = _move(t, s["status_resolved"], agent_user, resolution_summary="ok")
        assert t.closed_at is None  # "Resolved" is not final
        t = _move(t, s["status_closed"], agent_user)
        assert t.closed_at is not None and t.resolved_at is not None

    def test_summary_at_risk(self, sla_setup, requester_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        t = SupportTicket.objects.select_related("status").get(pk=t.pk)
        later = t.created_at + timedelta(minutes=25)  # 83% of the 30 min response window
        assert sla_summary(t, now=later, at_risk_percent=80)["response"]["state"] == SlaState.AT_RISK.value
        assert sla_summary(t, now=t.created_at + timedelta(minutes=1), at_risk_percent=80)["state"] == SlaState.OK.value


# --------------------------------------------------------------------------- admin config validation


@pytest.mark.django_db
class TestConfigValidation:
    def test_response_target_cannot_exceed_resolution_target(self, admin_user):
        with pytest.raises(SupportDeskError):
            create_priority(
                CreatePriorityInput(name="Bad", rank=9, response_target_minutes=100, resolution_target_minutes=50),
                actor=admin_user,
            )

    def test_status_flag_rules(self, admin_user):
        with pytest.raises(SupportDeskError):
            create_status(CreateStatusInput(name="X", system_state="open", is_final=True), actor=admin_user)
        with pytest.raises(SupportDeskError):
            create_status(CreateStatusInput(name="Y", system_state="done", pauses_sla=True), actor=admin_user)
        ok = create_status(CreateStatusInput(name="Waiting", system_state="waiting", pauses_sla=True), actor=admin_user)
        assert ok.pauses_sla

    def test_only_admins_manage_teams(self, requester_user):
        with pytest.raises(PermissionDeniedError):
            create_team(CreateTeamInput(name="Nope"), actor=requester_user)


# --------------------------------------------------------------------------- watchers, links, CSAT


@pytest.mark.django_db
class TestCollaboration:
    def test_watcher_lifecycle_permissions_and_notifications(self, sla_setup, requester_user, agent_user):
        other = UserFactory(username="colleague")
        t = _new_ticket(sla_setup, requester_user)
        with pytest.raises(PermissionDeniedError):  # requester cannot subscribe somebody else
            add_watcher(WatcherInput(ticket_key=t.key, user_id=other.pk), actor=requester_user)
        add_watcher(WatcherInput(ticket_key=t.key, user_id=other.pk), actor=agent_user)
        add_watcher(WatcherInput(ticket_key=t.key, user_id=other.pk), actor=agent_user)  # idempotent
        assert t.watchers.count() == 1
        add_comment(AddCommentInput(ticket_key=t.key, body="update"), actor=agent_user)
        assert NotificationOutbox.objects.filter(
            payload__event_name="comment_added", recipient=other, channel="email"
        ).exists()
        # internal notes never reach watchers
        add_comment(AddCommentInput(ticket_key=t.key, body="secret", visibility="internal"), actor=agent_user)
        assert not NotificationOutbox.objects.filter(
            payload__event_name="comment_added", payload__visibility="internal", recipient=other
        ).exists()
        remove_watcher(WatcherInput(ticket_key=t.key, user_id=other.pk), actor=agent_user)
        remove_watcher(WatcherInput(ticket_key=t.key, user_id=other.pk), actor=agent_user)  # idempotent
        assert t.watchers.count() == 0
        kinds = list(TicketActivity.objects.filter(ticket=t).values_list("event_type", flat=True))
        assert kinds.count(ActivityEventType.WATCHER_ADDED.value) == 1
        assert kinds.count(ActivityEventType.WATCHER_REMOVED.value) == 1

    def test_requester_can_follow_and_unfollow_self(self, sla_setup, requester_user, agent_user):
        other = UserFactory(username="colleague")
        t = _new_ticket(sla_setup, other)
        add_watcher(WatcherInput(ticket_key=t.key, user_id=requester_user.pk), actor=agent_user)
        remove_watcher(WatcherInput(ticket_key=t.key), actor=requester_user)
        assert t.watchers.count() == 0

    def test_ticket_links(self, sla_setup, requester_user, agent_user):
        a = _new_ticket(sla_setup, requester_user, subject="a")
        b = _new_ticket(sla_setup, requester_user, subject="b")
        link = link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=b.key, link_type="blocks"), actor=agent_user)
        assert TicketActivity.objects.filter(event_type=ActivityEventType.TICKET_LINKED.value).count() == 2
        with pytest.raises(DuplicateTicketLinkError):
            link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=b.key, link_type="blocks"), actor=agent_user)
        with pytest.raises(InvalidTicketLinkError):
            link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=a.key, link_type="blocks"), actor=agent_user)
        with pytest.raises(InvalidTicketLinkError):
            link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=b.key, link_type="nonsense"), actor=agent_user)
        with pytest.raises(PermissionDeniedError):
            link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=b.key, link_type="relates_to"), actor=requester_user)
        unlink_tickets(UnlinkTicketsInput(ticket_key=b.key, link_id=link.pk), actor=agent_user)  # from target side
        assert a.outgoing_links.count() == 0

    def test_relates_to_is_symmetric(self, sla_setup, requester_user, agent_user):
        a = _new_ticket(sla_setup, requester_user, subject="a")
        b = _new_ticket(sla_setup, requester_user, subject="b")
        link_tickets(LinkTicketsInput(ticket_key=a.key, target_key=b.key, link_type="relates_to"), actor=agent_user)
        with pytest.raises(DuplicateTicketLinkError):
            link_tickets(LinkTicketsInput(ticket_key=b.key, target_key=a.key, link_type="relates_to"), actor=agent_user)

    def test_csat_rules(self, sla_setup, requester_user, agent_user):
        s = sla_setup
        t = _new_ticket(s, requester_user)
        with pytest.raises(CsatNotAllowedError):  # not resolved yet
            submit_csat(SubmitCsatInput(ticket_key=t.key, score=5), actor=requester_user)
        t = _move(t, s["status_active"], agent_user)
        t = _move(t, s["status_resolved"], agent_user, resolution_summary="ok")
        with pytest.raises(PermissionDeniedError):
            submit_csat(SubmitCsatInput(ticket_key=t.key, score=5), actor=agent_user)
        with pytest.raises(InvalidFieldValueError):
            submit_csat(SubmitCsatInput(ticket_key=t.key, score=6), actor=requester_user)
        t = submit_csat(SubmitCsatInput(ticket_key=t.key, score=4, comment="quick"), actor=requester_user)
        assert t.csat_score == 4 and t.csat_submitted_at
        stats = get_queue_stats(viewer=agent_user)
        assert stats["csat_average"] == 4.0 and stats["csat_responses"] == 1

        SupportTicket.objects.filter(pk=t.pk).update(resolved_at=timezone.now() - timedelta(days=30))
        with pytest.raises(CsatNotAllowedError):  # window expired
            submit_csat(SubmitCsatInput(ticket_key=t.key, score=1), actor=requester_user)

    def test_queue_stats_shape(self, sla_setup, requester_user, agent_user):
        t = _new_ticket(sla_setup, requester_user, priority_id=sla_setup["critical"].id)
        SupportTicket.objects.filter(pk=t.pk).update(resolution_due_at=timezone.now() - timedelta(minutes=1))
        stats = get_queue_stats(viewer=agent_user)
        assert stats["open_total"] == 1 and stats["unassigned"] == 1
        assert stats["sla"]["overdue_resolution"] == 1
        assert stats["by_priority"][0]["name"] == "Critical"


# --------------------------------------------------------------------------- background jobs


@pytest.mark.django_db
class TestBackgroundJobs:
    def test_outbox_row_is_not_dispatched_twice(self, requester_user):
        from django.core import mail

        NotificationOutbox.objects.create(
            event_id="e1", recipient=requester_user, channel="email", payload={"subject": "s", "message": "m"}
        )
        assert process_notification_outbox() == 1
        assert process_notification_outbox() == 0
        assert len(mail.outbox) == 1

    def test_claimed_rows_are_leased(self, requester_user):
        from core.support_desk.features.tickets.application.tasks import _claim_outbox_batch

        row = NotificationOutbox.objects.create(
            event_id="e2", recipient=requester_user, channel="in_app", payload={"message": "m"}
        )
        assert _claim_outbox_batch(10) == [row.pk]
        assert _claim_outbox_batch(10) == []  # leased: a second worker sees nothing

    def test_email_html_is_escaped_and_link_absolute(self, requester_user, settings):
        from django.core import mail

        settings.SUPPORT_DESK_BASE_URL = "https://mango.example.com/"
        NotificationOutbox.objects.create(
            event_id="e3",
            recipient=requester_user,
            channel="email",
            payload={"subject": "s", "message": "<script>alert(1)</script>", "deep_link": "/support/tickets/SUP-1"},
        )
        process_notification_outbox()
        html = mail.outbox[0].alternatives[0][0]
        assert "<script>" not in html and "&lt;script&gt;" in html
        assert 'href="https://mango.example.com/support/tickets/SUP-1"' in html

    def test_pending_attachments_use_pluggable_scanner(self, sla_setup, requester_user, settings):
        from core.support_desk.contracts import AttachmentScanStatus
        from core.support_desk.models.attachment import TicketAttachment

        t = _new_ticket(sla_setup, requester_user)
        att = TicketAttachment.objects.create(
            ticket=t, uploaded_by=requester_user, filename="a.txt", content_type="text/plain", size=1,
            scan_status=AttachmentScanStatus.PENDING.value,
        )
        settings.SUPPORT_DESK_ATTACHMENT_SCANNER = "core.support_desk.tests.fake_scanner.always_clean"
        assert scan_pending_attachments() == 1
        att.refresh_from_db()
        assert att.scan_status == AttachmentScanStatus.CLEAN.value

    def test_new_uploads_quarantined_only_when_external_scanner_configured(self, sla_setup, requester_user, settings):
        t = _new_ticket(sla_setup, requester_user)
        a = add_attachment(
            AddAttachmentInput(ticket_key=t.key, filename="a.txt", content_type="text/plain", size=1, content=b"x"),
            actor=requester_user,
        )
        assert a.scan_status == "clean"
        settings.SUPPORT_DESK_ATTACHMENT_SCANNER = "core.support_desk.tests.fake_scanner.always_clean"
        b = add_attachment(
            AddAttachmentInput(ticket_key=t.key, filename="b.txt", content_type="text/plain", size=1, content=b"y"),
            actor=requester_user,
        )
        assert b.scan_status == "pending"
