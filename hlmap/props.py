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


def compass(dx, dy):
    """Nearest compass name ('east', 'north', ...) to a 2D direction."""
    if abs(dx) >= abs(dy):
        return "east" if dx >= 0 else "west"
    return "north" if dy >= 0 else "south"


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
                  targetname=None, use_only=False, swing_into=None, master=None,
                  locked_sound=12, unlocked_sound=13, opaque=True, **kv):
    """Hinged door filling a Level doorway.

    hinge:  'left' or 'right' as seen from room a (the first room given to doorway()).
    swing_into: None = opens away from the player; or a Room (opening.a / opening.b)
            to always swing into that room.
    wait:   seconds before closing again (-1 = stay open).
    master: name of a lock (see lock()); while locked the door won't open and plays
            `locked_sound` (12 = latch rattle). Extra **kv are passed through.
    opaque: block light while compiling (zhlt_lightflags 2) so lit rooms don't bleed
            through closed doors; the baked shadow stays when the door opens.
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
          "stopsnd": stopsnd, "spawnflags": flags, **kv}
    if targetname:
        kv["targetname"] = targetname
    if master:
        kv.update(master=master, locked_sound=locked_sound, unlocked_sound=unlocked_sound)
    if opaque:
        kv.setdefault("zhlt_lightflags", 2)
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
                  trim="FIFTIES_DSK5B", drop=2, name=None, angle=0):
    """Flush fluorescent panel on the ceiling centered at (x, y), emitting via its texture.
    Remember to register the texture: m.texlight(texture, (255, 250, 235), 4000).

    name: make it switchable. Returns [func_wall panel, named light]; firing `name`
    (e.g. from switch()) toggles the light style AND flips the panel to its +A (off)
    texture frame. Panels sharing a name switch together. Use a '+0' texture."""
    if angle:     # turned (degrees; the panel's depth runs along `angle`), e.g. for a diagonal corridor
        from .geometry import prism
        t = math.radians(angle)
        v = (math.cos(t), math.sin(t))                 # along the depth
        u = (v[1], -v[0])                              # across (the width)
        pts = [(round(x + u[0] * a + v[0] * c, 1), round(y + u[1] * a + v[1] * c, 1))
               for a, c in ((-width / 2, -depth / 2), (width / 2, -depth / 2), (width / 2, depth / 2), (-width / 2, depth / 2))]
        b = prism(pts, ceiling_z - drop, ceiling_z, trim, comment="ceiling light")
        b.fit("bottom", texture, u_axis=(u[0], u[1], 0), v_axis=(-v[0], -v[1], 0))
    else:
        b = box((x - width / 2, y - depth / 2, ceiling_z - drop), (x + width / 2, y + depth / 2, ceiling_z),
                trim, comment="ceiling light")
        b.fit("bottom", texture)
    if not name:
        return detail(b)
    # style -3 = "piggyback texlight": the compiler gives this entity's texture light the
    # switchable style of the real light with the same targetname (sdHLCSG qcsg.cpp).
    # Only that light entity can toggle the style in-game, hence the anchor light below.
    panel = Entity("func_wall", brushes=[b], targetname=name, style=-3)
    anchor = light((x, y, ceiling_z - drop - 8), brightness=25, targetname=name)
    return [panel, anchor]


def light(pos, color=(255, 240, 220), brightness=200, style=None, targetname=None, fade=None, **extra):
    """Point light. brightness ~150-300 for a room. A named light is switchable (the
    compiler gives each name its own light style); extras: spawnflags=1 (starts dark),
    pattern="mmnmmo..." (its look while on, 'a' dark .. 'm' normal .. 'z' double)."""
    kv = {"origin": pos, "_light": f"{color[0]} {color[1]} {color[2]} {brightness}", **extra}
    if style is not None:
        kv["style"] = style
    if targetname:
        kv["targetname"] = targetname
    if fade is not None:
        kv["_fade"] = fade
    return Entity("light", kv=kv)


def point(classname, pos, facing=None, **kv):
    """Any point entity at pos; facing = yaw degrees or compass name."""
    if facing is not None:
        kv["angles"] = f"0 {YAW.get(facing, facing)} 0"
    return Entity(classname, origin=tuple(pos), **kv)


# ---------------------------------------------------------------- logic

def lock(name, origin, globalstate=None):
    """A lock for doors and buttons: set their `master=name`. Locked until something fires
    f"{name}_key" (a button, trigger, keycard pickup...); the key works once, so firing
    it again can't relock (a multisource input toggles on every fire).
    globalstate: also require that global state (a logic.Flag's .state, e.g. power).
    Returns the two entities."""
    kv = {"globalstate": globalstate} if globalstate else {}
    return [Entity("multisource", targetname=name, origin=tuple(origin), **kv),
            Entity("trigger_relay", targetname=f"{name}_key", target=name, triggerstate=1,
                   spawnflags=1, origin=tuple(origin))]   # 1 = fire once


def switch(pos, facing, target, texture="C1A1_SWTCH1", size=(10, 15), depth=2, sound=14,
           toggle=False, master=None, wait=1, **kv):
    """Wall switch (func_button) centred on `pos`, a point ON the wall surface, sticking
    `depth` units out toward `facing` (the side the player stands on). Pressing (+use)
    fires `target` (toggle); sound 14 = light switch click. With `master` it only works
    while the master is on (it still clicks). Leave toggle=False with a master: a
    toggle-mode button skips the master check on every second press (HLSDK)."""
    fx, fy = DIRS[facing]
    w, h = size
    x, y, z = pos
    if fx:
        x0, x1 = (x, x + depth) if fx > 0 else (x - depth, x)
        b = box((x0, y - w / 2, z - h / 2), (x1, y + w / 2, z + h / 2), "FIFTIES_DSK5B", comment="switch")
    else:
        y0, y1 = (y, y + depth) if fy > 0 else (y - depth, y)
        b = box((x - w / 2, y0, z - h / 2), (x + w / 2, y1, z + h / 2), "FIFTIES_DSK5B", comment="switch")
    b.fit(facing, texture)
    kv = {"target": target, "sounds": sound, "wait": wait,
          "spawnflags": 1 | (32 if toggle else 0), **kv}   # 1 = don't move, 32 = toggle
    if master:
        kv["master"] = master
    return Entity("func_button", brushes=[b], kv=kv)


# ---------------------------------------------------------------- set dressing

def crate(x, y, z, size=48, texture="CRATE02", height=None):
    """Crate (func_detail) standing on z, centred on (x, y); one texture copy per face."""
    h = height or size
    b = box((x - size / 2, y - size / 2, z), (x + size / 2, y + size / 2, z + h), texture, comment="crate")
    for side in ("top", "bottom", "north", "south", "east", "west"):
        b.fit(side)
    return detail(b)


def crystal(base, height=96, radius=14, lean=(0, 0), sides=6, texture="CRYS_2A", seed=0):
    """Pointed crystal growing from `base` (floor point), leaning by (dx, dy) at the tip.
    Register the texture with m.texlight() to make it glow."""
    import random
    from .geometry import hull
    rnd = random.Random(seed)
    bx, by, bz = base
    pts = []
    for i in range(sides):
        a = 2 * math.pi * (i + rnd.uniform(-0.15, 0.15)) / sides
        r = radius * rnd.uniform(0.85, 1.1)
        pts.append((round(bx + r * math.cos(a)), round(by + r * math.sin(a)), round(bz - 8)))
        pts.append((round(bx + lean[0] * 0.7 + r * 0.8 * math.cos(a)),
                    round(by + lean[1] * 0.7 + r * 0.8 * math.sin(a)), round(bz + height * 0.7)))
    pts.append((round(bx + lean[0]), round(by + lean[1]), round(bz + height)))
    return detail(hull(pts, texture, comment="crystal"))


def xen_plantlight(pos, name, color=(255, 190, 90), brightness=140, facing=0):
    """Xen light stalk that retracts when the player gets close, switching off its light.
    Returns [plant, light]."""
    plant = point("xen_plantlight", pos, facing, target=name)
    glow = light((pos[0], pos[1], pos[2] + 56), color=color, brightness=brightness, targetname=name)
    return [plant, glow]


def player_start(pos, facing=0):
    """info_player_start. pos = FLOOR point under the player; facing = yaw or compass name."""
    yaw = YAW.get(facing, facing)
    return Entity("info_player_start", kv={"origin": (pos[0], pos[1], pos[2] + 36), "angles": f"0 {yaw} 0"})


def yaw_towards(src, dst):
    return round(math.degrees(math.atan2(dst[1] - src[1], dst[0] - src[0]))) % 360


# ---------------------------------------------------------------- structure helpers

def railing(start, end, z, height=40, texture="FIFTIES_DSK5B", post_every=64, thick=4, side=None):
    """Railing along an axis-aligned segment on floor height z: posts, a top rail and a
    mid rail (func_detail, solid). `side` ('north'...) shifts it off the line so it sits
    beside an edge instead of on it."""
    (x0, y0), (x1, y1) = start, end
    if x0 != x1 and y0 != y1:
        raise ValueError("railing segments must be axis-aligned")
    ox, oy = DIRS[side] if side else (0, 0)
    h = thick / 2
    sx, sy = ox * h, oy * h
    cx0, cx1 = sorted((x0, x1))
    cy0, cy1 = sorted((y0, y1))
    brushes = []
    length = max(cx1 - cx0, cy1 - cy0)
    posts = max(1, math.ceil(length / post_every))
    for i in range(posts + 1):
        t = i / posts
        px, py = x0 + (x1 - x0) * t + sx, y0 + (y1 - y0) * t + sy
        brushes.append(box((px - h, py - h, z), (px + h, py + h, z + height), texture, comment="railing post"))
    for rz in (z + height - thick, z + height / 2 - thick / 2):
        if cx0 != cx1:
            brushes.append(box((cx0, cy0 - h + sy, rz), (cx1, cy0 + h + sy, rz + thick), texture, comment="rail"))
        else:
            brushes.append(box((cx0 - h + sx, cy0, rz), (cx0 + h + sx, cy1, rz + thick), texture, comment="rail"))
    return detail(*brushes)


def ladder(base, top_z, facing, width=32, texture="{LADDER1", extra=32):
    """Climbable ladder on a vertical surface. base = (x, y, z): centre of its foot ON
    the surface; facing = direction the climber faces (toward the surface). The climbing
    volume reaches `extra` units above top_z so players can step off at the top.
    Returns [visible see-through ladder (func_illusionary), func_ladder volume]."""
    fx, fy = DIRS[facing]
    x, y, z = base
    w = width / 2
    if fx:   # surface is the plane x = const; the ladder sits in front of it
        vis = box((x - 4, y - w, z), (x, y + w, top_z), "FIFTIES_DSK5B") if fx > 0 else \
            box((x, y - w, z), (x + 4, y + w, top_z), "FIFTIES_DSK5B")
        vol = box((x - 12, y - w, z), (x, y + w, top_z + extra), "AAATRIGGER") if fx > 0 else \
            box((x, y - w, z), (x + 12, y + w, top_z + extra), "AAATRIGGER")
        side = "west" if fx > 0 else "east"
    else:
        vis = box((x - w, y - 4, z), (x + w, y, top_z), "FIFTIES_DSK5B") if fy > 0 else \
            box((x - w, y, z), (x + w, y + 4, top_z), "FIFTIES_DSK5B")
        vol = box((x - w, y - 12, z), (x + w, y, top_z + extra), "AAATRIGGER") if fy > 0 else \
            box((x - w, y, z), (x + w, y + 12, top_z + extra), "AAATRIGGER")
        side = "south" if fy > 0 else "north"
    from .wad import default_db
    th = default_db().size(texture)[1]
    vis.fit(side, texture, repeat=(1, max(1, round((top_z - z) / th))))
    visual = Entity("func_illusionary", brushes=[vis], rendermode=4, renderamt=255)   # see-through
    return [visual, Entity("func_ladder", brushes=[vol])]


# ---------------------------------------------------------------- more furniture

def front_box(x, y, z, w, d, h, facing, front, sides="FIFTIES_DSK5B", top=None, repeat=(1, 1)):
    """Box standing on z, centred on (x, y): `w` across its front, `d` deep; the front
    face points toward `facing` and gets `front` fitted (repeated)."""
    fx, fy = DIRS[facing]
    if fx:
        b = box((x - d / 2, y - w / 2, z), (x + d / 2, y + w / 2, z + h), sides)
    else:
        b = box((x - w / 2, y - d / 2, z), (x + w / 2, y + d / 2, z + h), sides)
    b.fit(facing, front, repeat=repeat)
    if top:
        b.fit("top", top)
    return b


def radio(x, y, z, facing, texture="C1A1_GGT8", w=24, h=24, d=16):
    """A table-top radio set (func_detail), dial panel toward `facing`."""
    return detail(front_box(x, y, z, w, d, h, facing, texture))


def filing_cabinet(x, y, z, facing, drawers=4, texture="FIFTSFILE1", w=24, d=28):
    return detail(front_box(x, y, z, w, d, 16 * drawers, facing, texture, sides="FIFTSFILE2",
                             top="FIFTSFILE2", repeat=(1, drawers)))


def bookshelf(x, y, z, facing, w=64, h=96, d=16, texture="PFAB_BKS1A"):
    """Shelf full of books (one row of books per 16 units)."""
    return detail(front_box(x, y, z, w, d, h, facing, texture, sides="FIFTIES_DSK1",
                             repeat=(max(1, round(w / 32)), max(1, round(h / 16)))))


def vending_machine(x, y, z, facing):
    return detail(front_box(x, y, z, 48, 32, 80, facing, "GEN_VEND1", sides="GEN_VEND1A"))


def wall_art(pos, facing, texture, w, h, depth=2, frame="FIFTIES_DSK5B"):
    """Flat picture, clock, sign, fuse box... on a wall: pos = centre ON the wall
    surface, facing = the direction it faces (into the room); `frame` = edge texture."""
    fx, fy = DIRS[facing]
    x, y, z = pos
    if fx:
        b = box((min(x, x + fx * depth), y - w / 2, z - h / 2), (max(x, x + fx * depth), y + w / 2, z + h / 2),
                frame)
    else:
        b = box((x - w / 2, min(y, y + fy * depth), z - h / 2), (x + w / 2, max(y, y + fy * depth), z + h / 2),
                frame)
    b.fit(facing, texture)
    return detail(b)


def barrel(x, y, z, texture="BARREL2", top="BARRELTOP", r=16, h=48):
    from .geometry import cylinder
    return detail(cylinder((x, y), r, z, z + h, sides=10, tex={"top": top, "bottom": top, "sides": texture}))


def pipe(start, end, size=8, texture="GENERIC029"):
    """Axis-aligned square pipe between two points (e.g. along a ceiling)."""
    lo = tuple(min(a, b) - (0 if a != b else size / 2) for a, b in zip(start, end))
    hi = tuple(max(a, b) + (0 if a != b else size / 2) for a, b in zip(start, end))
    return detail(box(lo, hi, texture, comment="pipe"))


# ---------------------------------------------------------------- projector & slides

def projector(lens, screen_lo, screen_hi, ceiling_z=None, body="FIFTIES_DSK5B", lens_tex="FLATBED_LITE1",
              beam_tex="+0~WHITE", beam_alpha=28, name=None):
    """Ceiling projector with its lens at `lens`, throwing a visible see-through light
    cone onto the vertical screen rectangle screen_lo..screen_hi.
    Returns [body (func_detail), beam (additive func_illusionary)]. With `name` the beam
    is named, so an env_render can hide it (renderamt 0) and bring it back."""
    from .geometry import hull
    lx, ly, lz = lens
    sc = tuple((a + b) / 2 for a, b in zip(screen_lo, screen_hi))
    dx, dy = sc[0] - lx, sc[1] - ly
    facing = ("east" if dx > 0 else "west") if abs(dx) > abs(dy) else ("north" if dy > 0 else "south")
    fx, fy = DIRS[facing]
    # 24 x 32 x 16 body behind the lens
    if fx:
        body_b = box((min(lx, lx - fx * 32), ly - 12, lz - 8), (max(lx, lx - fx * 32), ly + 12, lz + 8), body)
    else:
        body_b = box((lx - 12, min(ly, ly - fy * 32), lz - 8), (lx + 12, max(ly, ly - fy * 32), lz + 8), body)
    body_b.comment = "projector"
    body_b.fit(facing, lens_tex)
    parts = [body_b]
    if ceiling_z is not None:
        cx, cy = lx - fx * 16, ly - fy * 16
        parts.append(box((cx - 2, cy - 2, lz + 8), (cx + 2, cy + 2, ceiling_z), body, comment="projector rod"))
    x0, y0, z0 = screen_lo
    x1, y1, z1 = screen_hi
    if fy:
        yy = (y0 if fy > 0 else y1) - fy
        far = [(x0, yy, z0), (x1, yy, z0), (x1, yy, z1), (x0, yy, z1)]
    else:
        xx = (x0 if fx > 0 else x1) - fx
        far = [(xx, y0, z0), (xx, y1, z0), (xx, y1, z1), (xx, y0, z1)]
    near = []
    for a in (-3, 3):
        for c in (-3, 3):
            near.append((round(lx + fx * 2 + (a if fy else 0)), round(ly + fy * 2 + (a if fx else 0)), round(lz + c)))
    beam = hull(near + [tuple(round(v) for v in p) for p in far], beam_tex, comment="projector beam")
    kv = {"targetname": name} if name else {}
    return [detail(*parts), Entity("func_illusionary", brushes=[beam], rendermode=5, renderamt=beam_alpha, **kv)]


def screen(lo, hi, facing, slide_tex, name=None, frame="FIFTIES_DSK5B"):
    """Projection screen: thin panel lo..hi with `slide_tex` fitted on its front. With
    `name` it is a func_wall that toggles between its '+0' and '+A' slide when fired."""
    b = box(lo, hi, frame, comment="screen")
    b.fit(facing, slide_tex)
    if name:
        return Entity("func_wall", brushes=[b], targetname=name)
    return detail(b)


def pickup(classname, pos, fires=(), message=None, sound="buttons/bell1.wav", name=None, facing=0,
           hide=(), invisible=False):
    """An item (e.g. item_security = access card) that, when picked up, fires every
    targetname in `fires` (e.g. a lock's '<lock>_key'), shows `message`, plays `sound`
    and removes the entities named in `hide` (e.g. a visible prop standing in for the
    item). invisible=True hides the item's own model (use with a stand-in prop).
    Items drop onto the floor/table below `pos` when the map starts."""
    name = name or f"{classname}_{round(pos[0])}_{round(pos[1])}"
    kv = {"target": name}
    if invisible:
        kv.update(rendermode=2, renderamt=0)
    ents = [point(classname, pos, facing, **kv)]
    mm = {t: 0 for t in fires}
    for k, h in enumerate(hide):       # trigger_relay does killtarget; multi_manager can't
        ents.append(Entity("trigger_relay", targetname=f"{name}_hide{k}", killtarget=h, origin=tuple(pos)))
        mm[f"{name}_hide{k}"] = 0
    if message:
        ents.append(hud_message(f"{name}_msg", pos, message))
        mm[f"{name}_msg"] = 0
    if sound:
        ents.append(sound_effect(f"{name}_snd", pos, sound, everywhere=True))
        mm[f"{name}_snd"] = 0
    ents.append(Entity("multi_manager", targetname=name, origin=tuple(pos), kv=mm))
    return ents


def hud_message(name, pos, text, color=(255, 220, 0), y=0.72, channel=2, hold=3.5):
    """On-screen text shown to the player when `name` is fired (game_text; y 0 = top,
    1 = bottom; messages on different channels can show at once)."""
    return Entity("game_text", targetname=name, origin=tuple(pos), message=text, x=-1, y=y, effect=0,
                  color=color, color2="255 255 255", fadein=0.05, fadeout=0.6, holdtime=hold,
                  channel=channel, spawnflags=1)   # 1 = all players


def sound_effect(name, pos, wav, volume=10, everywhere=False, radius="medium"):
    """A sound played once each time `name` is fired (ambient_generic, not looping).
    wav is relative to valve/sound, e.g. 'buttons/spark1.wav'."""
    flags = 16 | 32 | (1 if everywhere else {"small": 2, "medium": 4, "large": 8}[radius])
    return Entity("ambient_generic", targetname=name, origin=tuple(pos), message=wav, health=volume,
                  pitch=100, spawnflags=flags)   # 16 = start silent, 32 = not looped


def flat_prop(pos, w, d, texture, name=None, thick=1, sides="FIFTIES_DSK5B"):
    """A thin flat object lying on a surface (paper, card, map): pos = centre of its
    underside. With `name` it is a func_wall that can be removed (killtarget) later."""
    x, y, z = pos
    b = box((x - w / 2, y - d / 2, z), (x + w / 2, y + d / 2, z + thick), sides, comment="flat prop")
    b.fit("top", texture)
    if name:
        return Entity("func_wall", brushes=[b], targetname=name)
    return detail(b)


# ---------------------------------------------------------------- emergency lights, levers

EMERGENCY_PULSE = "klmnopqrrqponmlk"     # slow pulse that never goes dark


def emergency_light(pos, facing, name="emergency", color=(255, 36, 20), brightness=90,
                    pattern=EMERGENCY_PULSE, lamp="+0~LIGHT6A", stand=None):
    """A battery emergency lamp, dark until `name` is fired (e.g. by a logic.Circuit
    power failure): then its light pulses and its lamp shows lit.
    pos: point ON the wall; the lamp sticks out toward `facing`. stand=floor_z instead
    puts the lamp on a pole standing on the floor under pos (e.g. in a cave).
    Returns [lamp func_wall (starts on its +A 'off' frame), light, (pole)]."""
    fx, fy = DIRS[facing]
    x, y, z = pos
    w, h, d = 16, 10, 8
    if stand is not None:                # centred on pos
        x, y = x - fx * d / 2, y - fy * d / 2
    if fx:
        b = box((min(x, x + fx * d), y - w / 2, z - h / 2), (max(x, x + fx * d), y + w / 2, z + h / 2),
                "FIFTIES_DSK5B", comment="emergency lamp")
    else:
        b = box((x - w / 2, min(y, y + fy * d), z - h / 2), (x + w / 2, max(y, y + fy * d), z + h / 2),
                "FIFTIES_DSK5B", comment="emergency lamp")
    b.fit(facing, lamp)
    b.fit("bottom", lamp)
    parts = [Entity("func_wall", brushes=[b], targetname=name, frame=1),
             light((x + fx * (d + 12), y + fy * (d + 12), z - 6), color, brightness, targetname=name,
                   spawnflags=1, pattern=pattern)]
    if stand is not None:
        cx, cy = x + fx * d / 2, y + fy * d / 2
        parts.append(detail(box((cx - 2, cy - 2, stand + 2), (cx + 2, cy + 2, z - h / 2), "FIFTIES_DSK5B", comment="pole"),
                            box((cx - 10, cy - 10, stand), (cx + 10, cy + 10, stand + 2), "FIFTIES_DSK5B", comment="foot")))
    return parts


def lever(pos, facing, target, master=None, texture="BRKHANDLE", size=(12, 16), depth=8, travel=16,
          sound=21, wait=2, **kv):
    """A handle that slides up when used and springs back after `wait` s (a func_button
    moving up; sound 21 = lever clunk). pos = centre of its base ON the wall; the
    handle sticks out toward `facing`. With `master` it only works while the master is
    on; locked, it stays put and just clunks."""
    fx, fy = DIRS[facing]
    w, h = size
    x, y, z = pos
    if fx:
        b = box((min(x, x + fx * depth), y - w / 2, z), (max(x, x + fx * depth), y + w / 2, z + h), texture)
    else:
        b = box((x - w / 2, min(y, y + fy * depth), z), (x + w / 2, max(y, y + fy * depth), z + h), texture)
    b.comment = "lever"
    kv = {"target": target, "sounds": sound, "wait": wait, "speed": 60, "lip": h - travel,
          "angles": "0 -1 0", "spawnflags": 0, **kv}      # angles 0 -1 0 = moves up
    if master:
        kv["master"] = master
    return Entity("func_button", brushes=[b], kv=kv)


# ---------------------------------------------------------------- signs & decals

def _texname(prefix, text, *salt):
    import hashlib
    import re
    clean = re.sub(r"[^A-Z0-9]", "", str(text).upper())[:15 - len(prefix) - 4]
    digest = hashlib.md5(repr((text,) + salt).encode()).hexdigest()[:4].upper()
    return f"{prefix}{clean}{digest}"


def sign(pos, facing, text=None, w=48, h=16, style="steel", image=None, texture=None, depth=1,
         frame="FIFTIES_DSK5B"):
    """A wall sign centred on `pos` (a point ON the wall), facing into the room.
    text: a nameplate drawn in one of Black Mesa's plate styles (art.plate: 'steel',
    'red', 'brass', 'warning', 'white'; '\n' for more lines), or image: any picture
    (poster, photo you may use). The generated texture travels with the entity and is
    embedded when the map is written; texture= names a stock or existing one instead."""
    from .art import plate
    from .mapfile import prepare_texture
    tex = texture
    textures = {}
    if tex is None:
        img = image if image is not None else plate(text, (w, h), style)
        tex = _texname("SG_", text if text else "IMG", style, w, h, id(image) if image is not None else 0)
        textures[tex] = prepare_texture(tex, img)
    ent = wall_art(pos, facing, tex, w, h, depth=depth, frame=frame)
    ent.textures = textures
    return ent


def decal(texture, pos, name=None):
    """A stock decal (decals.wad: '{SCORCH1', '{OIL1', '{CRACK2', '{ARROW_L', '{PSTRIPE4',
    ...) on the surface within a few units of `pos` (the engine traces +-5 units from
    it). With `name` it appears only when fired (e.g. a scorch mark after a blast)."""
    kv = {"texture": texture}
    if name:
        kv["targetname"] = name
    return point("infodecal", pos, **kv)


STENCIL = {**{chr(c): f"{{CAPS{chr(c)}" for c in range(65, 91)}, **{str(d): f"{{SMALL#S{d}" for d in range(10)}}


def stencil(text, pos, facing, size=16, gap=-3):
    """Stencilled lettering from stock decals only, 16 units tall, centred on `pos` on
    a wall facing `facing`; needs no custom texture. Letters ({CAPSA-Z) are yellow
    stencil paint; digits ({SMALL#S0-9, the only ones that size) come out black.
    The glyphs have blank margins, hence the negative gap."""
    fx, fy = DIRS[facing]
    rx, ry = -fy, fx                      # the viewer's right, looking at the wall
    chars = [c for c in text.upper()]
    widths = [size if c in STENCIL else size // 2 for c in chars]
    total = sum(widths) + gap * (len(chars) - 1)
    x, y, z = pos
    off = -total / 2
    out = []
    for c, wd in zip(chars, widths):
        mid = off + wd / 2
        if c in STENCIL:
            out.append(decal(STENCIL[c], (round(x + rx * mid + fx), round(y + ry * mid + fy), z)))
        off += wd + gap
    return out


# ---------------------------------------------------------------- slideshows & triggers

def slideshow(name, lo, hi, facing, textures, frame="FIFTIES_DSK5B"):
    """A screen (lo..hi, a thin box on a wall) that steps through any number of slides.
    Each slide is a func_wall_toggle plate on the screen's front (only the current one
    is shown). Fire f"{name}_next" to advance (wrapping round), or f"{name}_step{k}" to
    go from slide k to k+1. f"{name}_next" is a relay whose target a
    trigger_changetarget rewrites at every step, so it always knows the current slide.
    Returns the entities; slideshow_front(lo, hi, facing) is where the slides' faces are."""
    fx, fy = DIRS[facing]
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    ents = [detail(box(lo, hi, frame, comment="screen"))]
    n = len(textures)
    for k, tex in enumerate(textures, 1):
        if fy:
            y = y0 if fy < 0 else y1
            b = box((x0, min(y, y + fy), z0), (x1, max(y, y + fy), z1), frame, comment=f"slide {k}")
        else:
            x = x0 if fx < 0 else x1
            b = box((min(x, x + fx), y0, z0), (max(x, x + fx), y1, z1), frame, comment=f"slide {k}")
        b.fit(facing, tex)
        ents.append(Entity("func_wall_toggle", brushes=[b], targetname=f"{name}_{k}",
                           spawnflags=0 if k == 1 else 1))           # 1 = starts hidden
    o = tuple((a + b) / 2 for a, b in zip(lo, hi))
    ents.append(Entity("trigger_relay", targetname=f"{name}_next", target=f"{name}_step1", triggerstate=2, origin=o))
    for k in range(1, n + 1):
        nxt = k % n + 1
        ents.append(Entity("multi_manager", targetname=f"{name}_step{k}", origin=o,
                           kv={f"{name}_{k}": 0, f"{name}_{nxt}": 0, f"{name}_to{nxt}": 0}))
        ents.append(Entity("trigger_changetarget", targetname=f"{name}_to{nxt}", target=f"{name}_next",
                           m_iszNewTarget=f"{name}_step{nxt}", origin=o))
    return ents


def slideshow_front(lo, hi, facing):
    """(lo, hi) of the plane the slides show on: what a projector or a cover targets."""
    fx, fy = DIRS[facing]
    lo, hi = list(lo), list(hi)
    if fy:
        y = (lo[1] - 1) if fy < 0 else (hi[1] + 1)
        lo[1] = hi[1] = y
    else:
        x = (lo[0] - 1) if fx < 0 else (hi[0] + 1)
        lo[0] = hi[0] = x
    return tuple(lo), tuple(hi)


def trigger(mins, maxs, target, once=True, master=None, **kv):
    """An invisible volume that fires `target` when the player walks in (trigger_once,
    or trigger_multiple with once=False). With `master`, only while the master is on;
    a trigger_once that is locked stays armed."""
    kv = {"target": target, **kv}
    if master:
        kv["master"] = master
    return Entity("trigger_once" if once else "trigger_multiple",
                  brushes=[box(mins, maxs, "AAATRIGGER", comment="trigger")], kv=kv)

