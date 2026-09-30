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

    def models(self):
        """(mins, maxs) of every brush model (index = the number in model "*N")."""
        L = self.bsp.lumps["models"]
        return [(struct.unpack_from("<3f", L, i * 64), struct.unpack_from("<3f", L, i * 64 + 12))
                for i in range(len(L) // 64)]

    def _plane(self, idx):
        nx, ny, nz, d, _ = self.planes[idx]
        return (nx, ny, nz), d

    def model_head(self, model, hull):
        """The root of a brush model's collision tree for `hull` (1-3)."""
        return struct.unpack_from("<4i", self.bsp.lumps["models"], model * 64 + 36)[hull]

    def contents(self, hull, p, head=None):
        """Contents at point p (for hulls 1-3, p is the player/monster origin). head: a
        brush model's tree (model_head) instead of the world's; p is then relative to
        the entity's origin."""
        if hull == 0:
            n = self.heads[0]
            while n >= 0:
                pl, c0, c1 = self.nodes[n]
                nrm, d = self._plane(pl)
                n = c0 if dot(nrm, p) - d >= 0 else c1
            return self.leaves[-n - 1]
        n = self.heads[hull] if head is None else head
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
            # probe the centre and points toward each corner; a probe counts when there is
            # real air just in front of it (not a zero-thickness taper, not a thin sign
            # or another brush covering that spot)
            exposed = []
            for q in [c] + [add(c, mul(sub(v, c), 0.7)) for v in poly]:
                front = add(q, mul(n, 0.5))
                if is_air(front, 0) and is_air(add(q, mul(n, 2)), 0) and not solid_at(front):
                    exposed.append(q)
            if not exposed:
                continue
            checked += 1
            for q in exposed:
                found = False
                for key in _near_keys(n, d):
                    for bn, bd, bpoly in index.get(key, ()):
                        if dot(bn, n) > 0.999 and abs(bd - d) < 0.1 and _in_polygon(q, bpoly, n):
                            found = True
                            break
                    if found:
                        break
                if not found:
                    missing.append({"texture": f.texture, "at": tuple(round(v) for v in q),
                                    "normal": tuple(round(v, 2) for v in n)})
                    break
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


# ---------------------------------------------------------------- walking & progression

STEP_HEIGHT = 18      # sv_stepsize
JUMP_HEIGHT = 45      # standing jump
MAX_FALL = 600        # ~ where falling damage becomes lethal
HALF = (16, 16, 36)   # standing player half extents (hull 1)


SOLID_ENTITIES = ("func_wall", "func_breakable", "func_button", "func_rot_button")


def _grow(lo, hi):
    """A box grown by the standing player's half size: where the player's origin is
    when their box touches it."""
    return tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3))


def solid_entities(hulls):
    """Brush entities that are always solid (glass, walls, buttons; doors are handled
    by state): [(root of the model's standing-player hull, entity origin, grown box)]."""
    models = hulls.models()
    out = []
    for e in hulls.entities:
        if e.get("classname") in SOLID_ENTITIES and e.get("model", "").startswith("*"):
            o = tuple(float(c) for c in e["origin"].split()) if e.get("origin") else (0.0, 0.0, 0.0)
            out.append((hulls.model_head(int(e["model"][1:]), 1), o, _grow(*_placed(models, e))))
    return out


def teleports(hulls):
    """trigger_teleports: [(entity index, grown box, where it puts the player (origin),
    target name)]. The game puts the player's feet 1 unit over the target's origin."""
    models = hulls.models()
    named = {e["targetname"]: e for e in hulls.entities if e.get("targetname") and e.get("origin")}
    out = []
    for i, e in enumerate(hulls.entities):
        if e.get("classname") == "trigger_teleport" and e.get("model", "").startswith("*"):
            dest = named.get(e.get("target", ""))
            land = None
            if dest is not None:
                x, y, z = (float(c) for c in dest["origin"].split())
                land = (x, y, z + HALF[2] + 1)
            out.append((i, _grow(*_placed(models, e)), land, e.get("target", "")))
    return out


class Walker:
    """Where a player can get to ON FOOT: gravity, 18-unit steps, 45-unit jumps, falls
    up to MAX_FALL, ladders (func_ladder volumes), doors (locked doors block until their
    lock opens), solid brush entities (glass, func_walls: their own collision hulls)
    and teleporters (walking into an active one moves the player to its landing).
    Positions are standing-player origins on an 8-unit grid."""

    def __init__(self, hulls, ladders=(), step=8, solids=()):
        self.h = hulls
        self.step = step
        self.ladders = [(tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))
                        for lo, hi in ladders]
        self.blockers = []
        self.teleports = []          # [(grown box, landing position)] of the active ones
        self._cache = {}
        self._solids = {}
        for head, o, (lo, hi) in solids:
            for gx in range(int(lo[0] // 128), int(hi[0] // 128) + 1):
                for gy in range(int(lo[1] // 128), int(hi[1] // 128) + 1):
                    self._solids.setdefault((gx, gy), []).append((head, o, lo, hi))

    def _solid(self, p):
        if p not in self._cache:
            hit = self.h.contents(1, p) != -1
            if not hit:
                for head, o, lo, hi in self._solids.get((int(p[0] // 128), int(p[1] // 128)), ()):
                    if all(lo[k] < p[k] < hi[k] for k in range(3)) and \
                            self.h.contents(1, (p[0] - o[0], p[1] - o[1], p[2] - o[2]), head) != -1:
                        hit = True
                        break
            self._cache[p] = hit
        if self._cache[p]:
            return True
        return any(all(lo[k] < p[k] < hi[k] for k in range(3)) for lo, hi in self.blockers)

    def teleport_at(self, p):
        """Where an active teleporter the player at p touches sends them, or None."""
        for (lo, hi), land in self.teleports:
            if all(lo[k] <= p[k] <= hi[k] for k in range(3)):
                return land
        return None

    def _on_ladder(self, p):
        return any(all(lo[k] <= p[k] <= hi[k] for k in range(3)) for lo, hi in self.ladders)

    def _drop(self, x, y, z):
        """Fall from (x, y, z) to the ground (or onto a ladder); None if blocked, lethal
        or bottomless."""
        start = z
        if self._solid((x, y, z)):
            return None
        while True:
            if z != start and self._on_ladder((x, y, z)):
                return (x, y, z)
            if self._solid((x, y, z - 1)):
                return (x, y, z)
            if start - z > MAX_FALL:
                return None
            # hull-1 solids are >= 72 thick vertically, so 8-unit strides can't skip one
            z -= 8 if not (self._solid((x, y, z - 8)) or self._on_ladder((x, y, z - 8))) else 1

    def _moves(self, p):
        land = self.teleport_at(p)
        if land is not None:          # the teleporter takes over: that's the only way on
            return [land]
        x, y, z = p
        on_ladder = self._on_ladder(p)
        out = []
        for dx, dy in ((self.step, 0), (-self.step, 0), (0, self.step), (0, -self.step)):
            nx, ny = x + dx, y + dy
            dest = None
            for lift in (STEP_HEIGHT, 0, JUMP_HEIGHT):
                if not self._solid((x, y, z + lift)) and not self._solid((nx, ny, z + lift)):
                    dest = self._drop(nx, ny, z + lift)
                    if dest:
                        break
            if dest:
                out.append(dest)
        if on_ladder:   # climb
            for dz in (self.step, -self.step):
                q = (x, y, z + dz)
                if not self._solid(q):
                    out.append(q if self._on_ladder(q) else (self._drop(x, y, z + dz) or q))
        return out

    def settle(self, p):
        x, y, z = (round(c) for c in p)
        for up in range(64):
            if not self._solid((x, y, z + up)):
                return self._drop(x, y, z + up) or (x, y, z + up)
        return (x, y, z)

    def flood(self, seeds, limit=400000, known=(), goal=None):
        """Every position reachable from `seeds`. known: positions already known to be
        reachable (not explored again; e.g. an earlier flood before a door opened).
        goal(p): stop as soon as a position passes it; returns (found, seen) then."""
        seen = set(known) | set(seeds)
        todo = deque(seeds)
        while todo and len(seen) < limit:
            p = todo.popleft()
            if goal is not None and goal(p):
                return True, seen
            for q in self._moves(p):
                if q not in seen:
                    seen.add(q)
                    todo.append(q)
        return (False, seen) if goal is not None else seen


def _placed(models, e):
    """World bounds of a brush entity (models with an ORIGIN brush are stored relative
    to the entity's origin)."""
    lo, hi = models[int(e["model"][1:])]
    o = tuple(float(c) for c in e["origin"].split()) if e.get("origin") else (0, 0, 0)
    return tuple(lo[k] + o[k] for k in range(3)), tuple(hi[k] + o[k] for k in range(3))


# ---------------------------------------------------------------- picking things up

ITEM_BOX = ((-16, -16, 0), (16, 16, 16))   # every item's touch box (HLSDK CItem::Spawn)
SECTORS = ["east", "north-east", "north", "north-west", "west", "south-west", "south", "south-east"]


def item_rest(hulls, origin):
    """Where an item comes to rest: items drop onto the surface below at spawn."""
    x, y, z = origin
    corners = [(0, 0), (-15, -15), (15, -15), (-15, 15), (15, 15)]
    for dz in range(0, 2048):
        if any(hulls.contents(0, (x + cx, y + cy, z - dz - 1)) == -2 for cx, cy in corners):
            return (x, y, z - dz)
    return origin


def touches_box(p, lo, hi):
    """Does a standing player at origin p touch the box lo..hi (a trigger volume)?"""
    return all(lo[k] - HALF[k] <= p[k] <= hi[k] + HALF[k] for k in range(3))


def touches_item(p, item):
    """Does a standing player at origin p touch an item resting at `item`? (Boxes
    overlap; the engine pads both by 1 unit.)"""
    (lx, ly, lz), (hx, hy, hz) = ITEM_BOX
    return (item[0] + lx - 1 <= p[0] + HALF[0] and p[0] - HALF[0] <= item[0] + hx + 1 and
            item[1] + ly - 1 <= p[1] + HALF[1] and p[1] - HALF[1] <= item[1] + hy + 1 and
            item[2] + lz - 1 <= p[2] + HALF[2] and p[2] - HALF[2] <= item[2] + hz + 1)


def straight_walk(hulls, start, target, stop=lambda p: False, max_len=400):
    """Walk from `start` (a standing origin) straight toward target's x, y as a player
    holding forward does: 1-unit steps, stepping up to 18, falling, no sliding along
    what blocks. Returns (stopped by `stop`, end position, blocked-at or None)."""
    x, y, z = start
    dx, dy = target[0] - x, target[1] - y
    dist = math.hypot(dx, dy)
    if dist < 1:
        return stop((x, y, z)), (x, y, z), None
    ux, uy = dx / dist, dy / dist
    solid = lambda q: hulls.contents(1, q) != -1
    for i in range(1, int(min(dist, max_len)) + 1):
        if stop((x, y, z)):
            return True, (x, y, z), None
        nx, ny = start[0] + ux * i, start[1] + uy * i
        if solid((nx, ny, z)):
            if solid((x, y, z + STEP_HEIGHT)) or solid((nx, ny, z + STEP_HEIGHT)):
                return False, (x, y, z), (round(nx + ux * HALF[0]), round(ny + uy * HALF[1]), round(z))
            z += STEP_HEIGHT
        x, y = nx, ny
        for _ in range(64):                       # settle onto the ground
            if solid((x, y, z - 1)):
                break
            z -= 1
    return stop((x, y, z)), (x, y, z), None


def pickup_approaches(hulls, comp, item, near=72, far=104, clear=40):
    """Walk straight at an item from the open ground around it, as a player who has
    spotted it does: in each of 8 compass sectors, the reachable position `near`..`far`
    units away (same floor level) whose way is clear to within `clear` units of the
    item. Returns [(sector, start, touched, blocked_at)]; sectors with no such
    position (walls, the far side of the table) are left out."""
    best = {}
    for p in comp:
        d = math.hypot(p[0] - item[0], p[1] - item[1])
        if not near <= d <= far or not -48 <= p[2] - HALF[2] - item[2] <= 2:   # standing below/level
            continue
        sector = round(math.degrees(math.atan2(p[1] - item[1], p[0] - item[0])) / 45) % 8
        best.setdefault(sector, []).append((abs(d - (near + far) / 2), p))
    out = []
    for sector, cands in sorted(best.items()):
        for _, p in sorted(cands)[:12]:
            near_item = lambda q: math.hypot(q[0] - item[0], q[1] - item[1]) <= clear
            ok, _, _ = straight_walk(hulls, p, item, near_item)
            if not ok:
                continue
            touched, end, blocked = straight_walk(hulls, p, item, lambda q: touches_item(q, item))
            out.append((SECTORS[sector], p, touched, blocked))
            break
    return out


class FloorLight:
    """How brightly lit the walkable surfaces are, from the compiled lightmaps.

    Every upward-facing world face contributes its lightmap samples (one per 16
    texels, up to four light styles each). at() gives the brightest sample under a
    standing player's feet for a given set of light style levels (World.style_levels),
    so the same map can be judged with the power on and off. Values are lightmap
    units, max over R/G/B (a red emergency light counts): about 0-255."""

    def __init__(self, bsp):
        L = bsp.lumps
        verts = [struct.unpack_from("<3f", L["vertices"], i * 12) for i in range(len(L["vertices"]) // 12)]
        edges = [struct.unpack_from("<2H", L["edges"], i * 4) for i in range(len(L["edges"]) // 4)]
        surf = struct.unpack_from(f"<{len(L['surfedges']) // 4}i", L["surfedges"])
        texinfo = [struct.unpack_from("<8f", L["texinfo"], i * 40) for i in range(len(L["texinfo"]) // 40)]
        light = L["lighting"]
        m = struct.unpack_from("<9f4i3i", L["models"], 0)
        self.cells = {}
        self.samples = 0
        for fi in range(m[14], m[14] + m[15]):
            plane, side, fe, ne, ti, s0, s1, s2, s3, lofs = struct.unpack_from("<HHiHH4Bi", L["faces"], fi * 20)
            nx, ny, nz, d, _ = struct.unpack_from("<3ffi", L["planes"], plane * 20)
            if side:
                nx, ny, nz, d = -nx, -ny, -nz, -d
            if nz < 0.7 or lofs < 0:
                continue
            styles = [s for s in (s0, s1, s2, s3) if s != 255]
            if not styles:
                continue
            poly = [verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]] for e in surf[fe:fe + ne]]
            S, T = texinfo[ti][0:4], texinfo[ti][4:8]
            ss = [p[0] * S[0] + p[1] * S[1] + p[2] * S[2] + S[3] for p in poly]
            ts = [p[0] * T[0] + p[1] * T[1] + p[2] * T[2] + T[3] for p in poly]
            bs, bt = math.floor(min(ss) / 16), math.floor(min(ts) / 16)
            w = math.ceil(max(ss) / 16) - bs + 1
            h = math.ceil(max(ts) / 16) - bt + 1
            n = (nx, ny, nz)
            tn, ns, st = cross(T[:3], n), cross(n, S[:3]), cross(S[:3], T[:3])
            det = dot(S[:3], tn)
            if abs(det) < 1e-9:
                continue
            lo = [min(p[k] for p in poly) - 8 for k in range(3)]
            hi = [max(p[k] for p in poly) + 8 for k in range(3)]
            size = w * h
            for j in range(h):
                for i in range(w):
                    a, b = (bs + i) * 16 - S[3], (bt + j) * 16 - T[3]
                    p = tuple((a * tn[k] + b * ns[k] + d * st[k]) / det for k in range(3))
                    if not all(lo[k] <= p[k] <= hi[k] for k in range(3)):
                        continue
                    vals = []
                    for k, style in enumerate(styles):
                        o = lofs + (k * size + j * w + i) * 3
                        if o + 3 <= len(light):
                            vals.append((style, max(light[o], light[o + 1], light[o + 2])))
                    self.cells.setdefault((int(p[0] // 16), int(p[1] // 16)), []).append((p, vals))
                    self.samples += 1

    def at(self, pos, levels, standing=True):
        """Brightness of the floor under a player origin (standing) or a floor point."""
        x, y, z = pos
        feet = z - HALF[2] if standing else z
        best = 0.0
        cx, cy = int(x // 16), int(y // 16)
        for ix in (cx - 1, cx, cx + 1):
            for iy in (cy - 1, cy, cy + 1):
                for p, vals in self.cells.get((ix, iy), ()):
                    if abs(p[0] - x) <= 16 and abs(p[1] - y) <= 16 and -20 <= feet - p[2] <= 4:
                        best = max(best, sum(levels.get(s, 1.0) * v for s, v in vals))
        return best


LIT = 24            # floor brightness a player can see by (lightmap units)
SEE = 64            # ...and how far such a lit spot helps (units, horizontally)
DARK_LIMIT = 192    # most darkness a way forward may cross (units walked unable to see)


class Progress:
    """Result of progression(): see its docstring."""

    def __init__(self):
        self.missing, self.log, self.never, self.reached = [], [], [], set()
        self.softlocks = []      # (path of steps, checkpoints that can no longer be reached)
        self.darkness = []       # (path, next objective, units of darkness on the best way there)
        self.warnings = []
        self.exits = {}          # exit name -> [(globals, position, path)]
        self.teleports = []      # (teleporter, can the player get back, checkpoints lost if not)
        self.states = 0
        self.truncated = False

    def __iter__(self):          # (missing, log, never, reached), the old tuple form
        return iter((self.missing, self.log, self.never, self.reached))


def _describe(ents, i, models):
    e = ents[i]
    c = e.get("classname", "")
    if e.get("origin") and not e.get("model"):
        at = tuple(round(float(v)) for v in e["origin"].split())
    else:
        lo, hi = _placed(models, e)
        at = tuple(round((a + b) / 2) for a, b in zip(lo, hi))
    verb = "pick up" if c.startswith(("item_", "weapon_", "ammo_")) else "touch" if c.startswith("trigger_") else "press"
    return f"{verb} {c} at {at} -> {e.get('target')}"


def progression(hulls, checkpoints, radius=24, light=None, max_states=300, globals=None, start=None,
                exits=None, watch=()):
    """Play the map's logic on foot. From the player start, every progress-relevant
    thing the player can reach (pickups, buttons, trigger volumes) is tried in every
    order, with its effects simulated through the entity logic (hlmap/sim.py: relays,
    multi_managers, locks, global state, gates...). Doors block while locked.

    globals, start: arriving from another map, the global states carried over and
    where the player lands (a standing origin) instead of the player start.
    exits: {name: (mins, maxs)} volumes that leave the map (trigger_changelevel).
    watch: global states worth telling apart even if no door here depends on them
    (the ones the next map reads), so every way to set them is explored.

    Returns a Progress:
      missing    checkpoints no order of play reaches
      log        the shortest line of play that reaches everything, step by step
      never      locks never opened
      softlocks  lines of play after which some area can never be reached again
      darkness   (with `light`, a FloorLight) for each state along the way: how much
                 darkness the best way to the next objective crosses. There is no
                 flashlight without the HEV suit, so dark stretches are real.
      exits      {name: [(globals, position, path)]}: every distinct global state the
                 player can leave through each exit with, where they touch it, and a
                 line of play that gets there
    """
    from .sim import BUTTONS, DOORS, ITEMS, World
    res = Progress()
    ents = hulls.entities
    models = hulls.models()
    world0 = World(ents, globals).start()
    res.warnings += world0.warnings
    ladders = [_placed(models, e) for e in ents if e.get("classname") == "func_ladder"]
    w = Walker(hulls, ladders, solids=solid_entities(hulls))
    tele = [(i, box, w.settle(land)) for i, box, land, _ in teleports(hulls) if land is not None]
    doors = []
    for i, e in enumerate(ents):
        if e.get("classname") in DOORS and (e.get("master") or e.get("targetname")) and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            doors.append((i, (tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))))
    actions = []    # (entity, method, reach test)
    for i, e in enumerate(ents):
        cls = e.get("classname", "")
        if not e.get("target"):
            continue
        if cls.startswith(ITEMS) and e.get("origin"):
            o = tuple(float(c) for c in e["origin"].split())
            actions.append((i, "pickup", lambda p, o=o: abs(p[0] - o[0]) <= 32 and abs(p[1] - o[1]) <= 32
                            and -72 <= p[2] - o[2] <= 72))
        elif cls in BUTTONS and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            actions.append((i, "press", lambda p, lo=lo, hi=hi:
                            sum(max(0, lo[k] - p[k], p[k] - hi[k]) ** 2 for k in range(3)) <= 64 * 64))
        elif cls in ("trigger_once", "trigger_multiple") and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            actions.append((i, "touch", lambda p, lo=lo, hi=hi:
                            all(lo[k] - HALF[k] < p[k] < hi[k] + HALF[k] for k in range(3))))
    rel = world0.relevance([i for i, _ in doors] + [i for i, _, _ in tele], watch)
    actions = [a for a in actions if a[0] in rel[0]]

    cache = {}

    def configure(blocked, enabled):
        w.blockers = [b for i, b in doors if i in blocked]
        w.teleports = [(box, land) for i, box, land in tele if i in enabled]

    def flood(world, pos):
        blocked = tuple(i for i, _ in doors if not world.door_passable(i))
        enabled = tuple(i for i, _, _ in tele if world.teleport_enabled(i))
        cfg = (blocked, enabled)
        for comp in cache.get(cfg, ()):
            if pos in comp:
                return comp, cfg
        configure(blocked, enabled)
        # a door (or more) opened since an earlier flood that reached pos: everything it
        # reached is still reachable, so only grow it from the doors that opened (with
        # the same teleporters on: one that switches on also stops walks across it)
        base = None
        for (b_other, e_other), comps in cache.items():
            if e_other == enabled and set(blocked) <= set(b_other):
                for comp in comps:
                    if pos in comp and (base is None or len(comp) > len(base[1])):
                        base = (b_other, comp)
        if base is not None:
            opened_boxes = [b for i, b in doors if i in base[0] and i not in blocked]
            frontier = [p for p in base[1] if any(all(lo[k] - 24 <= p[k] <= hi[k] + 24 for k in range(3))
                                                  for lo, hi in opened_boxes)]
            comp = frozenset(w.flood(frontier, known=base[1]))
        else:
            comp = frozenset(w.flood([pos]))
        cache.setdefault(cfg, []).append(comp)
        return comp, cfg

    def lock_name(i):
        return ents[i].get("master") or ents[i].get("targetname") or f"door {i}"

    def tele_name(i):
        return f"teleporter to {ents[i].get('target')}"

    if start is None:
        start = tuple(float(c) for c in next(e for e in ents if e.get("classname") == "info_player_start")
                      ["origin"].split())
    pos0 = w.settle(start)
    nodes, order = {}, []
    queue = deque([(world0, pos0, [], None)])
    while queue:
        world, pos, path, via = queue.popleft()
        comp, (blocked, enabled) = flood(world, pos)
        key = (world.key(rel), min(comp))
        if via:
            nodes[via[0]]["children"].append((via[1], key))
        if key in nodes:
            continue
        if len(nodes) >= max_states:
            res.truncated = True
            continue
        node = {"world": world, "comp": comp, "blocked": blocked, "enabled": enabled, "entry": pos, "path": path,
                "children": []}
        nodes[key] = node
        order.append(key)
        base = world.key(rel)
        for a in actions:
            i, method, reach = a
            if not world.available(i):
                continue
            spot = next((p for p in comp if reach(p)), None)
            if spot is None:
                continue
            w2 = world.copy()
            getattr(w2, method)(i)
            if w2.key(rel) == base:
                continue
            change = w2.describe_change(world)
            for d, _ in doors:
                was, now = world.door_passable(d), w2.door_passable(d)
                if was != now:
                    change.append(f"{lock_name(d)} {'unlocked' if now else 'LOCKED'}")
            for t, _, _ in tele:
                was, now = world.teleport_enabled(t), w2.teleport_enabled(t)
                if was != now:
                    change.append(f"{tele_name(t)} {'on' if now else 'off'}")
            res.warnings += [x for x in w2.warnings if x not in res.warnings]
            step = _describe(ents, i, models) + (f": {'; '.join(change)}" if change else "")
            queue.append((w2, spot, path + [step], (key, a)))
    res.states = len(nodes)

    # which checkpoints each state reaches
    def covers(comp):
        grid = {}
        for p in comp:
            grid.setdefault((int(p[0] // 64), int(p[1] // 64)), []).append(p)

        def near(c):
            # a checkpoint that falls inside furniture counts as reached from next to it
            r = radius if hulls.contents(1, tuple(round(v) for v in c)) == -1 else 64
            gx, gy = int(c[0] // 64), int(c[1] // 64)
            return any(abs(p[0] - c[0]) <= r and abs(p[1] - c[1]) <= r and abs(p[2] - c[2]) <= 48
                       for ix in (gx - 1, gx, gx + 1) for iy in (gy - 1, gy, gy + 1) for p in grid.get((ix, iy), ()))
        return frozenset(k for k, (_, pts) in enumerate(checkpoints) if any(near(c) for c in pts))

    cov = {}
    for k in order:          # states sharing a reachable area share coverage
        comp = nodes[k]["comp"]
        cov[k] = next((cov[j] for j in cov if nodes[j]["comp"] is comp), None) or covers(comp)
    reachable = frozenset().union(*cov.values()) if cov else frozenset()
    res.reached = set().union(*(nodes[k]["comp"] for k in order))
    res.missing = [checkpoints[k] for k in range(len(checkpoints)) if k not in reachable]
    opened = {d for k in order for d, _ in doors if d not in nodes[k]["blocked"]}
    res.never = sorted({lock_name(d) for d, _ in doors if d not in opened})

    goals = {k for k in order if cov[k] == reachable}
    if not goals:
        res.warnings.append("no single state of play reaches every area (areas that close behind you?)")
        goals = {max(order, key=lambda k: len(cov[k]))}
    finish = set(goals)
    changed = True
    while changed:
        changed = False
        for k in order:
            if k not in finish and any(c in finish for _, c in nodes[k]["children"]):
                finish.add(k)
                changed = True
    for k in order:
        if k not in finish:
            lost = sorted(checkpoints[c][0] for c in reachable - cov[k])
            res.softlocks.append((nodes[k]["path"], lost))
    res.log = nodes[next(k for k in order if k in goals)]["path"]

    # every teleporter trip must have a way back (to where the player stepped on), or
    # at least leave everything else still reachable; checked with all of them on
    if tele:
        best = max(goals, key=lambda k: len(nodes[k]["enabled"]))
        node = nodes[best]
        configure(node["blocked"], node["enabled"])
        for t, (lo, hi), land in tele:
            if t not in node["enabled"]:
                continue
            around = lambda p, lo=lo, hi=hi: (not all(lo[k] <= p[k] <= hi[k] for k in range(3)) and
                                              all(lo[k] - 48 <= p[k] <= hi[k] + 48 for k in range(2)) and
                                              lo[2] - 48 <= p[2] <= hi[2])
            back, seen = w.flood([land], goal=around)
            lost = sorted(checkpoints[c][0] for c in cov[best] - covers(seen)) if not back else []
            res.teleports.append((tele_name(t), back, lost))

    for name, (lo, hi) in (exits or {}).items():     # what the player can leave with
        out, seen = [], set()
        for k in order:
            node = nodes[k]
            g = tuple(sorted(node["world"].globals.items()))
            if g in seen:
                continue
            spot = next((p for p in node["comp"] if touches_box(p, lo, hi)), None)
            if spot is not None:
                seen.add(g)
                out.append((dict(g), spot, node["path"]))
        res.exits[name] = out

    if light is not None:
        seeable_cache, walk_cache = {}, {}
        for k in order:
            if k not in finish or k in goals:
                continue
            node = nodes[k]
            useful = [(a, c) for a, c in node["children"] if c in finish]
            if not useful:
                continue
            levels = node["world"].style_levels()
            sig = (tuple(sorted(levels.items())), id(node["comp"]))
            if sig not in seeable_cache:
                seeable_cache[sig] = _seeable(node["comp"], light, levels)
            seeable = seeable_cache[sig]
            configure(node["blocked"], node["enabled"])
            best_cost, best_a = None, None
            for a, _ in useful:
                # states that differ only in things that don't move doors or lights
                # (e.g. who has said what) walk the same way
                wk = (sig, node["blocked"], node["enabled"], node["entry"], a[0])
                if wk not in walk_cache:
                    walk_cache[wk] = _dark_walk(w, node["comp"], seeable, node["entry"], a[2])
                cost = walk_cache[wk]
                if cost is not None and (best_cost is None or cost < best_cost):
                    best_cost, best_a = cost, a
            if best_a is not None:
                res.darkness.append((node["path"], _describe(ents, best_a[0], models), best_cost))
    return res


def _seeable(comp, light, levels):
    """Positions from which the player can see where they are going: a lit floor
    (>= LIT) within SEE units."""
    buckets = {}
    for p in comp:
        if light.at(p, levels) >= LIT:
            buckets.setdefault((int(p[0] // SEE), int(p[1] // SEE)), []).append(p)
    out = set()
    for p in comp:
        bx, by = int(p[0] // SEE), int(p[1] // SEE)
        if any(abs(q[0] - p[0]) <= SEE and abs(q[1] - p[1]) <= SEE and abs(q[2] - p[2]) <= 72
               for ix in (bx - 1, bx, bx + 1) for iy in (by - 1, by, by + 1) for q in buckets.get((ix, iy), ())):
            out.add(p)
    return out


def _dark_walk(walker, comp, seeable, start, reach):
    """Fewest units walked without being able to see, on the way from start to a
    position where reach(p) (0-1 BFS over the walk graph)."""
    dist = {start: 0}
    dq = deque([start])
    while dq:
        p = dq.popleft()
        d = dist[p]
        if d > dist.get(p, d):
            continue
        if reach(p):
            return d
        for q in walker._moves(p):
            if q not in comp:
                continue
            step = 0 if q in seeable else walker.step
            if d + step < dist.get(q, 1 << 30):
                dist[q] = d + step
                (dq.appendleft if step == 0 else dq.append)(q)
    return None


def teleport_landings(hulls):
    """Where each trigger_teleport puts the player: [(teleporter, problem)] for
    landings inside something, in mid-air, on a teleporter (sent straight on: two pads
    would bounce the player back and forth) or in a level change. Returns (problems,
    number of teleporters)."""
    from .campaign import changelevels
    tele = teleports(hulls)
    w = Walker(hulls, solids=solid_entities(hulls))
    changes = [_grow(*b) for _, _, b in changelevels(hulls)]
    out = []
    for i, _, land, target in tele:
        name = f"teleporter to {target}"
        if land is None:
            out.append((name, f"its target {target!r} is not a named point entity"))
            continue
        spot = tuple(round(c) for c in land)
        if w._solid(spot):
            out.append((name, f"puts the player inside something at {spot}"))
            continue
        ground = w._drop(*spot)
        if ground is None or spot[2] - ground[2] > STEP_HEIGHT:
            out.append((name, f"puts the player in mid-air at {spot}"))
            ground = ground or spot
        if any(all(lo[k] <= ground[k] <= hi[k] for k in range(3)) for j, (lo, hi), _, _ in tele):
            out.append((name, f"puts the player on a teleporter at {spot} (straight on to the next one)"))
        if any(all(lo[k] <= ground[k] <= hi[k] for k in range(3)) for lo, hi in changes):
            out.append((name, f"puts the player in a level change at {spot}"))
    return out, len(tele)
