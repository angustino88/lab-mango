# Notification inbox (header bell)

Owner: websocket feature. Additive; existing list/create behaviour is unchanged apart from new fields.

## Model
* `Notification.action_path` — optional in-app path for the primary action (e.g. a prefilled booking form).
  Database check `notification_action_path_internal`: empty, or starts with `/` and not `//`. Not editable in admin.
* `NotificationRead(user, notification, read_at)` — per-user read receipt, unique (user, notification); works for
  targeted and broadcast notifications. CASCADE on both sides (receipts are disposable).

## API (authenticated user)
| Method & path | Behaviour |
|---|---|
| `GET /api/notifications` | Adds `is_read` and `action_path`; new filter `unread=true|false`. Newest first. |
| `GET /api/notifications/unread-count` | `{"data": {"unread_count": n}}`, capped at 100. |
| `POST /api/notifications/{id}/actions/mark-read` | Idempotent; another user's notification → 404. |
| `POST /api/notifications/actions/mark-all-read` | Up to 500 per call; `{"data": {"marked_count": n}}`. |

Race guard: the unique constraint plus `get_or_create` / `bulk_create(ignore_conflicts=True)`.

## Websocket
The connect replay (up to 50 active notifications) now carries `action_path`, `is_read` and `replay: true`, so
clients list replayed items without popping them up again. Live pushes include `action_path`.

## Frontend behaviour (beauty)
Bell with unread badge → panel (All / Unread, mark all read, item click marks read and follows `action_path`).
New live notifications show a toast with the action; desktop (browser) notifications are opt-in from the panel and
shown only while the tab is in the background. The sticky banner is reserved for unread `announcement`
notifications; dismissing one marks it read.
