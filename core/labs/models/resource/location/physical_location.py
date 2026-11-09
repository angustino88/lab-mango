from __future__ import annotations

from collections.abc import Iterator
from typing import ClassVar, Self

from django.core.exceptions import ValidationError
from django.db import models


class LocationCycleError(ValueError):
    """Raised when a location's parent chain loops back on itself."""


class PhysicalLocationNode(models.Model):
    """
    Abstract base for hierarchical physical locations in the labs domain
    (lab -> rack -> chassis -> slot ...).

    Every subclass must implement ``get_location_parent()``. The path is built
    parent-first from each node's real-world display segment, for example:
    ``US-New York-HQ-3F-Lab A-Rack 01-Bench 02``.

    Override ``get_location_segment()`` when a model's real-world identifier
    cannot be represented by ``label``, ``sku``, or ``name``.
    """

    LOCATION_SEPARATOR: ClassVar[str] = "-"
    LOCATION_SEGMENT_FIELDS: ClassVar[tuple[str, ...]] = ("label", "sku", "name")
    MAX_LOCATION_DEPTH: ClassVar[int] = 32

    label = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Position within the parent location, e.g. R1C1 or U12.",
    )

    class Meta:
        abstract = True

    def get_location_parent(self) -> Self | None:
        """Return the parent location, or None for a root location."""
        raise NotImplementedError(
            f"{type(self).__name__} must implement get_location_parent()."
        )

    def get_location_segment(self) -> str | None:
        """Return this node's own piece of the path, or None if it has none."""
        for field_name in self.LOCATION_SEGMENT_FIELDS:
            value = getattr(self, field_name, None)
            if value:
                return str(value)
        return None

    def iter_location_ancestors(self) -> Iterator[PhysicalLocationNode]:
        """
        Yield ancestors nearest-first (parent, grandparent, ...).

        Raises:
            LocationCycleError: if the chain loops or exceeds MAX_LOCATION_DEPTH.
        """
        seen = {self._location_key()}
        node = self.get_location_parent()
        depth = 0

        while node is not None:
            depth += 1
            key = node._location_key()
            if key in seen or depth > self.MAX_LOCATION_DEPTH:
                raise LocationCycleError(
                    f"Invalid location hierarchy at {type(node).__name__} "
                    f"(pk={node.pk}): cycle or depth > {self.MAX_LOCATION_DEPTH}."
                )
            seen.add(key)
            yield node
            node = node.get_location_parent()

    def get_location_path(self) -> str:
        """Return the parent-first real-world path for this location."""
        nodes = [self, *self.iter_location_ancestors()]
        segments = (node.get_location_segment() for node in reversed(nodes))
        return self.LOCATION_SEPARATOR.join(s for s in segments if s)

    def get_location_string(self) -> str:
        """Return the API-facing display string for this physical location."""
        return self.get_location_path()

    def clean(self) -> None:
        super().clean()
        try:
            for _ in self.iter_location_ancestors():
                pass
        except LocationCycleError as exc:
            raise ValidationError(str(exc)) from exc

    def _location_key(self) -> tuple[str, object]:
        """Identity key that survives re-fetching the same row as a new instance."""
        if self.pk is None:
            return (self._meta.label, id(self))
        return (self._meta.concrete_model._meta.label, self.pk)
