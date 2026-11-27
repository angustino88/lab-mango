"""Add the built-in reference 3D models to the library and use them as catalog defaults."""

from typing import Any

from django.core.management.base import BaseCommand, CommandParser

from core.labs.features.visual_models.public import seed_reference_models


class Command(BaseCommand):
    help = (
        "Add the built-in reference 3D models (racks, benches, lab furniture, and embedded systems test "
        "equipment) to the model library, and set them as the default model of station types and equipment "
        "categories that have none. Idempotent; never replaces a model someone chose."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument(
            "--library-only", action="store_true", help="Add the models to the library without setting defaults."
        )

    def handle(self, *args: Any, **options: Any) -> None:
        report = seed_reference_models(assign_defaults=not options["library_only"])
        self.stdout.write(f"Added {len(report.created)} model(s); {len(report.existing)} already in the library.")
        for label, rows in (
            ("Station types", report.station_types),
            ("Equipment categories", report.equipment_categories),
            ("Product models", report.product_models),
        ):
            self.stdout.write(f"{label}: " + (", ".join(rows) if rows else "no new defaults"))
