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


# Black Mesa sign plates: (plate top colour, plate bottom colour, text colour)
PLATES = {
    "steel": ((150, 158, 176), (112, 120, 140), (16, 26, 62)),     # the grey-blue CenCom plates
    "red": ((164, 26, 22), (118, 14, 12), (244, 238, 232)),        # D-AL / restricted
    "brass": ((190, 150, 70), (146, 108, 40), (44, 28, 10)),       # CAFETERIA / STORAGE
    "warning": ((246, 204, 24), (222, 178, 10), (18, 18, 18)),     # yellow caution
    "white": ((232, 234, 236), (206, 208, 212), (20, 20, 24)),     # plain office plate
}


def plate(text, size, style="steel", scale=4, rivets=True, seed=0):
    """A riveted metal sign plate `size` = (w, h) world units with centred `text`
    ('\\n' separates lines; the first line is drawn largest). Returns a PIL image at
    `scale` texels per unit (capped at 512 px)."""
    import random
    top, bottom, ink = PLATES[style]
    w, h = size
    k = max(1, min(scale, 512 // max(w, h)))
    W, H = w * k, h * k
    img = Image.new("RGB", (W, H))
    rnd = random.Random(f"{text}{style}{seed}")
    px = img.load()
    for y in range(H):
        t = y / max(1, H - 1)
        base = [round(a + (b - a) * t) for a, b in zip(top, bottom)]
        for x in range(W):
            n = rnd.randint(-5, 5)                       # brushed-metal grain
            px[x, y] = tuple(max(0, min(255, c + n)) for c in base)
    d = ImageDraw.Draw(img)
    e = max(1, k // 2)                                   # bevel: light top-left, dark bottom-right
    d.rectangle((0, 0, W - 1, e - 1), fill=tuple(min(255, c + 45) for c in top))
    d.rectangle((0, 0, e - 1, H - 1), fill=tuple(min(255, c + 30) for c in top))
    d.rectangle((0, H - e, W - 1, H - 1), fill=tuple(max(0, c - 55) for c in bottom))
    d.rectangle((W - e, 0, W - 1, H - 1), fill=tuple(max(0, c - 40) for c in bottom))
    if style == "warning":
        d.rectangle((2 * e, 2 * e, W - 1 - 2 * e, H - 1 - 2 * e), outline=ink, width=max(1, k // 2))
    if rivets and min(w, h) >= 12 and style != "warning":
        r = max(2, k * 3 // 4)
        for cx in (3 * k, W - 3 * k):
            for cy in (3 * k, H - 3 * k):
                d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=tuple(max(0, c - 60) for c in bottom))
                d.ellipse((cx - r, cy - r, cx + r - max(1, r // 2), cy + r - max(1, r // 2)),
                          fill=tuple(min(255, c + 60) for c in top))
    lines = [s for s in str(text or "").split("\n")]
    if lines and lines != [""]:
        margin = 7 * k if rivets and min(w, h) >= 12 else 3 * k
        weights = [1.0] + [0.6] * (len(lines) - 1)      # first line largest
        unit = (H - 2 * k) / (sum(weights) * 1.15)
        sizes = []
        for line, wt in zip(lines, weights):
            sz = max(6, int(unit * wt))
            while sz > 6 and d.textlength(line, font=font(sz)) > W - 2 * margin:
                sz -= 1
            sizes.append(sz)
        total = sum(s * 1.15 for s in sizes)
        y = (H - total) / 2
        for line, sz in zip(lines, sizes):
            d.text((W / 2, y + sz * 0.575), line, fill=ink, font=font(sz), anchor="mm")
            y += sz * 1.15
    return img


# ---------------------------------------------------------------- slide decks

DECK = {"bg": (14, 16, 24), "accent": (255, 220, 0), "text": (236, 236, 242), "dim": (122, 128, 152)}


def deck_slide(title, number=None, total=None, size=(384, 240), footer="", theme=DECK):
    """A blank slide in a deck's style: title, rule, footer and page number.
    Returns (image, draw); the body is roughly y 58..212 at the default size."""
    w, h = size
    img = Image.new("RGB", size, theme["bg"])
    d = ImageDraw.Draw(img)
    if title:
        d.text((18, 14), title, fill=theme["accent"], font=font(24))
        d.line((18, 46, w - 18, 46), fill=theme["accent"], width=2)
    if footer:
        d.text((18, h - 14), footer, fill=theme["dim"], font=font(11, bold=False), anchor="lm")
    if number:
        d.text((w - 18, h - 14), f"{number} / {total}" if total else str(number), fill=theme["dim"],
               font=font(11, bold=False), anchor="rm")
    return img, d


def bullets(d, items, x=24, y=64, size=17, gap=34, theme=DECK):
    """Bulleted lines; an item (text, sub) adds a dimmer second line."""
    for it in items:
        text, sub = it if isinstance(it, tuple) else (it, None)
        d.rectangle((x, y + size // 2 - 3, x + 6, y + size // 2 + 3), fill=theme["accent"])
        d.text((x + 16, y), text, fill=theme["text"], font=font(size))
        if sub:
            d.text((x + 16, y + size + 3), sub, fill=theme["dim"], font=font(size - 5, bold=False))
        y += gap
    return y


def waveform(d, samples, box, color, bars=90):
    """Draw audio samples (an array of ints) as a bar waveform inside box."""
    x0, y0, x1, y1 = box
    mid, half = (y0 + y1) / 2, (y1 - y0) / 2
    n = max(1, len(samples) // bars)
    top = max((abs(v) for v in samples), default=1) or 1
    step = (x1 - x0) / bars
    for i in range(bars):
        chunk = samples[i * n:(i + 1) * n]
        a = max((abs(v) for v in chunk), default=0) / top
        x = x0 + i * step
        d.rectangle((x, mid - a * half, x + step * 0.6, mid + a * half), fill=color)

