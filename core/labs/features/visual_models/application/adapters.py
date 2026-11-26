import logging
from uuid import uuid4

from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

logger = logging.getLogger(__name__)


class DjangoModelStorage:
    def save(self, content: bytes) -> str:
        return default_storage.save(f"visual_models/{uuid4().hex}.glb", ContentFile(content))

    def delete(self, name: str) -> None:
        try:
            default_storage.delete(name)
        except Exception:
            logger.exception("Failed to clean up an unreferenced 3D model")
