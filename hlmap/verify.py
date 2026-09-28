"""Check a compiled BSP against the map's intended air: collision, visibility, coverage.

The compilers can silently produce broken hulls (e.g. "Ambiguous leafnode content"),
so a map is only trusted after these checks pass:

  leaks_into_solid()  Every EMPTY leaf of the world model is computed exactly as a
                      convex polytope, for hull 0 (visibility/bullets), 1 (standing
                      player) and 3 (crouching player). An EMPTY leaf reaching into
                      intended solid is a hole: walk-through walls, see-through gaps.
  reachability()      Flood-fills standing-player positions from the player start and
                      checks that every room and every cave stretch is reachable (no
                      invisible walls, no passages too tight to use).
  coverage()          Every generated face that should be visible exists in the BSP
                      (catches missing, see-through polygons).

"Intended air" comes from the Level (rooms, openings, extra air, caves).
"""
from __future__ import annotations

import math
import struct
from collections import deque

from .bsp import BSP
from .geometry import add, cross, dot, mul, normalize, sub

CONTENTS = {-1: "EMPTY", -2: "SOLID", -3: "WATER", -4: "SLIME", -5: "LAVA", -6: "SKY"}
HULL_NAMES = {0: "visibility/bullets", 1: "standing player", 2: "large monsters", 3: "crouching player"}
EPS = 0.01


class Hulls:
    """The world model's BSP trees (hull 0 = nodes/leaves, hulls 1-3 = clipnodes)."""

    def __init__(self, path):
        b = BSP(path)
        L = b.lumps
        self.planes = [struct.unpack_from("<3ffi", L["planes"], i * 20) for i in range(len(L["planes"]) // 20)]
        self.nodes = [struct.unpack_from("<i2h", L["nodes"], i * 24) for i in range(len(L["nodes"]) // 24)]
        self.leaves = [struct.unpack_from("<i", L["leaves"], i * 28)[0] for i in range(len(L["leaves"]) // 28)]
        self.clipnodes = [struct.unpack_from("<i2h", L["clipnodes"], i * 8) for i in range(len(L["clipnodes"]) // 8)]
        m = struct.unpack_from("<9f4i3i", L["models"], 0)
        self.mins, self.maxs = m[0:3], m[3:6]
        self.heads = m[9:13]
        self.entities = b.entities
        self.bsp = b

    def _plane(self, idx):
        nx, ny, nz, d, _ = self.planes[idx]
        return (nx, ny, nz), d

    def contents(self, hull, p):
        """Contents at point p (for hulls 1-3, p is the player/monster origin)."""
        if hull == 0:
            n = self.heads[0]
            while n >= 0:
                pl, c0, c1 = self.nodes[n]
                nrm, d = self._plane(pl)
                n = c0 if dot(nrm, p) - d >= 0 else c1
            return self.leaves[-n - 1]
        n = self.heads[hull]
        while n >= 0:
            pl, c0, c1 = self.clipnodes[n]
            nrm, d = self._plane(pl)
            n = c0 if dot(nrm, p) - d >= 0 else c1
        return n

    def empty_leaves(self, hull, margin=64):
        """Yield the vertex list of every EMPTY leaf's convex region (clipped to the
        model bounds + margin)."""
        return self.leaves_with(hull, -1, margin)

    def leaves_with(self, hull, contents, margin=64):
        """Yield the vertex list of every leaf with the given contents."""
        lo = tuple(c - margin for c in self.mins)
        hi = tuple(c + margin for c in self.maxs)
        stack = [(self.heads[hull], _box_polytope(lo, hi))]
        while stack:
            n, poly = stack.pop()
            if hull == 0:
                if n < 0:
                    if self.leaves[-n - 1] == contents:
                        yield _vertices(poly)
                    continue
                pl, c0, c1 = self.nodes[n]
            else:
                if n < 0:
                    if n == contents:
                        yield _vertices(poly)
                    continue
                pl, c0, c1 = self.clipnodes[n]
            nrm, d = self._plane(pl)
            front, back = _split(poly, nrm, d)
            if front:
                stack.append((c0, front))
            if back:
                stack.append((c1, back))


# ---------------------------------------------------------------- convex polytopes
# A polytope is a list of convex polygons (its faces), each a list of 3D points.

def _box_polytope(lo, hi):
    x0, y0, z0 = lo
    x1, y1, z1 = hi
    return [
        [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],
        [(x1, y0, z0), (x1, y0, z1), (x1, y1, z1), (x1, y1, z0)],
        [(x0, y0, z0), (x0, y0, z1), (x1, y0, z1), (x1, y0, z0)],
        [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],
        [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],
        [(x0, y0, z1), (x0, y1, z1), (x1, y1, z1), (x1, y0, z1)],
    ]


def _split(poly, n, d):
    """Split a convex polytope by plane n.x = d into (front: n.x >= d, back)."""
    front, back, cut = [], [], []
    for face in poly:
        dist = [dot(n, p) - d for p in face]
        if all(x >= -EPS for x in dist):
            front.append(face)
            cut.extend(p for p, x in zip(face, dist) if abs(x) <= EPS)
            continue
        if all(x <= EPS for x in dist):
            back.append(face)
            cut.extend(p for p, x in zip(face, dist) if abs(x) <= EPS)
            continue
        f, b = [], []
        for i, p in enumerate(face):
            q = face[(i + 1) % len(face)]
            dp, dq = dist[i], dist[(i + 1) % len(face)]
            if dp >= -EPS:
                f.append(p)
            if dp <= EPS:
                b.append(p)
            if (dp > EPS and dq < -EPS) or (dp < -EPS and dq > EPS):
                t = dp / (dp - dq)
                m = tuple(p[k] + (q[k] - p[k]) * t for k in range(3))
                f.append(m)
                b.append(m)
                cut.append(m)
            elif abs(dp) <= EPS:
                cut.append(p)
        if len(f) >= 3:
            front.append(f)
        if len(b) >= 3:
            back.append(b)
    cap = _order_on_plane(_dedupe(cut), n)
    if len(cap) >= 3:
        front.append(list(reversed(cap)))
        back.append(cap)
    return (front if _has_volume(front) else None), (back if _has_volume(back) else None)


def _dedupe(pts, tol=1e-3):
    out = []
    for p in pts:
        if not any(abs(p[0] - q[0]) < tol and abs(p[1] - q[1]) < tol and abs(p[2] - q[2]) < tol for q in out):
            out.append(p)
    return out


def _order_on_plane(pts, n):
    if len(pts) < 3:
        return pts
    c = tuple(sum(p[k] for p in pts) / len(pts) for k in range(3))
    a = (1.0, 0.0, 0.0) if abs(n[0]) < 0.9 else (0.0, 1.0, 0.0)
    u = normalize(cross(n, a))
    v = cross(n, u)
    return sorted(pts, key=lambda p: math.atan2(dot(sub(p, c), v), dot(sub(p, c), u)))


def _vertices(poly):
    return _dedupe([p for face in poly for p in face])


def _has_volume(poly, min_extent=0.05):
    if not poly or len(poly) < 4:
        return False
    vs = _vertices(poly)
    if len(vs) < 4:
        return False
    return all(max(p[k] for p in vs) - min(p[k] for p in vs) > min_extent for k in range(3))


# ---------------------------------------------------------------- checks

def leaks_into_solid(hulls, is_air, hull, tol=1.0, limit=20):
    """EMPTY leaves of `hull` that reach more than `tol` units into intended solid.
    Returns (problem list, leaves checked)."""
    problems, checked = [], 0
    for verts in hulls.empty_leaves(hull):
        checked += 1
        bad = [p for p in verts if not is_air(p, tol)]
        if not bad:
            continue
        centre = tuple(sum(p[k] for p in verts) / len(verts) for k in range(3))
        lo = tuple(round(min(p[k] for p in verts)) for k in range(3))
        hi = tuple(round(max(p[k] for p in verts)) for k in range(3))
        touches_air = len(bad) < len(verts)
        problems.append({"hull": hull, "at": tuple(round(c) for c in bad[0]), "bounds": (lo, hi),
                         "centre_in_solid": not is_air(centre, tol), "touches_air": touches_air})
    problems.sort(key=lambda p: (not p["touches_air"], not p["centre_in_solid"]))
    return problems[:limit] if limit else problems, checked


PLAYER_BOX = {1: ((-16, -16, -36), (16, 16, 36)), 3: ((-16, -16, -18), (16, 16, 18))}


def invisible_walls(hulls, is_air, hull, box_hits_solid, margin=4, limit=20):
    """SOLID leaves of a player hull containing an origin where the player's box (grown
    by `margin`) is inside intended air and touches no intended brush (level geometry,
    caves, func_detail props): invisible walls / bumps.
    box_hits_solid(p, lo, hi): does the box p+lo..p+hi touch any intended brush?"""
    lo, hi = PLAYER_BOX[hull]
    lo = tuple(c - margin for c in lo)
    hi = tuple(c + margin for c in hi)

    def fits(p):
        corners = [(p[0] + (hi[0] if a else lo[0]), p[1] + (hi[1] if b else lo[1]), p[2] + (hi[2] if c else lo[2]))
                   for a in (0, 1) for b in (0, 1) for c in (0, 1)]
        if not all(is_air(q, 0) for q in corners + [p]):
            return False          # outside the level (void) or clearly in rock
        return not box_hits_solid(p, lo, hi)
    problems = []
    for verts in hulls.leaves_with(hull, -2):
        centre = tuple(sum(p[k] for p in verts) / len(verts) for k in range(3))
        good = [p for p in verts + [centre] if fits(p)]
        if good:
            problems.append({"hull": hull, "at": tuple(round(c) for c in good[0]),
                             "bounds": (tuple(round(min(p[k] for p in verts)) for k in range(3)),
                                        tuple(round(max(p[k] for p in verts)) for k in range(3)))})
    return problems[:limit], len(problems)


def reachability(hulls, checkpoints, start, step=8, hull=1, radius=12):
    """Flood-fill hull `hull` from `start`; return the checkpoints (name, point) with no
    reached position within `radius` units."""
    lo, hi = hulls.mins, hulls.maxs
    s = tuple(round(c) for c in start)
    if hulls.contents(hull, s) != -1:
        # nudge the start up out of the floor if needed
        for dz in range(1, 20):
            q = (s[0], s[1], s[2] + dz)
            if hulls.contents(hull, q) == -1:
                s = q
                break
        else:
            return [("start", start)], 0
    seen = {s}
    todo = deque([s])
    while todo:
        p = todo.popleft()
        for dx, dy, dz in ((step, 0, 0), (-step, 0, 0), (0, step, 0), (0, -step, 0), (0, 0, step), (0, 0, -step)):
            q = (p[0] + dx, p[1] + dy, p[2] + dz)
            if q in seen or not all(lo[k] - 64 <= q[k] <= hi[k] + 64 for k in range(3)):
                continue
            if hulls.contents(hull, q) == -1:
                seen.add(q)
                todo.append(q)
    grid = {}
    for p in seen:
        grid.setdefault((p[0] // 32, p[1] // 32, p[2] // 32), []).append(p)

    def near(c):
        cx, cy, cz = (int(c[k] // 32) for k in range(3))
        for gx in (cx - 1, cx, cx + 1):
            for gy in (cy - 1, cy, cy + 1):
                for gz in (cz - 1, cz, cz + 1):
                    for p in grid.get((gx, gy, gz), ()):
                        if (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2 <= radius * radius:
                            return True
        return False
    missing = [(name, pts) for name, pts in checkpoints if not any(near(c) for c in pts)]
    return missing, len(seen)


def bsp_faces(hulls):
    """World-model faces of the BSP as (normal, dist, polygon, texture)."""
    b = hulls.bsp
    L = b.lumps
    verts = [struct.unpack_from("<3f", L["vertices"], i * 12) for i in range(len(L["vertices"]) // 12)]
    edges = [struct.unpack_from("<2H", L["edges"], i * 4) for i in range(len(L["edges"]) // 4)]
    surf = struct.unpack_from(f"<{len(L['surfedges']) // 4}i", L["surfedges"])
    tex = b.textures()
    ti = [struct.unpack_from("<8fii", L["texinfo"], i * 40)[8] for i in range(len(L["texinfo"]) // 40)]
    m = struct.unpack_from("<9f4i3i", L["models"], 0)
    first, count = m[14], m[15]
    out = []
    for i in range(first, first + count):
        plane, side, fe, ne, tinfo = struct.unpack_from("<HHiHH", L["faces"], i * 20)
        nx, ny, nz, d, _ = struct.unpack_from("<3ffi", L["planes"], plane * 20)
        n = (nx, ny, nz)
        if side:
            n, d = (-nx, -ny, -nz), -d
        poly = []
        for k in range(ne):
            e = surf[fe + k]
            poly.append(verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]])
        out.append((n, d, poly, tex[ti[tinfo]][0]))
    return out


def coverage(hulls, brushes, is_air, solid_at, limit=20):
    """Visible faces of `brushes` (non-tool textures, air in front) missing from the BSP."""
    from .preview import TOOL_TEXTURES
    faces = bsp_faces(hulls)
    index = {}
    for n, d, poly, name in faces:
        key = (round(n[0], 2), round(n[1], 2), round(n[2], 2), round(d))
        index.setdefault(key, []).append((n, d, poly))
    missing, checked = [], 0
    for b in brushes:
        verts = b.vertices()
        for f in b.faces:
            if f.texture.upper() in TOOL_TEXTURES:
                continue
            poly = b.face_polygon(f, verts)
            if len(poly) < 3:
                continue
            n, d = f.normal, f.dist
            c = tuple(sum(p[k] for p in poly) / len(poly) for k in range(3))
            front = add(c, mul(n, 2))
            # visible = real air in front: not a zero-thickness taper, not inside other brushes
            if not all(is_air(q, 0) for q in (front, add(front, (0, 0, 2)), add(front, (0, 0, -2))))                     or solid_at(front):
                continue
            checked += 1
            found = False
            for key in _near_keys(n, d):
                for bn, bd, bpoly in index.get(key, ()):
                    if dot(bn, n) > 0.999 and abs(bd - d) < 0.1 and _in_polygon(c, bpoly, n):
                        found = True
                        break
                if found:
                    break
            if not found:
                missing.append({"texture": f.texture, "at": tuple(round(v) for v in c), "normal": tuple(round(v, 2) for v in n)})
    return missing[:limit], checked, len(missing)


def _near_keys(n, d):
    base = [round(n[0], 2), round(n[1], 2), round(n[2], 2), round(d)]
    keys = []
    for dx in (-0.01, 0, 0.01):
        for dy in (-0.01, 0, 0.01):
            for dz in (-0.01, 0, 0.01):
                for dd in (-1, 0, 1):
                    keys.append((round(base[0] + dx, 2), round(base[1] + dy, 2), round(base[2] + dz, 2), base[3] + dd))
    return keys


def _in_polygon(p, poly, n, eps=0.05):
    sign = 0
    for i, a in enumerate(poly):
        b = poly[(i + 1) % len(poly)]
        s = dot(cross(sub(b, a), sub(p, a)), n)
        if abs(s) <= eps:
            continue
        if sign == 0:
            sign = 1 if s > 0 else -1
        elif (s > 0) != (sign > 0):
            return False
    return True
