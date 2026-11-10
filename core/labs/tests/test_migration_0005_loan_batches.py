"""Existing loans become one-line loan slips that carry their borrower (labs 0005)."""

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.utils import timezone

BEFORE = [("labs", "0004_equipment_loan")]
AFTER = [("labs", "0005_equipment_loan_batch")]


@pytest.mark.django_db(transaction=True)
def test_each_existing_loan_gets_a_batch_with_its_borrower():
    executor = MigrationExecutor(connection)
    executor.migrate(BEFORE)
    apps = executor.loader.project_state(BEFORE).apps
    User = apps.get_model("users", "User")
    Category = apps.get_model("labs", "EquipmentCategory")
    Kind = apps.get_model("labs", "EquipmentKind")
    Equipment = apps.get_model("labs", "Equipment")
    Loan = apps.get_model("labs", "EquipmentLoan")
    kind = Kind.objects.create(category=Category.objects.create(name="Mig5", definition="Mig5"), name="Mig5 kind")
    borrower = User.objects.create(username="mig5-borrower")
    now = timezone.now()
    loan = Loan.objects.create(
        equipment=Equipment.objects.create(sku="MIG5-1", name="Item", kind=kind),
        borrower=borrower,
        handed_over_at=now,
        due_at=now + timezone.timedelta(days=1),
    )

    executor = MigrationExecutor(connection)
    executor.migrate(AFTER)
    apps = executor.loader.project_state(AFTER).apps
    migrated = apps.get_model("labs", "EquipmentLoan").objects.select_related("batch").get(pk=loan.pk)
    assert migrated.batch.borrower_id == borrower.pk

    executor = MigrationExecutor(connection)
    executor.migrate(executor.loader.graph.leaf_nodes())
