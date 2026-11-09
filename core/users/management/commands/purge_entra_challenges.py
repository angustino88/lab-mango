from django.core.management.base import BaseCommand
from django.utils import timezone

from core.users.models import EntraLoginChallenge


class Command(BaseCommand):
    help = "Delete expired login challenges. Schedule periodically; no account data is deleted."

    def handle(self, *args, **options):
        count, _ = EntraLoginChallenge.objects.filter(expires_at__lt=timezone.now()).delete()
        self.stdout.write(f"Deleted {count} expired challenges.")
