"""Download the SDHLT compile tools (not stored in git) into tools/sdhlt."""
from __future__ import annotations

import hashlib
import io
import urllib.request
import zipfile

from . import config

SDHLT_URL = "https://github.com/seedee/SDHLT/releases/download/v1.3.0/sdhlt_v130.zip"
SDHLT_ROOT = "sdhlt-v1.3.0/"
SHA256 = {
    "tools/Win64/sdHLCSG_x64.exe": "d6bc1c65addc6a94e07cbb0245edc52449584f7885d88be9a25fbefe935a2298",
    "tools/Win64/sdHLBSP_x64.exe": "34d3d4014792659b672f69794f456a844c3bd7944f8b27e89e960518b2f2691d",
    "tools/Win64/sdHLVIS_x64.exe": "a248de9174cb715bbc30b42a6a09cec95234fcb8c9f0da0fdb4d2437eb6b921a",
    "tools/Win64/sdHLRAD_x64.exe": "084975c9025245a4cebfd502eeba7c134b09f83a65f2a1d63289796f2d10f7e9",
    "tools/Win64/sdRIPENT_x64.exe": "e0ef1cf89233c51cadfeaf9ee3ef8f2a6b8c5f7af90729f86eee5e0abcd8d45a",
    "tools/sdhlt.wad": "1b1a688420bb8e4f03090c2566fc5b6b0fc0a13f88ed96c2a4cabe550b58da87",
}


def installed():
    root = config.TOOLS_DIR.parent
    return all((root / rel).exists() for rel in SHA256)


def install_sdhlt(force=False):
    dest = config.TOOLS_DIR.parent  # tools/sdhlt
    if installed() and not force:
        return f"SDHLT already present in {dest}"
    with urllib.request.urlopen(SDHLT_URL) as r:
        data = r.read()
    z = zipfile.ZipFile(io.BytesIO(data))
    for rel, want in SHA256.items():
        got = hashlib.sha256(z.read(SDHLT_ROOT + rel)).hexdigest()
        if got != want:
            raise RuntimeError(f"checksum mismatch for {rel}: {got}")
    for info in z.infolist():
        if not info.filename.startswith(SDHLT_ROOT) or info.is_dir() or "/media/" in info.filename:
            continue
        out = dest / info.filename[len(SDHLT_ROOT):]
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(z.read(info))
    return f"installed SDHLT v1.3.0 into {dest}"
