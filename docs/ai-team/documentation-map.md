# Documentation map (owner-maintained)

Where architecture documents live. The Architecture Agent reads this **before choosing any output path**
and follows it over its own defaults. Keep it current: when a domain gets docs, add its row.

**Principle:** documentation lives next to the code it describes, grouped by domain. Repo-level `docs/`
is only for cross-domain content (system view, domain map, links to the domain docs).

## Status legend

| Status | What agents do |
| --- | --- |
| Adopted | Binding. Follow it. |
| Proposed | Not adopted. May be recommended to the owner. Never create, split, or move documents to match it. |
| CONFIRM | Best-guess default. Use it, state the path, ask the owner to confirm. |

## Placement rules

| Doc type | Location | File name | Status |
| --- | --- | --- | --- |
| Domain model architecture (single document) | `core/<domain>/models/docs/` | `<domain>-model-architecture.md` | Adopted for `labs` (owner example); CONFIRM for other domains |
| Domain model catalog | `core/<domain>/models/docs/` | `README.md` | Proposed |
| Domain model group | `core/<domain>/models/docs/` | `<group>.md` | Proposed |
| Feature architecture | `<feature package>/docs/` | `architecture.md` | CONFIRM |
| Cross-domain / system architecture | `docs/architecture.md` | | CONFIRM |
| Architecture Decision Records | `docs/architecture/decisions/` | `NNN-short-title.md` | CONFIRM |
| API response standard and golden examples | `docs/ai-team/api/` | `response-standard.md`, `response-golden-examples.md` | CONFIRM |
| OpenAPI contract (generated from code) | `openapi/` | `openapi.yml` | CONFIRM |

## Domain index

| Domain | Layout | Model architecture doc(s) | Status |
| --- | --- | --- | --- |
| labs | single document | `core/labs/models/docs/labs-model-architecture.md` | Adopted |
| `<domain>` | single document | `core/<domain>/models/docs/<domain>-model-architecture.md` | fill in |

## Model documentation layouts

### Layout A: single document (default)

One `<domain>-model-architecture.md` per domain, structured with `templates/model-group-doc.md`.

### Layout B: catalog plus groups (Proposed, not adopted)

For domains whose single document has become hard to navigate. Consider proposing it to the owner when
**two or more** of these hold:

- the domain has more than about 8 to 10 models
- it covers three or more distinct concerns or lifecycles (for example equipment, bookings, financial)
- the document is too long to review in one sitting
- several people regularly edit it at the same time

Structure:

- `core/<domain>/models/docs/README.md`: the catalog. Navigation and domain overview only: one row per
  group (purpose, owned models, link, status), an entity-level domain ER diagram, a class-name-only
  hierarchy overview, cross-domain dependencies. Structure: `templates/model-catalog-doc.md`.
- `core/<domain>/models/docs/<group>.md`: one document per group. Authoritative for its models' fields,
  constraints, lifecycle, inheritance hierarchy, and a focused ER diagram. Structure: `templates/model-group-doc.md`.

Labs example (proposed, not the adopted Labs layout):

- `core/labs/models/docs/README.md`: model catalog and domain ER overview
- `core/labs/models/docs/equipment.md`: equipment model group
- `core/labs/models/docs/bookings.md`: booking model group
- `core/labs/models/docs/financial.md`: purchase, payment, license, and expense relationships

**Adoption procedure.** Until the owner approves a domain's move and changes its Layout and Status in the
domain index, the existing document stays the authority. Once approved, do the move as one
documentation-only change: split content into groups, build the catalog, leave no duplicated definitions,
fix every link that pointed at the old document, and pass the model coverage check.

## Rules

- One authoritative document per model group. Other docs link to it; they do not copy it.
- A catalog is navigation and a domain-relationship overview; it is never a second copy of the group docs.
- Every model class in code appears in exactly one group document (or in the single document).
- A relationship that crosses groups or domains is defined on the owning side and linked from the other.
- An inheritance hierarchy is documented once, in the document that owns its base class (section
  "Inheritance and hierarchy"). Subclasses in other groups or domains link to it and do not redefine the base.
- Inheritance (is-a) and relationships (has-a) are shown in separate diagrams: `classDiagram` and `erDiagram`.
- Every subclass in code appears in its hierarchy documentation, with its inheritance kind.
- Update an existing document instead of creating a second one on the same subject.
- API response rules live in `docs/ai-team/api/response-standard.md`. Other documents link to it and to
  `docs/api-response-contracts.md`; they do not copy the rules.
- `openapi/` is generated from code. Change the code and regenerate; do not edit the schema by hand.
- Repo-level `docs/architecture.md` links to domain docs; it does not duplicate them.
- If a domain is not in the index, derive the path from the placement rules, state it, and ask the owner to confirm.
