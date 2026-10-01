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


def _capture_window(path):
    """Save the Half-Life window's picture (PrintWindow: only that window, even if
    something covers it) as a PNG. Returns the path, or None if there's no window."""
    import ctypes
    from ctypes import wintypes
    from PIL import Image
    user32, gdi32, kernel32 = ctypes.windll.user32, ctypes.windll.gdi32, ctypes.windll.kernel32
    user32.SetProcessDPIAware()          # real pixel sizes (else a scaled display crops the picture)
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):                                      # the visible window of hl.exe
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        proc = kernel32.OpenProcess(0x1000, False, pid.value)          # query limited information
        if proc and user32.IsWindowVisible(hwnd):
            name = ctypes.create_unicode_buffer(260)
            size = wintypes.DWORD(260)
            if kernel32.QueryFullProcessImageNameW(proc, 0, name, ctypes.byref(size)) and \
                    name.value.lower().endswith("\\hl.exe"):
                r = wintypes.RECT()
                user32.GetClientRect(hwnd, ctypes.byref(r))
                found.append((r.right * r.bottom, hwnd))
        if proc:
            kernel32.CloseHandle(proc)
        return True

    user32.EnumWindows(visit, 0)
    if not found:
        return None
    hwnd = max(found)[1]
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    hdc = user32.GetDC(hwnd)
    mdc = gdi32.CreateCompatibleDC(hdc)
    bmp = gdi32.CreateCompatibleBitmap(hdc, w, h)
    gdi32.SelectObject(mdc, bmp)
    user32.PrintWindow(hwnd, mdc, 1 | 2)                     # client area, full (GPU) content

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                    ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                    ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                    ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD),
                    ("biClrImportant", wintypes.DWORD)]
    bi = BITMAPINFOHEADER(ctypes.sizeof(BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    gdi32.GetDIBits(mdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
    gdi32.DeleteObject(bmp)
    gdi32.DeleteDC(mdc)
    user32.ReleaseDC(hwnd, hdc)
    Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1).save(path)
    return path


def _run_session(variants, script, out_dir, prefix, width=1280, height=720, timeout=120, console=(), finish=True,
                 files=None, capture=None):
    """Run Half-Life windowed on temporary map variants ({name: (source_bsp, write_fn)},
    write_fn(dest) writes the variant) and a console `script` (lines; ints = frames to
    wait). finish=False leaves out the final quit; then `capture` = (marker, seconds)
    ends the session: once `marker` shows in the console log, wait that long, save the
    window's picture and close the game. `files`: {path under valve/: text} written for
    the session only (e.g. a map's _load.cfg, which the engine runs when it loads).
    Returns (png paths of the snapshots taken, console log text)."""
    from PIL import Image

    if hl_running():
        raise RuntimeError("Half-Life is already running; close it first")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    maps_dir = config.GAME_DIR / "maps"
    files = {config.GAME_DIR / rel: text for rel, text in (files or {}).items()}
    for path in files:
        if path.exists():
            raise FileExistsError(f"{path} exists; not overwriting it for a playtest")
    # a variant may take an installed map's own name (level changes need it: the next
    # map links back by name); the installed file is set aside and put back afterwards
    backups = {}
    for name in variants:
        dest = maps_dir / f"{name}.bsp"
        if dest.exists():
            if name not in _manifest():
                raise FileExistsError(f"{dest} was not installed by hlmap; not replacing it for a session")
            backups[dest] = config.BUILD_DIR / f"{name}.bsp.session_backup"
            shutil.copy2(dest, backups[dest])
    for name, write in variants.items():
        write(maps_dir / f"{name}.bsp")
    for path, text in files.items():
        path.write_text(text)
    waits = "wait;" * 10
    first = next(iter(variants))       # warm-up load so skill.cfg is read (see launch())
    cfg = [f'alias hlm_w10 "{waits}"', 'alias hlm_w100 "' + "hlm_w10;" * 10 + '"', f"map {first}",
           "hlm_w10", "exec skill.cfg"] + list(console)
    for line in script:
        cfg += _waits(line) if isinstance(line, int) else [line]
    if finish:
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
    captured, seen_at = [], None

    def new_log():
        out = ""
        for p in log_paths:
            if p.exists() and p.stat().st_size > log_offsets[p]:
                with open(p, "rb") as fh:
                    fh.seek(log_offsets[p])
                    out += fh.read().decode("latin-1", errors="replace")
        return out

    try:
        deadline = time.time() + timeout
        time.sleep(3)
        while time.time() < deadline and (proc.poll() is None or hl_running()):
            time.sleep(1)
            if capture and not captured:
                if seen_at is None and capture[0] in new_log():
                    seen_at = time.time()
                if seen_at is not None and time.time() - seen_at >= capture[1]:
                    captured.append(_capture_window(out_dir / f"{prefix}window.png"))
                    subprocess.run(["taskkill", "/IM", "hl.exe", "/F"], capture_output=True)
                    time.sleep(2)
        timed_out = time.time() >= deadline
        if timed_out:
            subprocess.run(["taskkill", "/IM", "hl.exe", "/F"], capture_output=True)
            time.sleep(2)
    finally:
        restored = _reg_restore(reg)
        for name in variants:
            (maps_dir / f"{name}.bsp").unlink(missing_ok=True)
            if maps_dir / f"{name}.bsp" not in backups:       # a temporary copy: its node graph too
                for ext in ("nod", "nrp"):
                    (maps_dir / "graphs" / f"{name}.{ext}").unlink(missing_ok=True)
        for dest, backup in backups.items():
            shutil.move(backup, dest)
        cfg_path.unlink(missing_ok=True)
        for path in files:
            path.unlink(missing_ok=True)

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
    pngs += [c for c in captured if c]
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
    Each frame is 10 ms of game time whatever the real frame rate (host_framerate
    0.01), so 100 frames = 1 s and a run-up is the same every time; walking covers
    ~320 units/s. sv_cheats is on, so a script can `give item_suit`, `give
    item_longjump` (in that order: the module goes on the suit), `give weapon_crowbar`.
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

    lines = (["map hlmap_play", 150, "sv_cheats 1", "host_framerate 0.01", 5, "echo HLMAP_PLAY_START"]
             + list(script) + [10, "snapshot", 10, "host_framerate 0"])
    return _run_session({"hlmap_play": write}, lines, out_dir, prefix, width, height, timeout, console)


def playtest_transition(bsp_path, start, target, out_dir, settle=6, prefix="link", timeout=120, fire=()):
    """Walk into a level change in the real game: the player spawns at start = (x, y,
    feet_z, yaw) and holds forward until the level changes. Nothing may be left
    waiting in the console buffer: the game queues its changelevel, and the new map's
    sign-on, behind it. So a temporary maps/<target>_load.cfg (run by the engine when
    `target` loads) only lets go of forward and echoes a marker; `settle` seconds
    after the marker shows in the log, the window's picture is saved (where the player
    landed) and the game closed. fire: targetnames triggered first, as for cameras
    (e.g. a teleporter pad's power). Returns (png paths, console log): the log has
    "CHANGE LEVEL: <map> <landmark>" and "HLMAP_ARRIVED <target>" if it worked."""
    x, y, z, yaw = start[:4]

    def write(dest):
        b = BSP(bsp_path)
        ents = b.entities
        for e in ents:
            if e.get("classname") == "info_player_start":
                e["origin"] = f"{x:.1f} {y:.1f} {z + 36:.1f}"
                e["angles"] = f"0 {yaw} 0"
        b.entities = ents + _fire_entities(ents, fire, (x, y, z + 36))
        b.save(dest)

    # the copy runs under the map's own name: the next map links back to that name,
    # and the engine only brings the player across from a map it links to
    name = Path(bsp_path).stem
    lines = [f"map {name}", 150, "echo HLMAP_PLAY_START", "+forward"]
    return _run_session({name: write}, lines, out_dir, prefix, timeout=timeout, console=("developer 2",),
                        finish=False, files={f"maps/{target}_load.cfg": f"-forward\necho HLMAP_ARRIVED {target}\n"},
                        capture=(f"HLMAP_ARRIVED {target}", settle))


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
