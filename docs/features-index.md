# Master Features Specification Index & Architecture Hub

**Target:** Lab Mango Backend  
**Standard:** Vertical Feature Layering (`GEMINI.md`, `feature-template.md`, `core-architecture-redesign.md`)  
**Status:** Canonical Reference

---

## 1. Executive Domain Organization

The Lab Mango backend is architectured as a modular monolith organized into vertical feature slices across five primary applications under `core/`:

```
core/
├── labs/              # Core laboratory physical & logical assets, operations, finance & analytics
├── users/             # Identity, authentication, profiles, groups, and directory sync
├── support_desk/      # Incident & issue ticketing with permanent resource traceability
├── jira_integration/  # Enterprise Atlassian Jira proxy and request pipeline
└── websocket/         # Real-time event channels, daemon telemetry & notification delivery
```

Every feature encapsulates its own `api/` (views, serializers, contracts), `application/` (commands, policies, transactions), `queries/` (read-only selectors), and `tests/` (unit, integration, and architecture tests). Concrete database models reside under `core/<app>/models/` for unified Django discovery and migrations.

---

## 2. Master Feature Specification Catalog

### 2.1 Laboratory Management & Resources (`core/labs`)
| Feature | Domain Package | Detailed Specification Document | Primary Models |
|---|---|---|---|
| **Equipment** | `core/labs/features/equipment` | [Equipment Spec](../core/labs/features/equipment/docs/spec.md) | `Equipment`, `EquipmentAssignment`, `EquipmentStatusRecord` |
| **Benches** | `core/labs/features/benches` | [Benches Spec](../core/labs/features/benches/docs/spec.md) | `Bench`, `BenchGroup`, `BenchType`, `BenchFavorite` |
| **Bench Bookings** | `core/labs/features/bench_bookings` | [Bench Bookings Spec](../core/labs/features/bench_bookings/docs/spec.md) | `Booking`, `BenchBooking`, `BookingNotification` |
| **Locations** | `core/labs/features/locations` | [Locations Spec](../core/labs/features/locations/docs/spec.md) | `Room`, `RoomSlot`, `Station`, `StationSlot`, `PhysicalLocationNode` |
| **Licenses** | `core/labs/features/licenses` | [Licenses Spec](../core/labs/features/licenses/docs/spec.md) | `License`, `LicenseAssignment`, `LicenseAgreement`, `LicensePayment` |
| **Procurement** | `core/labs/features/procurement` | [Procurement Spec](../core/labs/features/procurement/docs/spec.md) | `Purchase`, `PurchaseItem`, `PurchaseItemResource`, `PurchaseTransaction` |
| **Expense & Finance** | `core/labs/features/expense` | [Expense Spec](../core/labs/features/expense/docs/spec.md) | `Expense`, `ExpensePayment` |
| **Resource Mappings** | `core/labs/features/resource_mappings` | [Resource Mappings Spec](../core/labs/features/resource_mappings/docs/spec.md) | Hierarchical Topology Projections |

### 2.2 Operational Intelligence & Telemetry (`core/labs`)
| Feature | Domain Package | Detailed Specification Document | Primary Models |
|---|---|---|---|
| **Monitoring** | `core/labs/features/monitoring` | [Monitoring Spec](../core/labs/features/monitoring/docs/spec.md) | `MonitoringEvent` |
| **Resource Audit** | `core/labs/features/resource_audit` | [Resource Audit Spec](../core/labs/features/resource_audit/docs/spec.md) | `ResourceAudit`, `ResourceAuditItem`, `ResourceChangeLog` |
| **Analytics** | `core/labs/features/analytics` | [Analytics Spec](../core/labs/features/analytics/docs/spec.md) | Longitudinal Observation Models |
| **Leaderboard** | `core/labs/features/leaderboard` | [Leaderboard Spec](../core/labs/features/leaderboard/docs/spec.md) | Persona Scoring, Utilization Heatmaps |
| **Dashboard** | `core/labs/features/dashboard` | [Dashboard Spec](../core/labs/features/dashboard/docs/spec.md) | Operational Live Synthesis Cards |

### 2.3 Identity, Access & Administration (`core/users`)
| Feature | Domain Package | Detailed Specification Document | Primary Models |
|---|---|---|---|
| **Authentication** | `core/users/features/auth` | [Authentication Spec](../core/users/features/auth/docs/spec.md) | `User`, `EntraIdentity`, `LabManagementEmail` |
| **User Profile** | `core/users/features/profile` | [Profile Spec](../core/users/features/profile/docs/spec.md) | `User`, `ActorContext` |
| **User Groups & RBAC** | `core/users/features/groups` | [Groups Spec](../core/users/features/groups/docs/spec.md) | `Group`, `URSGroup` |
| **URS Directory Sync** | `core/users/features/urs_sync` | [URS Sync Spec](../core/users/features/urs_sync/docs/spec.md) | Directory Sync Tasks |

### 2.4 Integrations & Real-Time Communication
| Feature | Domain Package | Detailed Specification Document | Primary Models |
|---|---|---|---|
| **Support Desk** | `core/support_desk/features/tickets` | [Support Desk Spec](../core/support_desk/features/tickets/docs/spec.md) | `SupportTicket`, `SupportStatus`, `SupportTransition`, `SupportTicketActivity` |
| **Jira Integration** | `core/jira_integration` | [Jira Integration Spec](../core/jira_integration/features/docs/spec.md) | `JiraConfiguration`, `JiraIssueRequest` |
| **Websocket & Alerts** | `core/websocket` | [Websocket Spec](../core/websocket/features/docs/spec.md) | `Notification`, Channels & Consumers |

---

## 3. Core Architectural Invariants Reference

### 3.1 Resource Identity & Lifecycle Standard
All business assets inherit from `core.labs.models.resource.base.ResourceModel`:
- **Identity:** Immutable `uid` (UUIDv4) and unique active `sku` (CharField(255), stripped, indexed).
- **Audit:** Automatic timestamping (`created`, `modified`) and user stamps (`creator`, `last_modified_by`).
- **Soft Deletion:** Deletion sets `deleted_at=timezone.now()`. Physical SQL `DELETE` is prohibited on business models.

### 3.2 Options Selector Standard (`GEMINI.md`)
Every resource dropdown picker (`/api/<domain>/<resource>/options`) strictly yields a flat payload:
```json
{
  "data": [
    { "id": 1, "sku": "RESOURCE-001", "name": "Display Name" }
  ]
}
```
No nested objects, relations, timestamps, or extended metadata are allowed.

### 3.3 Database Integrity Constraints
1. **Equipment Assignment:** Exactly one active bench assignment permitted per equipment (`UniqueConstraint(fields=("equipment"), condition=Q(unassigned_at__isnull=True))`).
2. **Bench Placement:** Exactly one bench docked per physical `StationSlot`. Bench setup location must match the station owning the slot.
3. **Booking Schedule:** `ends_at > starts_at`. Overlapping active bookings on the same bench are strictly forbidden. Terminal booking states are irreversible.
4. **Support Ticket Activity:** Activity audit events are write-once and protected by a PostgreSQL trigger prohibiting `UPDATE` and `DELETE`.
5. **Token Security:** JWT refresh tokens are delivered strictly via `HttpOnly`, `SameSite=Lax`, `Secure` cookies. State-modifying requests require anti-CSRF headers.
