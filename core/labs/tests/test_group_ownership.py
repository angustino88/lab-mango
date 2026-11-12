"""Resource ownership: Department -> Group, and a resource's group must belong to its department."""

import pytest
from django.core.exceptions import ValidationError

from core.labs.models import Bench, Department, Group

pytestmark = pytest.mark.django_db


def test_groups_belong_to_a_department():
    eds = Department.objects.create(name="EDS")
    eds1 = Group.objects.create(name="EDS1", department=eds)
    eds2 = Group.objects.create(name="EDS2", department=eds)

    assert list(eds.groups.order_by("name")) == [eds1, eds2]


def test_empty_department_is_filled_from_the_group():
    eds = Department.objects.create(name="EDS")
    bench = Bench(sku="BN-1", name="Bench 1", group=Group.objects.create(name="EDS1", department=eds))

    bench.clean()

    assert bench.department_id == eds.pk


def test_group_from_another_department_is_rejected_on_the_group_field():
    eds, ads = Department.objects.create(name="EDS"), Department.objects.create(name="ADS")
    bench = Bench(sku="BN-2", name="Bench 2", department=ads, group=Group.objects.create(name="EDS1", department=eds))

    with pytest.raises(ValidationError) as error:
        bench.clean()

    assert error.value.message_dict == {"group": ["The group belongs to a different department."]}
