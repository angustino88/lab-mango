"""Integration tests for Resource Audit API endpoints by ID, SKU, and UID."""

import pytest
from rest_framework.test import APIClient

from tests.factories import BenchFactory, LabComputerFactory, UserFactory, grant_labs_role


@pytest.fixture
def auditor_client(db):
    user = UserFactory(username="auditor_bob", email="auditor_bob@example.com")
    client = APIClient()
    grant_labs_role(user, "coord")
    client.force_authenticate(user=user)
    return client, user


@pytest.mark.django_db
class TestResourceAuditAPI:
    def test_audit_by_id_endpoints(self, auditor_client):
        client, user = auditor_client
        bench = BenchFactory(sku="BENCH-API-ID-01", name="API Bench ID 01")

        # 1. Initially empty
        res_empty = client.get(f"/api/labs/resources/id/{bench.id}/audits")
        assert res_empty.status_code == 200
        assert res_empty.json()["data"] == []

        # 2. Record audit by ID
        res_create = client.post(
            f"/api/labs/resources/id/{bench.id}/audits",
            {"result": "PASS", "remarks": "Full inspection by ID."},
            format="json",
        )
        assert res_create.status_code == 201
        data = res_create.json()["data"]
        audit_id = data["id"]
        assert data["result"] == "PASS"
        assert data["remarks"] == "Full inspection by ID."
        assert data["auditor"]["id"] == user.id

        # 3. List shows newly created audit
        res_list = client.get(f"/api/labs/resources/id/{bench.id}/audits")
        assert res_list.status_code == 200
        items = res_list.json()["data"]
        assert len(items) == 1
        assert items[0]["id"] == audit_id

        # 4. Detail endpoint
        res_detail = client.get(f"/api/labs/audits/{audit_id}")
        assert res_detail.status_code == 200
        assert res_detail.json()["data"]["id"] == audit_id

        # 5. Patch detail endpoint
        res_patch = client.patch(
            f"/api/labs/audits/{audit_id}",
            {"remarks": "Updated remark after second check."},
            format="json",
        )
        assert res_patch.status_code == 200
        assert res_patch.json()["data"]["remarks"] == "Updated remark after second check."

        # 6. Delete detail endpoint
        res_del = client.delete(f"/api/labs/audits/{audit_id}")
        assert res_del.status_code == 204

        # 7. Check 404 after delete
        res_404 = client.get(f"/api/labs/audits/{audit_id}")
        assert res_404.status_code == 404

    def test_audit_by_sku_endpoints(self, auditor_client):
        client, user = auditor_client
        comp = LabComputerFactory(sku="COMP-API-SKU-01")

        # Record audit by SKU
        res_create = client.post(
            f"/api/labs/resources/sku/{comp.sku}/audits",
            {"result": "PASS", "remarks": "Hardware diagnostic passed."},
            format="json",
        )
        assert res_create.status_code == 201
        assert res_create.json()["data"]["result"] == "PASS"

        # List audits by SKU
        res_list = client.get(f"/api/labs/resources/sku/{comp.sku}/audits")
        assert res_list.status_code == 200
        items = res_list.json()["data"]
        assert len(items) == 1
        assert items[0]["remarks"] == "Hardware diagnostic passed."

        # Unknown SKU returns 404
        res_unknown = client.get("/api/labs/resources/sku/NON-EXISTENT-SKU/audits")
        assert res_unknown.status_code == 404

    def test_audit_by_uid_endpoints(self, auditor_client):
        client, user = auditor_client
        bench = BenchFactory(sku="BENCH-API-UID-01")

        # Record audit by UID
        res_create = client.post(
            f"/api/labs/resources/uid/{bench.uid}/audits",
            {"result": "FAIL", "remarks": "Safety switch defective."},
            format="json",
        )
        assert res_create.status_code == 201
        assert res_create.json()["data"]["result"] == "FAIL"

        # List audits by UID
        res_list = client.get(f"/api/labs/resources/uid/{bench.uid}/audits")
        assert res_list.status_code == 200
        items = res_list.json()["data"]
        assert len(items) == 1
        assert items[0]["remarks"] == "Safety switch defective."

        # Unknown UID returns 404
        res_unknown = client.get("/api/labs/resources/uid/00000000-0000-0000-0000-000000000000/audits")
        assert res_unknown.status_code == 404

    def test_global_audit_list_and_options(self, auditor_client):
        client, _ = auditor_client
        bench = BenchFactory(sku="BENCH-API-GLOBAL-01")
        client.post(
            f"/api/labs/resources/id/{bench.id}/audits",
            {"result": "FAIL", "remarks": "Ground pin faulty."},
            format="json",
        )

        res_all = client.get("/api/labs/audits")
        assert res_all.status_code == 200
        assert "data" in res_all.json()
        assert len(res_all.json()["data"]) >= 1

        # Filter by result
        res_fail = client.get("/api/labs/audits?result=FAIL")
        assert res_fail.status_code == 200
        assert all(item["result"] == "FAIL" for item in res_fail.json()["data"])
