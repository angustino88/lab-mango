# Booking Model Conventions

## Scope, status and authority

Status: current booking persistence reference with target workflow guidance; not
runtime or migration certification. Scope: resource ownership, schedule invariants
and booking model naming. The [Feature Template Specification](../../../../docs/feature-template.md)
owns feature layout, command/query boundaries, public interfaces and test ownership;
[Django Model Conventions](../../../../docs/django-model-conventions.md) specialize persistence rules.
The existing singular `models/booking/` path is a transitional model mapping, not
an alternative feature template.

## Purpose

Booking models represent a time-bounded reservation of a lab resource, including
a virtual bench workspace or physical equipment.
The model package separates resource-specific ownership from shared booking workflow
rules so a bench booking cannot accidentally reference equipment, and vice versa.

## Package Structure

```text
core/labs/models/booking/
    base.py          Shared abstract booking workflow and value choices
    bench_booking.py Concrete booking linked to labs.Bench
    equipment_booking.py Concrete booking linked to labs.Equipment
    reference_data.py LabProject booking metadata
    __init__.py      Public booking model exports
```

`base.py` contains the abstract `Booking` model. It must not be used as a database
table or imported as a concrete relation target. `BenchBooking` and
`EquipmentBooking` are both concrete resource models defined and exported by the
[booking package](../booking/__init__.py).

`LabProject` remains in this package because projects are part of booking metadata
and are already consumed by the lab-project API and admin. It is not equipment
reference data and should not be moved into the equipment package.

## Model Rules

1. A concrete booking must have exactly one resource owner.
2. Resource-specific foreign keys belong on the concrete booking model.
3. Shared workflow fields belong on `Booking`.
4. `starts_at` must be earlier than `ends_at`.
5. A cancellation requires `cancellation_reason`.
6. A rejected booking requires `approved_by` for auditability.
7. Resource deletion uses `PROTECT` so booking history is not orphaned.
8. Schedule indexes must start with the resource foreign key, followed by time.
9. Status and approval values use `TextChoices`; do not add free-form strings.
10. Model `clean()` validates invariants, but it does not perform overlap queries.

## Naming

- Use `BenchBooking` and `EquipmentBooking` for concrete resource-specific models.
- Use `Booking` only for shared abstract behavior.
- Use `starts_at` and `ends_at` for timezone-aware booking boundaries.
- Use `approved_by` for the actor who made an approval decision.
- Use `reason` for the requested purpose and `cancellation_reason` for cancellation.

## Querying Availability

Read-only availability projections belong in the owning feature's `queries`, not
in `Booking.clean()`. Reservation writes enter `application` commands, which own
authorization, atomic persistence and race protection using documented locking or
database constraints; an earlier availability read alone cannot prevent double
booking. Existing service/selector names describe transitional code, not the target
layout. Internal API callers import their own `application`/`queries`, never their
own `public` facade; other features invoke supported behavior through `public`.
The standard overlap rule is half-open interval logic:

```python
existing.starts_at < requested_ends_at
and existing.ends_at > requested_starts_at
```

Bookings in `reserved` or `in_progress` with approval `pending` or `approved`
block a reservation, matching [Booking.is_reserving](../booking/base.py).
Availability queries must be scoped to
the concrete model's resource foreign key.

## Coding Rules

- Keep model files focused on fields, invariants, and small domain properties.
- Keep persistence workflows, notifications, and availability queries out of models.
- Use `select_related` for `bench`, `equipment`, `project`, and approval users in
  read paths.
- Add model integrity tests under `core/labs/tests/`; overlap projections and
  reservation-command tests belong in the owning feature's `tests/queries` and
  `tests/application` (or the small-layout equivalents).
- Explicitly invoke and test booking validation: Django `save()` does not call
  `full_clean()`, and the booking base does not override that behavior. The period
  check is database-backed; cancellation/approval checks also require validation.
- Keep best-effort notifications after commit with `transaction.on_commit`;
  required delivery needs an outbox row persisted in the command transaction,
  retryable dispatch and idempotent consumers. A callback alone is not durable.
- Do not silently rename persisted fields; database changes require an explicit
  migration decision.
- Do not reintroduce a nullable pair of `bench` and `equipment` fields on one
  concrete model.
- Keep public imports in `booking/__init__.py` intentional and remove exports when
  a model is deleted.

## Change Checklist

Before adding a booking resource:

- Create a concrete model inheriting from `Booking`.
- Add one required, protected resource foreign key.
- Add resource-first schedule and state indexes.
- Add the model to `booking/__init__.py` and `core.labs.models` only if it is a
  supported public import.
- Add tests for ownership, interval validation, cancellation, and availability.
- Review the required schema/data migration explicitly. Documentation does not
  generate migrations or authorize a reset of an existing database.
