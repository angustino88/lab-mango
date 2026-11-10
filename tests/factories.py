"""Shared model factories for cross-feature tests.

Feature suites import these from ``tests.factories``. Factories build valid
rows through the models' own ``save`` (which runs ``full_clean``), so they
exercise the same invariants as production writes.
"""

from __future__ import annotations

import factory
from factory.django import DjangoModelFactory

from core.labs.models import (
    Bench,
    BenchGroup,
    ComputingEquipment,
    EquipmentCategory,
    EquipmentKind,
)
from core.users.tests.factories import GroupFactory, URSGroupFactory, UserFactory

__all__ = [
    "BenchFactory",
    "BenchGroupFactory",
    "ComputingEquipmentFactory",
    "EquipmentCategoryFactory",
    "EquipmentKindFactory",
    "GroupFactory",
    "LabComputerFactory",
    "URSGroupFactory",
    "UserFactory",
]


class BenchGroupFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Bench Group {n:04d}")

    class Meta:
        model = BenchGroup
        django_get_or_create = ("name",)


class BenchFactory(DjangoModelFactory):
    sku = factory.Sequence(lambda n: f"BENCH-{n:05d}")
    name = factory.Sequence(lambda n: f"Bench {n:05d}")

    class Meta:
        model = Bench


class EquipmentCategoryFactory(DjangoModelFactory):
    name = factory.Sequence(lambda n: f"Category {n:04d}")
    definition = factory.LazyAttribute(lambda o: f"{o.name} equipment")

    class Meta:
        model = EquipmentCategory
        django_get_or_create = ("name",)


class EquipmentKindFactory(DjangoModelFactory):
    category = factory.SubFactory(EquipmentCategoryFactory)
    name = factory.Sequence(lambda n: f"Kind {n:04d}")

    class Meta:
        model = EquipmentKind
        django_get_or_create = ("category", "name")


def _computing_kind():
    category = EquipmentCategory.objects.filter(key="computing").first()
    if category is None:
        category = EquipmentCategoryFactory(name="Computing", key="computing")
    return EquipmentKindFactory(category=category, name="Workstation")


class ComputingEquipmentFactory(DjangoModelFactory):
    sku = factory.Sequence(lambda n: f"PC-{n:05d}")
    name = factory.Sequence(lambda n: f"Computer {n:05d}")
    kind = factory.LazyFunction(_computing_kind)

    class Meta:
        model = ComputingEquipment


# Legacy name kept for suites written before computers became equipment.
LabComputerFactory = ComputingEquipmentFactory
