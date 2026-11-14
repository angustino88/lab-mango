# ADR 007 — API contract gate and strict standard migration

- Status: **Accepted** (repository owner instruction, 2026-11-14: "follow the rules strictly; if a rule is not valid or out of date, update it, but the code must follow; add a CI gate; update all APIs").
- Date: 2026-11-14
- Decision owner: repository owner
- Scope: every HTTP/JSON API under `/api/` and `/agent/` (response standard GEN-1)
- Binding rules: [response standard](../../api/response-standard.md) and [request standard](../../api/request-standard.md). This ADR records why rules changed, how they are enforced, and the migration; the standards hold the rules.
- Related: [ADR 002](002-catalog-and-selector-api.md), [frontend migration guide](../../api/contract-migration-frontend-guide.md)

## 1. Context (verified 2026-11-14)

An audit of the generated schema (`openapi/openapi-full.json`, which the parity check keeps equal to the code)
found 263 violations of mechanically checkable rules. About 210 came from the imported v2 snapshot
(`cbfd46e`); about 50 were added after the standard existed, mostly by reusing older serializers such as
`ResourceOwnerSerializer` (`{id, username, display_name}`). Nothing failed in CI because `.spectral.yaml` checks
the envelope, errors, money and `_at` formats, but not identifiers, relations, enums or naming.

| Rule | Violations at baseline |
| --- | --- |
| REL-3 relation shape | 94 |
| NAM-3 date and date-time naming | 47 |
| NAM-8 bare `_id` in responses | 46 |
| ENU-1 enum as bare string | 37 |
| NAM-2 boolean prefix | 37 |
| REL-1 `id` first | 2 |

## 2. Rule review

Every rule in both standards was reread against the code, ADR 002 and the lint config. The rules stay; none
is weakened. These were unclear, incomplete, or missing, and were changed:

| Change | Problem it fixes |
| --- | --- |
| REL-3: a relation has *exactly* its keys; users' `name` is the display name | "A relation is `{id, name}`" was read as "at least"; 23 user objects had no `name` |
| REL-13 polymorphic relation `{id, name, type}` | `availability.blocked_by`, `downtime.resource` and monitoring subjects had no rule, so they put `type` before `id` |
| REL-14 report dimensions are relations | Analytics rows exposed `room_id`, `bench_id`, `team_id` with no rule covering aggregates |
| REL-15 embedded resources, marked `x-embedded-resource` | Owned children (current loan, placement) and bundles (reference data, mapping graph, dashboard) had no rule, so nothing distinguished them from malformed relations |
| NAM-3 holds both ways; no raw model column names | `expiry_date` was a date-time, `paid_at` a date, `created`/`modified` leaked from models |
| NAM-8 `_id` means a reference by id; external ids use `_key` | `backend_id`, `event_id`, `correlation_id` looked like references |
| NAM-9 one range vocabulary; `period` group | `period_start`, `valid_from`, `starts_on`, `warranty_until` named the same concept four ways (NAM-4) |
| ENU-1 scope stated: every enum incl. arrays and machine APIs; not error codes or REL-13 `type` | Error `code` and discriminators were ambiguous |
| REL-16 reference form chosen per serializer; REL-6 one form per relation | A first version (2026-11-14, morning) banned `_id` in responses outright; the owner rejected it the same day: each serializer decides whether its consumer needs the name (`{id, name}`) or only the id (`<relation>_id`). Over-converted payloads (catalog records, slots, mapping graph, loan slips, equipment reference bundle) went back to the id form |
| GEN-7 protocol surfaces | Routing sync has its own approved wire spec (`routing-sync.md` CHG-5: plain `op`, `mode`, `backend_id`) read by the separate Router; the standard and that spec conflicted. The Agent API is **not** exempt (it is not deployed, and `backend-api.md` already claims ENU-1/REL-1 compliance) |
| GEN-8, DOC-6 the gate | Rules without enforcement drifted within days |
| Request standard link text | Pointed to a non-existent `request-response-golden-examples.md` |

Rules that depend on runtime behavior (status codes, ETag, idempotency, ACT-2 action results) cannot be
checked from the schema; they stay covered by tests, and are not claimed as gated.

## 3. Decision: the gate

- `core/common/openapi/contract_rules.py` checks the generated schema: REL-1, REL-2, REL-3, REL-13, REL-15,
  REL-6, NAM-2, NAM-3, ENU-1 on response shapes; BDY-7, TYP-10 on request bodies. The choice between the two
  reference forms (REL-16) is reviewed with each serializer and not gated. It imports no business app.
- `core/common/openapi/tests/test_contract_rules.py` runs in `.github/workflows/api-lint.yml` (OpenAPI tests step).
  It fails on any violation not in `contract_baseline.json`, and on any baseline entry that no longer occurs,
  so the baseline only shrinks. Target: empty.
- `x-embedded-resource` and `x-protocol-spec` are set with `extend_schema_serializer(extensions=...)`. Each use is
  reviewable in the serializer; an embedded resource still passes every other rule.

## 4. Migration

Breaking for API clients (VER-2). Allowed under VER-1 as part of the approved redesign; the owner instruction
above is the approval. Done feature by feature, each change regenerating OpenAPI, updating tests, shrinking the
baseline, and adding its renames to the [frontend migration guide](../../api/contract-migration-frontend-guide.md).
Deployed-behavior note (AGENTS.md rule 1): the Agent API and routing sync are not deployed
(`docs/agent-platform/backend-api.md` line 6, `routing-sync.md` line 32).

## 5. Consequences

- New serializers cannot reintroduce drift; reviewers see every exemption as a schema extension.
- The React frontend must ship the field renames together with the backend release.
- Lookup display attributes (ticket status color, priority rank) are no longer inlined in relations; clients
  read them from the lookup catalog endpoints (REL-5, ADR 002).

## 6. Status (2026-11-14)

**Money, search and actions.** Three more rules are gated and hold: money is one `{amount, currency}` object
read and written (FMT-2, `core/common/api/money.py`), free-text search is `q` with `search` as a deprecated
alias (QRY-7, `core/common/api/search.py`), and a POST on an item that creates nothing is an `actions/` route
(ACT-1; old ticket paths and the equipment assignment POST are deprecated aliases, `core/common/api/deprecation.py`).
The aliases need a `Sunset` date before they are removed; that date is the owner's decision.

**Runtime check (DOC-4).** `respond_data` rendered nothing: it validated the dict and sent it unchanged, so
the schema could differ from the wire. It now renders through the payload serializer, like `respond`, and every
JSON response produced in the test suite is validated against the committed schema (`conftest.py`). The first
run found 47 mismatching responses on 20 routes, all fixed: relations documented as non-null that can be null
(ticket assignee/team/parent, geo and catalog parents, agent key enums), and the agent extend 422, which has two
bodies (`anyOf`). CI now runs the full suite, with a Redis service, instead of `core/users` and
`tests/architecture` only.

Migration complete for the gated rules: the generated schema has no violations and
`core/common/openapi/contract_baseline.json` is empty. Any new violation now fails CI. Known gaps that the gate
does not check, found during the migration and left for separate changes:

- The leaderboard export contract declares persona rows but can return lab rows.
- Monitoring event writes still accept legacy aliases (kept for deployed agents, AGENTS.md rule 1).
- The dashboard DTOs in `core/labs/features/dashboard/contracts.py` describe the old shape and are unused.
- `ENV-6`: the audit catalog's `meta.sync_started_at` is an ad-hoc meta key.
