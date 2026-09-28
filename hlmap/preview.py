"""Orthographic cutaway previews of a Map (no compile needed).

  plan    - top view, geometry cut at height z (like an architect's floor plan):
            floors in their texture colour, cut walls dark, furniture/doors tinted,
            point entities as labelled markers, 64-unit grid.
  section - side view cut by a vertical plane, looking north ('y') or east ('x').
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .geometry import dot

VOID = (18, 18, 22)
GRID = (255, 255, 255)
CUT_WORLD = (58, 60, 68)
ENTITY_TINT = {
    "func_detail": (190, 140, 90),
    "func_door": (70, 140, 235),
    "func_door_rotating": (70, 140, 235),
    "func_wall": (170, 170, 200),
    "func_breakable": (220, 120, 60),
    "func_button": (240, 60, 60),
    "func_illusionary": (150, 200, 150),
    "func_water": (60, 120, 220),
}
TRIGGER = (230, 90, 230)
QUIET = {"multisource", "trigger_relay", "trigger_auto", "info_target", "env_global"}
POINT_COLORS = {
    "info_player_start": (80, 230, 80),
    "info_player_deathmatch": (80, 230, 80),
    "light": (255, 220, 60),
    "light_spot": (255, 220, 60),
    "light_environment": (255, 180, 60),
}


TOOL_TEXTURES = {"ORIGIN", "CLIP", "NULL", "SKIP", "HINT", "AAATRIGGER", "BEVEL", "BEVELHINT",
                 "SOLIDHINT", "SPLITFACE"}


@lru_cache(maxsize=None)
def tex_color(name):
    """Average colour of a texture (for flat-shaded previews)."""
    if name.upper() in TOOL_TEXTURES:
        return (255, 140, 0)
    try:
        from .wad import default_db
        im = default_db().get(name).image().convert("RGB").resize((1, 1), Image.BILINEAR)
        return im.getpixel((0, 0))
    except Exception:
        return (255, 0, 255)


def _font(size):
    for name in ("consola.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def _shade(c, k):
    return tuple(max(0, min(255, int(v * k))) for v in c)


def _mix(a, b, t):
    return tuple(int(a[i] * (1 - t) + b[i] * t) for i in range(3))


def _hull2d(pts):
    pts = sorted(set((round(p[0], 3), round(p[1], 3)) for p in pts))
    if len(pts) <= 2:
        return pts

    def half(points):
        h = []
        for p in points:
            while len(h) >= 2 and ((h[-1][0] - h[-2][0]) * (p[1] - h[-2][1]) -
                                   (h[-1][1] - h[-2][1]) * (p[0] - h[-2][0])) <= 0:
                h.pop()
            h.append(p)
        return h
    lower, upper = half(pts), half(reversed(pts))
    return lower[:-1] + upper[:-1]


# view definitions: map point -> (u, v) screen axes (v up) and depth (larger = farther)
VIEWS = {
    "top": dict(uv=lambda p: (p[0], p[1]), depth=lambda p: -p[2], facing=(0, 0, 1)),
    "y": dict(uv=lambda p: (p[0], p[2]), depth=lambda p: p[1], facing=(0, -1, 0)),   # look north
    "x": dict(uv=lambda p: (-p[1], p[2]), depth=lambda p: p[0], facing=(-1, 0, 0)),  # look east
}


def render(m, path, view="top", cut=None, px_per_unit=None, max_px=1400, title=None,
           pointfile=None, show_entities=True):
    """Render a cutaway. view: 'top' (cut = z height), 'y' (cut = y plane, looking north),
    'x' (cut = x plane, looking east). Returns the image path."""
    V = VIEWS[view]
    uv, depth, facing = V["uv"], V["depth"], V["facing"]
    level = getattr(m, "level", None)
    if cut is None:
        if view == "top":
            base = level.rooms[0].floor if level and level.rooms else 0
            cut = base + 48
        else:
            axis = 1 if view == "y" else 0
            if level and level.rooms:
                r = level.rooms[0]
                cut = (r.mins[axis] + r.maxs[axis]) / 2
            else:
                cut = 0
    cut_depth = -cut if view == "top" else cut

    items = []  # (entity, brush, verts)
    for e in m.all_entities():
        for b in e.brushes:
            vs = b.vertices()
            if vs:
                items.append((e, b, vs))
    if not items:
        raise ValueError("map has no brushes")

    all_uv = [uv(p) for _, _, vs in items for p in vs]
    umin = min(p[0] for p in all_uv); umax = max(p[0] for p in all_uv)
    vmin = min(p[1] for p in all_uv); vmax = max(p[1] for p in all_uv)
    span = max(umax - umin, vmax - vmin, 1)
    s = px_per_unit or min(max_px / span, 4.0)
    pad_l, pad_t, pad_r, pad_b = 60, 56, 30, 40
    W = int((umax - umin) * s) + pad_l + pad_r
    H = int((vmax - vmin) * s) + pad_t + pad_b

    def P(p2):
        return (pad_l + (p2[0] - umin) * s, pad_t + (vmax - p2[1]) * s)

    img = Image.new("RGB", (W, H), VOID)
    d = ImageDraw.Draw(img, "RGBA")
    f_small, f_med = _font(11), _font(14)

    beyond, cutting = [], []
    for e, b, vs in items:
        ds = [depth(p) for p in vs]
        dmin, dmax = min(ds), max(ds)
        if dmin >= cut_depth - 1e-6:
            beyond.append((dmin, e, b, vs))
        elif dmax > cut_depth + 1e-6:
            cutting.append((e, b, vs))
        # else: in front of the cut plane (removed, e.g. ceilings in plan view)

    # far to near: nearest surfaces drawn last
    for dmin, e, b, vs in sorted(beyond, key=lambda x: -x[0]):
        # colour by the most viewer-facing face that is actually drawn (skip NULL etc.)
        shown = [f for f in b.faces if f.texture.upper() not in TOOL_TEXTURES] or b.faces
        f = max(shown, key=lambda f: dot(f.normal, facing))
        col = tex_color(f.texture) if f.texture.upper() not in TOOL_TEXTURES else (70, 70, 78)
        k = 1.1 - 0.5 * min(1.0, (dmin - cut_depth) / 384)
        col = _shade(col, k)
        tint = ENTITY_TINT.get(e.classname)
        if tint:
            col = _mix(col, tint, 0.35)
        if e.classname.startswith("trigger_"):
            continue
        poly = [P(p) for p in _hull2d([uv(p) for p in vs])]
        if len(poly) >= 3:
            outline = _shade(col, 0.6) if e.classname == "worldspawn" else _shade(tint or col, 1.15)
            d.polygon(poly, fill=col, outline=outline)

    for e, b, vs in cutting:
        poly = [P(p) for p in _hull2d([uv(p) for p in vs])]
        if len(poly) < 3:
            continue
        if all(f.texture.upper() == "ORIGIN" for f in b.faces):
            c = P(uv(tuple(sum(x) / len(vs) for x in zip(*vs))))
            d.ellipse([c[0] - 4, c[1] - 4, c[0] + 4, c[1] + 4], fill=(255, 140, 0))
            continue
        if e.classname.startswith("trigger_"):
            d.polygon(poly, fill=TRIGGER + (50,), outline=TRIGGER)
            continue
        tint = ENTITY_TINT.get(e.classname)
        if tint:
            d.polygon(poly, fill=_shade(tint, 0.75), outline=_shade(tint, 1.2))
        else:
            d.polygon(poly, fill=CUT_WORLD, outline=(95, 98, 110))

    # grid + axis labels
    step = 64
    while step * s < 12:
        step *= 2
    major = step * 4
    g0 = math.floor(umin / step) * step
    for gu in range(int(g0), int(umax) + step, step):
        x = P((gu, 0))[0]
        if pad_l <= x <= W - pad_r:
            a = 60 if gu % major == 0 else 22
            d.line([(x, pad_t), (x, H - pad_b)], fill=GRID + (a,))
            if gu % major == 0:
                label = str(-gu if view == "x" else gu)
                d.text((x + 2, H - pad_b + 4), label, fill=(170, 170, 180), font=f_small)
    g0 = math.floor(vmin / step) * step
    for gv in range(int(g0), int(vmax) + step, step):
        y = P((0, gv))[1]
        if pad_t <= y <= H - pad_b:
            a = 60 if gv % major == 0 else 22
            d.line([(pad_l, y), (W - pad_r, y)], fill=GRID + (a,))
            if gv % major == 0:
                d.text((4, y - 7), str(gv), fill=(170, 170, 180), font=f_small)

    # room labels
    if level and view == "top":
        for r in level.rooms:
            if r.floor <= cut <= r.ceiling and "#" not in r.name:
                c = P((r.mins[0], r.maxs[1]))
                sz = r.size
                d.text((c[0] + 6, c[1] + 5), f"{r.name}  {sz[0]:g}x{sz[1]:g}x{sz[2]:g}",
                       fill=(255, 255, 255, 190), font=f_med)

    # point entities
    if show_entities:
        labelled = set()
        for e in m.entities:
            if e.brushes or e.origin is None or e.classname == "info_texlights":
                continue
            o = e.origin
            if view == "top" and not (cut - 160 <= o[2] <= cut + 160):
                continue   # other floors
            c = P(uv(o))
            col = POINT_COLORS.get(e.classname, (240, 240, 240))
            if e.classname in QUIET:
                d.ellipse([c[0] - 2, c[1] - 2, c[0] + 2, c[1] + 2], fill=(150, 150, 160))
                continue
            r = 5
            d.ellipse([c[0] - r, c[1] - r, c[0] + r, c[1] + r], fill=col, outline=(0, 0, 0))
            ang = e.get("angles")
            if ang is not None and view == "top":
                yaw = float(str(ang).split()[1]) if isinstance(ang, str) else float(ang[1])
                ex = c[0] + math.cos(math.radians(yaw)) * 22
                ey = c[1] - math.sin(math.radians(yaw)) * 22
                d.line([c, (ex, ey)], fill=col, width=2)
            name = e.classname.replace("info_player_", "player_")
            if e.get("targetname"):
                name += f" '{e['targetname']}'"
            key = (round(c[0] / 40), round(c[1] / 12), name)
            if key not in labelled:
                labelled.add(key)
                d.text((c[0] + 8, c[1] + 4), name, fill=col, font=f_small)

    # leak line
    if pointfile and Path(pointfile).exists():
        pts = []
        for line in Path(pointfile).read_text().splitlines():
            # .pts: "x y z" per line; .lin: "x y z - x y z" segments
            nums = [float(x) for x in line.replace(" - ", " ").split()]
            for k in range(0, len(nums) - 2, 3):
                q = P(uv(tuple(nums[k:k + 3])))
                if not pts or pts[-1] != q:
                    pts.append(q)
        if len(pts) >= 2:
            d.line(pts, fill=(255, 30, 30), width=3)
            d.text(pts[0], "LEAK", fill=(255, 60, 60), font=f_med)

    what = {"top": f"plan, cut at z={cut:g}", "y": f"section at y={cut:g}, looking north",
            "x": f"section at x={cut:g}, looking east"}[view]
    d.text((pad_l, 8), f"{title or m.name} - {what}", fill=(235, 235, 240), font=f_med)
    d.text((pad_l, 28), f"grid {step} (major {major}) units   {s:.2f} px/unit   "
                        f"{len(items)} brushes, {len(m.entities)} entities",
           fill=(150, 150, 160), font=f_small)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path
