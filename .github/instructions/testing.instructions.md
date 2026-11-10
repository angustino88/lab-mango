---
applyTo: '**/tests/**,**/test_*.py,**/conftest.py'
---
# Test rules

Test placement is owned by `docs/architecture/feature-template.md` section 6: feature tests live in
`core/<domain>/features/<feature>/tests/` mirroring the source; cross-feature, architecture, and deployment
suites live in top-level `tests/`. Do not add feature tests under top-level `tests/`.

## A test must fail when the behavior breaks
Before handing off, name for each new test the code change that would make it fail. A test that passes with
the production line deleted is not evidence. Bad: asserting a mock was called with the arguments you just passed.

## Required cases (T1/T2), pick those that apply and say which you skipped and why
Happy path · invalid input (`422` / `400`) · permission denied (authorization matrix,
`security.instructions.md`) · boundary values · duplicate or retried request · invalid state transition
(`409`) · dependency failure · concurrent conflict (when state is contested).

## How
- PostgreSQL only (`config.settings.test`); never SQLite. `--reuse-db` is allowed locally.
- Concurrency: `@pytest.mark.django_db(transaction=True)`, two threads released together by a
  `threading.Barrier`, each calling `close_old_connections()` first; assert exactly one succeeds and the other
  raised the feature exception (not a 500). Pattern: `tests/integration/booking_notifications/test_postgres.py`.
  Required for every write path listed in `write-safety.instructions.md` section 2.
- Idempotency: call the command (or task) twice with the same input; assert the row count and the returned
  result are unchanged. For `Idempotency-Key` endpoints also assert replay headers and the different-body `422`.
- Query budget: `query-performance.instructions.md` section 2.
- List and detail endpoints assert query count (`django_assert_num_queries`) (PRF-2).
- API tests assert the error envelope and the `code`, not only the status.
- Time with `freezegun` or a fixture; no `sleep`; no order dependence; factories from the feature's
  `tests/factories.py`; no real personal data.
- External calls are mocked (`respx` for `httpx`); no real network.
- A flaky test is reported, never retried until green or silently skipped.

Report results per AGENTS.md rule 8, including skipped counts.
