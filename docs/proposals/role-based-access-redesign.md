# Design: Role-based access for Lab Mango (roles, permissions, naming)

- Tier: T2 (authorization, public API contract, cross-feature).
- Status: **Decided (2026-11-20) and implemented** on branch `claude/gracious-cray-omxgvw`; needs review and
  human approval before merge.
- Revisits: [user roles and URS sync](user-roles-and-urs-sync.md), "Alternative role models" (2026-11-11: keep
  model A). This design keeps model A's three roles and adds the permission layer of model C, defined in code
  instead of in the database.
- Current matrix: [access matrix](../architecture/access-matrix.md) (generated from code).
- Used by: [lab operator booking access](downtime-lab-operator-booking-access.md).

## 1. Decisions (owner, 2026-11-20)

| # | Decision | Outcome |
|---|---|---|
| D1 | Umbrella term for "Lab Coordinator or Lab Administrator" | **Lab operator**: a person whose role grants `lab_operations.manage`. "Staff" is not used (it means Django `is_staff`, admin-site access). |
| D2 | Role codes and display names | **Lab Administrator** (`admin`), **Lab Coordinator** (`coord`), **Lab Member** (`member`). |
| D3 | Reference-data writes | **Labs permissions only.** The Django model-permission fallback is removed; a reference resource without a write rule is read-only. |
| D4 | API keys | **Read-only by default and off in production** (closes R4, M11). `HasAPIKeyAccess` allows reads only unless `API_KEY_WRITE_ACCESS_ENABLED` (default `False`); `config/settings/production.py` defaults `API_KEY_ACCESS_ENABLED` to `False` and fixes `API_KEY_WRITE_ACCESS_ENABLED = False`. Keys are for API testing only. |
| D5 | Administrator-only rules | **Kept as they are**, now visible in the matrix. |
| - | Remove the old role API | Done: `IsLab*` classes, `LABS_*_ACCESS`, `has_labs_role`, `users_holding_labs_role`, `RolePermission`, `_is_lab_staff` are gone. |

## 2. Problem (before this change)

| # | Finding | Resolution |
|---|---|---|
| F1 | Features checked **roles**, not actions (`has_labs_role(actor, LabsRole.COORDINATOR)` 7 times, `ADMIN` 4 times; the support desk read roles). | Features call `has_permission(actor, LabsPermission.X)`; an architecture test forbids role imports outside `core.users`. |
| F2 | Administrator-only rules (equipment reference data, license checks, workbook import, telemetry profile approval) were missing from the published matrix. | Each is a permission in the registry and a row in the generated matrix. |
| F3 | The leaderboard re-ran DRF permission classes to ask "coordinator or admin?" (`_is_lab_staff`). | `assessment.read_any`. |
| F4 | Inconsistent names: "staff", "member" vs "user", the `IsLabCoordinatorOnly` alias, `IsLabAdmin` vs `IsLabAdminReadWrite`. | One vocabulary: roles (D2), permissions (`area.action`), policies named after the area (`FINANCE_ACCESS`). |
| F5 | Three authorization systems: Labs roles, Django model permissions, `is_staff`. | Django model permissions removed from reference data (D3); `is_staff` only opens Django admin. |
| F6 | API keys pass every Labs policy and are on by default. | D4: read-only by default; off in production. |
| F7 | The frontend received role codes only. | `GET /api/users/me` adds `effective_permissions.labs`. |
| F8 | Agents endpoints let every Labs role (Lab Members included) **read** agents, unlike the rest of the matrix. | **Restricted (owner decision 2026-11-20):** reads and writes need `agent.manage` (lab operators). Lab Members get 403. |

## 3. Model

```
URS group ──(labs_role, Django admin)──▶ Role ──(ROLE_PERMISSIONS, code)──▶ Permission ◀── checked by features and endpoints
```

| Layer | Module | Owns |
|---|---|---|
| Role | `core/users/roles.py` | `LabsRole` (values persisted, labels per D2), `LABS_ROLE_HIERARCHY` (`admin` > `coord` > `member`) |
| Permission | `core/users/permissions.py` | `LabsPermission` (code and description), `ROLE_PERMISSIONS` (what each role adds), `render_access_matrix` |
| Check | `core/users/access.py` | `effective_permissions`, `has_permission`, `require_permission`, `users_with_permission`, `is_lab_operator`, `LabsAccessPolicy` (DRF) |
| Generic mechanics | `core/common/api/permissions.py` | `RoleHierarchy`, `CapabilityPermission` (business-agnostic) |
| Labs endpoint policies | `core/labs/features/base/access.py` | `LAB_OPERATIONS_ACCESS` (default of every Labs base view), `DASHBOARD_ACCESS`, `LEADERBOARD_ACCESS`, `BENCH_BOOKING_ACCESS`, `BENCH_BOOKING_DECISION_ACCESS`, `FINANCE_ACCESS`, `ORGANIZATION_ACCESS`, `WORKBOOK_IMPORT_ACCESS` |
| Other endpoint policies | Owning feature | `AGENT_ACCESS` (`core/agents/api/views.py`), `DIRECTORY_ACCESS` (`core/users/features/groups/list_groups/api.py`) |

Other apps import only `core.users.public`: `LabsPermission`, `LabsAccessPolicy`, `has_permission`,
`require_permission`, `users_with_permission`, `is_lab_operator`, `effective_permissions`. Roles are not exported.

## 4. Permissions (19)

The generated [access matrix](../architecture/access-matrix.md) is authoritative. Lab Member holds 4, Lab
Coordinator adds 9, Lab Administrator adds 6.

Change from the proposal draft: `resource.manage`, `downtime.manage` and `monitoring.read` became one permission,
`lab_operations.manage`, because every Labs operations endpoint inherits one policy from the Labs base views and
the same people hold all three. Splitting it later is mechanical: add the permission, give the feature's base
view its own policy, grant it in `ROLE_PERMISSIONS`. `agent.manage` and `reference_data.import` were added to
name rules the draft had missed (`agent.read` was merged into `agent.manage` when agents were restricted, F8).

## 5. Rules

1. Features check permissions, never roles (`tests/architecture/test_access_control.py`).
2. Every `/api/labs/` route is covered by an area policy (`core/labs/tests/test_access_policy.py`).
3. `ROLE_PERMISSIONS` is the only place that decides who holds what. The matrix document is generated from it
   (`uv run python manage.py access_matrix`) and `core/users/tests/test_permissions.py` fails when they differ.
4. Every permission is granted to some role; a role does not repeat what a lower role grants; codes are
   `area.action`; permission values are API-visible and are never edited in place.
5. Deny by default: anonymous users, API keys (outside `HasAPIKeyAccess` policies), users without a mapped group,
   and a policy side set to `None` grant nothing. Superusers hold every permission.
6. Features that publish a specific error code (`license_check_admin_only`, reference-data and assessment denials)
   keep it: they check `has_permission` and raise their own error. New code may use `require_permission`
   (`permission_denied`).

## 6. Extending

| Change | Steps |
|---|---|
| New endpoint in an existing area | Inherit the area's base view or set its policy. No registry change. |
| Change who may do X | Edit one line in `ROLE_PERMISSIONS`; regenerate the matrix; record the owner decision. |
| New distinct rule | Add a `LabsPermission` (code and description), grant it in `ROLE_PERMISSIONS`, use it (`has_permission` or a `LabsAccessPolicy`), regenerate the matrix. |
| New role | Add a `LabsRole` value (migration of the choices and of the `users_ursgroup_valid_labs_role` constraint), place it in `LABS_ROLE_HIERARCHY`, map it in `ROLE_PERMISSIONS`. |
| Frontend | Read `effective_permissions.labs` (`{value, label}` items, ENU-1) from `/api/users/me` once; gate each action with `can("area.action")` on `value`. Keep the frontend's list of codes in step with the access matrix. |

## 7. Compatibility and verification

- `LabsRole.MEMBER` value is `member` (`admin`, `coord`, `member`), folded into `users.0001_initial`.
  `effective_roles.labs` on `/api/users/me` lists the user's assigned roles (e.g. `["admin"]`), while
  `effective_permissions.labs` lists all permissions granted through `LABS_ROLE_HIERARCHY`.
- Route-level access was compared before and after for every `/api/` route × 5 HTTP methods × 6 actors (none,
  member, coordinator, administrator, superuser, API key): 10,740 decisions, 16 differ, all write methods on the
  two read-only user-group endpoints (no write handler: 405 before, 403 now).
- Application-level checks (booking visibility, approval and editing, reference-data writes, license checks,
  workbook import, telemetry approval, assessments, support roles) map to permissions held by exactly the same
  roles as before; their tests pass unchanged.

## 8. Not in scope

Per-key API key scopes (one switch for all keys is enough while keys are for testing only), per-room or per-department scoping (each department has its own backend),
database-editable permission bundles, URS group sync.
