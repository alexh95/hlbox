"""Install compiled maps into Half-Life, launch the game, take in-engine screenshots.

Screenshots: for each camera a temporary copy of the BSP is written to
valve/maps/hlmap_camN.bsp whose entity lump gets a trigger_camera (fired by a
trigger_auto) at the camera pose. A generated cfg loads each copy, waits, runs
`snapshot`, then quits. The BMPs are converted to PNG and all temp files removed.
The user's Half-Life video settings (registry) are restored afterwards.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config
from .bsp import BSP

MANIFEST = config.BUILD_DIR / "installed.json"
REG_KEY = r"Software\Valve\Half-Life\Settings"
REG_VALUES = ("ScreenWindowed", "DisplayWidth", "DisplayHeight", "ScreenWidth", "ScreenHeight",
              "ScreenBPP", "DisplayBPP")


# ---------------------------------------------------------------- install

def _manifest():
    try:
        return set(json.loads(MANIFEST.read_text()))
    except (OSError, ValueError):
        return set()


def install(bsp_path, name=None, force=False, files=None):
    """Copy a BSP to valve/maps/, plus the map's other files ({path under valve/:
    source}, e.g. sounds and its .res). Refuses to overwrite anything it didn't
    install (stock maps, other content); files it installed for this map earlier
    and that are no longer part of it are removed."""
    bsp_path = Path(bsp_path)
    name = name or bsp_path.stem
    dest = config.GAME_DIR / "maps" / f"{name}.bsp"
    owned = _manifest()
    files = {str(k).replace("\\", "/"): Path(v) for k, v in (files or {}).items()}
    for rel in [f"maps/{name}.bsp"] + list(files):
        target = config.GAME_DIR / rel
        key = name if rel == f"maps/{name}.bsp" else rel
        if target.exists() and key not in owned and not force:
            raise FileExistsError(f"{target} exists and was not installed by hlmap; pick another map name")
    shutil.copy2(bsp_path, dest)
    owned.add(name)
    for rel, src in files.items():
        target = config.GAME_DIR / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        owned.add(rel)
    # this map's own content from earlier installs that it no longer uses
    mine = (f"sound/hlbox/{name}/", f"maps/{name}.res")
    for rel in sorted(o for o in owned if o.startswith(mine) and o not in files):
        (config.GAME_DIR / rel).unlink(missing_ok=True)
        owned.discard(rel)
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(sorted(owned)))
    return dest


# ---------------------------------------------------------------- process helpers

def hl_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq hl.exe", "/NH"], capture_output=True, text=True).stdout
    return "hl.exe" in out.lower()


def _reg_snapshot():
    import winreg
    vals = {}
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY) as k:
            for n in REG_VALUES:
                try:
                    vals[n] = winreg.QueryValueEx(k, n)
                except FileNotFoundError:
                    vals[n] = None
    except FileNotFoundError:
        pass
    return vals


def _reg_restore(before):
    """Put back the user's video settings if the game rewrote them."""
    import winreg
    if not before:
        return []
    changed = []
    now = _reg_snapshot()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as k:
        for n, v in before.items():
            if now.get(n) != v:
                if v is None:
                    try:
                        winreg.DeleteValue(k, n)
                    except FileNotFoundError:
                        pass
                else:
                    winreg.SetValueEx(k, n, 0, v[1], v[0])
                changed.append(n)
    return changed


def launch(mapname, extra_args=(), windowed=True, width=None, height=None, dev=False):
    """Start Half-Life straight into a map (does not wait)."""
    args = [str(config.HL_DIR / "hl.exe"), "-game", "valve", "-novid"]
    if windowed:
        args.append("-windowed")
    if width and height:
        args += ["-w", str(width), "-h", str(height)]
    if dev:
        args += ["-dev", "-condebug"]
    # The first map of a session spawns before the game has read skill.cfg (its sk_*
    # settings only exist once a server runs), so every NPC gets 0 health and breaks
    # after one scripted_sequence. Load, read skill.cfg, then load again.
    args += list(extra_args) + ["+map", mapname, "+exec", "skill.cfg", "+map", mapname]
    return subprocess.Popen(args, cwd=str(config.HL_DIR))


# ---------------------------------------------------------------- screenshots

def _camera_entities(cam):
    """Entities that force the view to a camera pose. cam = (x, y, z, pitch, yaw);
    pitch > 0 looks down."""
    x, y, z, pitch, yaw = cam
    p, yw = math.radians(pitch), math.radians(yaw)
    fwd = (math.cos(p) * math.cos(yw), math.cos(p) * math.sin(yw), -math.sin(p))
    look = (x + fwd[0] * 256, y + fwd[1] * 256, z + fwd[2] * 256)
    f = lambda v: " ".join(f"{c:.2f}" for c in v)
    return [
        {"classname": "trigger_camera", "targetname": "hlmap_cam", "origin": f((x, y, z)),
         "angles": f"{pitch} {yaw} 0", "target": "hlmap_look", "wait": "3600", "spawnflags": "4"},
        {"classname": "info_target", "targetname": "hlmap_look", "origin": f(look)},
        {"classname": "trigger_auto", "target": "hlmap_cam", "triggerstate": "1", "delay": "0.1",
         "spawnflags": "1", "origin": f((x, y, z))},
    ]


def _fire_entities(ents, fire, origin):
    """trigger_autos that fire `fire` after spawn: names in order 0.3 s apart, or
    (name, seconds). '@doors' opens every door and keeps it open."""
    extra = []
    for name in fire:
        if name == "@doors":   # open every door (temporarily named so a trigger can reach it)
            for e in ents:
                if e.get("classname") in ("func_door", "func_door_rotating"):
                    e.setdefault("targetname", "hlmap_doors")
                    e["wait"] = "-1"   # stay open for the snapshot
                    if e["targetname"] not in fire:
                        extra.append(e["targetname"])
            continue
        extra.append(name)
    extra = list(dict.fromkeys(tuple(x) if isinstance(x, list) else x for x in extra))
    out = []
    for i, item in enumerate(extra):
        name, delay = item if isinstance(item, tuple) else (item, 0.3 * (i + 1))
        # triggerstate 2 = toggle, like pressing a switch (lights ignore "on" when already on)
        out.append({"classname": "trigger_auto", "target": name, "triggerstate": "2",
                    "delay": f"{delay:.1f}", "spawnflags": "1",
                    "origin": " ".join(f"{c:.1f}" for c in origin)})
    return out


def _cam_variant(bsp_path, cam, dest, fire=()):
    b = BSP(bsp_path)
    ents = b.entities
    x, y, z, pitch, yaw = cam[:5]
    fire = list(fire) + list(cam[5] if len(cam) > 5 else ())
    triggers = _fire_entities(ents, fire, (x, y, z))
    # park the player just behind the camera so its model stays out of view
    back = (x - math.cos(math.radians(yaw)) * 24, y - math.sin(math.radians(yaw)) * 24, z - 28)
    for e in ents:
        if e.get("classname") == "info_player_start":
            e["origin"] = " ".join(f"{c:.1f}" for c in back)
            e["angles"] = f"0 {yaw} 0"
    b.entities = ents + triggers + _camera_entities(cam[:5])
    b.save(dest)


def _waits(frames):
    """Console commands that wait `frames` frames (aliases defined by _run_session)."""
    return ["hlm_w100"] * (frames // 100) + ["hlm_w10"] * (frames % 100 // 10) + ["wait"] * (frames % 10)


def _run_session(variants, script, out_dir, prefix, width=1280, height=720, timeout=120, console=()):
    """Run Half-Life windowed on temporary map variants ({name: (source_bsp, write_fn)},
    write_fn(dest) writes the variant) and a console `script` (lines; ints = frames to
    wait). Returns (png paths of the snapshots taken, console log text)."""
    from PIL import Image

    if hl_running():
        raise RuntimeError("Half-Life is already running; close it first")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    maps_dir = config.GAME_DIR / "maps"
    for name, write in variants.items():
        write(maps_dir / f"{name}.bsp")
    waits = "wait;" * 10
    first = next(iter(variants))       # warm-up load so skill.cfg is read (see launch())
    cfg = [f'alias hlm_w10 "{waits}"', 'alias hlm_w100 "' + "hlm_w10;" * 10 + '"', f"map {first}",
           "hlm_w10", "exec skill.cfg"] + list(console)
    for line in script:
        cfg += _waits(line) if isinstance(line, int) else [line]
    cfg += ["echo HLMAP_DONE", "quit"]
    cfg_path = config.GAME_DIR / "hlmap_shot.cfg"
    cfg_path.write_text("\n".join(cfg) + "\n")

    t_start = time.time()
    before_bmps = set(config.GAME_DIR.glob("*.bmp"))
    reg = _reg_snapshot()
    log_paths = [config.HL_DIR / "qconsole.log", config.GAME_DIR / "qconsole.log"]
    log_offsets = {p: (p.stat().st_size if p.exists() else 0) for p in log_paths}
    args = [str(config.HL_DIR / "hl.exe"), "-game", "valve", "-windowed", "-w", str(width), "-h", str(height),
            "-condebug", "-nojoy", "-novid", "+exec", "hlmap_shot.cfg"]
    env = dict(os.environ, SteamNoOverlayUIDrawing="1")   # keep Steam toasts out of the shots
    proc = subprocess.Popen(args, cwd=str(config.HL_DIR), env=env)
    try:
        deadline = time.time() + timeout
        time.sleep(3)
        while time.time() < deadline and (proc.poll() is None or hl_running()):
            time.sleep(1)
        timed_out = time.time() >= deadline
        if timed_out:
            subprocess.run(["taskkill", "/IM", "hl.exe", "/F"], capture_output=True)
            time.sleep(2)
    finally:
        restored = _reg_restore(reg)
        for name in variants:
            (maps_dir / f"{name}.bsp").unlink(missing_ok=True)
        cfg_path.unlink(missing_ok=True)

    log = ""
    for p in log_paths:
        if p.exists() and p.stat().st_size != log_offsets[p]:
            with open(p, "rb") as fh:
                fh.seek(log_offsets[p] if p.stat().st_size > log_offsets[p] else 0)
                log += fh.read().decode("latin-1", errors="replace")
    new_bmps = sorted((p for p in config.GAME_DIR.glob("*.bmp")
                       if p not in before_bmps and p.stat().st_mtime >= t_start - 1),
                      key=lambda p: p.stat().st_mtime)
    pngs = []
    for i, bmp in enumerate(new_bmps):
        png = out_dir / f"{prefix}{i}.png"
        Image.open(bmp).convert("RGB").save(png)
        bmp.unlink()
        pngs.append(png)
    if timed_out:
        log += "\n[hlmap] timed out waiting for Half-Life; killed it\n"
    if restored:
        log += f"\n[hlmap] restored registry video settings: {restored}\n"
    return pngs, log


def screenshots(bsp_path, cameras, out_dir, prefix="shot", width=1280, height=720,
                wait_frames=300, timeout=120, fire=(), console=()):
    """Render in-engine screenshots. cameras: list of (x, y, z_eye, pitch, yaw[, fire_list]).
    fire: targetnames to trigger ~0.3s after spawn ('@doors' = open all doors; triggered
    two-way doors swing away from the camera). console: extra console commands run before
    the first map (e.g. "developer 2"). Returns (png_paths, console_log_text)."""
    names = [f"hlmap_cam{i}" for i in range(len(cameras))]
    variants = {n: (lambda dest, cam=cam: _cam_variant(bsp_path, cam, dest, fire)) for n, cam in zip(names, cameras)}
    script = []
    for i, n in enumerate(names):
        settle = wait_frames + (400 if i == 0 else 0)    # first load: let startup toasts fade
        script += [f"map {n}", settle, "snapshot", f"echo HLMAP_SHOT {n}"]
    return _run_session(variants, script, out_dir, prefix, width, height,
                        max(timeout, 40 + 12 * len(cameras)), console)


def playtest(bsp_path, start, script, out_dir, fire=(), prefix="play", width=1280, height=720,
             timeout=90, console=("developer 2",)):
    """Play the map in the real game from a scripted start: the player spawns at
    start = (x, y, feet_z, yaw[, pitch]), `fire` is triggered first (as for cameras), then
    `script` runs: console commands and frame waits, e.g.
        ["+forward", 60, "-forward", "+use", 5, "-use", "snapshot"]
    (at the default 100 fps, 100 frames = 1 s; walking covers ~320 units/s).
    Returns (png paths, console log). With developer 2 the log shows everything that
    fired ("Firing: (name)"), e.g. whether an item was picked up."""
    x, y, z, yaw = start[:4]
    pitch = start[4] if len(start) > 4 else 0

    def write(dest):
        b = BSP(bsp_path)
        ents = b.entities
        for e in ents:
            if e.get("classname") == "info_player_start":
                e["origin"] = f"{x:.1f} {y:.1f} {z + 36:.1f}"
                e["angles"] = f"{pitch} {yaw} 0"
        b.entities = ents + _fire_entities(ents, fire, (x, y, z + 36))
        b.save(dest)

    lines = ["map hlmap_play", 150, "echo HLMAP_PLAY_START"] + list(script) + [10, "snapshot", 10]
    return _run_session({"hlmap_play": write}, lines, out_dir, prefix, width, height, timeout, console)


def playtest_pickups(bsp_path, tests, out_dir, walk_frames=90, timeout=None):
    """Walk into items in the real game. tests: [(label, start, item_origin)] with
    start = (x, y, feet_z) of the player; each test is its own map load: the player
    spawns at start facing the item, holds forward for `walk_frames`, and the item
    (found by its origin) fires a probe target when picked up. The item is tested as an
    item_security: same touch box, but no "does the player need it" rule.
    Returns ({label: picked up}, console log)."""
    variants, script = {}, []
    for i, (label, start, item) in enumerate(tests):
        x, y, z = start
        yaw = math.degrees(math.atan2(item[1] - y, item[0] - x))

        def write(dest, x=x, y=y, z=z, yaw=yaw, item=item, i=i):
            b = BSP(bsp_path)
            ents = b.entities
            for e in ents:
                if e.get("classname") == "info_player_start":
                    e["origin"] = f"{x:.1f} {y:.1f} {z + 36:.1f}"
                    e["angles"] = f"0 {yaw:.1f} 0"
                o = e.get("origin")
                if o and e.get("classname", "").startswith(("item_", "weapon_", "ammo_")) and \
                        all(abs(float(a) - b) < 0.5 for a, b in zip(o.split(), item)):
                    e["target"] = f"hlmap_got{i}"
                    # same 32x32x16 touch box as every item, but always taken (a medkit
                    # is refused at full health, a battery without the suit...)
                    e["classname"] = "item_security"
            b.entities = ents + [{"classname": "info_target", "targetname": f"hlmap_got{i}",
                                  "origin": " ".join(o for o in ents[0].get("origin", "0 0 0").split())}]
            b.save(dest)

        variants[f"hlmap_pick{i}"] = write
        script += [f"map hlmap_pick{i}", 150 if i else 450, "+forward", walk_frames, "-forward", 20,
                   f"echo HLMAP_PICK {i} done"]
    _, log = _run_session(variants, script, out_dir, "pick", timeout=timeout or 40 + 10 * len(tests),
                          console=("developer 2",))
    return {label: f"Firing: (hlmap_got{i})" in log for i, (label, _, _) in enumerate(tests)}, log
