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


def install(bsp_path, name=None, force=False):
    """Copy a BSP to valve/maps/. Refuses to overwrite maps it didn't install (stock maps)."""
    bsp_path = Path(bsp_path)
    name = name or bsp_path.stem
    dest = config.GAME_DIR / "maps" / f"{name}.bsp"
    owned = _manifest()
    if dest.exists() and name not in owned and not force:
        raise FileExistsError(f"{dest} exists and was not installed by hlmap; pick another map name")
    shutil.copy2(bsp_path, dest)
    owned.add(name)
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
    args += list(extra_args) + ["+map", mapname]
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


def _cam_variant(bsp_path, cam, dest, fire=()):
    b = BSP(bsp_path)
    ents = b.entities
    x, y, z, pitch, yaw = cam[:5]
    fire = list(fire) + list(cam[5] if len(cam) > 5 else ())
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
    for i, name in enumerate(dict.fromkeys(extra)):   # fired in order, 0.3 s apart
        # triggerstate 2 = toggle, like pressing a switch (lights ignore "on" when already on)
        ents.append({"classname": "trigger_auto", "target": name, "triggerstate": "2",
                     "delay": f"{0.3 * (i + 1):.1f}", "spawnflags": "1", "origin": f"{x:.1f} {y:.1f} {z:.1f}"})
    # park the player just behind the camera so its model stays out of view
    back = (x - math.cos(math.radians(yaw)) * 24, y - math.sin(math.radians(yaw)) * 24, z - 28)
    for e in ents:
        if e.get("classname") == "info_player_start":
            e["origin"] = " ".join(f"{c:.1f}" for c in back)
            e["angles"] = f"0 {yaw} 0"
    b.entities = ents + _camera_entities(cam[:5])
    b.save(dest)


def screenshots(bsp_path, cameras, out_dir, prefix="shot", width=1280, height=720,
                wait_frames=300, timeout=120, fire=(), console=()):
    """Render in-engine screenshots. cameras: list of (x, y, z_eye, pitch, yaw[, fire_list]).
    fire: targetnames to trigger ~0.3s after spawn ('@doors' = open all doors; triggered
    two-way doors swing away from the camera). console: extra console commands run before
    the first map (e.g. "developer 2"). Returns (png_paths, console_log_text)."""
    from PIL import Image

    if hl_running():
        raise RuntimeError("Half-Life is already running; close it first")
    timeout = max(timeout, 40 + 12 * len(cameras))
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    maps_dir = config.GAME_DIR / "maps"
    names = [f"hlmap_cam{i}" for i in range(len(cameras))]
    for n, cam in zip(names, cameras):
        _cam_variant(bsp_path, cam, maps_dir / f"{n}.bsp", fire)

    waits = "wait;" * 10
    cfg = [f'alias hlm_w10 "{waits}"', 'alias hlm_w100 "' + "hlm_w10;" * 10 + '"']
    cfg += list(console)   # e.g. "developer 2" to log entity firing into the console log
    for i, n in enumerate(names):
        settle = max(1, wait_frames // 100) + (4 if i == 0 else 0)   # first load: let startup toasts fade
        cfg += [f"map {n}"] + ["hlm_w100"] * settle + ["snapshot", f"echo HLMAP_SHOT {n}"]
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
        for n in names:
            (maps_dir / f"{n}.bsp").unlink(missing_ok=True)
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
