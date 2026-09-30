"""The office map's story logic, simulated from its script (no compile):
the briefing, the power failure, and what the scientist says when you come back.

Run:  python -m pytest tests      (or: python tests/test_office.py)
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from hlmap.sim import World  # noqa: E402
from test_logic import _lump  # noqa: E402

_ents = []


def _world():
    if not _ents:
        spec = importlib.util.spec_from_file_location("office", ROOT / "maps" / "office.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ents.extend(_lump(mod.build().entities))
    return World([dict(e) for e in _ents]).start()


def _enter(w, until=None):
    """Walk into the conference room: touch its trigger volume (it needs power)."""
    i = next(k for k, e in enumerate(w.ents) if e.get("classname") == "trigger_multiple"
             and e.get("target") == "conf_enter")
    return w.touch(i, until)


def _said(w):
    """Voice lines played so far, in order."""
    return [w.ents[i]["targetname"][:-6] for i, c, u in w.effects      # (hushing turns voices "off")
            if c == "ambient_generic" and u == "toggle" and w.ents[i].get("targetname", "").endswith("_voice")]


def test_first_visit_gives_the_briefing_once():
    w = _world()
    _enter(w)
    _enter(w)                                         # walking around the room: nothing new
    said = _said(w)
    assert said == [f"talk{k:02d}" for k in range(1, 13)], said
    assert not w.warnings


def test_back_after_the_briefing():
    w = _world()
    _enter(w)                              # the briefing
    w.fire("power_fail")
    w.fire("power_restore")
    n = len(_said(w))
    _enter(w)
    assert _said(w)[n:] == ["back_after01", "back_after02", "back_after03"], _said(w)[n:]
    _enter(w)                              # only once
    assert len(_said(w)) == n + 3


def test_back_after_an_interrupted_briefing():
    w = _world()
    _enter(w, until=20)                    # 20 s into the briefing
    w.fire("power_fail")
    w.run()
    said = _said(w)
    assert "talk_int" in said and "talk12" not in said, said
    w.fire("power_restore")
    _enter(w)
    assert _said(w)[-3:] == ["back_after01", "back_after02", "back_after03"], _said(w)


def test_back_before_the_briefing_then_the_briefing():
    w = _world()
    w.fire("power_fail")                              # the card, without visiting the room
    _enter(w)                              # no power: nothing
    assert _said(w) == []
    w.fire("power_restore")
    _enter(w)
    said = _said(w)
    assert said[:2] == ["back_before01", "back_before02"] and said[2:] == [f"talk{k:02d}" for k in range(1, 13)], said


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
