"""The verifier must catch each defect class it claims to catch.

Each test compiles a small sealed room (SDHLT required: `python -m hlmap setup`) and then
verifies it against a deliberately mismatched description of the intended air, so the
compiled BSP contains exactly the defect under test.

Run:  python -m pytest tests      (or: python tests/test_verify.py)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hlmap import Level, Map, Material, box, props  # noqa: E402
from hlmap.compile import compile_map  # noqa: E402
from hlmap.verify import Hulls, coverage, invisible_walls, leaks_into_solid, reachability  # noqa: E402

MAT = Material("FIFTIES_FLR02C", "FIFTIES_WALL14A", "FIFTIES_CEIL01")
_cache = {}


def _room(extra_world=()):
    """Compile a 256x256x128 room (+ extra world brushes); returns (Map, Hulls)."""
    key = tuple(map(repr, extra_world))
    if key in _cache:
        return _cache[key]
    m = Map("vtest")
    lvl = Level(wall=16)
    lvl.room("room", (0, 0, 0), (256, 256, 128), MAT)
    lvl.build(m)
    m.add_world(*extra_world)
    m.add(props.player_start((64, 64, 0)))
    m.add(props.light((128, 128, 100)))
    out = Path(tempfile.mkdtemp()) / "vtest.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    _cache[key] = (m, Hulls(res.bsp))
    return _cache[key]


def _box_hits(brushes):
    def hits(p, lo, hi):
        for b in brushes:
            if all(f.normal[0] * p[0] + f.normal[1] * p[1] + f.normal[2] * p[2]
                   + sum(min(f.normal[k] * lo[k], f.normal[k] * hi[k]) for k in range(3)) <= f.dist + 0.01
                   for f in b.faces):
                return True
        return False
    return hits


def test_clean_room_passes():
    m, h = _room()
    lvl = m.level
    for hull in (0, 1, 3):
        assert leaks_into_solid(h, lvl.is_air, hull)[0] == []
        if hull:
            assert invisible_walls(h, lvl.is_air, hull, _box_hits(m.worldspawn.brushes))[1] == 0
    missing, _ = reachability(h, lvl.checkpoints(), (64, 64, 37))
    assert missing == []


def test_hidden_solid_is_an_invisible_wall():
    pillar = box((112, 112, 0), (144, 144, 128), "FIFTIES_WALL14A")
    m, h = _room([pillar])
    # verify against the level WITHOUT telling it about the pillar
    hits = _box_hits(m.worldspawn.brushes[:-1])
    assert invisible_walls(h, m.level.is_air, 1, hits)[1] > 0


def test_air_declared_solid_is_a_hole():
    m, h = _room()
    # pretend the room is only half as wide: the real air beyond x=128 is now "solid"
    def smaller(p, tol=0):
        return -tol <= p[0] <= 128 + tol and -tol <= p[1] <= 256 + tol and -tol <= p[2] <= 128 + tol
    for hull in (0, 1, 3):
        assert leaks_into_solid(h, smaller, hull)[0], f"hull {hull} hole not detected"


def test_missing_face_is_detected():
    m, h = _room()
    ghost = box((96, 96, 0), (160, 160, 32), "CRATE02")   # never compiled
    missing, checked, total = coverage(h, [ghost], m.level.is_air, lambda p: False)
    assert total >= 1


def _two_rooms(key_in_first):
    """Room A (spawn) -- locked door -- room B; the key is in A or (softlock) in B."""
    from hlmap.verify import progression
    m = Map("vlock")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (256, 256, 128), MAT)
    b = lvl.room("b", (272, 0, 0), (528, 256, 128), MAT)
    door = lvl.doorway(a, b, width=64, height=96)
    lvl.build(m)
    m.add(props.lock("lk", door.center), props.door_rotating(door, master="lk"))
    key_at = (64, 200, 16) if key_in_first else (464, 200, 16)
    m.add(props.pickup("item_security", key_at, fires=["lk_key"], sound=None))
    m.add(props.player_start((64, 64, 0)), props.light((128, 128, 100)), props.light((400, 128, 100)))
    out = Path(tempfile.mkdtemp()) / "vlock.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    return progression(Hulls(res.bsp), lvl.checkpoints())


def test_key_in_reach_opens_the_door():
    p = _two_rooms(key_in_first=True)
    assert p.missing == [] and p.never == [] and p.log and p.softlocks == []


def test_key_behind_its_own_door_is_a_softlock():
    p = _two_rooms(key_in_first=False)
    assert p.never == ["lk"] and [n for n, _ in p.missing] == ["room b"]


def _power_rooms(one_shot_breaker=False, emergency=False, rad=False):
    """a (start, card) | b (locked: card AND power) ; a - corridor - c (breaker).
    Taking the card trips the power (lights out); the breaker in c restores it."""
    from hlmap import logic
    from hlmap.verify import FloorLight, progression
    m = Map("vpower")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (256, 256, 128), MAT)
    b = lvl.room("b", (272, 0, 0), (528, 256, 128), MAT)
    cor = lvl.room("corridor", (-528, 96, 0), (-16, 160, 128), MAT)
    c = lvl.room("c", (-800, 0, 0), (-544, 256, 128), MAT)
    door = lvl.doorway(a, b, width=64, height=96)
    lvl.doorway(a, cor, width=64, height=96, center=128)
    lvl.doorway(cor, c, width=64, height=96, center=128)
    lvl.build(m)
    grid = logic.Circuit("power")
    m.add(props.lock("lk", door.center, globalstate=grid.flag.state), props.door_rotating(door, master="lk"))
    m.add(props.pickup("item_security", (200, 200, 16), fires=["lk_key", grid.fail], sound=None))
    if one_shot_breaker:     # sets the power on directly and can only be used once
        m.add(props.switch((-800, 128, 48), "east", grid.flag.on, wait=-1))
    else:                    # the real thing: only works while the power is out
        m.add(props.switch((-800, 128, 48), "east", grid.restore, master=grid.dead))
    for name, pts in (("a_lights", [(128, 128, 100)]), ("cor_lights", [(-400, 128, 100), (-150, 128, 100)]),
                      ("c_lights", [(-672, 128, 100)])):
        m.add([props.light(p, targetname=name) for p in pts])
        grid.group(name)
    if emergency:
        m.add([props.light(p, (255, 40, 20), 90, targetname="em", spawnflags=1)
               for p in ((128, 128, 100), (-270, 128, 100), (-672, 128, 100))])
        grid.emergency("em")
    m.add(grid.entities(), props.light((400, 128, 100)), props.player_start((64, 64, 0)))
    out = Path(tempfile.mkdtemp()) / "vpower.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp", "vis", "rad") if rad else ("csg", "bsp"))
    assert res.ok, res.summary()
    h = Hulls(res.bsp)
    return progression(h, lvl.checkpoints(), light=FloorLight(h.bsp) if rad else None)


def test_power_sequence_is_followed():
    p = _power_rooms()
    assert p.missing == [] and p.softlocks == [] and not p.warnings, (p.missing, p.softlocks, p.warnings)
    assert len(p.log) == 2 and "power off" in p.log[0] and "lk unlocked" in p.log[1], p.log


def test_breaker_used_before_the_outage_is_a_lockout():
    p = _power_rooms(one_shot_breaker=True)
    assert p.missing == []                       # the right order still reaches everything...
    assert p.softlocks, "pressing the one-shot breaker first must be reported"
    path, lost = p.softlocks[0]
    assert "power_on" in path[0] and lost == ["room b"], p.softlocks


def test_dark_way_to_the_breaker_is_caught():
    from hlmap.verify import DARK_LIMIT
    dark = _power_rooms(rad=True)
    lit = _power_rooms(emergency=True, rad=True)
    worst = lambda p: max(cost for _, _, cost in p.darkness)
    assert worst(dark) > DARK_LIMIT, dark.darkness      # 500+ units of pitch-black corridor
    assert worst(lit) <= DARK_LIMIT, lit.darkness


def _item_on_table(inset, pole):
    """A card on a table (east edge at x 280), `inset` units in from the edge, with or
    without a thin pole just off the table next to it (the office's radio-camp bug:
    walking straight at the card, the player stopped at the pole, out of reach)."""
    from hlmap.verify import Walker, item_rest, pickup_approaches
    m = Map("vitem")
    lvl = Level(wall=16)
    lvl.room("room", (0, 0, 0), (512, 256, 128), MAT)
    lvl.build(m)
    m.add(props.table(256, 128, 0, width=48, depth=96, height=38))
    if pole:
        m.add(props.detail(box((287, 139, 0), (291, 143, 90), "FIFTIES_DSK5B")))
    item = (280 - inset, 128, 46)
    m.add(props.point("item_security", item), props.player_start((420, 128, 0)), props.light((256, 128, 100)))
    out = Path(tempfile.mkdtemp()) / "vitem.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    h = Hulls(res.bsp)
    w = Walker(h)
    comp = w.flood([w.settle((420, 128, 37))])
    return {sector: touched for sector, _, touched, _ in pickup_approaches(h, comp, item_rest(h, item))}


def test_blocked_pickup_is_caught():
    bad = _item_on_table(inset=12, pole=True)
    assert bad["east"] is False, bad                   # stopped by the pole, like in the game
    good = _item_on_table(inset=6, pole=False)
    assert good and all(good.values()), good


def test_stairs_are_walkable():
    """Level.stairs must leave head room for a 32-wide, 72-tall player all the way down."""
    from hlmap.verify import progression
    m = Map("vstairs")
    lvl = Level(wall=16)
    up = lvl.room("up", (0, 0, 0), (256, 256, 128), MAT)
    down = lvl.room("down", (0, 0, -176), (256, 256, -16), MAT)
    steps, hole = lvl.stairs("s", down, up, top=(128, 32), down="north")
    lvl.build(m)
    m.add(steps, props.player_start((48, 48, 0)), props.light((128, 128, 100)), props.light((128, 128, -40)))
    out = Path(tempfile.mkdtemp()) / "vstairs.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    p = progression(Hulls(res.bsp), lvl.checkpoints())
    assert p.missing == [], p.missing


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
