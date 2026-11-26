"""Validate self-contained GLB v2 uploads before sending data to storage."""

import json
import struct

from .exceptions import InvalidModel

SUPPORTED_EXTENSIONS = frozenset(
    [
        "KHR_materials_unlit",
        "KHR_materials_clearcoat",
        "KHR_materials_transmission",
        "KHR_materials_volume",
        "KHR_materials_ior",
        "KHR_materials_specular",
        "KHR_materials_sheen",
        "KHR_materials_iridescence",
        "KHR_materials_anisotropy",
        "KHR_materials_emissive_strength",
        "KHR_texture_transform",
        "KHR_lights_punctual",
        # Compressed geometry and textures: the dashboard bundles these decoders (no CDN downloads).
        "KHR_draco_mesh_compression",
        "EXT_meshopt_compression",
        "KHR_mesh_quantization",
        "KHR_texture_basisu",
        "EXT_texture_webp",
    ]
)

MAX_BYTES = 15 * 1024 * 1024


def validate_glb(content: bytes) -> None:
    if len(content) > MAX_BYTES or len(content) < 20:
        raise InvalidModel("Use a GLB file up to 15 MB.")
    magic, version, length = struct.unpack_from("<4sII", content)
    if magic != b"glTF" or version != 2 or length != len(content):
        raise InvalidModel("The file must be a valid GLB version 2.")
    chunk_length, chunk_type = struct.unpack_from("<II", content, 12)
    if chunk_type != 0x4E4F534A or chunk_length % 4 or 20 + chunk_length > length:
        raise InvalidModel("The GLB JSON chunk is invalid.")
    try:
        data = json.loads(content[20 : 20 + chunk_length])
        if not isinstance(data, dict) or data.get("asset", {}).get("version") != "2.0":
            raise ValueError
        if set(data.get("extensionsRequired", [])) - SUPPORTED_EXTENSIONS:
            raise InvalidModel(
                "Use only supported glTF extensions: standard materials, Draco or Meshopt geometry, "
                "and PNG, JPEG, WebP or KTX2 textures."
            )
        for entry in [*data.get("buffers", []), *data.get("images", [])]:
            if entry.get("uri") and not entry["uri"].startswith("data:"):
                raise InvalidModel("Embed all textures and buffers in the GLB.")
        if not data.get("meshes"):
            raise InvalidModel("The model contains no meshes.")
    except (ValueError, TypeError, AttributeError, UnicodeDecodeError) as exc:
        raise InvalidModel("The GLB metadata is invalid.") from exc
