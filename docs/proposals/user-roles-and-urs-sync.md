# User Roles and URS Group Sync Proposal

**Status:** In implementation on branch `claude/bold-volta-rjje8r` (2026-11-11); T2, needs review and owner approval before merge
**Risk tier:** T2 — authorization, background job, external integration, migration
**Scope:** `core/users/access.py`, `core/common/api/permissions.py`, `core/users/models/urs_group.py`,
`core/users/features/urs_sync/`, `core/users/tasks.py`, `core/users/admin.py`,
`core/users/features/groups/list_groups/api.py`.
**Basis:** read-only review of the code on branch `claude/bold-volta-rjje8r` (2026-11-11). No code was
changed. No tests or quality gates were run.
**Related:** [User authentication hardening](user-authentication-hardening.md) (H1, H5, M11 there
interact with this document).

## How it works today

1. Each `URSGroup` row links a URS service ID to one Django `Group` and carries a `labs_role`
   (`admin`, `coord`, `user`, or empty), edited in Django admin.
2. `sync_urs_group` calls the URS API per active group, reads `UserMembers` (`domain\username`), creates
   stub users for unknown usernames, sets each Django group's members, then activates users who have a
   group and deactivates URS-managed non-superusers who have none.
3. A user's Labs roles are the `labs_role` values of their groups, expanded by the hierarchy
   `admin > coord > user`. Superusers hold every role. Roles are read from the database once per
   request.
4. `IsLabAdmin`, `IsLabCoordinator`, `IsLabMember` allow reads to any authenticated user and require the
   role for writes.

## What already holds and must be preserved

- [ ] Deny by default: no mapped group means no role and no write (`access.py:13-14`, `permissions.py:68-83`).
- [ ] Roles are resolved from the database per request, so a role or membership change applies on the
  next request with no token to revoke (`access.py:51-68`).
- [ ] Only groups fetched successfully are applied; a failed URS call leaves that group unchanged
  (`service.py:46-56`, `:94-99`).
- [ ] Activity changes go through the lifecycle command with locks and routing publication
  (`service.py:139-147`, `lifecycle/application.py`).
- [ ] Each department backend has its own roles and groups; nothing is shared across backends.

## Findings and proposed changes

Severity: **High** = fix before production; **Medium** = fix before or shortly after; **Low** = cleanup.

### High

#### R1. An empty URS answer removes everyone and deactivates them

- **Evidence:** a `200` response with no `UserMembers` (URS outage, wrong service ID, changed response
  format) is treated as "the group is now empty" (`service.py:58-62`). Every member is removed and, with no
  other group, deactivated (`service.py:139-147`). Members that are not in `domain\user` form are dropped
  silently (`service.py:62`).
- **Proposal:**
  - [ ] Validate the response shape strictly (`Info` and `UserMembers` present and a list); otherwise
    treat the group as failed.
  - [ ] Safety brake: if a group would lose more than a configured share of its members (for example
    30 %) or drop to zero, do not apply it; log, alert, and require an operator to confirm.
  - [ ] Count and report members that could not be parsed.

#### R2. Non-URS accounts can be pulled into groups, and case differences create duplicate users

- **Evidence:** existing members are matched case-insensitively but only among `is_urs_managed=True`
  users (`service.py:64-66`). Every other URS username goes to `get_or_create(username=username)` with
  the lower-cased name (`service.py:106`).
  - A locally managed account (`is_urs_managed=False`) with the same lower-case name is returned by
    `get_or_create` and **added to the group**, so it receives that group's role, against the flag's
    intent.
  - An existing account stored as `ABC1HC` does not match `abc1hc` exactly, so a **second** user
    `abc1hc` is created. Username uniqueness is case-sensitive in the database (`0001_initial.py:37`).
- **Proposal:**
  - [ ] Look up all users case-insensitively once; never add an `is_urs_managed=False` user, and report it.
  - [ ] Add a database unique constraint on `Lower("username")` after cleaning existing duplicates
    (migration; data check first).

#### R3. Who can grant the admin role is not restricted

- **Evidence:** `labs_role` is editable directly in the URS group list (`admin.py:67`), and the user admin
  exposes `is_staff`, `is_superuser`, `groups` and `user_permissions` (`admin.py:25-34`). Any staff user
  with change permission on these models can grant `admin` or superuser. Only `EntraIdentityAdmin` is
  limited to superusers (`admin.py:79-94`).
- **Proposal:**
  - [ ] Allow changes to `labs_role`, `is_staff`, `is_superuser`, `groups` and `user_permissions` only to
    superusers (read-only for everyone else).
  - [ ] Record every role grant or removal as a structured audit event (who, what, before, after).

#### R4. API keys bypass roles on money endpoints

- **Evidence:** procurement and expense views use `HasAPIKey | IsLabCoordinator`, so any API key can write
  purchases and expenses with no user and no creator (`core/labs/features/procurement/docs/architecture.md:49`,
  `core/labs/features/expense/docs/architecture.md:39`). The owner confirmed keys are for API testing only.
- **Proposal:** [ ] covered by M11 in the authentication proposal: turn the key path off in production.
  List procurement and expense explicitly in that change.

### Medium

#### R5. The sync is neither atomic nor protected against running twice

- **Evidence:** the apply phase has no transaction or lock (`service.py:89-147`). The Celery task and the
  admin action (`admin.py:52-58`) can run at the same time. A crash halfway leaves some groups updated and
  others not. AGENTS.md rule 4 requires every write path to name its race guard.
- **Proposal:**
  - [ ] Take a single-runner lock (PostgreSQL advisory lock or `select_for_update` on the `URSGroup` rows)
    for the whole run; a second run exits.
  - [ ] Apply each group's membership in its own transaction; keep activity changes in the lifecycle
    command as today.
  - [ ] Run the admin action as a queued task instead of inside the web request.

#### R6. One bad username aborts the rest of the run

- **Evidence:** the apply phase is outside the per-group `try` (`service.py:86`). A username longer than 150
  characters or with characters the username validator rejects makes `get_or_create` fail, and every
  group after it is skipped.
- **Proposal:** [ ] validate usernames before applying (length, allowed characters); skip and report
  invalid ones instead of failing the run.

#### R7. The domain part of the URS name is discarded

- **Evidence:** `apac\abc1hc` becomes `abc1hc` (`service.py:62`). The same account name in two domains
  collapses into one local user. This also feeds first-login binding by username (authentication H1).
- **Proposal:**
  - [ ] Keep only an allow-list of domains (setting) and reject others; or store the domain with the user.
  - [ ] Decide with the owner whether account names are unique across domains (not verified).

#### R8. Every authenticated user can list all groups and their members

- **Evidence:** `ListGroupUserView` and `ListUsersInGroupView` return every Django group and member to any
  authenticated user or API key (`list_groups/api.py:42-53`, `:61-73`). Anyone can see who holds the admin
  role. AGENTS.md rule 5 requires object-scoped authorization.
- **Proposal:** [ ] restrict to coordinators and admins, or limit each user to the groups they belong to.

#### R9. Reads are open to every authenticated user, including users with no role

- **Evidence:** `RolePermission` allows safe methods when `read_roles` is `None` (`permissions.py:80-82`),
  and no Labs permission class sets it (`access.py:89-104`). A user in a URS group whose `labs_role` is
  empty stays active (has a group) and can read all Labs data, including procurement and expenses. The
  procurement and expense docs already list this as an open decision.
- **Proposal:**
  - [ ] Decide per area whether reads need at least `user`; set `read_roles` on `IsLabMember` and on the
    money areas (`IsLabCoordinator` reads for procurement and expenses).
  - [ ] Optionally deactivate users whose groups carry no Labs role at all.

#### R10. Superusers and `is_staff` sit outside URS

- **Evidence:** superusers keep group membership and are never deactivated by sync
  (`service.py:78-80`, `:142-147`), and hold every role (`access.py:58-59`). `is_staff` controls the admin
  site and user-directory visibility (`profile/queries/list_users.py:19`) but is set by hand. There are
  three authorization systems: Labs roles, `is_staff`, and Django permissions (`reference_data/policies.py:13`).
- **Proposal:**
  - [ ] Document which system governs which area, in `core/users` docs.
  - [ ] Periodic review report of superusers and staff (no automatic change).

#### R11. No database constraint on role values or on duplicate URS groups

- **Evidence:** `labs_role` uses choices only (`urs_group.py:17-24`); `urs_group_id` is not unique
  (`urs_group.py:15`), so two rows can sync the same URS service into two Django groups with different roles.
  AGENTS.md rule 4 asks for database-enforced invariants.
- **Proposal:**
  - [ ] Check constraint `labs_role IN ('', 'admin', 'coord', 'user')`.
  - [ ] Unique constraint on `urs_group_id` (after checking existing data).

### Low

- [ ] **L1. TLS default differs in code and settings.** The service falls back to `True`
  (`service.py:25`) but settings default to `False` (`base.py:254`); fix with authentication H5.
- [ ] **L2. Spec drift.** The spec names the task `sync_urs_groups_task` (`urs_sync/docs/spec.md:25`); the
  code is `scan_urs_group` (`tasks.py:8`). The spec omits the "only successful groups apply" rule and the
  superuser retention rule details. Keep the deployed task name (AGENTS.md rule 1) and fix the spec.
- [ ] **L3. Run time.** Calls are sequential with a 30 s timeout each (`service.py:48`) under a 4-minute
  soft limit (`base.py:298`); about eight slow groups exceed it. Fetch with a shorter timeout or in
  parallel, and set an explicit limit on the task.
- [ ] **L4. Extra queries.** One superuser query per group (`service.py:79`) and per affected user
  (`service.py:143`); load once.
- [ ] **L5. Admin error message.** The admin action shows raw exception text (`admin.py:58`); log it and show
  a generic message.
- [ ] **L6. No sync report.** Record per run: groups fetched or failed, members added or removed, users
  created, activated, deactivated, skipped. Needed for R1 alerts.

## Suggested order

1. R1 and R6 — stop one bad URS answer from locking people out.
2. R3 and R4 — close the role-escalation paths.
3. R2, R11 — data clean-up, then constraints (migrations).
4. R5, R7 — lock, transactions, domain rule.
5. R8, R9, R10 — authorization scope decisions with the owner.
6. Low items, then rewrite `urs_sync/docs/spec.md` once.

## Process for each item

- [ ] T2 workflow per `AGENTS.md`: design note, security and QA review, independent review, owner approval.
- [ ] Tests for each acceptance criterion; quality gates from `docs/ai-team/quality-gates.md`.
- [ ] When an item is approved and implemented, fold its rule into the owning spec and remove it here.

## Owner decisions (2026-11-11)

| Question | Answer | Effect |
| --- | --- | --- |
| Safety brake (R1) | Sync everything, immediately (2026-11-12) | Brake off by default (`URS_SYNC_SAFETY_BRAKE`); failed or malformed URS answers still change nothing; saving a URS group syncs it at once |
| Same account name in two domains (R7) | One account name is the same person | Keep dropping the domain; documented in the sync spec |
| Reads without a Labs role; plain users reading procurement and expenses (R9) | No | Labs permission classes require a role to read; procurement, expenses and finance reports require coordinator |
| Who may list groups and members (R8) | Admin | Group endpoints require the Labs `admin` role |
| Where roles are configured | Django admin | Admin workflow improved (R3, L6) |
| Labs roles vs Django groups (R10) | Option 1: URS group is the only configuration; Django group only stores membership | Automatic Django group per URS group; support desk on Labs roles |

## Implementation status

| Item | Status | Where |
| --- | --- | --- |
| R1 safety brake, strict response check | Done | `urs_sync/sync_group/service.py`, settings `URS_SYNC_*` |
| R2 case-insensitive matching, unmanaged accounts skipped, DB constraint | Done | service; `User` constraint `users_user_username_ci_unique` (migration 0005) |
| R3 role-granting fields superuser-only | Done | `core/users/admin.py` (users, URS groups, Django groups) |
| R4 API keys on money endpoints | Not in this change | Authentication proposal M11 |
| R5 single apply transaction with advisory lock; admin action queued | Done | service; `core/users/tasks.py` (`users.urs_sync.sync_selected_groups`) |
| R6 invalid usernames skipped | Done | service |
| R7 domain | Decided: keep dropping | sync spec |
| R8 group list admin-only | Done | `groups/list_groups/api.py`, OpenAPI regenerated |
| R9 reads need a role | **Done (2026-11-11):** Labs-wide policy in `core/labs/features/base/access.py`; default coordinator and admin for every Labs endpoint; plain users read only the dashboard (including bench detail and its equipment mapping) and the leaderboard, and manage their own bench bookings; no role means no access. `core/labs/tests/test_access_policy.py` walks every `/api/labs/` route | `core/labs/features/base/`, Labs views, `core/common/api/reference_views.py` |
| R10 one role system | **Done (option 1, 2026-11-11):** URS group is the only place roles are configured; its Django group is created and named automatically and only stores membership; support desk uses Labs roles only (admin -> support admin, coord -> support agent), group names grant nothing. Remaining: reference-data writes still use Django permissions (`core/reference_data/policies.py:13`) | `urs_sync/mapping.py`, `core/users/admin.py`, `support_desk/.../policies.py`, `notifications.py` |
| R11 role check and unique URS id constraints | Done | `URSGroup` constraints (migration 0005) |
| L1 code uses settings value | Done (default still `False`, see authentication H5) | service |
| L2 spec | Done | `urs_sync/docs/spec.md`, `groups/docs/spec.md` |
| L3 timeout setting | Done (`URS_API_TIMEOUT_S=15`); calls still sequential | settings |
| L4 extra queries | Done | service |
| L5 admin error text | Done | admin |
| L6 sync report and last status per group | Done | `URSGroup.last_sync_*`, admin list |

Migration 0005 stops with a clear message before adding constraints when existing data has case-variant
usernames, duplicate URS ids or unknown roles. Check production-like data before deploying.

## Labs access matrix (owner decision 2026-11-11)

| Area | No role | Plain user (`user`) | Coordinator (`coord`) | Admin (`admin`) |
|---|---|---|---|---|
| Dashboard: overview, summary, bench detail with equipment mapping | none | read | read | read |
| Leaderboard (including bench and user profiles and usage) | none | read | read | read |
| Bench bookings (own), lab projects for booking | none | own bookings | all, approve | all, approve |
| Benches, equipment, licenses, rooms and locations, monitoring, resource audit and mappings, analytics, procurement, expenses | none | none | read and write | read and write |
| User groups and members | none | none | none | read |

## Alternative role models (for discussion)

| Model | Roles | Fits when | Cost |
|---|---|---|---|
| **A. Current hierarchy** (recommended now) | `admin` > `coord` > `user` | One team runs equipment and money together | None |
| **B. Functional roles added to the hierarchy** | Keep the three, add independent roles: `finance` (procurement, expenses, finance reports), `auditor` (read everything including finance and audit, write nothing), optionally `approver` (decide bookings only) and `viewer` (dashboard and leaderboard only, no bookings) | Money must be separated from equipment management, or reviewers need read-only access (separation of duties) | New role values (migration of the role check), permission classes for procurement, expenses and finance, URS groups mapped per role |
| **C. Permission bundles (NIST RBAC core)** | Roles are named sets of permissions (`booking.approve`, `bench.write`, `finance.read`, ...) edited in Django admin and assigned to URS groups | Roles change often, or each department wants different bundles | Large: permission registry, admin UI, every view checks a permission |
| D. Scoped roles (ABAC) | Roles per room or lab | One backend serves several teams | Not needed: each department has its own backend |

**Decision (2026-11-11): keep model A.** `core/users/access.py` now states what the code does: coordinators manage procurement, expenses and finance reports; admins add the user directory.

## Open questions for the owner

None. Standards items S2 (no self-approval), S5 (access review) and S6 (role audit log) are done
(2026-11-12); see `core/users/features/urs_sync/docs/spec.md` section 6.
