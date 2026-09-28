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

    # --- description ------------------------------------------------------
    def room(self, name, mins, maxs, material: Material | None = None, **overrides):
        """Add a room of empty space. overrides: floor=, wall=, ceiling= texture names."""
        mat = material or self.material
        if overrides:
            mat = mat.with_(**overrides)
        r = Room(name, AABB(tuple(mins), tuple(maxs)), mat)
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

    # --- queries ------------------------------------------------------------
    def all_air(self):
        return self.rooms + [o.room for o in self.openings] + self.extra_air

    def is_inside(self, p):
        return any(r.box.contains_point(p) for r in self.all_air())

    def room_at(self, p):
        for r in self.rooms:
            if r.box.contains_point(p):
                return r
        return None

    def check(self):
        problems = []
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
        m.level = self
        return brushes


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
