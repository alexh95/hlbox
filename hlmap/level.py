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

Corridors (Level.corridor) run at any angle along a polyline between two rooms: their
air, walls, floor and ceiling are convex prisms carved with exact CSG (hlmap.csg),
and a room they pass too close to gets its corner cut parallel to them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from .csg import Convex, Plane, line_intersection
from .csg import subtract_all as carve_all
from .geometry import Brush, Face, SIDE_NAMES, box, face_axes, make_face, world_axes
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
WATER_TEX = "!C2A5"          # liquids.wad: the dam's blue water ('!' makes it water)


@dataclass(eq=False)
class Room:
    name: str
    box: AABB
    material: Material
    is_opening: bool = False
    parent: "Room | None" = None
    group: str | None = None     # rooms in the same group may touch/overlap (merged space)
    meta: dict = field(default_factory=dict)
    cuts: list = field(default_factory=list)   # [((a, b), c)]: the air also has a*x + b*y <= c

    def contains(self, p, tol=0.0):
        """Is p in this room's air (its box, minus any cut corners)?"""
        b = self.box
        if not all(b.mins[k] - tol <= p[k] <= b.maxs[k] + tol for k in range(3)):
            return False
        return all((a * p[0] + bb * p[1] - c) / math.hypot(a, bb) <= tol for (a, bb), c in self.cuts)

    def convex(self):
        cv = Convex.box(self.mins, self.maxs)
        for (a, b), c in self.cuts:
            cv = cv.clipped(Plane((a, b, 0), c, _line_points(a, b, c)))
        return cv.tidy() if self.cuts else cv

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
        self.corridors: list = []
        self.notes: list = []        # things the builder did that you should know about

    # --- description ------------------------------------------------------
    def room(self, name, mins, maxs, material: Material | None = None, group=None, checkpoints=None, water=None,
             water_tex=WATER_TEX, **overrides):
        """Add a room of empty space. overrides: floor=, wall=, ceiling= texture names.
        Rooms must be separated by walls unless they share a `group` (then they merge).
        checkpoints: [(x, y), ...] places in it that must be reachable on foot (default:
        the centre and inset corners; give them for rooms with terrain). An empty list:
        nothing in it needs reaching (a view through a window, a sky).
        water: fill the room with water this deep (from its floor; up to its ceiling
        floods it); doorways between watered rooms are filled to the lower level."""
        mat = material or self.material
        if overrides:
            mat = mat.with_(**overrides)
        meta = {"checkpoints": list(checkpoints)} if checkpoints is not None else {}
        if water:
            meta["water"] = (mins[2] + min(water, maxs[2] - mins[2]), water_tex)
        r = Room(name, AABB(tuple(mins), tuple(maxs)), mat, group=group, meta=meta)
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

    def corridor(self, name, path, width=96, height=112, material=None, cut=True, max_cut=0.3, checkpoints=True):
        """A corridor along a polyline `path` [(x, y), ...] at any angle, from inside one
        room to inside another (both ends must be in room air; the rooms' walls get
        carved where it passes through). Keep points on integers and turns at 45 or 90
        degrees and every plane stays exact. Floor = the first room's floor.

        cut: other rooms it passes within a wall of get the corner cut off, parallel
        to it and one wall away (their cut corner becomes solid); a cut that would
        take more than `max_cut` of a room's floor is an error. Returns the Corridor
        (floor_point(), frame() for placing things). checkpoints=False: nothing in it
        needs reaching on foot (a railway cutting with a live rail)."""
        start = self.room_at((path[0][0], path[0][1], self._floor_near(path[0]) + 1))
        end = self.room_at((path[-1][0], path[-1][1], self._floor_near(path[-1]) + 1))
        if start is None or end is None:
            raise ValueError(f"corridor {name}: both ends must be inside rooms")
        if start.floor != end.floor:
            raise ValueError(f"corridor {name}: {start.name} and {end.name} have different floors")
        mat = (material or start.material).with_(floor_align="world", ceiling_align="world")
        c = Corridor(name, path, width, height, start.floor, self.wall, mat, (start, end))
        c.must_reach = checkpoints
        for r in self.rooms:
            if r in (start, end):
                continue
            for seg in c.segments:
                if not r.convex().overlaps(seg["outer"]):
                    continue
                if not cut:
                    raise ValueError(f"corridor {name} passes through room {r.name}")
                (a, b), co = seg["cut_left"] if seg["side_of"](r.center) > 0 else seg["cut_right"]
                before = _floor_area(r.convex(), r.floor)
                r.cuts.append(((a, b), co))
                after = _floor_area(r.convex(), r.floor) if r.convex().valid() else 0
                lost = 1 - after / before
                if lost > max_cut:
                    raise ValueError(f"corridor {name}: cutting room {r.name} would take {lost:.0%} of its floor "
                                     f"(max {max_cut:.0%}); move the corridor")
                grown = r.box.expand(self.wall)
                for o in self.openings:
                    if r not in (o.a, o.b):
                        continue
                    (x0, y0, _), (x1, y1, _) = o.room.mins, o.room.maxs
                    if any(grown.contains_point((x, y, r.floor)) and a * x + b * y > co
                           for x in (x0, x1) for y in (y0, y1)):
                        raise ValueError(f"corridor {name}: the cut through {r.name} reaches doorway {o.room.name}")
                self.notes.append(f"{r.name}: corner cut by corridor {name} ({lost:.0%} of its floor)")
        self.corridors.append(c)
        return c

    def terrain(self, name, room, height, **opts):
        """Hills and lawns in an (outdoor) room: a heightfield of brush columns rising
        from its floor; see hlmap.terrain.Terrain. Returns the Terrain (surface(x, y))."""
        from .terrain import Terrain
        t = Terrain(name, room, height, **opts)
        self.features.append(t)
        return t

    def _floor_near(self, xy):
        """Floor of the highest room over (x, y) (stacked rooms: the upper one)."""
        floors = [r.floor for r in self.rooms if r.mins[0] <= xy[0] <= r.maxs[0] and r.mins[1] <= xy[1] <= r.maxs[1]]
        return max(floors) if floors else 0

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
    def floor_polygons(self, spaces):
        """The floors of rooms and corridors as [(convex polygon [(x, y), ...], z)]
        (a room's whole box; a corridor's segments): e.g. for a live rail over a
        railway's channels (hlmap.track.live_rail)."""
        out = []
        for sp in spaces:
            if isinstance(sp, Room):
                (x0, y0, z), (x1, y1, _) = sp.mins, sp.maxs
                out.append(([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], z))
            else:
                out += [(seg["floor"], sp.z0) for seg in sp.segments]
        return out

    def all_air(self):
        return self.rooms + [o.room for o in self.openings] + self.extra_air

    def is_air(self, p, tol=0.0):
        """True if p is inside intended air (rooms, openings, extra air, corridors, caves),
        with `tol` units of slack."""
        if any(f.in_ground(p, tol) for f in self.features if hasattr(f, "in_ground")):
            return False              # inside terrain
        for r in self.all_air():
            if r.contains(p, tol):
                return True
        if any(c.contains(p, tol) for c in self.corridors):
            return True
        return any(f.contains(p, tol) for f in self.features if hasattr(f, "contains"))

    def checkpoints(self):
        """[(name, [standing-player origins])] that must be reachable: every room (centre
        and inset corners) and stretches of every cave."""
        out = []
        for r in self.rooms:
            (x0, y0, z), (x1, y1, _) = r.mins, r.maxs
            if "checkpoints" in r.meta and not r.meta["checkpoints"]:
                continue                               # only there to be looked at
            if r.meta.get("checkpoints"):
                pts = []
                for x, y in r.meta["checkpoints"]:
                    zs = [f.surface(x, y) for f in self.features if hasattr(f, "surface")]
                    top = max([z] + [s for s in zs if s is not None])
                    pts.append((x, y, top + 37))
                out.append((f"room {r.name}", pts))
                continue
            pts = [((x0 + x1) / 2, (y0 + y1) / 2)] + [(x, y) for x in (x0 + 40, x1 - 40) for y in (y0 + 40, y1 - 40)]
            cx, cy = pts[0]
            mid = (r.floor + r.ceiling) / 2
            for i, (x, y) in enumerate(pts):         # corners cut off: move toward the middle
                for _ in range(40):
                    if r.contains((x, y, mid), tol=-24):
                        break
                    x, y = x + (cx - x) * 0.1, y + (cy - y) * 0.1
                pts[i] = (x, y)
            out.append((f"room {r.name}", [(x, y, z + 37) for x, y in pts]))
        for c in self.corridors:
            if getattr(c, "must_reach", True):
                out.append((f"corridor {c.name}", [(x, y, c.z0 + 37) for x, y in c.checkpoints()]))
        for f in self.features:
            if hasattr(f, "checkpoints"):
                for k, p in enumerate(f.checkpoints()):
                    out.append((f"{f.name} stretch {k + 1}", [(p[0], p[1], p[2] + 37)]))
        return out

    def is_inside(self, p):
        if any(f.in_ground(p, -2) for f in self.features if hasattr(f, "in_ground")):
            return False
        return (any(r.contains(p) for r in self.all_air()) or any(c.contains(p) for c in self.corridors)
                # +2: things standing exactly on a tunnel floor count as inside
                or any(f.contains((p[0], p[1], p[2] + 2)) for f in self.features if hasattr(f, "contains")))

    def room_at(self, p):
        for r in self.rooms:
            if r.contains(p):
                return r
        return None

    def in_cut(self, p):
        """The room whose cut-off corner contains p (solid now), if any."""
        for r in self.rooms:
            if r.cuts and r.box.contains_point(p) and not r.contains(p):
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
        for c in self.corridors:
            for room, corners in zip(c.rooms, c.cap_corners()):
                for x, y in corners:
                    for z in (c.z0 + 1, c.z0 + c.height - 1):
                        if not room.contains((float(x), float(y), z)):
                            problems.append(f"corridor {c.name}: its end at ({float(x):.0f}, {float(y):.0f}) is not "
                                            f"inside room {room.name}; extend the path further in")
            for r in self.rooms:
                if r in c.rooms:
                    continue
                if any(r.convex().overlaps(seg["outer"]) for seg in c.segments):
                    problems.append(f"corridor {c.name} runs into room {r.name}")
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
        convex_airs = [seg["air"] for c in self.corridors for seg in c.segments]
        extra = []                    # solids that go through the exact convex pass
        for c in self.corridors:
            extra += c.shell_pieces()
        for r in self.rooms:          # cut-off corners become solid
            for (a, b), co in r.cuts:
                fill = Convex.box(r.mins, r.maxs).clipped(Plane((-a, -b, 0), -co, _line_points(a, b, co)))
                if fill.valid():
                    extra.append(fill.tidy())
        for b, specs in self.solids():
            if convex_airs and any(Convex.box(b.mins, b.maxs).overlaps(ca) for ca in convex_airs):
                extra.append(Convex.box(b.mins, b.maxs))      # a wall a corridor passes through
                continue
            fallback = next((s for s in specs.values() if s), ("NULL", 0, 0, 1))
            faces = []
            for n, name in SIDE_NAMES.items():
                p = b.maxs if sum(n) > 0 else b.mins
                tex, uo, vo, sc = specs[name] or fallback
                f = make_face(n, p, tex)
                f.u_offset, f.v_offset, f.u_scale, f.v_scale = uo, vo, sc, sc
                faces.append(f)
            brushes.append(Brush(faces, "level"))
        if extra:
            cutters = [r.convex() for r in self.rooms] + [Convex.box(r.mins, r.maxs) for r in
                                                           [o.room for o in self.openings] + self.extra_air]
            cutters += convex_airs
            for piece in carve_all(extra, cutters):
                brushes.append(self._convex_brush(piece))
        m.add_world(*brushes)
        m.add_world(*self.water_brushes())
        for f in self.features:
            f.emit(m)
        m.level = self
        return brushes

    def water_brushes(self):
        """Water filling the rooms that have it, and the openings between two of them
        (to the lower of their levels), as world brushes of a liquid ('!') texture."""
        out = []
        for r in self.rooms:
            if "water" in r.meta:
                level, tex = r.meta["water"]
                out.append(box(r.mins, (r.maxs[0], r.maxs[1], level), tex, comment=f"water {r.name}"))
        for op in self.openings:
            if "water" in op.a.meta and "water" in op.b.meta:
                level = min(op.a.meta["water"][0], op.b.meta["water"][0], op.maxs[2])
                if level > op.mins[2]:
                    out.append(box(op.mins, (op.maxs[0], op.maxs[1], level), op.a.meta["water"][1],
                                   comment=f"water {op.room.name}"))
        return out

    def _air_for(self, p):
        """The Room (or corridor pseudo-room) whose air contains p, for texturing."""
        for r in self.all_air():
            if r.contains(p):
                return r
        for c in self.corridors:
            if c.contains(p):
                return c.as_room
        return None

    def _convex_brush(self, piece):
        """A world brush from a convex piece, each face textured by the air it faces."""
        faces, specs = [], []
        for pl in piece.planes:
            poly = piece.face(pl)
            n = [float(c) for c in pl.n]
            ln = math.sqrt(sum(c * c for c in n))
            n = [c / ln for c in n]
            spec, side = None, "top" if n[2] > 0.7 else "bottom" if n[2] < -0.7 else "wall"
            if len(poly) >= 3:
                c = [sum(float(v[k]) for v in poly) / len(poly) for k in range(3)]
                probes = [c] + [[c[k] + (float(v[k]) - c[k]) * 0.8 for k in range(3)] for v in poly]
                for q in probes:
                    air = self._air_for([q[k] + n[k] * 0.5 for k in range(3)])
                    if air is not None:
                        spec = _face_spec(air, side)
                        break
            specs.append(spec)
            faces.append((pl, n, side))
        fallback = next((s for s in specs if s), ("NULL", 0, 0, 1))
        from .csg import face_points
        out = []
        for (pl, n, side), spec in zip(faces, specs):
            tex, uo, vo, sc = spec or fallback
            p0, p1, p2 = face_points(piece, pl)
            axis_aligned = sum(1 for c in n if abs(c) > 1e-9) == 1
            u, v = world_axes(tuple(n)) if side != "wall" or axis_aligned else face_axes(tuple(n))
            out.append(Face(p0, p1, p2, tex, u, v, uo, vo, 0.0, sc, sc))
        return Brush(out, "level (convex)")


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


# ---------------------------------------------------------------- corridors

def _line_points(a, b, c):
    """Two integer points on the line a*x + b*y = c (a, b, c integers), or rational ones."""
    from fractions import Fraction as F
    a, b, c = int(a), int(b), c
    g = math.gcd(a, b)
    if isinstance(c, int) or float(c).is_integer():
        c = int(c)
        if c % g == 0:
            x0, y0 = _egcd_point(a, b, c)
            return ((F(x0), F(y0)), (F(x0 + b // g * 8), F(y0 - a // g * 8)))
    if a:
        return ((F(c) / a, F(0)), (F(c - b * 8) / a, F(8)))
    return ((F(0), F(c) / b), (F(8), F(c - a * 8) / b))


def _egcd_point(a, b, c):
    """An integer solution of a*x + b*y = c (c divisible by gcd(a, b))."""
    def egcd(x, y):
        if y == 0:
            return (x, 1, 0)
        g, s, t = egcd(y, x % y)
        return (g, t, s - (x // y) * t)
    g, s, t = egcd(abs(a), abs(b))
    s *= 1 if a >= 0 else -1
    t *= 1 if b >= 0 else -1
    k = c // g
    return s * k, t * k


def _floor_area(cv, z):
    pts = [(float(p[0]), float(p[1])) for p in cv.vertices() if float(p[2]) == z]
    if len(pts) < 3:
        return 0.0
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
    return abs(sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
                   for i in range(len(pts)))) / 2


class Corridor:
    """A corridor along a polyline, built from convex prisms (see Level.corridor).
    Each segment's side lines are integer lines, so segments at 0/45/90 degrees meet
    at exact points; joints are mitred."""

    def __init__(self, name, path, width, height, z0, wall, material, rooms):
        self.name, self.path, self.width, self.height = name, [tuple(p) for p in path], width, height
        self.z0, self.wall, self.material, self.rooms = z0, wall, material, rooms
        if len(self.path) < 2:
            raise ValueError(f"corridor {name}: needs at least two points")
        lines = []
        for (x0, y0), (x1, y1) in zip(self.path, self.path[1:]):
            dx, dy = x1 - x0, y1 - y0
            g = math.gcd(int(dx), int(dy)) or 1
            dx, dy = dx // g, dy // g
            nl = (-dy, dx)                                  # left of the direction of travel
            k = math.hypot(dx, dy)
            h, w = round(width / 2 * k), round(wall * k)
            cl = nl[0] * x0 + nl[1] * y0 + h                # left side: nl.p = cl
            cr = -(nl[0] * x0 + nl[1] * y0) + h             # right side: -nl.p = cr
            lines.append({"d": (dx, dy), "nl": nl, "left": (nl, cl), "right": ((-nl[0], -nl[1]), cr),
                          "left_out": (nl, cl + w), "right_out": ((-nl[0], -nl[1]), cr + w),
                          "from": (x0, y0), "to": (x1, y1)})
        self.segments = []
        for i, ln in enumerate(lines):
            def corner(side, end):
                other = lines[i - 1] if end == "start" and i > 0 else lines[i + 1] if end == "end" and i + 1 < len(lines) else None
                if other is None:                           # a square end cap
                    p = ln["from"] if end == "start" else ln["to"]
                    cap = (ln["d"], ln["d"][0] * p[0] + ln["d"][1] * p[1])
                    return line_intersection(ln[side], cap)
                q = line_intersection(ln[side], other[side])
                if q is None:
                    raise ValueError(f"corridor {name}: segments {i} and {i + (1 if end == 'end' else -1)} "
                                     "are parallel; drop the middle point")
                return q
            L0, L1 = corner("left", "start"), corner("left", "end")
            R0, R1 = corner("right", "start"), corner("right", "end")
            LO0, LO1 = corner("left_out", "start"), corner("left_out", "end")
            RO0, RO1 = corner("right_out", "start"), corner("right_out", "end")
            z0, z1, t = self.z0, self.z0 + height, wall
            air_poly = [L0, L1, R1, R0]
            if _area2(air_poly) == 0 or not _convex_poly(air_poly):
                raise ValueError(f"corridor {name}: segment {i} is too short for its turns")
            seg = {
                "air": Convex.prism(air_poly, z0, z1).tidy(),
                "floor": [tuple(q) for q in air_poly],
                "pieces": [Convex.prism([LO0, LO1, L1, L0], z0, z1), Convex.prism([R0, R1, RO1, RO0], z0, z1),
                           Convex.prism([LO0, LO1, RO1, RO0], z0 - t, z0), Convex.prism([LO0, LO1, RO1, RO0], z1, z1 + t)],
                "outer": Convex.prism([LO0, LO1, RO1, RO0], z0 - t, z1 + t),
                "cut_left": ((-ln["nl"][0], -ln["nl"][1]), -(ln["left_out"][1])),
                "cut_right": ((ln["nl"][0], ln["nl"][1]), -(ln["right_out"][1])),
                "side_of": (lambda nl, c: (lambda p: nl[0] * p[0] + nl[1] * p[1] - c))(
                    ln["nl"], ln["nl"][0] * ln["from"][0] + ln["nl"][1] * ln["from"][1]),
                "line": ln,
            }
            self.segments.append(seg)
        lo = [min(float(v[k]) for sg in self.segments for v in sg["air"].vertices()) for k in range(3)]
        hi = [max(float(v[k]) for sg in self.segments for v in sg["air"].vertices()) for k in range(3)]
        self.as_room = Room(name, AABB(tuple(lo), tuple(hi)), material)
        self.as_room.contains = lambda p, tol=0.0: self.contains(p, tol)

    def contains(self, p, tol=0.0):
        return any(s["air"].contains(p, tol) for s in self.segments)

    def shell_pieces(self):
        return [p for s in self.segments for p in s["pieces"]]

    def cap_corners(self):
        """The corners of the two open ends (they must lie inside the rooms)."""
        a, b = self.segments[0]["air"], self.segments[-1]["air"]
        def near(cv, pt):
            vs = sorted({(v[0], v[1]) for v in cv.vertices()},
                        key=lambda v: (float(v[0]) - pt[0]) ** 2 + (float(v[1]) - pt[1]) ** 2)
            return vs[:2]
        return near(a, self.path[0]), near(b, self.path[-1])

    def length(self):
        return sum(math.dist(a, b) for a, b in zip(self.path, self.path[1:]))

    def frame(self, s):
        """(floor point, direction of travel, left) at fraction s along the centreline."""
        d = s * self.length()
        for a, b in zip(self.path, self.path[1:]):
            L = math.dist(a, b)
            if d <= L or b == self.path[-1]:
                t = min(1.0, d / L) if L else 0
                u = ((b[0] - a[0]) / L, (b[1] - a[1]) / L)
                return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, self.z0), u, (-u[1], u[0])
            d -= L

    def floor_point(self, s, lateral=0.0, above=0):
        """Floor point at fraction s along the corridor; lateral -1..1 across its width."""
        (x, y, z), _, left = self.frame(s)
        o = lateral * (self.width / 2 - 16)
        return (x + left[0] * o, y + left[1] * o, z + above)

    def checkpoints(self):
        return [self.floor_point(s)[:2] for s in (0.3, 0.5, 0.7)]


def _area2(poly):
    return sum(poly[i][0] * poly[(i + 1) % len(poly)][1] - poly[(i + 1) % len(poly)][0] * poly[i][1]
               for i in range(len(poly)))


def _convex_poly(poly):
    signs = set()
    n = len(poly)
    for i in range(n):
        a, b, c = poly[i], poly[(i + 1) % n], poly[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cr:
            signs.add(cr > 0)
    return len(signs) <= 1
