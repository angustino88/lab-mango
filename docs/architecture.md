# Lab Mango backend architecture (cross-domain)

> Status: Proposed overview, verified against repository layout on 2026-10-15. Domain details live in the linked domain documents; this page does not duplicate them.

## 1. System view

The backend is a Django and Django REST Framework application with PostgreSQL. Top-level packages under `core/` are:

- `core/labs/`: laboratory domain (resources, bookings, licenses, finance, procurement, monitoring, analytics).
- `core/users/`, `core/websocket/`, `core/infrastructure/`, `core/jira_integration/`: supporting areas.
- `core/common/`, `core/contrib/`: shared technical code. These must not import feature code.

## 2. Domain documents

| Area | Document |
|---|---|
| Labs model architecture (authoritative for Labs models) | [core/labs/models/docs/labs-model-architecture.md](../core/labs/models/docs/labs-model-architecture.md) |
| Equipment feature architecture | [core/labs/features/equipment/docs/architecture.md](../core/labs/features/equipment/docs/architecture.md) |

## 3. Cross-domain designs

| Topic | Document | Status |
| --- | --- | --- |
| Reference data provisioning and deletion policy (all Labs models) | [reference-data-defaults.md](reference-data-defaults.md) | Proposed framework |
| Catalog and selector API standard (all domains) | [ADR 002](architecture/decisions/002-catalog-and-selector-api.md) | Accepted (D5 pending confirmation); implementation not started |

## 4. Cross-domain rules

- Feature modules own their data and rules; other code uses the feature's public interface.
- Invariants are enforced in the database where PostgreSQL can enforce them.
- Startup and provisioning commands run after schema migrations; `AppConfig.ready()` performs no ORM work.
- Architecture rules are enforced by checks (import contracts, architecture tests) rather than by documentation alone. Those checks are not verified as complete here.

## 5. Open items

- The enforcement checks named in the domain documents are not verified as implemented.
- Choosing which Labs reference models are protected, editable, or unmanaged is an owner decision.
