"""Model validation before a write, without the queries that cannot find anything ``full_clean`` would.

``Model.full_clean()`` runs a database query for every foreign key (does the target exist?) and for every
``Meta.constraints`` entry (Django evaluates even a ``CheckConstraint`` with a query inside a savepoint).
On a create that holds its references as loaded instances most of those queries prove what is already
known, and PostgreSQL enforces every one of them again on ``save()``.

``validate_for_write`` runs the same steps in the same order (``clean_fields``, ``clean``,
``validate_unique``, constraints) and raises the same ``ValidationError`` shape. It skips only:

1. the existence query of a foreign key whose related instance is loaded on the object (it was read or
   saved in this process) and has no ``limit_choices_to``; the field's own validation is still skipped
   with it, as ``full_clean(exclude=...)`` would, because a loaded instance has a valid primary key;
2. a ``CheckConstraint`` of the form ``field__in=<the field's choices>`` when ``clean_fields`` already
   checked that field's value against the same choices;
3. the savepoint and SQL condition check Django wraps around a conditional ``UniqueConstraint`` whose
   condition only tests ``field__isnull`` (for example "active rows": ``deleted_at__isnull=True``): the
   condition is decided on the instance in Python and the duplicate lookup is the same single query, with
   the same ``ValidationError`` Django raises;
4. constraints the model lists in ``constraints_validated_in_clean`` (its ``clean()`` raises the same
   rule with a field message) or the caller lists in ``skip_constraints`` (the caller's own logic, under
   its lock, guarantees the rule; say why at the call site).

PostgreSQL still enforces every skipped rule: a concurrent change that breaks one fails the write with an
``IntegrityError`` instead of a ``ValidationError``.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.core.exceptions import NON_FIELD_ERRORS, FieldDoesNotExist, ValidationError
from django.db import models, router
from django.db.models import Q


def _loaded_relations(instance: models.Model) -> set[str]:
    names: set[str] = set()
    for field in instance._meta.concrete_fields:
        # ForeignKey and OneToOneField (a ForeignKey subclass); not generic or composite relations.
        if not isinstance(field, models.ForeignKey) or not field.is_cached(instance):
            continue
        related = field.get_cached_value(instance)
        if related is None or related._state.adding or related.pk is None:
            continue
        if field.get_limit_choices_to():
            continue
        if getattr(related, field.target_field.attname) != getattr(instance, field.attname):
            continue
        names.add(field.name)
    return names


def _choices_only_check(constraint: Any, model: type[models.Model], instance: models.Model) -> bool:
    """``CheckConstraint(condition=Q(field__in=<field choices>))`` whose field ``clean_fields`` validated."""
    if not isinstance(constraint, models.CheckConstraint):
        return False
    condition = constraint.condition
    if not isinstance(condition, Q) or condition.negated or len(condition.children) != 1:
        return False
    child = condition.children[0]
    if not isinstance(child, tuple) or not child[0].endswith("__in"):
        return False
    field = _concrete_field(model, child[0][: -len("__in")])
    if field is None or not field.choices:
        return False
    if getattr(instance, field.attname) in field.empty_values:
        # clean_fields does not check an empty value against the choices; let the constraint decide.
        return False
    allowed = {str(value) for value in child[1]}
    return allowed == {str(value) for value, _label in field.flatchoices}


def _concrete_field(model: type[models.Model], name: str) -> models.Field | None:
    """The concrete model field called ``name`` (no lookups across relations), or ``None``."""
    try:
        field = model._meta.get_field(name)
    except FieldDoesNotExist:
        return None
    return field if isinstance(field, models.Field) and field.concrete else None


def _condition_fields(model: type[models.Model], tests: list[tuple[str, bool]]) -> list[models.Field]:
    attnames = {attname for attname, _isnull in tests}
    return [field for field in model._meta.concrete_fields if field.attname in attnames]


def _isnull_condition(constraint: models.UniqueConstraint, model: type[models.Model]) -> list[tuple[str, bool]] | None:
    """``[(attname, isnull), ...]`` when the condition is an AND of ``field__isnull=<bool>``; else ``None``."""
    condition = constraint.condition
    if not isinstance(condition, Q) or condition.negated or condition.connector != Q.AND:
        return None
    tests: list[tuple[str, bool]] = []
    for child in condition.children:
        if not isinstance(child, tuple) or not child[0].endswith("__isnull") or not isinstance(child[1], bool):
            return None
        field = _concrete_field(model, child[0][: -len("__isnull")])
        if field is None or field.generated:
            return None
        tests.append((field.attname, child[1]))
    return tests or None


def _validate_isnull_unique(
    constraint: models.UniqueConstraint,
    model: type[models.Model],
    instance: models.Model,
    *,
    exclude: set[str],
    using: str,
) -> bool:
    """Validate ``constraint`` as ``UniqueConstraint.validate`` would; ``False`` when it is not supported.

    Supported: plain field lists (no expressions or generated fields), ``nulls_distinct`` not ``False`` and a
    condition accepted by ``_isnull_condition``.
    """
    if not constraint.fields or constraint.expressions or constraint.nulls_distinct is False:
        return False
    tests = _isnull_condition(constraint, model)
    if tests is None:
        return False
    fields = [_concrete_field(model, name) for name in constraint.fields]
    if any(field is None or field.generated for field in fields):
        return False
    lookup: dict[str, Any] = {}
    for field in fields:
        assert field is not None
        if field.name in exclude:
            return True
        value = getattr(instance, field.attname)
        if value is None:
            return True  # NULL never equals NULL: no duplicate is possible.
        lookup[field.name] = value
    # Django skips the check when a field of the condition is excluded (FieldError); so does this.
    if any(field.name in exclude or field.attname in exclude for field in _condition_fields(model, tests)):
        return True
    if not all((getattr(instance, attname) is None) is isnull for attname, isnull in tests):
        return True  # The instance is outside the constraint's condition.
    queryset = model._default_manager.using(using).filter(**lookup).filter(constraint.condition)
    model_pk = instance._get_pk_val(model._meta)
    if not instance._state.adding and model_pk is not None:
        queryset = queryset.exclude(pk=model_pk)
    if queryset.exists():
        raise ValidationError(constraint.get_violation_error_message(), code=constraint.violation_error_code)
    return True


def _validate_constraints(instance: models.Model, *, exclude: set[str], skip: frozenset[str]) -> None:
    using = router.db_for_write(type(instance), instance=instance)
    errors: dict[str, list[ValidationError]] = {}
    for model_class, model_constraints in instance.get_constraints():
        for constraint in model_constraints:
            if constraint.name in skip or _choices_only_check(constraint, model_class, instance):
                continue
            try:
                if isinstance(constraint, models.UniqueConstraint) and constraint.condition is not None:
                    if _validate_isnull_unique(constraint, model_class, instance, exclude=exclude, using=using):
                        continue
                constraint.validate(model_class, instance, exclude=exclude, using=using)
            except ValidationError as error:
                fields: tuple[str, ...] = tuple(getattr(constraint, "fields", ()))
                if getattr(error, "code", None) == "unique" and len(fields) == 1:
                    errors.setdefault(fields[0], []).append(error)
                else:
                    errors = error.update_error_dict(errors)
    if errors:
        raise ValidationError(errors)


def validate_for_write(
    instance: models.Model,
    *,
    skip_constraints: Iterable[str] = (),
    skip_unique: Iterable[str] = (),
) -> None:
    """``instance.full_clean()`` without the redundant queries listed in the module docstring.

    ``skip_unique`` names unique fields whose value the caller generated (for example a ``uuid4`` default the
    caller never accepts from input); the unique index still guards them.
    """
    errors: dict[str, Any] = {}
    exclude = _loaded_relations(instance)
    try:
        instance.clean_fields(exclude=exclude)
    except ValidationError as error:
        errors = error.update_error_dict(errors)
    try:
        instance.clean()
    except ValidationError as error:
        errors = error.update_error_dict(errors)
    # As in full_clean: unique and constraint checks run only for fields that passed validation. A loaded
    # relation is not excluded here, so unique and constraint checks that involve it still run.
    failed = {name for name in errors if name != NON_FIELD_ERRORS}
    try:
        instance.validate_unique(exclude=failed | set(skip_unique))
    except ValidationError as error:
        errors = error.update_error_dict(errors)
    failed = {name for name in errors if name != NON_FIELD_ERRORS}
    skip = frozenset(skip_constraints) | frozenset(getattr(type(instance), "constraints_validated_in_clean", ()))
    try:
        _validate_constraints(instance, exclude=failed, skip=skip)
    except ValidationError as error:
        errors = error.update_error_dict(errors)
    if errors:
        raise ValidationError(errors)


__all__ = ["validate_for_write"]
