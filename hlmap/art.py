"""Make textures from non-standard sources: pixel-art SVGs, text, simple slides."""
from __future__ import annotations

import re

from PIL import Image, ImageDraw, ImageFont


def _subpaths(d):
    """Polygons of an SVG path that uses only M/L/H/V (absolute or relative) and z."""
    toks = re.findall(r"[MmLlHhVvZz]|-?\d*\.?\d+(?:e-?\d+)?", d)
    polys, cur, x, y, cmd, i = [], [], 0.0, 0.0, None, 0
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t
            i += 1
            if cmd in "Zz":
                if cur:
                    polys.append(cur)
                cur = []
                continue
            continue
        if cmd in "Mm":
            nx, ny = float(toks[i]), float(toks[i + 1])
            x, y = (x + nx, y + ny) if cmd == "m" else (nx, ny)
            i += 2
            if cur:
                polys.append(cur)
            cur = [(x, y)]
            cmd = "l" if cmd == "m" else "L"
            continue
        if cmd in "Ll":
            nx, ny = float(toks[i]), float(toks[i + 1])
            x, y = (x + nx, y + ny) if cmd == "l" else (nx, ny)
            i += 2
        else:
            v = float(toks[i])
            i += 1
            if cmd == "H":
                x = v
            elif cmd == "h":
                x += v
            elif cmd == "V":
                y = v
            elif cmd == "v":
                y += v
            else:
                raise ValueError(f"unsupported SVG path command {cmd!r}")
        cur.append((x, y))
    if cur:
        polys.append(cur)
    return polys


def _winding(px, py, polys):
    w = 0
    for poly in polys:
        for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
            if y1 <= py < y2 and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                w += 1
            elif y2 <= py < y1 and px < x1 + (py - y1) * (x2 - x1) / (y2 - y1):
                w -= 1
    return w


def pixel_svg(path, pixel=None):
    """Rasterize a pixel-art SVG (straight-edged paths on a regular grid) exactly: one
    output pixel per art pixel, transparent background, each path in its fill colour.
    `pixel` = grid size in SVG units (guessed from the view box if omitted)."""
    s = open(path, encoding="utf-8").read()
    vb = [float(v) for v in re.search(r'viewBox="([^"]+)"', s).group(1).replace(",", " ").split()]
    styles = dict(re.findall(r"\.(\w+)\{fill:(#[0-9A-Fa-f]{6});?\}", s))
    paths = re.findall(r'<path([^>]*)\sd="([^"]*)"', s)
    polys_all = []
    for attrs, d in paths:
        cls = re.search(r'class="(\w+)"', attrs)
        fill = re.search(r'fill="(#[0-9A-Fa-f]{6})"', attrs)
        colour = fill.group(1) if fill else styles.get(cls.group(1) if cls else "", "#FFFFFF")
        polys_all.append((_subpaths(d), tuple(int(colour[k:k + 2], 16) for k in (1, 3, 5))))
    if pixel is None:   # most common edge length ~ the art's grid (robust to rounding drift)
        from collections import Counter
        steps = Counter(round(abs(b[k] - a[k]), 1) for polys, _ in polys_all for poly in polys
                        for a, b in zip(poly, poly[1:]) for k in (0, 1) if abs(b[k] - a[k]) > 0.5)
        pixel = steps.most_common(1)[0][0]
        pixel = vb[2] / round(vb[2] / pixel)
    cols, rows = round(vb[2] / pixel), round(vb[3] / pixel)
    img = Image.new("RGBA", (cols, rows), (0, 0, 0, 0))
    for r in range(rows):
        for c in range(cols):
            px, py = vb[0] + (c + 0.5) * pixel, vb[1] + (r + 0.5) * pixel
            for polys, colour in polys_all:
                if _winding(px, py, polys):
                    img.putpixel((c, r), colour + (255,))
    return img


def font(size, bold=True):
    for name in (("arialbd.ttf", "consolab.ttf") if bold else ("arial.ttf", "consola.ttf")) + ("DejaVuSans-Bold.ttf",):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def slide(size, background, art=None, art_box=None, texts=()):
    """Compose a slide: background colour, pixel art scaled with hard edges into
    art_box (x0, y0, x1, y1), and texts [(text, (x, y), size, colour, anchor)]."""
    img = Image.new("RGB", size, background)
    if art is not None:
        x0, y0, x1, y1 = art_box
        k = min((x1 - x0) // art.width, (y1 - y0) // art.height) or 1
        a = art.resize((art.width * k, art.height * k), Image.NEAREST)
        img.paste(a, (x0 + (x1 - x0 - a.width) // 2, y0 + (y1 - y0 - a.height) // 2), a)
    d = ImageDraw.Draw(img)
    for text, pos, sz, colour, anchor in texts:
        d.text(pos, text, fill=colour, font=font(sz), anchor=anchor)
    return img
