"""Command line:  python -m hlmap <command> ...

  setup                                       download the SDHLT compilers into tools/sdhlt
  build <map> [--profile fast|normal|final] [--no-install] [--shots]
        maps/<map>.py -> build/<map>/<map>.map -> compile -> install -> previews
  preview <map> [--view top|x|y] [--cut N]    orthographic cutaway PNG (no compile)
  shots <map> [--cam "x y z pitch yaw"]... [--fire NAME|@doors]
                                              in-engine screenshots (uses CAMERAS by default)
  play <map>                                  launch Half-Life into the map
  tex <pattern> [--sheet]                     search textures (and render a contact sheet)
  info <map>                                  stats + entity list of the compiled BSP
"""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from . import config


def load_map_module(name):
    path = config.MAPS_SRC_DIR / f"{name}.py"
    if not path.exists():
        sys.exit(f"no map source {path}")
    spec = importlib.util.spec_from_file_location(f"maps.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_map(name):
    mod = load_map_module(name)
    m = mod.build()
    m.name = name
    return m, mod


def out_dir(name):
    d = config.BUILD_DIR / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def cmd_setup(a):
    from .setup import install_sdhlt
    print(install_sdhlt(force=a.force))


def cmd_build(a):
    from .compile import compile_map
    from .preview import render
    from .setup import installed
    if not installed():
        sys.exit("SDHLT compilers missing: run  python -m hlmap setup")
    m, mod = build_map(a.map)
    problems = m.check()
    level = getattr(m, "level", None)
    if level:
        for e in m.entities:
            o = e.origin
            if o is not None and not e.brushes and e.classname != "info_texlights" and not level.is_inside(o):
                problems.append(f"{e.classname} at {o} is outside every room (in solid or void)")
    if problems:
        print("MAP PROBLEMS:\n  " + "\n  ".join(problems))
        if any("degenerate" in p or "not in any WAD" in p for p in problems):
            sys.exit(1)
    d = out_dir(a.map)
    map_path = m.write(d / f"{a.map}.map")
    print(f"wrote {map_path}  ({len(m.worldspawn.brushes)} world brushes, {len(m.entities)} entities)")
    for view, cut in (("top", None),):
        print("preview:", render(m, d / "plan.png", view=view, cut=cut))
    res = compile_map(map_path, profile=a.profile)
    print(res.summary())
    if res.pointfile:
        print("leak preview:", render(m, d / "leak.png", pointfile=res.pointfile))
    if not res.ok:
        sys.exit(1)
    if not a.no_install:
        from . import game
        print("installed:", game.install(res.bsp, a.map))
    if a.shots:
        a.cam, a.fire = None, None
        cmd_shots(a)


def _parse_cams(cams, mod):
    if cams:
        return [tuple(float(x) for x in c.replace(",", " ").split()) for c in cams]
    return list(getattr(mod, "CAMERAS", [])) or None


def cmd_shots(a):
    from . import game
    mod = load_map_module(a.map)
    cams = _parse_cams(a.cam, mod)
    if not cams:
        sys.exit("no cameras: pass --cam 'x y z pitch yaw' or define CAMERAS in the map script")
    bsp = config.BUILD_DIR / a.map / f"{a.map}.bsp"
    if not bsp.exists():
        sys.exit(f"{bsp} not found; run build first")
    d = out_dir(a.map) / "shots"
    for old in d.glob("*.png"):
        old.unlink()
    pngs, log = game.screenshots(bsp, cams, d, prefix=f"{a.map}_", width=a.width, height=a.height,
                                 wait_frames=a.wait, fire=a.fire or ())
    interesting = [l for l in log.splitlines()
                   if any(k in l.lower() for k in ("error", "warning", "missing", "couldn't", "can't",
                                                    "bad ", "overflow", "hlmap"))
                   and "_load.cfg" not in l and "_unload.cfg" not in l]
    for l in interesting:
        print("  console:", l)
    for cam, p in zip(cams, pngs):
        print(f"shot {p}  cam={cam}")
    if len(pngs) != len(cams):
        print(f"WARNING: expected {len(cams)} screenshots, got {len(pngs)}")


def cmd_preview(a):
    from .preview import render
    m, _ = build_map(a.map)
    d = out_dir(a.map)
    name = "plan.png" if a.view == "top" else f"section_{a.view}.png"
    print(render(m, d / name, view=a.view, cut=a.cut))


def cmd_play(a):
    from . import game
    if game.hl_running():
        sys.exit("Half-Life is already running")
    game.launch(a.map, dev=a.dev)
    print(f"launched Half-Life into {a.map}")


def cmd_tex(a):
    from .wad import default_db, contact_sheet
    ts = default_db().search(a.pattern)
    for t in ts[:400]:
        print(f"{t.name:16s} {t.width:4d}x{t.height:<4d} {Path(t.wad).name}")
    if len(ts) > 400:
        print(f"... {len(ts) - 400} more")
    if a.sheet:
        p = config.BUILD_DIR / "sheets" / (a.pattern.replace("*", "_").replace("?", "_") or "all")
        p = p.with_suffix(".png")
        p.parent.mkdir(parents=True, exist_ok=True)
        print("sheet:", contact_sheet(ts[:120], p, thumb=a.thumb))


def cmd_info(a):
    from .bsp import BSP
    b = BSP(config.BUILD_DIR / a.map / f"{a.map}.bsp")
    print(b.stats())
    for e in b.entities:
        print(" ", e.get("classname"), {k: v for k, v in e.items() if k != "classname"})


def main(argv=None):
    p = argparse.ArgumentParser(prog="hlmap", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    su = sub.add_parser("setup")
    su.add_argument("--force", action="store_true", help="re-download even if present")
    su.set_defaults(fn=cmd_setup)

    b = sub.add_parser("build")
    b.add_argument("map")
    b.add_argument("--profile", default="normal", choices=["fast", "normal", "final"])
    b.add_argument("--no-install", action="store_true")
    b.add_argument("--shots", action="store_true", help="also take in-engine screenshots")
    b.add_argument("--width", type=int, default=1280)
    b.add_argument("--height", type=int, default=720)
    b.add_argument("--wait", type=int, default=300)
    b.set_defaults(fn=cmd_build)

    s = sub.add_parser("shots")
    s.add_argument("map")
    s.add_argument("--cam", action="append", help='"x y z pitch yaw" (pitch>0 looks down; yaw 0=east, 90=north)')
    s.add_argument("--width", type=int, default=1280)
    s.add_argument("--height", type=int, default=720)
    s.add_argument("--wait", type=int, default=300, help="frames to wait after loading before the snapshot")
    s.add_argument("--fire", action="append", help="targetname to trigger before the shot; '@doors' opens all doors")
    s.set_defaults(fn=cmd_shots)

    v = sub.add_parser("preview")
    v.add_argument("map")
    v.add_argument("--view", default="top", choices=["top", "x", "y"])
    v.add_argument("--cut", type=float)
    v.set_defaults(fn=cmd_preview)

    pl = sub.add_parser("play")
    pl.add_argument("map")
    pl.add_argument("--dev", action="store_true", help="developer mode + console log")
    pl.set_defaults(fn=cmd_play)

    t = sub.add_parser("tex")
    t.add_argument("pattern", nargs="?", default="")
    t.add_argument("--sheet", action="store_true")
    t.add_argument("--thumb", type=int, default=96)
    t.set_defaults(fn=cmd_tex)

    i = sub.add_parser("info")
    i.add_argument("map")
    i.set_defaults(fn=cmd_info)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
