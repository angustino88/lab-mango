"""Bootstrap an explicitly verified identity through the trusted operator CLI."""

from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.users.models import User
from core.users.public import BindEntraIdentityInput, bind_entra_identity_from_operator


class Command(BaseCommand):
    help = "Bind an existing user to a verified Entra object ID. Never creates users or grants roles."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("object_id", type=UUID)

    def handle(self, *args, **options):
        try:
            with transaction.atomic():
                user = User.objects.select_for_update().get(username=options["username"])
                result = bind_entra_identity_from_operator(
                    data=BindEntraIdentityInput(
                        user_id=user.pk,
                        tenant_id=UUID(settings.AAD_TENANT_ID),
                        object_id=options["object_id"],
                    ),
                )
                if settings.ENTRA_SSO_ONLY and user.has_usable_password():
                    user.set_unusable_password()
                    user.save(update_fields=["password"])
        except User.DoesNotExist as exc:
            raise CommandError("The user must be provisioned before binding.") from exc
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS("Identity bound." if result.changed else "Identity already bound."))
