# Domain Glossary (to be confirmed by the product owner)

This file lists concepts named in `AGENTS.md`. Agents must not add definitions they
cannot verify in code or from the owner. Owner: fill in and keep current.

| Term | Meaning / owner module | Notes |
|---|---|---|
| Resource lifecycle status | <confirm> for benches, rooms, stations, licenses. Equipment: see *Equipment lifecycle state* | Distinct from booking and live activity status |
| Booking status | <confirm> | Distinct from resource lifecycle status |
| Live activity status | <confirm> | From monitoring; distinct from lifecycle |
| Stable global resource identifier | <confirm> | Distinct from database primary key |
| Room / Station / Bench | <confirm> | |
| Equipment | <confirm> | |
| Assignment | A **bench placement** of equipment (`EquipmentAssignment.objects` returns only these); see *Placement*. License assignments are a separate concept (`LicenseAssignment`). | Verified in code: `core/labs/models/resource/equipment/assignment.py` |
| License | <confirm> | Agreement vs payment are different concepts |
| Expense / Purchase | <confirm> | Commitment vs actual payment |
| Equipment lifecycle state | Whether the lab still has a unit: `planned`, `in_service`, `transferred_out` (handed to another organisation), `retired` (scrapped), `lost`. Changed only by the change-lifecycle action. `in_service` does **not** mean "on a bench". Owner: equipment | Owner decisions OD5, OD8 (redesign proposal); code: `Equipment.lifecycle_state`, `application/change_state.py` |
| Equipment condition | Whether an in-service unit works: `operational`, `in_maintenance`, `out_of_service`. Changing it never moves the unit. Owner: equipment | Code: `Equipment.condition`; constraint `equipment_condition_only_in_service` |
| Placement | Where a unit is: on a bench, at a station, in a room, or at an untracked place described in `location_note`; none means unknown. One active placement per unit. "In storage" means placed in a room, at a station, or at a noted place. Owner: equipment | Owner decisions OD1-OD2; code: `EquipmentPlacement`, `application/place_equipment.py` |
| Display status (equipment) | One computed, read-only label (`available`, `in_use`, `maintenance`, `broken`, `calibration_overdue`, `on_order`, `transferred`, `retired`, `lost`) derived from lifecycle state, condition, bench placement and calibration. Never stored or set by hand. Owner: equipment | Code: `queries/equipment.py::display_status_expression`; priority table in `features/equipment/docs/spec.md` section 2.0 |
| Equipment event | Append-only record of one lifecycle or condition change (from, to, reason, actor, time). Owner: equipment | Code: `EquipmentEvent` |
| Equipment loan | Physical custody: who holds an item and until when (`borrower`, `due_at`). Not a booking (a booking is a calendar entry). An item on loan has no placement; overdue is computed. Owner: equipment | Owner decision OD4 (no loan code); code: `EquipmentLoan`, `application/loans.py` |
| Loan slip (equipment loan batch) | One borrower (a user, or a name and contact for people without an account) and purpose for one or more items handed over together; each item is a loan line and can be returned separately. Owner: equipment | Owner answers R2, R3, R5; code: `EquipmentLoanBatch` |
| Equipment reservation | A coordinator-entered booking that keeps one item for a borrower over a later window (`EquipmentBooking`, grouped on a loan slip). Becomes a loan at hand-over; expires if not collected by the end of its start day. Owner: equipment | Owner decisions R1, R6, R7; code: `application/reservations.py` |
| Equipment category | The family of a unit (`kind.category`), stored data rather than a model: all equipment is one table. Its flags `bookable`, `placeable_on_bench`, `calibratable`, `monitored` decide what units of the category can do; which typed fields it uses is `CATEGORY_TYPED_FIELDS`. Owner: equipment | Redesign step 6, owner decisions A-C; code: `EquipmentCategory`, `application/_category.py` |
| Computing profile | The computing columns of a unit in a `monitored` category (hostname, IP, OS, disks, RDP file, technical user). "Computing equipment" means a unit with a profile. Owner: equipment | Code: `ComputingProfile`, `application/computing_profile.py` |
