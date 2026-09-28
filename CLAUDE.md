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
- `docs/design.md` covers capabilities, the roadmap, engine limits and open decisions.
  The scope is maps for stock Half-Life; mod-only features are out of scope.
- Half-Life lives at `E:\SteamLibrary\steamapps\common\Half-Life` (auto-detected; override with `HL_DIR`).

## Workflow (run from the project root)

```
python -m hlmap setup                  # once per checkout: fetch the compilers
python -m hlmap build <map>            # script -> .map -> compile (normal) -> install -> build/<map>/plan.png
python -m hlmap build <map> --shots    # ...and take in-engine screenshots of CAMERAS
python -m hlmap build <map> --profile fast|final
python -m hlmap preview <map> [--view top|x|y] [--cut N]   # cutaway PNG only, no compile
python -m hlmap shots <map> [--only NAME]... [--cam "x y z pitch yaw"]... [--fire @doors|targetname]
                                       [--console "developer 2" --log]   # log entity firing to shots/console.log
python -m hlmap play <map>             # launch HL into the map for the user
python -m hlmap tex <pattern> [--sheet]   # find textures; --sheet renders build/sheets/<pattern>.png
python -m hlmap verify <map>           # collision/visibility checks (build runs this too)
python -m hlmap info <map>             # BSP stats + entity lump
python tests/test_verify.py            # the verifier must catch holes, invisible walls, missing faces
```

The verification loop after every change:
1. `build`. Read the compile summary. Any ERROR or LEAK means the map is broken. The
   budget line shows the share of each engine limit used; it warns at 70%. Then
   `verify` runs, and a failure blocks the install. It checks four things:
   - **Holes:** empty space in any collision tree (sight/bullets, standing, crouching)
     that reaches into intended solid. That means walk-through walls or see-through
     gaps.
   - **Invisible walls:** solid collision where the player's box fits in open air.
   - **Reachability:** every room and cave stretch can be reached from the player start.
   - **Coverage:** every visible face exists in the BSP.
   A clean compile does NOT mean clean collision. The compiler's "ambiguous leafnode"
   warnings once hid walk-through cave walls, and only `verify` (or a playtest) shows
   them.
2. Look at `build/<map>/plan.png` with Read. Check that rooms, doors, furniture and
   entities are where intended. Use `preview --view x|y` for heights.
3. `shots` (or `build --shots`), then Read the PNGs. This is the real game render,
   with the real lighting. Check texture alignment, brightness and scale.

Screenshots open a 1280x720 Half-Life window for about 10-20 s and then close it.
They refuse to run if HL is already open. The user's HL video settings are restored
afterwards. Camera: pitch > 0 looks down; yaw 0 = east (+X), 90 = north (+Y).
A standing player's eye is 64 units above the floor.

Cameras are best defined in `build()` as `m.cameras = {"name": (x, y, z, pitch, yaw[, fire])}`,
so they can use computed positions such as `cave.camera(0.4)`. `fire` is a list of
targetnames to toggle first, in order and 0.3 s apart, like pressing a switch.
`"@doors"` opens every door and keeps it open, e.g. `["office_lights"]` or
`["storage_lock_key", "@doors"]`. A locked door stays shut under `@doors`, which
tests the lock. Triggered two-way doors swing in an arbitrary direction; real players
push them away from themselves. If a fired entity seems to do nothing, rerun with
`--console "developer 2" --log`. The log then shows "Found: <class>, firing (<name>)"
for every entity that receives the trigger.

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
  the shared wall. Rooms that touch or overlap are an error unless they share a
  `group=` (then they merge into one space). `lvl.air(name, mins, maxs, like=room)` adds
  alcoves and window holes. `doorway(..., sill=40)` makes a window.
- **Caves.** Use `cave = lvl.tunnel(name, from_room, side, center, path=[...], mouth=(w, h),
  width=, height=, roughness=, seed=, cell=32, materials=[(0.0, ROCK), (0.5, XEN)],
  blend=, scale=f(s))`. It cuts a hole in `from_room`'s `side` wall and grows a cave
  along the floor path.
  - **Construction:** a 2.5-D heightfield. On a `cell`-unit grid, each triangle is a
    floor column (sloped top) plus a ceiling column (sloped bottom). Every side is a
    vertical plane through shared integer grid points, so it's watertight by
    construction and the collision hulls come out clean.
  - **Mouth:** its width must be a multiple of `cell`. Define all other rooms before
    the cave; it keeps clear of them and errors if it passes too close.
  - **Placing things:** `cave.floor_point(s, lateral)` (s = 0..1 along the cave,
    lateral -1..1 across the flat middle of the floor), `cave.frame(s)` and
    `cave.camera(s, eye=, look_ahead=)`.
  - **Scale:** the office cave (~1,000 brushes) uses about 12% of clipnodes and 9% of
    world leaves.
  - **Limit:** one span of air per (x, y), so no overhangs or passages over each other.
  - **Don't build caves from thin slanted brushes** (a shell of rock plates). It
    compiles, but the collision hulls get holes. That's how the first cave failed in
    playtesting.
- **Raw brushes.** Use `box(mins, maxs, tex)`, `prism(xy_points, z0, z1, tex)`,
  `wedge(mins, maxs, low_side, tex)`, `cylinder(center, r, z0, z1, sides, tex)` and
  `hull(points, tex)`. `tex` can be a name or `{'top':..,'bottom':..,'sides':..,'north':..}`.
  Add them with `m.add_world(...)` or wrap them in an entity. Use
  `brush.fit('south', 'TEXNAME')` to stretch one copy of a texture over a face (doors,
  signs, screens). World brushes you add yourself are not carved by rooms. Put them
  inside room air, or make sure they seal.
- **Entities.** `Entity(classname, brushes=[...], kv={...}, **keyvalues)`. Tuples become
  "x y z". Furniture goes in `props.detail(...)` (func_detail), which stays solid without
  cutting visibility. `props` has table, chair, crate (texture fitted per face),
  crystal, door_rotating, door_sliding, ceiling_light, light, point(classname, pos,
  facing, **kv), switch, lock, xen_plantlight, player_start and yaw_towards.
- **Locks.** `m.add(props.lock("storage_lock", door.center))` then
  `door_rotating(..., master="storage_lock")`. The door rattles (locked_sound 12) and
  won't open until something fires `storage_lock_key`. The lock is a multisource plus a
  trigger_relay; a multisource with no inputs counts as unlocked.
- **Switchable lights.** `ceiling_light(..., name="office_lights")` becomes a func_wall
  panel with `style -3` (a "piggyback" texture light that takes the style of the real
  light with the same name) plus that named light. `props.switch(pos_on_wall,
  facing, "office_lights")` is a toggle func_button with a click sound. Firing the name
  turns the room dark and flips the panel to its `+A` (off) frame.
  `zhlt_usestyle` alone does NOT switch texture lights.
- **Where switches go.** Half-Life's `+use` takes anything within 64 units of the
  player that they're facing, and walls don't block it. Never put a switch on a wall
  shared with another room. Keep usable things at least 128 apart. `build` warns about
  both (`hlmap/checks.py`).
- **Xen.** Available entities: `xen_plantlight` (retracts near the player and turns
  off its `target` light; see props.xen_plantlight), `xen_hair`, `xen_spore_small`,
  `xen_spore_medium`, `xen_spore_large` and `xen_tree` (it attacks). Crystals:
  `props.crystal(...)` with `CRYS_2A` plus `m.texlight("CRYS_2A", ...)` to glow.
  `ambient_generic` with `message="ambience/aliencave1.wav"` gives a looping cave sound.
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

- **Caves.** Rock `-0OUT_RK3` with dirt floor `-0OUT_DIRT2` (`hlmap.cave.ROCK`). Xen:
  walls `-0XENO_2W1`, floor `-0XENO_2WA`, crystals `CRYS_2A`. Crates: `CRATE02`,
  `BCRATE09A` (hazard). Computer banks: `FIFTIES_CMP1A`/`3A` fitted on a 96x128 face.
  Light switch plate: `C1A1_SWTCH1`. Locked door: `FIFTIES_DR5` with edge
  `FIFTIES_DR5B`.
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
- `light` entities ignore "on" when already on. Anything meant to act like a switch
  must send toggle (`triggerstate 2`, or a func_button).
- Brush entities don't block light at compile time unless `zhlt_lightflags 2`.
  door_rotating sets this by default, otherwise lit rooms bleed through closed doors.
- A lightmap cell is 16 units, so a door jamb inside a 16-unit wall picks up a little
  light from the other side. That's normal Half-Life behaviour.
- `+use` reaches through walls (64 units, no line-of-sight test); see "Where switches go".
- Collision is only trusted after `verify` passes. If you change a geometry
  generator, run `python tests/test_verify.py` and add a verify-based test for it.
- A func_door_rotating needs an ORIGIN brush at the hinge (props.door_rotating adds one).
- Point entities must sit inside air. `build` warns when they're in solid or void.
- `install` refuses to overwrite a map it didn't install, which protects the stock
  maps, so don't name maps c1a0 and the like.
- Compiled maps go to `valve/maps/<name>.bsp` in the user's Half-Life install. The
  compilers reference WADs by path, and players only need halflife.wad.
