"""Room-based level layout: describe the AIR, get sealed walls for free.

    lvl = Level(wall=16)
    office = lvl.room("office", (0, 0, 0), (320, 240, 128), OFFICE)
    hall = lvl.room("hall", (-160, -112, 0), (480, -16, 128), HALL)
    door = lvl.doorway(office, hall, width=64, height=96)
    lvl.build(m)          # adds carved world brushes to Map m

Every room is an axis-aligned box of empty space (mins = floor corner, maxs =
ceiling corner). The builder surrounds each room with a solid shell `wall` units
thick, merges the shells, carves out all air (rooms + openings) and textures each
face by the room it faces. Because the solid always encloses the air, the level
cannot leak unless an opening pokes outside every shell (checked).
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Brush, make_face, SIDE_NAMES
from .wad import default_db

AXES = "xyz"


# ---------------------------------------------------------------- AABB helpers

@dataclass(frozen=True)
class AABB:
    mins: tuple
    maxs: tuple

    def valid(self):
        return all(self.mins[i] < self.maxs[i] for i in range(3))

    def overlaps(self, o):
        return all(self.mins[i] < o.maxs[i] and o.mins[i] < self.maxs[i] for i in range(3))

    def contains_point(self, p):
        return all(self.mins[i] <= p[i] <= self.maxs[i] for i in range(3))

    def expand(self, t):
        return AABB(tuple(c - t for c in self.mins), tuple(c + t for c in self.maxs))

    def volume(self):
        v = 1
        for i in range(3):
            v *= self.maxs[i] - self.mins[i]
        return v


def subtract(a: AABB, b: AABB):
    """a minus b as a list of disjoint boxes."""
    if not a.overlaps(b):
        return [a]
    out = []
    lo, hi = list(a.mins), list(a.maxs)
    for i in range(3):
        if lo[i] < b.mins[i]:
            m = list(hi); m[i] = b.mins[i]
            out.append(AABB(tuple(lo), tuple(m)))
            lo[i] = b.mins[i]
        if hi[i] > b.maxs[i]:
            m = list(lo); m[i] = b.maxs[i]
            out.append(AABB(tuple(m), tuple(hi)))
            hi[i] = b.maxs[i]
    return out


def subtract_all(boxes, cutter):
    return [p for b in boxes for p in subtract(b, cutter)]


def split_at(box: AABB, axis, coords):
    cuts = sorted(c for c in coords if box.mins[axis] < c < box.maxs[axis])
    if not cuts:
        return [box]
    out, lo = [], box.mins[axis]
    for c in cuts + [box.maxs[axis]]:
        mn, mx = list(box.mins), list(box.maxs)
        mn[axis], mx[axis] = lo, c
        out.append(AABB(tuple(mn), tuple(mx)))
        lo = c
    return out


# ---------------------------------------------------------------- materials

@dataclass(frozen=True)
class Material:
    """Textures for a room. Alignment modes:
    floor_align / ceiling_align: 'world' | 'min' (tile grid starts at room's NW corner)
                                 | 'center' (a tile is centered in the room)
    wall_align: 'floor' (texture bottom edge sits on the room floor) | 'world'
    """
    floor: str
    wall: str
    ceiling: str
    floor_align: str = "world"
    ceiling_align: str = "world"
    wall_align: str = "floor"
    scale: float = 1.0

    def with_(self, **kw):
        from dataclasses import replace
        return replace(self, **kw)


DEFAULT_MATERIAL = Material("FIFTIES_FLR02", "FIFTIES_WALL14A", "FIFTIES_CEIL01")


@dataclass(eq=False)
class Room:
    name: str
    box: AABB
    material: Material
    is_opening: bool = False
    parent: "Room | None" = None
    group: str | None = None     # rooms in the same group may touch/overlap (merged space)
    meta: dict = field(default_factory=dict)

    mins = property(lambda s: s.box.mins)
    maxs = property(lambda s: s.box.maxs)
    floor = property(lambda s: s.box.mins[2])
    ceiling = property(lambda s: s.box.maxs[2])
    size = property(lambda s: tuple(s.box.maxs[i] - s.box.mins[i] for i in range(3)))

    @property
    def center(self):
        return tuple((self.box.mins[i] + self.box.maxs[i]) / 2 for i in range(3))

    def floor_point(self, x=None, y=None, above=0):
        """Absolute point at (x, y) on this room's floor (+above). Defaults to the center."""
        c = self.center
        return (c[0] if x is None else x, c[1] if y is None else y, self.floor + above)

    def rel(self, dx, dy, dz=0):
        """Point relative to the room's floor corner (mins)."""
        return (self.mins[0] + dx, self.mins[1] + dy, self.mins[2] + dz)

    def __repr__(self):
        return f"<Room {self.name} {self.box.mins}..{self.box.maxs}>"


@dataclass
class Opening:
    """A doorway/window punched through the wall between two rooms (or to outside)."""
    room: Room            # the air box of the opening itself
    a: Room
    b: Room | None
    axis: int             # 0 = wall runs along Y (opening crosses X), 1 = crosses Y
    direction: tuple      # unit vector pointing from room a toward room b

    mins = property(lambda s: s.room.box.mins)
    maxs = property(lambda s: s.room.box.maxs)
    center = property(lambda s: s.room.center)

    @property
    def width(self):
        return self.room.size[1 - self.axis]

    @property
    def height(self):
        return self.room.size[2]


# ---------------------------------------------------------------- level

class Level:
    def __init__(self, wall=16, material: Material = DEFAULT_MATERIAL):
        self.wall = wall
        self.material = material
        self.rooms: list[Room] = []
        self.openings: list[Opening] = []
        self.extra_air: list[Room] = []
        self.features: list = []     # things with .emit(m) and .check(level), e.g. tunnels

    # --- description ------------------------------------------------------
    def room(self, name, mins, maxs, material: Material | None = None, group=None, **overrides):
        """Add a room of empty space. overrides: floor=, wall=, ceiling= texture names.
        Rooms must be separated by walls unless they share a `group` (then they merge)."""
        mat = material or self.material
        if overrides:
            mat = mat.with_(**overrides)
        r = Room(name, AABB(tuple(mins), tuple(maxs)), mat, group=group)
        if not r.box.valid():
            raise ValueError(f"room {name}: mins must be < maxs, got {mins} {maxs}")
        self.rooms.append(r)
        return r

    def air(self, name, mins, maxs, like: Room):
        """Extra empty space (alcove, window hole, vent) textured like room `like`."""
        r = Room(name, AABB(tuple(mins), tuple(maxs)), _opening_material(like.material),
                 is_opening=True, parent=like)
        self.extra_air.append(r)
        return r

    def doorway(self, a: Room, b: Room, width=64, height=96, center=None, sill=0, name=None):
        """Cut an opening through the wall separating rooms a and b.

        center: coordinate along the wall (x for a wall running east-west, y for
                north-south). Default: middle of the shared wall span.
        sill:   height of the bottom above the (higher) floor; 0 for doors,
                e.g. 40 for a window.
        """
        found = None
        for axis in (0, 1):
            other = 1 - axis
            lo = max(a.mins[other], b.mins[other])
            hi = min(a.maxs[other], b.maxs[other])
            if hi - lo < width:
                continue
            if a.maxs[axis] <= b.mins[axis]:
                found = (axis, a.maxs[axis], b.mins[axis], lo, hi, +1)
            elif b.maxs[axis] <= a.mins[axis]:
                found = (axis, b.maxs[axis], a.mins[axis], lo, hi, -1)
            if found:
                break
        if not found:
            raise ValueError(f"doorway: rooms {a.name} and {b.name} don't share a wall at least {width} wide")
        axis, w0, w1, lo, hi, sign = found
        if w1 - w0 > 4 * self.wall:
            raise ValueError(f"doorway: gap between {a.name} and {b.name} is {w1 - w0} units (too thick)")
        c = (lo + hi) / 2 if center is None else center
        if c - width / 2 < lo or c + width / 2 > hi:
            raise ValueError(f"doorway: center {c} +- {width / 2} outside shared span {lo}..{hi}")
        z0 = max(a.floor, b.floor) + sill
        z1 = z0 + height
        if z1 > min(a.ceiling, b.ceiling):
            raise ValueError(f"doorway: top {z1} is above a ceiling")
        mins, maxs = [0, 0, z0], [0, 0, z1]
        mins[axis], maxs[axis] = w0, w1
        mins[1 - axis], maxs[1 - axis] = c - width / 2, c + width / 2
        d = [0, 0, 0]
        d[axis] = sign
        r = Room(name or f"{a.name}-{b.name}", AABB(tuple(mins), tuple(maxs)),
                 _opening_material(a.material), is_opening=True, parent=a)
        op = Opening(r, a, b, axis, tuple(d))
        self.openings.append(op)
        return op

    def tunnel(self, name, from_room: Room, side, center, path, mouth=(96, 112), material=None,
               **opts):
        """Organic cave leaving `from_room` through a hole in its `side` wall
        ('north'/'south'/'east'/'west'), centred at `center` along that wall.

        path:   floor-centre control points after the mouth (z = floor height); keep
                turns gentle (radius above half the cave width).
        mouth:  hole (width, height); width must be a multiple of `cell` (default 32).
                The cave starts as exactly this rectangle and flares out over `flare`.
        material / materials=[(fraction, Material), ...] along the cave, blend=0.1
        Other options (cave.Cave): cell, width, height, roughness, floor_noise, flare,
        seed, scale=f(fraction)->size multiplier.
        Returns the Cave (floor_point(), camera(), frame() for placing things).
        Define the other rooms first: the cave keeps clear of their air.
        """
        from .cave import ROCK, Cave
        dirs = {"north": (1, +1), "south": (1, -1), "east": (0, +1), "west": (0, -1)}
        axis, sign = dirs[side]
        other = 1 - axis
        face = (from_room.maxs[axis] + self.wall) if sign > 0 else (from_room.mins[axis] - self.wall)
        mouth_pt = [0, 0, from_room.floor]
        mouth_pt[axis] = face
        mouth_pt[other] = center
        d = [0, 0]
        d[axis] = sign
        if "materials" not in opts:
            opts["materials"] = ((0.0, material or ROCK),)
        avoid = [r.box for r in self.rooms if r is not from_room]
        cave = Cave(name, tuple(mouth_pt), tuple(d), mouth, path, avoid=avoid, **opts)
        # the hole through the wall; the cave's first cell row continues it exactly
        lo, hi = [0, 0, from_room.floor], [0, 0, from_room.floor + mouth[1]]
        inner = from_room.maxs[axis] if sign > 0 else from_room.mins[axis]
        lo[axis], hi[axis] = sorted((inner, face))
        lo[other], hi[other] = center - mouth[0] / 2, center + mouth[0] / 2
        self.air(f"{name}-mouth", lo, hi, like=from_room)
        self.features.append(cave)
        return cave

    def stairs(self, name, lower: Room, upper: Room, top, down, width=80, rise=16, tread=16,
               tread_tex="FIFTIES_TRD03", riser_tex="CRETE4_STP01", side_tex="FIFTIES_DSK5B"):
        """Staircase from `upper`'s floor down into `lower`, through a hole in the slab
        between them (`lower` must sit directly under `upper`, `wall` units apart).

        top:   (x, y) centre of the top edge, where you step off onto upper's floor.
        down:  compass direction the stairs descend toward ('north', 'south', ...).
        The hole is registered as air and is as long as head clearance needs (a
        standing player is 72 tall). Returns (steps func_detail entity, hole Room); put
        a railing around the hole's open sides (props.railing).
        """
        from .geometry import box
        from .mapfile import Entity
        drop = upper.floor - lower.floor
        if drop % rise:
            raise ValueError(f"stairs {name}: height {drop} is not a multiple of rise {rise}")
        if upper.floor - lower.ceiling != self.wall:
            raise ValueError(f"stairs {name}: {lower.name} must be directly under {upper.name} "
                             f"({self.wall} units of slab between them)")
        dirs = {"north": (1, 1), "south": (1, -1), "east": (0, 1), "west": (0, -1)}
        axis, sign = dirs[down]
        other = 1 - axis
        n = drop // rise
        # hole: over every step where a standing player's head would reach the slab, plus
        # the player's full width (32): the box still stands on a step while its origin is
        # up to 16 past the step's edge, and its front reaches 16 further
        need = sum(1 for k in range(1, n + 1) if lower.floor + k * rise + 72 > lower.ceiling - 4)
        hole_len = need * tread + 32 + 8
        lo, hi = [0, 0, lower.ceiling], [0, 0, upper.floor]
        a0, a1 = sorted((top[axis], top[axis] + sign * hole_len))
        lo[axis], hi[axis] = a0, a1
        lo[other], hi[other] = top[other] - width / 2, top[other] + width / 2
        for r in (lower, upper):
            if not (r.mins[other] <= lo[other] and hi[other] <= r.maxs[other]
                    and r.mins[axis] <= a0 and a1 <= r.maxs[axis]):
                raise ValueError(f"stairs {name}: hole {lo}..{hi} is not inside room {r.name}")
        hole = self.air(f"{name}-hole", lo, hi, like=upper)
        steps = []
        for k in range(1, n + 1):          # k = n is the top step, level with upper's floor
            along0 = top[axis] + sign * (n - k) * tread
            along1 = along0 + sign * tread
            smin, smax = [0, 0, lower.floor], [0, 0, lower.floor + k * rise]
            smin[axis], smax[axis] = sorted((along0, along1))
            smin[other], smax[other] = top[other] - width / 2, top[other] + width / 2
            b = box(tuple(smin), tuple(smax), side_tex, comment=f"{name} step {k}")
            v = _unit(axis, sign)                      # texture 'down' = toward the front edge,
            u = (-v[1], v[0], 0)                       # so the nosing strip sits on the edge
            b.fit("top", tread_tex, u_axis=u, v_axis=v)
            b.fit(down, riser_tex)
            steps.append(b)
        if steps[0].bounds()[0][axis] < lower.mins[axis] - 0.5 or steps[0].bounds()[1][axis] > lower.maxs[axis] + 0.5:
            raise ValueError(f"stairs {name}: the bottom step runs out of room {lower.name}")
        return Entity("func_detail", brushes=steps, kv={"zhlt_detaillevel": "1"}), hole

    # --- queries ------------------------------------------------------------
    def all_air(self):
        return self.rooms + [o.room for o in self.openings] + self.extra_air

    def is_air(self, p, tol=0.0):
        """True if p is inside intended air (rooms, openings, extra air, caves), with
        `tol` units of slack."""
        for r in self.all_air():
            b = r.box
            if all(b.mins[k] - tol <= p[k] <= b.maxs[k] + tol for k in range(3)):
                return True
        return any(f.contains(p, tol) for f in self.features if hasattr(f, "contains"))

    def checkpoints(self):
        """[(name, [standing-player origins])] that must be reachable: every room (centre
        and inset corners) and stretches of every cave."""
        out = []
        for r in self.rooms:
            (x0, y0, z), (x1, y1, _) = r.mins, r.maxs
            pts = [((x0 + x1) / 2, (y0 + y1) / 2)] + [(x, y) for x in (x0 + 40, x1 - 40) for y in (y0 + 40, y1 - 40)]
            out.append((f"room {r.name}", [(x, y, z + 37) for x, y in pts]))
        for f in self.features:
            if hasattr(f, "checkpoints"):
                for k, p in enumerate(f.checkpoints()):
                    out.append((f"{f.name} stretch {k + 1}", [(p[0], p[1], p[2] + 37)]))
        return out

    def is_inside(self, p):
        return (any(r.box.contains_point(p) for r in self.all_air())
                # +2: things standing exactly on a tunnel floor count as inside
                or any(f.contains((p[0], p[1], p[2] + 2)) for f in self.features if hasattr(f, "contains")))

    def room_at(self, p):
        for r in self.rooms:
            if r.box.contains_point(p):
                return r
        return None

    def check(self):
        problems = []
        for i, a in enumerate(self.rooms):
            for b in self.rooms[i + 1:]:
                if a.group is not None and a.group == b.group:
                    continue
                if all(a.box.mins[k] <= b.box.maxs[k] and b.box.mins[k] <= a.box.maxs[k] for k in range(3)):
                    problems.append(f"rooms {a.name} and {b.name} touch or overlap (no wall between "
                                    f"them); separate them by {self.wall} units or give them a group")
        for f in self.features:
            problems.extend(f.check(self) if hasattr(f, "check") else [])
        shells = [r.box.expand(self.wall) for r in self.rooms]
        for r in [o.room for o in self.openings] + self.extra_air:
            rest = [r.box]
            for s in shells:
                rest = subtract_all(rest, s)
            if rest:
                problems.append(f"opening {r.name} pokes outside the level (would leak): {rest[0]}")
        return problems

    # --- build --------------------------------------------------------------
    def solids(self):
        """Disjoint solid boxes after carving, each with a per-side texture spec."""
        solid: list[AABB] = []
        for r in self.rooms:
            for piece in subtract(r.box.expand(self.wall), r.box):
                pieces = [piece]
                for s in solid:
                    pieces = subtract_all(pieces, s)
                solid.extend(pieces)
        airs = self.all_air()
        for a in airs:
            solid = subtract_all(solid, a.box)
        # slice at every air boundary so each face touches at most one kind of air
        for axis in range(3):
            coords = {a.box.mins[axis] for a in airs} | {a.box.maxs[axis] for a in airs}
            solid = [p for b in solid for p in split_at(b, axis, coords)]
        cells = [(b, self._specs(b, airs)) for b in solid]
        return _merge(cells)

    def _specs(self, b: AABB, airs):
        specs = {}
        for n, name in SIDE_NAMES.items():
            axis = [i for i in range(3) if n[i]][0]
            pos = b.maxs[axis] if n[axis] > 0 else b.mins[axis]
            spec = None
            for a in airs:  # rooms first, so rooms win over openings
                touch = a.box.mins[axis] if n[axis] > 0 else a.box.maxs[axis]
                if touch != pos:
                    continue
                if all(b.mins[i] < a.box.maxs[i] and a.box.mins[i] < b.maxs[i] for i in range(3) if i != axis):
                    spec = _face_spec(a, name)
                    break
            specs[name] = spec
        return specs

    def build(self, m):
        problems = self.check()
        if problems:
            raise ValueError("level problems:\n  " + "\n  ".join(problems))
        brushes = []
        for b, specs in self.solids():
            fallback = next((s for s in specs.values() if s), ("NULL", 0, 0, 1))
            faces = []
            for n, name in SIDE_NAMES.items():
                p = b.maxs if sum(n) > 0 else b.mins
                tex, uo, vo, sc = specs[name] or fallback
                f = make_face(n, p, tex)
                f.u_offset, f.v_offset, f.u_scale, f.v_scale = uo, vo, sc, sc
                faces.append(f)
            brushes.append(Brush(faces, "level"))
        m.add_world(*brushes)
        for f in self.features:
            f.emit(m)
        m.level = self
        return brushes


def _unit(axis, sign=1):
    v = [0, 0, 0]
    v[axis] = sign
    return tuple(v)


def _opening_material(mat: Material):
    # door/window reveals: floor like the room, sides and top in the wall texture
    return mat.with_(ceiling=mat.wall, wall_align="world")


def _face_spec(air: Room, side):
    """(texture, u_offset, v_offset, scale) for a solid face touching `air` on `side`
    (`side` is the solid face's outward direction; 'top' = floor of the air)."""
    mat = air.material
    sc = mat.scale
    if side == "top":
        tex, mode = mat.floor, mat.floor_align
    elif side == "bottom":
        tex, mode = mat.ceiling, mat.ceiling_align
    else:
        tex, mode = mat.wall, mat.wall_align
    try:
        tw, th = default_db().size(tex)
    except KeyError:
        return (tex, 0, 0, sc)
    box = (air.parent.box if air.is_opening and air.parent else air.box)
    uo = vo = 0.0
    if side in ("top", "bottom"):
        # world axes for floors/ceilings: s = x/sc + uo, t = -y/sc + vo
        if mode == "min":
            uo = (-box.mins[0] / sc) % tw
            vo = (box.maxs[1] / sc) % th
        elif mode == "center":
            cx = (box.mins[0] + box.maxs[0]) / 2
            cy = (box.mins[1] + box.maxs[1]) / 2
            uo = (tw / 2 - cx / sc) % tw
            vo = (th / 2 + cy / sc) % th
    elif mode == "floor":
        # walls: t = -z/sc + vo ; put the texture's bottom edge on the floor
        vo = (box.mins[2] / sc) % th
    return (tex, round(uo, 4), round(vo, 4), sc)


def _merge(cells):
    """Greedily merge adjacent boxes whose merged faces keep a single texture spec."""
    changed = True
    while changed:
        changed = False
        for axis in range(3):
            others = [i for i in range(3) if i != axis]
            groups = {}
            for c in cells:
                b = c[0]
                key = tuple((b.mins[i], b.maxs[i]) for i in others)
                groups.setdefault(key, []).append(c)
            out = []
            lo_name = {0: "west", 1: "south", 2: "bottom"}[axis]
            hi_name = {0: "east", 1: "north", 2: "top"}[axis]
            for g in groups.values():
                g.sort(key=lambda c: c[0].mins[axis])
                cur = g[0]
                for nxt in g[1:]:
                    merged = _try_merge(cur, nxt, axis, lo_name, hi_name)
                    if merged:
                        cur = merged
                        changed = True
                    else:
                        out.append(cur)
                        cur = nxt
                out.append(cur)
            cells = out
    return cells


def _try_merge(c1, c2, axis, lo_name, hi_name):
    (b1, s1), (b2, s2) = c1, c2
    if b1.maxs[axis] != b2.mins[axis]:
        return None
    specs = {lo_name: s1[lo_name], hi_name: s2[hi_name]}
    for side in s1:
        if side in (lo_name, hi_name):
            continue
        a, b = s1[side], s2[side]
        if a is not None and b is not None and a != b:
            return None
        # a face that is only partly exposed is fine: the hidden part is culled
        specs[side] = a if a is not None else b
    mins = list(b1.mins); maxs = list(b1.maxs)
    maxs[axis] = b2.maxs[axis]
    return (AABB(tuple(mins), tuple(maxs)), specs)
