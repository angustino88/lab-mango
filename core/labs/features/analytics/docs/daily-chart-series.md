# Daily Chart Series (bookings, visitors, users, benches)

> Status: Implemented, awaiting owner approval (T2: background jobs, public API contract) · Owner: Labs Engineering (Analytics)

## 1. Problem

The dashboard needs one point per day for four charts: weekly visitors, weekly bookings, total users and
total benches. The endpoints existed (`GET /api/labs/analytics/{lab-visits,booking,user-count,lab-count}?unit=day`)
but returned nothing useful:

- The daily series reads observation tables filled by the `labs.analytics.snapshot_daily_*` tasks, and those
  tasks were not scheduled in code (`CELERY_BEAT_SCHEDULE` held only booking reconciliation). Without a manual
  Periodic Task in Django admin the series stayed empty.
- When they did run, each task recorded the *current* day at run time, so a run shortly after midnight stored
  an almost-empty day.
- `?unit=day` returned every row ever stored (unbounded read), with gaps for missing days.
- `user-count?unit=week|month|...` summed daily population snapshots (about 7x the real value for a week).
- An invalid `unit` was not validated and raised `ValueError` in the selector.

## 2. API (for the frontend)

All four endpoints: `GET /api/labs/analytics/<name>?unit=day[&date_after=YYYY-MM-DD][&date_before=YYYY-MM-DD]`

| Chart | `<name>` | Daily value |
|---|---|---|
| Visitors | `lab-visits` | Distinct visitors that day (visits without a known visitor count as one) |
| Bookings | `booking` | Bookings created that day |
| Total users | `user-count` | Active user accounts at the end of that day |
| Total benches | `lab-count` | Non-deleted benches at the end of that day |

Response: `{"data": [{"date": "2026-11-12", "count": 42}, ...]}`, oldest first, local calendar days
(`TIME_ZONE`).

- **Range** (QRY-5): `date_after` inclusive, `date_before` exclusive. Default: the last 30 days including today.
  Only `date_after`: up to today. Only `date_before`: the 30 days before it. At most 366 days.
- **Today** is counted live; earlier days come from the nightly snapshot. Future days are never returned.
- **Missing days:** bookings and visitors return `0` for a past day with no snapshot, so the x-axis is
  continuous. User and bench totals omit such days, because `0` would wrongly mean "nobody"; draw a gap or
  connect the neighbours.
- **Other units** (`week`, `month`, `quarter`, `year`) keep their previous shape and default (all history);
  `date_after` / `date_before` optionally bound them. Population buckets now take the maximum daily snapshot.
- **Without `unit`** the endpoints keep returning the `{count, trend}` summary card. Sending `date_after` or
  `date_before` without `unit` is rejected.
- **Errors:** an unknown parameter, an invalid `unit` or date, an empty range or one over 366 days returns
  `400` with the standard error body (previously an invalid `unit` failed in the selector, and unknown
  parameters were ignored).
- **Access:** lab coordinators, admins and API keys (`LABS_STAFF_ACCESS`), unchanged. Plain lab members get `403`.

## 3. Design

- **Schedule:** `config/settings/base.py` `CELERY_BEAT_SCHEDULE` gains `analytics-snapshot-daily-{booking-volume,
  facility-visitors,active-users,active-benches}`, `crontab(minute=15, hour=0)` in `CELERY_TIMEZONE`. The
  database scheduler copies them into Periodic Tasks on beat start; an admin can still disable one.
- **Tasks** record the local day that just ended (DST-safe bounds via `local_day_start`). Volume tasks accept an
  ISO `day` for backfill. Population tasks take no `day`: a past population cannot be measured.
- **Shared definitions:** `queries/observations.py` `count_bookings_created`, `count_distinct_visitors`,
  `count_active_users`, `count_active_benches` are used by both the snapshot tasks and the live "today" value,
  so the two never disagree.
- **Bounded read:** a daily request costs one aggregate query over at most 366 days of observations, plus one
  live count when the window includes today (`test_query_count_is_constant_for_the_longest_window`).
  `period_start` is the leading column of each observation's unique constraint, so the range filter can use
  that index; no migration.
- **Write safety:** race guard is the unique constraint on `(period_start, period_end, granularity, source)`;
  `update_or_create` makes reruns and concurrent duplicates overwrite one row. Every task and the backfill are
  safe to run twice.

## 4. Operations

1. Deploy; restart beat so the four entries are created.
2. Remove any hand-made Periodic Task that runs the same `labs.analytics.snapshot_daily_*` tasks (check Django
   admin). A manual entry running late in the evening would now record *yesterday's* populations with
   today's values.
3. Backfill bookings and visitors once:
   `uv run python manage.py backfill_analytics_daily_snapshots --since YYYY-MM-DD [--until YYYY-MM-DD]`
   (default `--until` is yesterday, at most 366 days per run, idempotent). User and bench totals cannot be
   backfilled; their chart starts on the first nightly run, plus today's live value.

## 5. Not changed

- The `{count, trend}` summary for `lab-visits` counts visit *events* in a rolling 7 days, while the daily
  series counts *distinct visitors*. Which one the "weekly visitors" card should show is an open product
  question; the summary was left as is.
- Observations from other sources (`collector`, `import`, `manual`) are still summed with application
  snapshots, as before.
