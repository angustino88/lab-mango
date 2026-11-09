"""Session restoration for Entra; deliberately cannot authenticate a password."""

from typing import Any

from django.contrib.auth.backends import ModelBackend
from django.http import HttpRequest


class EntraSessionBackend(ModelBackend):
    def authenticate(
        self,
        request: HttpRequest | None,
        username: str | None = None,
        password: str | None = None,
        **kwargs: Any,
    ) -> None:
        return None
