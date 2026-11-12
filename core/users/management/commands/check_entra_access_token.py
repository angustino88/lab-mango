"""Check one Entra access token against this server's settings, the same way the scanner endpoints do."""

import json
import sys

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.users.public import diagnose_access_token


class Command(BaseCommand):
    help = (
        "Read one Microsoft Entra access token from stdin and report each check the audit-tool endpoints apply "
        "(issuer, audience, tenant, expiry, scope, signature, linked user). The token is never printed. "
        "Example: python manage.py check_entra_access_token < token.txt"
    )

    def handle(self, *args, **options):
        token = sys.stdin.read().strip()
        if token.lower().startswith("bearer "):
            token = token[7:].strip()
        if not token:
            raise CommandError("Pipe exactly one access token into stdin.")

        if not settings.ENTRA_API_ACCESS_TOKENS_ENABLED:
            self.stdout.write(
                self.style.WARNING("ENTRA_API_ACCESS_TOKENS_ENABLED is off: endpoints ignore these tokens.")
            )
        checks, claims = diagnose_access_token(token)
        self.stdout.write("Claims (selected): " + json.dumps(claims, sort_keys=True, default=str))
        for check in checks:
            mark = self.style.SUCCESS("PASS") if check.passed else self.style.ERROR("FAIL")
            self.stdout.write(f"{mark}  {check.name}: {check.detail}")
        if not all(check.passed for check in checks):
            raise CommandError("The token would be rejected.")
        self.stdout.write(self.style.SUCCESS("The token would be accepted."))
