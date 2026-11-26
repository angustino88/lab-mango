"""Reference 3D models built in code: original, license-free GLB files used as catalog defaults.

Every model faces +Z (its front), stands on y = 0, is centred on x and z and is measured in metres. The bytes
are deterministic, so seeding twice finds the same asset by its sha256.
"""

import json
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

# name: (base colour RGBA, metallic, roughness, emissive RGB)
MATERIALS: dict[str, tuple[tuple[float, float, float, float], float, float, tuple[float, float, float]]] = {
    "frame": ((0.05, 0.06, 0.08, 1), 0.7, 0.45, (0, 0, 0)),
    "panel": ((0.10, 0.12, 0.15, 1), 0.6, 0.5, (0, 0, 0)),
    "cavity": ((0.02, 0.025, 0.03, 1), 0.2, 0.9, (0, 0, 0)),
    "rail": ((0.55, 0.58, 0.62, 1), 0.9, 0.3, (0, 0, 0)),
    "chrome": ((0.8, 0.82, 0.85, 1), 1.0, 0.2, (0, 0, 0)),
    "steel": ((0.62, 0.66, 0.7, 1), 0.8, 0.4, (0, 0, 0)),
    "light_grey": ((0.78, 0.8, 0.82, 1), 0.3, 0.55, (0, 0, 0)),
    "worktop": ((0.86, 0.85, 0.8, 1), 0.0, 0.6, (0, 0, 0)),
    "esd_mat": ((0.18, 0.32, 0.42, 1), 0.0, 0.85, (0, 0, 0)),
    "rubber": ((0.04, 0.04, 0.04, 1), 0.0, 0.95, (0, 0, 0)),
    "glass": ((0.2, 0.32, 0.4, 1), 0.1, 0.1, (0.02, 0.04, 0.05)),
    "screen": ((0.02, 0.08, 0.1, 1), 0.0, 0.25, (0.05, 0.45, 0.5)),
    "led_green": ((0.1, 0.9, 0.5, 1), 0.0, 0.4, (0.1, 0.9, 0.5)),
    "led_white": ((0.95, 0.95, 0.9, 1), 0.0, 0.4, (0.9, 0.9, 0.85)),
    "accent": ((0.15, 0.55, 0.85, 1), 0.2, 0.5, (0, 0, 0)),
    "bin_blue": ((0.2, 0.45, 0.8, 1), 0.0, 0.6, (0, 0, 0)),
    "bin_orange": ((0.9, 0.5, 0.15, 1), 0.0, 0.6, (0, 0, 0)),
    "socket": ((0.92, 0.92, 0.9, 1), 0.0, 0.6, (0, 0, 0)),
}

Vec = tuple[float, float, float]


@dataclass
class _Mesh:
    positions: list[Vec] = field(default_factory=list)
    normals: list[Vec] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


class Builder:
    """Collects boxes and cylinders, merged into one primitive per material."""

    def __init__(self) -> None:
        self.meshes: dict[str, _Mesh] = {}

    def _mesh(self, material: str) -> _Mesh:
        if material not in MATERIALS:
            raise KeyError(material)
        return self.meshes.setdefault(material, _Mesh())

    def box(self, material: str, centre: Vec, size: Vec) -> None:
        mesh = self._mesh(material)
        (cx, cy, cz), (sx, sy, sz) = centre, size
        x0, x1, y0, y1, z0, z1 = cx - sx / 2, cx + sx / 2, cy - sy / 2, cy + sy / 2, cz - sz / 2, cz + sz / 2
        faces = (
            ((0, 0, 1), ((x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))),
            ((0, 0, -1), ((x1, y0, z0), (x0, y0, z0), (x0, y1, z0), (x1, y1, z0))),
            ((1, 0, 0), ((x1, y0, z1), (x1, y0, z0), (x1, y1, z0), (x1, y1, z1))),
            ((-1, 0, 0), ((x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0))),
            ((0, 1, 0), ((x0, y1, z1), (x1, y1, z1), (x1, y1, z0), (x0, y1, z0))),
            ((0, -1, 0), ((x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))),
        )
        for normal, corners in faces:
            base = len(mesh.positions)
            mesh.positions.extend(corners)
            mesh.normals.extend([normal] * 4)
            mesh.indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))

    def cylinder(self, material: str, centre: Vec, radius: float, length: float, axis: str = "y", segments: int = 20):
        """A capped cylinder along ``axis`` ("x", "y" or "z")."""
        mesh = self._mesh(material)

        def orient(a: float, b: float, c: float) -> Vec:
            # (a, c) is the circle plane, b runs along the axis.
            local = {"y": (a, b, c), "x": (b, a, c), "z": (a, c, b)}[axis]
            return (centre[0] + local[0], centre[1] + local[1], centre[2] + local[2])

        def direction(a: float, b: float, c: float) -> Vec:
            return {"y": (a, b, c), "x": (b, a, c), "z": (a, c, b)}[axis]

        half = length / 2
        ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments)) for i in range(segments)]
        # Sides, with smooth normals.
        base = len(mesh.positions)
        for cos, sin in ring:
            mesh.positions.extend(
                (orient(radius * cos, -half, radius * sin), orient(radius * cos, half, radius * sin))
            )
            mesh.normals.extend((direction(cos, 0, sin),) * 2)
        for i in range(segments):
            a, b = base + 2 * i, base + 2 * ((i + 1) % segments)
            mesh.indices.extend((a, a + 1, b + 1, a, b + 1, b))
        # Caps.
        for sign in (-1, 1):
            centre_index = len(mesh.positions)
            mesh.positions.append(orient(0, sign * half, 0))
            mesh.normals.append(direction(0, sign, 0))
            for cos, sin in ring:
                mesh.positions.append(orient(radius * cos, sign * half, radius * sin))
                mesh.normals.append(direction(0, sign, 0))
            for i in range(segments):
                a, b = centre_index + 1 + i, centre_index + 1 + (i + 1) % segments
                mesh.indices.extend((centre_index, b, a) if sign > 0 else (centre_index, a, b))

    def glb(self, name: str) -> bytes:
        gltf: dict = {
            "asset": {"version": "2.0", "generator": "LabMango reference models"},
            "scene": 0,
            "scenes": [{"name": name, "nodes": [0]}],
            "nodes": [{"name": name, "mesh": 0}],
            "meshes": [{"name": name, "primitives": []}],
            "materials": [],
            "accessors": [],
            "bufferViews": [],
            "buffers": [],
        }
        blob = bytearray()

        def view(data: bytes, target: int) -> int:
            offset = len(blob)
            blob.extend(data)
            blob.extend(b"\0" * (-len(data) % 4))
            gltf["bufferViews"].append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
            return len(gltf["bufferViews"]) - 1

        for material in sorted(self.meshes):
            mesh = self.meshes[material]
            colour, metallic, roughness, emissive = MATERIALS[material]
            gltf["materials"].append(
                {
                    "name": material,
                    "pbrMetallicRoughness": {
                        "baseColorFactor": list(colour),
                        "metallicFactor": metallic,
                        "roughnessFactor": roughness,
                    },
                    **({"emissiveFactor": list(emissive)} if any(emissive) else {}),
                }
            )
            accessors = gltf["accessors"]
            positions = view(b"".join(struct.pack("<3f", *p) for p in mesh.positions), 34962)
            normals = view(b"".join(struct.pack("<3f", *n) for n in mesh.normals), 34962)
            indices = view(struct.pack(f"<{len(mesh.indices)}I", *mesh.indices), 34963)
            accessors.append(
                {
                    "bufferView": positions,
                    "componentType": 5126,
                    "count": len(mesh.positions),
                    "type": "VEC3",
                    "min": [round(min(p[k] for p in mesh.positions), 6) for k in range(3)],
                    "max": [round(max(p[k] for p in mesh.positions), 6) for k in range(3)],
                }
            )
            accessors.append(
                {"bufferView": normals, "componentType": 5126, "count": len(mesh.normals), "type": "VEC3"}
            )
            accessors.append(
                {"bufferView": indices, "componentType": 5125, "count": len(mesh.indices), "type": "SCALAR"}
            )
            gltf["meshes"][0]["primitives"].append(
                {
                    "attributes": {"POSITION": len(accessors) - 3, "NORMAL": len(accessors) - 2},
                    "indices": len(accessors) - 1,
                    "material": len(gltf["materials"]) - 1,
                }
            )
        gltf["buffers"].append({"byteLength": len(blob)})
        payload = json.dumps(gltf, separators=(",", ":"), sort_keys=True).encode()
        payload += b" " * (-len(payload) % 4)
        total = 12 + 8 + len(payload) + 8 + len(blob)
        return (
            struct.pack("<4sII", b"glTF", 2, total)
            + struct.pack("<II", len(payload), 0x4E4F534A)
            + payload
            + struct.pack("<II", len(blob), 0x004E4942)
            + bytes(blob)
        )


# --- Models ------------------------------------------------------------------------------------------------


def server_rack() -> Builder:
    """42U, 600 × 2000 × 1070 mm. Open front so mounted equipment shows; the dashboard draws the rails and
    units (7 % to 93 % of the height)."""
    b = Builder()
    w, h, d = 0.6, 2.0, 1.07
    b.box("frame", (0, 0.05, 0), (w, 0.1, d))  # plinth
    b.box("frame", (0, h - 0.05, 0), (w, 0.1, d))  # roof
    for x in (-1, 1):
        for z in (-1, 1):
            b.box("frame", (x * (w / 2 - 0.025), h / 2, z * (d / 2 - 0.025)), (0.05, h - 0.2, 0.05))
            b.cylinder("rubber", (x * (w / 2 - 0.06), 0.012, z * (d / 2 - 0.08)), 0.03, 0.024)
        b.box("panel", (x * (w / 2 - 0.008), h / 2, 0), (0.016, h - 0.2, d - 0.1))  # side panels
        b.box("rail", (x * (w / 2 - 0.0005), h / 2, d / 2 - 0.2), (0.002, 0.5, 0.012))  # side latch
    b.box("cavity", (0, h / 2, -d / 2 + 0.2), (w - 0.06, h - 0.2, 0.01))  # dark interior
    # Rear perforated door.
    b.box("panel", (0, h / 2, -d / 2 + 0.008), (w - 0.06, h - 0.24, 0.016))
    for i in range(14):
        b.box("cavity", (-0.21 + i * 0.0323, h / 2, -d / 2 - 0.001), (0.012, h - 0.4, 0.004))
    # Front: door frame stiles and a top status bar.
    b.box("frame", (0, h - 0.13, d / 2 - 0.02), (w, 0.06, 0.04))
    b.box("frame", (0, 0.13, d / 2 - 0.02), (w, 0.06, 0.04))
    b.box("led_white", (0, h - 0.13, d / 2 + 0.001), (w * 0.6, 0.012, 0.004))
    # Roof fans and cable entry.
    for x in (-0.13, 0.13):
        b.cylinder("cavity", (x, h + 0.003, -0.15), 0.1, 0.006)
        b.cylinder("rail", (x, h + 0.007, -0.15), 0.03, 0.004)
    b.box("rubber", (0, h + 0.002, 0.3), (0.3, 0.006, 0.08))
    return b


def lab_workbench() -> Builder:
    """1800 × 1750 × 850 mm, worktop at 900 mm, with an upper shelf, power rail and task light."""
    b = Builder()
    w, d, top = 1.8, 0.85, 0.9
    for x in (-1, 1):
        for z in (-1, 1):
            b.box("light_grey", (x * (w / 2 - 0.05), (top - 0.04) / 2, z * (d / 2 - 0.05)), (0.05, top - 0.04, 0.05))
            b.cylinder("rubber", (x * (w / 2 - 0.05), 0.01, z * (d / 2 - 0.05)), 0.03, 0.02)
        b.box("light_grey", (x * (w / 2 - 0.05), 0.15, 0), (0.04, 0.04, d - 0.1))  # side stretchers
    b.box("light_grey", (0, 0.15, -(d / 2 - 0.05)), (w - 0.1, 0.04, 0.04))
    b.box("steel", (-0.2, 0.18, 0), (w - 0.55, 0.02, d - 0.15))  # lower shelf
    b.box("worktop", (0, top - 0.02, 0), (w, 0.04, d))
    b.box("rubber", (0, top - 0.02, d / 2 + 0.002), (w, 0.04, 0.004))  # edge band
    b.box("esd_mat", (0, top + 0.002, 0.02), (w - 0.1, 0.004, d - 0.16))
    b.box("led_green", (w / 2 - 0.1, top + 0.006, d / 2 - 0.1), (0.03, 0.006, 0.02))  # ESD ground point
    # Drawer pedestal.
    px = w / 2 - 0.3
    b.box("light_grey", (px, 0.45, 0.02), (0.45, 0.78, d - 0.14))
    for i in range(3):
        y = 0.22 + i * 0.25
        b.box("panel", (px, y, d / 2 - 0.045), (0.42, 0.22, 0.01))
        b.box("chrome", (px, y + 0.06, d / 2 - 0.035), (0.18, 0.015, 0.015))
    # Uprights, upper shelf, power rail and task light.
    for x in (-1, 1):
        b.box("light_grey", (x * (w / 2 - 0.05), top + 0.42, -(d / 2 - 0.04)), (0.05, 0.84, 0.05))
    b.box("light_grey", (0, top + 0.82, -(d / 2 - 0.04)), (w, 0.04, 0.05))
    b.box("steel", (0, top + 0.55, -(d / 2 - 0.18)), (w - 0.06, 0.025, 0.3))
    b.box("led_white", (0, top + 0.53, -(d / 2 - 0.25)), (w - 0.3, 0.015, 0.03))
    b.box("panel", (0, top + 0.12, -(d / 2 - 0.05)), (w - 0.2, 0.07, 0.05))
    for i in range(8):
        b.box("socket", (-0.7 + i * 0.2, top + 0.12, -(d / 2 - 0.077)), (0.06, 0.045, 0.004))
    return b


def storage_cabinet() -> Builder:
    """1000 × 1950 × 500 mm two-door cabinet with glazed upper doors."""
    b = Builder()
    w, h, d = 1.0, 1.95, 0.5
    b.box("light_grey", (0, h / 2 + 0.03, 0), (w, h - 0.06, d))
    b.box("rubber", (0, 0.03, 0), (w - 0.04, 0.06, d - 0.04))  # plinth
    for x in (-1, 1):
        cx = x * (w / 4 + 0.002)
        b.box("light_grey", (cx, h * 0.3, d / 2 + 0.01), (w / 2 - 0.012, h * 0.48, 0.02))  # lower door
        b.box("light_grey", (cx, h * 0.76, d / 2 + 0.01), (w / 2 - 0.012, h * 0.42, 0.02))  # upper door
        b.box("glass", (cx, h * 0.76, d / 2 + 0.021), (w / 2 - 0.1, h * 0.34, 0.004))
        b.box("chrome", (x * 0.04, h * 0.52, d / 2 + 0.035), (0.015, 0.22, 0.015))  # handles
        b.box("panel", (cx, h * 0.45, d / 2 + 0.021), (0.12, 0.04, 0.002))  # label holder
    for i in range(3):
        b.box("steel", (0, h * (0.62 + i * 0.12), 0), (w - 0.04, 0.015, d - 0.06))  # shelves behind glass
    return b


def storage_shelving() -> Builder:
    """1200 × 1800 × 500 mm steel shelving with five shelves and storage bins."""
    b = Builder()
    w, h, d = 1.2, 1.8, 0.5
    for x in (-1, 1):
        for z in (-1, 1):
            b.box("steel", (x * (w / 2 - 0.02), h / 2, z * (d / 2 - 0.02)), (0.035, h, 0.035))
    levels = [0.08 + i * (h - 0.12) / 4 for i in range(5)]
    for y in levels:
        b.box("light_grey", (0, y, 0), (w - 0.02, 0.02, d - 0.02))
        b.box("light_grey", (0, y + 0.02, d / 2 - 0.01), (w - 0.02, 0.04, 0.01))  # front lip
    colours = ("bin_blue", "bin_orange", "bin_blue", "bin_blue", "bin_orange", "bin_blue")
    for level, y in enumerate(levels[:4]):
        for i in range(3):
            if (level + i) % 4 == 3:
                continue
            b.box(colours[(level + i) % len(colours)], (-0.38 + i * 0.38, y + 0.11, 0.02), (0.3, 0.2, d - 0.1))
            b.box("socket", (-0.38 + i * 0.38, y + 0.15, d / 2 - 0.079), (0.08, 0.03, 0.002))
    return b


def benchtop_instrument() -> Builder:
    """400 × 200 × 300 mm benchtop instrument (oscilloscope style): display, knobs and keys."""
    b = Builder()
    w, h, d = 0.4, 0.2, 0.3
    b.box("light_grey", (0, h / 2 + 0.01, 0), (w, h - 0.02, d))
    b.box("panel", (0, h / 2 + 0.01, d / 2 + 0.004), (w - 0.01, h - 0.03, 0.008))
    b.box("screen", (-0.06, h / 2 + 0.015, d / 2 + 0.009), (0.22, 0.13, 0.002))
    for row in range(3):
        for col in range(2):
            b.cylinder("rail", (0.1 + col * 0.06, 0.06 + row * 0.045, d / 2 + 0.016), 0.014, 0.016, axis="z")
    for i in range(6):
        b.box("socket", (-0.15 + i * 0.044, 0.025, d / 2 + 0.01), (0.03, 0.012, 0.006))
    for x in (-0.12, -0.04, 0.04, 0.12):
        b.cylinder("accent", (x, 0.025, d / 2 + 0.02), 0.008, 0.012, axis="z")  # BNC inputs
    b.box("led_green", (0.17, h - 0.03, d / 2 + 0.009), (0.008, 0.008, 0.002))
    for x in (-1, 1):
        for z in (-1, 1):
            b.box("rubber", (x * (w / 2 - 0.03), 0.005, z * (d / 2 - 0.03)), (0.03, 0.01, 0.03))
        b.box("panel", (x * (w / 2 + 0.006), h / 2 + 0.01, 0.0), (0.012, 0.04, d * 0.6))  # handle mounts
    return b


def computer_tower() -> Builder:
    """200 × 450 × 450 mm desktop computer."""
    b = Builder()
    w, h, d = 0.2, 0.45, 0.45
    b.box("frame", (0, h / 2 + 0.01, 0), (w, h - 0.02, d))
    b.box("panel", (0, h / 2 + 0.01, d / 2 + 0.005), (w - 0.01, h - 0.03, 0.01))
    for i in range(10):
        b.box("cavity", (0, 0.08 + i * 0.022, d / 2 + 0.011), (w - 0.06, 0.008, 0.002))
    b.cylinder("rail", (0, h - 0.05, d / 2 + 0.012), 0.012, 0.006, axis="z")
    b.box("led_white", (0, h - 0.075, d / 2 + 0.011), (0.03, 0.003, 0.002))
    b.box("rubber", (0, h - 0.03, d / 2 + 0.011), (0.05, 0.01, 0.002))  # USB ports
    b.box("glass", (w / 2 + 0.001, h / 2 + 0.02, 0), (0.002, h - 0.1, d - 0.08))  # side window
    for x in (-1, 1):
        for z in (-1, 1):
            b.box("rubber", (x * (w / 2 - 0.03), 0.005, z * (d / 2 - 0.04)), (0.03, 0.01, 0.04))
    return b


def monitor() -> Builder:
    """600 × 450 × 200 mm display on a stand."""
    b = Builder()
    b.box("frame", (0, 0.01, -0.01), (0.25, 0.02, 0.18))  # base
    b.box("frame", (0, 0.13, -0.06), (0.06, 0.24, 0.025))  # neck
    b.box("frame", (0, 0.29, -0.02), (0.6, 0.34, 0.03))  # panel
    b.box("screen", (0, 0.295, -0.004), (0.58, 0.32, 0.002))
    b.box("led_white", (0.27, 0.13, -0.004), (0.006, 0.004, 0.002))
    return b


@dataclass(frozen=True)
class ReferenceModel:
    key: str
    name: str
    build: Callable[[], Builder]
    surface: float = 1.0  # work-surface height as a fraction of model height


REFERENCE_MODELS: tuple[ReferenceModel, ...] = (
    ReferenceModel("server-rack", "Reference · Server rack 42U", server_rack),
    ReferenceModel("lab-workbench", "Reference · Lab workbench", lab_workbench, surface=round(0.904 / 1.74, 3)),
    ReferenceModel("storage-cabinet", "Reference · Storage cabinet", storage_cabinet),
    ReferenceModel("storage-shelving", "Reference · Storage shelving", storage_shelving),
    ReferenceModel("benchtop-instrument", "Reference · Benchtop instrument", benchtop_instrument),
    ReferenceModel("computer", "Reference · Desktop computer", computer_tower),
    ReferenceModel("monitor", "Reference · Monitor", monitor),
)


def build_glb(model: ReferenceModel) -> bytes:
    return model.build().glb(model.key)
