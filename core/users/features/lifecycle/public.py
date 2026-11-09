"""Public facade for user lifecycle writes owned by ``core.users``."""

from core.users.features.lifecycle.application import (
    bind_entra_identity,
    delete_user,
    replace_entra_identity,
    set_user_active,
    unlink_entra_identity,
)
from core.users.features.lifecycle.contracts import (
    BindEntraIdentityInput,
    DeleteUserInput,
    ReplaceEntraIdentityInput,
    SetUserActiveInput,
    UnlinkEntraIdentityInput,
    UserLifecycleResult,
)

__all__ = [
    "BindEntraIdentityInput",
    "DeleteUserInput",
    "ReplaceEntraIdentityInput",
    "SetUserActiveInput",
    "UnlinkEntraIdentityInput",
    "UserLifecycleResult",
    "bind_entra_identity",
    "delete_user",
    "replace_entra_identity",
    "set_user_active",
    "unlink_entra_identity",
]
