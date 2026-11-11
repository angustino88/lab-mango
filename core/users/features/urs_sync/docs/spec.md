# Feature Specification: URS Group Synchronization (`core/users/features/urs_sync`)

## 1. Purpose
Synchronizes membership of Bosch URS (User Rights Service) groups into the linked Django groups, creates
stub accounts for new members, and activates or deactivates URS-managed users. Labs roles follow from the
`URSGroup.labs_role` of each group (`core/users/access.py`); this feature never changes a role mapping.

## 2. Configuration
| Setting | Default | Meaning |
|---|---|---|
| `URS_API_URL` | Bosch URS endpoint | Sync is skipped when blank. |
| `URS_ACCESS_TOKEN` | empty | Sync is skipped when empty (fails closed). |
| `URS_API_VERIFY_SSL` | `False` (see authentication proposal H5) | TLS certificate verification. |
| `URS_API_TIMEOUT_S` | `15` | Timeout per URS call. |
| `URS_SYNC_MAX_REMOVAL_RATIO` | `0.5` | Safety check, see 3.3. |
| `URS_SYNC_BRAKE_MIN_MEMBERS` | `10` | Safety check applies to groups at least this large. |

## 3. Rules

### 3.1 Fetch
- One URS call per selected `URSGroup`. No database transaction or lock is held during network I/O.
- A group with no linked Django group, a request error, a non-200 status, a body that is not JSON, or a body
  without an `Info.UserMembers` list marks the group **failed**. A failed group is never treated as empty
  and its members are left unchanged.
- Members are `domain\account`. The domain is dropped: one account name identifies one person across
  domains (owner, 2026-11-11). Names are lower-cased. A value without a domain separator, longer than 150
  characters, or rejected by Django's username validator is skipped and counted as unusable.

### 3.2 Apply
- All fetched groups are applied in one transaction holding a PostgreSQL transaction advisory lock.
  **Race guard:** concurrent runs (scheduled task and admin action) serialize on that lock. The apply is
  set-based, so running it twice with the same URS data leaves the same state.
- Accounts are matched case-insensitively; the database enforces one account per lower-case username
  (`users_user_username_ci_unique`).
- A matching account with `is_urs_managed=False` is never added; it is counted as skipped.
- An unknown name gets a stub account: `is_urs_managed=True`, active, unusable password, no Entra binding.
- The Django group's members become the matched URS-managed accounts plus any superusers already in it.
  Everyone else is removed.
- Activity: URS-managed users with at least one group are activated; URS-managed non-superusers with no
  group are deactivated. Changes go through the users lifecycle command, which also publishes routing
  updates. Reconciliation runs only when at least one group was applied.

### 3.3 Safety check
A fetched group is **blocked** (nothing changed) when:
- URS returned no members while the group has members, or
- the group has at least `URS_SYNC_BRAKE_MIN_MEMBERS` members and the sync would remove more than
  `URS_SYNC_MAX_REMOVAL_RATIO` of them.

A superuser can apply blocked groups with the admin action "Sync selected URS groups and apply blocked
removals" (`force=True`). A blocked group does not stop other groups from being applied.

### 3.4 Outcome recording
Each run writes `last_sync_at`, `last_sync_status` (`applied`, `blocked`, `failed`) and `last_sync_message`
on every selected group, and logs one summary line (applied, blocked, failed, created, added, removed,
activated, deactivated, skipped, unusable names).

## 4. Entry points
| Entry point | Name | Selects |
|---|---|---|
| Celery task (scheduled in Django admin, Periodic tasks) | `core.users.tasks.scan_urs_group` (deployed name) | all active groups |
| Celery task queued by the admin actions | `users.urs_sync.sync_selected_groups` | selected groups, optional `force` |

## 5. Django admin workflow
- **URS groups** list shows the linked group, Labs role, active flag, member count, and the last sync time,
  status and message, with filters on role, active and last status.
- Adding, changing or deleting URS groups (including `labs_role`) and Django group permissions is limited
  to superusers. Other staff can view.
- On users, `is_staff`, `is_superuser`, `is_urs_managed`, `groups` and `user_permissions` are editable by
  superusers only; `is_active` is read-only (managed by sync) and the effective Labs roles are shown.
- Actions: "Sync selected URS groups" queues a sync; "... and apply blocked removals" queues a forced sync.
  Refresh the list to see the outcome.
