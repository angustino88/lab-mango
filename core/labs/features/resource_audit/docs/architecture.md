# Resource Audit Feature Architecture

## Overview
The `resource_audit` feature provides unified lifecycle auditing and compliance verification across all Lab Mango physical and digital resources (Equipment, Benches, Locations, Licenses) using three first-class identifiers:
1. **ID** (`int`): Relational primary key identity.
2. **SKU** (`str`): Unique business asset tag.
3. **UID** (`UUID`): Universally unique immutable system identity.

## Layering
- `core/labs/features/resource_audit/public.py`: Public entry point exposing domain commands, read selectors, and error contracts.
- `core/labs/features/resource_audit/application/`: Write use cases (`record_resource_audit`, `record_audit_by_id`, `record_audit_by_sku`, `record_audit_by_uid`, `update_resource_audit`, `delete_resource_audit`) enforcing authorization, leaf downcasting, and transactional change-log tracking (`ResourceChangeLog`).
- `core/labs/features/resource_audit/queries/`: Read selectors (`list_audits_for_resource`, `list_audits_by_id`, `list_audits_by_sku`, `list_audits_by_uid`, `list_all_resource_audits`, `get_resource_audit`, `get_latest_audit_by_resource`, `get_audit_result_options`).
- `core/labs/features/resource_audit/api/`: HTTP transport layer declaring operation contracts (`OperationContract`), view implementations (`ResourceAuditAPIView`), and serializers.

## Routes
- `GET`, `POST /api/labs/resources/id/{resource_id}/audits`: Resource audit collection by integer ID.
- `GET`, `POST /api/labs/resources/sku/{sku}/audits`: Resource audit collection by business SKU.
- `GET`, `POST /api/labs/resources/uid/{uid}/audits`: Resource audit collection by system UUID.
- `GET`, `POST /api/labs/resources/{resource_type}/{resource_id}/audits`: Resource-scoped audit collection.
- `GET /api/labs/audits`: Global audit query with multi-field filters (`resource_type`, `result`, `auditor_id`, `search`).
- `GET`, `PATCH`, `DELETE /api/labs/audits/{id}`: Single audit resource inspection and lifecycle management.
- `GET /api/labs/audits/options`: Selector standard options endpoint returning `{ "id", "sku", "name" }`.
