from collections.abc import Callable, Iterable

from core.reference_data.declarations import ReferenceList

ReferenceProvisioner = Callable[..., None]
"""Owner-supplied provisioning step called as ``provisioner(using=<alias>)``.

Use one only when a baseline cannot be expressed as a :class:`ReferenceList`, for example rows
linked to each other (a status workflow and its transitions). It must be idempotent.
"""

_REFERENCE_LISTS: dict[str, ReferenceList] = {}
_PROVISIONERS: dict[str, ReferenceProvisioner] = {}


def register_reference_lists(reference_lists: Iterable[ReferenceList]) -> None:
    """Register declarations from an owning app during Django app startup."""
    for reference_list in reference_lists:
        registered = _REFERENCE_LISTS.get(reference_list.key)
        if registered is not None and registered != reference_list:
            raise ValueError(f"Reference list key {reference_list.key!r} is registered more than once.")
        _REFERENCE_LISTS[reference_list.key] = reference_list


def get_registered_reference_lists() -> tuple[ReferenceList, ...]:
    """Return a stable snapshot of declarations registered by installed apps."""
    return tuple(_REFERENCE_LISTS[key] for key in sorted(_REFERENCE_LISTS))


def register_reference_provisioner(key: str, provisioner: ReferenceProvisioner) -> None:
    """Register an idempotent provisioning step from an owning app during Django app startup."""
    if not key.strip():
        raise ValueError("Reference provisioner key must not be empty.")
    registered = _PROVISIONERS.get(key)
    if registered is not None and registered is not provisioner:
        raise ValueError(f"Reference provisioner key {key!r} is registered more than once.")
    _PROVISIONERS[key] = provisioner


def get_registered_reference_provisioners() -> tuple[tuple[str, ReferenceProvisioner], ...]:
    """Return a stable snapshot of provisioning steps registered by installed apps."""
    return tuple((key, _PROVISIONERS[key]) for key in sorted(_PROVISIONERS))
