"""Command line:  python -m hlmap <command> ...

  setup                                       download the SDHLT compilers into tools/sdhlt
  build <map> [--profile fast|normal|final] [--no-install] [--shots]
        maps/<map>.py -> build/<map>/<map>.map -> compile -> install -> previews
  preview <map> [--view top|x|y] [--cut N]    orthographic cutaway PNG (no compile)
  shots <map> [--cam "x y z pitch yaw"]... [--fire NAME|@doors]
                                              in-engine screenshots (uses CAMERAS by default)
  play <map>                                  launch Half-Life into the map
  tex <pattern> [--sheet]                     search textures (and render a contact sheet)
  verify <map>                                collision/visibility checks of the compiled BSP
                                              (also run by build; failures block install)
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
        from .checks import doorway_clearance, use_reach
        problems.extend(use_reach(m, level))
        problems.extend(doorway_clearance(m, level))
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
    print(res.budget_report())
    if res.pointfile:
        print("leak preview:", render(m, d / "leak.png", pointfile=res.pointfile))
    if not res.ok:
        sys.exit(1)
    if not a.no_verify and not run_verify(m, res.bsp):
        sys.exit("verify failed: not installing (use --no-verify to override)")
    if not a.no_install:
        from . import game
        print("installed:", game.install(res.bsp, a.map))
    if a.shots:
        a.cam, a.fire, a.only, a.console, a.log = None, None, None, None, False
        cmd_shots(a)


def _parse_cams(a):
    """[(name, camera)] from --cam, or the map's cameras (m.cameras set in build(), or a
    module-level CAMERAS). Cameras are (x, y, z, pitch, yaw[, fire_list]); a dict gives names."""
    if a.cam:
        return [(f"cam{i}", tuple(float(x) for x in c.replace(",", " ").split())) for i, c in enumerate(a.cam)]
    m, mod = build_map(a.map)
    cams = getattr(m, "cameras", None) or getattr(mod, "CAMERAS", None) or []
    items = list(cams.items()) if isinstance(cams, dict) else [(str(i), c) for i, c in enumerate(cams)]
    if a.only:
        wanted = set(a.only)
        items = [(n, c) for n, c in items if n in wanted]
    return items


def cmd_shots(a):
    from . import game
    named = _parse_cams(a)
    if not named:
        sys.exit("no cameras: pass --cam 'x y z pitch yaw' or define cameras in the map script")
    cams = [c for _, c in named]
    bsp = config.BUILD_DIR / a.map / f"{a.map}.bsp"
    if not bsp.exists():
        sys.exit(f"{bsp} not found; run build first")
    from .verify import Hulls
    hulls = Hulls(bsp)
    for name, cam in named:
        if hulls.contents(0, tuple(cam[:3])) != -1:
            print(f"WARNING: camera {name} at {tuple(cam[:3])} is inside solid geometry; its shot will be garbage")
    d = out_dir(a.map) / "shots"
    for name, _ in named:   # replace only the shots being retaken
        (d / f"{a.map}_{name}.png").unlink(missing_ok=True)
    pngs, log = game.screenshots(bsp, cams, d, prefix=f"{a.map}_", width=a.width, height=a.height,
                                 wait_frames=a.wait, fire=a.fire or (), console=a.console or ())
    if a.log:
        (out_dir(a.map) / "shots" / "console.log").write_text(log, encoding="utf-8")
    interesting = [l for l in log.splitlines()
                   if any(k in l.lower() for k in ("error", "warning", "missing", "couldn't", "can't",
                                                    "bad ", "overflow", "hlmap"))
                   and "_load.cfg" not in l and "_unload.cfg" not in l]
    for l in interesting:
        print("  console:", l)
    final = []
    for (name, cam), p in zip(named, pngs):
        dest = p.with_name(f"{a.map}_{name}.png")
        if dest != p:
            p.replace(dest)
        final.append(dest)
        print(f"shot {dest}  cam={cam}")
    if len(pngs) != len(cams):
        print(f"WARNING: expected {len(cams)} screenshots, got {len(pngs)}")


def run_verify(m, bsp_path, coverage_check=True):
    """Collision/visibility checks of a compiled BSP. Returns True if everything passed."""
    from .verify import HULL_NAMES, Hulls, coverage, invisible_walls, leaks_into_solid, progression
    level = getattr(m, "level", None)
    if level is None:
        print("verify: skipped (map has no Level to compare against)")
        return True
    h = Hulls(bsp_path)
    ok = True
    world_brushes = list(m.worldspawn.brushes) + [b for e in m.entities if e.classname == "func_detail"
                                                  for b in e.brushes]
    index = {}
    for b in world_brushes:
        lo, hi = b.bounds()
        for gx in range(int(lo[0] // 128), int(hi[0] // 128) + 1):
            for gy in range(int(lo[1] // 128), int(hi[1] // 128) + 1):
                index.setdefault((gx, gy), []).append(b)

    def solid_at(p):
        """Inside any brush of the world model (level geometry, caves, func_detail props)."""
        for b in index.get((int(p[0] // 128), int(p[1] // 128)), ()):
            if all(f.normal[0] * p[0] + f.normal[1] * p[1] + f.normal[2] * p[2] <= f.dist + 0.01 for f in b.faces):
                return True
        return False

    def box_hits_solid(p, lo, hi):
        """Does the box p+lo..p+hi touch a world-model brush? Uses each brush's planes pushed
        out by the box (what the compiler's clip hulls do): exact on faces, slightly
        generous at edges, so it never reports a false invisible wall."""
        seen = set()
        for gx in range(int((p[0] + lo[0]) // 128), int((p[0] + hi[0]) // 128) + 1):
            for gy in range(int((p[1] + lo[1]) // 128), int((p[1] + hi[1]) // 128) + 1):
                for b in index.get((gx, gy), ()):
                    if id(b) in seen:
                        continue
                    seen.add(id(b))
                    inside = True
                    for f in b.faces:
                        n = f.normal
                        # the box reaches this face's inner half-space iff its nearest corner does
                        near = sum(min(n[k] * lo[k], n[k] * hi[k]) for k in range(3))
                        if n[0] * p[0] + n[1] * p[1] + n[2] * p[2] + near > f.dist + 0.01:
                            inside = False
                            break
                    if inside:
                        return True
        return False

    for hull in (0, 1, 3):
        probs, n = leaks_into_solid(h, level.is_air, hull, tol=1.0, limit=0)
        if probs:
            ok = False
            print(f"verify FAIL hull {hull} ({HULL_NAMES[hull]}): {len(probs)} of {n} empty regions reach into solid")
            for p in probs[:6]:
                print(f"    near {p['at']}  region {p['bounds'][0]}..{p['bounds'][1]}"
                      f"{'  (next to playable space)' if p['touches_air'] else ''}")
        else:
            print(f"verify ok   hull {hull} ({HULL_NAMES[hull]}): {n} empty regions, none inside solid")
    for hull in (1, 3):
        probs, n = invisible_walls(h, level.is_air, hull, box_hits_solid)
        if n:
            ok = False
            print(f"verify FAIL hull {hull} ({HULL_NAMES[hull]}): {n} invisible walls (solid where the player fits):")
            for p in probs[:6]:
                print(f"    near {p['at']}  region {p['bounds'][0]}..{p['bounds'][1]}")
        else:
            print(f"verify ok   hull {hull} ({HULL_NAMES[hull]}): no invisible walls")
    checkpoints = level.checkpoints() + [(name, [(p[0], p[1], p[2] + 37)])
                                         for name, p in getattr(m, "checkpoints", [])]
    missing, log, never, reached = progression(h, checkpoints)
    for line in log:
        print(f"verify      progression: {line}")
    if missing:
        ok = False
        print(f"verify FAIL walkability: {len(missing)} places a player can't get to on foot "
              f"(steps <= 18, jumps <= 45, ladders, locked doors):")
        for name, pts in missing[:10]:
            print(f"    {name} near {tuple(round(c) for c in pts[0])}")
        if never:
            print(f"    locks never opened: {', '.join(never)}")
    else:
        print(f"verify ok   walkability: all {len(checkpoints)} checkpoints reachable on foot "
              f"({len(reached)} positions{', locks opened: ' + str(len(log)) if log else ''})")
    if coverage_check:
        missing, checked, total = coverage(h, world_brushes, level.is_air, solid_at)
        if missing:
            ok = False
            print(f"verify FAIL coverage: {total} of {checked} visible faces missing from the BSP (see-through):")
            for f in missing[:6]:
                print(f"    {f['texture']} at {f['at']} facing {f['normal']}")
        else:
            print(f"verify ok   coverage: all {checked} visible faces present")
    return ok


def cmd_verify(a):
    m, _ = build_map(a.map)
    bsp = config.BUILD_DIR / a.map / f"{a.map}.bsp"
    if not bsp.exists():
        sys.exit(f"{bsp} not found; run build first")
    if not run_verify(m, bsp):
        sys.exit(1)


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
    b.add_argument("--no-verify", action="store_true", help="skip collision/visibility checks")
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
    s.add_argument("--only", action="append", help="only these named cameras")
    s.add_argument("--console", action="append", help='console command before loading, e.g. "developer 2"')
    s.add_argument("--log", action="store_true", help="save the game console log to shots/console.log")
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

    ve = sub.add_parser("verify")
    ve.add_argument("map")
    ve.set_defaults(fn=cmd_verify)

    i = sub.add_parser("info")
    i.add_argument("map")
    i.set_defaults(fn=cmd_info)

    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()
