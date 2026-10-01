# hlbox

Half-Life (GoldSrc) maps written as Python code. You describe the rooms, doorways,
furniture and lights in a script. `hlmap` generates a Valve 220 `.map`, compiles it
with [SDHLT](https://github.com/seedee/SDHLT), installs it into Half-Life and can take
in-engine screenshots to check the result. It was built so Claude Code can make maps
end to end, but it works fine by hand too.

![a scientist presenting generated slides in the conference room, in game](docs/office.jpg)
![generated cave turning into Xen, in game](docs/cave.jpg)
![the second map's test chamber, after someone pressed the red button, in game](docs/labs.jpg)

```python
from hlmap import Map, Level, Material, props

OFFICE = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01")

def build():
    m = Map("office")
    lvl = Level(wall=16)
    office = lvl.room("office", (0, 0, 0), (320, 240, 128), OFFICE)   # describe the air...
    hall = lvl.room("hall", (-160, -112, 0), (480, -16, 128), OFFICE)
    door = lvl.doorway(office, hall, width=64, height=96)             # ...walls are generated, sealed
    lvl.build(m)
    m.add(props.door_rotating(door, hinge="right"))
    m.add(props.table(160, 168, 0), props.chair(160, 124, 0, facing="north"))
    m.add(props.player_start((-100, -64, 0), facing="east"))
    return m
```

## Requirements

- Windows, with Half-Life on Steam (it's auto-detected from the Steam library folders;
  or set `HL_DIR`)
- Python 3.10+ with Pillow (`pip install -r requirements.txt`)

## Usage

```
python -m hlmap setup                 # download the SDHLT compilers (checksum-verified)
python -m hlmap build office          # maps/office.py -> compile -> install -> build/office/plan.png
python -m hlmap build office labs xen pumps   # the whole campaign, in order
python -m hlmap build office --shots  # + in-engine screenshots from the map's CAMERAS
python -m hlmap play office           # launch Half-Life into the map
python -m hlmap tex FIFTIES --sheet   # search textures, render a contact sheet
python -m hlmap preview office --view y --cut 150   # side cutaway
```

`build` also writes a plan-view cutaway, which is handy for checking a layout before
playing it:

![plan preview](docs/office_plan.png)

## What's in the box

- `hlmap/geometry.py` has brushes (box, prism, wedge, cylinder, convex hull) and
  Valve 220 texture alignment, including "fit texture to face".
- `hlmap/level.py` is the room builder. It carves air volumes out of solid shells,
  so rooms and doorways can't leak, and it textures each face by the room it faces.
  Corridors run at any angle, carved with exact convex CSG (`hlmap/csg.py`). A room
  in the way gets its corner cut: in the office, a 45° corridor slips past the
  storage room to a cafeteria.
- `hlmap/campaign.py` joins maps with level transitions. Both maps build the stretch
  where the level changes from one shared function (`maps/campaign.py`), and verify
  checks that it matches surface by surface, that every landing spot is clear, and
  that the next map works for every state the player can arrive in. The office's
  road tunnel leads through a gate, opened by a sector pass from the records room,
  to a second map: a loading bay with a guard, and a materials lab with a red button
  you're asked not to press.
- `hlmap/teleport.py` builds teleporter networks: pads, routes, a power switch,
  offline slots for places to come, pads into other maps, and a board that maps it
  all. Pressing the red button brings labs' network online; its hub has no doors,
  only pads (back to the office basement, and out to Xen) and a window onto Xen.
  `verify` walks through teleporters and checks each trip has a way back.
- The third map, `xen`, is a long jump course. A field station hands out the HEV
  suit, the long jump module and a crowbar, and its airlock won't cycle without
  them; it's one way, sealing behind you. Outside, in 60% gravity, floating islands
  and cliff ledges run over a void, with two gaps only the long jump clears,
  headcrabs that keep coming, an acid pool
  and an arc between two crystals. At the far end a decontamination airlock keeps
  the crowbar and locks the way back; the field lab behind it has the card that
  powers its pad home (one way, onto the hub's arrivals pad). Come back through the
  station and you get a new crowbar and can run it again. `verify` flies every
  running jump and long jump in the low gravity, treats the void as death, tracks
  the gear, fails if you could meet a headcrab unarmed, and plays the course again
  after a round trip through the hub.
- The field lab's card powers the hub's pad to the fourth map, `pumps`: a flooded
  pump station. Dive into the hall past barnacles and leeches, hold your breath
  through a flooded corridor with an air pocket half way, drain a settling tank to
  unlock its hatch, smash a grate past houndeyes, flood a cistern to swim up to its
  exit, ride a lift to the pump control and restart the pumps. `verify` swims,
  holds its breath (no way may keep the head under too long), moves the water with
  the valves, rides the lift and breaks the grate; the build places the monsters'
  navigation nodes.
- `hlmap/terrain.py` builds open terrain for outdoor areas under a sky: hills and
  lawns as watertight triangle columns (GoldSrc has no displacements). The office's
  cafeteria opens onto a patio and a staff car park with brush-built cars and painted
  bays. There are crossed-plane trees, lamp posts, and a road to a tunnel past a
  security booth whose button raises and lowers a boom barrier.
- `hlmap/cave.py` builds organic caves. A heightfield of simple rock columns follows a
  path out of a doorway. It's watertight by construction, its collision is verified,
  and its materials can change along the way (rock turning into Xen).
- `hlmap/verify.py` checks the compiled map against the intended design:
  - collision holes, invisible walls and missing faces;
  - on-foot walkability, playing every order of pickups and buttons through a
    simulation of the entity logic. Can every area be reached? Can any order lock
    you out?
  - after every step, whether the way on is lit enough to see (from the compiled
    lightmaps);
  - jumps, long jumps and gravity zones, gear, hostiles met unarmed, and coming
    back to a map after leaving it.
  `build` won't install a map that fails.
- `hlmap/scene.py` and `hlmap/voice.py` stage talks. In the office, a scientist
  presents a 12-slide briefing with voice lines synthesized at build time, subtitles
  and gestures, timed to the real clip lengths; a power cut stops him mid-sentence.
- `hlmap/logic.py` builds map state out of stock entities: flags (global state),
  conditional relays, timed sequences, and building power. In the office, taking the
  access card trips the breaker: the lights die, red emergency lamps pulse, the
  projector goes dark, and the records door waits for the basement breaker.
- `hlmap/props.py` has furniture (tables, chairs, crates, radios, filing cabinets,
  bookshelves, a vending machine, barrels, pipes, wall art), stairs railings and
  ladders, doors with locks and key pickups, light switches and switchable ceiling
  panels, a projector with toggleable slides, emergency lamps, a breaker lever, Xen
  plants and crystals. There are also Black Mesa style nameplates, posters, stock
  signs and decals, and stencilled words made from stock decal letters.
- `hlmap/wadwrite.py` and `hlmap/art.py` add non-standard textures from any image or
  a pixel-art SVG, embedded in the compiled map.
- `hlmap/compile.py` runs CSG/BSP/VIS/RAD with fast, normal and final profiles, and
  summarizes errors, leaks and how much of each engine limit the map uses. A leak path
  is drawn on the plan preview.
- `hlmap/game.py` installs maps into `valve/maps`. It takes screenshots by loading
  temporary copies of the map with a `trigger_camera` at each camera pose. Each camera
  can first trigger entities: flip light switches, unlock a door, open all doors. Your
  Half-Life video settings are restored afterwards. `playtest` drives the player
  with scripted input and reads back what fired. `playtest --pickups` walks at every
  item to confirm the game picks it up.
- `hlmap/wad.py` reads WAD3 textures and makes contact sheets.
- `hlmap/preview.py` draws orthographic plan and section cutaways.
- `CLAUDE.md` has the workflow, scale numbers, texture and lighting notes, and
  gotchas. `docs/entities.md` is an entity reference.

`install` never overwrites a map it didn't put there, so the stock campaign maps
are safe.
