"""Django application configuration for core.agents."""

from django.apps import AppConfig


class AgentsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core.agents"
    verbose_name = "Agents"
