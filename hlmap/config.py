"""Paths for the Half-Life install, compile tools and build output.

Everything is auto-detected; override with environment variables:
  HL_DIR     Half-Life install dir (the folder that contains hl.exe)
  HLT_DIR    folder that contains sdHLCSG_x64.exe etc.
"""
import os
import re
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
MAPS_SRC_DIR = PROJECT_DIR / "maps"
BUILD_DIR = PROJECT_DIR / "build"
TOOLS_DIR = PROJECT_DIR / "tools" / "sdhlt" / "tools"


def _steam_libraries():
    roots = [Path(r"C:\Program Files (x86)\Steam"), Path(r"C:\Program Files\Steam")]
    libs = []
    for root in roots:
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for m in re.finditer(r'"path"\s+"([^"]+)"', vdf.read_text(errors="ignore")):
                libs.append(Path(m.group(1).replace("\\\\", "\\")))
        libs.append(root)
    return libs


def find_hl_dir() -> Path:
    env = os.environ.get("HL_DIR")
    if env:
        return Path(env)
    for lib in _steam_libraries():
        cand = lib / "steamapps" / "common" / "Half-Life"
        if (cand / "hl.exe").exists():
            return cand
    raise FileNotFoundError("Half-Life not found; set HL_DIR")


HL_DIR = find_hl_dir()
GAME_DIR = HL_DIR / "valve"
HLT_DIR = Path(os.environ.get("HLT_DIR", str(TOOLS_DIR / "Win64")))

# WADs made available to every map. Only textures actually used get referenced.
DEFAULT_WADS = [
    GAME_DIR / "halflife.wad",
    GAME_DIR / "liquids.wad",
    GAME_DIR / "xeno.wad",
    GAME_DIR / "decals.wad",
    TOOLS_DIR / "sdhlt.wad",  # tool textures: NULL, CLIP, ORIGIN, SKIP, HINT, BEVEL...
]
