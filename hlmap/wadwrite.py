"""Write custom textures (any image) into a WAD3 file.

Each texture is quantized to its own 256-colour palette and stored with the four mip
levels GoldSrc expects. Sizes are rounded to multiples of 16 (engine requirement).
Names starting with '{' are transparent: palette index 255 is reserved for pixels
with alpha < 128 (drawn see-through on entities with rendermode 4).
"""
from __future__ import annotations

import struct
from pathlib import Path

from PIL import Image

MIPTEX = 0x43


def _prepare(img: Image.Image, max_size=512):
    w, h = img.size
    scale = min(1.0, max_size / max(w, h))
    w16 = max(16, int(round(w * scale / 16)) * 16)
    h16 = max(16, int(round(h * scale / 16)) * 16)
    if (w16, h16) != (w, h):
        img = img.resize((w16, h16), Image.LANCZOS)
    return img


def _miptex(name, img: Image.Image):
    transparent = name.startswith("{")
    img = _prepare(img.convert("RGBA"))
    w, h = img.size
    rgb = img.convert("RGB")
    colors = 255 if transparent else 256
    q = rgb.quantize(colors=colors, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = (q.getpalette() or [])[:768]
    pal += [0] * (768 - len(pal))
    if transparent:
        pal[765:768] = [0, 0, 255]
    levels = []
    for k in range(4):
        lw, lh = w >> k, h >> k
        if k == 0:
            lq = q
        else:
            lq = rgb.resize((lw, lh), Image.LANCZOS).quantize(palette=q, dither=Image.Dither.NONE)
        data = bytearray(lq.tobytes())
        if transparent:
            alpha = img.getchannel("A").resize((lw, lh), Image.NEAREST).tobytes()
            for i, a in enumerate(alpha):
                if a < 128:
                    data[i] = 255
        levels.append(bytes(data))
    header = struct.pack("<16sII", name.encode("latin-1")[:15].ljust(16, b"\0"), w, h)
    offsets, pos = [], 40
    for lv in levels:
        offsets.append(pos)
        pos += len(lv)
    blob = header + struct.pack("<4I", *offsets) + b"".join(levels) + struct.pack("<H", 256) + bytes(pal)
    blob += b"\0" * (-len(blob) % 4)
    return blob, (w, h)


def write_wad(path, textures):
    """textures: {name: PIL.Image}. Returns {name: (width, height)} as stored."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lumps, sizes = [], {}
    for name, img in textures.items():
        if len(name) > 15:
            raise ValueError(f"texture name {name!r} is longer than 15 characters")
        blob, sizes[name] = _miptex(name, img)
        lumps.append((name, blob))
    out = bytearray(b"WAD3" + struct.pack("<ii", len(lumps), 0))
    entries = []
    for name, blob in lumps:
        entries.append((len(out), len(blob), name))
        out += blob
    diroff = len(out)
    for pos, size, name in entries:
        out += struct.pack("<iiibbh16s", pos, size, size, MIPTEX, 0, 0, name.encode("latin-1").ljust(16, b"\0"))
    struct.pack_into("<i", out, 8, diroff)
    path.write_bytes(bytes(out))
    return sizes
