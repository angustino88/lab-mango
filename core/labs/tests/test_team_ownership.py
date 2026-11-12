"""Resource ownership: a resource's team must belong to its department (``ResourceModel.clean``)."""

import pytest
from django.core.exceptions import ValidationError

from core.labs.models import Bench, Department, Team

pytestmark = pytest.mark.django_db


def test_team_belongs_to_department_and_is_listed_on_it():
    validation = Department.objects.create(name="Validation")
    radar = Team.objects.create(name="Radar", department=validation)

    assert list(validation.teams.all()) == [radar]


def test_empty_department_is_filled_from_the_team():
    validation = Department.objects.create(name="Validation")
    bench = Bench(sku="BN-1", name="Bench 1", team=Team.objects.create(name="Radar", department=validation))

    bench.clean()

    assert bench.department_id == validation.pk


def test_team_from_another_department_is_rejected_on_the_team_field():
    validation, software = Department.objects.create(name="Validation"), Department.objects.create(name="Software")
    bench = Bench(
        sku="BN-2",
        name="Bench 2",
        department=software,
        team=Team.objects.create(name="Radar", department=validation),
    )

    with pytest.raises(ValidationError) as error:
        bench.clean()

    assert error.value.message_dict == {"team": ["The team belongs to a different department."]}
