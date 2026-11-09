# Documentation index

The single entry point for project documentation. Setup and development: the repository [README](../README.md).
AI-agent rules: [AGENTS.md](../AGENTS.md). Where a new document goes: [documentation map](ai-team/documentation-map.md).

Documentation describes the **target**; existing code is transitional. Generated [OpenAPI](../openapi/openapi.yml)
and mounted URLconfs determine the live API; proposed paths in prose are not callable endpoints.

## Layout

| Folder | Holds |
| --- | --- |
| [`architecture/`](architecture/README.md) | System view, feature template, core architecture, reference data, [ADRs](architecture/decisions/) |
| [`conventions/`](conventions/) | Naming/text conventions and Django model conventions |
| [`api/`](api/) | Request/response standards, golden examples, runtime operation contracts |
| [`agent-platform/`](agent-platform/) | Device agent, backend Agent API and routing-sync designs |
| [`proposals/`](proposals/) | Designs not yet approved, or for features that do not exist yet |
| [`ai-team/`](ai-team/README.md) | AI team roles, prompt formats, quality gates, templates |
| `core/<app>/…/docs/` | Feature specs, feature architecture and feature designs, next to the code |

## Standards (binding, in precedence order)

1. [Feature template](architecture/feature-template.md) — feature structure, layers, public contracts, wiring, tests.
2. [Core architecture](architecture/core-architecture.md) — app/kernel/infrastructure ownership, composition, rebuild phases, review backlog.
3. [Django model conventions](conventions/django-models.md) and [naming conventions](conventions/naming.md).
4. [Response standard](api/response-standard.md) and [request standard](api/request-standard.md), with
   [response](api/response-golden-examples.md) and [request](api/request-golden-examples.md) golden examples;
   [operation contracts](api/contracts.md) for runtime/OpenAPI usage.
5. Feature documents below for behavior and compatibility.

## Architecture

- [System overview](architecture/README.md) — top-level packages and cross-domain rules.
- [Labs cross-feature map](architecture/labs-features.md) — Labs feature ownership and dependencies.
- [Labs model architecture](../core/labs/models/docs/labs-model-architecture.md) — authoritative Labs model inventory and constraints; [booking model conventions](../core/labs/models/docs/booking-model-conventions.md).
- [Reference data framework](architecture/reference-data.md) — baseline rows and deletion policy.
- [API resource summaries](api/resource-summary.md) — independent summary endpoints.

### Decisions

| ADR | Subject | Status |
| --- | --- | --- |
| [001](architecture/decisions/001-common-foundation.md) | Common foundation redesign | Accepted |
| [002](architecture/decisions/002-catalog-and-selector-api.md) | Catalog and selector API standard | Accepted, implemented |
| [003](architecture/decisions/003-temporal-query-convention.md) | Temporal query bounds | Proposed |
| [004](architecture/decisions/004-agent-routing-sync.md) | Agent routing and backend sync | Approved constraints |

## Agent platform

Proposals, not deployed behavior. Each document owns one concern; the others link to it.

| Document | Owns |
| --- | --- |
| [Device design](agent-platform/device-design.md) | Windows/Linux agent service, updater, bootstrap, local reliability |
| [Backend Agent API](agent-platform/backend-api.md) | Enrollment, authentication, telemetry and booking API |
| [Routing and sync](agent-platform/routing-sync.md) | Routing claims, publisher, internal sync API (sole routing authority) |

Accepted constraints are recorded in [ADR 004](architecture/decisions/004-agent-routing-sync.md).

## Feature catalog

### Labs (`core/labs`)

| Feature | Package | Documents |
| --- | --- | --- |
| Equipment | `core/labs/features/equipment` | [spec](../core/labs/features/equipment/docs/spec.md) · [architecture](../core/labs/features/equipment/docs/architecture.md) · [category APIs](../core/labs/features/equipment/docs/equipment-category-apis.md) |
| Benches | `core/labs/features/benches` | [spec](../core/labs/features/benches/docs/spec.md) · [architecture](../core/labs/features/benches/docs/architecture.md) · [bench & station APIs](../core/labs/features/benches/docs/bench-station-apis.md) |
| Bench bookings | `core/labs/features/bench_bookings` | [spec](../core/labs/features/bench_bookings/docs/spec.md) · [architecture](../core/labs/features/bench_bookings/docs/architecture.md) · [notifications](../core/labs/features/bench_bookings/docs/notifications.md) |
| Locations | `core/labs/features/locations` | [spec](../core/labs/features/locations/docs/spec.md) · [architecture](../core/labs/features/locations/docs/architecture.md) |
| Licenses | `core/labs/features/licenses` | [spec](../core/labs/features/licenses/docs/spec.md) |
| Procurement | `core/labs/features/procurement` | [spec](../core/labs/features/procurement/docs/spec.md) · [architecture](../core/labs/features/procurement/docs/architecture.md) · [purchase plan design](../core/labs/features/procurement/docs/purchase-plan-design.md) |
| Expense | `core/labs/features/expense` | [spec](../core/labs/features/expense/docs/spec.md) · [architecture](../core/labs/features/expense/docs/architecture.md) |
| Resource mappings | `core/labs/features/resource_mappings` | [spec](../core/labs/features/resource_mappings/docs/spec.md) · [architecture](../core/labs/features/resource_mappings/docs/architecture.md) |
| Resource audit | `core/labs/features/resource_audit` | [spec](../core/labs/features/resource_audit/docs/spec.md) · [architecture](../core/labs/features/resource_audit/docs/architecture.md) |
| Monitoring | `core/labs/features/monitoring` | [spec](../core/labs/features/monitoring/docs/spec.md) · [architecture](../core/labs/features/monitoring/docs/architecture.md) |
| Analytics | `core/labs/features/analytics` | [spec](../core/labs/features/analytics/docs/spec.md) · [architecture](../core/labs/features/analytics/docs/architecture.md) |
| Leaderboard | `core/labs/features/leaderboard` | [spec](../core/labs/features/leaderboard/docs/spec.md) · [architecture](../core/labs/features/leaderboard/docs/architecture.md) |
| Dashboard | `core/labs/features/dashboard` | [spec](../core/labs/features/dashboard/docs/spec.md) · [architecture](../core/labs/features/dashboard/docs/architecture.md) |

### Support Desk, Users, WebSocket

| Feature | Package | Documents |
| --- | --- | --- |
| Support tickets | `core/support_desk/features/tickets` | [spec](../core/support_desk/features/tickets/docs/spec.md) |
| Authentication | `core/users/features/auth` | [spec](../core/users/features/auth/docs/spec.md) |
| Profile | `core/users/features/profile` | [spec](../core/users/features/profile/docs/spec.md) |
| Groups | `core/users/features/groups` | [spec](../core/users/features/groups/docs/spec.md) |
| URS sync | `core/users/features/urs_sync` | [spec](../core/users/features/urs_sync/docs/spec.md) |
| WebSocket notifications | `core/websocket/features` | [spec](../core/websocket/features/docs/spec.md) |

## Proposals

| Proposal | Status |
| --- | --- |
| [Equipment booking](proposals/equipment-booking.md) | Draft; `equipment_bookings` feature not created |
| [All-feature faceted filtering](proposals/faceted-filtering.md) | Proposed; Equipment facets pilot implemented |
| [API error details audit](proposals/api-error-details-audit.md) | Not started |
