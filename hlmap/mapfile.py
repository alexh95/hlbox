"""Entities, the Map container and the Valve 220 .map writer."""
from __future__ import annotations

from pathlib import Path

from .geometry import Brush


def _fmt(x):
    x = float(x)
    if abs(x - round(x)) < 1e-6:
        return str(int(round(x)))
    return f"{x:.6f}".rstrip("0").rstrip(".")


def _kv_value(v):
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (tuple, list)):
        return " ".join(_fmt(c) if isinstance(c, (int, float)) else str(c) for c in v)
    if isinstance(v, float):
        return _fmt(v)
    return str(v)


class Entity:
    """A point entity (has origin) or brush entity (has brushes).

    Keyvalues: pass as kwargs, or `kv={...}` for keys that aren't Python identifiers
    (e.g. '_light'). Tuples are written space-separated: origin=(0, 0, 36).
    """

    def __init__(self, classname, brushes=None, kv=None, **kwargs):
        self.classname = classname
        self.brushes: list[Brush] = list(brushes or [])
        self.kv: dict[str, object] = {}
        self.kv.update(kv or {})
        self.kv.update(kwargs)

    def __getitem__(self, k): return self.kv[k]
    def __setitem__(self, k, v): self.kv[k] = v
    def get(self, k, default=None): return self.kv.get(k, default)

    @property
    def origin(self):
        o = self.kv.get("origin")
        if o is None:
            return None
        if isinstance(o, str):
            return tuple(float(c) for c in o.split())
        return tuple(o)

    def add(self, *brushes):
        for b in brushes:
            if isinstance(b, (list, tuple)):
                self.brushes.extend(b)
            else:
                self.brushes.append(b)
        return self

    def __repr__(self):
        return f"<Entity {self.classname} {self.kv.get('targetname', '')} brushes={len(self.brushes)}>"


class Map:
    def __init__(self, name="untitled", **world_kv):
        self.name = name
        self.worldspawn = Entity("worldspawn", kv={"mapversion": "220"})
        self.worldspawn.kv.update(world_kv)
        self.entities: list[Entity] = []
        self.texlights: dict[str, str] = {}   # texture -> "r g b intensity" (info_texlights)
        self.custom_textures: dict = {}       # name -> PIL image, written to <map>_custom.wad

    # --- building -------------------------------------------------------
    def add_world(self, *brushes):
        self.worldspawn.add(*brushes)
        return self

    def add(self, *entities):
        for e in entities:
            if isinstance(e, (list, tuple)):
                self.entities.extend(e)
            else:
                self.entities.append(e)
        return entities[0] if len(entities) == 1 else entities

    def texlight(self, texture, rgb=(255, 255, 255), intensity=1000):
        """Make every face with `texture` emit light (written as an info_texlights entity)."""
        self.texlights[texture] = f"{rgb[0]} {rgb[1]} {rgb[2]} {intensity}"

    def add_texture(self, name, image):
        """Add a non-standard texture (PIL image or image path). It is usable right away
        (fit(), alignment) and gets embedded in the BSP, so the map needs no extra files.
        Names: max 15 chars; '+0'/'+A' prefixes make toggling pairs, '{' transparent."""
        from PIL import Image
        from .wad import default_db
        from .wadwrite import _prepare
        if len(name) > 15:
            raise ValueError(f"texture name {name!r} is longer than 15 characters")
        img = image if isinstance(image, Image.Image) else Image.open(image)
        img = _prepare(img.convert("RGBA"))
        self.custom_textures[name] = img
        default_db().register(name, img)
        return name

    def all_entities(self):
        return [self.worldspawn] + self.entities

    def textures_used(self):
        return sorted({f.texture for e in self.all_entities() for b in e.brushes for f in b.faces})

    def find(self, classname=None, targetname=None):
        return [e for e in self.entities
                if (classname is None or e.classname == classname)
                and (targetname is None or e.get("targetname") == targetname)]

    # --- validation -------------------------------------------------------
    def check(self):
        """Return a list of problems that would break compiling or playing."""
        from .wad import default_db
        db = default_db()
        problems = []
        for t in self.textures_used():
            if t not in db:
                problems.append(f"texture not in any WAD: {t}")
            elif len(t) > 15:
                problems.append(f"texture name too long (max 15 chars): {t}")
        for ei, e in enumerate(self.all_entities()):
            for bi, b in enumerate(e.brushes):
                if not b.is_valid():
                    problems.append(f"entity {ei} ({e.classname}) brush {bi} {b.comment!r} is degenerate")
            if e.classname != "worldspawn" and not e.brushes and e.origin is None:
                problems.append(f"point entity {e.classname} has no origin")
            if e.brushes and e.classname in ("func_door_rotating", "func_rotating", "func_pendulum"):
                if not any(all(f.texture.upper() == "ORIGIN" for f in b.faces) for b in e.brushes):
                    problems.append(f"{e.classname} {e.get('targetname', '')} has no ORIGIN brush")
        names = {str(e.get("targetname")) for e in self.entities if e.get("targetname")}
        for e in self.entities:
            for key in ("target", "killtarget", "master", "zhlt_usestyle"):
                v = e.get(key)
                if v and str(v) not in names:
                    problems.append(f"{e.classname} {key}={v!r} matches no targetname"
                                    + (" (door/button would NOT be locked)" if key == "master" else ""))
        if not self.find("info_player_start") and not self.find("info_player_deathmatch"):
            problems.append("no info_player_start")
        return problems

    # --- output -----------------------------------------------------------
    def _wad_list(self):
        from .wad import default_db
        return default_db().wads_for(self.textures_used())

    def to_text(self):
        world = self.worldspawn
        if "wad" not in world.kv:
            world.kv["wad"] = ";".join(self._wad_list())
        ents = list(self.entities)
        if self.texlights:
            ents.append(Entity("info_texlights", kv=dict(self.texlights), origin=(0, 0, 0)))
        out = ["// Game: Half-Life", "// Format: Valve", f"// Generated by hlmap: {self.name}"]
        for i, e in enumerate([world] + ents):
            out.append(f"// entity {i}")
            out.append("{")
            out.append(f'"classname" "{e.classname}"')
            for k, v in e.kv.items():
                if k == "classname" or v is None:
                    continue
                out.append(f'"{k}" "{_kv_value(v)}"')
            for bi, b in enumerate(e.brushes):
                out.append(f"// brush {bi}" + (f" {b.comment}" if b.comment else ""))
                out.append("{")
                for f in b.faces:
                    pts = " ".join(f"( {_fmt(p[0])} {_fmt(p[1])} {_fmt(p[2])} )" for p in (f.p0, f.p1, f.p2))
                    u = " ".join(_fmt(c) for c in f.u_axis)
                    v = " ".join(_fmt(c) for c in f.v_axis)
                    out.append(f"{pts} {f.texture} [ {u} {_fmt(f.u_offset)} ] [ {v} {_fmt(f.v_offset)} ] "
                               f"{_fmt(f.rotation)} {_fmt(f.u_scale)} {_fmt(f.v_scale)}")
                out.append("}")
            out.append("}")
        return "\n".join(out) + "\n"

    def write(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.custom_textures:
            from .wad import default_db
            from .wadwrite import write_wad
            wad = path.with_name(f"{path.stem}_custom.wad")
            write_wad(wad, self.custom_textures)
            for name in self.custom_textures:
                default_db().get(name).wad = str(wad)
        path.write_text(self.to_text(), encoding="latin-1")
        return path
