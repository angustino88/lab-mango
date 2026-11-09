"""Legacy command alias for generalized reference provisioning."""

from core.reference_data.management.commands.provision_reference_data import Command as ProvisionReferenceDataCommand


class Command(ProvisionReferenceDataCommand):
    """Backward-compatible alias for the shared reference-data command."""

    help = "Provision declared baseline reference data (legacy command alias)."
