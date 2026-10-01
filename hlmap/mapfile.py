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
        self.textures: dict = {}   # custom textures this entity brings (Map.add registers them)

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


def prepare_texture(name, image):
    """Make `image` (PIL image or path) usable as texture `name` right away (fit(),
    alignment); returns the prepared image to embed. Names: max 15 characters."""
    from PIL import Image
    from .wad import default_db
    from .wadwrite import _prepare
    if len(name) > 15:
        raise ValueError(f"texture name {name!r} is longer than 15 characters")
    img = image if isinstance(image, Image.Image) else Image.open(image)
    img = _prepare(img.convert("RGBA"))
    default_db().register(name, img)
    return img


class Map:
    def __init__(self, name="untitled", **world_kv):
        self.name = name
        self.worldspawn = Entity("worldspawn", kv={"mapversion": "220"})
        self.worldspawn.kv.update(world_kv)
        self.entities: list[Entity] = []
        self.texlights: dict[str, str] = {}   # texture -> "r g b intensity" (info_texlights)
        self.custom_textures: dict = {}       # name -> PIL image, written to <map>_custom.wad
        self.custom_sounds: dict = {}         # "hlbox/<map>/x.wav" (under valve/sound) -> source WAV
        self.notes: list = []                 # problems found while building (reported by check())

    # --- building -------------------------------------------------------
    def add_world(self, *brushes):
        self.worldspawn.add(*brushes)
        return self

    def add(self, *entities):
        for e in entities:
            for ent in (e if isinstance(e, (list, tuple)) else [e]):
                self.entities.append(ent)
                self.custom_textures.update(getattr(ent, "textures", None) or {})
        return entities[0] if len(entities) == 1 else entities

    def texlight(self, texture, rgb=(255, 255, 255), intensity=1000):
        """Make every face with `texture` emit light (written as an info_texlights entity)."""
        self.texlights[texture] = f"{rgb[0]} {rgb[1]} {rgb[2]} {intensity}"

    def add_texture(self, name, image):
        """Add a non-standard texture (PIL image or image path). It is usable right away
        (fit(), alignment) and gets embedded in the BSP, so the map needs no extra files.
        Names: max 15 chars; '+0'/'+A' prefixes make toggling pairs, '{' transparent."""
        self.custom_textures[name] = prepare_texture(name, image)
        return name

    def add_sound(self, name, source):
        """Ship a WAV with the map: `name` is its path under valve/sound (e.g.
        "hlbox/office/talk01.wav", what ambient_generic's `message` names); `source`
        is the file. It is installed next to the map and listed in <map>.res."""
        name = str(name).replace("\\", "/")
        self.custom_sounds[name] = Path(source)
        return name

    def content_files(self, build_dir):
        """Files the map needs besides its BSP, {path under valve/: built file}."""
        build_dir = Path(build_dir)
        files = {f"sound/{n}": build_dir / "sound" / n for n in self.custom_sounds}
        if files:
            files[f"maps/{self.name}.res"] = build_dir / f"{self.name}.res"
        return files

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
        problems = list(self.notes)
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
        marks = [str(e.get("targetname")) for e in self.find("info_landmark")]
        for e in self.find("trigger_changelevel"):
            if not e.get("map"):
                problems.append("trigger_changelevel without a map")
            elif e.get("landmark") and marks.count(str(e.get("landmark"))) != 1:
                problems.append(f"trigger_changelevel to {e.get('map')}: landmark {e.get('landmark')!r} must be an "
                                f"info_landmark in this map exactly once (found {marks.count(str(e.get('landmark')))})")
        for e in self.find("monstermaker"):     # HLSDK: named + "start on" sets no first think
            if e.get("targetname") and int(e.get("spawnflags") or 0) & 1:
                problems.append(f"monstermaker {e.get('targetname')} has a name and 'start on': it never starts "
                                "(fire it, e.g. from a trigger_auto, or leave the name off)")
        for e in self.find("infodecal"):
            if str(e.get("texture")) not in db:
                problems.append(f"infodecal texture {e.get('texture')!r} is not in decals.wad")
        from . import config
        from .voice import check_wav, loops
        for e in self.find("ambient_generic"):
            wav = str(e.get("message") or "")
            src = self.custom_sounds.get(wav) or config.GAME_DIR / "sound" / wav
            if not wav.endswith(".wav") or not Path(src).exists():
                if wav.endswith(".wav") and Path(config.GAME_DIR / "sound").exists():
                    problems.append(f"sound {e.get('targetname') or wav}: {wav} is not a sound the game has")
                continue
            flags = int(e.get("spawnflags") or 0)
            if flags & 32 and loops(src):          # a looping WAV played "once" can never be stopped
                problems.append(f"sound {e.get('targetname') or wav}: {wav} loops, and played once it never stops; "
                                "use props.sound_effect(..., stoppable=True) and turn it off")
            elif not flags & (16 | 32) and not loops(src):
                problems.append(f"sound {e.get('targetname') or wav}: {wav} has no loop points, so a sound that "
                                "starts on plays it once as the map loads (and on every load); use a looping WAV "
                                "(props.ambient_loop) or props.sound_effect")
        for n, src in self.custom_sounds.items():
            if len(n) > 60:
                problems.append(f"sound name {n!r} is longer than 60 characters")
            if not Path(src).exists():
                problems.append(f"sound {n}: {src} does not exist")
            else:
                problems += [f"sound {n}: {p}" for p in check_wav(src)]
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
            # any point entity outside the sealed level leaks, so put it where the player starts
            start = next((e.origin for e in self.find("info_player_start")), None) or (0, 0, 0)
            ents.append(Entity("info_texlights", kv=dict(self.texlights), origin=start))
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
        if self.custom_sounds:          # copies next to the build, and the resource list
            import shutil
            for n, src in self.custom_sounds.items():
                dest = path.parent / "sound" / n
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, dest)
            res = ["// custom content for " + self.name + " (written by hlmap)"]
            res += [f"sound/{n}" for n in sorted(self.custom_sounds)]
            path.with_name(f"{self.name}.res").write_text("\n".join(res) + "\n", encoding="latin-1")
        return path
