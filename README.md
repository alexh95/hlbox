# hlbox

Half-Life (GoldSrc) maps written as Python code. You describe the rooms, doorways,
furniture and lights in a script. `hlmap` generates a Valve 220 `.map`, compiles it
with [SDHLT](https://github.com/seedee/SDHLT), installs it into Half-Life and can take
in-engine screenshots to check the result. It was built so Claude Code can make maps
end to end, but it works fine by hand too.

![office map, in game](docs/office.jpg)

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
- `hlmap/props.py` has a table, chair, hinged and sliding doors, ceiling panel
  lights, lights and the player start.
- `hlmap/compile.py` runs CSG/BSP/VIS/RAD with fast, normal and final profiles, and
  summarizes errors and leaks. A leak path is drawn on the plan preview.
- `hlmap/game.py` installs maps into `valve/maps`. It takes screenshots by loading
  temporary copies of the map with a `trigger_camera` at each camera pose. Your
  Half-Life video settings are restored afterwards.
- `hlmap/wad.py` reads WAD3 textures and makes contact sheets.
- `hlmap/preview.py` draws orthographic plan and section cutaways.
- `CLAUDE.md` has the workflow, scale numbers, texture and lighting notes, and
  gotchas. `docs/entities.md` is an entity reference.

`install` never overwrites a map it didn't put there, so the stock campaign maps
are safe.
