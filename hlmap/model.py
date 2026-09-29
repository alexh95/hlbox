"""Read GoldSrc studio models (.mdl): the animation sequences a model has.

    model.sequences("models/scientist.mdl")   # {"wave": (1.9, False), "talkleft": (15.1, True), ...}

Paths are relative to the game folder (valve/) unless absolute. Used to check the
animations scripted_sequences and talks ask for.
"""
from __future__ import annotations

import struct
from functools import lru_cache
from pathlib import Path

from . import config

NPC_MODELS = {"monster_scientist": "models/scientist.mdl", "monster_barney": "models/barney.mdl",
              "monster_gman": "models/gman.mdl", "monster_zombie": "models/zombie.mdl"}


@lru_cache(maxsize=None)
def sequences(path):
    """{name: (seconds, loops)} for every sequence in a studio model."""
    p = Path(path)
    if not p.is_absolute():
        p = config.GAME_DIR / p
    data = p.read_bytes()
    if data[:4] != b"IDST":
        raise ValueError(f"{p}: not a studio model")
    numseq, seqindex = struct.unpack_from("<ii", data, 164)
    out = {}
    for i in range(numseq):
        o = seqindex + i * 176                       # mstudioseqdesc_t
        name = data[o:o + 32].split(b"\0")[0].decode("latin-1")
        fps, flags = struct.unpack_from("<fi", data, o + 32)
        frames = struct.unpack_from("<i", data, o + 56)[0]
        out.setdefault(name, (frames / fps if fps else 0.0, bool(flags & 1)))
    return out
