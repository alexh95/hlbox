"""Voice lines synthesized at build time with Windows' built-in speech voices.

    clips = voice.synthesize({"talk01": "Welcome to the briefing."}, cache_dir, voice="david")
    voice.duration(clips["talk01"])   # seconds, for timing subtitles and events

Output is what GoldSrc plays: PCM WAV, 16-bit mono, 22050 Hz. Clips are cached by
their text and settings, so rebuilding a map doesn't re-synthesize unchanged lines.
Leading and trailing silence is trimmed and the level normalized. Voices are the
stock Windows ones (generic voices; no imitating Half-Life's voice actors).
"""
from __future__ import annotations

import array
import hashlib
import subprocess
import wave
from pathlib import Path

VOICES = {"david": "Microsoft David Desktop", "zira": "Microsoft Zira Desktop"}
RATE = 22050
VERSION = 2          # bump when the post-processing changes (invalidates the cache)


def _key(text, voice, rate, pitch):
    return hashlib.sha1(repr((VERSION, text, voice, rate, pitch)).encode()).hexdigest()[:16]


def synthesize(lines, cache_dir, voice="david", rate=0, pitch=1.0):
    """{name: text} -> {name: Path to a WAV}. rate: -10..10 (0 = normal speed).
    pitch: > 1 higher/faster, < 1 lower/slower (resampled after synthesis)."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out, todo = {}, []
    for name, text in lines.items():
        path = cache_dir / f"{_key(text, voice, rate, pitch)}.wav"
        out[name] = path
        if not path.exists():
            todo.append((path, text))
    if todo:
        raw = [(p.with_suffix(".raw.wav"), t) for p, t in todo]
        _speak(raw, VOICES.get(voice, voice), rate)
        for (rp, _), (p, _) in zip(raw, todo):
            _postprocess(rp, p, pitch)
            rp.unlink(missing_ok=True)
    return out


def _speak(items, voice, rate):
    """One PowerShell run (System.Speech) for all the lines."""
    q = lambda s: "'" + str(s).replace("'", "''") + "'"
    ps = ["Add-Type -AssemblyName System.Speech",
          "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer",
          f"$s.SelectVoice({q(voice)})", f"$s.Rate = {int(rate)}",
          f"$f = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo({RATE}, "
          "[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)"]
    for path, text in items:
        ps += [f"$s.SetOutputToWaveFile({q(path)}, $f)", f"$s.Speak({q(text)})"]
    ps += ["$s.SetOutputToNull()", "$s.Dispose()"]
    script = items[0][0].parent / "speak.ps1"
    script.write_text("\n".join(ps), encoding="utf-8-sig")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                       capture_output=True, text=True)
    script.unlink(missing_ok=True)
    missing = [str(p) for p, _ in items if not p.exists()]
    if r.returncode or missing:
        raise RuntimeError(f"speech synthesis failed ({voice}): {r.stderr.strip() or missing}")


def _read(path):
    with wave.open(str(path), "rb") as w:
        assert w.getnchannels() == 1 and w.getsampwidth() == 2, f"{path}: expected 16-bit mono"
        rate = w.getframerate()
        samples = array.array("h", w.readframes(w.getnframes()))
    return samples, rate


def _write(path, samples, rate=RATE):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())


def _postprocess(src, dest, pitch=1.0, threshold=300, pad=0.05, peak=0.9):
    s, rate = _read(src)
    # trim silence (keep a little padding)
    loud = [i for i in range(0, len(s), 64) if abs(s[i]) > threshold]
    if loud:
        a = max(0, loud[0] - int(pad * rate))
        b = min(len(s), loud[-1] + int(pad * rate))
        s = s[a:b]
    if pitch != 1.0 and len(s) > 1:          # resample: shifts pitch and speed together
        n = int(len(s) / pitch)
        r = array.array("h", bytes(2 * n))
        for i in range(n):
            x = i * pitch
            j = int(x)
            f = x - j
            r[i] = int(s[j] * (1 - f) + s[min(j + 1, len(s) - 1)] * f)
        s = r
    top = max((abs(v) for v in s), default=0)
    if top:
        k = peak * 32767 / top
        s = array.array("h", (max(-32768, min(32767, int(v * k))) for v in s))
    _write(dest, s, rate)


def samples(path):
    """The 16-bit samples of a mono WAV (e.g. to draw its waveform)."""
    return _read(path)[0]


def duration(path):
    """Length of a WAV in seconds."""
    with wave.open(str(path), "rb") as w:
        return w.getnframes() / w.getframerate()


def check_wav(path):
    """Problems that stop GoldSrc from playing a WAV (it wants PCM mono 8/16-bit at
    11025/22050/44100 Hz)."""
    try:
        with wave.open(str(path), "rb") as w:
            probs = []
            if w.getnchannels() != 1:
                probs.append("not mono")
            if w.getsampwidth() not in (1, 2):
                probs.append(f"{8 * w.getsampwidth()}-bit (use 8 or 16)")
            if w.getframerate() not in (11025, 22050, 44100):
                probs.append(f"{w.getframerate()} Hz (use 11025, 22050 or 44100)")
            return probs
    except (wave.Error, EOFError) as e:
        return [f"not a PCM WAV ({e})"]


def loops(path):
    """Does a WAV loop (a 'cue ' chunk)? The game repeats such a sound until it's
    turned off."""
    import struct
    try:
        data = Path(path).read_bytes()
    except OSError:
        return False
    i = 12
    while i + 8 <= len(data):
        cid, size = struct.unpack_from("<4sI", data, i)
        if cid == b"cue ":
            return True
        i += 8 + size + (size & 1)
    return False
