from django.apps import AppConfig
from django.utils.translation import gettext_lazy as _


class UsersConfig(AppConfig):
    name = "core.users"
    verbose_name = _("People and access")

    def ready(self):
        # Signal wiring is loaded if present. Other import errors must surface at startup.
        from importlib.util import find_spec

        from . import checks  # noqa: F401

        if find_spec("core.users.signals") is not None:
            import core.users.signals  # noqa: F401
