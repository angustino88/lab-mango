from django.apps import AppConfig


class SupportDeskConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.support_desk"
    verbose_name = "Support Desk"

    def ready(self) -> None:
        from core.reference_data.registry import register_reference_provisioner
        from core.support_desk.features.tickets.defaults import (
            PROVISIONER_KEY,
            provision_support_desk_defaults,
        )

        register_reference_provisioner(PROVISIONER_KEY, provision_support_desk_defaults)
