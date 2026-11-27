"""Reference 3D models built in code: original, license-free GLB files used as catalog defaults.

Every model faces +Z (its front), stands on y = 0, is centred on x and z and is measured in metres. The bytes
are deterministic, so seeding twice finds the same asset by its sha256.
"""

import json
import math
import struct
from collections.abc import Callable
from dataclasses import dataclass, field

from . import textures

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
    "pcb_green": ((0.06, 0.36, 0.16, 1), 0.15, 0.45, (0, 0, 0)),
    "pcb_blue": ((0.08, 0.22, 0.48, 1), 0.15, 0.45, (0, 0, 0)),
    "copper": ((0.78, 0.45, 0.24, 1), 0.95, 0.28, (0, 0, 0)),
    "gold": ((0.88, 0.72, 0.25, 1), 0.95, 0.25, (0, 0, 0)),
    "chip_black": ((0.04, 0.045, 0.055, 1), 0.15, 0.55, (0, 0, 0)),
    "heatsink": ((0.18, 0.2, 0.24, 1), 0.85, 0.35, (0, 0, 0)),
    "yellow_safety": ((0.92, 0.74, 0.08, 1), 0.25, 0.45, (0, 0, 0)),
    "red_safety": ((0.84, 0.14, 0.14, 1), 0.2, 0.45, (0.06, 0.01, 0.01)),
    "led_amber": ((0.98, 0.65, 0.1, 1), 0.0, 0.35, (0.95, 0.55, 0.05)),
    "led_cyan": ((0.12, 0.85, 0.95, 1), 0.0, 0.35, (0.1, 0.78, 0.9)),
    "led_red": ((0.95, 0.18, 0.18, 1), 0.0, 0.35, (0.9, 0.12, 0.12)),
    "white_enclosure": ((0.88, 0.9, 0.92, 1), 0.2, 0.45, (0, 0, 0)),
    "dark_blue": ((0.08, 0.2, 0.38, 1), 0.35, 0.45, (0, 0, 0)),
    "wood_top": ((0.68, 0.52, 0.35, 1), 0.0, 0.65, (0, 0, 0)),
    "mesh_dark": ((0.07, 0.08, 0.1, 1), 0.5, 0.75, (0, 0, 0)),
    "vector_red": ((0.56, 0.014, 0.028, 1), 0.04, 0.58, (0.02, 0.0, 0.004)),
    "bezel_dark": ((0.032, 0.036, 0.044, 1), 0.32, 0.42, (0, 0, 0)),
    "lauterbach_white": ((0.84, 0.85, 0.87, 1), 0.06, 0.36, (0, 0, 0)),
    "aluminum_brushed": ((0.70, 0.73, 0.77, 1), 0.88, 0.30, (0, 0, 0)),
    "rack_beige": ((0.58, 0.57, 0.53, 1), 0.10, 0.56, (0, 0, 0)),
    "ecu_blue": ((0.44, 0.54, 0.74, 1), 0.58, 0.36, (0, 0, 0)),
    "usb_blue": ((0.015, 0.22, 0.72, 1), 0.08, 0.38, (0, 0, 0)),
    "green_terminal": ((0.03, 0.44, 0.11, 1), 0.12, 0.44, (0, 0, 0)),
    "yellow_terminal": ((0.82, 0.60, 0.02, 1), 0.12, 0.44, (0, 0, 0)),
    "red_terminal": ((0.54, 0.015, 0.02, 1), 0.12, 0.44, (0, 0, 0)),
    "fluke_yellow": ((0.86, 0.54, 0.012, 1), 0.03, 0.62, (0, 0, 0)),
    "segger_green": ((0.02, 0.44, 0.14, 1), 0.08, 0.42, (0, 0, 0)),
    "weller_teal": ((0.018, 0.22, 0.36, 1), 0.14, 0.44, (0, 0, 0)),
    "cast_aluminum": ((0.54, 0.58, 0.62, 1), 0.80, 0.40, (0, 0, 0)),
    "nucleo_white": ((0.90, 0.91, 0.92, 1), 0.06, 0.42, (0, 0, 0)),
    "phoenix_green": ((0.04, 0.38, 0.12, 1), 0.08, 0.48, (0, 0, 0)),
    "fakra_blue": ((0.03, 0.22, 0.64, 1), 0.08, 0.40, (0, 0, 0)),
}

Vec = tuple[float, float, float]
UV = tuple[float, float]


@dataclass
class _Mesh:
    positions: list[Vec] = field(default_factory=list)
    normals: list[Vec] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


@dataclass
class _TexturedMesh:
    png_bytes: bytes
    metallic: float = 0.05
    roughness: float = 0.45
    emissive: float = 0.0
    positions: list[Vec] = field(default_factory=list)
    normals: list[Vec] = field(default_factory=list)
    uvs: list[UV] = field(default_factory=list)
    indices: list[int] = field(default_factory=list)


def _rounded_rect_loop(w: float, h: float, r: float, corner_segs: int = 6) -> list[tuple[float, float, float, float]]:
    """Return CCW 2D loop of (u, v, nu, nv) points for a rounded rectangle centred at (0, 0)."""
    r = max(1e-5, min(r, w / 2 - 1e-5, h / 2 - 1e-5))
    hw, hh = w / 2 - r, h / 2 - r
    corners = (
        (hw, hh, 0.0, math.pi / 2),
        (-hw, hh, math.pi / 2, math.pi),
        (-hw, -hh, math.pi, 3 * math.pi / 2),
        (hw, -hh, 3 * math.pi / 2, 2 * math.pi),
    )
    pts: list[tuple[float, float, float, float]] = []
    for cx, cy, a0, a1 in corners:
        for s in range(corner_segs + 1):
            ang = a0 + (a1 - a0) * (s / corner_segs)
            ca, sa = math.cos(ang), math.sin(ang)
            pts.append((cx + r * ca, cy + r * sa, ca, sa))
    return pts


def _axis_frame(
    centre: Vec, axis: str
) -> tuple[Callable[[float, float, float], Vec], Callable[[float, float, float], Vec]]:
    """Right-handed (u, v, b) frame along axis ('x', 'y', or 'z') so CCW in (u, v) faces +b."""
    cx, cy, cz = centre
    if axis == "z":
        return (lambda u, v, b: (cx + u, cy + v, cz + b)), (lambda u, v, b: (u, v, b))
    if axis == "y":
        return (lambda u, v, b: (cx + u, cy + b, cz - v)), (lambda u, v, b: (u, b, -v))
    return (lambda u, v, b: (cx + b, cy + u, cz + v)), (lambda u, v, b: (b, u, v))


class Builder:
    """Collects boxes, rounded extrusions, collars, cylinders and textured decals into a single GLB v2."""

    def __init__(self) -> None:
        self.meshes: dict[str, _Mesh] = {}
        self.textured: dict[str, _TexturedMesh] = {}

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

    def beveled_box(self, material: str, centre: Vec, size: Vec, bevel: float = 0.002) -> None:
        """A box with subtle 45-degree edge chamfers on top/bottom rims for realistic specular highlights."""
        (cx, cy, cz), (sx, sy, sz) = centre, size
        bv = min(bevel, sx * 0.18, sy * 0.18, sz * 0.18)
        if bv <= 1e-5:
            self.box(material, centre, size)
            return
        mesh = self._mesh(material)
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        ihx, ihy, ihz = hx - bv, hy - bv, hz - bv

        def quad(a: Vec, b: Vec, c: Vec, d: Vec, n: Vec) -> None:
            base = len(mesh.positions)
            mesh.positions.extend((a, b, c, d))
            mesh.normals.extend((n, n, n, n))
            mesh.indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))

        # 6 main flat faces (inset by bevel).
        quad(
            (cx - ihx, cy - ihy, cz + hz),
            (cx + ihx, cy - ihy, cz + hz),
            (cx + ihx, cy + ihy, cz + hz),
            (cx - ihx, cy + ihy, cz + hz),
            (0, 0, 1),
        )
        quad(
            (cx + ihx, cy - ihy, cz - hz),
            (cx - ihx, cy - ihy, cz - hz),
            (cx - ihx, cy + ihy, cz - hz),
            (cx + ihx, cy + ihy, cz - hz),
            (0, 0, -1),
        )
        quad(
            (cx + hx, cy - ihy, cz + ihz),
            (cx + hx, cy - ihy, cz - ihz),
            (cx + hx, cy + ihy, cz - ihz),
            (cx + hx, cy + ihy, cz + ihz),
            (1, 0, 0),
        )
        quad(
            (cx - hx, cy - ihy, cz - ihz),
            (cx - hx, cy - ihy, cz + ihz),
            (cx - hx, cy + ihy, cz + ihz),
            (cx - hx, cy + ihy, cz - ihz),
            (-1, 0, 0),
        )
        quad(
            (cx - ihx, cy + hy, cz + ihz),
            (cx + ihx, cy + hy, cz + ihz),
            (cx + ihx, cy + hy, cz - ihz),
            (cx - ihx, cy + hy, cz - ihz),
            (0, 1, 0),
        )
        quad(
            (cx - ihx, cy - hy, cz - ihz),
            (cx + ihx, cy - hy, cz - ihz),
            (cx + ihx, cy - hy, cz + ihz),
            (cx - ihx, cy - hy, cz + ihz),
            (0, -1, 0),
        )
        # 12 chamfer strips connecting the faces.
        s = math.sqrt(0.5)
        # Top 4 chamfers.
        quad(
            (cx - ihx, cy + ihy, cz + hz),
            (cx + ihx, cy + ihy, cz + hz),
            (cx + ihx, cy + hy, cz + ihz),
            (cx - ihx, cy + hy, cz + ihz),
            (0, s, s),
        )
        quad(
            (cx + ihx, cy + ihy, cz - hz),
            (cx - ihx, cy + ihy, cz - hz),
            (cx - ihx, cy + hy, cz - ihz),
            (cx + ihx, cy + hy, cz - ihz),
            (0, s, -s),
        )
        quad(
            (cx + hx, cy + ihy, cz + ihz),
            (cx + hx, cy + ihy, cz - ihz),
            (cx + ihx, cy + hy, cz - ihz),
            (cx + ihx, cy + hy, cz + ihz),
            (s, s, 0),
        )
        quad(
            (cx - hx, cy + ihy, cz - ihz),
            (cx - hx, cy + ihy, cz + ihz),
            (cx - ihx, cy + hy, cz + ihz),
            (cx - ihx, cy + hy, cz - ihz),
            (-s, s, 0),
        )
        # Bottom 4 chamfers.
        quad(
            (cx - ihx, cy - hy, cz + ihz),
            (cx + ihx, cy - hy, cz + ihz),
            (cx + ihx, cy - ihy, cz + hz),
            (cx - ihx, cy - ihy, cz + hz),
            (0, -s, s),
        )
        quad(
            (cx + ihx, cy - hy, cz - ihz),
            (cx - ihx, cy - hy, cz - ihz),
            (cx - ihx, cy - ihy, cz - hz),
            (cx + ihx, cy - ihy, cz - hz),
            (0, -s, -s),
        )
        quad(
            (cx + ihx, cy - hy, cz + ihz),
            (cx + ihx, cy - hy, cz - ihz),
            (cx + hx, cy - ihy, cz - ihz),
            (cx + hx, cy - ihy, cz + ihz),
            (s, -s, 0),
        )
        quad(
            (cx - ihx, cy - hy, cz - ihz),
            (cx - ihx, cy - hy, cz + ihz),
            (cx - hx, cy - ihy, cz + ihz),
            (cx - hx, cy - ihy, cz - ihz),
            (-s, -s, 0),
        )
        # Vertical 4 chamfers.
        quad(
            (cx + ihx, cy - ihy, cz + hz),
            (cx + hx, cy - ihy, cz + ihz),
            (cx + hx, cy + ihy, cz + ihz),
            (cx + ihx, cy + ihy, cz + hz),
            (s, 0, s),
        )
        quad(
            (cx + hx, cy - ihy, cz - ihz),
            (cx + ihx, cy - ihy, cz - hz),
            (cx + ihx, cy + ihy, cz - hz),
            (cx + hx, cy + ihy, cz - ihz),
            (s, 0, -s),
        )
        quad(
            (cx - ihx, cy - ihy, cz - hz),
            (cx - hx, cy - ihy, cz - ihz),
            (cx - hx, cy + ihy, cz - ihz),
            (cx - ihx, cy + ihy, cz - hz),
            (-s, 0, -s),
        )
        quad(
            (cx - hx, cy - ihy, cz + ihz),
            (cx - ihx, cy - ihy, cz + hz),
            (cx - ihx, cy + ihy, cz + hz),
            (cx - hx, cy + ihy, cz + ihz),
            (-s, 0, s),
        )

    def rounded_box(
        self,
        material: str,
        centre: Vec,
        size: Vec,
        radius: float,
        *,
        axis: str = "z",
        corner_segs: int = 6,
    ) -> None:
        """Extrude a rounded-rectangle cross-section along axis ('x', 'y' or 'z')."""
        mesh = self._mesh(material)
        sx, sy, sz = size
        if axis == "z":
            pw, ph, length = sx, sy, sz
        elif axis == "y":
            pw, ph, length = sx, sz, sy
        else:
            pw, ph, length = sy, sz, sx
        orient, direction = _axis_frame(centre, axis)
        loop = _rounded_rect_loop(pw, ph, radius, corner_segs)
        half = length / 2
        n = len(loop)
        # Smooth extruded walls.
        base = len(mesh.positions)
        for u, v, nu, nv in loop:
            mesh.positions.extend((orient(u, v, -half), orient(u, v, half)))
            mesh.normals.extend((direction(nu, nv, 0.0),) * 2)
        for i in range(n):
            a, b = base + 2 * i, base + 2 * ((i + 1) % n)
            mesh.indices.extend((a, b, b + 1, a, b + 1, a + 1))
        # Flat end caps.
        for sign in (-1.0, 1.0):
            ci = len(mesh.positions)
            nrm = direction(0.0, 0.0, sign)
            mesh.positions.append(orient(0.0, 0.0, sign * half))
            mesh.normals.append(nrm)
            for u, v, _, _ in loop:
                mesh.positions.append(orient(u, v, sign * half))
                mesh.normals.append(nrm)
            for i in range(n):
                a, b = ci + 1 + i, ci + 1 + ((i + 1) % n)
                mesh.indices.extend((ci, a, b) if sign > 0 else (ci, b, a))

    def rounded_collar(
        self,
        material: str,
        centre: Vec,
        outer_size: Vec,
        wall: float,
        radius: float,
        *,
        axis: str = "z",
        corner_segs: int = 6,
    ) -> None:
        """Hollow rounded-rectangle bumper ring (e.g. Vector crimson rubber protective collars)."""
        mesh = self._mesh(material)
        sx, sy, sz = outer_size
        if axis == "z":
            ow, oh, length = sx, sy, sz
        elif axis == "y":
            ow, oh, length = sx, sz, sy
        else:
            ow, oh, length = sy, sz, sx
        orient, direction = _axis_frame(centre, axis)
        outer = _rounded_rect_loop(ow, oh, radius, corner_segs)
        inner = _rounded_rect_loop(ow - 2 * wall, oh - 2 * wall, max(0.001, radius - wall), corner_segs)
        half = length / 2
        n = len(outer)
        # Outer wall.
        base = len(mesh.positions)
        for u, v, nu, nv in outer:
            mesh.positions.extend((orient(u, v, -half), orient(u, v, half)))
            mesh.normals.extend((direction(nu, nv, 0.0),) * 2)
        for i in range(n):
            a, b = base + 2 * i, base + 2 * ((i + 1) % n)
            mesh.indices.extend((a, b, b + 1, a, b + 1, a + 1))
        # Inner wall (reversed winding & inverted normals).
        base_in = len(mesh.positions)
        for u, v, nu, nv in inner:
            mesh.positions.extend((orient(u, v, -half), orient(u, v, half)))
            mesh.normals.extend((direction(-nu, -nv, 0.0),) * 2)
        for i in range(n):
            a, b = base_in + 2 * i, base_in + 2 * ((i + 1) % n)
            mesh.indices.extend((a, a + 1, b + 1, a, b + 1, b))
        # Front (+half) and rear (-half) annular caps.
        for sign in (-1.0, 1.0):
            nrm = direction(0.0, 0.0, sign)
            cap_base = len(mesh.positions)
            for (ou, ov, _, _), (iu, iv, _, _) in zip(outer, inner, strict=True):
                mesh.positions.extend((orient(iu, iv, sign * half), orient(ou, ov, sign * half)))
                mesh.normals.extend((nrm, nrm))
            for i in range(n):
                a, b = cap_base + 2 * i, cap_base + 2 * ((i + 1) % n)
                if sign > 0:
                    mesh.indices.extend((a, a + 1, b + 1, a, b + 1, b))
                else:
                    mesh.indices.extend((a, b + 1, a + 1, a, b, b + 1))

    def decal(
        self,
        name: str,
        png_bytes: bytes,
        centre: Vec,
        width: float,
        height: float,
        *,
        face: str = "+z",
        rx: float = 0.0,
        metallic: float = 0.05,
        roughness: float = 0.45,
        emissive: float = 0.0,
    ) -> None:
        """Add a UV-mapped PNG faceplate/LCD quad embedded directly into the GLB binary chunk."""
        tm = self.textured.setdefault(
            name, _TexturedMesh(png_bytes=png_bytes, metallic=metallic, roughness=roughness, emissive=emissive)
        )
        cx, cy, cz = centre
        hw, hh = width / 2, height / 2
        if face == "+z":
            local_corners: tuple[Vec, Vec, Vec, Vec] = ((-hw, -hh, 0.0), (hw, -hh, 0.0), (hw, hh, 0.0), (-hw, hh, 0.0))
            nrm: Vec = (0.0, 0.0, 1.0)
        elif face == "-z":
            local_corners = ((hw, -hh, 0.0), (-hw, -hh, 0.0), (-hw, hh, 0.0), (hw, hh, 0.0))
            nrm = (0.0, 0.0, -1.0)
        elif face == "+y":
            # Image top -> -Z (rear), image bottom -> +Z (front facing viewer).
            local_corners = ((-hw, 0.0, hh), (hw, 0.0, hh), (hw, 0.0, -hh), (-hw, 0.0, -hh))
            nrm = (0.0, 1.0, 0.0)
        elif face == "+x":
            local_corners = ((0.0, -hh, hw), (0.0, -hh, -hw), (0.0, hh, -hw), (0.0, hh, hw))
            nrm = (1.0, 0.0, 0.0)
        else:
            raise ValueError(f"Unsupported decal face: {face}")
        if rx != 0.0:
            cr, sr = math.cos(rx), math.sin(rx)
            corners = tuple((cx + x, cy + y * cr - z * sr, cz + y * sr + z * cr) for x, y, z in local_corners)
            nrm = (nrm[0], nrm[1] * cr - nrm[2] * sr, nrm[1] * sr + nrm[2] * cr)
        else:
            corners = tuple((cx + x, cy + y, cz + z) for x, y, z in local_corners)
        base = len(tm.positions)
        tm.positions.extend(corners)
        tm.normals.extend((nrm,) * 4)
        tm.uvs.extend(((0.0, 1.0), (1.0, 1.0), (1.0, 0.0), (0.0, 0.0)))
        tm.indices.extend((base, base + 1, base + 2, base, base + 2, base + 3))

    def rotated_cylinder(
        self,
        material: str,
        centre: Vec,
        radius: float,
        length: float,
        *,
        rx: float = 0.0,
        ry: float = 0.0,
        rz: float = 0.0,
        segments: int = 16,
    ) -> None:
        """A Y-axis capped cylinder rotated around its centre by Euler angles (radians, XYZ order)."""
        mesh = self._mesh(material)
        cx, cy, cz = centre
        cxr, sxr = math.cos(rx), math.sin(rx)
        cyr, syr = math.cos(ry), math.sin(ry)
        czr, szr = math.cos(rz), math.sin(rz)

        def rot(v: Vec) -> Vec:
            x, y, z = v
            y, z = y * cxr - z * sxr, y * sxr + z * cxr
            x, z = x * cyr + z * syr, -x * syr + z * cyr
            x, y = x * czr - y * szr, x * szr + y * czr
            return (x, y, z)

        half = length / 2
        ring = [(math.cos(2 * math.pi * i / segments), math.sin(2 * math.pi * i / segments)) for i in range(segments)]
        base = len(mesh.positions)
        for cos, sin in ring:
            p0 = rot((radius * cos, -half, radius * sin))
            p1 = rot((radius * cos, half, radius * sin))
            rn = rot((cos, 0.0, sin))
            mesh.positions.extend(((cx + p0[0], cy + p0[1], cz + p0[2]), (cx + p1[0], cy + p1[1], cz + p1[2])))
            mesh.normals.extend((rn, rn))
        for i in range(segments):
            a, b = base + 2 * i, base + 2 * ((i + 1) % segments)
            mesh.indices.extend((a, a + 1, b + 1, a, b + 1, b))
        for sign in (-1.0, 1.0):
            ci = len(mesh.positions)
            pc = rot((0.0, sign * half, 0.0))
            rn = rot((0.0, sign, 0.0))
            mesh.positions.append((cx + pc[0], cy + pc[1], cz + pc[2]))
            mesh.normals.append(rn)
            for cos, sin in ring:
                pr = rot((radius * cos, sign * half, radius * sin))
                mesh.positions.append((cx + pr[0], cy + pr[1], cz + pr[2]))
                mesh.normals.append(rn)
            for i in range(segments):
                a, b = ci + 1 + i, ci + 1 + (i + 1) % segments
                mesh.indices.extend((ci, b, a) if sign > 0 else (ci, a, b))

    def rotated_box(
        self,
        material: str,
        centre: Vec,
        size: Vec,
        *,
        rx: float = 0.0,
        ry: float = 0.0,
        rz: float = 0.0,
    ) -> None:
        """A box rotated around its centre by Euler angles (radians, XYZ order)."""
        mesh = self._mesh(material)
        (cx, cy, cz), (sx, sy, sz) = centre, size
        hx, hy, hz = sx / 2, sy / 2, sz / 2
        cxr, sxr = math.cos(rx), math.sin(rx)
        cyr, syr = math.cos(ry), math.sin(ry)
        czr, szr = math.cos(rz), math.sin(rz)

        def rot(v: Vec) -> Vec:
            x, y, z = v
            y, z = y * cxr - z * sxr, y * sxr + z * cxr
            x, z = x * cyr + z * syr, -x * syr + z * cyr
            x, y = x * czr - y * szr, x * szr + y * czr
            return (x, y, z)

        local_faces = (
            ((0.0, 0.0, 1.0), ((-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz))),
            ((0.0, 0.0, -1.0), ((hx, -hy, -hz), (-hx, -hy, -hz), (-hx, hy, -hz), (hx, hy, -hz))),
            ((1.0, 0.0, 0.0), ((hx, -hy, hz), (hx, -hy, -hz), (hx, hy, -hz), (hx, hy, hz))),
            ((-1.0, 0.0, 0.0), ((-hx, -hy, -hz), (-hx, -hy, hz), (-hx, hy, hz), (-hx, hy, -hz))),
            ((0.0, 1.0, 0.0), ((-hx, hy, hz), (hx, hy, hz), (hx, hy, -hz), (-hx, hy, -hz))),
            ((0.0, -1.0, 0.0), ((-hx, -hy, -hz), (hx, -hy, -hz), (hx, -hy, hz), (-hx, -hy, hz))),
        )
        for normal, corners in local_faces:
            rn = rot(normal)
            base = len(mesh.positions)
            for corner in corners:
                rxv, ryv, rzv = rot(corner)
                mesh.positions.append((cx + rxv, cy + ryv, cz + rzv))
            mesh.normals.extend([rn] * 4)
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

        def view(data: bytes, target: int | None = None) -> int:
            offset = len(blob)
            blob.extend(data)
            blob.extend(b"\0" * (-len(data) % 4))
            bv: dict = {"buffer": 0, "byteOffset": offset, "byteLength": len(data)}
            if target is not None:
                bv["target"] = target
            gltf["bufferViews"].append(bv)
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

        if self.textured:
            gltf["samplers"] = [{"magFilter": 9729, "minFilter": 9987, "wrapS": 33071, "wrapT": 33071}]
            gltf["images"] = []
            gltf["textures"] = []
            for tex_name in sorted(self.textured):
                tm = self.textured[tex_name]
                img_bv = view(tm.png_bytes)
                img_idx = len(gltf["images"])
                gltf["images"].append({"bufferView": img_bv, "mimeType": "image/png", "name": tex_name})
                tex_idx = len(gltf["textures"])
                gltf["textures"].append({"sampler": 0, "source": img_idx})
                mat_def: dict = {
                    "name": f"tex_{tex_name}",
                    "pbrMetallicRoughness": {
                        "baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                        "baseColorTexture": {"index": tex_idx},
                        "metallicFactor": tm.metallic,
                        "roughnessFactor": tm.roughness,
                    },
                }
                if tm.emissive > 0.0:
                    mat_def["emissiveTexture"] = {"index": tex_idx}
                    mat_def["emissiveFactor"] = [tm.emissive, tm.emissive, tm.emissive]
                gltf["materials"].append(mat_def)
                accessors = gltf["accessors"]
                pos_bv = view(b"".join(struct.pack("<3f", *p) for p in tm.positions), 34962)
                nrm_bv = view(b"".join(struct.pack("<3f", *n) for n in tm.normals), 34962)
                uv_bv = view(b"".join(struct.pack("<2f", *uv) for uv in tm.uvs), 34962)
                idx_bv = view(struct.pack(f"<{len(tm.indices)}I", *tm.indices), 34963)
                accessors.append(
                    {
                        "bufferView": pos_bv,
                        "componentType": 5126,
                        "count": len(tm.positions),
                        "type": "VEC3",
                        "min": [round(min(p[k] for p in tm.positions), 6) for k in range(3)],
                        "max": [round(max(p[k] for p in tm.positions), 6) for k in range(3)],
                    }
                )
                accessors.append(
                    {"bufferView": nrm_bv, "componentType": 5126, "count": len(tm.normals), "type": "VEC3"}
                )
                accessors.append({"bufferView": uv_bv, "componentType": 5126, "count": len(tm.uvs), "type": "VEC2"})
                accessors.append(
                    {"bufferView": idx_bv, "componentType": 5125, "count": len(tm.indices), "type": "SCALAR"}
                )
                gltf["meshes"][0]["primitives"].append(
                    {
                        "attributes": {
                            "POSITION": len(accessors) - 4,
                            "NORMAL": len(accessors) - 3,
                            "TEXCOORD_0": len(accessors) - 2,
                        },
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
    for fan_x in (-0.13, 0.13):
        b.cylinder("cavity", (fan_x, h + 0.003, -0.15), 0.1, 0.006)
        b.cylinder("rail", (fan_x, h + 0.007, -0.15), 0.03, 0.004)
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
    """261 × 104 × 304 mm 6.5-digit benchtop digital multimeter (Keysight 34461A / Fluke 8846A style)."""
    b = Builder()
    w, h, d = 0.261, 0.104, 0.304
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.025), 0.005, z * (d / 2 - 0.032)), (0.026, 0.010, 0.030), 0.004, axis="y"
            )
    body_h = h - 0.010
    body_cy = 0.010 + body_h / 2
    b.rounded_box("light_grey", (0, body_cy, -0.003), (w, body_h, d - 0.006), 0.009, axis="z", corner_segs=6)
    b.rounded_collar(
        "panel", (0, body_cy, d / 2 - 0.003), (w + 0.006, body_h + 0.006, 0.020), 0.007, 0.011, axis="z", corner_segs=6
    )
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.006, body_h - 0.006, 0.010), 0.007, axis="z")
    fz = d / 2 + 0.0045
    b.decal(
        "dmm_front",
        textures.tex_dmm_front(),
        (0, body_cy, fz),
        w - 0.010,
        body_h - 0.010,
        face="+z",
        metallic=0.08,
        roughness=0.40,
        emissive=0.42,
    )
    # 5 recessed 4mm safety banana input jacks (4W Sense HI/LO, Input HI/LO, 10A Fused).
    jacks = (
        (0.044, body_cy + 0.014, "red_terminal"),
        (0.076, body_cy + 0.014, "red_terminal"),
        (0.044, body_cy - 0.018, "bezel_dark"),
        (0.076, body_cy - 0.018, "bezel_dark"),
        (0.106, body_cy - 0.018, "red_terminal"),
    )
    for jx, jy, mat in jacks:
        b.cylinder(mat, (jx, jy, fz + 0.0045), 0.0068, 0.009, axis="z", segments=14)
        b.cylinder("cavity", (jx, jy, fz + 0.0092), 0.0040, 0.0015, axis="z", segments=12)
        b.cylinder("gold", (jx, jy, fz + 0.0085), 0.0018, 0.0025, axis="z", segments=10)
    # Side cooling slots & rear IEC/LAN/GPIB bay.
    for side in (-1, 1):
        for i in range(4):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.032 + i * 0.014, -0.02), (0.002, 0.005, 0.14))
    b.box("bezel_dark", (-0.06, body_cy, -d / 2 - 0.002), (0.032, 0.024, 0.004))
    b.box("chrome", (0.055, body_cy, -d / 2 - 0.003), (0.050, 0.022, 0.006))
    return b


def computer_tower() -> Builder:
    """200 × 450 × 450 mm engineering workstation tower with mesh intake bezel & brushed aluminum trim."""
    b = Builder()
    w, h, d = 0.20, 0.45, 0.45
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.028), 0.006, z * (d / 2 - 0.042)), 0.015, 0.012)
    # Beveled matte-black anodized workstation chassis.
    b.beveled_box("bezel_dark", (0, h / 2 + 0.006, 0), (w, h - 0.012, d), bevel=0.006)
    # Brushed aluminum front frame rim & textured ventilation/IO bezel.
    b.rounded_box(
        "aluminum_brushed", (0, h / 2 + 0.006, d / 2 + 0.004), (w - 0.008, h - 0.022, 0.009), 0.010, axis="z"
    )
    b.decal(
        "ws_front",
        textures.tex_workstation_front(),
        (0, h / 2 + 0.006, d / 2 + 0.009),
        w - 0.016,
        h - 0.030,
        face="+z",
        metallic=0.25,
        roughness=0.52,
    )
    # Recessed dark tinted side panel with aluminum trim & internal heatsink/GPU silhouette.
    b.box("cavity", (w / 2 - 0.004, h / 2 + 0.012, -0.01), (0.008, h - 0.09, d - 0.09))
    b.box("aluminum_brushed", (w / 2 + 0.0005, h / 2 + 0.012, -0.01), (0.002, h - 0.082, d - 0.082))
    b.box("glass", (w / 2 + 0.0018, h / 2 + 0.012, -0.01), (0.002, h - 0.096, d - 0.096))
    # Rear exhaust fan grille & PSU bay.
    b.cylinder("cavity", (0, h - 0.11, -d / 2 - 0.001), 0.052, 0.004, axis="z")
    b.box("panel", (0, 0.065, -d / 2 - 0.002), (w - 0.04, 0.085, 0.004))
    return b


def monitor() -> Builder:
    """610 × 455 × 200 mm 27-inch engineering display with sculpted aluminum stand & dark IDE screen."""
    b = Builder()
    # Sculpted brushed-aluminum pedestal base resting flush on y = 0.
    b.rounded_box("aluminum_brushed", (0, 0.007, 0.005), (0.27, 0.014, 0.19), 0.016, axis="y")
    b.box("rubber", (0, 0.0015, 0.005), (0.25, 0.003, 0.17))
    # Tapered aluminum vertical stand column with cable-routing cutout detail.
    b.rotated_box("aluminum_brushed", (0, 0.155, -0.058), (0.056, 0.29, 0.018), rx=-0.08)
    b.box("cavity", (0, 0.085, -0.052), (0.022, 0.055, 0.022))  # cable pass-through hole
    b.box("bezel_dark", (0, 0.295, -0.036), (0.11, 0.10, 0.028))  # VESA mounting hub
    # Ultra-slim rounded-corner display housing with micro-bezel & silver bottom chin.
    pw, ph = 0.61, 0.355
    b.rounded_box("bezel_dark", (0, 0.295, -0.012), (pw, ph, 0.020), 0.008, axis="z")
    b.box("aluminum_brushed", (0, 0.295 - ph / 2 + 0.006, -0.001), (pw - 0.014, 0.010, 0.003))
    b.decal(
        "mon_screen",
        textures.tex_monitor_screen(),
        (0, 0.299, -0.0015),
        pw - 0.018,
        ph - 0.024,
        face="+z",
        metallic=0.05,
        roughness=0.22,
        emissive=0.45,
    )
    b.box("led_white", (pw / 2 - 0.032, 0.295 - ph / 2 + 0.006, 0.001), (0.008, 0.0025, 0.001))
    return b


# --- Embedded systems lab components -----------------------------------------------------------------------


def dc_power_supply() -> Builder:
    """280 × 165 × 360 mm Keysight E36312A-style triple-output programmable benchtop DC power supply."""
    b = Builder()
    w, h, d = 0.28, 0.165, 0.36
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.028), 0.006, z * (d / 2 - 0.036)), (0.028, 0.012, 0.034), 0.004, axis="y"
            )
    body_h = h - 0.012
    body_cy = 0.012 + body_h / 2
    b.rounded_box("light_grey", (0, body_cy, -0.004), (w, body_h, d - 0.008), 0.011, axis="z", corner_segs=6)
    b.rounded_collar(
        "panel", (0, body_cy, d / 2 - 0.004), (w + 0.006, body_h + 0.006, 0.022), 0.008, 0.013, axis="z", corner_segs=6
    )
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.006, body_h - 0.006, 0.012), 0.008, axis="z")
    fz = d / 2 + 0.0055
    b.decal(
        "keysight_psu_front",
        textures.tex_keysight_psu_front(),
        (0, body_cy, fz),
        w - 0.010,
        body_h - 0.010,
        face="+z",
        metallic=0.08,
        roughness=0.40,
        emissive=0.40,
    )
    # Twin tactile Voltage & Current rotary encoders aligned with front decal rings.
    for kx in (0.044, 0.088):
        b.cylinder("rubber", (kx, body_cy + 0.024, fz + 0.008), 0.0135, 0.016, axis="z", segments=18)
        b.cylinder("aluminum_brushed", (kx, body_cy + 0.024, fz + 0.0165), 0.010, 0.003, axis="z", segments=18)
    # Lower-left mains switch & front USB port.
    b.box("led_green", (-0.114, 0.034, fz + 0.003), (0.014, 0.012, 0.005))
    b.box("chrome", (-0.090, 0.034, fz + 0.002), (0.011, 0.0055, 0.003))
    # 7 realistic 4mm binding posts (CH1 +/-, GND, CH2 +/-, CH3 +/-).
    post_specs = (
        (-0.062, "yellow_terminal"),
        (-0.038, "rubber"),
        (-0.010, "green_terminal"),
        (0.020, "red_terminal"),
        (0.044, "rubber"),
        (0.076, "accent"),
        (0.100, "rubber"),
    )
    for px, mat in post_specs:
        b.cylinder("aluminum_brushed", (px, 0.034, fz + 0.002), 0.008, 0.004, axis="z", segments=12)
        b.cylinder(mat, (px, 0.034, fz + 0.010), 0.007, 0.015, axis="z", segments=14)
        b.cylinder("gold", (px, 0.034, fz + 0.018), 0.0035, 0.0025, axis="z", segments=10)
    # Side cooling louver slots & top carry handle.
    for side in (-1, 1):
        for i in range(6):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.046 + i * 0.015, -0.02), (0.002, 0.0055, 0.16))
    b.rounded_box("bezel_dark", (0, h + 0.012, 0.0), (0.145, 0.012, 0.022), 0.004, axis="x")
    for hx in (-0.066, 0.066):
        b.box("steel", (hx, h + 0.004, 0.0), (0.012, 0.014, 0.018))
    return b


def oscilloscope() -> Builder:
    """420 × 230 × 175 mm 4-channel mixed-signal oscilloscope (MSO) with live waveform TFT & BNC inputs."""
    b = Builder()
    w, h, d = 0.42, 0.23, 0.175
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.036), 0.006, z * (d / 2 - 0.026)), (0.034, 0.012, 0.028), 0.004, axis="y"
            )
    # Rounded industrial benchtop housing + front rubber protective surround.
    b.rounded_box("light_grey", (0, h / 2 + 0.006, -0.004), (w, h - 0.012, d - 0.008), 0.014, axis="z")
    b.rounded_box("bezel_dark", (0, h / 2 + 0.006, d / 2 - 0.002), (w - 0.010, h - 0.022, 0.014), 0.010, axis="z")
    fz = d / 2 + 0.0055
    # Crisp 4-channel MSO display with embedded waveform & graticule PNG.
    b.box("cavity", (-0.064, 0.138, fz), (0.252, 0.148, 0.003))
    b.decal(
        "mso_screen",
        textures.tex_oscilloscope_screen(),
        (-0.064, 0.138, fz + 0.002),
        0.242,
        0.140,
        face="+z",
        metallic=0.05,
        roughness=0.22,
        emissive=0.52,
    )
    # Softkey row beneath screen.
    for i in range(6):
        b.box("aluminum_brushed", (-0.164 + i * 0.040, 0.055, fz + 0.002), (0.022, 0.007, 0.004))
    # Right control deck: multi-tiered rotary encoders (vertical / horizontal / trigger) & run/stop keys.
    b.box("led_green", (0.140, h - 0.026, fz + 0.002), (0.022, 0.011, 0.004))  # RUN/STOP
    b.box("led_amber", (0.172, h - 0.026, fz + 0.002), (0.022, 0.011, 0.004))  # SINGLE
    knob_positions = (
        (0.095, 0.172, 0.014, "aluminum_brushed"),
        (0.145, 0.172, 0.011, "aluminum_brushed"),
        (0.184, 0.172, 0.011, "aluminum_brushed"),
        (0.095, 0.126, 0.012, "yellow_terminal"),
        (0.142, 0.126, 0.012, "accent"),
        (0.184, 0.126, 0.012, "led_green"),
        (0.095, 0.082, 0.010, "aluminum_brushed"),
        (0.142, 0.082, 0.010, "aluminum_brushed"),
        (0.184, 0.082, 0.010, "aluminum_brushed"),
    )
    for kx, ky, kr, cap_mat in knob_positions:
        b.cylinder("rubber", (kx, ky, fz + 0.006), kr, 0.012, axis="z")
        b.cylinder(cap_mat, (kx, ky, fz + 0.013), kr * 0.72, 0.004, axis="z")
    # 4 detailed metallic BNC channel inputs with colored rings + 16-ch MSO digital pod port + USB host.
    bnc_colors = ("yellow_terminal", "accent", "red_terminal", "green_terminal")
    for idx, color in enumerate(bnc_colors):
        bx = -0.156 + idx * 0.056
        b.cylinder(color, (bx, 0.028, fz + 0.002), 0.0115, 0.004, axis="z")
        b.cylinder("chrome", (bx, 0.028, fz + 0.011), 0.0075, 0.016, axis="z")
        b.cylinder("cavity", (bx, 0.028, fz + 0.019), 0.0048, 0.002, axis="z")
        b.cylinder("gold", (bx, 0.028, fz + 0.018), 0.0014, 0.005, axis="z")
    b.box("chip_black", (0.118, 0.030, fz + 0.005), (0.056, 0.020, 0.010))  # 16-ch MSO logic pod header
    b.box("chrome", (0.172, 0.030, fz + 0.003), (0.016, 0.008, 0.004))  # front USB host
    # Side ventilation louvers + sculpted top carry handle.
    for side in (-1, 1):
        for i in range(6):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.055 + i * 0.020, -0.01), (0.002, 0.007, 0.09))
    b.rounded_box("bezel_dark", (0, h + 0.013, 0.0), (0.185, 0.014, 0.026), 0.005, axis="x")
    for sx in (-0.084, 0.084):
        b.box("bezel_dark", (sx, h + 0.004, 0.0), (0.016, 0.016, 0.024))
    return b


def logic_analyzer_debugger() -> Builder:
    """160 × 28 × 124 mm Saleae Logic Pro 16 CNC-anodized 16-channel logic analyzer & protocol debugger."""
    b = Builder()
    w, h, d = 0.160, 0.028, 0.124
    # Flush silicone base pad standing on y = 0.
    b.rounded_box("rubber", (0, 0.002, 0), (w - 0.014, 0.004, d - 0.014), 0.009, axis="y", corner_segs=6)
    # Sleek CNC-machined anodized charcoal aluminum rounded body with machined chamfer rim.
    body_h = h - 0.004
    body_cy = 0.004 + body_h / 2
    b.rounded_box("bezel_dark", (0, body_cy, 0), (w, body_h, d), 0.012, axis="y", corner_segs=7)
    b.rounded_box("aluminum_brushed", (0, h - 0.001, 0), (w - 0.004, 0.002, d - 0.004), 0.011, axis="y", corner_segs=7)
    # High-DPI Saleae Logic Pro 16 top decal with channel callouts & status indicator.
    b.decal(
        "saleae_top",
        textures.tex_saleae_logic_top(),
        (0, h + 0.0005, 0),
        w - 0.012,
        d - 0.012,
        face="+y",
        metallic=0.22,
        roughness=0.42,
    )
    # Front (+Z): Dual 2×8 shrouded 0.1" pin headers (CH 0-7 & CH 8-15) with gold pin rows.
    fz = d / 2
    for bank_x in (-0.036, 0.036):
        b.beveled_box("chip_black", (bank_x, body_cy - 0.001, fz + 0.0045), (0.058, 0.015, 0.010), bevel=0.001)
        b.box("cavity", (bank_x, body_cy - 0.001, fz + 0.0092), (0.050, 0.010, 0.002))
        for p in range(8):
            px = bank_x - 0.021 + p * 0.006
            for dy in (-0.0024, 0.0024):
                b.box("gold", (px, body_cy - 0.001 + dy, fz + 0.0098), (0.0014, 0.0014, 0.005))
    # Rear (-Z): Recessed USB 3.0 Type-C / Micro-B host port.
    b.rounded_box("chrome", (0, body_cy, -d / 2 - 0.001), (0.014, 0.007, 0.005), 0.002, axis="z")
    b.box("cavity", (0, body_cy, -d / 2 - 0.0036), (0.010, 0.004, 0.0015))
    return b


def embedded_dev_kit() -> Builder:
    """260 × 92 × 200 mm automotive/embedded SoC evaluation board (NXP S32G / AURIX TriBoard style)."""
    b = Builder()
    w, d = 0.26, 0.20
    # ESD matte carrier plate with rubber feet and brass hex standoffs.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.022), 0.004, z * (d / 2 - 0.022)), 0.011, 0.008, segments=12)
            b.cylinder("gold", (x * (w / 2 - 0.026), 0.021, z * (d / 2 - 0.026)), 0.0045, 0.014, segments=6)
    b.rounded_box("bezel_dark", (0, 0.011, 0), (w, 0.006, d), 0.008, axis="y")
    # Rounded multi-layer emerald PCB + silkscreen/trace top decal.
    pcb_y = 0.030
    b.rounded_box("pcb_green", (0, pcb_y, 0), (w - 0.02, 0.004, d - 0.02), 0.006, axis="y")
    b.decal(
        "eval_pcb",
        textures.tex_eval_board_pcb(),
        (0, pcb_y + 0.0024, 0),
        w - 0.024,
        d - 0.024,
        face="+y",
        metallic=0.14,
        roughness=0.42,
    )
    # Central automotive BGA SoC with black anodized 8-fin heatsink.
    b.box("chip_black", (-0.018, pcb_y + 0.006, -0.004), (0.056, 0.007, 0.056))
    b.beveled_box("bezel_dark", (-0.018, pcb_y + 0.013, -0.004), (0.050, 0.007, 0.050), bevel=0.001)
    for i in range(8):
        b.box("heatsink", (-0.040 + i * 0.0063, pcb_y + 0.027, -0.004), (0.0024, 0.022, 0.048))
    # Companion LPDDR4 RAM, QSPI Flash & PMIC power inductors.
    b.beveled_box("chip_black", (-0.082, pcb_y + 0.005, -0.030), (0.026, 0.005, 0.034), bevel=0.001)
    b.beveled_box("chip_black", (-0.082, pcb_y + 0.005, 0.024), (0.022, 0.005, 0.022), bevel=0.001)
    for ix in (-0.078, -0.058):
        b.beveled_box("panel", (ix, pcb_y + 0.007, 0.056), (0.012, 0.008, 0.012), bevel=0.001)  # SMD chokes
    # Tilted diagnostic OLED daughterboard with live AUTOSAR telemetry screen.
    b.rotated_box("pcb_blue", (0.072, pcb_y + 0.029, -0.012), (0.074, 0.052, 0.007), rx=-0.22)
    b.decal(
        "eval_oled",
        textures.tex_eval_board_oled(),
        (0.072, pcb_y + 0.030, -0.007),
        0.064,
        0.042,
        face="+z",
        rx=-0.22,
        metallic=0.05,
        roughness=0.22,
        emissive=0.58,
    )
    # Rear 40-pin GPIO expansion header + shrouded 20-pin ARM JTAG header.
    b.box("bezel_dark", (-0.026, pcb_y + 0.007, -0.072), (0.125, 0.010, 0.009))
    for i in range(16):
        b.box("gold", (-0.082 + i * 0.0075, pcb_y + 0.015, -0.072), (0.0018, 0.008, 0.0018))
    b.box("bezel_dark", (0.078, pcb_y + 0.008, -0.072), (0.042, 0.012, 0.012))
    b.box("cavity", (0.078, pcb_y + 0.013, -0.072), (0.034, 0.004, 0.008))
    # Front-edge real connectors: RJ45 Ethernet, USB-C, DB9 CAN-FD with hex standoffs, gold SMA RF, 12V DC barrel.
    b.beveled_box("aluminum_brushed", (-0.086, pcb_y + 0.011, d / 2 - 0.018), (0.021, 0.017, 0.022), bevel=0.001)
    b.box("cavity", (-0.086, pcb_y + 0.010, d / 2 - 0.0065), (0.015, 0.012, 0.002))
    b.rounded_box("chrome", (-0.048, pcb_y + 0.006, d / 2 - 0.014), (0.012, 0.006, 0.012), 0.002, axis="z")
    # DB9 CAN-FD connector.
    b.rounded_box("chrome", (0.002, pcb_y + 0.010, d / 2 - 0.012), (0.032, 0.013, 0.014), 0.002, axis="z")
    b.box("cavity", (0.002, pcb_y + 0.010, d / 2 - 0.0045), (0.022, 0.008, 0.002))
    for stx in (-0.019, 0.019):
        b.cylinder("steel", (0.002 + stx, pcb_y + 0.010, d / 2 - 0.007), 0.0028, 0.008, axis="z", segments=6)
    # Gold SMA RF connector + 12V DC barrel jack.
    b.cylinder("gold", (0.056, pcb_y + 0.009, d / 2 - 0.010), 0.0055, 0.016, axis="z", segments=12)
    b.box("bezel_dark", (0.092, pcb_y + 0.009, d / 2 - 0.016), (0.014, 0.013, 0.016))
    b.cylinder("cavity", (0.092, pcb_y + 0.009, d / 2 - 0.0075), 0.0042, 0.002, axis="z", segments=12)
    # Status LEDs & tactile reset button.
    b.box("led_green", (-0.104, pcb_y + 0.004, 0.052), (0.006, 0.003, 0.006))
    b.box("led_amber", (-0.092, pcb_y + 0.004, 0.052), (0.006, 0.003, 0.006))
    b.cylinder("red_terminal", (0.098, pcb_y + 0.006, 0.044), 0.005, 0.006, segments=12)
    return b


def network_switch() -> Builder:
    """482 × 44 × 320 mm Cisco Catalyst-style 1U managed 24-port Gigabit Ethernet + 4×10G SFP+ switch."""
    b = Builder()
    w, h, d = 0.442, 0.044, 0.32
    b.beveled_box("steel", (0, h / 2, 0), (w, h, d), bevel=0.0025)
    # 19-inch rack mounting ears with screw slots.
    for side in (-1, 1):
        b.beveled_box(
            "aluminum_brushed", (side * (w / 2 + 0.010), h / 2, d / 2 - 0.005), (0.020, h - 0.004, 0.006), bevel=0.001
        )
        for hy in (0.011, 0.033):
            b.cylinder("cavity", (side * (w / 2 + 0.012), hy, d / 2 - 0.005), 0.0032, 0.007, axis="z", segments=10)
    # Front silkscreened Catalyst faceplate decal.
    fz = d / 2 + 0.0006
    b.decal(
        "switch_front",
        textures.tex_switch_front(),
        (0, h / 2, fz),
        w - 0.006,
        h - 0.004,
        face="+z",
        metallic=0.18,
        roughness=0.40,
        emissive=0.18,
    )
    # 24 RJ45 ports (2 banks × 6 stacked pairs) with chrome shield rim, gold pins & link LEDs.
    for bank in range(2):
        for col in range(6):
            px = -0.145 + bank * 0.116 + col * 0.0176
            for row in range(2):
                py = 0.014 + row * 0.016
                b.box("chrome", (px, py, fz + 0.0015), (0.0145, 0.013, 0.003))
                b.box("cavity", (px, py, fz + 0.0030), (0.0115, 0.010, 0.0015))
                b.box("gold", (px, py - 0.0025, fz + 0.0034), (0.008, 0.0018, 0.0015))
            b.box("led_green", (px - 0.004, 0.0365, fz + 0.0018), (0.0035, 0.0022, 0.0015))
            b.box("led_amber", (px + 0.004, 0.0365, fz + 0.0018), (0.0035, 0.0022, 0.0015))
    # 4× 10G SFP+ metallic optical uplink cages with cyan activity LEDs.
    for i in range(4):
        sx = 0.090 + i * 0.0235
        b.box("chrome", (sx, h / 2 - 0.001, fz + 0.0025), (0.0165, 0.0135, 0.005))
        b.box("cavity", (sx, h / 2 - 0.001, fz + 0.0048), (0.013, 0.0098, 0.0018))
        b.box("led_cyan", (sx, 0.036, fz + 0.0018), (0.005, 0.0025, 0.0015))
    # Blue RJ45 console port on far right & system LEDs on left.
    b.box("usb_blue", (0.195, h / 2 - 0.001, fz + 0.002), (0.0145, 0.013, 0.0035))
    b.box("cavity", (0.195, h / 2 - 0.001, fz + 0.0036), (0.011, 0.0095, 0.0015))
    b.box("led_green", (-0.174, 0.030, fz + 0.0018), (0.005, 0.0035, 0.0015))
    b.box("led_cyan", (-0.174, 0.018, fz + 0.0018), (0.005, 0.0035, 0.0015))
    # Side cooling perforation slots.
    for side in (-1, 1):
        for i in range(6):
            b.box("cavity", (side * (w / 2 + 0.0005), h / 2, -0.10 + i * 0.038), (0.002, 0.022, 0.016))
    return b


def hil_test_rack() -> Builder:
    """800 × 2070 × 900 mm dSPACE SCALEXIO / NI PXI Hardware-in-the-Loop (HIL) simulator cabinet."""
    b = Builder()
    w, h, d = 0.80, 1.95, 0.90
    # Heavy locking swivel casters standing on y = 0 & industrial extruded corner posts.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.08), 0.035, z * (d / 2 - 0.08)), 0.035, 0.032, axis="x")
            b.box("steel", (x * (w / 2 - 0.08), 0.06, z * (d / 2 - 0.08)), (0.042, 0.04, 0.042))
            b.beveled_box(
                "bezel_dark",
                (x * (w / 2 - 0.03), h / 2 + 0.04, z * (d / 2 - 0.03)),
                (0.056, h - 0.16, 0.056),
                bevel=0.006,
            )
    b.beveled_box("bezel_dark", (0, 0.11, 0), (w, 0.08, d), bevel=0.006)
    b.beveled_box("bezel_dark", (0, h - 0.04, 0), (w, 0.08, d), bevel=0.006)
    for side in (-1, 1):
        b.box("light_grey", (side * (w / 2 - 0.012), h / 2 + 0.04, 0), (0.022, h - 0.22, d - 0.12))
    b.box("panel", (0, h / 2 + 0.04, -d / 2 + 0.015), (w - 0.06, h - 0.22, 0.03))
    # Lower 4× 3U real-time SCALEXIO / programmable load & power bank chassis with brushed aluminum faceplates.
    for idx in range(4):
        uy = 0.24 + idx * 0.17
        b.beveled_box("bezel_dark", (0, uy, 0.04), (w - 0.12, 0.145, d - 0.14), bevel=0.004)
        b.box("aluminum_brushed", (0, uy + 0.062, d / 2 - 0.027), (w - 0.14, 0.008, 0.006))
        b.box("mesh_dark", (-0.06, uy - 0.005, d / 2 - 0.026), (w - 0.30, 0.095, 0.008))
        b.box("led_green", (w / 2 - 0.12, uy + 0.03, d / 2 - 0.024), (0.018, 0.008, 0.004))
        b.box("led_cyan", (w / 2 - 0.12, uy + 0.01, d / 2 - 0.024), (0.018, 0.006, 0.004))
        for hx in (-w / 2 + 0.09, w / 2 - 0.09):
            b.box("chrome", (hx, uy, d / 2 - 0.014), (0.012, 0.085, 0.010))
    # Pull-out keyboard/DUT shelf at y = 0.96 m (ESD mat top = 0.983 m, preserving exact surface fraction).
    b.beveled_box("aluminum_brushed", (0, 0.96, 0.10), (w - 0.10, 0.035, d - 0.12), bevel=0.003)
    b.box("esd_mat", (0, 0.98, 0.14), (w - 0.16, 0.006, 0.38))
    # Mid Fault-Injection Unit (FIU) & ECU Breakout Patch Panel with crisp silkscreen + 24 gold/color banana jacks.
    b.box("light_grey", (0, 1.24, 0.05), (w - 0.12, 0.34, d - 0.16))
    b.decal(
        "hil_patch",
        textures.tex_hil_patch_panel(),
        (0, 1.24, d / 2 - 0.024),
        w - 0.16,
        0.30,
        face="+z",
        metallic=0.18,
        roughness=0.45,
    )
    row_mats = ("yellow_terminal", "accent", "red_terminal")
    for r, rmat in enumerate(row_mats):
        for c in range(8):
            bx = -0.24 + c * 0.068
            by = 1.13 + r * 0.078
            b.cylinder(rmat if c < 6 else "rubber", (bx, by, d / 2 - 0.016), 0.0085, 0.014, axis="z", segments=12)
            b.cylinder("gold", (bx, by, d / 2 - 0.008), 0.0036, 0.003, axis="z", segments=10)
    # Upper recessed HIL ControlDesk real-time telemetry display.
    b.beveled_box("bezel_dark", (0, 1.66, 0.04), (w - 0.12, 0.38, d - 0.16), bevel=0.005)
    b.decal(
        "hil_screen",
        textures.tex_hil_screen(),
        (0, 1.66, d / 2 - 0.034),
        0.58,
        0.31,
        face="+z",
        metallic=0.05,
        roughness=0.22,
        emissive=0.48,
    )
    # Front-right Emergency Stop mushroom button on OSHA yellow collar.
    b.beveled_box("fluke_yellow", (w / 2 - 0.036, 1.05, d / 2 + 0.010), (0.066, 0.066, 0.022), bevel=0.004)
    b.cylinder("red_terminal", (w / 2 - 0.036, 1.05, d / 2 + 0.026), 0.022, 0.016, axis="z", segments=16)
    b.cylinder("red_safety", (w / 2 - 0.036, 1.05, d / 2 + 0.035), 0.024, 0.008, axis="z", segments=16)
    # Top 3-tier industrial Andon signal beacon tower (top at y = 2.070 m).
    b.cylinder("aluminum_brushed", (w / 2 - 0.12, h + 0.03, 0.0), 0.018, 0.06, segments=16)
    b.cylinder("led_green", (w / 2 - 0.12, h + 0.072, 0.0), 0.024, 0.028, segments=16)
    b.cylinder("led_amber", (w / 2 - 0.12, h + 0.103, 0.0), 0.024, 0.034, segments=16)
    return b


def soldering_rework_station() -> Builder:
    """280 × 190 × 230 mm Weller WT2M-style ESD digital soldering & hot-air rework station."""
    b = Builder()
    # Rubber feet at y = 0 under main Weller console.
    for x in (-0.115, 0.035):
        for z in (-0.085, 0.085):
            b.cylinder("rubber", (x, 0.005, z), 0.011, 0.010, segments=12)
    # Authentic Weller teal-blue rounded desktop console with dark charcoal faceplate.
    b.rounded_box("weller_teal", (-0.04, 0.074, 0), (0.185, 0.128, 0.21), 0.014, axis="z", corner_segs=6)
    b.rounded_box("bezel_dark", (-0.04, 0.074, 0.104), (0.168, 0.112, 0.010), 0.010, axis="z", corner_segs=6)
    # Crisp glowing dual-channel temperature readout decal (350°C Iron / 380°C Hot Air).
    b.decal(
        "weller_front",
        textures.tex_soldering_front(),
        (-0.04, 0.074, 0.110),
        0.160,
        0.104,
        face="+z",
        metallic=0.06,
        roughness=0.38,
        emissive=0.45,
    )
    # Metallic 5-pin DIN iron & hot-air front umbilical connector collars.
    for cx in (-0.092, 0.016):
        b.cylinder("chrome", (cx, 0.032, 0.115), 0.0085, 0.012, axis="z", segments=14)
        b.cylinder("cavity", (cx, 0.032, 0.121), 0.0055, 0.002, axis="z", segments=12)
    # Heavy weighted safety rest stand on right with sponge recess, brass wool tip cleaner & round angled iron.
    b.beveled_box("bezel_dark", (0.100, 0.014, 0.005), (0.088, 0.028, 0.155), bevel=0.004)
    b.box("yellow_terminal", (0.100, 0.029, 0.048), (0.056, 0.006, 0.046))  # damp cleaning sponge
    b.cylinder("bezel_dark", (0.100, 0.032, -0.028), 0.026, 0.022, segments=16)
    b.cylinder("gold", (0.100, 0.042, -0.028), 0.020, 0.008, segments=16)  # brass wool cleaner dome
    # Angled cylindrical soldering iron holder + ergonomic Weller blue soldering pen & copper tip.
    b.rotated_cylinder("steel", (0.100, 0.072, -0.012), 0.014, 0.095, rx=-0.52, segments=16)
    b.rotated_cylinder("weller_teal", (0.100, 0.128, -0.044), 0.0105, 0.115, rx=-0.52, segments=16)
    b.rotated_cylinder("rubber", (0.100, 0.102, -0.029), 0.012, 0.042, rx=-0.52, segments=16)
    b.rotated_cylinder("chrome", (0.100, 0.068, -0.009), 0.0045, 0.055, rx=-0.52, segments=12)
    b.rotated_cylinder("copper", (0.100, 0.042, 0.006), 0.0026, 0.024, rx=-0.52, segments=10)
    # Side magnetic hot-air wand cradle & cylindrical hot-air gun with stainless nozzle on left.
    b.box("aluminum_brushed", (-0.138, 0.092, 0.0), (0.022, 0.022, 0.038))
    b.rotated_cylinder("bezel_dark", (-0.142, 0.128, 0.0), 0.0145, 0.125, rz=0.14, segments=16)
    b.rotated_cylinder("chrome", (-0.151, 0.055, 0.0), 0.0075, 0.058, rz=0.14, segments=14)
    return b


def thermal_chamber() -> Builder:
    """900 × 1750 × 1050 mm ESPEC / Weiss Technik environmental climatic test chamber."""
    b = Builder()
    w, h, d = 0.90, 1.75, 1.05
    # Heavy locking casters standing on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.09), 0.04, z * (d / 2 - 0.10)), 0.04, 0.036, axis="x")
            b.box("steel", (x * (w / 2 - 0.09), 0.065, z * (d / 2 - 0.10)), (0.045, 0.04, 0.045))
    # Insulated beveled white powder-coated shell with subtle blue brand trim stripe.
    b.beveled_box("white_enclosure", (0, h / 2 + 0.04, 0), (w, h - 0.08, d), bevel=0.012)
    b.box("dark_blue", (0, h - 0.032, d / 2 + 0.002), (w - 0.04, 0.032, 0.008))
    # Lower slatted compressor intake louver panel.
    b.beveled_box("bezel_dark", (0, 0.36, d / 2 + 0.004), (w - 0.12, 0.44, 0.010), bevel=0.004)
    for i in range(9):
        b.box("aluminum_brushed", (0, 0.18 + i * 0.045, d / 2 + 0.010), (w - 0.16, 0.007, 0.005))
    # Upper insulated chamber door with dark heated multi-pane observation window & stainless interior.
    b.beveled_box("light_grey", (0, 1.15, d / 2 + 0.034), (w - 0.08, 0.88, 0.068), bevel=0.010)
    b.rounded_box("bezel_dark", (-0.05, 1.17, d / 2 + 0.066), (0.46, 0.50, 0.014), 0.014, axis="z")
    b.box("cavity", (-0.05, 1.17, d / 2 + 0.062), (0.41, 0.45, 0.016))
    b.box("glass", (-0.05, 1.17, d / 2 + 0.074), (0.41, 0.45, 0.005))
    b.box("led_white", (-0.05, 1.37, d / 2 + 0.069), (0.34, 0.012, 0.004))
    for sy in (1.03, 1.19):
        b.box("aluminum_brushed", (-0.05, sy, d / 2 + 0.068), (0.38, 0.009, 0.005))
    # Heavy chrome compression cam handle & industrial door hinges.
    b.beveled_box("chrome", (0.33, 1.15, d / 2 + 0.084), (0.036, 0.24, 0.026), bevel=0.004)
    for hy in (0.85, 1.46):
        b.beveled_box("aluminum_brushed", (-w / 2 + 0.032, hy, d / 2 + 0.042), (0.032, 0.095, 0.042), bevel=0.003)
    # Top-right PID touchscreen controller decal (-40°C / 65% RH + ramp curve) & E-Stop.
    b.beveled_box("bezel_dark", (0.24, 1.655, d / 2 + 0.010), (0.30, 0.145, 0.020), bevel=0.004)
    b.decal(
        "thermal_pid",
        textures.tex_thermal_controller(),
        (0.22, 1.655, d / 2 + 0.021),
        0.23,
        0.128,
        face="+z",
        metallic=0.05,
        roughness=0.22,
        emissive=0.50,
    )
    b.cylinder("red_terminal", (0.365, 1.655, d / 2 + 0.024), 0.015, 0.012, axis="z", segments=14)
    # Side 100mm silicone cable feedthrough port.
    b.cylinder("rubber", (w / 2 + 0.008, 1.16, 0.05), 0.056, 0.022, axis="x", segments=18)
    b.cylinder("chrome", (w / 2 + 0.016, 1.16, 0.05), 0.044, 0.008, axis="x", segments=18)
    return b


def rack_ups_pdu() -> Builder:
    """482 × 132 × 520 mm APC Smart-UPS 3000VA 3U rack/bench Uninterruptible Power Supply."""
    b = Builder()
    w, h, d = 0.442, 0.132, 0.52
    b.beveled_box("bezel_dark", (0, h / 2, 0), (w, h, d), bevel=0.003)
    for side in (-1, 1):
        b.beveled_box(
            "aluminum_brushed", (side * (w / 2 + 0.010), h / 2, d / 2 - 0.005), (0.020, h - 0.006, 0.008), bevel=0.001
        )
    # Sculpted curved-look front matte bezel with left intake louver bank.
    b.rounded_box("panel", (0, h / 2, d / 2 + 0.004), (w - 0.008, h - 0.008, 0.010), 0.005, axis="z")
    fz = d / 2 + 0.0095
    for i in range(6):
        b.box("cavity", (-0.125, 0.024 + i * 0.0168, fz), (0.165, 0.008, 0.003))
    # Signature backlit blue APC Smart-UPS status LCD screen.
    b.beveled_box("bezel_dark", (0.042, 0.074, fz), (0.128, 0.076, 0.004), bevel=0.002)
    b.decal(
        "ups_lcd",
        textures.tex_ups_lcd(),
        (0.042, 0.074, fz + 0.0025),
        0.118,
        0.068,
        face="+z",
        metallic=0.05,
        roughness=0.25,
        emissive=0.58,
    )
    # Status LED indicators & tactile menu navigation pad on right.
    for i, mat in enumerate(("led_green", "led_green", "led_amber", "led_red")):
        b.box(mat, (0.126 + i * 0.016, 0.104, fz + 0.001), (0.009, 0.006, 0.002))
    b.cylinder("aluminum_brushed", (0.150, 0.056, fz + 0.003), 0.016, 0.007, axis="z", segments=16)
    b.cylinder("bezel_dark", (0.150, 0.056, fz + 0.007), 0.010, 0.002, axis="z", segments=14)
    b.box("led_green", (0.194, 0.056, fz + 0.002), (0.016, 0.016, 0.004))  # power key
    # Rear metered IEC C13/C19 output banks & network management card.
    for i in range(6):
        b.box("socket", (-0.155 + i * 0.052, 0.066, -d / 2 - 0.003), (0.032, 0.026, 0.006))
        b.box("cavity", (-0.155 + i * 0.052, 0.066, -d / 2 - 0.0062), (0.022, 0.016, 0.0015))
    return b


def rf_signal_analyzer() -> Builder:
    """430 × 210 × 410 mm Rohde & Schwarz FSVA / Keysight EXA RF spectrum & vector signal analyzer."""
    b = Builder()
    w, h, d = 0.43, 0.21, 0.41
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.036), 0.006, z * (d / 2 - 0.040)), (0.032, 0.012, 0.036), 0.004, axis="y"
            )
    body_h = h - 0.012
    body_cy = 0.012 + body_h / 2
    b.rounded_box("light_grey", (0, body_cy, -0.004), (w, body_h, d - 0.008), 0.012, axis="z", corner_segs=6)
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.010, body_h - 0.014, 0.012), 0.009, axis="z")
    fz = d / 2 + 0.0055
    # High-DPI RF spectrum trace display (2.442 GHz carrier + marker M1 + max-hold).
    b.box("cavity", (-0.068, body_cy + 0.008, fz), (0.244, 0.152, 0.003))
    b.decal(
        "rf_spectrum",
        textures.tex_rf_spectrum_screen(),
        (-0.068, body_cy + 0.008, fz + 0.002),
        0.236,
        0.144,
        face="+z",
        metallic=0.05,
        roughness=0.22,
        emissive=0.52,
    )
    # Vertical softkeys next to screen.
    for i in range(6):
        b.box("aluminum_brushed", (0.064, 0.058 + i * 0.021, fz + 0.002), (0.012, 0.009, 0.004))
    # Heavy knurled brushed-aluminum frequency tuning wheel & 3x4 keypad.
    b.cylinder("bezel_dark", (0.112, 0.142, fz + 0.008), 0.025, 0.016, axis="z", segments=24)
    b.cylinder("aluminum_brushed", (0.112, 0.142, fz + 0.017), 0.021, 0.004, axis="z", segments=24)
    for r in range(4):
        for c in range(3):
            b.box("socket", (0.154 + c * 0.015, 0.104 + r * 0.017, fz + 0.002), (0.010, 0.010, 0.004))
    # Precision gold 50-Ohm N-Type & SMA RF input ports on lower right + front USB.
    for rx, rad in ((0.098, 0.0115), (0.152, 0.0075)):
        b.cylinder("chrome", (rx, 0.048, fz + 0.004), rad * 1.25, 0.006, axis="z", segments=16)
        b.cylinder("gold", (rx, 0.048, fz + 0.015), rad, 0.018, axis="z", segments=16)
        b.cylinder("cavity", (rx, 0.048, fz + 0.024), rad * 0.55, 0.002, axis="z", segments=12)
        b.cylinder("gold", (rx, 0.048, fz + 0.023), 0.0018, 0.005, axis="z", segments=10)
    b.box("led_green", (-0.184, 0.032, fz + 0.002), (0.016, 0.012, 0.004))
    # Sculpted metallic front instrument handles.
    for side in (-1, 1):
        b.rounded_box(
            "aluminum_brushed",
            (side * (w / 2 - 0.014), body_cy, d / 2 + 0.028),
            (0.012, body_h - 0.05, 0.012),
            0.004,
            axis="y",
        )
        for hy in (0.046, h - 0.036):
            b.box("aluminum_brushed", (side * (w / 2 - 0.014), hy, d / 2 + 0.016), (0.012, 0.014, 0.022))
    # Side ventilation louvers.
    for side in (-1, 1):
        for i in range(6):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.052 + i * 0.020, -0.02), (0.002, 0.007, 0.18))
    return b


# --- Lab furniture components ------------------------------------------------------------------------------


def esd_corner_bench() -> Builder:
    """1800 × 1650 × 1400 mm L-shaped ESD electronics workstation, worktop at 900 mm."""
    b = Builder()
    w, d, top = 1.80, 1.40, 0.90
    main_d = 0.78
    wing_w = 0.72
    # Main bench along back (-z) + right return wing (+x, +z).
    back_z = -d / 2 + main_d / 2
    wing_x = w / 2 - wing_w / 2
    wing_z = d / 2 - (d - main_d) / 2
    # Steel legs with rubber leveling feet.
    leg_coords = (
        (-w / 2 + 0.05, -d / 2 + 0.05),
        (-w / 2 + 0.05, -d / 2 + main_d - 0.05),
        (w / 2 - 0.05, -d / 2 + 0.05),
        (w / 2 - wing_w + 0.05, d / 2 - 0.05),
        (w / 2 - 0.05, d / 2 - 0.05),
    )
    for lx, lz in leg_coords:
        b.cylinder("rubber", (lx, 0.01, lz), 0.028, 0.02)
        b.box("light_grey", (lx, (top - 0.04) / 2, lz), (0.05, top - 0.04, 0.05))
    # Worktop surfaces (L-shape) and grounded ESD mats.
    b.box("worktop", (0, top - 0.02, back_z), (w, 0.04, main_d))
    b.box("worktop", (wing_x, top - 0.02, wing_z), (wing_w, 0.04, d - main_d))
    b.box("esd_mat", (0, top + 0.002, back_z + 0.02), (w - 0.08, 0.004, main_d - 0.12))
    b.box("esd_mat", (wing_x, top + 0.002, wing_z), (wing_w - 0.08, 0.004, d - main_d - 0.06))
    b.box("led_green", (-w / 2 + 0.12, top + 0.006, -d / 2 + main_d - 0.05), (0.032, 0.006, 0.02))
    # Under-desk 3-drawer pedestal on the right wing.
    b.box("light_grey", (wing_x + 0.08, 0.44, wing_z), (0.44, 0.78, 0.50))
    for i in range(3):
        dy = 0.21 + i * 0.24
        b.box("panel", (wing_x - 0.145, dy, wing_z), (0.012, 0.21, 0.44))
        b.box("chrome", (wing_x - 0.156, dy + 0.05, wing_z), (0.014, 0.014, 0.16))
    # Rear upright frame, perforated tool pegboard, upper shelf, power strip, and LED task bar.
    for ux in (-w / 2 + 0.05, 0.0, w / 2 - 0.05):
        b.box("light_grey", (ux, top + 0.375, -d / 2 + 0.04), (0.045, 0.75, 0.045))
    b.box("steel", (0, top + 0.34, -d / 2 + 0.05), (w - 0.14, 0.34, 0.018))  # tool pegboard
    b.box("steel", (0, top + 0.56, -d / 2 + 0.18), (w - 0.08, 0.024, 0.30))  # upper shelf
    b.box("led_white", (0, top + 0.72, -d / 2 + 0.26), (w - 0.26, 0.018, 0.038))
    b.box("light_grey", (0, top + 0.74, -d / 2 + 0.15), (w, 0.035, 0.28))  # overhead hood bar
    b.box("panel", (0, top + 0.10, -d / 2 + 0.06), (w - 0.18, 0.065, 0.045))
    for i in range(8):
        b.box("socket", (-0.70 + i * 0.20, top + 0.10, -d / 2 + 0.085), (0.052, 0.04, 0.004))
    return b


def mobile_lab_cart() -> Builder:
    """900 × 980 × 600 mm rolling 3-tier ESD instrument trolley, top tray at 860 mm."""
    b = Builder()
    w, h, d = 0.90, 0.98, 0.60
    tray_y = (0.16, 0.51, 0.86)
    # 4 swivel casters standing on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            cx, cz = x * (w / 2 - 0.06), z * (d / 2 - 0.06)
            b.cylinder("rubber", (cx, 0.04, cz), 0.04, 0.028, axis="x")
            b.box("steel", (cx, 0.09, cz), (0.032, 0.05, 0.032))
            b.cylinder("chrome", (cx, 0.50, cz), 0.018, 0.78)
    # Three lipped steel trays + ESD mat on top work surface.
    for y in tray_y:
        b.box("light_grey", (0, y, 0), (w - 0.04, 0.024, d - 0.04))
        b.box("steel", (0, y + 0.02, -d / 2 + 0.025), (w - 0.04, 0.03, 0.012))
        b.box("steel", (0, y + 0.02, d / 2 - 0.025), (w - 0.04, 0.03, 0.012))
    b.box("esd_mat", (0, 0.875, 0), (w - 0.08, 0.006, d - 0.08))
    # Push handle on +X end (rising to h = 0.98).
    for hz in (-d / 2 + 0.06, d / 2 - 0.06):
        b.cylinder("chrome", (w / 2 - 0.06, 0.92, hz), 0.016, 0.12)
    b.cylinder("chrome", (w / 2 - 0.06, h - 0.016, 0), 0.016, d - 0.10, axis="z")
    # Side-mounted 6-outlet power strip.
    b.box("panel", (-w / 2 + 0.015, 0.72, 0), (0.035, 0.06, d - 0.14))
    for i in range(5):
        b.box("socket", (-w / 2 - 0.004, 0.72, -0.18 + i * 0.09), (0.004, 0.032, 0.042))
    return b


def fume_hood() -> Builder:
    """1500 × 2150 × 850 mm industrial laboratory fume & soldering extraction hood."""
    b = Builder()
    w, h, d = 1.50, 2.15, 0.85
    deck_y = 0.90
    # Base chemical/filter storage cabinet.
    b.box("rubber", (0, 0.04, 0), (w - 0.04, 0.08, d - 0.06))
    b.box("light_grey", (0, 0.48, 0), (w, 0.80, d))
    for side in (-1, 1):
        b.box("white_enclosure", (side * (w / 4 - 0.005), 0.48, d / 2 + 0.012), (w / 2 - 0.03, 0.72, 0.02))
        b.box("chrome", (side * 0.055, 0.56, d / 2 + 0.028), (0.016, 0.18, 0.016))
    # Chemical-resistant dark phenolic work deck.
    b.box("frame", (0, deck_y, 0), (w + 0.02, 0.045, d + 0.02))
    # Upper hood enclosure (left, right, back, top plenum).
    wall_h = 1.05
    for side in (-1, 1):
        b.box("white_enclosure", (side * (w / 2 - 0.04), deck_y + wall_h / 2 + 0.02, 0), (0.08, wall_h, d))
    b.box("light_grey", (0, deck_y + wall_h / 2 + 0.02, -d / 2 + 0.04), (w - 0.14, wall_h, 0.08))
    b.box("white_enclosure", (0, h - 0.18, 0), (w, 0.20, d))
    # Angled tempered glass sliding sash + chrome handle bar.
    b.rotated_box("glass", (0, deck_y + 0.62, d / 2 - 0.06), (w - 0.18, 0.62, 0.012), rx=-0.12)
    b.box("chrome", (0, deck_y + 0.32, d / 2 - 0.01), (w - 0.22, 0.022, 0.028))
    # Internal overhead task lighting & digital face-velocity airflow monitor.
    b.box("led_white", (0, deck_y + wall_h - 0.02, 0.05), (w - 0.32, 0.018, 0.08))
    b.beveled_box("bezel_dark", (w / 2 - 0.26, h - 0.18, d / 2 + 0.008), (0.30, 0.105, 0.014), bevel=0.003)
    b.decal(
        "fume_monitor",
        textures.tex_fume_hood_monitor(),
        (w / 2 - 0.26, h - 0.18, d / 2 + 0.016),
        0.27,
        0.092,
        face="+z",
        metallic=0.05,
        roughness=0.28,
        emissive=0.45,
    )
    # Top circular exhaust duct collar.
    b.cylinder("steel", (0, h - 0.04, -0.05), 0.14, 0.08)
    return b


def safety_cabinet() -> Builder:
    """1100 × 1650 × 500 mm OSHA/EN flammable & Li-ion battery safety cabinet."""
    b = Builder()
    w, h, d = 1.10, 1.65, 0.50
    # Leveling feet + sump plinth.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.05), 0.015, z * (d / 2 - 0.05)), 0.025, 0.03)
    b.beveled_box("fluke_yellow", (0, h / 2 + 0.015, 0), (w, h - 0.03, d), bevel=0.008)
    # Double doors with recessed seam, 3-point chrome handle, and crisp FLAMMABLE hazard placards.
    for side in (-1, 1):
        dx = side * (w / 4 + 0.003)
        b.beveled_box("fluke_yellow", (dx, h / 2 + 0.02, d / 2 + 0.012), (w / 2 - 0.018, h - 0.12, 0.024), bevel=0.004)
        b.decal(
            "safety_placard",
            textures.tex_safety_placard(),
            (dx, h * 0.68, d / 2 + 0.0255),
            0.34,
            0.146,
            face="+z",
            metallic=0.04,
            roughness=0.42,
        )
    b.box("cavity", (0, h / 2 + 0.02, d / 2 + 0.012), (0.008, h - 0.12, 0.026))
    b.beveled_box("chrome", (0.055, h * 0.50, d / 2 + 0.034), (0.026, 0.15, 0.022), bevel=0.003)
    # Side flame-arrester vent bungs.
    for side in (-1, 1):
        b.cylinder("steel", (side * (w / 2 + 0.01), 0.35, 0.0), 0.032, 0.02, axis="x")
        b.cylinder("steel", (side * (w / 2 + 0.01), h - 0.30, 0.0), 0.032, 0.02, axis="x")
    return b


def lab_chair() -> Builder:
    """620 × 1050 × 620 mm ESD ergonomic lab stool/chair on 5-star caster base."""
    b = Builder()
    # 5-star base spokes and casters standing on y = 0.
    for i in range(5):
        angle = 2 * math.pi * i / 5
        rx, rz = math.cos(angle) * 0.27, math.sin(angle) * 0.27
        b.cylinder("rubber", (rx, 0.022, rz), 0.024, 0.044, axis="y")
        b.rotated_box("frame", (rx / 2, 0.068, rz / 2), (0.28, 0.026, 0.032), ry=-angle)
    # Pneumatic chrome cylinder and circular footring (approximated with 10 segments).
    b.cylinder("chrome", (0, 0.34, 0), 0.026, 0.52)
    b.cylinder("frame", (0, 0.16, 0), 0.042, 0.18)
    for i in range(10):
        angle = 2 * math.pi * i / 10
        fx, fz = math.cos(angle) * 0.20, math.sin(angle) * 0.20
        b.rotated_box("chrome", (fx, 0.25, fz), (0.13, 0.016, 0.016), ry=-angle + math.pi / 2)
    for i in range(5):
        angle = 2 * math.pi * i / 5
        b.rotated_box(
            "chrome", (math.cos(angle) * 0.10, 0.25, math.sin(angle) * 0.10), (0.20, 0.012, 0.012), ry=-angle
        )
    # Contoured ESD seat cushion + armrests.
    b.box("frame", (0, 0.59, 0), (0.36, 0.03, 0.34))
    b.box("panel", (0, 0.635, 0.01), (0.46, 0.065, 0.44))
    for side in (-1, 1):
        b.box("frame", (side * 0.24, 0.72, 0.0), (0.024, 0.18, 0.03))
        b.box("rubber", (side * 0.25, 0.81, 0.02), (0.055, 0.024, 0.24))
    # Backrest spine and slightly angled ESD lumbar pad.
    b.box("frame", (0, 0.74, -0.21), (0.06, 0.28, 0.028))
    b.rotated_box("panel", (0, 0.90, -0.21), (0.42, 0.30, 0.05), rx=-0.10)
    return b


def component_drawer_cabinet() -> Builder:
    """950 × 1450 × 580 mm 7-drawer heavy-duty ESD SMD/component storage cabinet."""
    b = Builder()
    w, h, d = 0.95, 1.45, 0.58
    b.box("rubber", (0, 0.035, 0), (w - 0.04, 0.07, d - 0.04))
    b.box("frame", (0, h / 2 + 0.03, 0), (w, h - 0.07, d))
    b.box("esd_mat", (0, h + 0.002, 0), (w - 0.04, 0.006, d - 0.04))
    # 7 full-width modular drawers (taller on bottom, shallower SMD drawers on top).
    heights = (0.24, 0.22, 0.20, 0.17, 0.15, 0.14, 0.13)
    cursor = 0.09
    for idx, dh in enumerate(heights):
        cy = cursor + dh / 2
        b.box("dark_blue" if idx % 2 == 0 else "panel", (0, cy, d / 2 + 0.01), (w - 0.06, dh - 0.012, 0.02))
        b.box("chrome", (0, cy + dh * 0.24, d / 2 + 0.024), (w - 0.12, 0.024, 0.012))
        b.box("socket", (0, cy + dh * 0.24, d / 2 + 0.031), (w - 0.24, 0.012, 0.002))  # label strip
        cursor += dh
    b.cylinder("chrome", (w / 2 - 0.05, h - 0.05, d / 2 + 0.012), 0.012, 0.008, axis="z")  # central lock
    return b


def cable_tray_overhead() -> Builder:
    """1800 × 2200 × 650 mm overhead power/data service gantry bridge."""
    b = Builder()
    w, h, d = 1.80, 2.20, 0.65
    # Twin H-frame floor bases and vertical columns.
    for side in (-1, 1):
        cx = side * (w / 2 - 0.04)
        b.box("frame", (cx, 0.02, 0), (0.08, 0.04, d))
        for z in (-d / 2 + 0.08, d / 2 - 0.08):
            b.box("light_grey", (cx, h / 2, z), (0.055, h - 0.04, 0.055))
        b.box("light_grey", (cx, 0.88, 0), (0.045, 0.045, d - 0.10))  # bench-height tie bar
    # Overhead ladder cable tray with color-coded power (red) and network (blue) busways.
    b.box("steel", (0, h - 0.06, -0.14), (w, 0.06, 0.03))
    b.box("steel", (0, h - 0.06, 0.14), (w, 0.06, 0.03))
    for i in range(9):
        b.box("steel", (-0.72 + i * 0.18, h - 0.08, 0), (0.025, 0.02, 0.28))
    b.box("red_safety", (0, h - 0.03, -0.06), (w - 0.10, 0.04, 0.06))  # power busway
    b.box("accent", (0, h - 0.03, 0.06), (w - 0.10, 0.04, 0.06))  # network fiber/Cu tray
    # Twin suspended overhead LED work lights.
    for lx in (-0.42, 0.42):
        b.box("frame", (lx, h - 0.18, 0.0), (0.62, 0.03, 0.10))
        b.box("led_white", (lx, h - 0.20, 0.0), (0.58, 0.01, 0.08))
    # Suspended vertical power/Ethernet drop box on left side.
    b.box("panel", (-w / 2 + 0.16, 1.48, 0.0), (0.10, 0.56, 0.10))
    for i in range(4):
        b.box("socket", (-w / 2 + 0.16, 1.30 + i * 0.10, 0.053), (0.05, 0.045, 0.004))
    return b


# --- Specific automotive & embedded lab hardware models ----------------------------------------------------


def vector_vn1630a() -> Builder:
    """132 × 42 × 106 mm Vector VN1630A CAN/LIN interface with rounded extrusion, red rubber collars & crisp faceplate."""
    b = Builder()
    w, h, d = 0.132, 0.042, 0.106
    collar_w, collar_h = w + 0.006, h + 0.004
    cy = collar_h / 2  # rubber collars rest flush on y = 0
    # Rounded matte-black extruded aluminum body.
    b.rounded_box("bezel_dark", (0, cy, 0), (w, h - 0.002, d), 0.0085, axis="z", corner_segs=7)
    # Signature Vector hollow crimson silicone protective collars (front +Z and rear -Z).
    for sz in (-1, 1):
        bz = sz * (d / 2 - 0.0075)
        b.rounded_collar("vector_red", (0, cy, bz), (collar_w, collar_h, 0.009), 0.004, 0.010, axis="z", corner_segs=7)
    # Crisp printed white top faceplate decal (VECTOR >, VN1630A grey band, CAN/LIN crimson band, 5 labeled LEDs).
    top_y = cy + (h - 0.002) / 2 + 0.0005
    b.decal(
        "vn1630a_top",
        textures.tex_vn1630a_top(),
        (0, top_y, 0),
        w - 0.018,
        d - 0.025,
        face="+y",
        metallic=0.04,
        roughness=0.42,
    )
    # Front plate (+Z): matte black silkscreen (CH2/4, CH1/3, Sync) + detailed DB9 connectors & circular Sync port.
    fz = d / 2 + 0.0006
    b.decal(
        "vn1630a_front",
        textures.tex_vn1630a_front(),
        (0, cy, fz),
        w - 0.016,
        h - 0.010,
        face="+z",
        metallic=0.25,
        roughness=0.48,
    )
    # Recessed black corner screw plugs left/right.
    for sx in (-w / 2 + 0.007, w / 2 - 0.007):
        b.cylinder("rubber", (sx, cy - 0.002, fz + 0.001), 0.0038, 0.002, axis="z", segments=12)
    # Two detailed DB9 male connectors (CH2/4 & CH1/3) with metallic flange, dark shell, 9 gold pins & hex standoffs.
    for db_x in (-0.028, 0.014):
        b.rounded_box("aluminum_brushed", (db_x, cy - 0.004, fz + 0.0025), (0.031, 0.013, 0.004), 0.0025, axis="z")
        b.rounded_box("chrome", (db_x, cy - 0.004, fz + 0.0065), (0.022, 0.010, 0.006), 0.0022, axis="z")
        b.rounded_box("cavity", (db_x, cy - 0.004, fz + 0.0092), (0.018, 0.0072, 0.0016), 0.0015, axis="z")
        for p in range(5):
            b.cylinder(
                "gold", (db_x - 0.0068 + p * 0.0034, cy - 0.0024, fz + 0.0098), 0.0006, 0.0032, axis="z", segments=8
            )
        for p in range(4):
            b.cylinder(
                "gold", (db_x - 0.0051 + p * 0.0034, cy - 0.0056, fz + 0.0098), 0.0006, 0.0032, axis="z", segments=8
            )
        for stx in (-0.0175, 0.0175):
            b.cylinder("chrome", (db_x + stx, cy - 0.004, fz + 0.0055), 0.0032, 0.009, axis="z", segments=6)
            b.cylinder("cavity", (db_x + stx, cy - 0.004, fz + 0.010), 0.0014, 0.0015, axis="z", segments=8)
    # Circular push-pull metallic Sync connector on right.
    b.cylinder("aluminum_brushed", (0.047, cy - 0.004, fz + 0.0045), 0.0068, 0.008, axis="z", segments=16)
    b.cylinder("chrome", (0.047, cy - 0.004, fz + 0.0095), 0.0052, 0.007, axis="z", segments=16)
    b.cylinder("cavity", (0.047, cy - 0.004, fz + 0.0128), 0.0038, 0.0015, axis="z", segments=14)
    for ang in (0.0, 2.094, 4.189):
        b.cylinder(
            "gold",
            (0.047 + 0.0017 * math.cos(ang), cy - 0.004 + 0.0017 * math.sin(ang), fz + 0.0126),
            0.00055,
            0.0028,
            axis="z",
            segments=8,
        )
    # Rear face (-Z): USB-B host receptacle & auxiliary IO barrel.
    rz = -d / 2 - 0.0005
    b.box("chrome", (-0.022, cy, rz - 0.003), (0.014, 0.012, 0.006))
    b.box("cavity", (-0.022, cy, rz - 0.0058), (0.009, 0.008, 0.002))
    b.cylinder("chrome", (0.024, cy, rz - 0.0045), 0.0052, 0.009, axis="z")
    return b


def vector_vn5620() -> Builder:
    """170 × 45 × 154 mm Vector VN5620 Automotive Ethernet/CAN interface with rounded body, red collars & specs decal."""
    b = Builder()
    w, h, d = 0.170, 0.045, 0.154
    collar_w, collar_h = w + 0.006, h + 0.004
    cy = collar_h / 2
    # Matte-black rounded extruded aluminum enclosure.
    b.rounded_box("bezel_dark", (0, cy, 0), (w, h - 0.002, d), 0.0085, axis="z", corner_segs=7)
    # Signature Vector hollow crimson silicone bumper collars front and rear.
    for sz in (-1, 1):
        bz = sz * (d / 2 - 0.009)
        b.rounded_collar(
            "vector_red", (0, cy, bz), (collar_w, collar_h, 0.0095), 0.0042, 0.010, axis="z", corner_segs=7
        )
    # High-DPI white top faceplate decal matching real VN5620 photo (VECTOR >, crimson VN5620 banner, BroadR-Reach, ETH/CAN).
    top_y = cy + (h - 0.002) / 2 + 0.0005
    b.decal(
        "vn5620_top",
        textures.tex_vn5620_top(),
        (0, top_y, 0),
        w - 0.018,
        d - 0.028,
        face="+y",
        metallic=0.04,
        roughness=0.42,
    )
    # Front face (+Z): silkscreened matte black plate + 4 Automotive Ethernet cages + DB9 CAN 5/6 port.
    fz = d / 2 + 0.0006
    b.decal(
        "vn5620_front",
        textures.tex_vn5620_front(),
        (0, cy, fz),
        w - 0.016,
        h - 0.010,
        face="+z",
        metallic=0.25,
        roughness=0.48,
    )
    for i in range(4):
        px = -0.056 + i * 0.0235
        b.rounded_box("chrome", (px, cy - 0.004, fz + 0.004), (0.017, 0.015, 0.008), 0.0015, axis="z")
        b.box("cavity", (px, cy - 0.004, fz + 0.0076), (0.013, 0.011, 0.002))
        b.box("gold", (px, cy - 0.001, fz + 0.0072), (0.009, 0.002, 0.0015))
        b.box("led_green", (px - 0.0055, cy + 0.0048, fz + 0.0045), (0.0026, 0.002, 0.002))
    # DB9 CAN 5/6 connector on right of front face.
    db_x = 0.047
    b.rounded_box("aluminum_brushed", (db_x, cy - 0.004, fz + 0.0025), (0.030, 0.013, 0.004), 0.0025, axis="z")
    b.rounded_box("chrome", (db_x, cy - 0.004, fz + 0.0065), (0.022, 0.010, 0.006), 0.0022, axis="z")
    b.rounded_box("cavity", (db_x, cy - 0.004, fz + 0.0092), (0.018, 0.0072, 0.0016), 0.0015, axis="z")
    for p in range(5):
        b.cylinder("gold", (db_x - 0.0068 + p * 0.0034, cy - 0.0024, fz + 0.0098), 0.0006, 0.003, axis="z", segments=8)
    for stx in (-0.0175, 0.0175):
        b.cylinder("chrome", (db_x + stx, cy - 0.004, fz + 0.0055), 0.0032, 0.009, axis="z", segments=6)
    # Rear face (-Z): protruding circular knurled Sync & 12V Power connectors + USB-C host (matching top of photo).
    rz = -d / 2 - 0.0005
    for rx in (0.012, 0.034, 0.054):
        b.cylinder("aluminum_brushed", (rx, cy, rz - 0.006), 0.0062, 0.012, axis="z", segments=16)
        b.cylinder("chrome", (rx, cy, rz - 0.013), 0.0048, 0.006, axis="z", segments=16)
        b.cylinder("cavity", (rx, cy, rz - 0.016), 0.0032, 0.0015, axis="z", segments=12)
    b.rounded_box("chrome", (-0.044, cy, rz - 0.003), (0.014, 0.007, 0.006), 0.0025, axis="z")
    return b


def lauterbach_powerdebug() -> Builder:
    """110 × 29 × 215 mm Lauterbach TRACE32 PowerDebug with beveled pearl shell, 13-fin heatsink & dual trace headers."""
    b = Builder()
    w, h, d = 0.110, 0.029, 0.215
    # Low rubber pad feet at y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.014), 0.0015, z * (d / 2 - 0.018)), 0.0065, 0.003, segments=12)
    # Sleek beveled off-white modular enclosure matching Lauterbach industrial design.
    body_h = h - 0.003
    body_cy = 0.003 + body_h / 2
    b.beveled_box("lauterbach_white", (0, body_cy, 0), (w, body_h, d), bevel=0.0032)
    # Subtle molded side grip ribbing zones on left & right walls.
    for side in (-1, 1):
        for z_off in (-0.088, 0.002, 0.078):
            for i in range(4):
                b.box(
                    "light_grey",
                    (side * (w / 2 + 0.0003), body_cy, z_off + i * 0.0032),
                    (0.0008, body_h - 0.007, 0.0014),
                )
    # Crisp printed top deck decal (POWER/RUNNING/DEBUG LEDs, DBG/USB/5V diagram, LAUTERBACH wordmark, A/B & CE).
    b.decal(
        "lauterbach_top",
        textures.tex_lauterbach_top(),
        (0, h + 0.0003, 0),
        w - 0.008,
        d - 0.008,
        face="+y",
        metallic=0.04,
        roughness=0.38,
    )
    # Signature centered matte-black extruded 13-fin aluminum heatsink with chamfered end walls.
    hs_w, hs_d = 0.078, 0.084
    b.beveled_box("bezel_dark", (0, h + 0.0025, 0.004), (hs_w, 0.0045, hs_d), bevel=0.0012)
    for i in range(13):
        fin_z = -0.036 + i * 0.0066
        b.beveled_box("bezel_dark", (0, h + 0.0082, fin_z), (hs_w, 0.0105, 0.0026), bevel=0.0006)
    # Rear-top (-Z) twin high-density black debug/trace docking headers (A & B) with dual pin rows & grey latches.
    for hz in (-0.064, -0.084):
        b.beveled_box("bezel_dark", (0, h + 0.0052, hz), (0.062, 0.0095, 0.0105), bevel=0.001)
        b.box("cavity", (0, h + 0.0088, hz), (0.052, 0.0035, 0.0055))
        for p in range(14):
            px = -0.023 + p * 0.0035
            for dz in (-0.0012, 0.0012):
                b.box("gold", (px, h + 0.0092, hz + dz), (0.0010, 0.0042, 0.0010))
        for lx in (-0.034, 0.034):
            b.beveled_box("panel", (lx, h + 0.0076, hz), (0.0062, 0.0135, 0.0125), bevel=0.001)
    # Front end (+Z): recessed faceplate with blue USB 3.0 Type-B receptacle, black DC 5V barrel jack & reset pinhole.
    fz = d / 2 + 0.0003
    b.box("light_grey", (0, body_cy, fz), (w - 0.014, body_h - 0.008, 0.0015))
    # Blue USB 3.0 Type-B port (tall double-deck square profile).
    b.box("chrome", (-0.008, body_cy, fz + 0.0018), (0.014, 0.0155, 0.0035))
    b.box("usb_blue", (-0.008, body_cy, fz + 0.0034), (0.0105, 0.012, 0.0018))
    b.box("cavity", (-0.008, body_cy - 0.001, fz + 0.0044), (0.007, 0.0075, 0.001))
    # Black 5V DC barrel power jack.
    b.box("bezel_dark", (0.013, body_cy, fz + 0.0018), (0.0115, 0.013, 0.0035))
    b.cylinder("cavity", (0.013, body_cy, fz + 0.0036), 0.0040, 0.0018, axis="z", segments=14)
    b.cylinder("chrome", (0.013, body_cy, fz + 0.0036), 0.0014, 0.0024, axis="z", segments=10)
    # Tiny recessed debug reset pinhole left of USB.
    b.cylinder("cavity", (-0.028, body_cy, fz + 0.001), 0.0022, 0.0015, axis="z", segments=10)
    return b


def raspberry_pi() -> Builder:
    """85 × 22 × 56 mm Raspberry Pi 5 SBC with rounded textured PCB, 40-pin GPIO, RF shield & stacked USB/RJ45."""
    b = Builder()
    w, d = 0.085, 0.056
    pcb_y = 0.005
    # 4 brass corner standoffs resting on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("gold", (x * (w / 2 - 0.0055), 0.002, z * (d / 2 - 0.0055)), 0.0028, 0.004, segments=12)
    # Rounded-corner green PCB + rich trace/silkscreen top decal.
    b.rounded_box("pcb_green", (0, pcb_y, 0), (w, 0.002, d), 0.0038, axis="y", corner_segs=6)
    b.decal(
        "rpi_pcb",
        textures.tex_raspberry_pi_pcb(),
        (0, pcb_y + 0.0012, 0),
        w - 0.004,
        d - 0.004,
        face="+y",
        metallic=0.14,
        roughness=0.42,
    )
    # Full 2x20 (40-pin) GPIO header along rear edge (-Z).
    b.box("bezel_dark", (-0.007, pcb_y + 0.0024, -d / 2 + 0.0045), (0.051, 0.0028, 0.0052))
    for i in range(20):
        px = -0.031 + i * 0.00254
        for pz in (-d / 2 + 0.0032, -d / 2 + 0.0058):
            b.box("gold", (px, pcb_y + 0.0062, pz), (0.00075, 0.0068, 0.00075))
    # Brushed metallic Broadcom SoC heatspreader + LPDDR4X BGA + RP1 I/O controller + stamped Wi-Fi RF shield.
    b.beveled_box("chrome", (-0.008, pcb_y + 0.0028, 0.001), (0.016, 0.0032, 0.016), bevel=0.0007)
    b.box("chip_black", (0.009, pcb_y + 0.0022, 0.002), (0.011, 0.0022, 0.014))
    b.box("chip_black", (0.011, pcb_y + 0.0020, -0.012), (0.009, 0.0018, 0.009))  # RP1 chip
    b.beveled_box("aluminum_brushed", (-0.029, pcb_y + 0.0028, -0.005), (0.013, 0.0032, 0.011), bevel=0.0006)
    # Right edge (+X): Gigabit RJ45 jack + stacked USB 3.0 (blue tongues) & USB 2.0 (black) metallic cages.
    b.beveled_box("aluminum_brushed", (w / 2 - 0.0085, pcb_y + 0.008, -0.0165), (0.021, 0.014, 0.016), bevel=0.0008)
    b.box("cavity", (w / 2 + 0.0018, pcb_y + 0.0078, -0.0165), (0.0018, 0.010, 0.012))
    b.box("gold", (w / 2 + 0.0014, pcb_y + 0.011, -0.0165), (0.0015, 0.0018, 0.008))
    b.box("led_green", (w / 2 + 0.0018, pcb_y + 0.0135, -0.0205), (0.0015, 0.002, 0.0025))
    b.box("led_amber", (w / 2 + 0.0018, pcb_y + 0.0135, -0.0125), (0.0015, 0.002, 0.0025))
    for uz, mat in ((0.0025, "usb_blue"), (0.019, "chip_black")):
        b.beveled_box("chrome", (w / 2 - 0.0065, pcb_y + 0.0085, uz), (0.017, 0.015, 0.0135), bevel=0.0008)
        for uy in (pcb_y + 0.0052, pcb_y + 0.0122):
            b.box("cavity", (w / 2 + 0.0016, uy, uz), (0.0018, 0.0048, 0.0112))
            b.box(mat, (w / 2 + 0.0019, uy + 0.0008, uz), (0.0016, 0.0016, 0.0098))
    # Front edge (+Z): USB-C power port, dual micro-HDMI metallic cages, 3.5 mm jack & CSI/DSI latches.
    b.rounded_box("chrome", (-0.030, pcb_y + 0.0032, d / 2 - 0.0025), (0.009, 0.0038, 0.0075), 0.0014, axis="z")
    b.box("cavity", (-0.030, pcb_y + 0.0032, d / 2 + 0.0013), (0.0068, 0.0022, 0.001))
    for hx in (-0.015, -0.002):
        b.box("chrome", (hx, pcb_y + 0.0029, d / 2 - 0.0025), (0.007, 0.0034, 0.007))
        b.box("cavity", (hx, pcb_y + 0.0029, d / 2 + 0.0011), (0.0054, 0.002, 0.001))
    b.cylinder("bezel_dark", (0.012, pcb_y + 0.0042, d / 2 - 0.002), 0.0032, 0.009, axis="z", segments=14)
    b.cylinder("chrome", (0.012, pcb_y + 0.0042, d / 2 + 0.0026), 0.0022, 0.0012, axis="z", segments=12)
    # Dual MIPI CSI/DSI ribbon connectors (white body + black bail) + PCIe FFC connector on left.
    b.box("white_enclosure", (-0.037, pcb_y + 0.0032, 0.002), (0.0032, 0.005, 0.022))
    b.box("bezel_dark", (-0.037, pcb_y + 0.0058, 0.002), (0.0036, 0.0014, 0.023))
    b.box("white_enclosure", (0.004, pcb_y + 0.0032, 0.016), (0.022, 0.005, 0.0032))
    b.box("bezel_dark", (0.004, pcb_y + 0.0058, 0.016), (0.023, 0.0014, 0.0036))
    return b


def rigol_dp831() -> Builder:
    """239 × 157 × 418 mm Rigol DP831 triple-output programmable DC power supply with TFT decal & binding posts."""
    b = Builder()
    w, h, d = 0.239, 0.157, 0.418
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.026), 0.006, z * (d / 2 - 0.040)), (0.028, 0.012, 0.038), 0.004, axis="y"
            )
    body_h = h - 0.012
    body_cy = 0.012 + body_h / 2
    # Rounded powder-coated light-grey main enclosure + molded dark-grey front protective bumper collar.
    b.rounded_box("light_grey", (0, body_cy, -0.004), (w, body_h, d - 0.008), 0.011, axis="z", corner_segs=6)
    b.rounded_collar(
        "panel", (0, body_cy, d / 2 - 0.004), (w + 0.006, body_h + 0.006, 0.022), 0.008, 0.013, axis="z", corner_segs=6
    )
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.006, body_h - 0.006, 0.012), 0.008, axis="z")
    fz = d / 2 + 0.0055
    # Crisp printed Rigol DP831 front panel + 3-channel backlit TFT display decal.
    b.decal(
        "rigol_dp831_front",
        textures.tex_rigol_dp831_front(),
        (0, body_cy, fz),
        w - 0.010,
        body_h - 0.010,
        face="+z",
        metallic=0.08,
        roughness=0.40,
        emissive=0.38,
    )
    # Tactile 3D rotary encoder dial aligned with the ADJUST ring on the front decal.
    b.cylinder("rubber", (0.034, body_cy + 0.022, fz + 0.008), 0.014, 0.016, axis="z", segments=20)
    b.cylinder("aluminum_brushed", (0.034, body_cy + 0.022, fz + 0.0165), 0.0105, 0.003, axis="z", segments=20)
    # 3D physical softkeys & numeric keypad micro-caps subtly raised off the bezel.
    b.box("led_green", (-0.094, 0.032, fz + 0.003), (0.014, 0.012, 0.005))  # mains power switch
    b.box("chrome", (-0.072, 0.032, fz + 0.002), (0.011, 0.0055, 0.003))  # front USB host
    # 6 realistic 4mm banana binding posts (CH1 +8V/-, GND, CH2 +30V/-, CH3 -30V) with hex collar & gold core.
    posts = (
        (-0.044, "yellow_terminal"),
        (-0.022, "rubber"),
        (0.002, "green_terminal"),
        (0.028, "red_terminal"),
        (0.050, "rubber"),
        (0.078, "accent"),
    )
    for px, mat in posts:
        b.cylinder("aluminum_brushed", (px, 0.032, fz + 0.002), 0.0082, 0.004, axis="z", segments=12)
        b.cylinder(mat, (px, 0.032, fz + 0.0105), 0.0072, 0.015, axis="z", segments=16)
        b.cylinder("gold", (px, 0.032, fz + 0.0185), 0.0036, 0.0025, axis="z", segments=12)
        b.cylinder("cavity", (px, 0.032, fz + 0.0198), 0.0022, 0.001, axis="z", segments=10)
    # Side cooling louver slots & rear fan/IEC socket.
    for side in (-1, 1):
        for i in range(6):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.044 + i * 0.015, -0.01), (0.002, 0.0055, 0.19))
    b.cylinder("cavity", (-0.045, body_cy, -d / 2 - 0.001), 0.038, 0.004, axis="z")
    b.box("bezel_dark", (0.055, body_cy - 0.015, -d / 2 - 0.002), (0.032, 0.024, 0.004))
    return b


def toellner_toe8952() -> Builder:
    """320 × 104 × 340 mm Toellner TOE 8952 precision German lab DC power supply with dual LED meters & safety jacks."""
    b = Builder()
    w, h, d = 0.320, 0.104, 0.340
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.028), 0.005, z * (d / 2 - 0.035)), (0.026, 0.010, 0.032), 0.004, axis="y"
            )
    body_h = h - 0.010
    body_cy = 0.010 + body_h / 2
    # Classic German light-grey rounded aluminum housing with metallic front rim.
    b.rounded_box("light_grey", (0, body_cy, -0.003), (w, body_h, d - 0.006), 0.008, axis="z", corner_segs=6)
    b.rounded_box("aluminum_brushed", (0, body_cy, d / 2 - 0.002), (w - 0.004, body_h - 0.004, 0.010), 0.006, axis="z")
    fz = d / 2 + 0.0035
    # Crisp printed Toellner TOE 8952 front panel decal (green 13.80V & amber 02.45A 7-seg readouts + scales).
    b.decal(
        "toellner_8952_front",
        textures.tex_toellner_8952_front(),
        (0, body_cy, fz),
        w - 0.008,
        body_h - 0.008,
        face="+z",
        metallic=0.14,
        roughness=0.42,
        emissive=0.30,
    )
    # Twin precision Voltage & Current 3D rotary knobs aligned over the arc scales on the front panel.
    for kx in (0.026, 0.075):
        b.cylinder("bezel_dark", (kx, body_cy + 0.004, fz + 0.009), 0.013, 0.018, axis="z", segments=20)
        b.cylinder("aluminum_brushed", (kx, body_cy + 0.004, fz + 0.0185), 0.010, 0.0025, axis="z", segments=20)
        b.box("white_enclosure", (kx, body_cy + 0.011, fz + 0.0195), (0.002, 0.006, 0.0015))
    # Lower-left green illuminated mains rocker switch.
    b.box("bezel_dark", (-0.126, 0.025, fz + 0.003), (0.022, 0.016, 0.006))
    b.box("led_green", (-0.126, 0.025, fz + 0.0065), (0.015, 0.010, 0.0025))
    # 4 recessed 4mm safety banana sockets (+ SENSE, + OUT, PE, - OUT) aligned with silkscreen labels.
    toe_posts = (
        (0.022, "red_terminal"),
        (0.056, "red_terminal"),
        (0.088, "green_terminal"),
        (0.118, "bezel_dark"),
    )
    for px, mat in toe_posts:
        b.cylinder(mat, (px, 0.024, fz + 0.0065), 0.0072, 0.013, axis="z", segments=16)
        b.cylinder("cavity", (px, 0.024, fz + 0.0132), 0.0044, 0.0015, axis="z", segments=12)
        b.cylinder("gold", (px, 0.024, fz + 0.0125), 0.0020, 0.003, axis="z", segments=10)
    # Rear cooling fan grille & remote GPIB/RS-232 interface.
    b.cylinder("cavity", (-0.070, body_cy, -d / 2 - 0.001), 0.032, 0.004, axis="z")
    b.box("chrome", (0.068, body_cy, -d / 2 - 0.003), (0.052, 0.024, 0.006))
    return b


def embedded_test_rack() -> Builder:
    """1400 × 1900 × 1060 mm empty 4-bench automotive embedded test rack ready for benches & device placement."""
    b = Builder()
    w, h, d_cab = 1.40, 1.90, 0.82
    zc = -0.10  # shift cabinet slightly rear so cantilevered pull-out trays stay centred around z = 0
    front_z = zc + d_cab / 2  # +0.31 m
    back_z = zc - d_cab / 2  # -0.51 m
    # Leveling rubber plinth base resting flush on y = 0 + warm beige industrial open-front enclosure.
    b.box("rubber", (0, 0.015, zc), (w - 0.04, 0.03, d_cab - 0.04))
    b.beveled_box("rack_beige", (0, 0.048, zc), (w, 0.038, d_cab), bevel=0.004)  # base deck
    b.beveled_box("rack_beige", (0, h - 0.02, zc), (w, 0.04, d_cab), bevel=0.004)  # top roof
    for sx in (-1, 1):
        b.beveled_box("rack_beige", (sx * (w / 2 - 0.022), h / 2 + 0.015, zc), (0.044, h - 0.05, d_cab), bevel=0.003)
        # Interior vertical brushed-aluminum T-slot mounting rails (front & rear).
        for rz in (front_z - 0.055, back_z + 0.085):
            b.box("aluminum_brushed", (sx * (w / 2 - 0.050), h / 2 + 0.015, rz), (0.014, h - 0.12, 0.024))
    # Rear structural panel with vertical cable-management comb ducts & ventilation louvers.
    b.box("rack_beige", (0, h / 2 + 0.015, back_z + 0.02), (w - 0.088, h - 0.05, 0.038))
    for cx in (-0.34, 0.34):
        b.box("panel", (cx, h / 2 + 0.015, back_z + 0.048), (0.045, h - 0.14, 0.024))
    for i in range(6):
        b.box("cavity", (0, 1.60 + i * 0.032, back_z + 0.041), (0.52, 0.012, 0.004))
        b.box("cavity", (0, 0.14 + i * 0.026, back_z + 0.041), (0.52, 0.010, 0.004))
    # Overhead interior LED task light bar beneath roof.
    b.box("bezel_dark", (0, h - 0.048, zc + 0.12), (w - 0.24, 0.018, 0.044))
    b.box("led_white", (0, h - 0.058, zc + 0.12), (w - 0.28, 0.006, 0.030))
    # Integrated rear rack PDU power strips (upper & lower bays) with AC outlets.
    for pdu_y in (1.16, 0.70):
        b.box("bezel_dark", (0, pdu_y, back_z + 0.058), (w - 0.22, 0.044, 0.036))
        for i in range(8):
            b.box("socket", (-0.49 + i * 0.14, pdu_y, back_z + 0.077), (0.038, 0.028, 0.004))
        b.box("red_terminal", (0.54, pdu_y, back_z + 0.077), (0.022, 0.024, 0.006))  # main breaker switch
    # Empty interior equipment shelves (top PC bay, upper PSU bay, lower PSU bay) with front lip trim.
    for sy in (1.50, 1.07, 0.61):
        b.box("rack_beige", (0, sy, zc - 0.01), (w - 0.096, 0.026, d_cab - 0.08))
        b.box("aluminum_brushed", (0, sy, front_z - 0.045), (w - 0.096, 0.028, 0.012))
    # Heavy brushed-aluminum monitor mounting crossbar with end clamp blocks & dual empty VESA slide mounts.
    b.beveled_box("aluminum_brushed", (0, 1.46, front_z - 0.025), (w - 0.10, 0.058, 0.046), bevel=0.004)
    for bx in (-w / 2 + 0.095, w / 2 - 0.095):
        b.box("steel", (bx, 1.46, front_z - 0.005), (0.070, 0.064, 0.058))
        b.cylinder("chrome", (bx, 1.46, front_z + 0.028), 0.011, 0.014, axis="z")
    for vx in (-0.32, 0.32):
        b.box("bezel_dark", (vx, 1.43, front_z + 0.008), (0.095, 0.095, 0.014))  # empty VESA mount plate
        b.box("steel", (vx, 1.46, front_z - 0.002), (0.048, 0.070, 0.022))  # rail clamp
    # Empty cantilevered pull-out ESD worktop / keyboard tray at y = 0.88 (surface top = 0.908 m).
    kb_z_front = 0.51
    b.box("rack_beige", (0, 0.892, 0.21), (w - 0.10, 0.024, 0.58))
    b.box("esd_mat", (0, 0.906, 0.21), (w - 0.14, 0.004, 0.52))  # anti-static worktop surface at y = 0.908 m
    b.beveled_box("rack_beige", (0, 0.888, kb_z_front), (w - 0.08, 0.054, 0.020), bevel=0.003)
    b.rounded_box("aluminum_brushed", (0, 0.888, kb_z_front + 0.020), (0.28, 0.012, 0.012), 0.004, axis="x")
    for hx in (-0.125, 0.125):
        b.box("aluminum_brushed", (hx, 0.888, kb_z_front + 0.012), (0.014, 0.012, 0.014))
    for sx in (-1, 1):
        b.box("aluminum_brushed", (sx * (w / 2 - 0.054), 0.884, 0.18), (0.016, 0.044, 0.64))  # telescopic drawer slide
        b.cylinder("chrome", (sx * (w / 2 - 0.044), 0.884, kb_z_front - 0.03), 0.006, 0.006, axis="x", segments=10)
    # Empty cantilevered pull-out green ESD DUT test tray at y = 0.36 (ready for Vector / Lauterbach / ECU rigs).
    dut_z_front = 0.52
    b.box("rack_beige", (0, 0.365, 0.21), (w - 0.10, 0.020, 0.60))
    b.box("pcb_green", (0, 0.379, 0.21), (w - 0.14, 0.008, 0.54))  # clean ESD DUT mounting deck
    b.beveled_box("rack_beige", (0, 0.380, dut_z_front), (w - 0.08, 0.060, 0.020), bevel=0.003)
    b.rounded_box("aluminum_brushed", (0, 0.380, dut_z_front + 0.020), (0.28, 0.012, 0.012), 0.004, axis="x")
    for hx in (-0.125, 0.125):
        b.box("aluminum_brushed", (hx, 0.380, dut_z_front + 0.012), (0.014, 0.012, 0.014))
    for sx in (-1, 1):
        b.box("aluminum_brushed", (sx * (w / 2 - 0.054), 0.374, 0.18), (0.016, 0.046, 0.66))  # telescopic drawer slide
        b.cylinder("chrome", (sx * (w / 2 - 0.044), 0.374, dut_z_front - 0.03), 0.006, 0.006, axis="x", segments=10)
    return b


def vector_vt_system() -> Builder:
    """482 × 132 × 360 mm Vector VT System (VT8012A) 3U modular HIL test chassis with 8 VT slot blades."""
    b = Builder()
    w, h, d = 0.442, 0.132, 0.360
    # 3U rack/bench chassis standing cleanly on y = 0 with crimson Vector side accents.
    b.beveled_box("bezel_dark", (0, h / 2, 0), (w, h, d), bevel=0.003)
    for side in (-1, 1):
        b.beveled_box(
            "aluminum_brushed", (side * (w / 2 + 0.010), h / 2, d / 2 - 0.006), (0.020, h - 0.006, 0.008), bevel=0.001
        )
        b.box("vector_red", (side * (w / 2 - 0.004), h / 2, d / 2 + 0.003), (0.008, h - 0.010, 0.008))
        # Brushed aluminum 3U rack pull handles.
        b.rounded_box(
            "aluminum_brushed",
            (side * (w / 2 + 0.010), h / 2, d / 2 + 0.022),
            (0.010, h - 0.038, 0.010),
            0.003,
            axis="y",
        )
        for hy in (0.024, h - 0.024):
            b.box("aluminum_brushed", (side * (w / 2 + 0.010), hy, d / 2 + 0.010), (0.010, 0.012, 0.018))
    # High-DPI Vector VT8012A modular slot faceplate decal.
    fz = d / 2 + 0.0006
    b.decal(
        "vt_system_front",
        textures.tex_vt_system_front(),
        (0, h / 2, fz),
        w - 0.018,
        h - 0.006,
        face="+z",
        metallic=0.22,
        roughness=0.40,
    )
    # 8 physical green Phoenix terminal blocks & ejector latches across the 8 VT card slots.
    for i in range(8):
        bx = -0.184 + i * 0.0525
        b.beveled_box("phoenix_green", (bx, 0.036, fz + 0.0045), (0.028, 0.050, 0.009), bevel=0.001)
        for p in range(5):
            b.cylinder("chrome", (bx - 0.006, 0.018 + p * 0.009, fz + 0.0092), 0.0020, 0.0015, axis="z", segments=8)
        # Card top/bottom knurled thumbscrews.
        for ty in (0.008, 0.098):
            b.cylinder("chrome", (bx + 0.016, ty, fz + 0.0035), 0.0028, 0.007, axis="z", segments=10)
    # Rear cooling fan array & power inlet.
    for fx in (-0.12, 0.0, 0.12):
        b.cylinder("cavity", (fx, h / 2, -d / 2 - 0.001), 0.042, 0.004, axis="z", segments=18)
    return b


def segger_jlink() -> Builder:
    """112 × 28 × 72 mm SEGGER J-Link PRO JTAG/SWD Ethernet debug probe with iconic green/white top decal."""
    b = Builder()
    w, h, d = 0.112, 0.028, 0.072
    # Low rubber pad feet standing on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (w / 2 - 0.012), 0.0015, z * (d / 2 - 0.010)), 0.0055, 0.003, segments=12)
    body_h = h - 0.003
    body_cy = 0.003 + body_h / 2
    # Matte-black sleek rounded-corner SEGGER debugger body.
    b.rounded_box("bezel_dark", (0, body_cy, 0), (w, body_h, d), 0.008, axis="y", corner_segs=7)
    b.rounded_box("segger_green", (0, body_cy, 0), (w + 0.0012, 0.0035, d + 0.0012), 0.0082, axis="y", corner_segs=7)
    # Crisp SEGGER J-Link PRO green & white top label decal.
    b.decal(
        "segger_top",
        textures.tex_segger_jlink_top(),
        (0, h + 0.0004, 0),
        w - 0.008,
        d - 0.008,
        face="+y",
        metallic=0.04,
        roughness=0.38,
    )
    # Front (+Z): Shrouded 20-pin 0.1" ARM JTAG/SWD ribbon header with key notch & gold pins.
    fz = d / 2
    b.beveled_box("chip_black", (0, body_cy, fz + 0.005), (0.036, 0.013, 0.011), bevel=0.001)
    b.box("cavity", (0, body_cy, fz + 0.0102), (0.030, 0.009, 0.002))
    for p in range(10):
        px = -0.0115 + p * 0.00254
        for dy in (-0.002, 0.002):
            b.box("gold", (px, body_cy + dy, fz + 0.0105), (0.0008, 0.0008, 0.0045))
    # Rear (-Z): RJ45 100M Ethernet jack + USB-B host receptacle.
    rz = -d / 2
    b.box("chrome", (-0.022, body_cy, rz - 0.0025), (0.017, 0.014, 0.006))
    b.box("cavity", (-0.022, body_cy, rz - 0.0052), (0.013, 0.010, 0.0018))
    b.box("led_green", (-0.028, body_cy + 0.006, rz - 0.0052), (0.003, 0.002, 0.0015))
    b.box("chrome", (0.022, body_cy, rz - 0.0025), (0.014, 0.012, 0.006))
    b.box("cavity", (0.022, body_cy, rz - 0.0052), (0.009, 0.008, 0.0018))
    return b


def fluke_multimeter() -> Builder:
    """98 × 192 × 88 mm Fluke 87V Industrial True-RMS handheld multimeter tilted cleanly on its kickstand."""
    b = Builder()
    w, bh, bd = 0.098, 0.194, 0.048
    tilt = 0.30  # ~17.2 deg ergonomic bench viewing angle
    # Compute centre height so the lowest front corner of the yellow protective holster rests at exact y = 0.
    cy = (bh / 2) * math.cos(tilt) + (bd / 2) * math.sin(tilt)
    cz = 0.008
    # Iconic thick Fluke yellow protective rubber holster + dark charcoal inner body.
    b.rotated_box("fluke_yellow", (0, cy, cz), (w, bh, bd), rx=-tilt)
    b.rotated_box("bezel_dark", (0, cy, cz + 0.004), (w - 0.012, bh - 0.016, bd - 0.004), rx=-tilt)
    # Compute surface helper in local tilted coordinates (ly along length, lz normal out of front face).
    ct, st = math.cos(tilt), math.sin(tilt)

    def face_pos(lx: float, ly: float, lz: float) -> Vec:
        return (lx, cy + ly * ct + lz * st, cz - ly * st + lz * ct)

    # Crisp printed Fluke 87V front face decal (LCD 12.04 V, keys, range dial legends, socket markings).
    b.decal(
        "fluke_front",
        textures.tex_fluke_dmm_front(),
        face_pos(0.0, 0.0, bd / 2 + 0.0028),
        w - 0.014,
        bh - 0.018,
        face="+z",
        rx=-tilt,
        metallic=0.05,
        roughness=0.42,
        emissive=0.18,
    )
    # 3D sculpted yellow/charcoal central rotary range selector dial & pointer ridge.
    dial_y = -0.015
    b.rotated_cylinder(
        "bezel_dark", face_pos(0.0, dial_y, bd / 2 + 0.007), 0.021, 0.010, rx=math.pi / 2 - tilt, segments=20
    )
    b.rotated_box("fluke_yellow", face_pos(0.0, dial_y, bd / 2 + 0.013), (0.007, 0.036, 0.007), rx=-tilt, rz=0.58)
    # 4 recessed 4mm shrouded safety test-lead sockets (10A, 400mA, COM, V/Ohm) along lower face.
    for i, smat in enumerate(("red_terminal", "red_terminal", "bezel_dark", "red_terminal")):
        sx = -0.0285 + i * 0.019
        b.rotated_cylinder(
            smat, face_pos(sx, -0.068, bd / 2 + 0.004), 0.0062, 0.006, rx=math.pi / 2 - tilt, segments=14
        )
        b.rotated_cylinder(
            "cavity", face_pos(sx, -0.068, bd / 2 + 0.0072), 0.0038, 0.0015, rx=math.pi / 2 - tilt, segments=12
        )
    # Rear folding dark-grey tilt kickstand resting squarely on y = 0 behind body.
    b.rotated_box("bezel_dark", (0, 0.056, -0.036), (0.044, 0.112, 0.008), rx=0.22)
    b.box("rubber", (0, 0.004, -0.046), (0.046, 0.008, 0.012))
    return b


def waveform_generator() -> Builder:
    """261 × 104 × 304 mm Keysight 33522B / Rigol DG4000 dual-channel arbitrary waveform generator."""
    b = Builder()
    w, h, d = 0.261, 0.104, 0.304
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.025), 0.005, z * (d / 2 - 0.032)), (0.026, 0.010, 0.030), 0.004, axis="y"
            )
    body_h = h - 0.010
    body_cy = 0.010 + body_h / 2
    b.rounded_box("light_grey", (0, body_cy, -0.003), (w, body_h, d - 0.006), 0.009, axis="z", corner_segs=6)
    b.rounded_collar(
        "panel", (0, body_cy, d / 2 - 0.003), (w + 0.006, body_h + 0.006, 0.020), 0.007, 0.011, axis="z", corner_segs=6
    )
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.006, body_h - 0.006, 0.010), 0.007, axis="z")
    fz = d / 2 + 0.0045
    b.decal(
        "awg_front",
        textures.tex_awg_front(),
        (0, body_cy, fz),
        w - 0.010,
        body_h - 0.010,
        face="+z",
        metallic=0.08,
        roughness=0.40,
        emissive=0.42,
    )
    # Tactile frequency/amplitude rotary encoder dial aligned with front decal.
    b.cylinder("rubber", (0.097, body_cy + 0.015, fz + 0.007), 0.013, 0.014, axis="z", segments=18)
    b.cylinder("aluminum_brushed", (0.097, body_cy + 0.015, fz + 0.0145), 0.0095, 0.003, axis="z", segments=18)
    # Power key + 3 metallic BNC outputs (SYNC, CH1 OUT Yellow, CH2 OUT Cyan).
    b.box("led_green", (-0.104, 0.024, fz + 0.002), (0.013, 0.010, 0.004))
    for bx, ring_mat in ((0.025, "aluminum_brushed"), (0.062, "yellow_terminal"), (0.098, "accent")):
        b.cylinder(ring_mat, (bx, 0.024, fz + 0.002), 0.0095, 0.004, axis="z", segments=14)
        b.cylinder("chrome", (bx, 0.024, fz + 0.010), 0.0065, 0.014, axis="z", segments=14)
        b.cylinder("cavity", (bx, 0.024, fz + 0.0172), 0.0040, 0.0015, axis="z", segments=12)
        b.cylinder("gold", (bx, 0.024, fz + 0.0165), 0.0014, 0.004, axis="z", segments=10)
    for side in (-1, 1):
        for i in range(4):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.032 + i * 0.014, -0.02), (0.002, 0.005, 0.14))
    return b


def electronic_dc_load() -> Builder:
    """255 × 118 × 370 mm ITECH IT8512A+ / Rigol DL3021 programmable DC electronic load."""
    b = Builder()
    w, h, d = 0.255, 0.118, 0.370
    for x in (-1, 1):
        for z in (-1, 1):
            b.rounded_box(
                "rubber", (x * (w / 2 - 0.026), 0.006, z * (d / 2 - 0.038)), (0.026, 0.012, 0.034), 0.004, axis="y"
            )
    body_h = h - 0.012
    body_cy = 0.012 + body_h / 2
    b.rounded_box("light_grey", (0, body_cy, -0.004), (w, body_h, d - 0.008), 0.009, axis="z", corner_segs=6)
    b.rounded_collar(
        "bezel_dark",
        (0, body_cy, d / 2 - 0.004),
        (w + 0.006, body_h + 0.006, 0.020),
        0.007,
        0.011,
        axis="z",
        corner_segs=6,
    )
    b.rounded_box("bezel_dark", (0, body_cy, d / 2 - 0.001), (w - 0.006, body_h - 0.006, 0.010), 0.007, axis="z")
    fz = d / 2 + 0.0045
    b.decal(
        "dc_load_front",
        textures.tex_dc_load_front(),
        (0, body_cy, fz),
        w - 0.010,
        body_h - 0.010,
        face="+z",
        metallic=0.08,
        roughness=0.40,
        emissive=0.45,
    )
    # Precision rotary setting knob & power switch.
    b.cylinder("rubber", (0.038, body_cy + 0.014, fz + 0.007), 0.013, 0.014, axis="z", segments=18)
    b.cylinder("aluminum_brushed", (0.038, body_cy + 0.014, fz + 0.0145), 0.0095, 0.003, axis="z", segments=18)
    b.box("led_green", (-0.100, 0.026, fz + 0.003), (0.014, 0.012, 0.005))
    # Oversized heavy-duty 30A high-current red (+) and black (-) knurled screw terminals + remote sense posts.
    for sx, smat in ((0.026, "red_terminal"), (0.044, "bezel_dark")):
        b.cylinder(smat, (sx, 0.026, fz + 0.006), 0.0045, 0.010, axis="z", segments=12)
    for tx, tmat in ((0.072, "red_terminal"), (0.104, "bezel_dark")):
        b.cylinder("aluminum_brushed", (tx, 0.026, fz + 0.003), 0.0115, 0.006, axis="z", segments=16)
        b.cylinder(tmat, (tx, 0.026, fz + 0.014), 0.0105, 0.018, axis="z", segments=16)
        b.cylinder("copper", (tx, 0.026, fz + 0.024), 0.0052, 0.004, axis="z", segments=12)
    # Heavy rear heatsink & dual exhaust fans for 300W load dissipation.
    for side in (-1, 1):
        for i in range(5):
            b.box("cavity", (side * (w / 2 + 0.0005), 0.034 + i * 0.015, -0.02), (0.002, 0.006, 0.20))
    for fx in (-0.055, 0.055):
        b.cylinder("cavity", (fx, body_cy, -d / 2 - 0.001), 0.036, 0.004, axis="z", segments=18)
    return b


def stereo_microscope() -> Builder:
    """260 × 410 × 310 mm trinocular PCB inspection stereo microscope with LED ring light & dual eyepieces."""
    b = Builder()
    bw, bd = 0.26, 0.30
    # 4 low rubber feet standing cleanly on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("rubber", (x * (bw / 2 - 0.025), 0.004, z * (bd / 2 - 0.025)), 0.014, 0.008, segments=12)
    # Weighted white/grey ESD inspection stage base + circular black/white specimen disc & chrome stage clips.
    b.rounded_box("white_enclosure", (0, 0.020, 0), (bw, 0.024, bd), 0.014, axis="y", corner_segs=6)
    b.cylinder("bezel_dark", (0, 0.0335, 0.038), 0.052, 0.004, segments=24)
    b.cylinder("white_enclosure", (0, 0.0345, 0.038), 0.044, 0.003, segments=24)
    for sx in (-0.068, 0.068):
        b.box("chrome", (sx, 0.036, 0.038), (0.042, 0.003, 0.008))
        b.cylinder("chrome", (sx * 1.28, 0.038, 0.038), 0.005, 0.008, segments=10)
    # Vertical solid chrome steel support pillar at rear (-Z).
    col_z = -0.105
    b.cylinder("bezel_dark", (0, 0.042, col_z), 0.026, 0.020, segments=18)
    b.cylinder("chrome", (0, 0.202, col_z), 0.015, 0.310, segments=20)
    b.cylinder("bezel_dark", (0, 0.358, col_z), 0.016, 0.008, segments=16)  # top end cap
    # Focusing carriage collar, horizontal arm & dual large knurled focus handwheels.
    focus_y = 0.235
    b.rounded_box("white_enclosure", (0, focus_y, col_z + 0.048), (0.056, 0.064, 0.125), 0.008, axis="x")
    b.cylinder("chrome", (0, focus_y, col_z + 0.045), 0.008, 0.118, axis="x", segments=14)
    for kx in (-0.058, 0.058):
        b.cylinder("bezel_dark", (kx, focus_y, col_z + 0.045), 0.024, 0.016, axis="x", segments=20)
        b.cylinder("aluminum_brushed", (kx * 1.15, focus_y, col_z + 0.045), 0.015, 0.006, axis="x", segments=16)
    # Optical zoom head housing centered above specimen stage (z = +0.035).
    head_z = 0.035
    b.cylinder("white_enclosure", (0, 0.232, head_z), 0.042, 0.092, segments=20)
    b.cylinder("bezel_dark", (0, 0.178, head_z), 0.032, 0.028, segments=18)  # objective lens barrel
    # Glowing 56-LED ring light collar around objective bottom.
    b.cylinder("bezel_dark", (0, 0.156, head_z), 0.042, 0.018, segments=20)
    b.cylinder("led_white", (0, 0.146, head_z), 0.036, 0.004, segments=20)
    # Zoom magnification knobs on left/right sides of optical head.
    for zx in (-0.046, 0.046):
        b.cylinder("bezel_dark", (zx, 0.228, head_z), 0.016, 0.012, axis="x", segments=16)
    # Upper angled binocular prism head + twin ergonomic 45-degree eyepieces facing +Z.
    b.rotated_box("white_enclosure", (0, 0.288, head_z + 0.012), (0.096, 0.056, 0.072), rx=0.42)
    for ex in (-0.030, 0.030):
        b.rotated_cylinder("bezel_dark", (ex, 0.326, head_z + 0.058), 0.015, 0.078, rx=0.78, segments=16)
        b.rotated_cylinder("rubber", (ex, 0.352, head_z + 0.084), 0.0175, 0.018, rx=0.78, segments=16)
        b.rotated_cylinder("glass", (ex, 0.359, head_z + 0.091), 0.011, 0.004, rx=0.78, segments=14)
    # Top vertical trinocular C-mount digital camera port & compact HDMI inspection camera cube.
    b.cylinder("bezel_dark", (0, 0.342, head_z - 0.004), 0.018, 0.064, segments=18)
    b.beveled_box("weller_teal", (0, 0.392, head_z - 0.004), (0.052, 0.038, 0.052), bevel=0.004)
    return b


def stm32_nucleo_board() -> Builder:
    """70 × 19 × 133 mm STMicroelectronics STM32 Nucleo-144 MCU development board (NUCLEO-H743ZI2)."""
    b = Builder()
    w, d = 0.070, 0.133
    pcb_y = 0.005
    # 4 corner brass standoffs resting on y = 0.
    for x in (-1, 1):
        for z in (-1, 1):
            b.cylinder("gold", (x * (w / 2 - 0.005), 0.002, z * (d / 2 - 0.006)), 0.0024, 0.004, segments=10)
    # Iconic matte-white STM32 Nucleo PCB + high-DPI white silkscreen top decal.
    b.rounded_box("nucleo_white", (0, pcb_y, 0), (w, 0.0018, d), 0.0025, axis="y", corner_segs=5)
    b.decal(
        "nucleo_pcb",
        textures.tex_stm32_nucleo_pcb(),
        (0, pcb_y + 0.0011, 0),
        w - 0.003,
        d - 0.003,
        face="+y",
        metallic=0.06,
        roughness=0.40,
    )
    # Upper snap-off ST-LINK/V3E debugger section (-Z end): MCU, USB-C/Micro port & 6-pin SWD header.
    b.box("chip_black", (0.006, pcb_y + 0.002, -0.046), (0.011, 0.002, 0.011))
    b.box("chrome", (0, pcb_y + 0.0026, -d / 2 + 0.004), (0.009, 0.0035, 0.007))
    b.box("bezel_dark", (-0.018, pcb_y + 0.003, -0.044), (0.005, 0.004, 0.016))
    # Central 45-degree rotated LQFP144 STM32H7 microcontroller package (signature Nucleo look!).
    b.rotated_box("chip_black", (0, pcb_y + 0.0024, 0.002), (0.020, 0.0024, 0.020), ry=math.pi / 4)
    b.rotated_box("chrome", (0, pcb_y + 0.0015, 0.002), (0.0225, 0.0010, 0.0225), ry=math.pi / 4)
    # Dual long black ST Morpho & Arduino Zio female header banks along left & right edges.
    for side in (-1, 1):
        b.box("bezel_dark", (side * 0.029, pcb_y + 0.005, 0.006), (0.005, 0.0085, 0.072))
        b.box("bezel_dark", (side * 0.021, pcb_y + 0.005, 0.006), (0.003, 0.0085, 0.062))
        for p in range(16):
            b.box("gold", (side * 0.029, pcb_y + 0.0098, -0.026 + p * 0.0042), (0.0012, 0.0012, 0.0012))
    # Iconic Blue USER push-button (B1) & Black RESET push-button (B2) + 3 status LEDs (LD1/LD2/LD3).
    b.box("white_enclosure", (-0.013, pcb_y + 0.0026, 0.036), (0.007, 0.003, 0.007))
    b.cylinder("usb_blue", (-0.013, pcb_y + 0.0055, 0.036), 0.0024, 0.004, segments=12)
    b.box("white_enclosure", (0.013, pcb_y + 0.0026, 0.036), (0.007, 0.003, 0.007))
    b.cylinder("bezel_dark", (0.013, pcb_y + 0.0055, 0.036), 0.0024, 0.004, segments=12)
    for lx, lmat in ((-0.008, "led_green"), (0.0, "led_cyan"), (0.008, "led_red")):
        b.box(lmat, (lx, pcb_y + 0.002, 0.024), (0.0028, 0.0016, 0.0028))
    # Front edge (+Z): Full-size metallic RJ45 Ethernet jack & USB OTG port.
    b.beveled_box("aluminum_brushed", (-0.012, pcb_y + 0.0075, d / 2 - 0.010), (0.016, 0.0135, 0.020), bevel=0.0008)
    b.box("cavity", (-0.012, pcb_y + 0.0075, d / 2 + 0.0004), (0.012, 0.0095, 0.0015))
    b.rounded_box("chrome", (0.014, pcb_y + 0.003, d / 2 - 0.0035), (0.009, 0.0038, 0.007), 0.0012, axis="z")
    return b


def automotive_ecu_dut() -> Builder:
    """196 × 42 × 140 mm die-cast finned automotive ADAS / powertrain ECU DUT with TE bulkhead & FAKRA ports."""
    b = Builder()
    w, h, d = 0.172, 0.038, 0.128
    # 4 corner die-cast mounting flange ears with bolt holes resting flush on y = 0.
    for sx in (-1, 1):
        for sz in (-1, 1):
            b.rounded_box(
                "cast_aluminum",
                (sx * (w / 2 + 0.007), 0.0045, sz * (d / 2 - 0.014)),
                (0.020, 0.009, 0.022),
                0.005,
                axis="y",
            )
            b.cylinder("cavity", (sx * (w / 2 + 0.010), 0.005, sz * (d / 2 - 0.014)), 0.0042, 0.010, segments=12)
    # Main bead-blasted die-cast aluminum ECU enclosure with cooling ribs along side flanks.
    b.beveled_box("cast_aluminum", (0, h / 2, 0), (w, h, d), bevel=0.004)
    for i in range(9):
        rz = -0.048 + i * 0.012
        b.box("cast_aluminum", (0, h + 0.0025, rz), (w - 0.016, 0.005, 0.0045))
    # Raised flat center nameplate deck + crisp industrial automotive ECU asset label decal.
    b.beveled_box("aluminum_brushed", (0, h + 0.0035, 0), (w - 0.038, 0.005, d - 0.032), bevel=0.0015)
    b.decal(
        "ecu_dut_top",
        textures.tex_ecu_dut_top(),
        (0, h + 0.0063, 0),
        w - 0.044,
        d - 0.038,
        face="+y",
        metallic=0.12,
        roughness=0.40,
    )
    # Front (+Z): Heavy multi-pin black TE Automotive / Bosch bulkhead harness connector with gold pin arrays.
    fz = d / 2
    b.beveled_box("bezel_dark", (-0.018, h / 2 - 0.001, fz + 0.011), (0.094, 0.027, 0.022), bevel=0.002)
    b.box("cavity", (-0.018, h / 2 - 0.001, fz + 0.021), (0.084, 0.019, 0.003))
    for p in range(14):
        px = -0.055 + p * 0.0057
        for py in (h / 2 - 0.005, h / 2, h / 2 + 0.005):
            b.box("gold", (px, py, fz + 0.020), (0.0012, 0.0012, 0.006))
    # Dual high-speed automotive FAKRA coaxial connectors (Water Blue & Crimson) on right of front face.
    for fx, fmat in ((0.046, "fakra_blue"), (0.068, "vector_red")):
        b.rounded_box(fmat, (fx, h / 2 - 0.001, fz + 0.010), (0.015, 0.016, 0.020), 0.002, axis="z")
        b.cylinder("chrome", (fx, h / 2 - 0.001, fz + 0.020), 0.0046, 0.003, axis="z", segments=14)
        b.cylinder("gold", (fx, h / 2 - 0.001, fz + 0.021), 0.0015, 0.004, axis="z", segments=10)
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
    # Embedded systems lab components
    ReferenceModel("dc-power-supply", "Reference · Programmable DC power supply", dc_power_supply),
    ReferenceModel("oscilloscope", "Reference · Mixed-signal oscilloscope", oscilloscope),
    ReferenceModel("logic-analyzer-debugger", "Reference · JTAG debugger & logic analyzer", logic_analyzer_debugger),
    ReferenceModel("embedded-dev-kit", "Reference · Embedded dev board & DUT rig", embedded_dev_kit),
    ReferenceModel("network-switch", "Reference · Managed network switch 1U", network_switch),
    ReferenceModel("hil-test-rack", "Reference · HIL test cabinet", hil_test_rack, surface=round(0.983 / 2.07, 3)),
    ReferenceModel("soldering-rework-station", "Reference · Soldering & rework station", soldering_rework_station),
    ReferenceModel("thermal-chamber", "Reference · Environmental test chamber", thermal_chamber),
    ReferenceModel("rack-ups-pdu", "Reference · Rack UPS & power distribution", rack_ups_pdu),
    ReferenceModel("rf-signal-analyzer", "Reference · RF spectrum & signal analyzer", rf_signal_analyzer),
    # Specific automotive & embedded hardware reference models
    ReferenceModel("vector-vn1630a", "Reference · Vector VN1630A CAN/LIN interface", vector_vn1630a),
    ReferenceModel("vector-vn5620", "Reference · Vector VN5620 Ethernet/CAN interface", vector_vn5620),
    ReferenceModel("vector-vt-system", "Reference · Vector VT System HIL chassis", vector_vt_system),
    ReferenceModel("lauterbach-powerdebug", "Reference · Lauterbach TRACE32 PowerDebug", lauterbach_powerdebug),
    ReferenceModel("segger-jlink", "Reference · SEGGER J-Link PRO debugger", segger_jlink),
    ReferenceModel("raspberry-pi", "Reference · Raspberry Pi SBC", raspberry_pi),
    ReferenceModel("stm32-nucleo-board", "Reference · STM32 Nucleo-144 dev board", stm32_nucleo_board),
    ReferenceModel("automotive-ecu-dut", "Reference · Automotive ADAS ECU DUT", automotive_ecu_dut),
    ReferenceModel("rigol-dp831", "Reference · Rigol DP831 DC power supply", rigol_dp831),
    ReferenceModel("toellner-toe8952", "Reference · Toellner TOE 8952 DC power supply", toellner_toe8952),
    ReferenceModel("electronic-dc-load", "Reference · ITECH IT8512A+ DC electronic load", electronic_dc_load),
    ReferenceModel("waveform-generator", "Reference · Keysight 33522B waveform generator", waveform_generator),
    ReferenceModel("fluke-multimeter", "Reference · Fluke 87V digital multimeter", fluke_multimeter),
    ReferenceModel("stereo-microscope", "Reference · Trinocular PCB stereo microscope", stereo_microscope),
    ReferenceModel(
        "embedded-test-rack",
        "Reference · 4-Bench embedded test rack",
        embedded_test_rack,
        surface=round(0.908 / 1.90, 3),
    ),
    # Lab furniture components
    ReferenceModel(
        "esd-corner-bench", "Reference · ESD L-shaped workstation", esd_corner_bench, surface=round(0.904 / 1.658, 3)
    ),
    ReferenceModel(
        "mobile-lab-cart", "Reference · Mobile instrument cart", mobile_lab_cart, surface=round(0.878 / 0.98, 3)
    ),
    ReferenceModel("fume-hood", "Reference · Lab fume hood", fume_hood, surface=round(0.922 / 2.15, 3)),
    ReferenceModel("safety-cabinet", "Reference · Flammable safety cabinet", safety_cabinet),
    ReferenceModel("lab-chair", "Reference · ESD ergonomic lab stool", lab_chair),
    ReferenceModel("component-drawer-cabinet", "Reference · ESD component drawer cabinet", component_drawer_cabinet),
    ReferenceModel(
        "cable-tray-overhead",
        "Reference · Overhead cable & power gantry",
        cable_tray_overhead,
        surface=round(0.90 / 2.20, 3),
    ),
)


def build_glb(model: ReferenceModel) -> bytes:
    return model.build().glb(model.key)
