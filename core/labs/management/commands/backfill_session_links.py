"""Fill access type and booking, bench and user links on session logs stored before they existed."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser

from core.labs.features.lab_sessions.public import resolve_session_links


class Command(BaseCommand):
    help = (
        "Fill access_type and the booking, bench and user links on session logs where access_type is "
        "empty. Batched, idempotent and safe to stop and rerun."
    )

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--batch-size", type=int, default=500, help="Rows per transaction (default 500).")
        parser.add_argument("--max-batches", type=int, default=None, help="Stop after this many batches.")

    def handle(self, *args: Any, **options: Any) -> None:
        batch_size: int = options["batch_size"]
        max_batches: int | None = options["max_batches"]
        if batch_size < 1 or (max_batches is not None and max_batches < 1):
            raise CommandError("--batch-size and --max-batches must be at least 1.")
        filled = resolve_session_links(batch_size=batch_size, max_batches=max_batches)
        self.stdout.write(f"Filled {filled} session log(s).")
