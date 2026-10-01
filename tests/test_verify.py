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


def _corridor_level():
    """a -- a corridor north, 45 degrees north-west, north -- b; room c (no door) is in
    the way, so its north-east corner gets cut."""
    m = Map("vcorr")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (512, 96, 128), MAT)
    lvl.room("b", (96, 432, 0), (416, 640, 144), MAT)
    c = lvl.room("c", (48, 112, 0), (320, 208, 128), MAT)
    corr = lvl.corridor("diag", [(400, 48), (400, 176), (240, 336), (240, 500)], width=96, height=112)
    lvl.build(m)
    m.add(props.player_start((64, 48, 0)), props.light((256, 48, 100)), props.light((256, 540, 100)),
          props.light((180, 160, 100)))
    out = Path(tempfile.mkdtemp()) / "vcorr.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    return m, lvl, c, corr, Hulls(res.bsp)


def test_diagonal_corridor_is_sealed_and_walkable():
    from hlmap.verify import progression
    m, lvl, c, corr, h = _corridor_level()
    assert c.cuts and "corner cut" in lvl.notes[0]
    brushes = m.worldspawn.brushes
    for hull in (0, 1, 3):
        assert leaks_into_solid(h, lvl.is_air, hull)[0] == [], f"hull {hull} has holes"
        if hull:
            assert invisible_walls(h, lvl.is_air, hull, _box_hits(brushes))[1] == 0, f"hull {hull} invisible walls"

    def solid_at(p):
        return any(all(f.normal[0] * p[0] + f.normal[1] * p[1] + f.normal[2] * p[2] <= f.dist + 0.01
                       for f in b.faces) for b in brushes)
    missing, checked, _ = coverage(h, brushes, lvl.is_air, solid_at)
    assert missing == [] and checked > 50, missing
    p = progression(h, lvl.checkpoints())
    # a, b and the corridor are reached; c has no door: reaching it would mean the
    # corridor broke into it where it cut the corner
    assert [n for n, _ in p.missing] == ["room c"], p.missing


def test_terrain_is_sealed_and_walkable():
    """Outdoor terrain (a heightfield of triangle columns under a sky): no holes in any
    hull, no invisible walls, every face present, and a gentle slope is walkable."""
    import math
    from hlmap.verify import progression
    m = Map("vterrain", skyname="desert")
    lvl = Level(wall=16)
    out = lvl.room("out", (0, 0, 0), (1024, 1024, 512),
                   Material("OUT_PAVE1", "sky", "sky"), checkpoints=[(200, 200), (512, 700)])
    ground = lvl.terrain("ground", out, lambda x, y: 16 + max(0, y - 512) * 0.4 + 12 * math.sin(x / 90),
                         cell=128, flat=[(0, 0, 512, 384)])
    lvl.build(m)
    m.add(props.player_start((128, 128, 0)), props.light((512, 512, 400)))
    path = Path(tempfile.mkdtemp()) / "vterrain.map"
    res = compile_map(m.write(path), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    h = Hulls(res.bsp)
    brushes = m.worldspawn.brushes
    for hull in (0, 1, 3):
        assert leaks_into_solid(h, lvl.is_air, hull)[0] == [], f"hull {hull} has holes"
        if hull:
            assert invisible_walls(h, lvl.is_air, hull, _box_hits(brushes))[1] == 0, f"hull {hull} invisible walls"

    def solid_at(p):
        return any(all(f.normal[0] * p[0] + f.normal[1] * p[1] + f.normal[2] * p[2] <= f.dist + 0.01
                       for f in b.faces) for b in brushes)
    missing, checked, _ = coverage(h, brushes, lvl.is_air, solid_at)
    assert missing == [] and checked > 50, missing
    assert ground.surface(512, 700) > 60                     # the checkpoint is up the slope
    p = progression(h, lvl.checkpoints())
    assert p.missing == [], p.missing


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


def _pad_rooms(glass=False, window=False, route="two-way", bad_landing=False):
    """Room a (start) and room b beside it. With window=True a 24-high sill joins them
    you can jump through (glass=True puts a func_wall pane in it); otherwise only teleporter pads link
    them: route "two-way", "one-way" (b's pad offline) or None."""
    from hlmap import teleport
    from hlmap.verify import progression, teleport_landings
    m = Map("vpads")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (384, 256, 128), MAT)
    b = lvl.room("b", (400, 0, 0), (784, 256, 128), MAT)
    if window:
        w = lvl.doorway(a, b, width=128, height=96, sill=24)
    lvl.build(m)
    if glass:
        (x0, y0, z0), (x1, y1, z1) = w.mins, w.maxs
        m.add(props.Entity("func_wall", brushes=[box((x0 + 7, y0, z0), (x0 + 9, y1, z1), "GLASS_BRIGHT")],
                           rendermode=2, renderamt=60))
    if route:
        net = teleport.Network("t")
        pa = net.pad("pa", (192, 200, 0), "south", site="A")
        pb = net.pad("pb", (592, 200, 0), "south", site="B", offline=route == "one-way")
        net.route(pa, pb, two_way=route == "two-way")
        m.add(net.entities(m))
    if bad_landing:      # a teleporter whose target stands on another teleporter's volume
        m.add(props.Entity("trigger_teleport", brushes=[box((40, 40, 0), (88, 88, 64), "AAATRIGGER")], target="dst"),
              props.Entity("trigger_teleport", brushes=[box((296, 40, 0), (344, 88, 64), "AAATRIGGER")], target="dst"),
              props.point("info_teleport_destination", (320, 64, 0), targetname="dst"))
    m.add(props.player_start((64, 180, 0)), props.light((192, 128, 100)), props.light((592, 128, 100)))
    out = Path(tempfile.mkdtemp()) / "vpads.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    h = Hulls(res.bsp)
    return progression(h, lvl.checkpoints()), teleport_landings(h)[0]


def test_glass_blocks_the_walker():
    """A pane of glass (a func_wall) in a low window: without it you could jump through."""
    p, _ = _pad_rooms(window=True, route=None)
    assert p.missing == []
    p, _ = _pad_rooms(window=True, glass=True, route=None)
    assert [n for n, _ in p.missing] == ["room b"], p.missing


def test_teleporter_reaches_a_sealed_room():
    p, bad = _pad_rooms()
    assert p.missing == [] and bad == []
    assert [back for _, back, _ in p.teleports] == [True, True]


def test_one_way_teleporter_that_strands_is_caught():
    p, bad = _pad_rooms(route="one-way")
    assert p.missing == [] and bad == []
    assert p.teleports and p.teleports[0][1] is False and "room a" in p.teleports[0][2], p.teleports


def test_landing_on_a_teleporter_is_caught():
    _, bad = _pad_rooms(route=None, bad_landing=True)
    assert any("on a teleporter" in problem for _, problem in bad), bad


def _gap(gap, gear=False, gravity=None, lethal=False):
    """Two ledges (tops at z 0) with a `gap` between them over a pit 256 deep; the
    start is on the near ledge. gear: the HEV suit and the long jump module lie on it;
    gravity: a trigger_gravity over everything; lethal: a trigger_hurt fills the pit."""
    from hlmap.verify import progression
    m = Map("vgap")
    lvl = Level(wall=16)
    lvl.room("pit", (0, 0, -256), (1024, 256, 256), MAT)
    lvl.build(m)
    near, far = 320, 320 + gap
    m.add(props.detail(box((0, 0, -256), (near, 256, 0), "CRETE4_WALL01B"),
                       box((far, 0, -256), (1024, 256, 0), "CRETE4_WALL01B")))
    if gear:
        m.add(props.point("item_suit", (96, 64, 8)), props.point("item_longjump", (96, 192, 8)))
    if gravity:
        m.add(props.Entity("trigger_gravity", brushes=[box((0, 0, -256), (1024, 256, 256), "AAATRIGGER")],
                           gravity=gravity))
    if lethal:
        m.add(props.Entity("trigger_hurt", brushes=[box((near, 0, -256), (far, 256, -200), "AAATRIGGER")],
                           dmg=1000, damagetype=32))
    m.add(props.player_start((160, 128, 0), facing="east"), props.light((512, 128, 200)))
    out = Path(tempfile.mkdtemp()) / "vgap.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    checkpoints = [("far ledge", [(far + 200, 128, 37)]), ("pit floor", [(near + gap / 2, 128, -256 + 37)])]
    return progression(Hulls(res.bsp), checkpoints, jumps=True)


def test_running_jump_clears_a_small_gap():
    p = _gap(150)
    assert "far ledge" not in [n for n, _ in p.missing], p.missing


def test_wide_gap_needs_the_long_jump_module():
    p = _gap(300)
    assert "far ledge" in [n for n, _ in p.missing]            # too far for a running jump
    p = _gap(300, gear=True)
    assert "far ledge" not in [n for n, _ in p.missing], p.missing
    assert any("got the long jump module" in step for step in p.log), p.log


def test_low_gravity_stretches_a_jump():
    p = _gap(300, gravity=0.5)
    assert "far ledge" not in [n for n, _ in p.missing], p.missing


def test_a_lethal_pit_is_not_a_place_to_go():
    p = _gap(300)
    assert "pit floor" not in [n for n, _ in p.missing]         # a fall you survive
    p = _gap(300, lethal=True)
    assert "pit floor" in [n for n, _ in p.missing]             # into a trigger_hurt: death


def _one_way_rooms(come_back):
    """Rooms a and b; the door between opens while a Flag is on, and walking on into b
    turns it off (the Xen decontamination airlock). A way out of the map is in b."""
    from hlmap import logic
    from hlmap.verify import progression
    m = Map("voneway")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (256, 256, 128), MAT)
    b = lvl.room("b", (272, 0, 0), (528, 256, 128), MAT)
    door = lvl.doorway(a, b, width=64, height=96)
    lvl.build(m)
    flag = logic.Flag("open", True, (128, 128, 100))
    m.add(flag.entities(), props.door_sliding(door, master=flag.is_on),
          props.trigger((400, 0, 0), (528, 256, 128), flag.off),
          props.player_start((64, 128, 0)), props.light((128, 128, 100)), props.light((400, 128, 100)))
    out = Path(tempfile.mkdtemp()) / "voneway.map"
    res = compile_map(m.write(out), profile="fast", steps=("csg", "bsp"))
    assert res.ok, res.summary()
    exits = {"out": ((480, 100, 0), (520, 150, 100))}
    return progression(Hulls(res.bsp), lvl.checkpoints(), exits=exits, come_back=come_back)


def test_a_door_that_locks_behind_is_a_lockout_unless_the_player_can_come_back():
    p = _one_way_rooms(come_back=())
    assert p.softlocks and "room a" in p.softlocks[0][1], p.softlocks
    p = _one_way_rooms(come_back=["out"])          # leave by "out" and come back in: not stuck
    assert not p.softlocks and not p.missing, (p.softlocks, p.missing)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
