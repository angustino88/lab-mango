from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import connections
from django.db.migrations.executor import MigrationExecutor
from django.db.models.signals import pre_delete
from django.dispatch import receiver

from core.reference_data.models import ProtectedReferenceMixin

AUTO_PROVISION_SETTING = "REFERENCE_DATA_AUTO_PROVISION"


@receiver(pre_delete, dispatch_uid="reference_data.protect_ensured_rows")
def prevent_protected_reference_cascade(*, instance, **kwargs) -> None:
    """Reject deletion collectors attempting to cascade through protected rows."""
    if isinstance(instance, ProtectedReferenceMixin):
        raise ValidationError("Protected reference data cannot be deleted through the ORM.")


def provision_after_migrate(sender, *, using: str, plan=None, verbosity: int = 1, stdout=None, **kwargs) -> None:
    """Provision baseline reference data once ``migrate`` has brought the database fully up to date.

    Connected for this app only, so it runs once per ``migrate`` call. It is skipped when the setting
    ``REFERENCE_DATA_AUTO_PROVISION`` is false (test settings), when the run unapplied migrations,
    and while any migration is still unapplied: provisioning needs every owning table to exist.
    ``provision_reference_data`` stays available for an explicit run.
    """
    if not getattr(settings, AUTO_PROVISION_SETTING, True):
        return
    if plan and any(backwards for _migration, backwards in plan):
        return
    executor = MigrationExecutor(connections[using])
    if executor.migration_plan(executor.loader.graph.leaf_nodes()):
        if verbosity >= 1 and stdout is not None:
            stdout.write("  Skipping reference data provisioning: the database has unapplied migrations.\n")
        return

    from core.reference_data.provisioning import provision_registered_reference_data

    provision_registered_reference_data(using=using)
    if verbosity >= 1 and stdout is not None:
        stdout.write("  Declared reference data is provisioned.\n")
