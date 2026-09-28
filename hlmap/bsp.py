"""Minimal BSP v30 (GoldSrc) reader/writer: entity lump editing + geometry access."""
from __future__ import annotations

import re
import struct
from pathlib import Path

LUMPS = ["entities", "planes", "textures", "vertices", "visibility", "nodes", "texinfo",
         "faces", "lighting", "clipnodes", "leaves", "marksurfaces", "edges", "surfedges", "models"]


class BSP:
    def __init__(self, path):
        self.path = Path(path)
        data = self.path.read_bytes()
        version = struct.unpack_from("<i", data, 0)[0]
        if version != 30:
            raise ValueError(f"{path}: BSP version {version}, expected 30")
        self.lumps = {}
        for i, name in enumerate(LUMPS):
            off, ln = struct.unpack_from("<ii", data, 4 + i * 8)
            self.lumps[name] = data[off:off + ln]

    # --- entities -----------------------------------------------------------
    @property
    def entities(self):
        return parse_entities(self.lumps["entities"].rstrip(b"\0").decode("latin-1"))

    @entities.setter
    def entities(self, ents):
        self.lumps["entities"] = serialize_entities(ents).encode("latin-1") + b"\0"

    def save(self, path=None):
        path = Path(path or self.path)
        header_size = 4 + 8 * len(LUMPS)
        out = bytearray(header_size)
        struct.pack_into("<i", out, 0, 30)
        for i, name in enumerate(LUMPS):
            data = self.lumps[name]
            while len(out) % 4:
                out.append(0)
            struct.pack_into("<ii", out, 4 + i * 8, len(out), len(data))
            out += data
        path.write_bytes(bytes(out))
        return path

    # --- geometry -------------------------------------------------------------
    def textures(self):
        data = self.lumps["textures"]
        n = struct.unpack_from("<i", data, 0)[0]
        offs = struct.unpack_from(f"<{n}i", data, 4)
        out = []
        for o in offs:
            if o < 0:
                out.append(("", 0, 0))
                continue
            name, w, h = struct.unpack_from("<16sII", data, o)
            out.append((name.split(b"\0")[0].decode("latin-1"), w, h))
        return out

    def stats(self):
        sizes = {"planes": 20, "vertices": 12, "nodes": 24, "texinfo": 40, "faces": 20,
                 "clipnodes": 8, "leaves": 28, "marksurfaces": 2, "edges": 4, "surfedges": 4, "models": 64}
        s = {k: len(self.lumps[k]) // v for k, v in sizes.items()}
        s["lighting_bytes"] = len(self.lumps["lighting"])
        s["visibility_bytes"] = len(self.lumps["visibility"])
        s["entities"] = len(self.entities)
        return s


_TOKEN = re.compile(r'"([^"]*)"|([{}])')


def parse_entities(text):
    ents, cur, key = [], None, None
    for m in _TOKEN.finditer(text):
        if m.group(2) == "{":
            cur = []
        elif m.group(2) == "}":
            ents.append(cur)
            cur = None
        elif cur is not None:
            if key is None:
                key = m.group(1)
            else:
                cur.append((key, m.group(1)))
                key = None
    # list of ordered (key, value) pairs -> dicts (last key wins; keys are unique in practice)
    return [dict(e) for e in ents]


def serialize_entities(ents):
    parts = []
    for e in ents:
        parts.append("{\n" + "".join(f'"{k}" "{v}"\n' for k, v in e.items()) + "}\n")
    return "".join(parts)
