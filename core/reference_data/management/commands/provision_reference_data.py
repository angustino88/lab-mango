from django.core.management.base import BaseCommand
from django.db import DEFAULT_DB_ALIAS

from core.reference_data.provisioning import provision_registered_reference_data


class Command(BaseCommand):
    help = "Provision declared baseline reference data."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--database",
            default=DEFAULT_DB_ALIAS,
            help="Database alias to provision (default: %(default)s).",
        )

    def handle(self, *args, **options) -> None:
        provision_registered_reference_data(using=options["database"])

        self.stdout.write(self.style.SUCCESS("Declared reference data is provisioned."))
