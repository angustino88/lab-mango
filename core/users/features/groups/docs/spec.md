# Feature Specification: User Groups & Role-Based Access Control (`core/users/features/groups`)

## 1. Domain Overview & Purpose
The User Groups feature bridges Django's standard authorization group model with enterprise URS (User Rights Service) roles, providing hierarchical permission sets (`admin`, `coordinator`, `engineer`, `viewer`, `guest`).

---

## 2. Data Models & Constraints

### 2.1 `django.contrib.auth.models.Group`
- Standard group entity storing `name` (unique) and permissions.

### 2.2 `core.users.models.URSGroup`
- **Purpose:** Associates an external enterprise URS directory identifier with an internal Lab Mango group and role tier.
- **Key Fields:**
  - `group` (OneToOneField `Group`, on_delete=CASCADE, related_name="urs_metadata").
  - `urs_group_id` (IntegerField, unique, indexed).
  - `labs_role`: CharField enum with choices:
    - `admin`: Full system, user, and financial configuration rights.
    - `coordinator`: Equipment lifecycle management, booking approvals, status changes.
    - `engineer`: Bench booking, equipment usage, support ticket reporting.
    - `viewer`: Read-only operational inspection.
    - `guest`: Restricted visitor profile.

---

## 3. API Endpoints & Transport Contracts

| Method & Path | View Class | Request Params | Success Contract | Problem Codes |
|---|---|---|---|---|
| `GET /api/user-groups` | `ListGroupUserView` | `PageNumberQuerySerializer` (`page`, `page_size`) | `Paginated[UserGroupSerializer]` (`id`, `name`, `user_count`) | 400, 401 |
| `GET /api/user-groups/{group_id}/users` | `ListUsersInGroupView` | Path `{group_id}`, `page`, `page_size` | `Paginated[UserGroupMemberSerializer]` (`id`, `name`) | 400, 401, 404 |
