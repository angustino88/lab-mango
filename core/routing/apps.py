"""Django application configuration for core.routing."""

from django.apps import AppConfig


class RoutingConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.routing"
    verbose_name = "Routing"
