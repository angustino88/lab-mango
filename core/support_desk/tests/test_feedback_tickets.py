"""Tests for Support Desk platform feedback ticket types, context capture, SLA rules, and CSAT eligibility."""

from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.utils import timezone

from core.support_desk.contracts import NON_SLA_TICKET_TYPES, TicketType
from core.support_desk.exceptions import CsatNotAllowedError, InvalidFieldValueError, PermissionDeniedError
from core.support_desk.features.tickets.application.create_ticket import CreateTicketInput, create_ticket
from core.support_desk.features.tickets.application.policies import is_csat_submission_open
from core.support_desk.features.tickets.application.submit_csat import SubmitCsatInput, submit_csat
from core.support_desk.features.tickets.application.transition_ticket import (
    TransitionTicketInput,
    transition_ticket,
)
from core.support_desk.features.tickets.application.triage import sanitize_client_context, sanitize_page_path
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.settings import SupportSettings
from core.support_desk.models.ticket import SupportTicket

pytestmark = pytest.mark.django_db


class TestContextSanitization:
    def test_sanitize_page_path_strips_query_and_fragment(self):
        assert sanitize_page_path("  /booking-calendar?token=abc#section  ") == "/booking-calendar"
        assert sanitize_page_path("") == ""
        assert sanitize_page_path("   ") == ""

    @pytest.mark.parametrize(
        "bad_path",
        [
            "https://evil.example/login",
            "//evil.example/path",
            "booking-calendar",
            "/labs/../admin",
            "/labs\n/inject",
            "/" + ("a" * 260),
        ],
    )
    def test_sanitize_page_path_rejects_unsafe_values(self, bad_path):
        with pytest.raises(InvalidFieldValueError):
            sanitize_page_path(bad_path)

    def test_sanitize_client_context_allowlist_and_bounds(self):
        cleaned = sanitize_client_context(
            {
                "browser": " Chrome 131 ",
                "os": "Linux",
                "viewport": "1440x900",
                "theme": "dark",
                "app_version": "",
                "language": "en-US",
            }
        )
        assert cleaned == {
            "browser": "Chrome 131",
            "os": "Linux",
            "viewport": "1440x900",
            "theme": "dark",
            "language": "en-US",
        }

        with pytest.raises(InvalidFieldValueError):
            sanitize_client_context({"token": "secret"})

        with pytest.raises(InvalidFieldValueError):
            sanitize_client_context({"browser": "x" * 65})

    def test_db_constraint_rejects_non_relative_page_path(self, support_setup, requester_user):
        with pytest.raises(IntegrityError):
            SupportTicket.objects.create(
                subject="Constraint check",
                description="Invalid page path",
                category=support_setup["category"],
                priority=support_setup["priority_med"],
                status=support_setup["status_open"],
                requester=requester_user,
                created_by=requester_user,
                page_path="https://external.example/bad",
            )


class TestFeedbackTicketWorkflow:
    def test_create_feedback_ticket_without_category_id_resolves_default_and_skips_sla(
        self, support_setup, requester_client
    ):
        resp = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Improve calendar keyboard navigation",
                "description": "Allow arrow keys when switching booking slots.",
                "ticket_type": TicketType.FEATURE_REQUEST.value,
                "page_path": "/booking-calendar?week=48#top",
                "client_context": {"browser": "Chrome 131", "theme": "dark", "viewport": "1440x900"},
            },
            format="json",
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()["data"]
        assert data["ticket_type"] == {"value": "feature_request", "label": "Feature Request"}
        assert data["category"]["id"] == support_setup["category"].id
        assert data["page_path"] == "/booking-calendar"
        assert data["client_context"] == {"browser": "Chrome 131", "theme": "dark", "viewport": "1440x900"}
        assert data["sla"]["state"] == "none"
        assert data["sla"]["response"]["due_at"] is None
        assert data["sla"]["resolution"]["due_at"] is None
        assert data["can_submit_csat"] is False

    def test_create_bug_ticket_prefers_matching_category_code_and_applies_sla(self, support_setup, requester_client):
        priority = support_setup["priority_med"]
        priority.response_target_minutes = 60
        priority.resolution_target_minutes = 240
        priority.save(update_fields=["response_target_minutes", "resolution_target_minutes"])
        bug_category = SupportCategory.objects.create(name="Platform Bugs", code="bug", is_active=True)

        resp = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Floor plan zoom resets after filter change",
                "description": "Steps to reproduce: open 3D dashboard and toggle overlay.",
                "ticket_type": TicketType.BUG.value,
                "page_path": "/dashboard/3d",
            },
            format="json",
        )
        assert resp.status_code == 201, resp.json()
        data = resp.json()["data"]
        assert data["ticket_type"] == {"value": "bug", "label": "Bug"}
        assert data["category"] == {"id": bug_category.id, "name": "Platform Bugs"}
        assert data["page_path"] == "/dashboard/3d"
        assert data["sla"]["state"] != "none"
        assert data["sla"]["response"]["due_at"] is not None
        assert data["sla"]["resolution"]["due_at"] is not None

    def test_reclassifying_between_feedback_and_bug_toggles_sla_deadlines(
        self, support_setup, agent_client, requester_user
    ):
        priority = support_setup["priority_med"]
        priority.response_target_minutes = 60
        priority.resolution_target_minutes = 240
        priority.save(update_fields=["response_target_minutes", "resolution_target_minutes"])
        ticket = create_ticket(
            CreateTicketInput(
                subject="Slow equipment search",
                description="Filtering takes several seconds.",
                ticket_type=TicketType.FEEDBACK.value,
                page_path="/lab-equipment/computing",
            ),
            actor=requester_user,
        )
        assert ticket.response_due_at is None
        assert ticket.resolution_due_at is None

        # Reclassify feedback -> bug starts SLA tracking
        resp_bug = agent_client.patch(
            f"/api/support/tickets/{ticket.key}",
            {"version": ticket.version, "ticket_type": TicketType.BUG.value},
            format="json",
        )
        assert resp_bug.status_code == 200, resp_bug.json()
        bug_data = resp_bug.json()["data"]
        assert bug_data["sla"]["response"]["due_at"] is not None
        assert bug_data["sla"]["resolution"]["due_at"] is not None

        # Reclassify bug -> feature_request clears open SLA deadlines
        resp_feat = agent_client.patch(
            f"/api/support/tickets/{ticket.key}",
            {"version": bug_data["version"], "ticket_type": TicketType.FEATURE_REQUEST.value},
            format="json",
        )
        assert resp_feat.status_code == 200, resp_feat.json()
        feat_data = resp_feat.json()["data"]
        assert feat_data["sla"]["state"] == "none"
        assert feat_data["sla"]["response"]["due_at"] is None
        assert feat_data["sla"]["resolution"]["due_at"] is None

    def test_filter_and_search_by_page_path_and_ticket_type(self, support_setup, agent_client, requester_user):
        create_ticket(
            CreateTicketInput(
                subject="Booking overlap warning",
                description="Clarify message",
                ticket_type=TicketType.FEEDBACK.value,
                page_path="/booking-calendar",
            ),
            actor=requester_user,
        )
        create_ticket(
            CreateTicketInput(
                subject="Export timeout",
                description="Finance export slow",
                ticket_type=TicketType.BUG.value,
                page_path="/finance-report",
            ),
            actor=requester_user,
        )

        by_path = agent_client.get("/api/support/tickets?page_path=/booking-calendar")
        assert by_path.status_code == 200
        assert len(by_path.json()["data"]) == 1
        assert by_path.json()["data"][0]["subject"] == "Booking overlap warning"

        by_type = agent_client.get("/api/support/tickets?ticket_type=bug")
        assert by_type.status_code == 200
        assert len(by_type.json()["data"]) == 1
        assert by_type.json()["data"][0]["subject"] == "Export timeout"

    def test_invalid_page_path_or_client_context_returns_422(self, support_setup, requester_client):
        resp_path = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Bad path",
                "description": "Testing validation",
                "ticket_type": TicketType.FEEDBACK.value,
                "page_path": "https://evil.example/phish",
            },
            format="json",
        )
        assert resp_path.status_code == 422

        resp_ctx = requester_client.post(
            "/api/support/tickets",
            {
                "subject": "Bad context",
                "description": "Testing validation",
                "ticket_type": TicketType.FEEDBACK.value,
                "client_context": {"cookie": "sessionid=secret"},
            },
            format="json",
        )
        assert resp_ctx.status_code == 422

    def test_can_submit_csat_flag_and_submission_flow(
        self, support_setup, requester_client, agent_client, requester_user
    ):
        ticket = create_ticket(
            CreateTicketInput(
                subject="Dark mode contrast in table",
                description="Row hover state is faint.",
                ticket_type=TicketType.FEEDBACK.value,
            ),
            actor=requester_user,
        )

        # Open ticket cannot be rated yet
        detail_open = requester_client.get(f"/api/support/tickets/{ticket.key}")
        assert detail_open.status_code == 200
        assert detail_open.json()["data"]["can_submit_csat"] is False

        # Transition Open -> In Progress -> Resolved as agent
        in_progress_resp = agent_client.post(
            f"/api/support/tickets/{ticket.key}/actions/transition",
            {
                "to_status_id": support_setup["status_active"].id,
                "version": ticket.version,
            },
            format="json",
        )
        assert in_progress_resp.status_code == 200, in_progress_resp.json()
        next_version = in_progress_resp.json()["data"]["version"]

        resolved_status = support_setup["status_resolved"]
        transition = agent_client.post(
            f"/api/support/tickets/{ticket.key}/actions/transition",
            {
                "to_status_id": resolved_status.id,
                "version": next_version,
                "resolution_summary": "Updated dark theme row hover token.",
                "resolution_code": "fixed",
            },
            format="json",
        )
        assert transition.status_code == 200, transition.json()

        # Requester sees can_submit_csat=True; agent sees False
        req_detail = requester_client.get(f"/api/support/tickets/{ticket.key}")
        assert req_detail.status_code == 200
        assert req_detail.json()["data"]["can_submit_csat"] is True

        agent_detail = agent_client.get(f"/api/support/tickets/{ticket.key}")
        assert agent_detail.status_code == 200
        assert agent_detail.json()["data"]["can_submit_csat"] is False

        # Requester submits CSAT
        csat_resp = requester_client.post(
            f"/api/support/tickets/{ticket.key}/actions/submit-csat",
            {"score": 5, "comment": "Super fast fix!"},
            format="json",
        )
        assert csat_resp.status_code == 200, csat_resp.json()
        csat_data = csat_resp.json()["data"]
        assert csat_data["csat_score"] == 5
        assert csat_data["csat_comment"] == "Super fast fix!"
        assert csat_data["can_submit_csat"] is True  # still amendable within window

        # Expired window turns can_submit_csat=False
        app_settings = SupportSettings.get_solo()
        SupportTicket.objects.filter(pk=ticket.pk).update(
            resolved_at=timezone.now() - timedelta(days=app_settings.csat_window_days + 2)
        )
        expired_detail = requester_client.get(f"/api/support/tickets/{ticket.key}")
        assert expired_detail.status_code == 200
        assert expired_detail.json()["data"]["can_submit_csat"] is False

    def test_ticket_list_and_detail_query_budgets_with_feedback_context(
        self, support_setup, agent_client, requester_user, django_assert_num_queries
    ):
        tickets = [
            create_ticket(
                CreateTicketInput(
                    subject=f"Feedback item {idx}",
                    description="Context capture test",
                    ticket_type=TicketType.FEEDBACK.value if idx % 2 == 0 else TicketType.BUG.value,
                    page_path=f"/page-{idx}",
                    client_context={"browser": "Chrome", "theme": "dark"},
                ),
                actor=requester_user,
            )
            for idx in range(4)
        ]

        # Assert bounded non-N+1 queries on list (4 rows -> 5 queries total)
        with django_assert_num_queries(5):
            list_resp = agent_client.get("/api/support/tickets")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["data"]) == 4

        # Detail endpoint reuses cached SupportSettings for both SLA and can_submit_csat
        detail_resp = agent_client.get(f"/api/support/tickets/{tickets[0].key}")
        assert detail_resp.status_code == 200
        assert detail_resp.json()["data"]["page_path"] == "/page-0"
        assert detail_resp.json()["data"]["client_context"] == {"browser": "Chrome", "theme": "dark"}


def _set_sla_targets(priority, *, response=60, resolution=240):
    priority.response_target_minutes = response
    priority.resolution_target_minutes = resolution
    priority.save(update_fields=["response_target_minutes", "resolution_target_minutes"])


def _move(ticket, status, actor, **kw):
    ticket.refresh_from_db()
    return transition_ticket(
        TransitionTicketInput(ticket_key=ticket.key, to_status_id=status.id, version=ticket.version, **kw),
        actor=actor,
    )


def _resolve_and_reopen(setup, ticket, agent, requester):
    ticket = _move(ticket, setup["status_active"], agent)
    ticket = _move(ticket, setup["status_resolved"], agent, resolution_summary="done", resolution_code="fixed")
    return _move(ticket, setup["status_open"], requester, reason="still happening")


class TestReopenSlaRules:
    @pytest.mark.parametrize("ticket_type", sorted(NON_SLA_TICKET_TYPES))
    def test_reopening_non_sla_ticket_keeps_sla_clocks_off(
        self, support_setup, requester_user, agent_user, ticket_type
    ):
        _set_sla_targets(support_setup["priority_med"])
        ticket = create_ticket(
            CreateTicketInput(subject="Suggestion", description="Please add X.", ticket_type=ticket_type),
            actor=requester_user,
        )
        assert ticket.resolution_due_at is None

        ticket = _resolve_and_reopen(support_setup, ticket, agent_user, requester_user)

        assert ticket.reopen_count == 1
        assert ticket.response_due_at is None
        assert ticket.resolution_due_at is None
        assert ticket.resolution_breached_at is None

    def test_reopening_sla_ticket_restarts_resolution_clock(self, support_setup, requester_user, agent_user):
        _set_sla_targets(support_setup["priority_med"])
        ticket = create_ticket(
            CreateTicketInput(subject="Export fails", description="500 on export.", ticket_type=TicketType.BUG.value),
            actor=requester_user,
        )

        before_reopen = timezone.now()
        ticket = _resolve_and_reopen(support_setup, ticket, agent_user, requester_user)

        assert ticket.reopen_count == 1
        assert ticket.resolution_due_at is not None
        assert ticket.resolution_due_at >= before_reopen + timedelta(minutes=240)


class TestCsatEligibilityParity:
    """The ``can_submit_csat`` flag and the submit-csat command must agree in every case."""

    @pytest.mark.parametrize("case", ["open", "resolved", "expired", "disabled", "not_requester"])
    def test_flag_matches_submit_outcome(self, support_setup, requester_user, agent_user, case):
        ticket = create_ticket(
            CreateTicketInput(subject="Contrast", description="Low contrast.", ticket_type=TicketType.FEEDBACK.value),
            actor=requester_user,
        )
        actor = agent_user if case == "not_requester" else requester_user
        if case != "open":
            ticket = _move(ticket, support_setup["status_active"], agent_user)
            ticket = _move(ticket, support_setup["status_resolved"], agent_user, resolution_summary="ok")
        app_settings = SupportSettings.get_solo()
        if case == "expired":
            SupportTicket.objects.filter(pk=ticket.pk).update(
                resolved_at=timezone.now() - timedelta(days=app_settings.csat_window_days + 1)
            )
        if case == "disabled":
            app_settings.csat_enabled = False
            app_settings.save(update_fields=["csat_enabled"])

        ticket = SupportTicket.objects.select_related("status").get(pk=ticket.pk)
        flag = is_csat_submission_open(actor, ticket, app_settings=SupportSettings.get_solo())

        if flag:
            submit_csat(SubmitCsatInput(ticket_key=ticket.key, score=4), actor=actor)
        else:
            with pytest.raises((CsatNotAllowedError, PermissionDeniedError)):
                submit_csat(SubmitCsatInput(ticket_key=ticket.key, score=4), actor=actor)
        assert flag is (case == "resolved")
