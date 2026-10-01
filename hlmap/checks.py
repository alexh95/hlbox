"""Gameplay lint that needs the Level: things the compilers can't know are wrong."""
from __future__ import annotations

import math

# Half-Life's +use (CBasePlayer::PlayerUse) picks, among entities whose bounding box is
# within 64 units of the player's origin, the one most in front of the view (dot > 0.7).
# There is NO line-of-sight test: walls don't block it.
PLAYERUSE_RADIUS = 64
USABLE = {"func_button", "func_rot_button", "momentary_rot_button", "func_healthcharger", "func_recharge"}


def _bounds(e):
    los, his = zip(*(b.bounds() for b in e.brushes))
    return tuple(min(v[k] for v in los) for k in range(3)), tuple(max(v[k] for v in his) for k in range(3))


def _box_dist(alo, ahi, blo, bhi):
    return math.sqrt(sum(max(0.0, blo[k] - ahi[k], alo[k] - bhi[k]) ** 2 for k in range(3)))


def _name(e):
    return f"{e.classname} {e.get('target') or e.get('targetname') or ''}".strip()


def use_reach(m, level):
    """Problems with usable entities (buttons, switches, chargers):
    - usable from more than one room (through a wall), or
    - two of them close enough that one +use could pick either."""
    problems = []
    usable = [e for e in m.entities if e.brushes and (
        e.classname in USABLE or (e.classname.startswith("func_door") and int(e.get("spawnflags") or 0) & 256))]
    reach = {}
    for e in usable:
        lo, hi = _bounds(e)
        rooms = reach[id(e)] = []
        for r in level.rooms:
            # where a player's origin can be in that room: crouched on the floor up to
            # standing at the top of a jump (45)
            olo = (r.mins[0] + 16, r.mins[1] + 16, r.floor + 18)
            ohi = (r.maxs[0] - 16, r.maxs[1] - 16, min(r.ceiling - 18, r.floor + 36 + 45))
            if _box_dist(olo, ohi, lo, hi) <= PLAYERUSE_RADIUS:
                rooms.append(r.name)
        if len(rooms) > 1:
            problems.append(f"{_name(e)} at {tuple(round((a + b) / 2) for a, b in zip(lo, hi))} can be used "
                            f"from rooms {', '.join(rooms)}: +use ignores walls (64-unit reach), move it "
                            f"away from walls shared with other rooms")
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            d = _box_dist(*_bounds(a), *_bounds(b))
            if d < 2 * PLAYERUSE_RADIUS and set(reach[id(a)]) & set(reach[id(b)]):
                problems.append(f"{_name(a)} and {_name(b)} are {d:.0f} units apart: a player using one may "
                                f"trigger the other (keep usable things >= {2 * PLAYERUSE_RADIUS} apart)")
    return problems


def doorway_clearance(m, level, depth=64):
    """Doorways need open floor in front of them on both sides: no stair hole, railing,
    crate or other furniture within `depth` units of the opening (a player must be able
    to walk straight up to a door, not around obstacles). Windows (a sill) aren't walked
    through; solid beside the opening that reaches its wall (rock around a passage, a
    thicker jamb) only makes the doorway deeper."""
    problems = []
    blockers = []
    for r in level.extra_air:
        if r.name.endswith("-hole"):
            blockers.append((f"stair hole {r.name[:-5]}", r.box.mins, r.box.maxs))
    for e in m.entities:
        if e.classname == "func_detail":
            for b in e.brushes:
                lo, hi = b.bounds()
                blockers.append((b.comment or "furniture", lo, hi))
    for op in level.openings:
        if op.room.name.endswith("-mouth"):
            continue
        a = op.axis
        o = 1 - a
        (lo, hi) = op.mins, op.maxs
        if lo[2] > max(op.a.floor, op.b.floor) + 18:
            continue                      # a window
        for sign, room in ((-1, op.a), (+1, op.b)) if op.direction[a] > 0 else ((+1, op.a), (-1, op.b)):
            face = lo[a] if sign < 0 else hi[a]
            zmin, zmax = [0, 0, lo[2]], [0, 0, lo[2] + 72]
            zmin[a], zmax[a] = sorted((face, face + sign * depth))
            zmin[o], zmax[o] = lo[o] - 8, hi[o] + 8
            for name, blo, bhi in blockers:
                if bhi[2] <= lo[2] + 18 and not name.startswith("stair hole"):
                    continue              # a step up (sidewalk, low slab), not in the way
                if (bhi[o] <= lo[o] or blo[o] >= hi[o]) and blo[a] <= face + sign <= bhi[a]:
                    continue              # beside the opening, from its wall out: a jamb
                if all(blo[k] < zmax[k] and zmin[k] < bhi[k] for k in range(3)) and blo[2] < lo[2] + 8:
                    problems.append(f"{name} blocks the way to doorway {op.room.name} "
                                    f"(within {depth} units on the {room.name} side)")
    return sorted(set(problems))
