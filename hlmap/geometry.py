"""Brushes, faces and texture alignment for the Valve 220 .map format.

Conventions (same as Hammer / J.A.C.K. / TrenchBroom):
  +X = east, +Y = north, +Z = up. 1 unit ~ 1 inch. Player: 32x32x72 (36 crouched),
  eye height 64 above the floor, max step 18, max jump ~45 (crouch-jump).
  A brush is a convex solid: the intersection of the half-spaces behind its faces.
  Keep vertices on integer coordinates whenever possible (the compilers like it).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace

EPS = 1e-6

# ---------------------------------------------------------------- vector math

def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def length(a): return math.sqrt(dot(a, a))
def normalize(a):
    n = length(a)
    return (a[0] / n, a[1] / n, a[2] / n)


def plane_normal(p0, p1, p2):
    """Outward normal exactly as hlcsg/qbsp compute it from the 3 map points."""
    return normalize(cross(sub(p0, p1), sub(p2, p1)))


# Quake/Hammer "world" alignment axes: (normal, u, v) - first best match wins.
_BASE_AXES = [
    ((0, 0, 1), (1, 0, 0), (0, -1, 0)),   # floor
    ((0, 0, -1), (1, 0, 0), (0, -1, 0)),  # ceiling
    ((1, 0, 0), (0, 1, 0), (0, 0, -1)),   # west wall
    ((-1, 0, 0), (0, 1, 0), (0, 0, -1)),  # east wall
    ((0, 1, 0), (1, 0, 0), (0, 0, -1)),   # south wall
    ((0, -1, 0), (1, 0, 0), (0, 0, -1)),  # north wall
]


def world_axes(normal):
    best, best_d = _BASE_AXES[0], -1.0
    for axes in _BASE_AXES:
        d = dot(normal, axes[0])
        if d > best_d + EPS:
            best, best_d = axes, d
    return best[1], best[2]


def face_axes(normal):
    """Axes lying in the face plane ('face' alignment): U horizontal, V pointing down-slope.
    Unmirrored: u x v == -normal (the image reads correctly when viewed from outside)."""
    if abs(normal[2]) > 0.999:
        return world_axes(normal)
    u = normalize(cross((0, 0, 1), normal))
    return u, cross(u, normal)


# ---------------------------------------------------------------- faces

@dataclass
class Face:
    """One brush side: a plane (3 points) plus Valve 220 texture projection.

    Texel coordinates:  s = dot(p, u_axis) / u_scale + u_offset
                        t = dot(p, v_axis) / v_scale + v_offset
    """
    p0: tuple
    p1: tuple
    p2: tuple
    texture: str = "NULL"
    u_axis: tuple = (1, 0, 0)
    v_axis: tuple = (0, -1, 0)
    u_offset: float = 0.0
    v_offset: float = 0.0
    rotation: float = 0.0
    u_scale: float = 1.0
    v_scale: float = 1.0

    @property
    def normal(self):
        return plane_normal(self.p0, self.p1, self.p2)

    @property
    def dist(self):
        return dot(self.normal, self.p1)

    def translated(self, d):
        return replace(self, p0=add(self.p0, d), p1=add(self.p1, d), p2=add(self.p2, d),
                       u_offset=self.u_offset - dot(d, self.u_axis) / self.u_scale,
                       v_offset=self.v_offset - dot(d, self.v_axis) / self.v_scale)


def make_face(normal, point, texture="NULL"):
    """Face with the given outward normal through `point`, world-aligned texture."""
    n = normalize(normal)
    # in-plane t1, t2 with t1 x t2 == n; qbsp's (p0-p1) x (p2-p1) then gives +n
    a = (1, 0, 0) if abs(n[0]) < 0.9 else (0, 1, 0)
    t1 = normalize(cross(n, a))
    t2 = cross(n, t1)
    scale = 64
    p1 = tuple(point)
    p0 = add(p1, mul(t1, scale))
    p2 = add(p1, mul(t2, scale))
    if dot(plane_normal(p0, p1, p2), n) < 0:
        p0, p2 = p2, p0
    if all(float(c).is_integer() for c in n):
        p0, p1, p2 = (tuple(round(c) if abs(c - round(c)) < 1e-9 else c for c in p) for p in (p0, p1, p2))
    u, v = world_axes(n)
    return Face(p0, p1, p2, texture, u, v)


def face_from_points(a, b, c, texture="NULL"):
    """Face through 3 points given counter-clockwise as seen from OUTSIDE the brush."""
    p0, p1, p2 = tuple(c), tuple(b), tuple(a)   # qbsp wants them clockwise
    n = plane_normal(p0, p1, p2)
    u, v = world_axes(n)
    return Face(p0, p1, p2, texture, u, v)


# ---------------------------------------------------------------- brushes

SIDE_NAMES = {
    (0, 0, 1): "top", (0, 0, -1): "bottom",
    (1, 0, 0): "east", (-1, 0, 0): "west",
    (0, 1, 0): "north", (0, -1, 0): "south",
}


def side_name(normal):
    """'top'/'bottom'/'east'/'west'/'north'/'south' for the dominant axis of a normal."""
    best = max(SIDE_NAMES, key=lambda k: dot(k, normal))
    return SIDE_NAMES[best]


@dataclass
class Brush:
    faces: list = field(default_factory=list)
    comment: str = ""

    # --- geometry -------------------------------------------------------
    def vertices(self):
        """All corner points (brute force plane-triple intersection)."""
        planes = [(f.normal, f.dist) for f in self.faces]
        pts = []
        for i in range(len(planes)):
            for j in range(i + 1, len(planes)):
                for k in range(j + 1, len(planes)):
                    p = _intersect3(planes[i], planes[j], planes[k])
                    if p is None:
                        continue
                    if all(dot(n, p) - d <= 1e-3 for n, d in planes):
                        if not any(length(sub(p, q)) < 1e-3 for q in pts):
                            pts.append(p)
        return pts

    def face_polygon(self, face, verts=None):
        """Vertices lying on `face`, ordered counter-clockwise seen from outside."""
        verts = verts if verts is not None else self.vertices()
        n, d = face.normal, face.dist
        on = [p for p in verts if abs(dot(n, p) - d) < 1e-3]
        if len(on) < 3:
            return on
        c = mul(tuple(map(sum, zip(*on))), 1 / len(on))
        u, _ = face_axes(n)
        w = cross(n, u)
        on.sort(key=lambda p: math.atan2(dot(sub(p, c), w), dot(sub(p, c), u)))
        return on

    def bounds(self):
        vs = self.vertices()
        return tuple(min(v[i] for v in vs) for i in range(3)), tuple(max(v[i] for v in vs) for i in range(3))

    def is_valid(self):
        vs = self.vertices()
        if len(vs) < 4:
            return False
        return all(len(self.face_polygon(f, vs)) >= 3 for f in self.faces)

    # --- editing ----------------------------------------------------------
    def translated(self, d):
        return Brush([f.translated(d) for f in self.faces], self.comment)

    def set_texture(self, tex, sides=None):
        """Retexture all faces, or only faces whose side_name() is in `sides`."""
        for f in self.faces:
            if sides is None or side_name(f.normal) in sides:
                f.texture = tex
        return self

    def face(self, side):
        """The face whose outward normal best matches a side name or vector."""
        vec = {v: k for k, v in SIDE_NAMES.items()}.get(side, side)
        return max(self.faces, key=lambda f: dot(f.normal, vec))

    def fit(self, side, tex=None, flip_u=False, flip_v=False, u_axis=None, v_axis=None):
        """Stretch the texture so exactly one copy covers the face (doors, signs, screens).
        u_axis/v_axis: texture right/down directions (default: face-aligned, unmirrored)."""
        from .wad import default_db
        f = self.face(side)
        if tex:
            f.texture = tex
        tw, th = default_db().size(f.texture)
        poly = self.face_polygon(f)
        u, v = face_axes(f.normal)
        if u_axis is not None:
            u = normalize(u_axis)
            v = normalize(v_axis) if v_axis is not None else cross(u, f.normal)
        if flip_u:
            u = mul(u, -1)
        if flip_v:
            v = mul(v, -1)
        us = [dot(p, u) for p in poly]
        vs = [dot(p, v) for p in poly]
        f.u_axis, f.v_axis = u, v
        f.u_scale = (max(us) - min(us)) / tw
        f.v_scale = (max(vs) - min(vs)) / th
        f.u_offset = -min(us) / f.u_scale
        f.v_offset = -min(vs) / f.v_scale
        return self

    def align(self, side=None, u_offset=None, v_offset=None, scale=None):
        """Set texture offsets / uniform scale on one side (or all)."""
        for f in self.faces:
            if side is None or side_name(f.normal) == side:
                if scale is not None:
                    f.u_scale = f.v_scale = scale
                if u_offset is not None:
                    f.u_offset = u_offset
                if v_offset is not None:
                    f.v_offset = v_offset
        return self


def _intersect3(a, b, c):
    (n1, d1), (n2, d2), (n3, d3) = a, b, c
    den = dot(n1, cross(n2, n3))
    if abs(den) < 1e-9:
        return None
    p = add(add(mul(cross(n2, n3), d1), mul(cross(n3, n1), d2)), mul(cross(n1, n2), d3))
    return mul(p, 1 / den)


def _tex_for(tex, side):
    """Resolve a texture spec: a name, or a dict keyed by side name / 'sides' / 'default'."""
    if isinstance(tex, str):
        return tex
    if side in tex:
        return tex[side]
    if side in ("east", "west", "north", "south") and "sides" in tex:
        return tex["sides"]
    return tex.get("default", "NULL")


# ---------------------------------------------------------------- primitives

def box(mins, maxs, tex="NULL", comment=""):
    """Axis-aligned box. `tex` is a name or {'top':..,'bottom':..,'sides':..,'north':..}."""
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    if not (x0 < x1 and y0 < y1 and z0 < z1):
        raise ValueError(f"degenerate box {mins} {maxs}")
    faces = []
    for n, p in [((0, 0, 1), maxs), ((0, 0, -1), mins), ((1, 0, 0), maxs),
                 ((-1, 0, 0), mins), ((0, 1, 0), maxs), ((0, -1, 0), mins)]:
        faces.append(make_face(n, p, _tex_for(tex, SIDE_NAMES[n])))
    return Brush(faces, comment)


def prism(points_xy, z0, z1, tex="NULL", comment=""):
    """Vertical extrusion of a convex 2D polygon (any winding) from z0 to z1.
    Use for angled walls, wedges seen from above, pillars (pass a circle-ish polygon)."""
    pts = [tuple(p) for p in points_xy]
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts)))
    if area < 0:
        pts.reverse()  # make counter-clockwise seen from above
    faces = [make_face((0, 0, 1), (pts[0][0], pts[0][1], z1), _tex_for(tex, "top")),
             make_face((0, 0, -1), (pts[0][0], pts[0][1], z0), _tex_for(tex, "bottom"))]
    for i, a in enumerate(pts):
        b = pts[(i + 1) % len(pts)]
        # side quad, CCW seen from outside: a(z0) -> b(z0) -> b(z1)
        n = (b[1] - a[1], -(b[0] - a[0]), 0)
        f = face_from_points((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1),
                             _tex_for(tex, side_name(n)))
        faces.append(f)
    return Brush(faces, comment)


def wedge(mins, maxs, low_side, tex="NULL", comment=""):
    """Ramp/wedge filling the box, sloping DOWN toward `low_side` ('north','south','east','west').
    The high edge is on the opposite side at full height; the low edge is at z = mins.z."""
    x0, y0, z0 = mins
    x1, y1, z1 = maxs
    corners = {
        "north": [(x0, y0, z1), (x1, y0, z1)],
        "south": [(x0, y1, z1), (x1, y1, z1)],
        "east": [(x0, y0, z1), (x0, y1, z1)],
        "west": [(x1, y0, z1), (x1, y1, z1)],
    }[low_side]
    pts = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)] + corners
    return hull(pts, tex, comment)


def cylinder(center, radius, z0, z1, sides=12, tex="NULL", comment=""):
    """Vertical n-sided cylinder (vertices snapped to integers)."""
    cx, cy = center
    pts = []
    for i in range(sides):
        a = 2 * math.pi * i / sides
        p = (round(cx + radius * math.cos(a)), round(cy + radius * math.sin(a)))
        if p not in pts:
            pts.append(p)
    return prism(pts, z0, z1, tex, comment)


def hull(points, tex="NULL", comment=""):
    """Convex hull of a small point set (<= ~40 points) as a brush."""
    pts = [tuple(p) for p in points]
    c = mul(tuple(map(sum, zip(*pts))), 1 / len(pts))
    faces, seen = [], []
    n = len(pts)
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                nrm = cross(sub(pts[j], pts[i]), sub(pts[k], pts[i]))
                if length(nrm) < 1e-9:
                    continue
                nrm = normalize(nrm)
                if dot(nrm, sub(pts[i], c)) < 0:
                    nrm = mul(nrm, -1)
                d = dot(nrm, pts[i])
                if any(dot(nrm, p) - d > 1e-6 for p in pts):
                    continue
                if any(dot(nrm, s[0]) > 1 - 1e-9 and abs(s[1] - d) < 1e-6 for s in seen):
                    continue
                seen.append((nrm, d))
                on = [p for p in pts if abs(dot(nrm, p) - d) < 1e-6]
                # pick 3 well-spread points on the plane, ordered CCW from outside
                a = on[0]
                b = max(on, key=lambda p: length(sub(p, a)))
                cc = max(on, key=lambda p: length(cross(sub(b, a), sub(p, a))))
                if dot(cross(sub(b, a), sub(cc, a)), nrm) < 0:
                    b, cc = cc, b
                faces.append(face_from_points(a, b, cc, _tex_for(tex, side_name(nrm))))
    return Brush(faces, comment)
