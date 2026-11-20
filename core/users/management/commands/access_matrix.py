from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.users.permissions import ACCESS_MATRIX_PATH, render_access_matrix


class Command(BaseCommand):
    help = "Write the Labs access matrix document from the permission registry, or check it is current."

    def add_arguments(self, parser):
        parser.add_argument("--check", action="store_true", help="Fail when the document is out of date.")

    def handle(self, *args, check: bool = False, **options):
        path = Path(settings.BASE_DIR) / ACCESS_MATRIX_PATH
        expected = render_access_matrix()
        if check:
            current = path.read_text(encoding="utf-8") if path.exists() else ""
            if current != expected:
                raise CommandError(f"{ACCESS_MATRIX_PATH} is out of date. Run: uv run python manage.py access_matrix")
            self.stdout.write(f"{ACCESS_MATRIX_PATH} is current.")
            return
        path.write_text(expected, encoding="utf-8")
        self.stdout.write(f"Wrote {ACCESS_MATRIX_PATH}.")
