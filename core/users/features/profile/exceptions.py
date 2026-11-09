"""Stable profile business errors. No HTTP concepts."""


class ProfileError(Exception):
    """Base class for profile feature errors."""


class AvatarNotFound(ProfileError):
    """The user has no avatar to act on."""


class UserNotFound(ProfileError):
    """The user does not exist or is outside the caller's scope.

    Scope misses return the same error as missing rows to avoid leaking existence.
    """


class AvatarInvalid(ProfileError):
    """The uploaded avatar violates size or type rules."""

    def __init__(self, errors: dict):
        super().__init__("Invalid avatar")
        self.errors = errors
