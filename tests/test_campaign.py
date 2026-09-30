"""Level transitions: maps joined by a Link, and the story carried across them.

The first tests compile two tiny maps joined by a Link (SDHLT required) and check that
campaign.check_transition passes a good transition and catches broken ones: a zone
that looks different in the two maps, textures that don't line up, a landing spot
inside a wall. The rest simulate the office and the labs from their scripts (no
compile): what the player carries from one to the other.

Run:  python -m pytest tests      (or: python tests/test_campaign.py)
"""
import importlib.util
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from hlmap import Level, Map, Material, box, campaign, props  # noqa: E402
from hlmap.campaign import Link, check_transition  # noqa: E402
from hlmap.compile import compile_map  # noqa: E402
from hlmap.sim import World  # noqa: E402
from hlmap.verify import Hulls, Walker  # noqa: E402
from test_logic import _lump  # noqa: E402

ZONE = Material("OUT_PAVE1", "TNNL_W12", "TNNL_C1")


def _pair(origin_b=(512, 1024, 0), wall_b="TNNL_W12", pillar=False):
    """Maps ta and tb sharing a 512x256 stretch of corridor (the zone): ta goes on
    west of it, tb east. ta's trigger is at the zone's east end, tb's at its west end.
    Map tb's copy can differ: another wall texture, or a pillar where ta lands you.
    Returns (Hulls of ta, Hulls of tb, positions a player reaches in ta)."""
    def zone(m, lvl, o):
        mat = ZONE if m.name == "ta" else ZONE.with_(wall=wall_b)
        lvl.room("zone", (o[0] - 256, o[1] - 128, o[2]), (o[0] + 256, o[1] + 128, o[2] + 128), mat, group="z")

    link = Link("gap", ("ta", "tb"), zone=((-256, -128, 0), (256, 128, 128)),
                origins={"ta": (0, 0, 0), "tb": origin_b},
                triggers={"ta": ((128, -128, 0), (192, 128, 128)), "tb": ((-192, -128, 0), (-128, 128, 128))},
                build=zone)
    out = {}
    for name in ("ta", "tb"):
        m = Map(name)
        lvl = Level(wall=16)
        link.place(m, lvl)
        x, y, z = link.origins[name]
        side = -1 if name == "ta" else 1                     # where this map goes on
        lvl.room("rest", (x + min(side * 256, side * 512), y - 128, z), (x + max(side * 256, side * 512), y + 128,
                                                                         z + 128), ZONE, group="z")
        lvl.build(m)
        if name == "tb" and pillar:                          # right where ta's trigger lands the player
            m.add_world(box((x + 96, y - 128, z), (x + 128, y + 128, z + 128), "TNNL_W12"))
        m.add(props.player_start((x + side * 400, y, z), facing="east" if side < 0 else "west"),
              props.light((x, y, z + 100)))
        path = Path(tempfile.mkdtemp()) / f"{name}.map"
        res = compile_map(m.write(path), profile="fast", steps=("csg", "bsp"))
        assert res.ok, res.summary()
        out[name] = Hulls(res.bsp)
    w = Walker(out["ta"])
    start = next(e for e in out["ta"].entities if e.get("classname") == "info_player_start")
    reached = w.flood([w.settle(tuple(float(c) for c in start["origin"].split()))])
    return out["ta"], out["tb"], reached


def test_a_matching_transition_passes():
    ha, hb, reached = _pair()
    problems, warnings, notes = check_transition(ha, hb, "ta", "tb", reached)
    assert problems == [], problems
    assert any("landing spots stand clear" in n for n in notes) and any("zone surfaces match" in n for n in notes)


def test_a_different_zone_is_caught():
    ha, hb, reached = _pair(wall_b="CRETE4_WALL01B")
    problems, _, _ = check_transition(ha, hb, "ta", "tb", reached)
    assert any("the zone differs" in p for p in problems), problems
    assert any("TNNL_W12 here, CRETE4_WALL01B" in p for p in problems), problems


def test_misaligned_textures_are_caught():
    """Origins 64 apart shift every world-aligned 128-wide texture by half a tile."""
    old = campaign.ALIGN
    campaign.ALIGN = 64                   # Link refuses such origins; bypass that to build the bad pair
    try:
        ha, hb, reached = _pair(origin_b=(576, 1024, 0))
    finally:
        campaign.ALIGN = old
    problems, _, _ = check_transition(ha, hb, "ta", "tb", reached)
    assert any("shifted by" in p for p in problems), problems


def test_landing_in_a_wall_is_caught():
    ha, hb, reached = _pair(pillar=True)
    problems, _, _ = check_transition(ha, hb, "ta", "tb", reached)
    assert any("inside a wall" in p for p in problems), problems


def test_link_rejects_origins_that_misalign_textures():
    try:
        Link("x", ("a", "b"), zone=((-64, -64, 0), (64, 64, 64)), origins={"a": (0, 0, 0), "b": (100, 0, 0)},
             triggers={"a": ((0, -64, 0), (32, 64, 64)), "b": ((-32, -64, 0), (0, 64, 64))}, build=None)
    except ValueError as e:
        assert "multiples of 512" in str(e)
    else:
        raise AssertionError("expected a ValueError")


# ------------------------------------------------------------ the office -> labs story

_ents = {}


def _map_ents(name):
    if name not in _ents:
        spec = importlib.util.spec_from_file_location(name, ROOT / "maps" / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _ents[name] = _lump(mod.build().entities)
    return [dict(e) for e in _ents[name]]


def _index(w, classname, **kv):
    return next(i for i, e in enumerate(w.ents) if e.get("classname") == classname
                and all(e.get(k) == v for k, v in kv.items()))


def _said(w):
    return [w.ents[i]["targetname"][:-6] for i, c, u in w.effects      # (hushing turns voices "off")
            if c == "ambient_generic" and u == "toggle" and w.ents[i].get("targetname", "").endswith("_voice")]


def _office(briefing):
    """Play the office through: briefing (or not), the card and the power, the pass.
    Returns the global states the player leaves with."""
    w = World(_map_ents("office")).start()
    if briefing:
        w.touch(_index(w, "trigger_multiple", target="conf_enter"))
    w.pickup(_index(w, "item_security", target="records_card"))
    w.press(_index(w, "func_button", target="power_restore"))
    w.pickup(_index(w, "item_security", target="sector_pass_card"))
    gate = _index(w, "func_door", targetname="tunnel_gate")
    w.press(_index(w, "func_button", target="tunnel_reader_use"))
    assert w.door_passable(gate)
    return dict(w.globals)


def _labs(globals_=None):
    return World(_map_ents("labs"), globals_).start()


def test_the_pass_and_the_briefing_come_along():
    w = _labs(_office(briefing=True))
    w.touch(_index(w, "trigger_once", target="greet"))
    assert _said(w) == ["greet_briefed01", "greet_briefed02"], _said(w)
    door = _index(w, "func_door", targetname="lab_door")
    w.press(_index(w, "func_button", target="lab_reader_use"))
    assert w.door_passable(door)


def test_skipping_the_briefing_changes_the_greeting():
    w = _labs(_office(briefing=False))
    w.touch(_index(w, "trigger_once", target="greet"))
    assert _said(w) == ["greet_skipped01", "greet_skipped02"], _said(w)


def test_without_the_pass_the_lab_stays_shut():
    w = _labs()                                     # loaded on its own: no pass
    door = _index(w, "func_door", targetname="lab_door")
    w.press(_index(w, "func_button", target="lab_reader_use"))
    assert not w.door_passable(door)
    assert any(w.ents[i].get("targetname") == "lab_reader_msg_no" for i, _, _ in w.effects)


def test_the_red_button():
    for briefing, ending in ((True, "test_briefed"), (False, "test_skipped")):
        w = _labs(_office(briefing))
        w.press(_index(w, "func_button", target="lab_test"))
        said = _said(w)
        assert said[:3] == ["lab_test01", "lab_test02", "lab_test03"] and said[3:] == [
            f"{ending}0{k}" for k in range(1, 5)], said
        assert w.shown[_index(w, "func_wall_toggle", targetname="boxworth")]
        assert w.door_passable(_index(w, "func_door", targetname="chamber_door"))


def test_the_alarm_stops_when_boxworth_appears():
    for skip in (False, True):
        w = _labs(_office(briefing=True))
        alarm = _index(w, "ambient_generic", targetname="test_alarm")
        w.press(_index(w, "func_button", target="lab_test"), until=2 if skip else None)
        if skip:
            w.press(_index(w, "func_button", target="intercom_skip"))
        uses = [u for i, c, u in w.effects if i == alarm]
        assert uses == ["toggle", "off"], uses                  # on with the first line, off at the reveal


def test_the_test_brings_the_transit_network_online():
    w = _labs(_office(briefing=True))
    pads = [i for i, e in enumerate(w.ents) if e.get("classname") == "trigger_teleport"]
    assert len(pads) == 4 and not any(w.teleport_enabled(i) for i in pads)
    w.press(_index(w, "func_button", target="lab_test"))
    assert all(w.teleport_enabled(i) for i in pads)
    discs = [i for i, e in enumerate(w.ents) if e.get("targetname", "").endswith("_disc")]
    assert discs and all(w.frame[i] == 0 for i in discs)         # lit
    w.fire("transit_start")                                     # starting it again does nothing
    assert all(w.frame[i] == 0 for i in discs) and all(w.teleport_enabled(i) for i in pads)


def test_the_chamber_opens_without_waiting_for_the_intercom():
    w = _labs(_office(briefing=True))
    door = _index(w, "func_door", targetname="chamber_door")
    w.press(_index(w, "func_button", target="lab_test"), until=3)       # first line being said
    assert not w.door_passable(door)
    t = w.time
    w.press(_index(w, "func_button", target="intercom_skip"), until=1)  # the intercom panel
    assert w.door_passable(door) and w.time - t <= 1                   # open at once
    assert w.shown[_index(w, "func_wall_toggle", targetname="boxworth")]
    w.run()
    said = _said(w)
    assert said == ["lab_test01"], said                                # nothing more is said
    # not skipped: the door opens at the flash, well before the intercom has finished
    w = _labs(_office(briefing=True))
    door = _index(w, "func_door", targetname="chamber_door")
    w.press(_index(w, "func_button", target="lab_test"), until=0)
    t, opened_at, last_line_at, lines = 0.0, None, None, 0
    while w._queue:
        t += 0.25
        w.run(t)
        if opened_at is None and w.door_passable(door):
            opened_at = t
        if len(_said(w)) > lines:
            lines, last_line_at = len(_said(w)), t
    assert lines == 7 and opened_at < last_line_at - 5, (opened_at, last_line_at)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
