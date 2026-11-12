from django.core.management.base import BaseCommand
from django.utils import timezone

from core.users.models import EntraLoginNonce


class Command(BaseCommand):
    help = "Delete used login nonces past their expiry. Schedule periodically; no account data is deleted."

    def handle(self, *args, **options):
        count, _ = EntraLoginNonce.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"Deleted {count} expired login nonces.")
