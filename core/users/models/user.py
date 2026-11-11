from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import BooleanField, CharField
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _
from model_utils.fields import MonitorField

from core.infrastructure.storage.uploads import ResourceImageUploadPath


class User(AbstractUser):
    """Custom user model for LabMango."""

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    ACCOUNT_TYPE_PROVIDER = "PROVIDER"
    ACCOUNT_TYPE_STAFF = "STAFF"
    ACCOUNT_TYPE_CUSTOMER = "CUSTOMER"

    class AccountType(models.TextChoices):
        PROVIDER = "PROVIDER", _("Platform Provider")
        STAFF = "STAFF", _("Platform Staff")
        CUSTOMER = "CUSTOMER", _("Customer")

    class Presence(models.TextChoices):
        ONLINE = "ONLINE", _("Online")
        OFFLINE = "OFFLINE", _("Offline")

    # Compatibility fields: classification is not permission; presence is not account lifecycle.
    ACCOUNT_TYPE = AccountType.choices
    STATUS = Presence.choices
    status = CharField(_("status"), max_length=100, choices=Presence.choices, default=OFFLINE)
    status_changed = MonitorField(_("status changed"), monitor="status")
    account_type = CharField(
        _("Account Type"),
        max_length=100,
        choices=AccountType.choices,
        default=ACCOUNT_TYPE_CUSTOMER,
    )
    name = CharField(_("Name of User"), blank=True, max_length=255)
    display_name = CharField(max_length=255, blank=True)
    department = CharField(max_length=255, blank=True)
    is_urs_managed = BooleanField(default=True)
    avatar = models.ImageField(
        upload_to=ResourceImageUploadPath("avatars/"),
        blank=True,
        null=True,
    )

    class Meta(AbstractUser.Meta):
        constraints = [
            # URS and Entra match usernames case-insensitively; two accounts differing only in case
            # would make that match ambiguous.
            models.UniqueConstraint(Lower("username"), name="users_user_username_ci_unique"),
            models.CheckConstraint(
                condition=models.Q(account_type__in=["PROVIDER", "STAFF", "CUSTOMER"]),
                name="users_user_valid_account_type",
            ),
            models.CheckConstraint(
                condition=models.Q(status__in=["ONLINE", "OFFLINE"]),
                name="users_user_valid_presence",
            ),
        ]

    def get_absolute_url(self) -> str:
        from django.urls import reverse

        return reverse("users:detail", kwargs={"username": self.username})
