"""Command line:  python -m hlmap <command> ...

  setup                                       download the SDHLT compilers into tools/sdhlt
  build <map> [<map>...] [--profile fast|normal|final] [--no-install] [--shots]
        maps/<map>.py -> build/<map>/<map>.map -> compile -> install -> previews
        (several maps: in campaign order, maps/campaign.py)
  preview <map> [--view top|x|y] [--cut N]    orthographic cutaway PNG (no compile)
  shots <map> [--cam "x y z pitch yaw"]... [--fire NAME|@doors]
                                              in-engine screenshots (uses CAMERAS by default)
  play <map>                                  launch Half-Life into the map
  playtest <map> --pickups | --links | --at "x y z yaw" --script "..."
                                              scripted play in the real game
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
    root = str(config.MAPS_SRC_DIR.parent)     # map scripts may import shared parts (maps.campaign)
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location(f"maps.{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if not hasattr(mod, "build"):
        sys.exit(f"{path} has no build(): not a map (shared code for maps lives there too)")
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
    """Build each map in turn (in campaign order when several are named, so each one
    is verified with how players arrive from the one before)."""
    from .setup import installed
    if not installed():
        sys.exit("SDHLT compilers missing: run  python -m hlmap setup")
    maps = list(a.map)
    if len(maps) > 1:
        from .campaign import order
        rank = {n: i for i, n in enumerate(order())}
        maps.sort(key=lambda n: rank.get(n, len(rank)))
    for name in maps:
        if len(maps) > 1:
            print(f"==================== {name}")
        a1 = argparse.Namespace(**{**vars(a), "map": name})
        _build_one(a1)


def _build_one(a):
    from .compile import compile_map
    from .preview import render
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
            for br in e.brushes:          # furniture, lights, wall art reaching into a cut-off corner
                lo, hi = br.bounds()
                zc = (lo[2] + hi[2]) / 2
                c = tuple((a_ + b_) / 2 for a_, b_ in zip(lo, hi))
                r = next((level.in_cut((x, y, zc)) for x in (lo[0] + 1, hi[0] - 1) for y in (lo[1] + 1, hi[1] - 1)
                          if level.in_cut((x, y, zc))), None)
                if r is not None:
                    problems.append(f"{e.classname} {br.comment or ''} at {tuple(round(v) for v in c)} is in the "
                                    f"cut-off corner of room {r.name} (solid now)")
    if problems:
        print("MAP PROBLEMS:\n  " + "\n  ".join(problems))
        if any("degenerate" in p or "not in any WAD" in p for p in problems):
            sys.exit(1)
    for note in (getattr(level, "notes", None) or []):
        print("level:", note)
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
        files = m.content_files(d)
        print("installed:", str(game.install(res.bsp, a.map, files=files))
              + (f" (+{len(files)} files: sounds, {a.map}.res)" if files else ""))
        for target in sorted({e.get("map") for e in m.find("trigger_changelevel")}):
            if not (config.GAME_DIR / "maps" / f"{target}.bsp").exists():
                print(f"note: {a.map} leads to {target}, which isn't installed yet (build {target} too)")
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


def cmd_playtest(a):
    """Play the map in the real game from a scripted start (see game.playtest), or with
    --pickups walk straight at every item from the directions verify uses and check the
    game picks it up."""
    from . import game
    bsp = config.BUILD_DIR / a.map / f"{a.map}.bsp"
    if not bsp.exists():
        sys.exit(f"{bsp} not found; run build first")
    d = out_dir(a.map) / "playtest"
    if a.pickups:
        from .verify import Hulls, Walker, _placed, item_rest, pickup_approaches
        h = Hulls(bsp)
        ents = h.entities
        w = Walker(h, [_placed(h.models(), e) for e in ents if e.get("classname") == "func_ladder"])
        start = next(e for e in ents if e.get("classname") == "info_player_start")
        comp = w.flood([w.settle(tuple(float(c) for c in start["origin"].split()))])   # doors open
        tests, expect = [], {}
        for e in ents:
            if e.get("classname", "").startswith(("item_", "weapon_", "ammo_")) and e.get("origin"):
                o = tuple(float(c) for c in e["origin"].split())
                for sector, p, touched, _ in pickup_approaches(h, comp, item_rest(h, o)):
                    label = f"{e['classname']} at {tuple(round(c) for c in o)} from {sector}"
                    tests.append((label, (p[0], p[1], p[2] - 36), o))
                    expect[label] = touched
        if not tests:
            sys.exit("no items with open ground around them")
        got, log = game.playtest_pickups(bsp, tests, d)
        (d / "console.log").write_text(log, encoding="utf-8")
        agree = 0
        for label, picked in got.items():
            same = picked == expect[label]
            agree += same
            print(f"{'ok  ' if same else 'DIFF'} {label}: game {'picked it up' if picked else 'did NOT pick it up'}"
                  f"{'' if same else ' (verify expected the opposite)'}")
        print(f"{agree} of {len(got)} approaches agree with verify's model")
        return
    if a.links:
        _playtest_links(a, bsp, d)
        return
    if a.teleports:
        _playtest_teleports(a, bsp, d)
        return
    if not a.at:
        sys.exit('pass --pickups, --links, or --at "x y feet_z yaw" with --do steps')
    start = tuple(float(c) for c in a.at.split())
    steps = list(a.do or []) + [x.strip() for x in (a.script or "").split(";") if x.strip()]
    script = [int(s) if s.isdigit() else s for s in steps]
    pngs, log = game.playtest(bsp, start, script, d, fire=a.fire or ())
    (d / "console.log").write_text(log, encoding="utf-8")
    after = log[log.find("HLMAP_PLAY_START"):] if "HLMAP_PLAY_START" in log else ""
    for line in after.splitlines():
        if line.startswith(("Firing:", "Found:")) or "error" in line.lower():
            print("  console:", line)
    for p in pngs:
        print(f"shot {p}")


def _playtest_links(a, bsp, d):
    """Walk into every trigger_changelevel in the real game: start on open ground a
    little before it, hold forward, and check the game arrived in the other map; the
    picture (build/<map>/playtest/link_<target>_window.png) shows where the player landed."""
    import math
    from . import game
    from .campaign import changelevels
    from .verify import HALF, Hulls, Walker, _placed, straight_walk, touches_box
    h = Hulls(bsp)
    w = Walker(h, [_placed(h.models(), e) for e in h.entities if e.get("classname") == "func_ladder"])
    start = next(e for e in h.entities if e.get("classname") == "info_player_start")
    pos0 = w.settle(tuple(float(c) for c in start["origin"].split()))
    links = changelevels(h)
    if not links:
        sys.exit("no trigger_changelevel in this map")
    for target, lm, (lo, hi) in links:
        mid = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        # the side players come from: reachable from the start (doors open) without
        # crossing the trigger; open ground 96-160 units from it, from which walking
        # straight at it gets there
        w.blockers = [(tuple(lo[k] - HALF[k] for k in range(3)), tuple(hi[k] + HALF[k] for k in range(3)))]
        comp = w.flood([pos0])
        best = None
        for p in sorted(comp, key=lambda p: abs(math.hypot(p[0] - mid[0], p[1] - mid[1]) - 128)):
            if not 96 <= math.hypot(p[0] - mid[0], p[1] - mid[1]) <= 160:
                continue
            if straight_walk(h, p, mid, lambda q: touches_box(q, lo, hi))[0]:
                best = p
                break
        if best is None:
            print(f"to {target}: no open ground to walk into the trigger from")
            continue
        yaw = math.degrees(math.atan2(mid[1] - best[1], mid[0] - best[0]))
        at = (best[0], best[1], best[2] - 36, round(yaw))
        print(f"to {target} ({lm}): walking in from {tuple(round(c) for c in best[:2])}, facing {round(yaw)}")
        pngs, log = game.playtest_transition(bsp, at, target, d, prefix=f"link_{target}_")
        (d / f"link_{target}.log").write_text(log, encoding="utf-8")
        after = log[log.find("HLMAP_PLAY_START"):] if "HLMAP_PLAY_START" in log else ""
        changed = next((line.strip() for line in after.splitlines() if line.startswith("CHANGE LEVEL")), None)
        arrived = f"HLMAP_ARRIVED {target}" in after
        if changed:
            print("  console:", changed)
        for line in after.splitlines():      # (a first visit's "couldn't open" save lookups are normal)
            if any(k in line.lower() for k in ("landmark", "transition", "overflow")):
                print("  console:", line.strip())
        print(f"  {'ok  ' if arrived else 'FAIL'} " + (f"arrived in {target}" if arrived else
                                                      "the game started to change level but never arrived" if changed
                                                      else "the game did NOT change level"))
        for p in pngs:
            print(f"  shot {p}")


def _playtest_teleports(a, bsp, d):
    """Walk onto every trigger_teleport in the real game (from open ground in front of
    it, with --fire first, e.g. to power a network) and snapshot where it puts you."""
    import math
    from . import game
    from .verify import (Hulls, Walker, _placed, solid_entities, straight_walk, teleports)
    h = Hulls(bsp)
    w = Walker(h, [_placed(h.models(), e) for e in h.entities if e.get("classname") == "func_ladder"],
               solids=solid_entities(h))
    tele = teleports(h)
    if not tele:
        sys.exit("no trigger_teleport in this map")
    w.teleports = [(box, w.settle(land)) for _, box, land, _ in tele if land]     # all on, to get everywhere
    start = next(e for e in h.entities if e.get("classname") == "info_player_start")
    comp = w.flood([w.settle(tuple(float(c) for c in start["origin"].split()))])
    if any(h.entities[i].get("master") for i, _, _, _ in tele) and not a.fire:
        print("note: these teleporters have a master; pass --fire to switch them on first (e.g. --fire transit_start)")
    for i, (lo, hi), land, target in tele:
        mid = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        touching = lambda q, lo=lo, hi=hi: all(lo[k] <= q[k] <= hi[k] for k in range(3))
        best = None
        for p in sorted(comp, key=lambda p: abs(math.hypot(p[0] - mid[0], p[1] - mid[1]) - 96)):
            if 72 <= math.hypot(p[0] - mid[0], p[1] - mid[1]) <= 160 and w.teleport_at(p) is None \
                    and straight_walk(h, p, mid, touching)[0]:
                best = p
                break
        if best is None:
            print(f"teleporter to {target}: no open ground to walk onto it from")
            continue
        yaw = round(math.degrees(math.atan2(mid[1] - best[1], mid[0] - best[0])))
        print(f"teleporter to {target}: walking on from {tuple(round(c) for c in best[:2])}, "
              f"should land at {tuple(round(c) for c in land) if land else '?'}")
        pngs, log = game.playtest(bsp, (best[0], best[1], best[2] - 36, yaw), ["+forward", 30, "-forward", 150], d,
                                  fire=a.fire or (), prefix=f"teleport_{target}_")
        (d / f"teleport_{target}.log").write_text(log, encoding="utf-8")
        for p in pngs:
            print(f"  shot {p}")


def run_verify(m, bsp_path, coverage_check=True):
    """Collision/visibility checks of a compiled BSP. Returns True if everything passed."""
    from .verify import (DARK_LIMIT, HULL_NAMES, FloorLight, Hulls, coverage, invisible_walls, item_rest,
                         leaks_into_solid, pickup_approaches, progression)
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
    from . import campaign
    exits = {(target, lm): b for target, lm, b in campaign.changelevels(h)}
    checkpoints = level.checkpoints() + [(name, [(p[0], p[1], p[2] + 37)])
                                         for name, p in getattr(m, "checkpoints", [])]
    # every way out must be reachable (the middle of its floor)
    checkpoints += [(f"way to {target}", [((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] + 37)])
                    for (target, _), (lo, hi) in exits.items()]
    light = FloorLight(h.bsp) if h.bsp.lumps["lighting"] else None
    # arriving from an earlier map of the campaign: start where the player lands, with
    # the global states they can bring (one run per distinct state this map reads)
    runs = [("", None, None)]
    arrivals = campaign.entries(m.name)
    if arrivals is None:
        earlier = campaign.order()[:campaign.order().index(m.name)]
        print(f"verify WARN campaign: {', '.join(earlier)} not verified yet, so how players arrive here is "
              "unknown; checking from the player start with the map's own starting state")
    elif arrivals:
        read = {e["globalstate"] for e in h.entities if e.get("globalstate")}
        seen = {}
        for prev, lm, glob, pos in arrivals:
            key = tuple(sorted((g, glob.get(g, 0)) for g in read))
            seen.setdefault(key, (prev, lm, glob, pos))
        runs = []
        brought = {g for a in arrivals for g in a[2]}
        for key, (prev, lm, glob, pos) in seen.items():
            state = ", ".join(f"{g} {'on' if v == 1 else 'off'}" for g, v in key
                              if g in brought and not g.endswith("_not"))
            runs.append((f"from {prev}{': ' + state if state else ''}", glob, pos))
        print(f"verify      campaign: players arrive from {', '.join(sorted({a[0] for a in arrivals}))} "
              f"in {len(arrivals)} global state(s), {len(runs)} different for this map")
        carried = set(campaign.carried(m.name))
        mine = {e["globalstate"] for e in h.entities if e.get("classname") == "env_global" and e.get("globalstate")}
        for g in sorted(read & brought - carried - {f"{c}_not" for c in carried}):
            print(f"verify WARN campaign: this map reads global state {g!r}, which "
                  f"{'both maps set' if g in mine else 'comes from the previous map'}, but no link "
                  "carries it: its value on arrival wasn't explored (list it in the Link's carries, or rename "
                  "it if the maps mean different things by it)")
    reached, found, tele_report = set(), {}, []
    for k, (label, glob, start) in enumerate(runs):
        prog = progression(h, checkpoints, light=light, globals=glob, start=start, exits=exits,
                           watch=campaign.carried(m.name))
        reached |= prog.reached
        for key, states in prog.exits.items():
            have = found.setdefault(key, [])
            have += [s for s in states if s[0] not in [x[0] for x in have]]
        tag = f" [{label}]" if label else ""
        if k == 0:
            tele_report = prog.teleports
            if label:
                print(f"verify      arriving {label}:")
            for i, line in enumerate(prog.log, 1):
                print(f"verify      progression {i}. {line}")
            for wmsg in prog.warnings:
                print(f"verify WARN logic: {wmsg}")
        if prog.missing:
            ok = False
            print(f"verify FAIL walkability{tag}: {len(prog.missing)} places a player can't get to on foot "
                  f"(steps <= 18, jumps <= 45, ladders, locked doors):")
            for name, pts in prog.missing[:10]:
                print(f"    {name} near {tuple(round(c) for c in pts[0])}")
            if prog.never:
                print(f"    locks never opened: {', '.join(prog.never)}")
        else:
            print(f"verify ok   walkability{tag}: all {len(checkpoints)} checkpoints reachable on foot "
                  f"({len(prog.reached)} positions, {prog.states} states of play"
                  f"{', truncated' if prog.truncated else ''})")
        if prog.softlocks:
            ok = False
            print(f"verify FAIL lockout{tag}: {len(prog.softlocks)} lines of play leave areas unreachable for good, "
                  "e.g.:")
            for path, lost in prog.softlocks[:3]:
                print(f"    after: {' / '.join(path) or '(start)'}")
                print(f"      lost: {', '.join(lost)}")
        elif len(prog.log) > 0:
            print(f"verify ok   lockout{tag}: no order of play locks the player out ({prog.states} states)")
        if light is not None and prog.darkness:
            worst = max(prog.darkness, key=lambda d: d[2])
            dark = [d for d in prog.darkness if d[2] > DARK_LIMIT]
            if dark:
                ok = False
                print(f"verify FAIL darkness{tag}: the way forward crosses more than {DARK_LIMIT} units the player "
                      f"can't see in (no flashlight without the HEV suit):")
                for path, goal, cost in dark[:3]:
                    print(f"    after: {' / '.join(path) or '(start)'}")
                    print(f"      to {goal}: {cost} units in the dark")
            else:
                print(f"verify ok   darkness{tag}: every way forward is lit (worst {worst[2]} units in the dark, "
                      f"after {len(worst[0])} step{'s' if len(worst[0]) != 1 else ''}, "
                      f"to {worst[1].split(' -> ')[0]})")
    from .verify import teleport_landings
    bad, n_tele = teleport_landings(h)
    for name, problem in bad:
        ok = False
        print(f"verify FAIL teleport: {name} {problem}")
    if n_tele and not bad:
        print(f"verify ok   teleport: all {n_tele} teleporters put the player down standing, clear of the others")
    for name, back, lost in tele_report:
        if lost:
            ok = False
            print(f"verify FAIL teleport: {name} is one-way and strands the player: can't reach {', '.join(lost)}")
        elif not back:
            print(f"verify WARN teleport: {name} is one-way (no way back to where it was stepped on)")
    if tele_report and all(back for _, back, _ in tele_report):
        print(f"verify ok   teleport: every trip has a way back ({len(tele_report)} teleporters, all on)")
    if exits:
        campaign.save_exits(m.name, h, found, reached)
        for (target, lm), states in found.items():
            names = {g for glob, _, _ in states for g in glob if not g.endswith("_not")}
            differ = sorted(g for g in names if len({s[0].get(g, 0) for s in states}) > 1)
            print(f"verify ok   exit to {target} ({lm}): the player can leave in {len(states)} global state(s)"
                  + (f", differing in {', '.join(differ)}" if differ else ""))
    ok = _verify_links(m.name, h, reached) and ok
    prog.reached = reached
    items = [e for e in h.entities if e.get("classname", "").startswith(("item_", "weapon_", "ammo_"))
             and e.get("origin")]
    for e in items:
        # walk straight at it from the open ground around it, as a player who spots it does
        rest = item_rest(h, tuple(float(c) for c in e["origin"].split()))
        tries = pickup_approaches(h, prog.reached, rest)
        good = [t for t in tries if t[2]]
        bad = [t for t in tries if not t[2]]
        what = f"{e['classname']} at {tuple(round(c) for c in rest)}" + (f" -> {e['target']}" if e.get("target") else "")
        if not tries:
            print(f"verify WARN pickup: {what}: no open ground within 72-104 units to approach it from")
        elif len(bad) >= len(good):
            if e.get("target"):
                ok = False
            print(f"verify {'FAIL' if e.get('target') else 'WARN'} pickup: {what}: walking straight at it works "
                  f"from {len(good)} of {len(tries)} directions:")
            for sector, start, _, blocked in bad:
                print(f"    from {sector} {tuple(round(c) for c in start)}: stopped "
                      + (f"by solid at {blocked}" if blocked else "short of it (too far from the edge)"))
        else:
            print(f"verify ok   pickup: {what}: reached walking straight at it from "
                  f"{', '.join(t[0] for t in good)}" + (f" (not {', '.join(t[0] for t in bad)})" if bad else ""))
    decals = [e for e in h.entities if e.get("classname") == "infodecal" and e.get("origin")]
    if decals:
        # the game traces +-5 units from a decal's origin; nothing solid there = no decal
        floating = []
        for e in decals:
            o = tuple(float(c) for c in e["origin"].split())
            if not any(h.contents(0, tuple(o[k] + (s if k == axis else 0) for k in range(3))) == -2
                       for axis in range(3) for s in (-4, 4)):
                floating.append((e.get("texture"), tuple(round(c) for c in o)))
        if floating:
            ok = False
            print(f"verify FAIL decals: {len(floating)} of {len(decals)} are not on a surface (they won't show):")
            for tex, o in floating[:6]:
                print(f"    {tex} at {o}")
        else:
            print(f"verify ok   decals: all {len(decals)} sit on a surface")
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


def _verify_links(name, h, reached):
    """Level changes out of `name` and into it from other compiled maps (see
    campaign.check_transition). Returns True unless a transition is broken."""
    from . import campaign
    from .verify import Hulls
    ok = True
    out = {t for t, _, _ in campaign.changelevels(h)}
    for other in sorted((out | set(campaign.order())) - {name}):
        bsp = config.BUILD_DIR / other / f"{other}.bsp"
        if not bsp.exists():
            if other in out:
                print(f"verify WARN campaign: {name} leads to {other}, which isn't built yet (not checked)")
            continue
        ho = Hulls(bsp)
        pairs = [(h, ho, name, other, reached)] if other in out else []
        if any(t == name for t, _, _ in campaign.changelevels(ho)):
            touch = campaign.touched_from(other, name)
            if touch is None:
                print(f"verify WARN campaign: verify {other} to check its way into {name}")
            else:
                pairs.append((ho, h, other, name, touch))
        for ha, hb, an, bn, r in pairs:
            problems, warnings, notes = campaign.check_transition(ha, hb, an, bn, r)
            for p in problems:
                print(("verify FAIL transition: " if not p.startswith("    ") else "") + p)
            for w in warnings:
                print(f"verify WARN transition: {w}")
            for n in notes:
                print(f"verify ok   transition: {n}")
            ok = ok and not problems
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
    b.add_argument("map", nargs="+", help="one or more maps (several: built in campaign order)")
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

    pt = sub.add_parser("playtest", help="play the map in the real game from a scripted start")
    pt.add_argument("map")
    pt.add_argument("--pickups", action="store_true", help="walk straight at every item; check it's picked up")
    pt.add_argument("--links", action="store_true", help="walk into every level change; check the next map loads")
    pt.add_argument("--teleports", action="store_true", help="walk onto every teleporter; snapshot the landing")
    pt.add_argument("--at", help='"x y feet_z yaw" player start')
    pt.add_argument("--fire", action="append", help="targetname to trigger first (as for shots)")
    pt.add_argument("--do", action="append", help='a console command ("+forward") or frames to wait ("60"); '
                    'use --do=-forward for commands starting with -')
    pt.add_argument("--script", help='steps separated by ";", e.g. "+forward; 150; -forward; 300"')
    pt.set_defaults(fn=cmd_playtest)

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
