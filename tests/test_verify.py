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
    missing, log, never, _ = _two_rooms(key_in_first=True)
    assert missing == [] and never == [] and log


def test_key_behind_its_own_door_is_a_softlock():
    missing, log, never, _ = _two_rooms(key_in_first=False)
    assert never == ["lk"] and [n for n, _ in missing] == ["room b"]


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
    missing, _, _, _ = progression(Hulls(res.bsp), lvl.checkpoints())
    assert missing == [], missing


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
