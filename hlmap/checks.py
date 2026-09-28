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
            # where a player's origin can be in that room (standing or crouched)
            olo = (r.mins[0] + 16, r.mins[1] + 16, r.floor + 18)
            ohi = (r.maxs[0] - 16, r.maxs[1] - 16, r.ceiling - 18)
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
