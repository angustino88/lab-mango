from django.apps import AppConfig


class ReferenceDataConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.reference_data"
    label = "reference_data"
    verbose_name = "Reference data provisioning"

    def ready(self) -> None:
        from core.reference_data import signals  # noqa: F401
