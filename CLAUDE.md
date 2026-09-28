# Half-Life map making with code

Maps for Half-Life 1 (GoldSrc) are written as Python scripts using the `hlmap`
package. They're compiled with SDHLT and checked with previews and in-engine
screenshots. There is no GUI editor in the loop.

## Layout

- `hlmap/` is the library. It covers the geometry, the .map writer, the room builder, props, compile, preview and game integration.
- `maps/<name>.py` holds one map per file. Each defines `build() -> Map` and optionally `CAMERAS`.
- `build/<name>/` holds the generated `.map`, `.bsp`, logs, `plan.png` and `shots/*.png`. It's disposable.
- `tools/sdhlt/` has the SDHLT v1.3.0 compilers (`tools/Win64/*.exe`), `sdhlt.wad` (tool textures) and `sdhlt.fgd`.
  It's not in git; `python -m hlmap setup` downloads it and verifies the checksums.
- `docs/entities.md` is a quick reference for common entities and keyvalues.
- Half-Life lives at `E:\SteamLibrary\steamapps\common\Half-Life` (auto-detected; override with `HL_DIR`).

## Workflow (run from the project root)

```
python -m hlmap setup                  # once per checkout: fetch the compilers
python -m hlmap build <map>            # script -> .map -> compile (normal) -> install -> build/<map>/plan.png
python -m hlmap build <map> --shots    # ...and take in-engine screenshots of CAMERAS
python -m hlmap build <map> --profile fast|final
python -m hlmap preview <map> [--view top|x|y] [--cut N]   # cutaway PNG only, no compile
python -m hlmap shots <map> --cam "x y z pitch yaw" [--cam ...] [--fire @doors|targetname]
python -m hlmap play <map>             # launch HL into the map for the user
python -m hlmap tex <pattern> [--sheet]   # find textures; --sheet renders build/sheets/<pattern>.png
python -m hlmap info <map>             # BSP stats + entity lump
```

The verification loop after every change:
1. `build`. Read the compile summary. Any ERROR or LEAK means the map is broken.
2. Look at `build/<map>/plan.png` with Read. Check that rooms, doors, furniture and
   entities are where intended. Use `preview --view x|y` for heights.
3. `shots` (or `build --shots`), then Read the PNGs. This is the real game render,
   with the real lighting. Check texture alignment, brightness and scale.

Screenshots open a 1280x720 Half-Life window for about 10-20 s and then close it.
They refuse to run if HL is already open. The user's HL video settings are restored
afterwards. Camera: pitch > 0 looks down; yaw 0 = east (+X), 90 = north (+Y).
A standing player's eye is 64 units above the floor. `--fire @doors` opens every
door first. Triggered two-way doors swing in an arbitrary direction; real players
push them away from themselves.

## Writing a map

```python
from hlmap import Map, Level, Material, box, props

ROOM = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01",
                floor_align="min", ceiling_align="min")      # wall_align="floor" is the default

def build():
    m = Map("example")
    lvl = Level(wall=16)
    a = lvl.room("a", (0, 0, 0), (320, 240, 128), ROOM)      # AIR box: mins=floor corner, maxs=ceiling corner
    b = lvl.room("b", (-160, -112, 0), (480, -16, 128), ROOM, wall="FIFTIES_WALL14U")
    d = lvl.doorway(a, b, width=64, height=96, center=160)    # rooms must be separated by a wall gap
    lvl.build(m)                                              # sealed, textured world brushes
    m.add(props.door_rotating(d, hinge="right"))
    m.add(props.table(160, 168, a.floor), props.chair(160, 124, a.floor, facing="north"))
    m.texlight("+0~FIFTS_LGHT01", (255, 248, 230), 3000)      # texture lights need an intensity
    m.add(props.ceiling_light(160, 120, a.ceiling))
    m.add(props.player_start(b.floor_point(-100, -64), facing="east"))
    return m
```

- **Level/rooms.** Describe the empty space and the builder makes the walls. Leaks
  can't happen unless an opening pokes outside every room shell, and `Level.check`
  catches that. Separate adjacent rooms by exactly `wall` units so `doorway()` finds
  the shared wall. `lvl.air(name, mins, maxs, like=room)` adds alcoves and window holes.
  `doorway(..., sill=40)` makes a window.
- **Raw brushes.** Use `box(mins, maxs, tex)`, `prism(xy_points, z0, z1, tex)`,
  `wedge(mins, maxs, low_side, tex)`, `cylinder(center, r, z0, z1, sides, tex)` and
  `hull(points, tex)`. `tex` can be a name or `{'top':..,'bottom':..,'sides':..,'north':..}`.
  Add them with `m.add_world(...)` or wrap them in an entity. Use
  `brush.fit('south', 'TEXNAME')` to stretch one copy of a texture over a face (doors,
  signs, screens). World brushes you add yourself are not carved by rooms. Put them
  inside room air, or make sure they seal.
- **Entities.** `Entity(classname, brushes=[...], kv={...}, **keyvalues)`. Tuples become
  "x y z". Furniture goes in `props.detail(...)` (func_detail), which stays solid without
  cutting visibility. `props` has table, chair, door_rotating, door_sliding,
  ceiling_light, light, player_start and yaw_towards.
- **Default texture alignment** is world-aligned, so textures tile continuously across
  brushes. Room walls put the texture's bottom edge on the floor, so wainscots line up.
  `floor_align`/`ceiling_align` of `min` or `center` puts the tile grid on the room
  corner or centre. Make the room size a multiple of the tile (e.g. 64x80 ceiling tiles)
  and put lights on tile cells.

## Scale & gameplay numbers (1 unit ≈ 1 inch)

- **Player.** 32x32x72 standing, 36 crouched, eye at 64. Max step 18. Jumps 45 high
  (~56 with a crouch-jump). A falling player takes damage from about 300 units.
- **Doors.** At least 64 wide and 96-112 tall. Corridors are at least 64 wide (96-128
  is comfortable). Ceilings are 128+.
- **Furniture.** Table top 32-36. Chair seat 18 (steppable). Stairs are 16 high by 16
  deep (never over 18 high).
- **Grid.** Keep brush coordinates on integers, ideally multiples of 8/16.
- **Limits.** Entities must stay within ±4096 (±8192 engine). Texture names are 15
  characters max.

## Textures

- The WADs are halflife.wad, liquids.wad, xeno.wad, decals.wad and sdhlt.wad. Search
  them with `python -m hlmap tex`. Contact sheets let you pick textures by eye; always
  look before choosing.
- **Prefixes.** `~` is a light texture (it only emits light if registered with
  `m.texlight`). `+0`/`+A` are animated or toggling frames. `!` is water. `{` is
  transparent (index 255 is see-through). `-0` gives random tiling. `sky` is sky.
- **Tool textures.** NULL (face removed), CLIP (invisible player clip), ORIGIN
  (rotation origin, required for rotating entities), AAATRIGGER (triggers), SKIP,
  HINT and BEVEL.
- **The office set that looks right (the "Office Complex" look).** Walls
  FIFTIES_WALL14 / 14U / 14A. Carpet FIFTIES_FLR02C. Checker floor FIFTIES_FLR03.
  Ceiling FIFTIES_CEIL01 (64x80) with the +0~FIFTS_LGHT01 / +0~FIFTS_LGHT06 panels
  (64x80). Doors FIFTIES_DR6A2 (knob) or FIFTIES_DR1K, with edge FIFTIES_DR6B. Wood
  FIFTIES_DR1, FIFTIES_DR6A and FIFTIES_DSK1.

## Lighting

- **Point lights.** `props.light(pos, color, brightness)`, with a brightness of about
  150-300 for a room.
- **Texture lights.** `m.texlight(tex, rgb, intensity)` writes an `info_texlights`
  entity. A 64x80 panel wants about 2000-3000 in a 128-tall room, and less in narrow
  corridors. Use a different light texture when you need a different brightness.
- **Profiles.** The `fast` profile has no bounce, so ceilings come out black. Judge
  lighting from `normal` or `final` builds only.
- **Outdoors.** Add a `light_environment` entity and use `sky` ceilings. Set the
  worldspawn `skyname` (e.g. `Map("x", skyname="desert")`).

## Gotchas

- A door with a `targetname` no longer opens on touch. It needs a trigger or button.
- A func_door_rotating needs an ORIGIN brush at the hinge (props.door_rotating adds one).
- Point entities must sit inside air. `build` warns when they're in solid or void.
- `install` refuses to overwrite a map it didn't install, which protects the stock
  maps, so don't name maps c1a0 and the like.
- Compiled maps go to `valve/maps/<name>.bsp` in the user's Half-Life install. The
  compilers reference WADs by path, and players only need halflife.wad.
