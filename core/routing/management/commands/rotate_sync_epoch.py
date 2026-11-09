"""Management command to rotate routing sync epoch."""

from django.core.management.base import BaseCommand, CommandError

from core.routing.application.publish import rotate_sync_epoch
from core.routing.exceptions import RoutingPublishError


class Command(BaseCommand):
    help = "Rotate the routing stream epoch to force consumer resynchronization."

    def add_arguments(self, parser):
        parser.add_argument(
            "--entity",
            choices=["users", "agents"],
            default=None,
            help="Stream entity type to rotate (default: all streams).",
        )

    def handle(self, *args, **options):
        entity = options.get("entity")
        try:
            results = rotate_sync_epoch(entity)
            for stream, epoch in results.items():
                self.stdout.write(self.style.SUCCESS(f"Rotated epoch for '{stream}': {epoch}"))
        except RoutingPublishError as exc:
            raise CommandError(str(exc)) from exc
