from django.apps import AppConfig
from django.db.models.signals import post_migrate


class ReferenceDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.reference_data"
    label = "reference_data"
    verbose_name = "Reference data provisioning"

    def ready(self) -> None:
        from core.reference_data import signals

        post_migrate.connect(
            signals.provision_after_migrate,
            sender=self,
            dispatch_uid="reference_data.provision_after_migrate",
        )
