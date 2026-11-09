# Lab Mango backend architecture (cross-domain)

> Status: Proposed overview, verified against repository layout on 2026-11-09. Domain details live in the linked domain documents; this page does not duplicate them.

## 1. System view

The backend is a Django and Django REST Framework application with PostgreSQL. Top-level packages under `core/` are:

- `core/labs/`: laboratory domain (resources, bookings, licenses, finance, procurement, monitoring, analytics).
- `core/support_desk/`: support tickets with resource traceability.
- `core/users/`, `core/websocket/`: identity/access and real-time notifications.
- `core/agents/`, `core/routing/`: device agent enrollment and routing projection ([agent platform](../agent-platform/)).
- `core/reference_data/`: baseline reference rows ([reference data](reference-data.md)).
- `core/infrastructure/`: technical/provider adapters.
- `core/common/`: shared technical kernel. These must not import feature code.

## 2. Domain documents

| Area | Document |
|---|---|
| Labs model architecture (authoritative for Labs models) | [core/labs/models/docs/labs-model-architecture.md](../../core/labs/models/docs/labs-model-architecture.md) |
| Labs cross-feature map (ownership, dependencies) | [labs-features.md](labs-features.md) |
| Per-feature spec and architecture | [Feature catalog](../README.md#feature-catalog) |

## 3. Cross-domain designs

| Topic | Document | Status |
| --- | --- | --- |
| Reference data provisioning and deletion policy (all Labs models) | [Reference data](reference-data.md) | Proposed framework |
| Catalog and selector API standard (all domains) | [ADR 002](decisions/002-catalog-and-selector-api.md) | Accepted and implemented |

## 4. Cross-domain rules

- Feature modules own their data and rules; other code uses the feature's public interface.
- Invariants are enforced in the database where PostgreSQL can enforce them.
- Startup and provisioning commands run after schema migrations; `AppConfig.ready()` performs no ORM work.
- Architecture rules are enforced by checks (import contracts, architecture tests) rather than by documentation alone. Those checks are not verified as complete here.

## 5. Open items

- The enforcement checks named in the domain documents are not verified as implemented.
- Choosing which Labs reference models are protected, editable, or unmanaged is an owner decision.
