# Design: Role-based access for Lab Mango (roles, permissions, naming)

- Tier: T2 (authorization, public API contract, cross-feature). Access-control change: needs owner approval
  before implementation (AGENTS.md rules 5, 6, 9).
- Status: **Proposed (2026-11-20), awaiting owner decisions D1-D5.** Nothing in this note is implemented yet.
- Revisits: [user roles and URS sync](user-roles-and-urs-sync.md), "Alternative role models" (decision
  2026-11-11: keep model A). This note keeps model A's three roles and adds the permission layer that model C
  described, defined in code instead of in the database, so the cost stays small.
- Unblocks: [downtime booking access](downtime-lab-staff-booking-access.md) (the downtime value and its
  name follow D1).

## 1. Problem

Who may do what in Lab Mango is answered by reading code, not one table:

| # | Finding | Evidence |
|---|---|---|
| F1 | Features check **roles**, not actions: `has_labs_role(actor, LabsRole.COORDINATOR)` 7 times, `LabsRole.ADMIN` 4 times, `effective_labs_roles` in the support desk. Changing who may approve bookings means finding every call. | `core/labs/features/bench_bookings/application/decide_booking_approval.py:53`, `update_booking.py:43`, `queries/bench_bookings.py:74,130`, `api/serializers.py:94`, `support_desk/features/tickets/application/policies.py:28` |
| F2 | Real rules are missing from the published access matrix: equipment reference data is read by coordinators but written by administrators only (OD12); license check changes, workbook import and telemetry profile approval are administrator-only. The matrix says coordinators "read and write" these areas. | `equipment/application/reference_data.py:22`, `equipment/queries/reference_data.py:28`, `license_checks/application/manage.py:89`, `workbook_import/application/policies.py:9`, `telemetry/application/profiles.py:94`; matrix in `user-roles-and-urs-sync.md` |
| F3 | Policy logic is copied: the leaderboard re-runs the DRF permission classes to ask "is this a coordinator or admin?" | `leaderboard/api/views.py:173` (`_is_lab_staff`) |
| F4 | Naming is inconsistent. "Staff" (`LABS_STAFF_ACCESS`, `_is_lab_staff`) is not a Lab Mango term and clashes with Django `is_staff` (admin-site access). The `user` role is called "member" in classes (`IsLabMember`). `IsLabCoordinatorOnly` is an alias of `IsLabCoordinatorReadWrite`. `IsLabAdmin` (anyone reads, admin writes) and `IsLabAdminReadWrite` (admin only) differ in a way the names hide. | `core/labs/features/base/access.py:23`, `core/users/access.py:109-140` |
| F5 | Three authorization systems remain: Labs roles, Django model permissions (reference-data writes), and `is_staff` / `is_superuser`. | `core/reference_data/policies.py:17`, `core/users/admin.py` |
| F6 | API keys pass every Labs policy (`HasAPIKeyAccess \| ...`) and are on by default. A key has no user, so ownership, approval and audit rules cannot apply. Open item R4. | `core/labs/features/base/access.py:23-25`, `config/settings/base.py:427` |
| F7 | The frontend gets role codes only (`effective_roles.labs`), so it re-implements "can this user see the Approve button?" from roles. | `core/users/features/profile/serializers.py:53` |

## 2. Target model

Two layers, in the standard RBAC shape (roles are assigned to people, permissions to roles; code checks
permissions only):

```
URS group ──(labs_role, Django admin)──▶ Role ──(ROLE_PERMISSIONS, in code)──▶ Permission ◀── checked by features
```

### 2.1 Roles (unchanged values)

| Stored value | Display name | Who | Implies |
|---|---|---|---|
| `admin` | Lab Administrator | Owns the lab system: user directory, master/reference data, agent configuration, imports | Lab Coordinator |
| `coord` | Lab Coordinator | Runs daily lab operations: resources, downtime, bookings of everyone, approvals, procurement, expenses | Lab Member |
| `user` | Lab Member | Uses the lab: dashboard, leaderboard, own bookings | none |

Stored values do not change (`URSGroup.labs_role`, rule 1). Superusers keep every permission (platform
owner). `is_staff` keeps one meaning only: may open the Django admin site.

### 2.2 The term for "coordinator or administrator" (D1)

Recommended: **Lab operator**: a user whose role carries lab operations authority (Lab Coordinator or Lab
Administrator). It matches how the lab describes the work ("lab operation role") and is not used elsewhere
in the code.

| Option | Code | UI | Note |
|---|---|---|---|
| **Lab operator** (recommended) | `is_lab_operator()`, `LABS_OPERATOR_ACCESS` | "Lab operators" | Distinct from Django `is_staff` and from support-desk "agent" |
| Lab management | `is_lab_management()`, `LABS_MANAGEMENT_ACCESS` | "Lab management" | Already used in emails as a sender/mailbox name, so it reads as a team, not a person |
| Lab manager | `is_lab_manager()` | "Lab managers" | Short, but suggests a single job title and blocks a future `manager` role |

The term appears only in access-policy names and UI text. Business rules check permissions (2.3), so code
rarely needs the term at all. Example, the user's own question:

```python
# Today (leaderboard/api/views.py:173)
def _is_lab_staff(request, view) -> bool:
    return all(permission().has_permission(request, view) for permission in LABS_STAFF_ACCESS)

# Proposed
if not has_permission(request.user, LabsPermission.ASSESSMENT_READ_ANY) and pk != request.user.pk:
    raise AssessmentAccessDenied("You can see your own assessment only.")
```

### 2.3 Permissions (code-defined registry)

`LabsPermission` (`core/users/permissions.py`, exported through `core/users/public.py`): one `StrEnum`,
values `area.action`, reviewed like code. `ROLE_PERMISSIONS` maps each role to the permissions it adds; the
hierarchy adds the lower roles' permissions. This mapping is **the** access matrix: the doc table in section 3
is generated from it and a test fails when they differ.

API helpers (replace `has_labs_role` in features):

| Helper | Use |
|---|---|
| `has_permission(actor, LabsPermission.X) -> bool` | Application rules and object checks |
| `require_permission(actor, LabsPermission.X)` | Raises `Forbidden` with code `permission_denied` and `details.permission` |
| `effective_permissions(actor) -> frozenset[str]` | Cached per request like roles today (one query) |
| `users_with_permission(LabsPermission.X)` | Replaces `users_holding_labs_role` (queryset, one query) |
| DRF `RequiresPermission(read=..., write=...)` | Endpoint policies; `LABS_OPERATOR_ACCESS` etc. become named instances |
| `is_lab_operator(actor)` | Only for UI-facing wording; never for a business rule |

### 2.4 API keys (D4)

A key is a machine client, not a role. Proposed: a key carries an explicit, read-only scope by default
(`ApiKeyScope`: `read`, or `read_write` set per key in Django admin); write endpoints that need a user
(approval, ownership, money) refuse key-only requests; `API_KEY_ACCESS_ENABLED` defaults to `False` in
`config/settings/production.py`. This closes R4.

### 2.5 Frontend

`GET /api/users/me` adds `effective_permissions.labs` (sorted permission codes) next to
`effective_roles.labs` (additive). The UI shows or hides actions by permission; the server stays
authoritative. Role display names come from the existing `{value, label}` choices.

## 3. Access matrix (from `ROLE_PERMISSIONS`)

L = Lab Member, C = Lab Coordinator, A = Lab Administrator. Rows marked **(F2)** are today's rules made
visible; **(new)** rows need D2/D3.

| Permission | Meaning | L | C | A |
|---|---|---|---|---|
| `dashboard.read` | Overview, summary, bench detail with equipment mapping | ✓ | ✓ | ✓ |
| `leaderboard.read` | Leaderboard, bench and user profiles, own assessment | ✓ | ✓ | ✓ |
| `bench_booking.manage_own` | Create, change, cancel own bench bookings | ✓ | ✓ | ✓ |
| `bench_booking.manage_any` | Read and change everyone's bookings | | ✓ | ✓ |
| `bench_booking.approve` | Approve or reject long bookings (never one's own, S2) | | ✓ | ✓ |
| `bench_booking.book_during_downtime` | Book benches under a downtime window opened to lab operators | | ✓ | ✓ |
| `assessment.read_any` | Any user's KPI assessment | | ✓ | ✓ |
| `resource.manage` | Rooms, stations, benches, equipment, licenses, locations | | ✓ | ✓ |
| `downtime.manage` | Schedule, end, cancel downtime; change its booking access | | ✓ | ✓ |
| `monitoring.read` | Monitoring, telemetry readings, resource audit, analytics | | ✓ | ✓ |
| `finance.manage` | Procurement, expenses, finance reports | | ✓ | ✓ |
| `support.handle` | Support desk agent (today: coordinator → agent) | | ✓ | ✓ |
| `reference_data.read` | Equipment reference data **(F2)** | | ✓ | ✓ |
| `reference_data.manage` | Write equipment reference data and catalogs **(F2, OD12)** | | | ✓ |
| `license_check.manage` | Change what agents run **(F2)** | | | ✓ |
| `workbook.import` | Workbook import **(F2)** | | | ✓ |
| `telemetry_profile.approve` | Approve device profiles **(F2)** | | | ✓ |
| `support.administer` | Support desk administration | | | ✓ |
| `directory.read` | User groups and members | | | ✓ |

## 4. Rules

1. Features check permissions, never roles. `has_labs_role`, `effective_labs_roles` and `LabsRole` are not
   imported outside `core.users` (architecture test, like the existing Labs access-policy walk).
2. Every `/api/` route declares one policy built from permissions (extends `tests/architecture/test_labs_access_policy.py`).
3. Deny by default: an unknown permission, no role, an anonymous user, or an inactive user has none.
4. Stored role values, routes, response fields and error codes stay as they are; additions only.
5. Every permission denial on a write is logged with actor, permission and object (no payloads).

## 5. Compatibility and rollout

| Step | Change | Behavior change |
|---|---|---|
| 1 | Add `LabsPermission`, `ROLE_PERMISSIONS`, helpers, `RequiresPermission`; generated matrix doc and its test | None |
| 2 | Replace the 14 role checks and the leaderboard duplicate with permission checks; rename policies (`LABS_STAFF_ACCESS` → `LABS_OPERATOR_ACCESS`, `IsLabMember*` → permission policies); delete `IsLabCoordinatorOnly` alias | None (same grants; tests prove each route) |
| 3 | Reference-data writes use `reference_data.manage` instead of Django model permissions (closes F5 / R10 remainder) | Users who only had a Django model permission lose reference-data writes (confirm D3) |
| 4 | `effective_permissions.labs` on `/api/users/me`; OpenAPI regenerated | Additive |
| 5 | API key scope and production default off (D4) | Key-only writes refused |
| 6 | Downtime: `booking_access` values `closed` / `lab_operators` ("Lab operators only"), checked through `bench_booking.book_during_downtime` | Finishes the pending downtime change |

Steps 1-2 are one reviewable change with no behavior change; 3 and 5 are separate because they remove access.

## 6. Owner decisions needed

| # | Question | Recommendation |
|---|---|---|
| D1 | Term for coordinator or administrator | **Lab operator** |
| D2 | Display names | Lab Administrator, Lab Coordinator, Lab Member |
| D3 | Reference-data writes: Labs permission only, drop Django model permissions | Yes (one authorization system) |
| D4 | API keys: scoped, read-only by default, off in production | Yes (closes R4) |
| D5 | Confirm the administrator-only rows of section 3 as intended | Keep as today |

## 7. Not in scope

Per-room or per-department scoping (model D: each department has its own backend), database-editable
permission bundles (model C's admin UI), and changes to URS group sync.
