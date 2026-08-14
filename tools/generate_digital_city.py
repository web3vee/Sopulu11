#!/usr/bin/env python3
"""
Procedural generator for `digital_city_animated.glb`.

Builds a dense, blocky "digital landscape" (terrain/city of rectangular blocks,
flat tile plazas, floating glowing suns) and writes it as a single self-contained
binary glTF 2.0 file, including baked animation tracks.

Design notes
------------
Geometry is *shared*: the whole block field is drawn from ONE unit-cube mesh
(24 verts / 12 tris) whose POSITION / NORMAL / indices accessors are reused by
every per-material mesh. Per-block variation (footprint, height, position) comes
from node TRS, so the binary payload stays tiny no matter how many blocks exist.

Animation is baked as CUBICSPLINE keyframes with analytic tangents. Every motion
component is a sum of sinusoids whose periods divide the loop length exactly, so
the first and last keyframe agree in both value and derivative -> seamless loop.

Usage:  python3 tools/generate_digital_city.py [-o digital_city_animated.glb]
"""

from __future__ import annotations

import argparse
import json
import math
import os
import struct

import numpy as np

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

SEED = 20260814

GRID = 108                 # cells per side
PITCH = 2.0                # world units between cell centres
BLOCK_GAP = 0.14           # dark seam between adjacent blocks
TILE_GAP = 0.30            # wider seam for flat plaza tiles (see reference 3)
TILE_HEIGHT = 0.16         # thickness of plaza tiles
HEIGHT_STEP = 0.5          # heights quantised -> blocky silhouette

LOOP = 24.0                # animation loop length in seconds
KEYS_PER_CYCLE = 8         # cubic-spline keyframes per sine cycle

N_SUNS_LOW = 12            # suns nestled among the blocks (these carry lights)
N_SUNS_SKY = 6             # big, distant suns in the dark sky

TARGET_ANIMATED_BLOCKS = 850

SKY_RADIUS = 700.0
GROUND_EXTENT = 2400.0

# Nested translucent shells approximating a soft radial glow. A single shell of
# uniform alpha renders as a hard-edged disc from every angle (a sphere has the
# same optical depth at every impact parameter), so the falloff has to come from
# stacking shells: (radius x core, alpha, emissiveStrength).
SUN_SHELLS = [
    (1.35, 0.200, 1.60),
    (1.75, 0.130, 1.15),
    (2.25, 0.085, 0.80),
    (2.90, 0.050, 0.50),
    (3.70, 0.028, 0.30),
    (4.80, 0.014, 0.16),
]

# name, eye, target, vertical FOV (degrees). Declared up front so the height
# field can be given clearance underneath each viewpoint.
CAMERAS = [
    ("CineCam_Main",  (26.0, 29.0, 84.0), (42.0, 6.0, 10.0), 62.0),
    ("CineCam_Plaza", (-70.0, 18.0, 92.0), (-40.0, 0.0, 40.0), 66.0),
    ("CineCam_Wide",  (-8.0, 62.0, 172.0), (6.0, 8.0, -40.0), 58.0),
]
CAM_CLEAR_RADIUS = 16.0    # world units around each eye kept clear of spikes

# glTF component types
UBYTE, USHORT, UINT, FLOAT = 5121, 5123, 5125, 5126
ARRAY_BUFFER, ELEMENT_ARRAY_BUFFER = 34962, 34963


# ---------------------------------------------------------------------------
# Colour helpers
# ---------------------------------------------------------------------------

def srgb_to_linear(c: float) -> float:
    c = c / 255.0
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def lin(r: int, g: int, b: int) -> list[float]:
    """sRGB 0-255 -> linear glTF factor (baseColorFactor is linear)."""
    return [round(srgb_to_linear(r), 5), round(srgb_to_linear(g), 5),
            round(srgb_to_linear(b), 5), 1.0]


# name, sRGB, roughness, metallic
BLOCK_MATERIALS = [
    ("LightGray",      (203, 209, 216), 0.62, 0.00),
    ("LightGrayPolish",(206, 212, 220), 0.28, 0.15),   # subtle reflections
    ("Gray",           (168, 176, 186), 0.55, 0.00),
    ("MediumGray",     (120, 128, 140), 0.70, 0.00),
    ("MediumGrayWarm", (128, 130, 132), 0.42, 0.08),
    ("DarkGray",       ( 68,  74,  84), 0.50, 0.05),
    ("Charcoal",       ( 38,  42,  50), 0.45, 0.05),
    ("NearBlack",      ( 14,  15,  19), 0.35, 0.10),
    ("AccentRed",      (178,  30,  34), 0.45, 0.00),
    ("AccentBlue",     ( 28,  52, 176), 0.40, 0.05),
    ("AccentGreen",    ( 30, 140,  46), 0.50, 0.00),
    ("AccentLime",     (186, 186,  34), 0.50, 0.00),
    ("AccentMagenta",  (176,  32, 166), 0.42, 0.00),
    ("AccentCyan",     ( 34, 158, 176), 0.42, 0.05),
]
MAT_IDX = {n: i for i, (n, *_rest) in enumerate(BLOCK_MATERIALS)}

GRAY_NAMES = ["LightGray", "LightGrayPolish", "Gray", "MediumGray",
              "MediumGrayWarm", "DarkGray", "Charcoal", "NearBlack"]
ACCENT_NAMES = ["AccentRed", "AccentBlue", "AccentGreen", "AccentLime",
                "AccentMagenta", "AccentCyan"]


# ---------------------------------------------------------------------------
# Small vector helpers
# ---------------------------------------------------------------------------

def _norm(v):
    v = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def look_at_quat(eye, target, up=(0.0, 1.0, 0.0)):
    """Quaternion (x,y,z,w) orienting a -Z-forward node from `eye` to `target`."""
    eye = np.asarray(eye, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    fwd = _norm(target - eye)
    z = -fwd                                   # glTF cameras/lights look down -Z
    x = _norm(np.cross(np.asarray(up, dtype=np.float64), z))
    if np.linalg.norm(x) < 1e-9:               # degenerate: looking straight up/down
        x = _norm(np.cross(np.array([0.0, 0.0, 1.0]), z))
    y = np.cross(z, x)
    m = np.column_stack((x, y, z))             # basis as columns

    tr = m[0, 0] + m[1, 1] + m[2, 2]
    if tr > 0.0:
        s = math.sqrt(tr + 1.0) * 2.0
        qw, qx, qy, qz = 0.25 * s, (m[2, 1] - m[1, 2]) / s, (m[0, 2] - m[2, 0]) / s, (m[1, 0] - m[0, 1]) / s
    elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
        s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
        qw, qx, qy, qz = (m[2, 1] - m[1, 2]) / s, 0.25 * s, (m[0, 1] + m[1, 0]) / s, (m[0, 2] + m[2, 0]) / s
    elif m[1, 1] > m[2, 2]:
        s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
        qw, qx, qy, qz = (m[0, 2] - m[2, 0]) / s, (m[0, 1] + m[1, 0]) / s, 0.25 * s, (m[1, 2] + m[2, 1]) / s
    else:
        s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
        qw, qx, qy, qz = (m[1, 0] - m[0, 1]) / s, (m[0, 2] + m[2, 0]) / s, (m[1, 2] + m[2, 1]) / s, 0.25 * s

    q = _norm([qx, qy, qz, qw])
    return [round(float(c), 6) for c in q]


# ---------------------------------------------------------------------------
# Procedural noise (pure numpy value-noise fBm)
# ---------------------------------------------------------------------------

def _quintic(t):
    return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)


def value_noise(n: int, cells: int, rng: np.random.Generator) -> np.ndarray:
    """Smooth value noise on an n x n grid using a `cells` x `cells` lattice."""
    lat = rng.random((cells + 2, cells + 2))
    coord = np.linspace(0.0, cells, n, endpoint=False)
    i0 = np.floor(coord).astype(np.int64)
    f = _quintic(coord - i0)

    a = lat[np.ix_(i0, i0)]
    b = lat[np.ix_(i0, i0 + 1)]
    c = lat[np.ix_(i0 + 1, i0)]
    d = lat[np.ix_(i0 + 1, i0 + 1)]

    fx = f[None, :]
    fy = f[:, None]
    top = a * (1 - fx) + b * fx
    bot = c * (1 - fx) + d * fx
    return top * (1 - fy) + bot * fy


def fbm(n: int, base_cells: int, octaves: int, rng: np.random.Generator,
        gain: float = 0.5) -> np.ndarray:
    out = np.zeros((n, n))
    amp, total, cells = 1.0, 0.0, base_cells
    for _ in range(octaves):
        out += amp * value_noise(n, cells, rng)
        total += amp
        amp *= gain
        cells *= 2
    out /= total
    lo, hi = out.min(), out.max()
    return (out - lo) / max(hi - lo, 1e-9)


def smoothstep(edge0, edge1, x):
    t = np.clip((x - edge0) / max(edge1 - edge0, 1e-9), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

def unit_cube():
    """Cube spanning x,z in [-0.5,0.5] and y in [0,1]; 24 verts, flat normals.

    Base sits on y=0 so a node's translation places the block's *foot* and its
    scale is literally (width, height, depth).
    """
    faces = [
        ((0, 0, 1),  [(-.5, 0, .5), (.5, 0, .5), (.5, 1, .5), (-.5, 1, .5)]),
        ((0, 0, -1), [(.5, 0, -.5), (-.5, 0, -.5), (-.5, 1, -.5), (.5, 1, -.5)]),
        ((1, 0, 0),  [(.5, 0, .5), (.5, 0, -.5), (.5, 1, -.5), (.5, 1, .5)]),
        ((-1, 0, 0), [(-.5, 0, -.5), (-.5, 0, .5), (-.5, 1, .5), (-.5, 1, -.5)]),
        ((0, 1, 0),  [(-.5, 1, .5), (.5, 1, .5), (.5, 1, -.5), (-.5, 1, -.5)]),
        ((0, -1, 0), [(-.5, 0, -.5), (.5, 0, -.5), (.5, 0, .5), (-.5, 0, .5)]),
    ]
    pos, nrm, idx = [], [], []
    for n, quad in faces:
        base = len(pos)
        for v in quad:
            pos.append(v)
            nrm.append(n)
        idx += [base, base + 1, base + 2, base, base + 2, base + 3]
    return (np.array(pos, dtype=np.float32), np.array(nrm, dtype=np.float32),
            np.array(idx, dtype=np.uint16))


def icosphere(subdiv: int, inward: bool = False):
    """Unit icosphere with smooth (position) normals."""
    t = (1.0 + math.sqrt(5.0)) / 2.0
    verts = [(-1, t, 0), (1, t, 0), (-1, -t, 0), (1, -t, 0),
             (0, -1, t), (0, 1, t), (0, -1, -t), (0, 1, -t),
             (t, 0, -1), (t, 0, 1), (-t, 0, -1), (-t, 0, 1)]
    verts = [list(_norm(v)) for v in verts]
    faces = [(0, 11, 5), (0, 5, 1), (0, 1, 7), (0, 7, 10), (0, 10, 11),
             (1, 5, 9), (5, 11, 4), (11, 10, 2), (10, 7, 6), (7, 1, 8),
             (3, 9, 4), (3, 4, 2), (3, 2, 6), (3, 6, 8), (3, 8, 9),
             (4, 9, 5), (2, 4, 11), (6, 2, 10), (8, 6, 7), (9, 8, 1)]

    for _ in range(subdiv):
        cache: dict[tuple[int, int], int] = {}

        def mid(a, b):
            key = (min(a, b), max(a, b))
            if key not in cache:
                m = _norm(np.array(verts[a]) + np.array(verts[b]))
                verts.append(list(m))
                cache[key] = len(verts) - 1
            return cache[key]

        nxt = []
        for a, b, c in faces:
            ab, bc, ca = mid(a, b), mid(b, c), mid(c, a)
            nxt += [(a, ab, ca), (b, bc, ab), (c, ca, bc), (ab, bc, ca)]
        faces = nxt

    pos = np.array(verts, dtype=np.float32)
    nrm = -pos.copy() if inward else pos.copy()
    tri = np.array(faces, dtype=np.uint16)
    if inward:                                   # flip winding for inside-out shell
        tri = tri[:, ::-1].copy()
    return pos, nrm, tri.reshape(-1)


def ground_quad():
    pos = np.array([(-.5, 0, .5), (.5, 0, .5), (.5, 0, -.5), (-.5, 0, -.5)], dtype=np.float32)
    nrm = np.array([(0, 1, 0)] * 4, dtype=np.float32)
    idx = np.array([0, 1, 2, 0, 2, 3], dtype=np.uint16)
    return pos, nrm, idx


# ---------------------------------------------------------------------------
# GLB builder
# ---------------------------------------------------------------------------

class GLBBuilder:
    def __init__(self):
        self.bin = bytearray()
        self.buffer_views: list[dict] = []
        self.accessors: list[dict] = []
        self.materials: list[dict] = []
        self.meshes: list[dict] = []
        self.nodes: list[dict] = []
        self.cameras: list[dict] = []
        self.lights: list[dict] = []
        self.animations: list[dict] = []
        self.ext_used: set[str] = set()

    # -- binary ------------------------------------------------------------
    def _align(self, n=4):
        while len(self.bin) % n:
            self.bin.append(0)

    def add_view(self, data: bytes, target: int | None = None) -> int:
        self._align(4)
        view = {"buffer": 0, "byteOffset": len(self.bin), "byteLength": len(data)}
        if target is not None:
            view["target"] = target
        self.bin.extend(data)
        self.buffer_views.append(view)
        return len(self.buffer_views) - 1

    def add_accessor(self, view: int, comp: int, count: int, atype: str,
                     mn=None, mx=None) -> int:
        acc = {"bufferView": view, "componentType": comp, "count": count, "type": atype}
        if mn is not None:
            acc["min"] = [float(v) for v in mn]
            acc["max"] = [float(v) for v in mx]
        self.accessors.append(acc)
        return len(self.accessors) - 1

    def add_float_accessor(self, arr: np.ndarray, atype: str, with_bounds=False) -> int:
        arr = np.ascontiguousarray(arr, dtype=np.float32)
        flat = arr.reshape(-1) if arr.ndim > 1 else arr
        count = arr.shape[0] if arr.ndim > 1 else arr.shape[0]
        view = self.add_view(flat.tobytes())
        if with_bounds and arr.ndim > 1:
            return self.add_accessor(view, FLOAT, count, atype,
                                     arr.min(axis=0), arr.max(axis=0))
        if with_bounds:
            return self.add_accessor(view, FLOAT, count, atype, [arr.min()], [arr.max()])
        return self.add_accessor(view, FLOAT, count, atype)

    # -- scene graph -------------------------------------------------------
    def add_node(self, **kw) -> int:
        self.nodes.append({k: v for k, v in kw.items() if v is not None})
        return len(self.nodes) - 1

    def add_material(self, mat: dict) -> int:
        self.materials.append(mat)
        return len(self.materials) - 1

    def add_mesh(self, mesh: dict) -> int:
        self.meshes.append(mesh)
        return len(self.meshes) - 1

    # -- output ------------------------------------------------------------
    def build_gltf(self, scene_roots: list[int], generator: str, extras: dict) -> dict:
        gltf = {
            "asset": {"version": "2.0", "generator": generator},
            "scene": 0,
            "scenes": [{"name": "DigitalCity", "nodes": scene_roots}],
            "nodes": self.nodes,
            "meshes": self.meshes,
            "materials": self.materials,
            "accessors": self.accessors,
            "bufferViews": self.buffer_views,
            "buffers": [{"byteLength": len(self.bin)}],
            "extras": extras,
        }
        if self.cameras:
            gltf["cameras"] = self.cameras
        if self.animations:
            gltf["animations"] = self.animations
        if self.lights:
            gltf["extensions"] = {"KHR_lights_punctual": {"lights": self.lights}}
            self.ext_used.add("KHR_lights_punctual")
        if self.ext_used:
            gltf["extensionsUsed"] = sorted(self.ext_used)
        return gltf

    def write_glb(self, path: str, gltf: dict):
        self._align(4)
        js = json.dumps(gltf, separators=(",", ":"), allow_nan=False).encode("utf-8")
        js += b" " * ((4 - len(js) % 4) % 4)
        bin_chunk = bytes(self.bin)
        total = 12 + 8 + len(js) + 8 + len(bin_chunk)
        with open(path, "wb") as fh:
            fh.write(struct.pack("<III", 0x46546C67, 2, total))
            fh.write(struct.pack("<II", len(js), 0x4E4F534A))
            fh.write(js)
            fh.write(struct.pack("<II", len(bin_chunk), 0x004E4942))
            fh.write(bin_chunk)
        return total


# ---------------------------------------------------------------------------
# Baked sinusoidal animation
# ---------------------------------------------------------------------------

class SineSum:
    """Sum of sinusoids whose periods all divide LOOP exactly."""

    def __init__(self, offset: float, comps: list[tuple[int, float, float]]):
        self.offset = offset
        self.comps = comps                        # (cycles, amplitude, phase)

    @property
    def max_cycles(self) -> int:
        return max((n for n, _a, _p in self.comps), default=1)

    def value(self, t: float) -> float:
        v = self.offset
        for n, a, p in self.comps:
            v += a * math.sin(2.0 * math.pi * n * t / LOOP + p)
        return v

    def deriv(self, t: float) -> float:
        d = 0.0
        for n, a, p in self.comps:
            w = 2.0 * math.pi * n / LOOP
            d += a * w * math.cos(w * t + p)
        return d


class AnimationBaker:
    """Bakes per-node translation tracks as CUBICSPLINE keyframes."""

    def __init__(self, glb: GLBBuilder):
        self.glb = glb
        self._time_accessors: dict[int, int] = {}
        self.tracks: list[tuple[int, int, int, str]] = []   # node, input, output, group

    def _times(self, keys: int) -> int:
        if keys not in self._time_accessors:
            t = np.linspace(0.0, LOOP, keys, dtype=np.float32)
            view = self.glb.add_view(t.tobytes())
            self._time_accessors[keys] = self.glb.add_accessor(
                view, FLOAT, keys, "SCALAR", [0.0], [LOOP])
        return self._time_accessors[keys]

    def bake_translation(self, node: int, axes: tuple[SineSum, SineSum, SineSum],
                         group: str):
        cycles = max(ax.max_cycles for ax in axes)
        keys = KEYS_PER_CYCLE * cycles + 1
        times = np.linspace(0.0, LOOP, keys)

        # CUBICSPLINE output layout: [in-tangent, value, out-tangent] per key.
        out = np.zeros((keys * 3, 3), dtype=np.float32)
        for k, t in enumerate(times):
            val = [ax.value(float(t)) for ax in axes]
            der = [ax.deriv(float(t)) for ax in axes]
            out[k * 3 + 0] = der          # in-tangent  (C1: same as out-tangent)
            out[k * 3 + 1] = val
            out[k * 3 + 2] = der          # out-tangent
        # Force exact loop closure (guards against float drift at the seam).
        out[(keys - 1) * 3 + 0] = out[0]
        out[(keys - 1) * 3 + 1] = out[1]
        out[(keys - 1) * 3 + 2] = out[2]

        view = self.glb.add_view(out.reshape(-1).tobytes())
        out_acc = self.glb.add_accessor(view, FLOAT, keys * 3, "VEC3")
        self.tracks.append((node, self._times(keys), out_acc, group))

    def make_animation(self, name: str, groups: tuple[str, ...]) -> dict:
        samplers, channels = [], []
        for node, inp, outp, group in self.tracks:
            if group not in groups:
                continue
            samplers.append({"input": inp, "interpolation": "CUBICSPLINE", "output": outp})
            channels.append({"sampler": len(samplers) - 1,
                             "target": {"node": node, "path": "translation"}})
        return {"name": name, "samplers": samplers, "channels": channels}


# ---------------------------------------------------------------------------
# Main scene generation
# ---------------------------------------------------------------------------

def build_scene(out_path: str) -> dict:
    rng = np.random.default_rng(SEED)
    glb = GLBBuilder()

    # ---------------- materials ----------------
    for name, rgb, rough, metal in BLOCK_MATERIALS:
        glb.add_material({
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": lin(*rgb),
                "metallicFactor": metal,
                "roughnessFactor": rough,
            },
        })

    def emissive_material(name, rgb, strength, alpha=None):
        mat = {
            "name": name,
            "pbrMetallicRoughness": {
                "baseColorFactor": [0.0, 0.0, 0.0, 1.0 if alpha is None else alpha],
                "metallicFactor": 0.0,
                "roughnessFactor": 1.0,
            },
            "emissiveFactor": [round(srgb_to_linear(c), 5) for c in rgb],
            "extensions": {"KHR_materials_emissive_strength": {"emissiveStrength": strength}},
        }
        if alpha is not None:
            mat["alphaMode"] = "BLEND"
            mat["doubleSided"] = True
        glb.ext_used.add("KHR_materials_emissive_strength")
        return glb.add_material(mat)

    # Warm golden core + stacked halo shells that fake bloom without post-fx.
    # Kept deliberately faint: a bloom-capable viewer adds its own glow on top.
    mat_sun_core = emissive_material("SunCore", (255, 238, 196), 9.0)
    mat_sun_shells = [
        emissive_material(f"SunGlow{i}", (255, 208 - i * 8, 140 - i * 9), strength, alpha=alpha)
        for i, (_scale, alpha, strength) in enumerate(SUN_SHELLS)
    ]

    mat_ground = glb.add_material({
        "name": "GroundVoid",
        "pbrMetallicRoughness": {"baseColorFactor": lin(9, 10, 13),
                                 "metallicFactor": 0.0, "roughnessFactor": 0.95},
    })
    mat_sky = glb.add_material({
        "name": "SkyDome",
        "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0],
                                 "metallicFactor": 0.0, "roughnessFactor": 1.0},
        "extensions": {"KHR_materials_unlit": {}},
        "doubleSided": True,
    })
    glb.ext_used.add("KHR_materials_unlit")

    # ---------------- shared geometry ----------------
    cpos, cnrm, cidx = unit_cube()
    cube_pos = glb.add_float_accessor(cpos, "VEC3", with_bounds=True)
    cube_nrm = glb.add_float_accessor(cnrm, "VEC3")
    cube_idx = glb.add_accessor(glb.add_view(cidx.tobytes(), ELEMENT_ARRAY_BUFFER),
                                USHORT, len(cidx), "SCALAR")

    # One mesh per material, all pointing at the SAME accessors -> real reuse.
    cube_mesh = {}
    for name, *_r in BLOCK_MATERIALS:
        cube_mesh[name] = glb.add_mesh({
            "name": f"Block_{name}",
            "primitives": [{"attributes": {"POSITION": cube_pos, "NORMAL": cube_nrm},
                            "indices": cube_idx, "material": MAT_IDX[name]}],
        })

    spos, snrm, sidx = icosphere(2)
    sph_pos = glb.add_float_accessor(spos, "VEC3", with_bounds=True)
    sph_nrm = glb.add_float_accessor(snrm, "VEC3")
    sph_idx = glb.add_accessor(glb.add_view(sidx.tobytes(), ELEMENT_ARRAY_BUFFER),
                               USHORT, len(sidx), "SCALAR")

    def sphere_mesh(name, material):
        return glb.add_mesh({
            "name": name,
            "primitives": [{"attributes": {"POSITION": sph_pos, "NORMAL": sph_nrm},
                            "indices": sph_idx, "material": material}],
        })

    mesh_sun_core = sphere_mesh("SunCoreMesh", mat_sun_core)
    mesh_sun_shells = [sphere_mesh(f"SunGlow{i}Mesh", m) for i, m in enumerate(mat_sun_shells)]

    gpos, gnrm, gidx = ground_quad()
    mesh_ground = glb.add_mesh({
        "name": "GroundMesh",
        "primitives": [{"attributes": {
            "POSITION": glb.add_float_accessor(gpos, "VEC3", with_bounds=True),
            "NORMAL": glb.add_float_accessor(gnrm, "VEC3")},
            "indices": glb.add_accessor(glb.add_view(gidx.tobytes(), ELEMENT_ARRAY_BUFFER),
                                        USHORT, len(gidx), "SCALAR"),
            "material": mat_ground}],
    })

    # Sky dome: inward-facing sphere, unlit, vertex-coloured horizon gradient.
    # subdiv 4 keeps the gradient free of visible facet banding at this radius.
    dpos, dnrm, didx = icosphere(4, inward=True)
    horizon = np.array([srgb_to_linear(c) for c in (32, 24, 38)], dtype=np.float32)
    zenith = np.array([srgb_to_linear(c) for c in (4, 4, 6)], dtype=np.float32)
    nadir = np.array([srgb_to_linear(c) for c in (2, 2, 3)], dtype=np.float32)
    up = np.clip(dpos[:, 1], -1.0, 1.0)
    tup = np.clip(up / 0.40, 0.0, 1.0)[:, None]
    tup = tup * tup * (3.0 - 2.0 * tup)
    tdown = np.clip(-up / 0.25, 0.0, 1.0)[:, None]
    col = horizon[None, :] * (1 - tup) + zenith[None, :] * tup
    col = col * (1 - tdown) + nadir[None, :] * tdown
    dcol = np.concatenate([col, np.ones((col.shape[0], 1), dtype=np.float32)], axis=1)
    mesh_sky = glb.add_mesh({
        "name": "SkyDomeMesh",
        "primitives": [{"attributes": {
            "POSITION": glb.add_float_accessor(dpos, "VEC3", with_bounds=True),
            "NORMAL": glb.add_float_accessor(dnrm, "VEC3"),
            "COLOR_0": glb.add_float_accessor(dcol.astype(np.float32), "VEC4")},
            "indices": glb.add_accessor(glb.add_view(didx.tobytes(), ELEMENT_ARRAY_BUFFER),
                                        USHORT, len(didx), "SCALAR"),
            "material": mat_sky}],
    })

    # ---------------- height / colour fields ----------------
    n = GRID
    terrain = (0.62 * fbm(n, 3, 5, rng) + 0.38 * fbm(n, 7, 4, rng))
    terrain = (terrain - terrain.min()) / (terrain.max() - terrain.min())
    ridged = 1.0 - np.abs(fbm(n, 5, 3, rng) * 2.0 - 1.0)
    darkness = fbm(n, 4, 4, rng)
    accent_field = rng.random((n, n))
    detail = fbm(n, 12, 2, rng)

    gy, gx = np.mgrid[0:n, 0:n].astype(np.float64)
    ux, uy = gx / (n - 1), gy / (n - 1)

    # Tall tower clusters (the distant skyline in the references).
    towers = np.zeros((n, n))
    cluster_defs = [
        (0.74, 0.18, 0.115, 25.0),
        (0.55, 0.11, 0.075, 18.0),
        (0.88, 0.42, 0.090, 20.0),
        (0.30, 0.14, 0.065, 13.0),
        (0.66, 0.33, 0.055, 11.0),
    ]
    for _ in range(4):
        cluster_defs.append((float(rng.uniform(0.1, 0.95)), float(rng.uniform(0.05, 0.55)),
                             float(rng.uniform(0.04, 0.085)), float(rng.uniform(7.0, 16.0))))
    for cx, cy, sig, amp in cluster_defs:
        d2 = (ux - cx) ** 2 + (uy - cy) ** 2
        towers += amp * np.exp(-d2 / (2.0 * sig * sig))
    towers *= 0.70 + 0.60 * detail           # break up the gaussian smoothness

    # Flat tile plazas: noise-driven, plus two authored bands (references 3 & 4).
    # Kept to the left/front quadrant so CineCam_Main still faces a dense block field.
    plaza_noise = fbm(n, 3, 3, rng)
    plaza = smoothstep(0.63, 0.73, plaza_noise)
    band_a = smoothstep(0.06, 0.13, uy - 0.63) * smoothstep(0.04, 0.10, 1.02 - uy) \
        * smoothstep(0.03, 0.10, ux + 0.02) * smoothstep(0.05, 0.13, 0.42 - ux)
    band_b = smoothstep(0.05, 0.12, ux - 0.46) * smoothstep(0.05, 0.12, 0.80 - ux) \
        * smoothstep(0.05, 0.11, uy - 0.78) * smoothstep(0.04, 0.10, 1.02 - uy)
    plaza = np.maximum(plaza, np.maximum(band_a, band_b))
    plaza *= 1.0 - smoothstep(4.0, 10.0, towers)      # never flatten a tower cluster

    # Corridors: guarantee each camera actually faces the subject it was framed
    # for, instead of whatever the noise happened to put there.
    half_extent = (n - 1) * PITCH * 0.5
    world_x = gx * PITCH - half_extent
    world_z = gy * PITCH - half_extent

    def corridor(eye, target, length, width):
        """Smooth mask over the ground strip running from `eye` toward `target`."""
        dx, dz = target[0] - eye[0], target[2] - eye[2]
        mag = math.hypot(dx, dz) or 1.0
        fx, fz = dx / mag, dz / mag
        rx, rz = world_x - eye[0], world_z - eye[2]
        along = rx * fx + rz * fz
        lateral = np.abs(-rx * fz + rz * fx)
        return ((1.0 - smoothstep(length * 0.65, length, along))
                * (1.0 - smoothstep(width * 0.6, width, lateral))
                * smoothstep(-6.0, 2.0, along))

    main_eye, main_target = CAMERAS[0][1], CAMERAS[0][2]
    plaza_eye, plaza_target = CAMERAS[1][1], CAMERAS[1][2]
    main_corridor = corridor(main_eye, main_target, 78.0, 34.0)
    plaza_corridor = corridor(plaza_eye, plaza_target, 95.0, 40.0)

    plaza = np.minimum(plaza, 1.0 - main_corridor)     # dense blocks for CineCam_Main
    plaza = np.maximum(plaza, plaza_corridor)          # flat tiles for CineCam_Plaza
    is_tile = plaza > 0.5

    # Smooth terrain sets the large-scale skyline; the per-cell jitter gives the
    # stepped cube-mosaic of reference 1, where neighbours differ by a step or two.
    jitter = rng.random((n, n)) * 2.1
    heights = 1.25 + (terrain ** 1.75) * 5.6 + ridged * 1.15 + jitter + towers
    # Spikes stay out of the main camera's near corridor: reference 1 opens on a
    # dense field of cube tops, not on isolated pillars blocking the view.
    spike = (rng.random((n, n)) < 0.016) & (~is_tile) & (main_corridor < 0.35)
    heights = heights + spike * rng.uniform(3.0, 14.0, size=(n, n))
    heights = np.maximum(np.round(heights / HEIGHT_STEP) * HEIGHT_STEP, 1.0)

    # Keep a disc under every camera clear, so no spike ever impales a viewpoint.
    for _name, eye, _target, _fov in CAMERAS:
        d2 = (world_x - eye[0]) ** 2 + (world_z - eye[2]) ** 2
        near = d2 < CAM_CLEAR_RADIUS ** 2
        heights = np.where(near, np.minimum(heights, max(0.75, eye[1] - 8.0)), heights)

    # ---------------- block nodes ----------------
    block_nodes: list[int] = []
    tile_nodes: list[int] = []
    animated_candidates: list[tuple[int, float]] = []
    used = np.zeros((n, n), dtype=bool)
    stats = {"tiles": 0, "blocks": 0, "wide": 0, "accent": 0, "spikes": int(spike.sum())}
    half = (n - 1) * PITCH * 0.5

    def pick_material(i, j, h, tile):
        if accent_field[i, j] < (0.052 if tile else 0.028):
            stats["accent"] += 1
            return ACCENT_NAMES[int(rng.integers(0, len(ACCENT_NAMES)))]
        if spike[i, j] and rng.random() < 0.45:
            stats["accent"] += 1
            return ACCENT_NAMES[int(rng.integers(0, len(ACCENT_NAMES)))]
        d = darkness[i, j] + 0.18 * (detail[i, j] - 0.5)
        r = rng.random()
        if d > 0.70:
            return "NearBlack" if r < 0.62 else "Charcoal"
        if d > 0.60:
            return "Charcoal" if r < 0.5 else "DarkGray"
        if d > 0.50:
            return "DarkGray" if r < 0.35 else ("MediumGray" if r < 0.8 else "MediumGrayWarm")
        if r < 0.52:
            return "LightGray"
        if r < 0.62:
            return "LightGrayPolish"
        if r < 0.80:
            return "Gray"
        if r < 0.93:
            return "MediumGray"
        return "MediumGrayWarm"

    for i in range(n):
        for j in range(n):
            if used[i, j]:
                continue
            tile = bool(is_tile[i, j])
            if tile:
                used[i, j] = True
                h = TILE_HEIGHT
                foot = PITCH - TILE_GAP
                w = d = foot
                cx = j * PITCH - half
                cz = i * PITCH - half
                mat = pick_material(i, j, h, True)
                node = glb.add_node(mesh=cube_mesh[mat],
                                    translation=[round(cx, 3), 0.0, round(cz, 3)],
                                    scale=[round(w, 3), round(h, 3), round(d, 3)])
                tile_nodes.append(node)
                stats["tiles"] += 1
                continue

            h = float(heights[i, j])
            # Merge into wider footprints occasionally (taller = more likely).
            span_i = span_j = 1
            tall = h > 6.0
            p_two = 0.42 if tall else 0.055
            if (i + 1 < n and j + 1 < n and not used[i, j + 1] and not used[i + 1, j]
                    and not used[i + 1, j + 1] and not is_tile[i, j + 1]
                    and not is_tile[i + 1, j] and not is_tile[i + 1, j + 1]
                    and rng.random() < p_two):
                span_i = span_j = 2
                h = float(max(h, heights[i, j + 1], heights[i + 1, j], heights[i + 1, j + 1]))
            elif (j + 1 < n and not used[i, j + 1] and not is_tile[i, j + 1]
                  and rng.random() < 0.05):
                span_j = 2
                h = float(max(h, heights[i, j + 1]))
            elif (i + 1 < n and not used[i + 1, j] and not is_tile[i + 1, j]
                  and rng.random() < 0.05):
                span_i = 2
                h = float(max(h, heights[i + 1, j]))

            for di in range(span_i):
                for dj in range(span_j):
                    used[i + di, j + dj] = True
            if span_i * span_j > 1:
                stats["wide"] += 1

            w = span_j * PITCH - BLOCK_GAP
            d = span_i * PITCH - BLOCK_GAP
            cx = (j + (span_j - 1) * 0.5) * PITCH - half
            cz = (i + (span_i - 1) * 0.5) * PITCH - half
            mat = pick_material(i, j, h, False)
            node = glb.add_node(mesh=cube_mesh[mat],
                                translation=[round(cx, 3), 0.0, round(cz, 3)],
                                scale=[round(w, 3), round(h, 3), round(d, 3)])
            block_nodes.append(node)
            stats["blocks"] += 1
            if h > 1.0:
                animated_candidates.append((node, h))

    # ---------------- animation: rising / falling blocks ----------------
    baker = AnimationBaker(glb)
    n_anim = min(TARGET_ANIMATED_BLOCKS, len(animated_candidates))
    chosen = rng.choice(len(animated_candidates), size=n_anim, replace=False)
    anim_amplitudes = []
    for pick in chosen:
        node, h = animated_candidates[int(pick)]
        roll = rng.random()
        if roll < 0.22:                       # barely moves
            amp = float(rng.uniform(0.25, 0.8))
        elif roll < 0.72:                     # mid range
            amp = float(rng.uniform(1.2, 4.0))
        else:                                 # dramatic risers
            amp = float(rng.uniform(4.0, 8.5))
        cycles = int(rng.integers(1, 7))      # 1..6 cycles per loop -> varied speed
        phase = float(rng.uniform(0.0, 2.0 * math.pi))
        tx, _ty, tz = glb.nodes[node]["translation"]
        # y(t) = amp/2 * (1 - cos(w t + phase))  ->  stays within [0, amp]
        y = SineSum(amp * 0.5, [(cycles, -amp * 0.5, phase + math.pi / 2.0)])
        baker.bake_translation(node, (SineSum(tx, []), y, SineSum(tz, [])), "blocks")
        glb.nodes[node]["name"] = f"AnimBlock_{node}"
        anim_amplitudes.append(amp)

    # ---------------- suns ----------------
    sun_group_nodes: list[int] = []
    sun_records = []
    # A handful of suns are staged along the main camera's sight-line so the hero
    # composition always has glows among the blocks and in the sky (references 1/2);
    # the remainder are scattered freely.
    m_eye, m_target = CAMERAS[0][1], CAMERAS[0][2]
    _mdx, _mdz = m_target[0] - m_eye[0], m_target[2] - m_eye[2]
    _mmag = math.hypot(_mdx, _mdz) or 1.0
    fwd_x, fwd_z = _mdx / _mmag, _mdz / _mmag
    side_x, side_z = -fwd_z, fwd_x

    def staged(distance, lateral):
        return (m_eye[0] + fwd_x * distance + side_x * lateral,
                m_eye[2] + fwd_z * distance + side_z * lateral)

    staged_low = [staged(26.0, -11.0), staged(44.0, 9.0),
                  staged(63.0, -4.0), staged(88.0, 15.0)]
    staged_sky = [(staged(150.0, -34.0), 44.0), (staged(190.0, 12.0), 62.0),
                  (staged(240.0, -18.0), 36.0)]
    low_slots = [(float(rng.uniform(-0.85, 0.85)), float(rng.uniform(-0.9, 0.55)))
                 for _ in range(N_SUNS_LOW)]
    for k in range(N_SUNS_LOW + N_SUNS_SKY):
        sky = k >= N_SUNS_LOW
        if sky:
            si = k - N_SUNS_LOW
            if si < len(staged_sky):
                (cx, cz), cy = staged_sky[si]
                cy += float(rng.uniform(-4.0, 6.0))
            else:
                cx = float(rng.uniform(-0.75, 0.85)) * half
                cz = float(rng.uniform(-0.95, 0.10)) * half
                cy = float(rng.uniform(32.0, 78.0))
            radius = float(rng.uniform(0.85, 2.1))
            glow = 1.25
        else:
            if k < len(staged_low):
                cx, cz = staged_low[k]
            else:
                ux_, uz_ = low_slots[k]
                cx, cz = ux_ * half, uz_ * half
            gi = int(np.clip((cz + half) / PITCH, 0, n - 1))
            gj = int(np.clip((cx + half) / PITCH, 0, n - 1))
            cy = float(heights[gi, gj]) + float(rng.uniform(1.0, 6.0))
            radius = float(rng.uniform(0.28, 0.85))
            glow = 1.0

        # Independent multi-frequency drift per axis -> organic, unsynchronised.
        def axis(scale_a, scale_b):
            n1 = int(rng.integers(1, 3))
            n2 = int(rng.integers(2, 4))
            return [(n1, float(rng.uniform(*scale_a)), float(rng.uniform(0, 2 * math.pi))),
                    (n2, float(rng.uniform(*scale_b)), float(rng.uniform(0, 2 * math.pi)))]

        drift = 1.0 if not sky else 1.8
        ax_x = SineSum(cx, axis((2.8 * drift, 8.5 * drift), (0.8, 2.6)))
        ax_z = SineSum(cz, axis((2.8 * drift, 8.5 * drift), (0.8, 2.6)))
        ax_y = SineSum(cy, axis((0.6 * drift, 2.6 * drift), (0.3, 1.1)))

        group = glb.add_node(name=f"Sun_{k:02d}", translation=[round(cx, 3), round(cy, 3), round(cz, 3)])
        children = [glb.add_node(name=f"Sun_{k:02d}_Core", mesh=mesh_sun_core,
                                 scale=[round(radius, 4)] * 3)]
        for si, (scale, _a, _s) in enumerate(SUN_SHELLS):
            children.append(glb.add_node(
                name=f"Sun_{k:02d}_Halo{si}", mesh=mesh_sun_shells[si],
                scale=[round(radius * scale * glow, 4)] * 3))
        # Only the low suns carry punctual lights: they are what pools warm light
        # onto nearby block tops. The sky suns stay purely emissive, as in the refs.
        if not sky:
            intensity = 58.0 + 120.0 * radius
            rng_range = 22.0 + 20.0 * radius
            glb.lights.append({
                "name": f"SunLight_{k:02d}", "type": "point",
                "color": [1.0, 0.822, 0.545],
                "intensity": round(intensity, 2),
                "range": round(rng_range, 2),
            })
            children.append(glb.add_node(
                name=f"Sun_{k:02d}_Light",
                extensions={"KHR_lights_punctual": {"light": len(glb.lights) - 1}}))
        glb.nodes[group]["children"] = children
        sun_group_nodes.append(group)
        baker.bake_translation(group, (ax_x, ax_y, ax_z), "suns")
        sun_records.append({"index": k, "sky": sky, "radius": round(radius, 3),
                            "centre": [round(cx, 2), round(cy, 2), round(cz, 2)]})

    # ---------------- fill lighting ----------------
    # glTF has no ambient term, so the cool "night sky" ambience of the references
    # is carried by three dim directional lights: key, opposite fill, and a soft
    # top-down wash that keeps block tops readable away from the suns.
    # The key is deliberately steep: in the references block tops read bright
    # while the sides fall away to near-black, which needs top-down light and
    # only a whisper of side fill.
    fill_nodes = []
    for fname, colour, intensity, direction in [
        ("AmbientFillKey", [0.66, 0.74, 0.92], 1.45, (-0.20, -1.0, -0.28)),
        ("AmbientFillSide", [0.40, 0.46, 0.66], 0.30, (0.62, -0.34, 0.70)),
        ("AmbientFillRim", [0.34, 0.40, 0.60], 0.16, (-0.70, -0.30, 0.62)),
    ]:
        glb.lights.append({"name": fname, "type": "directional",
                           "color": colour, "intensity": intensity})
        fill_nodes.append(glb.add_node(
            name=fname, rotation=look_at_quat((0, 0, 0), direction),
            extensions={"KHR_lights_punctual": {"light": len(glb.lights) - 1}}))

    # ---------------- cameras ----------------
    # Main view looks across the dense block field toward the tallest cluster
    # (references 1/2); plaza view sweeps the flat tile field (reference 3);
    # wide view is the high, distant composition of reference 4.
    camera_nodes = []
    for cname, eye, target, yfov_deg in CAMERAS:
        glb.cameras.append({"name": cname, "type": "perspective",
                            "perspective": {"yfov": round(math.radians(yfov_deg), 6),
                                            "znear": 0.35, "zfar": 2400.0}})
        camera_nodes.append(glb.add_node(
            name=cname, camera=len(glb.cameras) - 1,
            translation=[round(float(v), 3) for v in eye],
            rotation=look_at_quat(eye, target)))

    # ---------------- environment ----------------
    # Dropped well below the block feet so every seam reads as black void rather
    # than as a lit surface, and so risen blocks show a dark slot underneath.
    ground = glb.add_node(name="GroundVoid", mesh=mesh_ground,
                          translation=[0.0, -1.0, 0.0],
                          scale=[GROUND_EXTENT, 1.0, GROUND_EXTENT])
    sky = glb.add_node(name="SkyDome", mesh=mesh_sky,
                       translation=[0.0, 0.0, 0.0], scale=[SKY_RADIUS] * 3)

    # ---------------- hierarchy ----------------
    terrain_node = glb.add_node(name="Terrain", children=block_nodes + tile_nodes)
    suns_node = glb.add_node(name="Suns", children=sun_group_nodes)
    lighting_node = glb.add_node(name="FillLighting", children=fill_nodes)
    cameras_node = glb.add_node(name="Cameras", children=camera_nodes)
    env_node = glb.add_node(name="Environment", children=[ground, sky])
    root = glb.add_node(name="DigitalCity",
                        children=[terrain_node, suns_node, lighting_node, cameras_node, env_node])

    # ---------------- animations ----------------
    # [0] combined (many viewers autoplay only the first clip),
    # [1] suns only, [2] blocks only.
    glb.animations = [
        baker.make_animation("DigitalCity_AllMotion", ("suns", "blocks")),
        baker.make_animation("SunsFloat", ("suns",)),
        baker.make_animation("BlocksRise", ("blocks",)),
    ]

    stats.update({
        "grid": f"{n}x{n}",
        "block_nodes": len(block_nodes),
        "tile_nodes": len(tile_nodes),
        "animated_blocks": n_anim,
        "suns": len(sun_group_nodes),
        "sun_lights": N_SUNS_LOW,
        "loop_seconds": LOOP,
        "total_nodes": len(glb.nodes),
        "triangles": (len(block_nodes) + len(tile_nodes)) * 12
                     + len(sun_group_nodes) * (1 + len(SUN_SHELLS)) * (len(sidx) // 3)
                     + len(didx) // 3 + 2,
        "amp_min": round(min(anim_amplitudes), 2),
        "amp_max": round(max(anim_amplitudes), 2),
    })

    extras = {"generator": "tools/generate_digital_city.py", "seed": SEED, "stats": stats}
    gltf = glb.build_gltf([root], "digital_city procedural generator (python/numpy)", extras)
    size = glb.write_glb(out_path, gltf)
    stats["file_bytes"] = size
    stats["cameras"] = [c["name"] for c in glb.cameras]
    stats["materials"] = len(glb.materials)
    stats["meshes"] = len(glb.meshes)
    stats["animations"] = [
        {"name": a["name"], "channels": len(a["channels"])} for a in glb.animations]
    return stats


# ---------------------------------------------------------------------------
# Validation: re-open the written GLB and check it from scratch
# ---------------------------------------------------------------------------

def _read_glb(path: str) -> tuple[dict, bytes]:
    with open(path, "rb") as fh:
        raw = fh.read()
    magic, version, length = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise ValueError("not a GLB (bad magic)")
    if version != 2:
        raise ValueError(f"unexpected glTF version {version}")
    if length != len(raw):
        raise ValueError(f"header length {length} != file size {len(raw)}")
    gltf, blob, off = None, b"", 12
    while off < len(raw):
        clen, ctype = struct.unpack_from("<II", raw, off)
        chunk = raw[off + 8: off + 8 + clen]
        if ctype == 0x4E4F534A:
            gltf = json.loads(chunk.decode("utf-8"))
        elif ctype == 0x004E4942:
            blob = chunk
        off += 8 + clen + ((4 - clen % 4) % 4)
    if gltf is None:
        raise ValueError("GLB has no JSON chunk")
    return gltf, blob


def _accessor_array(gltf: dict, blob: bytes, index: int) -> np.ndarray:
    acc = gltf["accessors"][index]
    ncomp = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}[acc["type"]]
    dtype = {5120: np.int8, 5121: np.uint8, 5122: np.int16,
             5123: np.uint16, 5125: np.uint32, 5126: np.float32}[acc["componentType"]]
    view = gltf["bufferViews"][acc["bufferView"]]
    start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
    data = np.frombuffer(blob, dtype=dtype, count=acc["count"] * ncomp,
                         offset=start)
    return data.reshape(acc["count"], ncomp) if ncomp > 1 else data


def _sample_cubic(times: np.ndarray, values: np.ndarray, t: float) -> np.ndarray:
    """Evaluate a glTF CUBICSPLINE sampler (values laid out as in-tangent/value/out)."""
    k = int(np.clip(np.searchsorted(times, t, side="right") - 1, 0, len(times) - 2))
    t0, t1 = float(times[k]), float(times[k + 1])
    dt = t1 - t0
    s = 0.0 if dt <= 0 else (t - t0) / dt
    p0, m0 = values[k * 3 + 1], values[k * 3 + 2] * dt
    p1, m1 = values[(k + 1) * 3 + 1], values[(k + 1) * 3 + 0] * dt
    s2, s3 = s * s, s * s * s
    return ((2 * s3 - 3 * s2 + 1) * p0 + (s3 - 2 * s2 + s) * m0
            + (-2 * s3 + 3 * s2) * p1 + (s3 - s2) * m1)


def validate(path: str) -> int:
    gltf, blob = _read_glb(path)
    checks: list[tuple[str, bool, str]] = []

    def check(label, ok, detail=""):
        checks.append((label, bool(ok), detail))

    # 1-2. container + geometry
    check("GLB re-opens, header consistent", True, f"{os.path.getsize(path):,} bytes")
    meshes, nodes = gltf.get("meshes", []), gltf.get("nodes", [])
    mesh_nodes = [nd for nd in nodes if "mesh" in nd]
    prim_count = sum(len(m["primitives"]) for m in meshes)
    tris = 0
    for nd in mesh_nodes:
        for prim in meshes[nd["mesh"]]["primitives"]:
            tris += gltf["accessors"][prim["indices"]]["count"] // 3
    check("geometry present", len(mesh_nodes) > 1000 and tris > 50000,
          f"{len(mesh_nodes):,} mesh nodes, {tris:,} triangles, {prim_count} primitives")

    # 3. materials, all referenced and complete
    mats = gltf.get("materials", [])
    used_mats = {p["material"] for m in meshes for p in m["primitives"] if "material" in p}
    missing = [i for i, p in enumerate(mats)
               if "pbrMetallicRoughness" not in p or
               "baseColorFactor" not in p["pbrMetallicRoughness"]]
    check("materials present and complete", len(mats) > 0 and not missing,
          f"{len(mats)} materials, {len(used_mats)} referenced by primitives")
    check("every primitive has a material",
          all("material" in p for m in meshes for p in m["primitives"]))

    # 4. coloured blocks
    accents = [i for i, m in enumerate(mats) if m.get("name", "").startswith("Accent")]
    accent_nodes = sum(1 for nd in mesh_nodes
                       for p in meshes[nd["mesh"]]["primitives"]
                       if p.get("material") in accents)
    check("coloured accent blocks present", len(accents) == 6 and accent_nodes > 100,
          f"{len(accents)} accent materials on {accent_nodes:,} blocks")

    # 5. glowing suns
    suns = [i for i, nd in enumerate(nodes)
            if nd.get("name", "").startswith("Sun_") and "children" in nd]
    emissive = [m for m in mats
                if any(c > 0 for c in m.get("emissiveFactor", [0, 0, 0]))]
    lights = gltf.get("extensions", {}).get("KHR_lights_punctual", {}).get("lights", [])
    point_lights = [l for l in lights if l["type"] == "point"]
    check("glowing suns present", len(suns) >= 10 and len(emissive) >= 2,
          f"{len(suns)} suns, {len(emissive)} emissive materials, "
          f"{len(point_lights)} point lights, {len(lights) - len(point_lights)} directional")

    # 6. animation tracks
    anims = gltf.get("animations", [])
    total_channels = sum(len(a["channels"]) for a in anims)
    check("animation tracks exist", len(anims) >= 2 and total_channels > 500,
          ", ".join(f"{a['name']}={len(a['channels'])}ch" for a in anims))
    check("all samplers use smooth interpolation",
          all(s.get("interpolation") == "CUBICSPLINE" for a in anims for s in a["samplers"]))

    # 7-9. actually sample the curves: suns move, blocks rise, everything loops
    name_of = {i: nd.get("name", "") for i, nd in enumerate(nodes)}
    probes = {"suns": [], "blocks": []}
    for anim in anims:
        if anim["name"] != "DigitalCity_AllMotion":
            continue
        for ch in anim["channels"]:
            smp = anim["samplers"][ch["sampler"]]
            times = _accessor_array(gltf, blob, smp["input"])
            vals = _accessor_array(gltf, blob, smp["output"])
            node_name = name_of[ch["target"]["node"]]
            bucket = "suns" if node_name.startswith("Sun_") else "blocks"
            samples = np.array([_sample_cubic(times, vals, t)
                                for t in np.linspace(0.0, LOOP, 97)])
            probes[bucket].append((node_name, samples, float(times[-1])))

    sun_travel = [np.ptp(s, axis=0) for _n, s, _d in probes["suns"]]
    check("suns move in X, Y and Z",
          len(sun_travel) >= 10 and all(np.min(t) > 0.3 for t in sun_travel),
          f"{len(sun_travel)} suns, XYZ travel min "
          f"{np.min([t.min() for t in sun_travel]):.2f} / max "
          f"{np.max([t.max() for t in sun_travel]):.2f} units")

    blk_rise = np.array([np.ptp(s[:, 1]) for _n, s, _d in probes["blocks"]])
    blk_horiz = np.array([max(np.ptp(s[:, 0]), np.ptp(s[:, 2])) for _n, s, _d in probes["blocks"]])
    check("selected blocks move vertically",
          len(blk_rise) > 500 and blk_rise.min() > 0.05 and blk_horiz.max() < 1e-4,
          f"{len(blk_rise)} blocks, rise {blk_rise.min():.2f}-{blk_rise.max():.2f} units, "
          f"horizontal drift {blk_horiz.max():.1e}")
    check("animated blocks are a subset of all blocks",
          0 < len(blk_rise) < len(mesh_nodes) * 0.25,
          f"{len(blk_rise):,} of {len(mesh_nodes):,} mesh nodes")

    # phases differ -> no synchronised movement
    starts = np.array([s[0, 1] for _n, s, _d in probes["blocks"]])
    check("block phases are desynchronised", float(np.std(starts)) > 0.3,
          f"start-height spread sigma={float(np.std(starts)):.2f}")

    # loop closure: value at t=0 equals value at t=LOOP for every track
    worst = 0.0
    for bucket in probes.values():
        for _n, s, dur in bucket:
            worst = max(worst, float(np.abs(s[0] - s[-1]).max()))
    durations = {round(d, 6) for bucket in probes.values() for _n, _s, d in bucket}
    check("animation loops seamlessly", worst < 1e-4 and durations == {LOOP},
          f"max |p(0)-p(T)| = {worst:.2e}, all tracks end at T={sorted(durations)}")

    # 10. no external references
    ext_uri = [b for b in gltf.get("buffers", []) if "uri" in b]
    check("self-contained (no external buffers/textures/images)",
          not ext_uri and not gltf.get("images") and not gltf.get("textures"),
          "single embedded BIN chunk, untextured PBR materials")

    # 11. geometry integrity
    bad_geo = []
    for mi, m in enumerate(meshes):
        for p in m["primitives"]:
            pos = _accessor_array(gltf, blob, p["attributes"]["POSITION"])
            nrm = _accessor_array(gltf, blob, p["attributes"]["NORMAL"])
            idx = _accessor_array(gltf, blob, p["indices"])
            lens = np.linalg.norm(nrm, axis=1)
            if (not np.isfinite(pos).all() or not np.isfinite(nrm).all()
                    or np.abs(lens - 1.0).max() > 1e-3
                    or idx.max() >= len(pos) or len(idx) % 3):
                bad_geo.append(m.get("name", str(mi)))
    check("geometry intact (finite verts, unit normals, valid indices)", not bad_geo,
          f"{len(meshes)} meshes checked" if not bad_geo else f"bad: {bad_geo}")

    degenerate = [i for i, nd in enumerate(nodes)
                  if "scale" in nd and min(abs(v) for v in nd["scale"]) < 1e-6]
    check("no degenerate node scales", not degenerate)

    # 12. reuse / efficiency
    accessor_users: dict[int, int] = {}
    for m in meshes:
        for p in m["primitives"]:
            accessor_users[p["attributes"]["POSITION"]] = \
                accessor_users.get(p["attributes"]["POSITION"], 0) + 1
    reuse = len(mesh_nodes) / max(len(accessor_users), 1)
    check("geometry is instanced, not duplicated",
          len(accessor_users) <= 8 and reuse > 500,
          f"{len(accessor_users)} unique POSITION accessors shared by "
          f"{len(mesh_nodes):,} nodes ({reuse:.0f}x reuse)")

    check("cameras present", len(gltf.get("cameras", [])) >= 1,
          ", ".join(c["name"] for c in gltf.get("cameras", [])))

    width = max(len(c[0]) for c in checks)
    failed = 0
    for label, ok, detail in checks:
        failed += not ok
        print(f"  [{'PASS' if ok else 'FAIL'}] {label.ljust(width)}  {detail}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    return 1 if failed else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="digital_city_animated.glb")
    ap.add_argument("--validate-only", action="store_true",
                    help="skip generation, just validate an existing GLB")
    args = ap.parse_args()
    if not args.validate_only:
        stats = build_scene(args.output)
        print(json.dumps(stats, indent=2))
        print(f"\nwrote {args.output} ({stats['file_bytes'] / 1_048_576:.2f} MiB)\n")
    print(f"validating {args.output}")
    raise SystemExit(validate(args.output))


if __name__ == "__main__":
    main()
