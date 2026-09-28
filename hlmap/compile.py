"""Run the SDHLT compile chain (CSG -> BSP -> VIS -> RAD) and summarize the logs."""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config

PROFILES = {
    # quick iteration: rough lighting, fast vis
    "fast": {"csg": [], "bsp": [], "vis": ["-fast"], "rad": ["-fast", "-bounce", "2"]},
    "normal": {"csg": [], "bsp": [], "vis": [], "rad": ["-bounce", "8"]},
    # release quality: full vis, supersampled lighting, ambient occlusion
    "final": {"csg": [], "bsp": [], "vis": ["-full"], "rad": ["-extra", "-bounce", "12", "-ao"]},
}

TOOLS = {"csg": "sdHLCSG_x64.exe", "bsp": "sdHLBSP_x64.exe", "vis": "sdHLVIS_x64.exe", "rad": "sdHLRAD_x64.exe"}


@dataclass
class CompileResult:
    ok: bool
    bsp: Path | None
    steps: dict = field(default_factory=dict)       # step -> seconds
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    leak: bool = False
    leak_entities: list = field(default_factory=list)
    pointfile: Path | None = None
    log: Path | None = None

    def summary(self):
        lines = [f"compile {'OK' if self.ok else 'FAILED'}: {self.bsp or ''}"]
        lines.append("  " + ", ".join(f"{k} {v:.1f}s" for k, v in self.steps.items()))
        if self.leak:
            lines.append(f"  LEAK! the world is not sealed. Leak starts at: {'; '.join(self.leak_entities)}")
            lines.append(f"  pointfile: {self.pointfile}")
        for e in self.errors[:20]:
            lines.append(f"  ERROR: {e}")
        for w in self.warnings[:20]:
            lines.append(f"  warning: {w}")
        if len(self.warnings) > 20:
            lines.append(f"  ... {len(self.warnings) - 20} more warnings in {self.log}")
        return "\n".join(lines)


_NOISE = re.compile(r"^\s*$")


def _scan(text, result: CompileResult):
    lines = text.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        low = s.lower()
        if low.startswith("error") and "leak is a hole" in " ".join(lines[i:i + 3]).lower():
            continue  # the leak explanation; reported via result.leak instead
        if low.startswith("error") or "*** error" in low or low.startswith("fatal"):
            # errors are often followed by a detail line or two
            detail = " ".join(l.strip() for l in lines[i + 1:i + 3] if l.strip() and not l.startswith("---"))
            result.errors.append(s + (f" | {detail}" if detail else ""))
        elif low.startswith("warning"):
            result.warnings.append(s)
        if "=== leak" in low:
            result.leak = True
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if nxt.lower().startswith("entity") and nxt not in result.leak_entities:
                result.leak_entities.append(nxt)


def compile_map(map_path, profile="normal", steps=("csg", "bsp", "vis", "rad"), extra=None, verbose=False):
    """Compile a .map in place (the .bsp lands next to it). Returns a CompileResult."""
    map_path = Path(map_path).resolve()
    base = map_path.with_suffix("")
    opts = PROFILES[profile]
    extra = extra or {}
    res = CompileResult(ok=False, bsp=None)
    full_log = []
    for step in steps:
        exe = config.HLT_DIR / TOOLS[step]
        args = [str(exe), "-console", "0"] + opts[step] + list(extra.get(step, [])) + [str(base)]
        t0 = time.time()
        proc = subprocess.run(args, cwd=str(map_path.parent), capture_output=True, text=True,
                              errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        dt = time.time() - t0
        res.steps[step] = dt
        out = proc.stdout + proc.stderr
        full_log.append(f"===== {step}: {' '.join(args)}\n{out}")
        if verbose:
            print(out)
        n_err = len(res.errors)
        _scan(out, res)
        if proc.returncode != 0 or len(res.errors) > n_err:
            if proc.returncode != 0 and len(res.errors) == n_err:
                res.errors.append(f"{step} exited with code {proc.returncode}")
            break
        if step == "bsp" and res.leak:
            break
    log = base.with_suffix(".compile.log")
    log.write_text("\n".join(full_log), encoding="utf-8")
    res.log = log
    for ext in (".lin", ".pts"):
        p = base.with_suffix(ext)
        if res.leak and p.exists() and p.stat().st_mtime > time.time() - 600:
            res.pointfile = p
            break
    bsp = base.with_suffix(".bsp")
    if not res.leak:
        for ext in (".lin", ".pts"):
            base.with_suffix(ext).unlink(missing_ok=True)
    res.ok = not res.errors and not res.leak and bsp.exists()
    res.bsp = bsp if bsp.exists() else None
    return res
