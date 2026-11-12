# Feature Specification: User Groups & Role-Based Access Control (`core/users/features/groups`)

## 1. Domain Overview & Purpose
Exposes Django authorization groups and their members. Membership comes from URS sync
(`core/users/features/urs_sync`); each URS-linked group carries one Labs role (`core/users/access.py`).

---

## 2. Data Models & Constraints

### 2.1 `django.contrib.auth.models.Group`
- Stores membership only. Each URS group gets its Django group automatically, named after the URS group
  (`core/users/features/urs_sync/mapping.py`); nobody creates or renames it by hand. Group names grant no
  role. The Django group screen in admin is visible to superusers only.

### 2.2 `core.users.models.URSGroup`
- **Purpose:** Links a URS service ID to one Django group and one Labs role.
- **Key Fields:**
  - `group` (OneToOneField `Group`, `on_delete=SET_NULL`, nullable).
  - `urs_group_id` (PositiveBigIntegerField, unique: `users_ursgroup_unique_urs_group_id`).
  - `labs_role`: `admin`, `coord`, `user`, or empty (no role); checked by `users_ursgroup_valid_labs_role`.
    Roles imply lower ones: `admin` > `coord` > `user`.
  - `active`: only active groups are synced by the scheduled task.
  - `last_sync_at`, `last_sync_status` (`applied`, `blocked`, `failed`), `last_sync_message`: written by sync.

---

## 3. Authorization
Both endpoints require the Labs `admin` role (`IsLabAdminReadWrite`): membership reveals who holds which
role (owner decision, 2026-11-11). Superusers hold every role.

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Request Params | Success Contract | Problem Codes |
|---|---|---|---|---|
| `GET /api/user-groups` | `ListGroupUserView` | `PageNumberQuerySerializer` (`page`, `page_size`) | `Paginated[UserGroupSerializer]` (`id`, `name`, `user_count`, `users_url`) | 400, 401, 403 |
| `GET /api/user-groups/{group_id}/users` | `ListUsersInGroupView` | Path `{group_id}`, `page`, `page_size` | `Paginated[UserGroupMemberSerializer]` (`id`, `name`) | 400, 401, 403, 404 |
