# Feature Specification: Websockets & Real-Time Notifications (`core/websocket`)

## 1. Domain Overview & Purpose
Provides real-time event distribution, asynchronous channel broadcasting, agent runner telemetry streaming, and hybrid REST polling fallbacks.

---

## 2. Data Models & Constraints

### 2.1 `core.websocket.models.Notification`
- **Fields:**
  - `target_user` (FK `AUTH_USER_MODEL`, null=True for global system broadcasts).
  - `notification_type` (CharField(64)).
  - `title` (CharField(255)).
  - `message` (TextField).
  - `data` (JSONField, default=dict).
  - `is_read` (BooleanField, default=False).
  - `expiry_date` (DateTimeField, indexed).
- **Invariants:**
  - Expired notifications (`expiry_date < now()`) are automatically filtered from active querysets.
  - Unauthenticated clients cannot subscribe to user-directed notification channels.

---

## 3. Websocket Channels & Consumers

All routes require a JWT (`?token=`) validated by `jwt_auth_middleware`; a missing or invalid
token closes with `4001`. Each route is registered exactly once, by its feature's `handler.py`;
`register_route` rejects a second handler for the same pattern, because the router dispatches
to the first match. Object-level failures close with `4003`.

| Route | Handler | Authorization and protocol |
|---|---|---|
| `ws/notifications` | `broadcast_notifications.handler` | Any authenticated user; system-wide announcements. |
| `ws/user` | `user_notifications.handler` | The connecting user's own channel plus broadcasts; replays up to 50 unexpired notifications for that user on connect. |
| `ws/equipment/{bench_id}` | `equipment_status.handler` | Bench must exist and not be deleted; equipment state and assignment changes. |
| `ws/computing/{computing_id}` | `computing_activity.handler` | Equipment must exist and not be deleted; computing activity changes. |
| `ws/monitoring/dashboard` | `monitoring_dashboard.handler` | Any authenticated user; dashboard refresh signals. |
| `ws/monitoring/{bench_id}` | `monitoring_dashboard.handler` | Bench must exist and not be deleted; bench monitoring events. |
| `ws/tasks/{task_id}` | `task_progress.handler` | Only the task's registered owner (deny by default). Streams Celery state/progress and closes with `1000` after `SUCCESS`, `FAILURE` or `REVOKED`. |

### Task progress ownership

A user may watch a task only if it was enqueued for them. Enqueue user-visible tasks with
`core.websocket.task_ownership.enqueue_user_task(task, actor=request.user, args=..., kwargs=...)`
and return `result.id` to the client. The owner is written to the shared cache (Redis in
production) before the task is published, so a client that connects immediately is not
refused, and expires after 24 hours (`TASK_OWNER_TTL_SECONDS`). Tasks enqueued any other way
have no owner and cannot be watched.

---

## 4. REST Hybrid Fallback API

| Method & Path | View Class | Parameters | Purpose & Contract |
|---|---|---|---|
| `GET /api/notifications` | `NotificationListCreateView` | `since=<id>`, `user_id=<id>`, `page`, `page_size` | Reconnection cursor poll. Enforces IDOR guard (`user_id == caller.id`; another id returns an empty page). Unknown or repeated parameters, and `since` / `user_id` that are not non-negative integers, return `400 invalid_query`. |
| `POST /api/notifications` | `NotificationListCreateView` | `NotificationSerializer` | Dispatch notification event into persistence and channel layer; returns `201` with `{"data": <notification>}`. |
