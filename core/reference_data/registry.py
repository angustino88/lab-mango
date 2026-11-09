from collections.abc import Iterable

from core.reference_data.declarations import ReferenceList

_REFERENCE_LISTS: dict[str, ReferenceList] = {}


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
