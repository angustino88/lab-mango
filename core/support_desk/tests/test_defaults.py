"""Baseline Support Desk configuration: provisioning, the post-migrate hook and first-ticket flow."""

import pytest
from django.core.management import call_command
from django.test import override_settings

from core.reference_data.registry import get_registered_reference_provisioners
from core.reference_data.signals import provision_after_migrate
from core.support_desk.contracts import SystemState
from core.support_desk.exceptions import TicketCreationDisabledError
from core.support_desk.features.tickets.application import (
    CreateTicketInput,
    TransitionTicketInput,
    create_ticket,
    transition_ticket,
)
from core.support_desk.features.tickets.defaults import (
    DEFAULT_PRIORITIES,
    DEFAULT_STATUSES,
    DEFAULT_TRANSITIONS,
    PROVISIONER_KEY,
    provision_support_desk_defaults,
)
from core.support_desk.models.category import SupportCategory
from core.support_desk.models.priority import SupportPriority
from core.support_desk.models.status import SupportStatus
from core.support_desk.models.transition import SupportStatusTransition


def test_provisioner_is_registered_by_the_app():
    assert PROVISIONER_KEY in dict(get_registered_reference_provisioners())


@pytest.mark.django_db
def test_empty_database_gets_a_complete_workflow():
    provision_support_desk_defaults(using="default")

    assert SupportStatus.objects.count() == len(DEFAULT_STATUSES)
    assert SupportStatusTransition.objects.count() == len(DEFAULT_TRANSITIONS)
    assert SupportPriority.objects.count() == len(DEFAULT_PRIORITIES)
    assert SupportCategory.objects.filter(name="General", is_active=True).exists()

    initial = SupportStatus.objects.get(is_initial=True)
    assert initial.system_state == SystemState.OPEN.value
    assert SupportStatus.objects.get(is_final=True).system_state == SystemState.DONE.value
    assert SupportStatus.objects.get(pauses_sla=True).system_state == SystemState.WAITING.value
    assert SupportPriority.objects.get(is_default=True).code == "medium"
    # Every state of the fixed lifecycle is reachable from the initial status.
    reachable = {initial.pk}
    frontier = [initial.pk]
    while frontier:
        nxt = SupportStatusTransition.objects.filter(from_status_id=frontier.pop()).values_list(
            "to_status_id", flat=True
        )
        for status_id in set(nxt) - reachable:
            reachable.add(status_id)
            frontier.append(status_id)
    assert reachable == set(SupportStatus.objects.values_list("pk", flat=True))


@pytest.mark.django_db
def test_provisioning_is_idempotent_and_keeps_admin_edits():
    provision_support_desk_defaults(using="default")
    SupportStatus.objects.filter(name="Open").update(name="New")
    SupportPriority.objects.filter(code="low").update(is_active=False)

    provision_support_desk_defaults(using="default")

    assert SupportStatus.objects.count() == len(DEFAULT_STATUSES)
    assert not SupportStatus.objects.filter(name="Open").exists()
    assert SupportPriority.objects.count() == len(DEFAULT_PRIORITIES)
    assert not SupportPriority.objects.get(code="low").is_active


@pytest.mark.django_db
def test_groups_already_configured_are_left_alone():
    """The reported case: categories and priorities exist, statuses were never created."""
    SupportCategory.objects.create(name="Hardware")
    SupportPriority.objects.create(name="P1", rank=1, is_default=True)

    provision_support_desk_defaults(using="default")

    assert list(SupportCategory.objects.values_list("name", flat=True)) == ["Hardware"]
    assert list(SupportPriority.objects.values_list("name", flat=True)) == ["P1"]
    assert SupportStatus.objects.filter(is_initial=True, is_active=True).exists()


@pytest.mark.django_db
def test_ticket_can_be_created_and_worked_with_defaults_only(requester_user, agent_user):
    call_command("provision_reference_data")
    ticket = create_ticket(
        CreateTicketInput(
            subject="TICKET 01",
            description="Microscope camera does not start",
            category_id=SupportCategory.objects.get(code="general").pk,
            priority_id=SupportPriority.objects.get(code="high").pk,
            ticket_type="incident",
        ),
        actor=requester_user,
    )
    assert ticket.status.name == "Open"
    assert ticket.response_due_at is not None

    ticket = transition_ticket(
        TransitionTicketInput(
            ticket_key=ticket.key,
            to_status_id=SupportStatus.objects.get(name="In Progress").pk,
            version=ticket.version,
        ),
        actor=agent_user,
    )
    assert ticket.status.system_state == SystemState.ACTIVE.value


@pytest.mark.django_db
def test_missing_status_is_reported_before_anything_else(requester_user):
    category = SupportCategory.objects.create(name="Hardware")
    priority = SupportPriority.objects.create(name="P1", rank=1, is_default=True)

    with pytest.raises(TicketCreationDisabledError, match="No active status"):
        create_ticket(
            CreateTicketInput(subject="s", description="d", category_id=category.pk, priority_id=priority.pk),
            actor=requester_user,
        )


@pytest.mark.django_db
class TestPostMigrateHook:
    def _run(self, **kwargs):
        provision_after_migrate(sender=None, using="default", plan=[], verbosity=0, **kwargs)

    @override_settings(REFERENCE_DATA_AUTO_PROVISION=True)
    def test_runs_registered_provisioning_when_enabled(self):
        self._run()
        assert SupportStatus.objects.filter(is_initial=True).exists()

    @override_settings(REFERENCE_DATA_AUTO_PROVISION=False)
    def test_does_nothing_when_disabled(self):
        self._run()
        assert not SupportStatus.objects.exists()

    @override_settings(REFERENCE_DATA_AUTO_PROVISION=True)
    def test_skips_a_backwards_migration(self):
        provision_after_migrate(sender=None, using="default", plan=[(object(), True)], verbosity=0)
        assert not SupportStatus.objects.exists()
