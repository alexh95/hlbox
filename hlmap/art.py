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


# ---------------------------------------------------------------- outdoor textures

def tree(seed=0, size=(256, 256), leaf=(70, 110, 52), kind="broad"):
    """A painted tree with a transparent background, for crossed '{' planes
    (props.tree). kind: 'broad' (round canopy) or 'pine' (a tall cone)."""
    import random
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    bark = (86, 62, 40, 255)
    d.polygon([(w * 0.46, h), (w * 0.54, h), (w * 0.52, h * 0.35), (w * 0.48, h * 0.35)], fill=bark)
    if kind == "pine":
        for k in range(7):                            # stacked, narrowing tiers
            y = h * (0.92 - k * 0.12)
            half = w * (0.44 - k * 0.055)
            d.polygon([(w / 2 - half, y), (w / 2 + half, y), (w / 2, y - h * 0.24)],
                      fill=tuple(max(0, c - 10 + rnd.randint(-8, 8)) for c in leaf) + (255,))
    else:
        for _ in range(9):                            # branches
            y = h * rnd.uniform(0.35, 0.6)
            d.line((w / 2, y, w / 2 + rnd.uniform(-0.3, 0.3) * w, y - h * rnd.uniform(0.1, 0.25)), fill=bark, width=3)
        for k in range(150):                          # leaf clumps, darker underneath
            r = rnd.uniform(w * 0.04, w * 0.085)
            cx = min(w - r - 2, max(r + 2, w / 2 + rnd.gauss(0, w * 0.15)))
            cy = min(h * 0.62, max(r + 2, h * 0.34 + rnd.gauss(0, h * 0.12)))
            shade = rnd.uniform(-28, 30) - (cy / h - 0.3) * 60
            col = tuple(max(0, min(255, int(c + shade))) for c in leaf) + (255,)
            d.ellipse((cx - r, cy - r * 0.85, cx + r, cy + r * 0.85), fill=col)
    px = img.load()                                   # speckle
    for _ in range(w * h // 6):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r, g, b, a = px[x, y]
        if a:
            n = rnd.randint(-14, 14)
            px[x, y] = (max(0, min(255, r + n)), max(0, min(255, g + n)), max(0, min(255, b + n)), a)
    return img


def paint(color, size=(64, 64), gloss=True, noise=6, seed=0):
    """A painted surface (car body, road marking): flat colour, a soft highlight
    band and a little grit."""
    import random
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        k = 1.0 + (0.18 * max(0.0, 1 - abs(t - 0.3) * 4) if gloss else 0) - 0.12 * t
        for x in range(w):
            n = rnd.randint(-noise, noise)
            px[x, y] = tuple(max(0, min(255, int(c * k) + n)) for c in color)
    return img


def bark(size=(64, 128), seed=0):
    import random
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size, (82, 60, 40))
    d = ImageDraw.Draw(img)
    for _ in range(40):                               # vertical furrows
        x = rnd.randrange(w)
        d.line((x, 0, x + rnd.randint(-3, 3), h), fill=(52, 38, 26), width=rnd.choice((1, 2)))
    for _ in range(300):
        x, y = rnd.randrange(w), rnd.randrange(h)
        d.point((x, y), fill=(110 + rnd.randint(-20, 20), 84 + rnd.randint(-15, 15), 58))
    return img


# ---------------------------------------------------------------- the facility's mascot

def boxworth():
    """Boxworth, the facility's mascot: a supply crate with boots and a hard hat, as
    32x32 pixel art (transparent; scale it up with NEAREST)."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink, wood, light, seam = (58, 36, 18), (184, 126, 62), (214, 160, 92), (146, 98, 46)
    d.rectangle((4, 18, 5, 22), fill=wood, outline=ink)                  # arms
    d.rectangle((26, 16, 27, 20), fill=wood, outline=ink)
    d.rectangle((8, 27, 12, 30), fill=(52, 54, 62), outline=ink)         # boots
    d.rectangle((19, 27, 23, 30), fill=(52, 54, 62), outline=ink)
    d.rectangle((6, 11, 25, 28), fill=wood, outline=ink)                 # the crate
    d.rectangle((7, 12, 24, 27), outline=light)
    for x in (12, 19):                                                   # plank seams
        d.line((x, 13, x, 26), fill=seam)
    for x, y in ((7, 12), (23, 12), (7, 26), (23, 26)):                  # corner brackets
        d.rectangle((x, y, x + 1, y + 1), fill=(120, 124, 132))
    d.rectangle((9, 15, 13, 19), fill=(246, 246, 240), outline=ink)      # eyes
    d.rectangle((18, 15, 22, 19), fill=(246, 246, 240), outline=ink)
    d.rectangle((11, 16, 12, 18), fill=ink)
    d.rectangle((20, 16, 21, 18), fill=ink)
    d.point([(10, 16), (19, 16)], fill=(255, 255, 255))
    d.rectangle((8, 21, 9, 21), fill=(232, 124, 110))                    # cheeks
    d.rectangle((22, 21, 23, 21), fill=(232, 124, 110))
    d.line((13, 22, 18, 22), fill=ink)                                   # smile
    d.point([(12, 21), (19, 21)], fill=ink)
    d.pieslice((8, 2, 23, 16), 180, 360, fill=(255, 204, 0), outline=ink)   # hard hat
    d.rectangle((5, 9, 26, 11), fill=(232, 170, 0), outline=ink)
    d.line((15, 3, 15, 8), fill=(255, 232, 110))
    return img


def card_reader(active=False):
    """A wall card reader, 32x48: a slot, a keypad and a status lamp (red idle, amber
    while reading: the '+A' frame a pressed button shows)."""
    img = Image.new("RGB", (32, 48), (58, 62, 70))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 31, 47), outline=(110, 116, 128))
    d.rectangle((1, 1, 30, 46), outline=(34, 36, 42))
    d.rectangle((5, 5, 26, 14), fill=(24, 26, 30))                       # display
    lamp = (255, 176, 30) if active else (230, 40, 30)
    d.ellipse((12, 7, 19, 12), fill=lamp)
    d.rectangle((6, 18, 25, 21), fill=(12, 12, 14))                      # card slot
    d.line((6, 22, 25, 22), fill=(120, 126, 138))
    for r in range(3):                                                   # keypad
        for c in range(3):
            x, y = 8 + c * 6, 26 + r * 6
            d.rectangle((x, y, x + 3, y + 3), fill=(150, 154, 164), outline=(40, 42, 48))
    d.rectangle((6, 44, 25, 45), fill=(246, 204, 24))
    return img


def boxworth_faces(size=64):
    """Boxworth's crate as textures for a brush model: (front with his face, plain side).
    Same palette as boxworth()."""
    out = []
    for face in (True, False):
        img = Image.new("RGB", (32, 32), (184, 126, 62))
        d = ImageDraw.Draw(img)
        ink, light, seam = (58, 36, 18), (214, 160, 92), (146, 98, 46)
        d.rectangle((0, 0, 31, 31), outline=ink)
        d.rectangle((1, 1, 30, 30), outline=light)
        for x in (11, 20):                                   # plank seams
            d.line((x, 2, x, 29), fill=seam)
        for x, y in ((2, 2), (28, 2), (2, 28), (28, 28)):    # corner brackets
            d.rectangle((x, y, x + 1, y + 1), fill=(120, 124, 132))
        if face:
            d.rectangle((5, 8, 11, 14), fill=(246, 246, 240), outline=ink)     # eyes
            d.rectangle((20, 8, 26, 14), fill=(246, 246, 240), outline=ink)
            d.rectangle((8, 10, 10, 12), fill=ink)
            d.rectangle((21, 10, 23, 12), fill=ink)
            d.point([(8, 10), (21, 10)], fill=(255, 255, 255))
            d.rectangle((4, 18, 6, 19), fill=(232, 124, 110))                 # cheeks
            d.rectangle((25, 18, 27, 19), fill=(232, 124, 110))
            d.line((11, 21, 20, 21), fill=ink)                                # smile
            d.point([(10, 20), (21, 20)], fill=ink)
        out.append(img.resize((size, size), Image.NEAREST))
    return tuple(out)


def skip_panel(label="INTERCOM", size=(24, 36), scale=4):
    """An intercom panel (size in world units): a label, a speaker grille and a SKIP
    legend over the spot where scene.skip_button puts its button."""
    w, h = size[0] * scale, size[1] * scale
    img = plate("", size, "steel", scale=scale, rivets=False)
    d = ImageDraw.Draw(img)
    d.rectangle((6, 6, w - 7, 26), fill=(30, 34, 44))
    d.text((w // 2, 16), label, fill=(236, 236, 242), font=font(12), anchor="mm")
    for y in range(32, 64, 6):                                 # speaker grille
        d.rounded_rectangle((14, y, w - 15, y + 3), radius=1, fill=(40, 44, 54))
    ink = (16, 26, 62)
    d.text((w // 2 - 10, 78), "SKIP", fill=ink, font=font(13), anchor="mm")
    for x0 in (w // 2 + 14, w // 2 + 22):                      # >>
        d.polygon([(x0, 72), (x0 + 7, 78), (x0, 84)], fill=ink)
    return img


def skip_button(pressed=False):
    """The skip button's face: '+0' idle, '+A' lit while pressed."""
    img = Image.new("RGB", (32, 32), (50, 54, 64))
    d = ImageDraw.Draw(img)
    d.ellipse((2, 2, 29, 29), fill=(20, 22, 28))
    d.ellipse((4, 4, 27, 27), fill=(90, 230, 120) if pressed else (40, 130, 70))
    for x0 in (9, 16):                                          # the fast-forward arrows
        d.polygon([(x0, 10), (x0 + 7, 16), (x0, 22)], fill=(240, 250, 240))
    return img


def transit_pad(state="on", color=(120, 200, 255), size=64):
    """A teleporter pad's top: rings around a core. state: 'on' (lit), 'off' (dark,
    its '+A' frame) or 'offline' (dark, with a red bar)."""
    import math as _m
    img = Image.new("RGB", (size, size), (34, 38, 46))
    d = ImageDraw.Draw(img)
    c = size / 2
    lit = state == "on"
    ring = color if lit else (70, 76, 88)
    core = tuple(min(255, v + 90) for v in color) if lit else (56, 60, 70)
    for k in range(8):                                        # hazard ring at the rim
        a0 = k * 45
        d.pieslice((1, 1, size - 2, size - 2), a0, a0 + 22, fill=(230, 180, 20))
    d.ellipse((5, 5, size - 6, size - 6), fill=(34, 38, 46))
    for r, wdt in ((24, 3), (17, 2), (10, 2)):
        d.ellipse((c - r, c - r, c + r, c + r), outline=ring, width=wdt)
    d.ellipse((c - 5, c - 5, c + 5, c + 5), fill=core)
    for k in range(4):                                        # spokes
        a = _m.radians(45 + 90 * k)
        d.line((c + _m.cos(a) * 10, c + _m.sin(a) * 10, c + _m.cos(a) * 24, c + _m.sin(a) * 24), fill=ring, width=2)
    if state == "offline":
        d.rectangle((6, c - 5, size - 7, c + 5), fill=(170, 30, 24))
    return img


def network_diagram(sites, edges, size=(256, 192), title="NETWORK", color=(120, 200, 255)):
    """A wall board of a teleporter network: `sites` as nodes (the busiest in the
    middle, the rest around it), `edges` [(a, b, active)] as lines, dashed when
    offline."""
    import math as _m
    w, h = size
    img = Image.new("RGB", size, (16, 20, 30))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, w - 1, 20), fill=(30, 38, 56))
    d.text((w // 2, 10), title, fill=(236, 236, 242), font=font(12), anchor="mm")
    degree = {s: sum(1 for a, b, _ in edges if s in (a, b)) for s in sites}
    hub = max(sites, key=lambda s: degree[s]) if sites else None
    others = [s for s in sites if s != hub]
    cx, cy, rx, ry = w / 2, 20 + (h - 20) / 2, w * 0.30, (h - 20) * 0.30
    pos = {hub: (cx, cy)}
    for k, s in enumerate(others):
        a = _m.radians(-90 + 360 * k / max(1, len(others)))
        pos[s] = (cx + rx * _m.cos(a), cy + ry * _m.sin(a))
    for a, b, active in edges:
        (x0, y0), (x1, y1) = pos[a], pos[b]
        if active:
            d.line((x0, y0, x1, y1), fill=color, width=3)
        else:
            n = max(1, int(_m.hypot(x1 - x0, y1 - y0) // 8))
            for k in range(0, n, 2):
                t0, t1 = k / n, min(1, (k + 1) / n)
                d.line((x0 + (x1 - x0) * t0, y0 + (y1 - y0) * t0, x0 + (x1 - x0) * t1, y0 + (y1 - y0) * t1),
                       fill=(110, 110, 120), width=2)
    offline = {b for a, b, active in edges if not active}
    for s, (x, y) in pos.items():
        r = 9 if s == hub else 6
        d.ellipse((x - r, y - r, x + r, y + r), fill=(110, 110, 120) if s in offline else color,
                  outline=(236, 236, 242), width=1)
        half = d.textlength(s, font=font(10)) / 2                  # above the top nodes, below the rest
        lx = min(w - 4 - half, max(4 + half, x))
        ly = y - r - 8 if s != hub and y < cy - 4 else y + r + 8
        d.text((lx, ly), s, fill=(150, 150, 160) if s in offline else (236, 236, 242), font=font(10), anchor="mm")
    return img
