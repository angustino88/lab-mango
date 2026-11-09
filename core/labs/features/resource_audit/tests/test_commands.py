"""Unit tests for resource audit application commands and selectors by ID, SKU, and UID."""

import pytest

from core.labs.features.resource_audit.exceptions import (
    AuditPermissionDeniedError,
    InvalidAuditResultError,
    ResourceAuditNotFoundError,
    ResourceNotFoundError,
)
from core.labs.features.resource_audit.public import (
    RecordAuditByIdInput,
    RecordAuditBySkuInput,
    RecordAuditByUidInput,
    UpdateResourceAuditInput,
    delete_resource_audit,
    get_audit_result_options,
    get_latest_audit_by_resource,
    get_resource_audit,
    list_all_resource_audits,
    list_audits_by_id,
    list_audits_by_sku,
    list_audits_by_uid,
    list_audits_for_resource,
    record_audit_by_id,
    record_audit_by_sku,
    record_audit_by_uid,
    update_resource_audit,
)
from core.labs.models.auditing.resource_change_log import ResourceChangeLog
from tests.factories import BenchFactory, LabComputerFactory, UserFactory


@pytest.fixture
def auditor_user(db):
    return UserFactory(username="auditor_jane", email="auditor_jane@example.com")


@pytest.mark.django_db
class TestResourceAuditCommands:
    def test_record_resource_audit_by_id(self, auditor_user):
        bench = BenchFactory(sku="BENCH-AUD-01", name="Audited Bench 01")

        cmd = RecordAuditByIdInput(
            resource_id=bench.id,
            resource_type="bench",
            result="PASS",
            remarks="Audited via ID.",
        )
        audit = record_audit_by_id(cmd, actor=auditor_user)

        assert audit.id is not None
        assert audit.result == "PASS"
        assert audit.remarks == "Audited via ID."
        assert audit.auditor == auditor_user
        assert audit.resource.pk == bench.pk

        # Verify change log was created
        log = ResourceChangeLog.objects.filter(resource_object_id=str(bench.id)).first()
        assert log is not None
        assert log.action == ResourceChangeLog.Action.CREATE

    def test_record_resource_audit_by_sku(self, auditor_user):
        comp = LabComputerFactory(sku="COMP-AUD-SKU-01")

        cmd = RecordAuditBySkuInput(
            sku="COMP-AUD-SKU-01",
            result="OK",  # normalizes to PASS
            remarks="Audited via SKU",
        )
        audit = record_audit_by_sku(cmd, actor=auditor_user)

        assert audit.id is not None
        assert audit.result == "PASS"
        assert audit.resource.pk == comp.pk

        # Query by SKU
        audits = list_audits_by_sku("COMP-AUD-SKU-01")
        assert audits.count() == 1
        assert audits.first().id == audit.id

    def test_record_resource_audit_by_uid(self, auditor_user):
        bench = BenchFactory(sku="BENCH-AUD-UID-01")

        cmd = RecordAuditByUidInput(
            uid=bench.uid,
            result="FAIL",
            remarks="Audited via UID",
        )
        audit = record_audit_by_uid(cmd, actor=auditor_user)

        assert audit.id is not None
        assert audit.result == "FAIL"
        assert audit.resource.pk == bench.pk

        # Query by UID
        audits = list_audits_by_uid(bench.uid)
        assert audits.count() == 1
        assert audits.first().id == audit.id

    def test_record_resource_audit_invalid_result_raises(self, auditor_user):
        bench = BenchFactory(sku="BENCH-AUD-02")
        cmd = RecordAuditByIdInput(
            resource_id=bench.id,
            result="INVALID_RESULT",
        )
        with pytest.raises(InvalidAuditResultError):
            record_audit_by_id(cmd, actor=auditor_user)

    def test_record_resource_audit_unauthenticated_raises(self):
        bench = BenchFactory(sku="BENCH-AUD-03")
        cmd = RecordAuditByIdInput(
            resource_id=bench.id,
            result="PASS",
        )
        with pytest.raises(AuditPermissionDeniedError):
            record_audit_by_id(cmd, actor=None)

    def test_record_resource_audit_nonexistent_resource_raises(self, auditor_user):
        cmd = RecordAuditByIdInput(
            resource_id=999999,
            resource_type="bench",
            result="PASS",
        )
        with pytest.raises(ResourceNotFoundError):
            record_audit_by_id(cmd, actor=auditor_user)

        cmd_sku = RecordAuditBySkuInput(
            sku="NONEXISTENT-SKU-999",
            result="PASS",
        )
        with pytest.raises(ResourceNotFoundError):
            record_audit_by_sku(cmd_sku, actor=auditor_user)

        cmd_uid = RecordAuditByUidInput(
            uid="00000000-0000-0000-0000-000000000000",
            result="PASS",
        )
        with pytest.raises(ResourceNotFoundError):
            record_audit_by_uid(cmd_uid, actor=auditor_user)

    def test_update_and_delete_resource_audit(self, auditor_user):
        bench = BenchFactory(sku="BENCH-AUD-04")
        audit = record_audit_by_id(
            RecordAuditByIdInput(resource_id=bench.id, resource_type="bench", result="FAIL", remarks="Needs fix"),
            actor=auditor_user,
        )

        updated = update_resource_audit(
            UpdateResourceAuditInput(audit_id=audit.id, result="PASS", remarks="Fixed and re-tested"),
            actor=auditor_user,
        )
        assert updated.result == "PASS"
        assert updated.remarks == "Fixed and re-tested"

        # Delete
        delete_resource_audit(audit.id, actor=auditor_user)
        assert get_resource_audit(audit.id) is None

        # Delete missing audit raises
        with pytest.raises(ResourceAuditNotFoundError):
            delete_resource_audit(999999, actor=auditor_user)


@pytest.mark.django_db
class TestResourceAuditSelectors:
    def test_list_and_options_selectors(self, auditor_user):
        bench = BenchFactory(sku="BENCH-AUD-05")
        record_audit_by_id(
            RecordAuditByIdInput(resource_id=bench.id, resource_type="bench", result="PASS", remarks="Pass 1"),
            actor=auditor_user,
        )
        record_audit_by_id(
            RecordAuditByIdInput(resource_id=bench.id, resource_type="bench", result="FAIL", remarks="Fail 1"),
            actor=auditor_user,
        )

        # By ID
        audits_id = list_audits_by_id(bench.id)
        assert audits_id.count() == 2

        # By SKU
        audits_sku = list_audits_by_sku(bench.sku)
        assert audits_sku.count() == 2

        # By UID
        audits_uid = list_audits_by_uid(bench.uid)
        assert audits_uid.count() == 2

        # Filtered by result
        filtered_pass = list_audits_for_resource(bench.id, result="PASS")
        assert filtered_pass.count() == 1

        # Latest
        latest = get_latest_audit_by_resource(bench.id)
        assert latest is not None

        # Global list
        all_audits = list_all_resource_audits(resource_type="bench")
        assert all_audits.count() >= 2

        # Options
        options = get_audit_result_options()
        assert len(options) == 3
        for opt in options:
            assert set(opt.keys()) == {"id", "sku", "name"}
            assert opt["sku"] in ("PASS", "FAIL", "NOT_ASSESSED")
