"""Ready-made furniture, doors, lights and common point entities.

Furniture is returned as a func_detail entity (merged into the world by the
compiler, but doesn't cut up visibility). Coordinates are absolute map units.
"""
from __future__ import annotations

import math

from .geometry import box
from .mapfile import Entity

YAW = {"east": 0, "north": 90, "west": 180, "south": 270}
DIRS = {"east": (1, 0), "north": (0, 1), "west": (-1, 0), "south": (0, -1)}


def detail(*brushes, **kv):
    """Wrap brushes in a func_detail (no vis splits, still solid and lit)."""
    return Entity("func_detail", brushes=list(brushes), kv={"zhlt_detaillevel": "1", **kv})


# ---------------------------------------------------------------- furniture

def table(x, y, z, width=96, depth=48, height=34, top="FIFTIES_DR1", legs="FIFTIES_DSK1",
          top_thickness=3, leg=4):
    """Table centered at (x, y) standing on floor height z. width along X, depth along Y."""
    x0, x1 = x - width / 2, x + width / 2
    y0, y1 = y - depth / 2, y + depth / 2
    zt = z + height
    brushes = [box((x0, y0, zt - top_thickness), (x1, y1, zt), top, comment="table top")]
    inset = 4
    for lx in (x0 + inset, x1 - inset - leg):
        for ly in (y0 + inset, y1 - inset - leg):
            brushes.append(box((lx, ly, z), (lx + leg, ly + leg, zt - top_thickness), legs,
                               comment="table leg"))
    return detail(*brushes)


def chair(x, y, z, facing="north", seat="FIFTIES_DR6A", frame="FIFTIES_DSK1",
          size=24, seat_height=18, back_height=44, leg=3):
    """Chair centered at (x, y) on floor z; a person sitting in it looks toward `facing`."""
    fx, fy = DIRS[facing]
    h = size / 2
    x0, x1, y0, y1 = x - h, x + h, y - h, y + h
    seat_z0, seat_z1 = z + seat_height - 3, z + seat_height
    brushes = [box((x0, y0, seat_z0), (x1, y1, seat_z1), {"top": seat, "default": frame},
                   comment="chair seat")]
    for lx in (x0 + 1, x1 - 1 - leg):
        for ly in (y0 + 1, y1 - 1 - leg):
            brushes.append(box((lx, ly, z), (lx + leg, ly + leg, seat_z0), frame, comment="chair leg"))
    t = 3  # backrest thickness, on the side opposite to `facing`
    if fx:
        bx0, bx1 = (x0, x0 + t) if fx > 0 else (x1 - t, x1)
        back = box((bx0, y0, seat_z1), (bx1, y1, z + back_height), frame, comment="chair back")
        back.set_texture(seat, {"east" if fx > 0 else "west"})
    else:
        by0, by1 = (y0, y0 + t) if fy > 0 else (y1 - t, y1)
        back = box((x0, by0, seat_z1), (x1, by1, z + back_height), frame, comment="chair back")
        back.set_texture(seat, {"north" if fy > 0 else "south"})
    brushes.append(back)
    return detail(*brushes)


# ---------------------------------------------------------------- doors

def door_rotating(opening, hinge="left", texture="FIFTIES_DR6A2", edge="FIFTIES_DR6B",
                  thickness=8, speed=120, wait=4, distance=90, movesnd=9, stopsnd=4,
                  targetname=None, use_only=False, swing_into=None):
    """Hinged door filling a Level doorway.

    hinge:  'left' or 'right' as seen from room a (the first room given to doorway()).
    swing_into: None = opens away from the player; or a Room (opening.a / opening.b)
            to always swing into that room.
    wait:   seconds before closing again (-1 = stay open).
    Sounds: movesnd 0-10 (9/10 squeaky, 1 servo), stopsnd 0-8 (4 chunk, 1 clang).
    """
    axis = opening.axis
    other = 1 - axis
    mins, maxs = list(opening.mins), list(opening.maxs)
    mid = (mins[axis] + maxs[axis]) / 2
    leaf_min, leaf_max = list(mins), list(maxs)
    leaf_min[axis], leaf_max[axis] = mid - thickness / 2, mid + thickness / 2

    # direction pointing from a into b, and "right" as seen from a looking into b
    d = opening.direction
    right = (d[1], -d[0], 0)
    hinge_on_high = (right[other] < 0) if hinge == "left" else (right[other] > 0)
    hinge_coord = maxs[other] if hinge_on_high else mins[other]
    latch_coord = mins[other] if hinge_on_high else maxs[other]
    u = [0, 0, 0]
    u[other] = 1 if latch_coord > hinge_coord else -1   # texture runs hinge -> latch

    leaf = box(tuple(leaf_min), tuple(leaf_max), edge, comment="door leaf")
    faces_names = ("west", "east") if axis == 0 else ("south", "north")
    for side in faces_names:
        leaf.fit(side, texture, u_axis=tuple(u), v_axis=(0, 0, -1))
    # hinge axis runs through the middle of the leaf's hinge edge
    o = [0, 0, 0]
    o[axis] = mid
    o[other] = hinge_coord + (thickness / 2 if latch_coord > hinge_coord else -thickness / 2)
    o[2] = (mins[2] + maxs[2]) / 2
    origin = box(tuple(c - 4 for c in o), tuple(c + 4 for c in o), "ORIGIN", comment="door hinge")

    flags = 0
    if use_only:
        flags |= 256
    if swing_into is not None:
        flags |= 16  # one-way
        into = opening.direction if swing_into is opening.b else tuple(-c for c in opening.direction)
        # opening = +yaw (counter-clockwise from above). Rotate hinge->latch by +90:
        lu = (u[0], u[1])
        ccw = (-lu[1], lu[0])
        if ccw[0] * into[0] + ccw[1] * into[1] < 0:
            flags |= 2  # reverse direction
    kv = {"speed": speed, "wait": wait, "distance": distance, "movesnd": movesnd,
          "stopsnd": stopsnd, "spawnflags": flags}
    if targetname:
        kv["targetname"] = targetname
    return Entity("func_door_rotating", brushes=[leaf, origin], kv=kv)


def door_sliding(opening, texture="LAB1_DOOR2A", edge="LAB1_DOOR2B", thickness=8, direction="up",
                 speed=100, wait=4, lip=4, movesnd=1, stopsnd=1, targetname=None):
    """Sliding func_door filling a doorway. direction: 'up', 'down', or a compass side."""
    axis = opening.axis
    mins, maxs = list(opening.mins), list(opening.maxs)
    mid = (mins[axis] + maxs[axis]) / 2
    mins[axis], maxs[axis] = mid - thickness / 2, mid + thickness / 2
    leaf = box(tuple(mins), tuple(maxs), edge, comment="sliding door")
    for side in (("west", "east") if axis == 0 else ("south", "north")):
        leaf.fit(side, texture)
    kv = {"speed": speed, "wait": wait, "lip": lip, "movesnd": movesnd, "stopsnd": stopsnd}
    if direction == "up":
        kv["angle"] = -1
    elif direction == "down":
        kv["angle"] = -2
    else:
        kv["angles"] = f"0 {YAW[direction]} 0"
    if targetname:
        kv["targetname"] = targetname
    return Entity("func_door", brushes=[leaf], kv=kv)


# ---------------------------------------------------------------- lights

def ceiling_light(x, y, ceiling_z, width=64, depth=80, texture="+0~FIFTS_LGHT01",
                  trim="FIFTIES_DSK5B", drop=2):
    """Flush fluorescent panel on the ceiling centered at (x, y), emitting via its texture.
    Remember to register the texture: m.texlight(texture, (255, 250, 235), 4000)."""
    b = box((x - width / 2, y - depth / 2, ceiling_z - drop), (x + width / 2, y + depth / 2, ceiling_z),
            trim, comment="ceiling light")
    b.fit("bottom", texture)
    return detail(b)


def light(pos, color=(255, 240, 220), brightness=200, style=None, targetname=None, fade=None):
    """Point light. brightness ~150-300 for a room."""
    kv = {"origin": pos, "_light": f"{color[0]} {color[1]} {color[2]} {brightness}"}
    if style is not None:
        kv["style"] = style
    if targetname:
        kv["targetname"] = targetname
    if fade is not None:
        kv["_fade"] = fade
    return Entity("light", kv=kv)


def player_start(pos, facing=0):
    """info_player_start. pos = FLOOR point under the player; facing = yaw or compass name."""
    yaw = YAW.get(facing, facing)
    return Entity("info_player_start", kv={"origin": (pos[0], pos[1], pos[2] + 36), "angles": f"0 {yaw} 0"})


def yaw_towards(src, dst):
    return round(math.degrees(math.atan2(dst[1] - src[1], dst[0] - src[0]))) % 360
