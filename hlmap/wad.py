"""WAD3 (GoldSrc texture archive) reader.

Used to look up texture sizes (needed for alignment) and to render texture
images for previews / contact sheets.
"""
import json
import struct
from functools import lru_cache
from pathlib import Path

from . import config

MIPTEX = 0x43


class Texture:
    __slots__ = ("name", "width", "height", "wad", "_offset")

    def __init__(self, name, width, height, wad, offset):
        self.name, self.width, self.height, self.wad, self._offset = name, width, height, wad, offset

    def __repr__(self):
        return f"<Texture {self.name} {self.width}x{self.height} ({Path(self.wad).name})>"

    def image(self):
        """Full-size mip level 0 as a PIL RGB(A) image. '{' textures get alpha for index 255."""
        from PIL import Image

        with open(self.wad, "rb") as f:
            f.seek(self._offset)
            data = f.read(40 + self.width * self.height * 85 // 64 + 2 + 768 + 64)
        name, w, h, o0, o1, o2, o3 = struct.unpack_from("<16sII4I", data, 0)
        pix = data[o0:o0 + w * h]
        pal_off = o3 + (w // 8) * (h // 8) + 2
        pal = data[pal_off:pal_off + 768]
        img = Image.frombytes("P", (w, h), pix)
        img.putpalette(pal)
        if self.name.startswith("{"):
            img.info["transparency"] = 255
            return img.convert("RGBA")
        return img.convert("RGB")


def read_wad(path):
    """Return {UPPERNAME: Texture} for every miptex in a WAD3 file."""
    path = str(path)
    out = {}
    with open(path, "rb") as f:
        magic, count, diroff = struct.unpack("<4sii", f.read(12))
        if magic not in (b"WAD3", b"WAD2"):
            raise ValueError(f"{path}: not a WAD3 file")
        f.seek(diroff)
        entries = [struct.unpack("<iiibbh16s", f.read(32)) for _ in range(count)]
        for filepos, disksize, size, typ, comp, _pad, raw in entries:
            if typ != MIPTEX:
                continue
            f.seek(filepos + 16)
            w, h = struct.unpack("<II", f.read(8))
            name = raw.split(b"\0", 1)[0].decode("latin-1")
            out[name.upper()] = Texture(name, w, h, path, filepos)
    return out


class MemTexture:
    """A custom texture held in memory (see Map.add_texture)."""

    def __init__(self, name, img):
        self.name, self._img = name, img
        self.width, self.height = img.size
        self.wad = None   # set when the map's custom WAD is written

    def image(self):
        return self._img.convert("RGBA" if self.name.startswith("{") else "RGB")

    def __repr__(self):
        return f"<MemTexture {self.name} {self.width}x{self.height}>"


class TextureDB:
    """All textures from a list of WADs. Later WADs don't override earlier ones."""

    def __init__(self, wads=None):
        self.wads = [Path(w) for w in (wads or config.DEFAULT_WADS) if Path(w).exists()]
        self.textures = {}
        for w in self.wads:
            for k, t in read_wad(w).items():
                self.textures.setdefault(k, t)

    def __contains__(self, name):
        return name.upper() in self.textures

    def get(self, name):
        t = self.textures.get(name.upper())
        if t is None:
            raise KeyError(f"texture {name!r} not found in {[w.name for w in self.wads]}")
        return t

    def size(self, name):
        t = self.get(name)
        return t.width, t.height

    def search(self, pattern=""):
        import fnmatch

        pat = pattern.upper()
        if not any(c in pat for c in "*?["):
            pat = f"*{pat}*"
        return [t for k, t in sorted(self.textures.items()) if fnmatch.fnmatch(k, pat)]

    def register(self, name, img):
        """Add (or replace) an in-memory custom texture."""
        self.textures[name.upper()] = MemTexture(name, img)

    def wads_for(self, names):
        """The subset of WAD paths that provide the given texture names."""
        used = {str(self.get(n).wad) for n in names if n.upper() in self.textures and self.get(n).wad}
        out = [str(w) for w in self.wads if str(w) in used]
        return out + sorted(u for u in used if u not in out)


@lru_cache(maxsize=1)
def default_db():
    return TextureDB()


def contact_sheet(textures, path, thumb=96, cols=10):
    """Save a labelled grid of texture thumbnails, for picking textures by eye."""
    from PIL import Image, ImageDraw

    rows = (len(textures) + cols - 1) // cols
    cell_w, cell_h = thumb + 8, thumb + 26
    sheet = Image.new("RGB", (cols * cell_w, max(rows, 1) * cell_h), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    for i, t in enumerate(textures):
        x, y = (i % cols) * cell_w + 4, (i // cols) * cell_h + 4
        im = t.image().convert("RGB")
        scale = thumb / max(im.width, im.height)
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.NEAREST)
        sheet.paste(im, (x, y))
        d.text((x, y + thumb + 1), t.name[:15], fill=(230, 230, 230))
        d.text((x, y + thumb + 11), f"{t.width}x{t.height}", fill=(140, 140, 150))
    sheet.save(path)
    return path


def dump_index(path):
    db = default_db()
    data = {t.name: [t.width, t.height, Path(t.wad).name] for t in db.textures.values()}
    Path(path).write_text(json.dumps(data, indent=0, sort_keys=True))
