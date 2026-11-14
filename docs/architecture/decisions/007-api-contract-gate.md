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
| NAM-8 `_id` suffix reserved for inputs and filters; external ids use `_key` | `backend_id`, `event_id`, `correlation_id` looked like relation inputs |
| NAM-9 one range vocabulary; `period` group | `period_start`, `valid_from`, `starts_on`, `warranty_until` named the same concept four ways (NAM-4) |
| ENU-1 scope stated: every enum incl. arrays and machine APIs; not error codes or REL-13 `type` | Error `code` and discriminators were ambiguous |
| RW-2: no bare `<relation>_id` in read shapes | REL-6 forbade mixing but did not say a response never carries the bare id |
| GEN-7 protocol surfaces | Routing sync has its own approved wire spec (`routing-sync.md` CHG-5: plain `op`, `mode`, `backend_id`) read by the separate Router; the standard and that spec conflicted. The Agent API is **not** exempt (it is not deployed, and `backend-api.md` already claims ENU-1/REL-1 compliance) |
| GEN-8, DOC-6 the gate | Rules without enforcement drifted within days |
| Request standard link text | Pointed to a non-existent `request-response-golden-examples.md` |

Rules that depend on runtime behavior (status codes, ETag, idempotency, ACT-2 action results) cannot be
checked from the schema; they stay covered by tests, and are not claimed as gated.

## 3. Decision: the gate

- `core/common/openapi/contract_rules.py` checks the generated schema: REL-1, REL-2, REL-3, REL-13, REL-15,
  NAM-2, NAM-3, NAM-8, ENU-1, RW-2 on response shapes; BDY-7, TYP-10 on request bodies. It imports no business app.
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
