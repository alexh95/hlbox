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

import heapq
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
    """EMPTY (and liquid) leaves of `hull` that reach more than `tol` units into
    intended solid. Returns (problem list, leaves checked)."""
    problems, checked = [], 0
    for verts in (v for c in PASSABLE for v in hulls.leaves_with(hull, c)):
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
# jumping (pm_shared.c): sv_gravity 800; a jump leaves the ground at the speed that
# rises 45 units, a long jump (the module, crouch + jump while moving) at 560 forward
# and the speed that rises 56. A player's own gravity (trigger_gravity) scales the
# pull, not the take-off, so in 0.5 gravity a jump rises twice as high.
GRAVITY = 800.0
JUMP_SPEED = (2 * GRAVITY * 45.0) ** 0.5
RUN_JUMP = 280        # forward speed credited to a running jump (the game allows 320)
LONG_JUMP = (510, (2 * GRAVITY * 56.0) ** 0.5)   # forward (the game gives 560), up
LETHAL = 100          # trigger_hurt damage that kills outright (a fall into the void)
# Water: the clip hulls keep liquids (-3 water, -4 slime, -5 lava) as contents of
# their own, grown like solid; hull 0 has the true surface. A player whose origin
# (waist) is in water swims (pm_shared: 0.8 of 320 = 256 units/s, any direction); with
# the eyes 28 over the origin under water they hold their breath: 12 s before drowning
# damage (AIRTIME), about 3,000 units. Out of water at a ledge: the water jump climbs
# onto a top level with the surface.
PASSABLE = (-1, -3, -4, -5)
LIQUID = (-3, -4, -5)
SWIM = 16             # swimming moves: a lattice coarser than walking's
EYES = 28
BREATH = 1800         # units a player may swim with their head under (a margin on 12 s)
WATER_CLIMB = 64      # how far above a swimming origin a ledge's standing origin may be
DIRS8 = [(1, 0), (0.7071, 0.7071), (0, 1), (-0.7071, 0.7071), (-1, 0), (-0.7071, -0.7071), (0, -1),
         (0.7071, -0.7071)]


SOLID_ENTITIES = ("func_wall", "func_breakable", "func_button", "func_rot_button", "func_pushable")


def _grow(lo, hi):
    """A box grown by the standing player's half size: where the player's origin is
    when their box touches it."""
    return tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3))


def solid_entities(hulls):
    """Brush entities that are solid (glass, walls, buttons, breakables until broken;
    doors are handled by state): [(entity index, root of the model's standing-player
    hull, entity origin, grown box)]."""
    models = hulls.models()
    out = []
    for i, e in enumerate(hulls.entities):
        if e.get("classname") in SOLID_ENTITIES and e.get("model", "").startswith("*"):
            o = tuple(float(c) for c in e["origin"].split()) if e.get("origin") else (0.0, 0.0, 0.0)
            out.append((i, hulls.model_head(int(e["model"][1:]), 1), o, _grow(*_placed(models, e))))
    return out


def breakables(hulls):
    """func_breakables a player can break (not "only trigger", not unbreakable glass)."""
    return [i for i, e in enumerate(hulls.entities)
            if e.get("classname") == "func_breakable" and e.get("model", "").startswith("*")
            and not int(e.get("spawnflags") or 0) & 1 and str(e.get("material") or "0") != "7"]


def _movedir(e):
    """A func_door's direction of travel (HLSDK SetMovedir): angle -1 up, -2 down,
    else the yaw of `angles`/`angle`."""
    a = e.get("angles")
    yaw = float(a.split()[1]) if a else float(e.get("angle") or 0)
    if a is None and e.get("angle") in ("-1", "-2"):
        return (0.0, 0.0, 1.0 if e.get("angle") == "-1" else -1.0)
    return (math.cos(math.radians(yaw)), math.sin(math.radians(yaw)), 0.0)


def water_movers(hulls):
    """func_waters: water that moves like a door when fired (a tank draining, a cistern
    filling): [(entity index, the box it's compiled in, the box it moves to)]."""
    models = hulls.models()
    out = []
    for i, e in enumerate(hulls.entities):
        if e.get("classname") == "func_water" and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            d = _movedir(e)
            travel = sum(abs(d[k] * (hi[k] - lo[k] - 2)) for k in range(3)) - float(e.get("lip") or 0)
            out.append((i, (lo, hi), (tuple(lo[k] + d[k] * travel for k in range(3)),
                                      tuple(hi[k] + d[k] * travel for k in range(3)))))
    return out


def lifts(hulls):
    """func_plats: a lift is placed at its top and, unnamed, starts at the bottom
    (`height` below; HLSDK: size - 8 without one) and rises when stood on:
    [((its grown box at the bottom, at the top), (x0, x1, y0, y1) where riders stand,
    the riders' origin z at the bottom, rise)]. The walker stands on it at both stops
    and rides it either way."""
    models = hulls.models()
    out = []
    for e in hulls.entities:
        if e.get("classname") == "func_plat" and e.get("model", "").startswith("*") and not e.get("targetname"):
            lo, hi = _placed(models, e)
            rise = float(e.get("height") or 0) or (hi[2] - lo[2] - 8)
            low = ((lo[0], lo[1], lo[2] - rise), (hi[0], hi[1], hi[2] - rise))
            out.append(((_grow(*low), _grow(lo, hi)), (lo[0] + 16, hi[0] - 16, lo[1] + 16, hi[1] - 16),
                        hi[2] - rise + HALF[2], rise))
    return out


def gravity_zones(hulls):
    """trigger_gravity volumes: [(grown box, gravity multiplier)]. The game sets the
    player's gravity when they touch one, and it stays until another changes it; the
    walker reads the zone a position is in (1.0 outside them all)."""
    models = hulls.models()
    return [(_grow(*_placed(models, e)), float(e.get("gravity") or 1) or 1.0) for e in hulls.entities
            if e.get("classname") == "trigger_gravity" and e.get("model", "").startswith("*")]


def lethal_volumes(hulls):
    """trigger_hurts that kill (damage >= LETHAL, on from the start): grown boxes."""
    models = hulls.models()
    return [_grow(*_placed(models, e)) for e in hulls.entities
            if e.get("classname") == "trigger_hurt" and e.get("model", "").startswith("*")
            and float(e.get("dmg") or 0) >= LETHAL and not int(e.get("spawnflags") or 0) & 2]


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
    With jumps=True, also running jumps across gaps and down, and long jumps while
    `long_jump` is set, flown as arcs; gravity zones (trigger_gravity) scale jumps and
    safe falls, and lethal trigger_hurts are death (nothing lands in them).
    Water (the world's, and func_waters where they are now): swimming in any
    direction on a SWIM lattice, falls into it don't hurt, ledges level with the
    surface can be climbed onto; and no way may keep the head under for more than
    BREATH units. Lifts (func_plats): standing on one at the bottom rides it up.
    Breakables block until broken (`removed`).
    Positions are standing-player origins on a grid of `step` units (x, y multiples)."""

    def __init__(self, hulls, ladders=(), step=8, solids=(), zones=(), lethal=(), jumps=False, lifts=(),
                 water=None):
        self.h = hulls
        self.step = step
        self.lifts = list(lifts)
        self.waters = []             # boxes of the func_waters, where they are now
        self.removed = frozenset()   # entities gone (broken breakables)
        self._wcache = {}
        # swim when the world has liquid or water can appear (func_waters)
        self.swim = (any(c in LIQUID for c in hulls.leaves) if water is None else water)
        self.zones = list(zones)
        self.lethal = list(lethal)
        self.jumps = jumps
        self.long_jump = False
        self._arcs = {}              # (p, dir, speed) -> (landing, box the flight passed through)
        self._arcs_blocked = {}      # ...flown again with doors in the way
        self.ladders = [(tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))
                        for lo, hi in ladders]
        self.blockers = []
        self.teleports = []          # [(grown box, landing position)] of the active ones
        self._cache = {}
        self._solids = {}
        for i, head, o, (lo, hi) in solids:
            for gx in range(int(lo[0] // 128), int(hi[0] // 128) + 1):
                for gy in range(int(lo[1] // 128), int(hi[1] // 128) + 1):
                    self._solids.setdefault((gx, gy), []).append((i, head, o, lo, hi))

    def _solid(self, p):
        if p not in self._cache:
            self._cache[p] = self.h.contents(1, p) not in PASSABLE
        if self._cache[p]:
            return True
        for i, head, o, lo, hi in self._solids.get((int(p[0] // 128), int(p[1] // 128)), ()):
            if i not in self.removed and all(lo[k] < p[k] < hi[k] for k in range(3)) and \
                    self.h.contents(1, (p[0] - o[0], p[1] - o[1], p[2] - o[2]), head) not in PASSABLE:
                return True
        if any(all(lo[k] < p[k] < hi[k] for k in range(3)) for stops, _, _, _ in self.lifts for lo, hi in stops):
            return True
        return any(all(lo[k] < p[k] < hi[k] for k in range(3)) for lo, hi in self.blockers)

    def water(self, p):
        """Is p (an origin: the player's waist) in water?"""
        if not self.swim:
            return False
        if p not in self._wcache:
            self._wcache[p] = self.h.contents(0, p) in LIQUID
        return self._wcache[p] or any(all(lo[k] <= p[k] <= hi[k] for k in range(3)) for lo, hi in self.waters)

    def underwater(self, p):
        """Are the eyes of a player at p under water (holding their breath)?"""
        return self.water((p[0], p[1], p[2] + EYES))

    def _afloat(self, x, y, z):
        """A swimming position at the water a fall reached: on the SWIM lattice when
        that's in water and clear, else where the fall stopped."""
        s = SWIM
        xs = sorted({s * math.floor(x / s), s * math.ceil(x / s)}, key=lambda v: abs(v - x))
        ys = sorted({s * math.floor(y / s), s * math.ceil(y / s)}, key=lambda v: abs(v - y))
        bz = s * math.floor(z / s)
        for q in ((qx, qy, qz) for qz in (bz, bz - s) for qx in xs for qy in ys):
            if self.water(q) and not self._solid(q):
                return q             # the nearest lattice point in the water (one lattice: fewer positions)
        return (x, y, z)

    def gravity(self, p):
        g = 1.0
        for (lo, hi), zg in self.zones:
            if all(lo[k] <= p[k] <= hi[k] for k in range(3)):
                g = zg
        return g

    def deadly(self, p):
        return any(all(lo[k] <= p[k] <= hi[k] for k in range(3)) for lo, hi in self.lethal)

    def teleport_at(self, p):
        """Where an active teleporter the player at p touches sends them, or None."""
        for (lo, hi), land in self.teleports:
            if all(lo[k] <= p[k] <= hi[k] for k in range(3)):
                return land
        return None

    def _on_ladder(self, p):
        return any(all(lo[k] <= p[k] <= hi[k] for k in range(3)) for lo, hi in self.ladders)

    def _drop(self, x, y, z, fell=0.0):
        """Fall from (x, y, z) to the ground (or onto a ladder, or into water); None if
        blocked, lethal or bottomless. fell: how far the player was already falling
        (from a jump). Water breaks any fall."""
        start = z
        if self._solid((x, y, z)):
            return None
        limit = MAX_FALL / self.gravity((x, y, z)) - fell
        while True:
            if self.lethal and self.deadly((x, y, z)):
                return None
            if self.swim and self.water((x, y, z)):
                return self._afloat(x, y, z)
            if z != start and self._on_ladder((x, y, z)):
                return (x, y, z)
            if self._solid((x, y, z - 1)):
                return (x, y, z) if start - z <= limit else None
            if start - z > max(limit, 0) + 4096:
                return None                    # bottomless
            # hull-1 solids are >= 72 thick vertically, so 8-unit strides can't skip one
            ahead = (x, y, z - 8)
            z -= 8 if not (self._solid(ahead) or self._on_ladder(ahead) or (self.swim and self.water(ahead))) else 1

    def _moves(self, p):
        land = self.teleport_at(p)
        if land is not None:          # the teleporter takes over: that's the only way on
            return [land]
        if self.swim and self.water(p):
            return self._swim_moves(p)
        x, y, z = p
        on_ladder = self._on_ladder(p)
        out = []
        jump = JUMP_HEIGHT / self.gravity(p) if self.zones else JUMP_HEIGHT
        for dx, dy in ((self.step, 0), (-self.step, 0), (0, self.step), (0, -self.step)):
            nx, ny = x + dx, y + dy
            dest = None
            for lift in (STEP_HEIGHT, 0, jump):
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
        if self.jumps and not on_ladder and self._solid((x, y, z - 1)):
            out += self._jump_moves(p)
        for _, (x0, x1, y0, y1), sz, rise in self.lifts:     # standing on a lift: ride it
            if x0 <= x <= x1 and y0 <= y <= y1:
                for at, to in ((sz, sz + rise), (sz + rise, sz)):
                    if abs(z - at) < 1 and not self._solid((x, y, to)):
                        out.append((x, y, to))
        return out

    def _swim_moves(self, p):
        """Swimming: a SWIM step in any of 6 directions while in water; out over an edge
        or a sill (falling, or wading on); onto a ledge whose standing origin is up to
        WATER_CLIMB above (pm_shared's water jump); never up out of the surface."""
        out = []
        x, y, z = p
        s = SWIM
        for dx, dy, dz in ((s, 0, 0), (-s, 0, 0), (0, s, 0), (0, -s, 0), (0, 0, s), (0, 0, -s)):
            q = (x + dx, y + dy, z + dz)
            if not self._solid(q):
                if self.water(q):
                    out.append(q)
                elif not dz:
                    d = self._drop(*q)
                    if d:
                        out.append(d)
                continue
            if dz:
                continue
            for lift in range(16, WATER_CLIMB + 1, 16):     # a wall: climb out onto it
                if self._solid((x, y, z + lift)):
                    break
                r = (x + dx, y + dy, z + lift)
                if not self._solid(r):
                    d = self._drop(*r)
                    if d:
                        out.append(d)
                    break
        return out

    # ------------------------------------------------------------------ jumping
    def _jump_moves(self, p):
        """Landings of running jumps (and long jumps) from p off an edge: in each of 8
        directions where the ground drops away in front of the player."""
        out = []
        x, y, z = p
        for d in DIRS8:
            ahead = (x + d[0] * 12, y + d[1] * 12, z)
            if self._solid(ahead):
                continue                       # a wall: stepping and jumping up cover it
            below = self._drop(*ahead)
            if below is not None and z - below[2] <= STEP_HEIGHT:
                continue                       # flat ground ahead: walking covers it
            kinds = []
            behind = (x - d[0] * 32, y - d[1] * 32, z)
            if not self._solid(behind) and self._solid((behind[0], behind[1], z - STEP_HEIGHT - 1)):
                kinds.append((RUN_JUMP, JUMP_SPEED))          # room for a run-up
            if self.long_jump:
                kinds.append(LONG_JUMP)
            for vh, vz in kinds:
                spot = self._jump(p, d, vh, vz)
                if spot:
                    out.append(spot)
        return out

    def _jump(self, p, d, vh, vz):
        """A jump's landing, flown once without doors; flown again only for the doors
        in its way (a jump on the far side of the map doesn't care about the airlock)."""
        key = (p, d, vh, self._wtoken)
        if key not in self._arcs:
            saved, self.blockers = self.blockers, []
            try:
                self._arcs[key] = (self._arc(p, d, vh, vz), self._flown)
            finally:
                self.blockers = saved
        spot, (lo, hi) = self._arcs[key]
        if not any(all(blo[k] < hi[k] and bhi[k] > lo[k] for k in range(3)) for blo, bhi in self.blockers):
            return spot
        key = (p, d, vh, self._token, self._wtoken)
        if key not in self._arcs_blocked:
            self._arcs_blocked[key] = self._arc(p, d, vh, vz)
        return self._arcs_blocked[key]

    _token = 0

    def configure(self, blockers=None, teleports=None, long_jump=None, waters=None, removed=None):
        """Set what changes between states of play (arcs are re-flown when it does)."""
        if blockers is not None:
            self.blockers = blockers
        if teleports is not None:
            self.teleports = teleports
        if long_jump is not None:
            self.long_jump = long_jump
        if waters is not None:
            self.waters = list(waters)
        if removed is not None:
            self.removed = frozenset(removed)
        self._token = tuple(self.blockers)
        self._wtoken = (tuple(self.waters), self.removed)

    _wtoken = ((), frozenset())

    def _arc(self, p, d, vh, vz):
        """Fly a jump from p in direction d: returns the standing position it lands on,
        or None (lands nowhere, lands deadly, falls too far)."""
        g = self.gravity(p)
        a = GRAVITY * g
        dt = min(0.02, 6.0 / vh)
        x, y, z = p
        top = z
        lo, hi = list(p), list(p)
        # the box the flight passes through (and the landing search around its end)
        self._flown = (tuple(c - 24 for c in p), tuple(c + 24 for c in p))
        for _ in range(int(3.0 / dt)):
            nz = z + vz * dt - 0.5 * a * dt * dt
            vz -= a * dt
            if self._solid((x, y, nz)):
                if vz < 0:                     # came down on something
                    break
                vz, nz = 0.0, z                # head hit a ceiling
            nx, ny = x + d[0] * vh * dt, y + d[1] * vh * dt
            if vh and self._solid((nx, ny, nz)):
                vh, nx, ny = 0.0, x, y         # hit a wall: drop down along it
            x, y, z = nx, ny, nz
            top = max(top, z)
            if self.swim and self.water((x, y, z)):
                return self._afloat(x, y, z)       # into water: it breaks the fall
            for k, c in enumerate((x, y, z)):
                lo[k], hi[k] = min(lo[k], c), max(hi[k], c)
            self._flown = (tuple(c - 24 for c in lo[:2]) + (lo[2] - MAX_FALL,), tuple(c + 24 for c in hi))
            if self.lethal and self.deadly((x, y, z)):
                return None
            if top - z > MAX_FALL / g:
                return None
        else:
            return None
        spot = self.settle((x, y, z), max_up=4)
        if spot is None or self._solid(spot) or (self.lethal and self.deadly(spot)):
            return None
        if top - spot[2] > MAX_FALL / g or spot == p:
            return None
        return spot

    def settle(self, p, max_up=64):
        """The standing position at p: on the grid (x, y multiples of `step`, the
        nearest clear one), dropped onto the ground. None if there is none nearby."""
        z0 = round(p[2])
        s = self.step
        bx, by = s * round(p[0] / s), s * round(p[1] / s)
        cands = sorted(((bx + i * s, by + j * s) for i in (-1, 0, 1) for j in (-1, 0, 1)),
                       key=lambda c: (c[0] - p[0]) ** 2 + (c[1] - p[1]) ** 2)
        for x, y in cands:
            for up in range(max_up):
                if not self._solid((x, y, z0 + up)):
                    got = self._drop(x, y, z0 + up)
                    if got is not None:
                        return got
                    break
        if max_up < 64:
            return None
        return (bx, by, z0)

    def flood(self, seeds, limit=400000, known=(), goal=None):
        """Every position reachable from `seeds`. known: positions already known to be
        reachable (not explored again; e.g. an earlier flood before a door opened).
        goal(p): stop as soon as a position passes it; returns (found, seen) then.
        With water, a position only counts if a way there keeps the head under for at
        most BREATH units at a stretch (a shortest-path search, the count reset by
        every breath)."""
        if self.swim:
            return self._flood_breathing(seeds, limit, known, goal)
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


    def _flood_breathing(self, seeds, limit, known, goal):
        known = set(known)
        best = {p: 0.0 for p in known}
        heap = []
        for p in seeds:
            best[p] = 0.0
            heapq.heappush(heap, (0.0, p))
        while heap and len(best) < limit:
            c, p = heapq.heappop(heap)
            if c > best.get(p, c):
                continue
            if goal is not None and goal(p):
                return True, set(best)
            for q in self._moves(p):
                nc = c + math.dist(p, q) if self.underwater(q) else 0.0
                if nc <= BREATH and nc < best.get(q, BREATH + 1):
                    best[q] = nc
                    if q not in known:
                        heapq.heappush(heap, (nc, q))
        return (False, set(best)) if goal is not None else set(best)


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
        ang = math.degrees(math.atan2(p[1] - item[1], p[0] - item[0]))
        sector = round(ang / 45) % 8
        # straight down the sector's middle first (positions are on a grid), then the
        # distance nearest the middle of near..far
        off = abs(d * math.sin(math.radians(ang - sector * 45)))
        best.setdefault(sector, []).append((off // 8, abs(d - (near + far) / 2), p))
    out = []
    for sector, cands in sorted(best.items()):
        for *_, p in sorted(cands)[:12]:
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
        self.unarmed = []        # (monster, position, path): met without a weapon
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
    verb = ("pick up" if c.startswith(("item_", "weapon_", "ammo_")) else "touch" if c.startswith("trigger_")
            else "break" if c == "func_breakable" else "turn" if c == "func_rot_button" else "press")
    return f"{verb} {c} at {at} -> {e.get('target')}"


HOSTILE = {"monster_headcrab", "monster_zombie", "monster_houndeye", "monster_bullchicken", "monster_alien_slave",
           "monster_alien_grunt", "monster_human_grunt", "monster_human_assassin", "monster_snark",
           "monster_babycrab", "monster_alien_controller", "monster_gargantua", "monster_barnacle",
           "monster_leech", "monster_ichthyosaur"}


def _clear_line(hulls, a, b, step=16):
    """Nothing solid (the world's sight hull) on the line from a to b?"""
    n = max(1, int(math.dist(a, b) // step))
    return all(hulls.contents(0, tuple(a[k] + (b[k] - a[k]) * i / n for k in range(3))) != -2 for i in range(n + 1))


def threatens(hulls, kind, o, p, in_water):
    """Can a `kind` monster at o get at a player standing at p? A barnacle only from
    above (its tongue drops straight down); a leech only in the water; anything else
    within 256 across and 160 up or down, with nothing solid between."""
    if kind == "monster_barnacle":
        return abs(p[0] - o[0]) <= 48 and abs(p[1] - o[1]) <= 48 and p[2] < o[2] and             _clear_line(hulls, o, (p[0], p[1], p[2] + EYES))
    if kind in ("monster_leech", "monster_ichthyosaur") and not in_water(p):
        return False
    return abs(p[0] - o[0]) <= 256 and abs(p[1] - o[1]) <= 256 and abs(p[2] - o[2]) <= 160 and         _clear_line(hulls, (o[0], o[1], o[2] + 16), (p[0], p[1], p[2] + EYES))


def progression(hulls, checkpoints, radius=24, light=None, max_states=300, globals=None, start=None,
                exits=None, watch=(), inventory=(), jumps=None, start_world=None, come_back=()):
    """Play the map's logic on foot. From the player start, every progress-relevant
    thing the player can reach (pickups, buttons, trigger volumes) is tried in every
    order, with its effects simulated through the entity logic (hlmap/sim.py: relays,
    multi_managers, locks, global state, gates...). Doors block while locked.

    globals, start, inventory: arriving from another map, the global states carried
    over, where the player lands (a standing origin) instead of the player start, and
    the gear and weapons they bring (classnames).
    exits: {name: (mins, maxs[, master])} volumes that leave the map
    (trigger_changelevel); with a master, only while it is on (a pad's power).
    start_world: a World the map was left in (from `exits`): coming back into it as
    it was, rather than as on a fresh load (with `start`, where the player lands).
    jumps: fly running jumps and long jumps (default: when the map has a long jump
    module or gravity zones). Gear (the HEV suit, the long jump module, weapons) is
    picked up like keys and is part of the state of play.
    watch: global states worth telling apart even if no door here depends on them
    (the ones the next map reads), so every way to set them is explored.
    come_back: exits (names in `exits`) the player can leave by and come back in to
    play the map again (another map leads back): a state from which one of them can be
    used isn't a lockout, even with areas closed behind the player (a course that
    ends behind a one-way door). Check the coming back with round trips.

    Returns a Progress:
      missing    checkpoints no order of play reaches
      log        the shortest line of play that reaches everything, step by step
      never      locks never opened
      softlocks  lines of play after which some area can never be reached again
      darkness   (with `light`, a FloorLight) for each state along the way: how much
                 darkness the best way to the next objective crosses. There is no
                 flashlight without the HEV suit, so dark stretches are real.
      exits      {name: [(globals, position, path, inventory, world)]}: every distinct
                 global state and inventory the player can leave through each exit
                 with, where they touch it, a line of play that gets there, and the
                 map's state then (a World)
      unarmed    [(monster, position, path)]: hostiles the player can meet unarmed
    """
    from .sim import BUTTONS, DOORS, ITEMS, World
    res = Progress()
    ents = hulls.entities
    models = hulls.models()
    if start_world is not None:
        world0 = start_world.copy()
        if globals:
            world0.globals.update(globals)
        world0.start()
    else:
        world0 = World(ents, globals, inventory).start()
    res.warnings += world0.warnings
    ladders = [_placed(models, e) for e in ents if e.get("classname") == "func_ladder"]
    zones = gravity_zones(hulls)
    if jumps is None:            # (a player who brings the long jump module jumps too)
        jumps = bool(zones) or any(e.get("classname") == "item_longjump" for e in ents) or world0.long_jump
    movers = water_movers(hulls)
    w = Walker(hulls, ladders, solids=solid_entities(hulls), zones=zones, lethal=lethal_volumes(hulls),
               jumps=jumps, lifts=lifts(hulls), water=True if movers else None)
    tele = [(i, box, w.settle(land)) for i, box, land, _ in teleports(hulls) if land is not None]
    brk = {i: _grow(*_placed(models, ents[i])) for i in breakables(hulls)}
    doors = []
    for i, e in enumerate(ents):
        if e.get("classname") in DOORS and (e.get("master") or e.get("targetname")) and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            doors.append((i, (tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))))
    actions = []    # (entity, method, reach test)
    gear = set()
    for i, e in enumerate(ents):
        cls = e.get("classname", "")
        if not e.get("target") and not (cls in ("item_suit", "item_longjump") or cls.startswith("weapon_")):
            continue
        if not e.get("target"):
            gear.add(i)                  # gear: picked up like a key, whether or not it fires anything
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
    for i in brk:                      # breakables: smashed (with a weapon) from next to them
        lo, hi = _placed(models, ents[i])
        actions.append((i, "break_", lambda p, lo=lo, hi=hi:
                        sum(max(0, lo[k] - p[k], p[k] - hi[k]) ** 2 for k in range(3)) <= 64 * 64))
    rel = world0.relevance([i for i, _ in doors] + [i for i, _, _ in tele] + [i for i, _, _ in movers], watch)
    rel = (rel[0] | set(brk), rel[1])
    actions = [a for a in actions if a[0] in rel[0] or a[0] in gear]

    cache = {}

    def configure(cfg):
        blocked, enabled, lj, wet, broken = cfg
        w.configure(blockers=[b for i, b in doors if i in blocked],
                    teleports=[(box, land) for i, box, land in tele if i in enabled], long_jump=lj,
                    waters=[moved if i in wet else at for i, at, moved in movers], removed=broken)

    def flood(world, pos):
        blocked = tuple(i for i, _ in doors if not world.door_passable(i))
        enabled = tuple(i for i, _, _ in tele if world.teleport_enabled(i))
        lj = jumps and world.long_jump
        wet = tuple(i for i, _, _ in movers if i in world.opened)       # func_waters moved
        broken = tuple(i for i in brk if i in world.gone)
        cfg = (blocked, enabled, lj, wet, broken)
        for comp in cache.get(cfg, ()):
            if pos in comp:
                return comp, cfg
        configure(cfg)
        # a door (or more) opened, or something broken, since an earlier flood that
        # reached pos: everything it reached is still reachable, so only grow it from
        # there (with the same teleporters on: one that switches on also stops walks
        # across it; and the same water)
        base = None
        for (b_other, e_other, lj_other, wet_other, br_other), comps in cache.items():
            if e_other == enabled and lj_other == lj and wet_other == wet and set(blocked) <= set(b_other) \
                    and set(broken) >= set(br_other):
                for comp in comps:
                    if pos in comp and (base is None or len(comp) > len(base[1])):
                        base = (b_other, comp, br_other)
        if base is not None:
            opened_boxes = [b for i, b in doors if i in base[0] and i not in blocked]
            opened_boxes += [brk[i] for i in broken if i not in base[2]]
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
        comp, cfg = flood(world, pos)
        blocked, enabled, lj = cfg[:3]
        key = (world.key(rel), min(comp))
        if via:
            nodes[via[0]]["children"].append((via[1], key))
        if key in nodes:
            continue
        if len(nodes) >= max_states:
            res.truncated = True
            continue
        node = {"world": world, "comp": comp, "blocked": blocked, "enabled": enabled, "lj": lj, "cfg": cfg,
                "entry": pos,
                "path": path, "children": [], "parent": via[0] if via else None}
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

    # states from which the player can leave and come back (come_back), and what a
    # line of play has seen on the way to each state
    back = set()
    for name in come_back:
        ex = (exits or {}).get(name)
        if ex is None:
            continue
        master = ex[2] if len(ex) > 2 else None
        back |= {k for k in order if nodes[k]["world"].master_ok(master)
                 and any(touches_box(p, ex[0], ex[1]) for p in nodes[k]["comp"])}
    seen_on_way = {}
    for k in order:                   # parents come first (breadth first)
        par = nodes[k]["parent"]
        seen_on_way[k] = cov[k] | (seen_on_way[par] if par in seen_on_way else frozenset())
    goals = {k for k in order if cov[k] == reachable}
    if not goals and back:            # a one-way course: all of it on the way to leaving
        goals = {k for k in order if k in back and seen_on_way[k] == reachable}
    if not goals:
        res.warnings.append("no single state of play reaches every area (areas that close behind you?)")
        goals = {max(order, key=lambda k: len(cov[k]))}
    finish = set(goals) | back
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
        configure(node["cfg"])
        for t, (lo, hi), land in tele:
            if t not in node["enabled"]:
                continue
            around = lambda p, lo=lo, hi=hi: (not all(lo[k] <= p[k] <= hi[k] for k in range(3)) and
                                              all(lo[k] - 48 <= p[k] <= hi[k] + 48 for k in range(2)) and
                                              lo[2] - 48 <= p[2] <= hi[2])
            back, seen = w.flood([land], goal=around)
            lost = sorted(checkpoints[c][0] for c in cov[best] - covers(seen)) if not back else []
            res.teleports.append((tele_name(t), back, lost))

    for name, ex in (exits or {}).items():     # what the player can leave with
        lo, hi = ex[0], ex[1]
        master = ex[2] if len(ex) > 2 else None
        out, seen = [], set()
        for k in order:
            node = nodes[k]
            g = (tuple(sorted(node["world"].globals.items())), tuple(sorted(node["world"].inventory)))
            if g in seen or not node["world"].master_ok(master):
                continue
            spot = next((p for p in node["comp"] if touches_box(p, lo, hi)), None)
            if spot is not None:
                seen.add(g)
                out.append((dict(g[0]), spot, node["path"], sorted(g[1]), node["world"]))
        res.exits[name] = out

    # hostiles the player can walk up to without a weapon
    spawns = []
    for e in ents:
        cls = e.get("classname", "")
        kind = e.get("monstertype") if cls == "monstermaker" else cls
        if kind in HOSTILE and e.get("origin"):
            spawns.append((kind, tuple(float(c) for c in e["origin"].split())))
    for kind, o in spawns:
        for k in order:
            node = nodes[k]
            if node["world"].armed:
                continue
            if any(threatens(hulls, kind, o, p, w.water) for p in node["comp"]):
                res.unarmed.append((kind, tuple(round(c) for c in o), node["path"]))
                break

    if light is not None:
        seeable_cache, walk_cache = {}, {}
        for k in order:
            if k not in finish or k in goals:
                continue
            node = nodes[k]
            if "item_suit" in node["world"].inventory:
                continue                  # the suit has a flashlight
            useful = [(a, c) for a, c in node["children"] if c in finish]
            if not useful:
                continue
            levels = node["world"].style_levels()
            sig = (tuple(sorted(levels.items())), id(node["comp"]))
            if sig not in seeable_cache:
                seeable_cache[sig] = _seeable(node["comp"], light, levels)
            seeable = seeable_cache[sig]
            configure(node["cfg"])
            best_cost, best_a = None, None
            for a, _ in useful:
                # states that differ only in things that don't move doors or lights
                # (e.g. who has said what) walk the same way
                wk = (sig, node["cfg"], node["entry"], a[0])
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
    changes = [_grow(*b) for _, _, b, _ in changelevels(hulls)]
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


def stranded_check(hulls, pos, globals_=None, inventory=(), exits=None):
    """Coming back into a map from a later one: from `pos`, with the carried global
    states and gear, can the player reach a way out that works (e.g. the pad they came
    by)? The rest of the map is taken as on a fresh load, an approximation: the game
    restores it as it was left. Returns the name of the way out, or None."""
    from .sim import DOORS, World
    ents = hulls.entities
    models = hulls.models()
    world = World(ents, globals_, inventory).start()
    zones = gravity_zones(hulls)
    jumps = bool(zones) or any(e.get("classname") == "item_longjump" for e in ents) or world.long_jump
    movers = water_movers(hulls)
    w = Walker(hulls, [_placed(models, e) for e in ents if e.get("classname") == "func_ladder"],
               solids=solid_entities(hulls), zones=zones, lethal=lethal_volumes(hulls), jumps=jumps,
               lifts=lifts(hulls), water=True if movers else None)
    blockers = [_grow(*_placed(models, e)) for i, e in enumerate(ents)
                if e.get("classname") in DOORS and (e.get("master") or e.get("targetname"))
                and e.get("model", "").startswith("*") and not world.door_passable(i)]
    tele = [(box, w.settle(land)) for i, box, land, _ in teleports(hulls) if land and world.teleport_enabled(i)]
    w.configure(blockers=blockers, teleports=tele, long_jump=world.long_jump,
                waters=[moved if i in world.opened else at for i, at, moved in movers])
    ways = [(f"{name[0]} ({name[1]})" if isinstance(name, tuple) else str(name), ex[0], ex[1])
            for name, ex in (exits or {}).items() if world.master_ok(ex[2] if len(ex) > 2 else None)]
    if not ways:
        return None
    hit = []

    def out(p):
        for label, lo, hi in ways:
            if touches_box(p, lo, hi):
                hit.append(label)
                return True
        return False
    found, _ = w.flood([w.settle(pos)], goal=out)
    return hit[0] if found else None


def node_positions(hulls, reached, spacing=192):
    """Where to put info_nodes so monsters can find their way (the game builds its node
    graph from them at the first load): one per `spacing` cell of the floor the player
    can walk on (from verify's reachable positions; not swimming), the one nearest the
    cell's middle. Returns node origins, 16 over the floor."""
    best = {}
    for p in reached:
        if hulls.contents(0, p) in LIQUID or hulls.contents(1, (p[0], p[1], p[2] - 1)) in PASSABLE:
            continue                                   # swimming, or not standing on anything
        key = (int(p[0] // spacing), int(p[1] // spacing), int(p[2] // 96))
        mid = ((key[0] + 0.5) * spacing, (key[1] + 0.5) * spacing)
        d = (p[0] - mid[0]) ** 2 + (p[1] - mid[1]) ** 2
        if key not in best or d < best[key][0]:
            best[key] = (d, p)
    return sorted((p[0], p[1], p[2] - HALF[2] + 16) for _, p in best.values())
