# Feature Specification: User Profiles & Self-Service (`core/users/features/profile`)

## 1. Domain Overview & Purpose
The User Profile feature governs identity self-service, user discoverability, role-scoped profile visibility, and binary avatar management.

---

## 2. Data Models & Constraints

### 2.1 `core.users.models.User`
- **Key Fields in Scope:**
  - `username`: Read-only identifier.
  - `email`: Corporate directory email.
  - `display_name`: User-facing alias (max 255 chars).
  - `name`: Full legal/display name.
  - `department`: Corporate organization code.
  - `avatar`: Managed file attachment stored under user avatar upload directory.

### 2.2 Security Boundary: `ActorContext`
- Pure domain data transfer object encapsulating `user_id` and role permissions.
- Invariants:
  - Users may only mutate their own profile attributes (`display_name`, `name`, `department`).
  - System administrators or API clients may view/edit extended attributes.
  - Inactive/soft-deleted users are excluded from standard user visibility listings unless explicitly queried by staff.

---

## 3. Application Commands & Domain Logic

### 3.1 Commands (`core/users/features/profile/application/`)
- **`update_user(actor: ActorContext, target_user_id: int, data: UpdateUserInput)`**:
  - Enforces `actor.user_id == target_user_id` unless actor has administrative scope.
  - Atomically applies changes and writes an audit event.
- **`upload_avatar(actor: ActorContext, image_file)`**:
  - Validates image dimensions, MIME type (JPEG/PNG/WEBP), and file size (< 2MB).
  - Stores binary image and updates `user.avatar`.
- **`delete_avatar(actor: ActorContext)`**:
  - Unlinks avatar file from storage and clears reference on user model.

---

## 4. API Endpoints & Transport Contracts

| Method & Path | View Class | Request Payload / Params | Success Contract (200/204) | Problem Codes |
|---|---|---|---|---|
| `GET /api/users/me` | `GetMeView` | None (reads auth session) | `UserWithPermissionSerializer`: profile, `groups` (`id`, editable `name`), `effective_roles.labs` (stable role codes) | 401 (`unauthorized`) |
| `GET /api/profile/users` | `ListUsersView` | `UsersListQuerySerializer` (`username`, pagination) | `Paginated[UserSerializer]` | 400, 401 |
| `GET /api/profile/users/{id}` | `RetrieveUserView` | Path `{id}` | `UserSerializer` | 401, 404 (`user_not_found`) |
| `PATCH /api/profile/users/{id}` | `RetrieveUserView` | `_UpdateUserSerializer` (`display_name`, `name`, `department`) | `UserSerializer` | 400, 401, 403 (`forbidden`), 404 |
| `GET /api/profile/avatar` | `UserAvatarView` | None (reads auth session) | `UserAvatarReadSerializer` (`avatar_url`) | 401, 404 (`no_avatar`) |
| `POST /api/profile/avatar` | `UserAvatarView` | Multipart Form (`avatar`) | `UserAvatarReadSerializer` (`avatar_url`) | 400, 401, 422 (`invalid_image`) |
| `DELETE /api/profile/avatar` | `UserAvatarView` | None | 204 No Content | 401, 404 (`no_avatar`) |

`effective_roles.labs` lists effective Labs roles in `admin`, `coord`, `user` order (including implied roles). It is empty when no Labs role is mapped. Clients use these codes for UI hints instead of relying on mutable Django group names; server-side authorization remains authoritative.
