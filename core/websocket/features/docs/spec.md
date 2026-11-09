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

| Channel / Topic | Consumer Class | Description & Protocol |
|---|---|---|
| `ws/notifications/broadcast/` | `BroadcastNotificationConsumer` | System-wide announcements and operational banner alerts. |
| `ws/notifications/user/` | `UserNotificationConsumer` | Authenticated user inbox notifications (booking updates, mentions). |
| `ws/equipment/status/` | `EquipmentStatusConsumer` | Real-time broadcast of equipment state and bench assignment changes. |
| `ws/computing/activity/` | `ComputingActivityConsumer` | Monitored compute telemetry streaming (CPU, memory, GPU). |
| `ws/monitoring/dashboard/` | `MonitoringDashboardConsumer` | Live dashboard refresh signals. |
| `ws/monitoring/command/` | `MonitoringCommandConsumer` | Hardware runner command execution and acknowledge signals. |
| `ws/tasks/progress/` | `TaskProgressConsumer` | Long-running asynchronous Celery task status. |

---

## 4. REST Hybrid Fallback API

| Method & Path | View Class | Parameters | Purpose & Contract |
|---|---|---|---|
| `GET /api/notifications` | `NotificationListCreateView` | `since=<id>`, `user_id=<id>` | Reconnection cursor poll. Enforces IDOR guard (`user_id == caller.id`). |
| `POST /api/notifications` | `NotificationListCreateView` | `NotificationSerializer` | Dispatch notification event into persistence and channel layer; returns `201` with `{"data": <notification>}`. |
