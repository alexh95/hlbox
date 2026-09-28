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


# ---------------------------------------------------------------- walking & progression

STEP_HEIGHT = 18      # sv_stepsize
JUMP_HEIGHT = 45      # standing jump
MAX_FALL = 600        # ~ where falling damage becomes lethal
HALF = (16, 16, 36)   # standing player half extents (hull 1)


class Walker:
    """Where a player can get to ON FOOT: gravity, 18-unit steps, 45-unit jumps, falls
    up to MAX_FALL, ladders (func_ladder volumes), and doors - locked doors block until
    their lock opens. Positions are standing-player origins on an 8-unit grid."""

    def __init__(self, hulls, ladders=(), step=8):
        self.h = hulls
        self.step = step
        self.ladders = [(tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))
                        for lo, hi in ladders]
        self.blockers = []
        self._cache = {}

    def _solid(self, p):
        if p not in self._cache:
            self._cache[p] = self.h.contents(1, p) != -1
        if self._cache[p]:
            return True
        return any(all(lo[k] < p[k] < hi[k] for k in range(3)) for lo, hi in self.blockers)

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

    def flood(self, seeds, limit=400000):
        seen = set(seeds)
        todo = deque(seeds)
        while todo and len(seen) < limit:
            p = todo.popleft()
            for q in self._moves(p):
                if q not in seen:
                    seen.add(q)
                    todo.append(q)
        return seen


def _placed(models, e):
    """World bounds of a brush entity (models with an ORIGIN brush are stored relative
    to the entity's origin)."""
    lo, hi = models[int(e["model"][1:])]
    o = tuple(float(c) for c in e["origin"].split()) if e.get("origin") else (0, 0, 0)
    return tuple(lo[k] + o[k] for k in range(3)), tuple(hi[k] + o[k] for k in range(3))


def _entity_graph(ents):
    """targetname -> list of targetnames it fires (through relays and multi_managers)."""
    fires = {}
    for e in ents:
        name = e.get("targetname")
        if not name:
            continue
        out = []
        if e.get("classname") == "multi_manager":
            out = [k for k in e if k not in ("classname", "targetname", "origin", "wait", "spawnflags")]
        elif e.get("target"):
            out = [e["target"]]
        fires.setdefault(name, []).extend(out)
    return fires


def _closure(names, fires):
    seen, todo = set(), list(names)
    while todo:
        n = todo.pop()
        if n in seen:
            continue
        seen.add(n)
        todo.extend(fires.get(n, ()))
    return seen


def progression(hulls, checkpoints, map_entities=(), radius=24):
    """Walk the map from the player start, collecting pickups and pressing buttons that
    are within reach, opening locked doors as their locks get triggered, until nothing
    changes. Returns (unreached checkpoints, unlock log, locks never opened, reached)."""
    ents = hulls.entities
    models = hulls.models()
    fires = _entity_graph(ents)
    ladders = [_placed(models, e) for e in ents if e.get("classname") == "func_ladder"]
    w = Walker(hulls, ladders)
    doors = []   # (lock name, blocker box in origin space, door name)
    for e in ents:
        if e.get("classname", "").startswith("func_door") and e.get("master") and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            blo = tuple(lo[k] - HALF[k] for k in range(3))
            bhi = tuple(hi[k] + HALF[k] for k in range(3))
            doors.append((e["master"], (blo, bhi), e.get("targetname") or e["model"]))
    triggers = []   # (kind, reach test, target)
    for e in ents:
        cls = e.get("classname", "")
        if not e.get("target"):
            continue
        if cls.startswith(("item_", "weapon_", "ammo_")) and e.get("origin"):
            o = tuple(float(c) for c in e["origin"].split())
            triggers.append((f"{cls} at {tuple(round(c) for c in o)}",
                             lambda p, o=o: abs(p[0] - o[0]) <= 32 and abs(p[1] - o[1]) <= 32 and -72 <= p[2] - o[2] <= 72,
                             e["target"]))
        elif cls in ("func_button", "func_rot_button") and e.get("model", "").startswith("*"):
            lo, hi = _placed(models, e)
            triggers.append((f"{cls} at {tuple(round((a + b) / 2) for a, b in zip(lo, hi))}",
                             lambda p, lo=lo, hi=hi: sum(max(0, lo[k] - p[k], p[k] - hi[k]) ** 2 for k in range(3)) <= 64 * 64,
                             e["target"]))
    opened, log = set(), []
    start = next(e for e in ents if e.get("classname") == "info_player_start")
    seeds = {w.settle(tuple(float(c) for c in start["origin"].split()))}
    reached = set()
    while True:
        w.blockers = [box for lock, box, _ in doors if lock not in opened]
        reached = w.flood(list(seeds | reached))
        new = set()
        for desc, reach, target in triggers:
            locks = {n for n in _closure([target], fires) if any(n == d[0] for d in doors)} - opened - new
            if locks and any(reach(p) for p in reached):
                new |= locks
                log.append(f"{', '.join(sorted(locks))} opened by {desc}")
        if not new:
            break
        opened |= new
    grid = {}
    for p in reached:
        grid.setdefault((int(p[0] // 64), int(p[1] // 64)), []).append(p)

    def near(c):
        # a checkpoint that falls inside furniture counts as reached from next to it
        r = radius if hulls.contents(1, tuple(round(v) for v in c)) == -1 else 64
        gx, gy = int(c[0] // 64), int(c[1] // 64)
        return any(abs(p[0] - c[0]) <= r and abs(p[1] - c[1]) <= r and abs(p[2] - c[2]) <= 48
                   for ix in (gx - 1, gx, gx + 1) for iy in (gy - 1, gy, gy + 1) for p in grid.get((ix, iy), ()))
    missing = [(name, pts) for name, pts in checkpoints if not any(near(c) for c in pts)]
    never = sorted({lock for lock, _, _ in doors} - opened)
    return missing, log, never, reached
