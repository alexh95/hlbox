"""hlmap.logic builds the intended behaviour, as simulated by hlmap.sim (no compile).

Run:  python -m pytest tests      (or: python tests/test_logic.py)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hlmap import box, logic, props  # noqa: E402
from hlmap.mapfile import _kv_value  # noqa: E402
from hlmap.sim import World  # noqa: E402


def _lump(entities):
    """Entities as they appear in a compiled BSP's entity lump (brush models numbered)."""
    out, model = [], 1
    for e in entities:
        d = {"classname": e.classname, **{k: _kv_value(v) for k, v in e.kv.items() if v is not None}}
        if e.brushes:
            d["model"] = f"*{model}"
            model += 1
        out.append(d)
    return out


def _building():
    grid = logic.Circuit("power")
    grid.group("hall", switched=True)
    grid.group("storage")
    grid.emergency("red")
    ents = grid.entities()
    ents += [props.light((0, 0, 0), targetname="hall"), props.light((0, 0, 0), targetname="storage"),
             props.light((0, 0, 0), targetname="red", spawnflags=1, pattern="mnop")]
    ents.append(props.switch((0, 0, 48), "east", grid.switch("hall"), master=grid.live))
    ents.append(props.Entity("func_button", brushes=[box((0, 0, 0), (8, 8, 8), "C1A1_SWTCH1")],
                             target=grid.restore, wait=1, spawnflags=1))
    w = World(_lump(ents)).start()
    by = {e.get("targetname"): i for i, e in enumerate(w.ents) if e["classname"] == "light"}
    buttons = [i for i, e in enumerate(w.ents) if e["classname"] == "func_button"]
    return w, by, buttons, grid


def _lights(w, by):
    return {n: w.lit[i] for n, i in by.items()}


def test_power_failure_keeps_switch_positions():
    w, by, (switch, breaker), grid = _building()
    assert _lights(w, by) == {"hall": True, "storage": True, "red": False}
    w.press(switch)                                   # hall switched off before the failure
    assert _lights(w, by)["hall"] is False
    w.fire(grid.fail)
    assert _lights(w, by) == {"hall": False, "storage": False, "red": True}
    w.press(switch)                                   # dead switch: no power
    assert _lights(w, by)["hall"] is False
    w.fire(grid.fail)                                 # a second failure changes nothing
    assert _lights(w, by) == {"hall": False, "storage": False, "red": True}
    w.press(breaker)
    assert _lights(w, by) == {"hall": False, "storage": True, "red": False}   # hall stays switched off
    w.press(breaker)                                  # restoring twice changes nothing
    assert _lights(w, by) == {"hall": False, "storage": True, "red": False}
    w.press(switch)
    assert _lights(w, by)["hall"] is True
    assert not w.warnings


def test_failure_with_lights_on():
    w, by, (switch, breaker), grid = _building()
    w.fire(grid.fail)
    assert _lights(w, by) == {"hall": False, "storage": False, "red": True}
    w.press(breaker)
    assert _lights(w, by) == {"hall": True, "storage": True, "red": False}


def test_lock_needs_key_and_power():
    grid = logic.Circuit("power")
    ents = grid.entities() + props.lock("lk", (0, 0, 0), globalstate=grid.flag.state)
    w = World(_lump(ents)).start()
    assert not w.master_ok("lk")
    w.fire("lk_key")
    assert w.master_ok("lk")
    w.fire(grid.fail)
    assert not w.master_ok("lk")
    w.fire(grid.restore)
    assert w.master_ok("lk")
    w.fire("lk_key")                                  # the key relay fires once: no relocking
    assert w.master_ok("lk")


def test_sequence_chains_past_16_targets():
    ents = logic.sequence("seq", [(f"t{i}", i * 0.1) for i in range(40)] + [("t0", 5)])
    ents += [props.light((0, 0, 0), targetname=f"t{i}") for i in range(40)]
    w = World(_lump(ents)).start()
    w.fire("seq")
    lit = {e["targetname"]: w.lit[i] for i, e in enumerate(w.ents) if e["classname"] == "light"}
    assert all(not v for k, v in lit.items() if k != "t0") and lit["t0"] is True   # t0 toggled twice
    assert all(len([k for k in e if k.startswith("t")]) <= 16 for e in w.ents if e["classname"] == "multi_manager")


def test_slideshow_steps_and_wraps():
    ents = props.slideshow("s", (0, 348, 24), (192, 352, 144), "south", ["WHITE"] * 5)
    w = World(_lump(ents)).start()
    slides = {e["targetname"]: i for i, e in enumerate(w.ents) if e["classname"] == "func_wall_toggle"}
    shown = lambda: [n for n, i in sorted(slides.items()) if w.shown[i]]
    assert shown() == ["s_1"]
    for k in range(2, 6):
        w.fire("s_next")
        assert shown() == [f"s_{k}"], shown()
    w.fire("s_next")                                  # wraps round
    assert shown() == ["s_1"]
    w.fire("s_step1")                                 # an explicit step keeps "next" in step
    w.fire("s_next")
    assert shown() == ["s_3"] and not w.warnings


def test_talk_runs_once_and_aborts_only_while_running():
    from hlmap import Map, scene
    m = Map("vtalk")
    talk = scene.Talk(m, "talk", head=(0, 0, 64), actor="sci")
    talk.line("One.", fire=["cue1"], gesture="wave")
    talk.line("Two.", fire=["cue2"])
    talk.interrupt("Oh.", gesture="startle")
    talk.on_end.append("after")
    ents = talk.entities()
    ents += [props.light((0, 0, 0), targetname=n) for n in ("cue1", "cue2", "after")]
    w = World(_lump(ents)).start()
    lit = lambda: {e["targetname"]: w.lit[i] for i, e in enumerate(w.ents) if e["classname"] == "light"}
    w.fire(talk.abort)                                # not running: nothing happens
    assert lit() == {"cue1": True, "cue2": True, "after": True}
    w.fire(talk.start)                                # the whole timeline runs (the sim doesn't wait)
    assert lit() == {"cue1": False, "cue2": False, "after": False}
    assert w.globals["talk_running"] == 0             # finished
    fired = [c for _, c, u in w.effects if u == "toggle"]      # (voices are also turned "off": hushed)
    assert fired.count("ambient_generic") == 2 and fired.count("scripted_sequence") == 1
    w.fire(talk.abort)                                # finished: abort does nothing
    assert lit()["after"] is False and not w.warnings
    assert talk.duration > 1 and len(m.custom_sounds) == 3
    # abort in the middle: line 2's cue never comes, the interruption is said
    w = World(_lump(ents)).start()
    w.fire(talk.start, until=talk.lead + 0.1)        # line 1 has started
    assert lit() == {"cue1": False, "cue2": True, "after": True}
    w.fire(talk.abort)
    w.run()
    assert lit() == {"cue1": False, "cue2": True, "after": False}
    said = [w.ents[i].get("targetname") for i, c, u in w.effects if c == "ambient_generic" and u == "toggle"]
    assert said == ["talk01_voice", "talk_int_voice"], said
    assert w.globals["talk_running"] == 0 and not w.warnings


def test_talk_skip_cuts_the_line_and_goes_to_the_end():
    from hlmap import Map, scene
    m = Map("vtalk3")
    talk = scene.Talk(m, "talk", head=(0, 0, 64))
    talk.line("One.", fire=["cue1"])
    talk.line("Two.", fire=["cue2"])
    talk.on_end.append("after")
    talk.on_skip.append("skipped_only")
    ents = talk.entities() + scene.skip_button((0, -64, 48), "north", [talk], name="skip")
    ents += [props.light((0, 0, 0), targetname=n) for n in ("cue1", "cue2", "after", "skipped_only")]
    w = World(_lump(ents)).start()
    lit = lambda: {e["targetname"]: w.lit[i] for i, e in enumerate(w.ents) if e["classname"] == "light"}
    w.fire("skip")                                    # nothing running: nothing happens
    assert all(lit().values())
    w.fire(talk.start, until=talk.lead + 0.1)        # line 1 is being said
    n = len(w.effects)
    w.press(next(i for i, e in enumerate(w.ents) if e.get("classname") == "func_button"))
    w.run()
    assert lit() == {"cue1": False, "cue2": True, "after": False, "skipped_only": False}
    offs = [w.ents[i]["targetname"] for i, c, u in w.effects[n:] if c == "ambient_generic" and u == "off"]
    assert "talk01_voice" in offs                     # the line being said is cut
    said = [w.ents[i]["targetname"] for i, c, u in w.effects[n:] if c == "ambient_generic" and u == "toggle"]
    assert said == [], said                           # and nothing more is said
    assert w.globals["talk_running"] == 0 and w.globals["talk_skipped"] == 1 and not w.warnings
    w.fire(talk.start)                                # a skipped talk is done for good (its timeline
    assert lit()["cue2"] is True and _said_after(w, n) == []   # is removed: the game can't cancel queued fires)


def _said_after(w, n):
    return [w.ents[i]["targetname"] for i, c, u in w.effects[n:] if c == "ambient_generic" and u == "toggle"]


def test_talk_checks_gestures_against_the_model():
    from hlmap import Map, scene
    talk = scene.Talk(Map("vtalk2"), "t", head=(0, 0, 64), actor="sci", actor_model="models/scientist.mdl")
    talk.line("Hi.", gesture="wav")                  # a typo: the game would silently skip it
    try:
        talk.entities()
    except ValueError as e:
        assert "'wav'" in str(e) and "wave" in str(e)
    else:
        raise AssertionError("unknown gesture not caught")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
