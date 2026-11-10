"""Database guards for booking approval and cancellation invariants (Booking.clean()).

Constraints are added NOT VALID: PostgreSQL enforces them for every new or updated row
without scanning or rejecting historical rows (e.g. cancellations recorded before
cancellation_reason was written). This keeps the deploy safe and lock-light. After checking
that no historical row violates them (queries in core/labs/models/docs/booking-model-conventions.md),
an owner may run, outside a migration:

    ALTER TABLE labs_benchbooking VALIDATE CONSTRAINT labs_benchbooking_cancellation_has_reason;

Django's migration state records the constraints exactly as declared on the models.
"""

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("labs", "0014_move_agent_routing_models_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AddConstraint(
                    model_name="benchbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("approval_status", "rejected"), _negated=True),
                            models.Q(("rejection_reason__regex", "^\\s*$"), _negated=True),
                            _connector="OR",
                        ),
                        name="labs_benchbooking_rejection_has_reason",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="benchbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("approval_status", "pending"), _negated=True),
                            ("approved_by__isnull", True),
                            _connector="OR",
                        ),
                        name="labs_benchbooking_pending_has_no_approver",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="benchbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("status", "cancelled"), _negated=True),
                            models.Q(("cancellation_reason__regex", "^\\s*$"), _negated=True),
                            _connector="OR",
                        ),
                        name="labs_benchbooking_cancellation_has_reason",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="equipmentbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("approval_status", "rejected"), _negated=True),
                            models.Q(("rejection_reason__regex", "^\\s*$"), _negated=True),
                            _connector="OR",
                        ),
                        name="labs_equipmentbooking_rejection_has_reason",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="equipmentbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("approval_status", "pending"), _negated=True),
                            ("approved_by__isnull", True),
                            _connector="OR",
                        ),
                        name="labs_equipmentbooking_pending_has_no_approver",
                    ),
                ),
                migrations.AddConstraint(
                    model_name="equipmentbooking",
                    constraint=models.CheckConstraint(
                        condition=models.Q(
                            models.Q(("status", "cancelled"), _negated=True),
                            models.Q(("cancellation_reason__regex", "^\\s*$"), _negated=True),
                            _connector="OR",
                        ),
                        name="labs_equipmentbooking_cancellation_has_reason",
                    ),
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_benchbooking" ADD CONSTRAINT "labs_benchbooking_rejection_has_reason" '
                        r"""CHECK ((NOT ("approval_status" = 'rejected') OR NOT ("rejection_reason"::text ~ E'^\\s*$'))) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_benchbooking" DROP CONSTRAINT IF EXISTS "labs_benchbooking_rejection_has_reason"',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_benchbooking" ADD CONSTRAINT "labs_benchbooking_pending_has_no_approver" '
                        r"""CHECK ((NOT ("approval_status" = 'pending') OR "approved_by_id" IS NULL)) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_benchbooking" DROP CONSTRAINT IF EXISTS "labs_benchbooking_pending_has_no_approver"',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_benchbooking" ADD CONSTRAINT "labs_benchbooking_cancellation_has_reason" '
                        r"""CHECK ((NOT ("status" = 'cancelled') OR NOT ("cancellation_reason"::text ~ E'^\\s*$'))) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_benchbooking" DROP CONSTRAINT IF EXISTS "labs_benchbooking_cancellation_has_reason"',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_equipmentbooking" ADD CONSTRAINT "labs_equipmentbooking_rejection_has_reason" '
                        r"""CHECK ((NOT ("approval_status" = 'rejected') OR NOT ("rejection_reason"::text ~ E'^\\s*$'))) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_equipmentbooking" DROP CONSTRAINT IF EXISTS "labs_equipmentbooking_rejection_has_reason"',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_equipmentbooking" ADD CONSTRAINT "labs_equipmentbooking_pending_has_no_approver" '
                        r"""CHECK ((NOT ("approval_status" = 'pending') OR "approved_by_id" IS NULL)) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_equipmentbooking" DROP CONSTRAINT IF EXISTS "labs_equipmentbooking_pending_has_no_approver"',
                ),
                migrations.RunSQL(
                    sql=(
                        'ALTER TABLE "labs_equipmentbooking" ADD CONSTRAINT "labs_equipmentbooking_cancellation_has_reason" '
                        r"""CHECK ((NOT ("status" = 'cancelled') OR NOT ("cancellation_reason"::text ~ E'^\\s*$'))) NOT VALID"""
                    ),
                    reverse_sql='ALTER TABLE "labs_equipmentbooking" DROP CONSTRAINT IF EXISTS "labs_equipmentbooking_cancellation_has_reason"',
                ),
            ],
        ),
    ]
