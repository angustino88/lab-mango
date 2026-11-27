# Notification inbox (header bell) & expiring banners

Owner: websocket feature. Additive; existing list/create behaviour is unchanged apart from new fields.

## Model
* `Notification.display_mode` — `alert` (default, one-time popup alert + bell inbox) or `banner` (time-bounded sticky
  top banner, never a popup toast). Enforced by DB check `notification_display_mode_valid` and indexed with
  `(display_mode, expiry_date)`.
* `Notification.is_dismissible` — boolean (default `True`). Banners with `is_dismissible=False` stay pinned until
  `expiry_date` passes and cannot be dismissed by users.
* `Notification.published_at` — timestamp when first broadcast over WebSocket. Prevents admin edits to one-time alerts
  from re-sending duplicate popups.
* `Notification.action_path` — optional in-app path for the primary action (e.g. a prefilled booking form).
  Database check `notification_action_path_internal`: empty, or starts with `/` and not `//`. Not editable in admin.
* `NotificationRead(user, notification, read_at)` — per-user read/dismiss receipt, unique (user, notification); works
  for targeted and broadcast notifications. CASCADE on both sides (receipts are disposable).
* Django Admin exposes two proxy entries backed by `Notification`:
  * **Expiring Banners** (`BannerNotification`) — requires future `expiry_date`, supports `info`/`warning`/`error`/`success`
    tones and the `Allow users to dismiss` toggle, pushes live `created`/`updated`/`removed` banner events (never toasts),
    and provides an `Expire selected banners now` action.
  * **One-time Alerts** (`AlertNotification`) — broadcasts strictly once on creation via `transaction.on_commit` (edits
    update inbox history without re-sending), and defaults inbox retention (`expiry_date`) to 7 days if left blank.

## API (authenticated user)
| Method & path | Behaviour |
|---|---|
| `GET /api/notifications` | Includes `display_mode`, `is_dismissible`, `is_read`, `action_path`; supports `unread=true\|false` and `display_mode=alert\|banner`. Newest first. |
| `GET /api/notifications/unread-count` | `{"data": {"unread_count": n}}`, capped at 100. Counts unread `alert` items only (banners never inflate the bell badge). |
| `POST /api/notifications/{id}/actions/mark-read` | Idempotent; records read receipt (or banner dismissal). Another user's notification → 404. |
| `POST /api/notifications/actions/mark-all-read` | Up to 500 per call; marks unread `alert` items read without dismissing active banners. `{"data": {"marked_count": n}}`. |

Race guard: the unique constraint plus `get_or_create` / `bulk_create(ignore_conflicts=True)`.

## Websocket
Both `/ws/user/` (primary client route) and `/ws/notifications/` (legacy broadcast route) use the canonical payload
from `serialize_notification_payload`, carrying `event` (`created`/`updated`/`removed`), `display_mode`,
`is_dismissible`, `expiry_date`, `action_path`, `is_read`, and `replay: true` on the connect replay batch (bounded to
50 items) so reconnecting clients hydrate banners/bell without re-popping one-time alerts.

## Frontend behaviour (beauty)
* Connects to `/ws/user/` with ref-stabilized callbacks so route navigation never tears down the socket.
* **Expiring banners** (`display_mode="banner"` or legacy `message_type="announcement"`): rendered exclusively in the
  sticky top `NotificationBanner` (hydrated from REST + updated/removed live over WS), styled by semantic tone
  (`info`/`warning`/`error`/`success`), auto-pruned client-side at `expires_at`, dismissible per user via `mark-read`
  unless `is_dismissible=false`. Also visible in the bell's "All" tab for re-reading, without counting toward the unread
  badge.
* **One-time alerts** (`display_mode="alert"`): bell with unread badge → panel (All / Unread, mark all read, item click
  marks read and follows `action_path`). Live new alerts show a toast **at most once** (guarded by `replay`, `isRead`,
  and a session-scoped shown-ID set); desktop notifications are opt-in and shown only while the tab is in the background.

## What reaches the bell (and therefore toasts / desktop notifications)

| Source | Surface | Action link | Desktop stays until clicked |
|---|---|---|---|
| Slot alerts, followed bookings | One-time alert (toast + bell) | `/booking-calendar?action=create&…` (Book now) | yes |
| Booking start / inactivity reminders | One-time alert (toast + bell) | `/my-bookings` (View booking) | yes |
| Support desk ticket updates | One-time alert (toast + bell) | `/support-tickets/<key>` (View ticket) | no |
| License expiry, license-check attention, license missing | One-time alert (toast + bell) | `/lab-equipment/license` | no |
| Monitoring: expected device disconnected | One-time alert (toast + bell) | `/lab-monitoring` | no |
| Admin One-time Alerts | One-time alert (toast + bell, sent once) | — | no |
| Admin Expiring Banners | Sticky top banner (+ bell "All" history; no toast, no unread badge) | — | — |

Not on the bell (by design): OTP codes (security), storage-quota emails and equipment loan reminders (email only;
candidates for a later change).
