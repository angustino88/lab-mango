from django.apps import AppConfig


class LabsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.labs"
    label = "labs"

    def ready(self) -> None:
        from core.labs.features.equipment.defaults import REFERENCE_LISTS
        from core.reference_data.registry import register_reference_lists

        register_reference_lists(REFERENCE_LISTS)

