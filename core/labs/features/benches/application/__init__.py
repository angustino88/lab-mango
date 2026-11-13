"""Transactional bench commands."""

from core.labs.features.base.resource_image_commands import ResourceImageCommands
from core.labs.models import Bench

from .services import (
    add_favorite,
    change_bench_lifecycle,
    create_bench,
    delete_bench,
    place_bench,
    remove_favorite,
    retire_reference,
    save_reference,
    update_bench,
)

# Image use cases (replace/remove) for this resource; see core/labs/features/base/resource_image_commands.py.
bench_images = ResourceImageCommands(Bench)


__all__ = [
    "bench_images",
    "add_favorite",
    "change_bench_lifecycle",
    "create_bench",
    "delete_bench",
    "place_bench",
    "remove_favorite",
    "retire_reference",
    "save_reference",
    "update_bench",
]
