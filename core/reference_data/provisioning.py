from collections.abc import Iterable, Mapping

from django.db import models, transaction
from django.db.models import F, UniqueConstraint
from django.db.models.functions import Lower

from core.reference_data.declarations import ReferenceList, ReferenceMode
from core.reference_data.models import ProtectedReferenceMixin, SeededReferenceList


def provision_reference_lists(
    reference_lists: Iterable[ReferenceList],
    *,
    using: str,
) -> None:
    """Provision declared rows on the requested database connection."""
    for reference_list in reference_lists:
        _validate_reference_list(reference_list)
        if _should_provision(reference_list, using=using):
            _provision_list(reference_list, using=using)


def _should_provision(reference_list: ReferenceList, *, using: str) -> bool:
    if reference_list.mode is ReferenceMode.ENSURE_PRESENT:
        return True
    if reference_list.mode is ReferenceMode.SEED_ONCE:
        return not _seed_marker_exists(reference_list, using=using)
    raise ValueError(f"Unsupported reference data mode: {reference_list.mode!r}")


def _provision_list(reference_list: ReferenceList, *, using: str) -> None:
    model = reference_list.model
    manager = model._base_manager.db_manager(using)

    with transaction.atomic(using=using):
        for row in reference_list.rows:
            identity_value = row.get(reference_list.identity)
            if identity_value is None:
                raise ValueError(
                    f"Reference row for {model._meta.label} is missing identity "
                    f"field {reference_list.identity!r}."
                )

            manager.get_or_create(
                **{reference_list.identity: identity_value},
                defaults=_creation_values(row, identity=reference_list.identity),
            )

        if reference_list.mode is ReferenceMode.SEED_ONCE:
            marker, _ = SeededReferenceList.objects.using(using).get_or_create(
                key=reference_list.key,
                defaults={
                    "model_label": model._meta.label_lower,
                    "identity_field": reference_list.identity,
                },
            )
            _validate_seed_marker(reference_list, marker)


def _validate_reference_list(reference_list: ReferenceList) -> None:
    model = reference_list.model
    identity_field = model._meta.get_field(reference_list.identity)
    if not isinstance(identity_field, models.Field):
        raise ValueError(f"{reference_list.identity!r} must name a concrete model field.")
    if not _is_unique_identity(model, reference_list.identity, identity_field):
        raise ValueError(
            f"{model._meta.label}.{reference_list.identity} must be unique for reference provisioning."
        )
    if reference_list.mode is ReferenceMode.ENSURE_PRESENT and not issubclass(model, ProtectedReferenceMixin):
        raise ValueError(
            f"{model._meta.label} must inherit ProtectedReferenceMixin for ENSURE_PRESENT provisioning."
        )

    seen_identities: set[object] = set()
    for row in reference_list.rows:
        if reference_list.identity not in row or row[reference_list.identity] is None:
            raise ValueError(
                f"Reference row for {model._meta.label} is missing identity "
                f"field {reference_list.identity!r}."
            )
        identity_value = row[reference_list.identity]
        if identity_value in seen_identities:
            raise ValueError(
                f"Reference list {reference_list.key!r} contains duplicate identity {identity_value!r}."
            )
        seen_identities.add(identity_value)


def _is_unique_identity(model: type[models.Model], identity: str, field: models.Field) -> bool:
    if field.unique or field.primary_key:
        return True
    identity_attname = field.attname
    if any(
        tuple(fields) in ((identity,), (identity_attname,))
        for fields in model._meta.unique_together
    ):
        return True
    return any(
        isinstance(constraint, UniqueConstraint)
        and constraint.condition is None
        and (
            (
                not getattr(constraint, "expressions", ())
                and tuple(constraint.fields) in ((identity,), (identity_attname,))
            )
            or _is_case_insensitive_identity(constraint, identity)
        )
        for constraint in model._meta.constraints
    )


def _is_case_insensitive_identity(constraint: UniqueConstraint, identity: str) -> bool:
    """Accept a single ``Lower(identity)`` expression, e.g. ``UniqueConstraint(Lower("name"))``."""
    expressions = tuple(getattr(constraint, "expressions", ()))
    if len(expressions) != 1 or constraint.fields:
        return False
    expression = expressions[0]
    if not isinstance(expression, Lower) or len(expression.source_expressions) != 1:
        return False
    source = expression.source_expressions[0]
    return isinstance(source, F) and source.name == identity


def _creation_values(row: Mapping[str, object], *, identity: str) -> dict[str, object]:
    return {field: value for field, value in row.items() if field != identity}


def _seed_marker_exists(reference_list: ReferenceList, *, using: str) -> bool:
    marker = SeededReferenceList.objects.using(using).filter(key=reference_list.key).first()
    if marker is None:
        return False
    _validate_seed_marker(reference_list, marker)
    return True


def _validate_seed_marker(reference_list: ReferenceList, marker: SeededReferenceList) -> None:
    expected = (reference_list.model._meta.label_lower, reference_list.identity)
    actual = (marker.model_label, marker.identity_field)
    if actual != expected:
        raise ValueError(
            f"Reference list key {reference_list.key!r} was already seeded for "
            f"{marker.model_label}.{marker.identity_field}, not "
            f"{reference_list.model._meta.label}.{reference_list.identity}."
        )
