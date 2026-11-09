# Documentation Index

## Architecture and conventions

- [Feature template specification](feature-template.md) — **canonical target standard** for feature structure, write/read/transport boundaries, public contracts, wiring, test ownership and adoption gates. All other docs follow it.
- [Super-app core architecture](core-architecture-redesign.md) — app/kernel/infrastructure ownership, composition, production requirements and rebuild phases; feature boundaries defer to the template.
- [Core architecture review and improvement backlog](core-architecture-redesign.md#14-core-architecture-review-and-improvement-backlog-2026-10-26) — sampled, read-only findings and proposed remediation/roadmap; not production certification.
- [Naming and text conventions](conventions.md) — coding, route, schema, registry, and documentation rules for new work.
- [Django model conventions](django-model-conventions.md) — project-wide model structure, naming, relationships, validation, migrations, and review rules.

Precedence: feature template for feature architecture; core design for app/composition
and rollout; model/API guides for specialist rules; feature references for behavior
and compatibility. Historical examples are not instructions for new work. A target
standard does not imply that current code, scaffolding or enforcement already conforms.

## API contracts and schema

- [API response contracts](api-response-contracts.md) — runtime response envelopes and operation-contract usage.
- [Labs API response audit](labs-api-response-audit.md) — compliance audit of Labs features against the REST API Response Standard.

## Agent platform: start here

Use these three working documents; do not implement from the older backend drafts.
"Current design" means the selected working proposal, **not** implemented or deployment-approved behavior.

| Read order | Document | Owns | Status |
| --- | --- | --- | --- |
| 1 | [Agent production design](agent-design-spec.md) | Device service/UI/updater, bootstrap, local reliability, gate behavior, delivery gates | Current agent design proposal; external implementation not verified |
| 2 | [Backend agent API proposal](backend-agent-api-spec.md) | Enrollment, authentication, telemetry and booking API proposals | Working backend proposal; routing sections superseded by the next document |
| 3 | [Backend routing and sync](backend-routing-sync-spec.md) | Users/agents claims, publisher, internal sync, recovery and Edge consumption | Current routing design; R0 schema only, R1/R2 approval pending |

Supporting references, not additional competing specifications:

- [ADR 004](architecture/decisions/004-agent-routing-sync.md) records identity constraints, the Agent booking capability boundary and approval limits; detailed mTLS, API and device behavior lives in the two working specs above.
- [Labs model architecture](../core/labs/models/docs/labs-model-architecture.md) owns persistence documentation; source models/migrations determine actual schema.
- [Generated OpenAPI](../openapi/openapi.yml) and mounted URLconfs determine existing API contracts. Proposed paths in prose are not callable endpoints.
- Gateway/Edge runtime and wire contracts must be reviewed in their own repositories; they are not verified by this workspace.

**Historical drafts:** [backend 1.0](archive/agent-platform/agent-platform-backend-spec.v1.md) and [backend 2.0](archive/agent-platform/agent-platform-backend-spec.v2.md)
are retained only for traceability. Their standalone/implementation claims, equipment routing and public-key
sync examples are superseded. Do not add more version-suffixed copies: update the working documents in place,
record accepted decisions in ADRs, and keep implementation history in version control. Current specs use
unversioned, responsibility-based filenames; older drafts live under `archive/agent-platform/` and are not working specifications.

Ownership: device behavior belongs in the agent design; server behavior in the backend proposal;
routing behavior only in the routing spec. Summaries link to owners rather than redefining their contracts.

## Feature-specific references

- [Bench and station APIs](../core/labs/features/benches/docs/bench-station-apis.md) — current routes, fields, placement, favorites, capacity, errors, lock protocol, and fresh-schema rollout limitations.
- [Equipment category APIs](../core/labs/features/equipment/docs/equipment-category-apis.md) — current category contracts and transitional API-base behavior, with target layer guidance.
- [Booking model conventions](../core/labs/models/docs/booking-model-conventions.md) — persistence reference and target reservation/concurrency rules.
- [Labs model architecture](../core/labs/models/docs/labs-model-architecture.md) — model inventory, principal relationships and constraints, ownership boundaries, integrity risks and open questions.

For project setup and the development overview, start at the repository [README](../README.md).
