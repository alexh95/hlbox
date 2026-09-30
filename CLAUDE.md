# Half-Life map making with code

Maps for Half-Life 1 (GoldSrc) are written as Python scripts using the `hlmap`
package. They're compiled with SDHLT and checked with previews and in-engine
screenshots. There is no GUI editor in the loop.

## Layout

- `hlmap/` is the library. It covers the geometry, the .map writer, the room builder, props, map logic
  (`logic.py`) and its simulator (`sim.py`), compile, preview, verification and game integration.
- `maps/<name>.py` holds one map per file. Each defines `build() -> Map` and optionally `CAMERAS`.
- `maps/campaign.py` lists the maps in the order a player meets them and defines the
  links between them, including the stretch of level both sides of a transition build
  (see "Campaigns"). `hlmap/campaign.py` is the library side of that.
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
python -m hlmap build office labs      # several maps, in campaign order (each verified with how you arrive)
python -m hlmap build <map> --shots    # ...and take in-engine screenshots of CAMERAS
python -m hlmap build <map> --profile fast|final
python -m hlmap preview <map> [--view top|x|y] [--cut N]   # cutaway PNG only, no compile
python -m hlmap shots <map> [--only NAME]... [--cam "x y z pitch yaw"]... [--fire @doors|targetname]
                                       [--console "developer 2" --log]   # log entity firing to shots/console.log
python -m hlmap play <map>             # launch HL into the map for the user
python -m hlmap tex <pattern> [--sheet]   # find textures; --sheet renders build/sheets/<pattern>.png
python -m hlmap verify <map>           # collision/visibility checks (build runs this too)
python -m hlmap playtest <map> --pickups   # in the real game: walk straight at every item, is it picked up?
python -m hlmap playtest <map> --at "x y feet_z yaw" [--fire NAME] --script "+forward; 60; -forward; 100"
                                       # scripted play from a start; prints what fired, saves a snapshot
python -m hlmap playtest <map> --links # walk into every level change: does the next map load? (snapshot)
python -m hlmap playtest <map> --teleports [--fire transit_start]   # step onto every teleporter (snapshot)
python -m hlmap info <map>             # BSP stats + entity lump
python tests/test_verify.py            # the verifier must catch holes, invisible walls, missing faces,
                                       # lockouts and dark routes
python tests/test_logic.py             # logic helpers behave as intended (simulated, no compile)
python tests/test_office.py            # the office's story: briefing, power cut, welcome back (simulated)
python tests/test_campaign.py          # level transitions must match up; what office hands to labs;
                                       # the lab's skippable intercom and early chamber door
```

The verification loop after every change:
1. `build`. Read the compile summary. Any ERROR or LEAK means the map is broken. The
   budget line shows the share of each engine limit used; it warns at 70%. Then
   `verify` runs, and a failure blocks the install. It checks:
   - **Holes:** empty space in any collision tree (sight/bullets, standing, crouching)
     that reaches into intended solid. That means walk-through walls or see-through
     gaps.
   - **Invisible walls:** solid collision where the player's box fits in open air.
   - **Walkability and progression:** every room (its centre and inset corners), cave
     stretch and `m.checkpoints` entry must be reachable ON FOOT: steps of at most 18,
     jumps of at most 45, falls under 600, ladders, and active teleporters. Solid brush
     entities (func_wall glass, buttons, func_breakable) block the way, tested against
     their own compiled collision hulls; func_wall_toggle and func_illusionary don't.
     - Every progress-relevant pickup, button and trigger volume is tried in every
       order. Its effects are simulated through the entity logic (`hlmap/sim.py`:
       relays, multi_managers, locks, global state, gates, lights). Doors block while
       locked. The log prints the shortest line of play, with what each step changes.
     - "locks never opened" plus unreachable rooms means a key behind its own door.
   - **Lockout:** no order of play may leave an area unreachable for good. For
     example, a one-shot breaker used before the power fails.
   - **Teleporters:** each lands the player standing, clear of solid, not in mid-air,
     not on another teleporter (that would bounce them on) and not in a level change.
     With them all on, every trip must have a way back to where it was stepped on. A
     one-way trip only warns when everything stays reachable, and fails when it cuts
     the player off (it names what's lost).
   - **Darkness:** after every step, the way to the next objective must be lit.
     There's no flashlight without the HEV suit. The check uses the compiled
     lightmaps with the light styles as the simulation left them. A floor under 24
     is dark, and a lit spot helps within 64 units. It reports the units walked
     unable to see, and more than 192 fails.
   - **Decals:** every infodecal sits on a surface (the game only looks 5 units
     out).
   - **Pickups:** each item is approached straight on, as a player who spots it walks
     at it. The walk starts from open ground 72-104 units out in each compass
     direction, with 1-unit steps, 18-unit step-ups and no sliding. If half or more of
     the approaches stop short, that fails for items with a target (keys) and warns
     for the rest. `playtest --pickups` repeats the same walks in the game.
   - **Coverage:** every visible face exists in the BSP.
   - **Campaign:** every level change is reachable (a "way to <map>" checkpoint).
     The global states the player can leave with go to `build/<map>/exits.json`, and
     the next map is verified from where they land, once per state it reads. When
     both maps are compiled, each transition is checked both ways: the landmark,
     the transition volume, every landing spot (standing, not in a wall or the air,
     not touching a trigger back), the shared stretch surface by surface (plane,
     texture, alignment), and the light where the player lands.
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

Extra walkability targets go in `m.checkpoints = [(name, floor_point)]`, e.g. a
mezzanine or a key table. A checkpoint inside furniture counts as reached from next to
it. `shots` warns when a camera sits inside solid geometry; its picture would show the
void.

Cameras are best defined in `build()` as `m.cameras = {"name": (x, y, z, pitch, yaw[, fire])}`,
so they can use computed positions such as `cave.camera(0.4)`. `fire` is a list of
targetnames to toggle first, in order and 0.3 s apart, like pressing a switch.
`"@doors"` opens every door and keeps it open, e.g. `["office_lights"]` or
`["storage_lock_key", "@doors"]`. An entry `("name", seconds)` fires at that time
instead, which lets a sequence finish before the next step (the snapshot is taken
about 3 s in). A locked door stays shut under `@doors`, which
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
  alcoves and window holes. `doorway(..., sill=40)` makes a window. A room with
  `checkpoints=[]` is only for looking at (the view out of a window, a sky with
  floating rocks): nothing in it has to be reachable.
- **Corridors at any angle.** `c = lvl.corridor(name, [(x, y), ...], width=96, height=112,
  material=...)` runs a corridor along a polyline from inside one room to inside
  another, carving the walls it passes through.
  - Keep points on integers and turns at 45 or 90 degrees, so every plane is exact.
  - Both ends must be deep enough inside their rooms that the square end caps are
    in room air (`check()` says so otherwise).
  - `c.floor_point(s, lateral)` and `c.frame(s)` place things along it.
    `props.ceiling_light(..., angle=)` turns a panel to follow a diagonal.
  - A room it passes too close to gets its corner cut, parallel to it and one wall
    away. The corner becomes solid and `build` prints "level: <room>: corner cut...".
    Move furniture, lights and wall art out of the cut; `build` lists any left there
    (`lvl.in_cut(p)`).
  - The pieces are exact convex CSG (`hlmap/csg.py`); `tests/test_verify.py` proves a
    corridor stays sealed.
- **Outdoors.** Make an ordinary room whose walls and ceiling are sky:
  `Material(floor="OUT_PAVE1", wall="sky", ceiling="sky")`. Set
  `Map(name, skyname="desert")` (stock skies: desert, 2desert, morning, dusk, cliff,
  night, ...), and add a `light_environment` (`pitch`, `angles`, `_light`,
  `_diffuse_light`) for the sun.
  - `lvl.terrain(name, room, height=f(x, y), cell=128, flat=[(x0, y0, x1, y1), ...])`
    raises hills and lawns from the room floor. GoldSrc has no displacements (that's
    Source), so this is a heightfield of triangle columns: the cave's watertight
    construction, open to the sky.
  - `flat` rectangles (roads, lots) stay bare floor, so the room's floor texture
    shows there. Put them on the terrain grid for straight edges.
  - Heights are above the floor. Raise hills at the room's edges so the sky walls'
    bases stay hidden.
  - `terrain.surface(x, y)` gives the ground height for placing things. Rooms with
    terrain need explicit `checkpoints=[(x, y), ...]`, which are lifted onto the
    ground.
  - `verify` treats the ground as solid (`is_air` excludes it), and
    `tests/test_verify.py` proves terrain stays sealed.
  - Connect it like any room: `lvl.doorway(inside_room, outside, ...)`. Build the
    building's face as world brushes along that wall (windows are `wall_art` with
    `GLASS_DARK`), and keep sky above its roofline.
- **Outdoor props.**
  - `tree(base, height, width, seed, kind="broad"|"pine")`: two crossed see-through
    planes with a generated `{` texture (rendermode 4), plus a solid trunk.
  - `car(x, y, z, facing, color)`: brushes with a paint texture.
  - `boom_barrier(pivot, facing, length, name)`: a toggling func_door_rotating;
    fire `name`, e.g. from a button. `reverse=True` if it swings down into the road.
  - Also `lamp_post`, `umbrella`, `cactus`, and `bay_lines(x0, x1, y0, y1)`
    (painted lines, non-solid; make the paint with `art.paint`).
  - Stock outdoor textures: OUT_PAVE1/2 asphalt, -0OUT_GRSS1 grass, -0OUT_GRND2B
    dry ground, OUT_WLK paving, OUT_WALL1A / OUT_WALL7 block walls, OUT_ROOF1,
    OUT_SHRB1 hedge, OUT_CAC1 cactus, STRIPES1/4 hazard stripes, {CHAINLINK and
    {FENCE fences, {GATE, {GRASS1/2 tufts, GLASS_DARK/MED, TIRES/TRK_TIRE, BLACK.
- **Campaigns (several maps).** Each map is its own script; `maps/campaign.py` says how
  they join. `MAPS = [...]` is the order a player meets them. A `Link` is one level
  transition:
  ```python
  LINK = Link("tunnel", ("office", "labs"), zone=((-512, -512, 0), (512, 512, 192)),
              origins={"office": (2128, 1632, 0), "labs": (-944, 96, 0)},
              triggers={"office": ((-128, 128, 0), (128, 192, 192)),
                        "labs": ((-128, -192, 0), (128, -128, 192))},
              build=tunnel_zone, carries=["sector_pass", "brief_pending"])
  ```
  - `build(m, lvl, origin)` makes the **zone**: the stretch both maps build
    identically (rooms, lights, signs), around the landmark at `origin`. Each map
    calls `LINK.place(m, lvl)` before `lvl.build(m)`. That builds the zone and adds
    the `info_landmark`, a `trigger_transition` over the zone and a
    `trigger_changelevel` to the other map over its `triggers` box (relative to the
    origin). Join your own rooms onto the zone's rooms (same `group` to merge).
  - Half-Life keeps the player's offset from the landmark, so they land at the same
    spot of the other map's copy. Put each map's trigger before a corner, so the
    zone's far end (which only the other map continues) is out of sight, and far from
    where the other map's trigger lands you. A `BLACK` func_wall at a dead end reads
    as the tunnel going on into the dark.
  - The origins must differ by multiples of 512, so world-aligned textures line up
    (verify checks the alignment too).
  - Global states (`logic.Flag`) carry over; nothing else does, apart from what's in
    the transition volume. Declare a map's own copy of each flag it reads (with its
    default), so loading it on its own works. `carries` lists the ones the other map
    cares about: verify explores every way of setting them before the player leaves,
    even with no door depending on them. It warns when a map reads a state that the
    previous map sets but no link carries (e.g. two maps both have a talk called
    "talk": the `talk_running` flags would collide).
  - Keys that must work across maps are Flags, not items: `props.pickup(...,
    fires=[pass_flag.on])`, then `props.card_reader(pos, facing, "lab_door",
    pass_flag, "lab_reader")` beside a door with `targetname="lab_door"`. The reader
    beeps and fires it while the flag is on, and says `denied` otherwise.
  - Build the maps together (`build office labs`) or earlier ones first: a later
    map's verify needs the earlier map's `exits.json`. Install both, or the level
    change fails in the game. `playtest <map> --links` tries each change for real.
  - Returning to a map isn't simulated (the game restores it as it was left); only
    the landing is checked.
- **Teleporters (`hlmap.teleport`).**
  ```python
  net = teleport.Network("transit", online=False)       # dark until net.start is fired
  a = net.pad("pad_chamber", (1736, 400, 0), "west", site="TEST CHAMBER")
  b = net.pad("hub_chamber", (1024, -200, 0), "south", site="TRANSIT HUB")
  net.route(a, b)                                        # two-way by default
  net.pad("hub_site2", (1216, -200, 0), "south", site="TRANSIT HUB", label="SITE 2", offline=True)
  m.add(net.entities())
  m.add(props.sign(pos, facing, image=net.diagram(), w=112, h=84))   # the network board
  ```
  - A pad is a raised disc with a sign on a post behind it (its destination). Its
    middle is a `trigger_teleport`; the player lands in front of the destination pad
    (`arrive` units toward its `facing`), facing away from it. Landing on a pad would
    send them straight on, so keep landing spots clear (verify checks).
  - An offline network is a Flag: pads are dark (their disc on the `+A` frame,
    sprite and light off) and dead until `net.start` fires. `trigger_teleport`
    ignores being fired, so the Flag is their master.
  - Stepping on flashes the screen (env_fade), with a whoosh there and a sound where
    the player lands.
  - Offline pads (`offline=True`, no route) are slots for places still to come: they
    look the part, say "OFFLINE", and show as dashed lines on `net.diagram()`. Giving
    one a route lights it with the rest. A place in another map would be a campaign
    Link whose zone has two pads (each map's trigger on the pad the other map lands
    on), so arrivals never stand on a live trigger.
- **Stairs between floors.** `steps, hole = lvl.stairs(name, lower, upper, top=(x, y),
  down="north")` makes a staircase from `upper`'s floor down into `lower`, which must
  sit directly below (`wall` units of slab).
  - The hole through the slab is sized for head clearance *including the player's
    32-unit width*. Keep that margin if you edit it; `tests/test_verify.py` guards it.
  - `m.add(steps)`, then put `props.railing(...)` on the hole's open sides.
- **Ladders.** `props.ladder(foot_on_surface, top_z, facing)` returns the visible
  see-through ladder plus the invisible `func_ladder` that does the climbing. Put it
  against something solid (the ladder itself is non-solid). Leave a gap of at least 64
  in any railing at the top; 32 is zero in collision terms.
- **Caves.** Use `cave = lvl.tunnel(name, from_room, side, center, path=[...], mouth=(w, h),
  width=, height=, roughness=, seed=, cell=32, materials=[(0.0, ROCK), (0.5, XEN)],
  blend=, scale=f(s), branches=[{"at": 0.25, "path": [...], "width":, "height":,
  "scale":, "materials": [(0.0, ROCK)]}])`. It cuts a hole in `from_room`'s `side` wall
  and grows a cave along the floor path.
  - **Branches** leave the main path at fraction `at`. They use the main materials
    unless given their own, and are addressed with `branch=1..` in
    `floor_point`/`frame`/`camera`.
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
  cutting visibility. What `props` offers:
  - **Furniture:** table, chair, crate (texture fitted per face), radio,
    filing_cabinet, bookshelf, vending_machine, barrel, pipe, and
    `front_box(..., facing, front_tex)` for anything box-shaped with a front.
  - **Wall items:** wall_art (pictures, clocks, fuse boxes, whiteboards).
  - **Structure:** railing, ladder, door_rotating, door_sliding.
  - **Lights:** ceiling_light, light.
  - **Logic:** switch, lock, pickup (item plus message plus sound, firing targets),
    card_reader (a reader that fires its target while a Flag is on).
  - **Sound:** sound_effect (once per fire; `stoppable=True` lets an "off" cut it).
  - **Presentation:** projector (with a visible additive light cone) and screen
    (toggleable slides).
  - **Xen:** crystal, xen_plantlight.
  - **Helpers:** point(classname, pos, facing, **kv), player_start, compass,
    yaw_towards.
- **Custom (non-standard) textures.** `m.add_texture("NAME", image_or_path)` makes one
  usable immediately (fit, alignment). It's written to `<map>_custom.wad` and embedded
  in the BSP with `-wadinclude`, so the map ships as one file.
  - `hlmap.art.pixel_svg(path)` rasterizes pixel-art SVGs exactly.
  - `hlmap.art.slide(size, bg, art, box, texts)` composes an image.
  - A `+0NAME`/`+ANAME` pair on a func_wall toggles when fired (slides, signs).
  - Rules: names up to 15 characters, sizes rounded to multiples of 16, one
    256-colour palette each.
- **Pickups as keys.** `props.pickup("item_security", pos, fires=["records_lock_key"],
  message=...)`. Items fire their target when picked up and drop onto the surface
  below `pos` at map start.
  - You pick an item up by touching its 32x32x16 box. A player can't get closer than
    16 units to a table edge, so an item more than about 12 in from the edge is hard
    to get, and one 16+ in can't be picked up from that side at all. Put items at the
    front edge.
  - Keep poles, lamps and props out of the way in. A pole beside the radio camp's
    table stopped players walking straight at the card 8 units short.
  - A medkit is only taken when the player is hurt, and a battery only with the
    suit.
  - The item models are tiny, so show a stand-in: `props.flat_prop(pos, w, d, tex,
    name="card_prop")`, then `pickup(..., hide=["card_prop"], invisible=True)`. The
    prop disappears when the item is taken (via a trigger_relay `killtarget`).
- **Photos of real people.** Use only images the user provides and has permission to
  use. Don't pull a person's photo from the web into a map (consent, copyright; this
  repo is public). `wall_art(..., frame="FIFTIES_DSK1")` with `m.add_texture()` frames
  any image.
- **Locks.** `m.add(props.lock("storage_lock", door.center))` then
  `door_rotating(..., master="storage_lock")`. The door rattles (locked_sound 12) and
  won't open until something fires `storage_lock_key`. The lock is a multisource plus a
  fire-once trigger_relay; a multisource with no inputs counts as unlocked.
  `props.lock(..., globalstate=grid.flag.state)` also needs that state (e.g. power) on.
- **Switchable lights.** `ceiling_light(..., name="office_lights")` becomes a func_wall
  panel with `style -3` (a "piggyback" texture light that takes the style of the real
  light with the same name) plus that named light. `props.switch(pos_on_wall,
  facing, "office_lights")` is a func_button with a click sound; each press toggles. Firing the name
  turns the room dark and flips the panel to its `+A` (off) frame.
  `zhlt_usestyle` alone does NOT switch texture lights.
- **Map state, power, conditions (`hlmap.logic`).** GoldSrc has no variables or ifs.
  These build them from stock entities, and `verify` simulates them:
  - `Flag(name)` is a true/false global state (env_global). Fire `.on`, `.off` or
    `.toggle`. Anything with a `master` can read it via `master=flag.is_on` or
    `flag.is_off`, and `props.lock(..., globalstate=flag.state)` needs it too.
  - `gate(name, target, master)` passes a fire only while the master is on.
    trigger_relay and multi_manager ignore masters, so this is the "if".
    `when(name, target, [m1, m2, ...])` chains gates, so all the masters must be on
    (AND), e.g. "power restored AND briefing given AND not talking".
  - `sequence(name, [(target, delay), ...])` is a multi_manager. Repeats are allowed,
    and more than 16 steps are chained (the engine's limit).
  - `Circuit("power")` is building power:
    - `group(lights, switched=True)` puts a named light group on the circuit and
      returns the name its switch fires. Use `props.switch(..., master=grid.live)` so
      switches are dead during an outage.
    - `emergency(lights)` adds named lights that start dark and run while the power
      is out.
    - `on_fail`/`on_restore` add effects.
    - Fire `grid.fail` (e.g. from a pickup) and `grid.restore` (e.g. a breaker
      `props.lever(..., grid.restore, master=grid.dead)`).
    - Switched-off rooms stay off through a failure and restore.
  - Everything the power touches must be named: ceiling panels via
    `ceiling_light(..., name=)`, bulbs via `light(..., targetname=)`. A named light
    gets its own style from the compiler, so give flicker as
    `pattern=logic.STYLE_FLUORESCENT`, not `style=10`.
  - `props.emergency_light(pos, facing[, stand=floor_z])` is a red lamp that starts
    dark (its func_wall shows the `+A` frame) and pulses when fired.
  - Hide or show things with `env_render` (renderamt only: `spawnflags=13`) on a named
    brush entity. The projector beam is `projector(..., name=)`.
  - `props.hud_message` shows `game_text` on screen, and `props.sound_effect` plays
    an `ambient_generic` once.
- **Talks and voice lines (`hlmap.scene.Talk`, `hlmap.voice`).**
  - `talk = scene.Talk(m, "talk", head=(x, y, z), actor="presenter")`, then
    `talk.line(subtitle, say=spoken_if_different, gesture="converse1", fire=[...])`
    for each line, and optionally `talk.interrupt(...)`. Add it with
    `m.add(talk.entities())` and start it by firing `talk.start`, e.g. from
    `props.trigger(mins, maxs, talk.start, master=...)`.
  - Each line is synthesized at build time with Windows' voices (`david`, `zira`;
    `rate` -10..10). Clips are cached in `build/<map>/voice/` by their text, so only
    changed lines are redone.
  - Each line plays from an ambient_generic at `head`, with a game_text subtitle
    (channel 4, wrapped) for as long as it lasts. `fire` cues and the actor's
    `gesture` start with it, and the next line follows after `gap`. The timeline
    comes from the real clip lengths (`talk.duration`).
  - `talk.abort` (only while running) stops it and says the interruption.
    `talk.skip` (only while running) stops it without a word: the line being said is
    cut (voices are stoppable sounds), the subtitle cleared, `on_end` fires (so what
    the talk leads to still happens) and `on_skip` too. `talk.on_start` targets fire
    as it starts, `talk.on_end` on finish, abort or skip. `talk.running` and
    `talk.skipped` are Flags: gate follow-up talks on `skipped.is_off` so a skip
    skips the scene. Set these before `talk.entities()`.
  - An aborted or skipped talk can't run again: its timeline is removed, the only
    way to cancel the fires the game has queued.
  - `scene.skip_button(pos, facing, [talks], name)` is an intercom panel with a SKIP
    button that skips whichever of the talks is running. Don't make the player wait
    for dialogue to open a door: open it on the event (the labs chamber opens at the
    flash) and let the talk run alongside.
  - Story state: use Flags ("briefing given", "power restored") and one room-wide
    `trigger_multiple` feeding `when(...)` branches. That's how the office picks
    between the briefing and the two welcome-backs. Test such branches with the
    simulator (tests/test_office.py): `World.touch(trigger)` respects its master,
    and `until=` stops mid-sequence.
  - Spell names out for the voice: `say="H L box"`.
  - Lips don't move. Stock Half-Life only lip-syncs lines from its sentences.txt,
    which a map can't extend, so gestures (scripted_sequence animations) carry the
    performance.
  - Gag NPCs that share a talk (`spawnflags` 2, no stock chatter) and make
    scientists pre-disaster (256, they won't follow). Gesture names come from the
    model; for scientists, `talkleft`, `converse1/2`, `pondering`, `wave`, `yes`,
    `no`, `checktie`, `eye_wipe`, `quicklook` and `startle` work.
- **Custom sounds.** `m.add_sound("hlbox/<map>/name.wav", wav_path)` ships any PCM
  mono WAV (8/16-bit; 11, 22 or 44 kHz; `check()` validates it). `build` installs it
  to `valve/sound/...` and writes `maps/<map>.res`. All of it is tracked in the
  manifest, and files the map no longer uses are removed. Sounds can't go inside
  the BSP the way textures can.
- **Slideshows.** `props.slideshow("slides", lo, hi, facing, [texture, ...])` gives
  a screen with any number of slides.
  - Fire `slides_next` to advance (it wraps), or `slides_step{k}` to go from slide k
    to k+1.
  - `props.slideshow_front(lo, hi, facing)` is the plane to aim a projector or a
    cover at.
  - `art.deck_slide(title, n, total)`, `art.bullets` and `art.waveform` draw slides
    in one style.
- **Signs and decals.**
  - `props.sign(pos, facing, "RECORDS\nAUTHORIZED PERSONNEL", w, h, style)` draws a
    riveted Black Mesa plate (`art.plate`: steel, red, brass, warning, white). The
    texture travels with the entity, so there's no `add_texture` call.
  - `props.sign(..., image=img)` makes a poster, and `props.sign(..., texture="SIGN74")`
    uses a stock sign. Look at `python -m hlmap tex SIGN --sheet` first; there are
    warnings, restrooms and arrows.
  - `props.decal("{OIL1", pos)` places a stock decal (decals.wad) within 5 units of
    a surface. With `name=`, it appears only when fired (e.g. a scorch mark).
  - `props.stencil("BASEMENT", pos, facing)` spells words from stock decal letters
    (yellow). The only 16-unit digits are black.
- **Where switches go.** Half-Life's `+use` takes anything within 64 units of the
  player that they're facing, and walls don't block it. Never put a switch on a wall
  shared with another room. Keep usable things at least 128 apart. `build` warns about
  both (`hlmap/checks.py`).
- **Keep doorways clear.** No stair hole, railing, crate or furniture within 64 units
  in front of a doorway on either side (`checks.doorway_clearance`, run by `build`).
  Put stairwells at the far end of a room, not by its door.
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
- **Outdoors.** See "Outdoors" under Writing a map: sky walls and ceiling, a
  `light_environment` sun with `_diffuse_light` sky fill, and `skyname` on the Map.
  Outdoor lamps don't need the power circuit.

## Gotchas

- A door with a `targetname` no longer opens on touch. It needs a trigger or button.
- `light` entities ignore "on" when already on. Anything meant to act like a switch
  must send toggle (`triggerstate 2`, or a func_button).
- Brush entities don't block light at compile time unless `zhlt_lightflags 2`.
  door_rotating sets this by default, otherwise lit rooms bleed through closed doors.
- A lightmap cell is 16 units, so a door jamb inside a 16-unit wall picks up a little
  light from the other side. That's normal Half-Life behaviour.
- `+use` reaches through walls (64 units, no line-of-sight test); see "Where switches go".
- A toggle-mode func_button (spawnflags 32) skips its master check on every second
  press. `props.switch` is non-toggle by default; keep it that way with a master.
- A multisource input toggles on EVERY fire, so a key fired twice would relock.
  `props.lock` keys fire once. A trigger_relay without `triggerstate` sends "off".
- Rendermode 2 (texture) brush entities render fullbright, ignoring their lightmap.
  Use rendermode 4 for something that should look lit when shown.
- A func_wall keyvalue `frame 1` starts it on its `+A` texture.
- A func_door_rotating turns about Z by default. `spawnflags` 64 turns it about the
  x axis (roll: an arm lying north-south), 128 about the y axis. The way it swings
  depends on the axis; flag 2 reverses it. Check with a `shots` camera that fires it.
- A `{` texture on a brush entity is only see-through with `rendermode 4`
  (`renderamt 255`).
- The first map of a Half-Life session spawns before `skill.cfg` has been read (its
  settings only exist once a server runs). Every NPC then gets 0 health ("GetSkillCVar
  Got a zero" in the console) and gets stuck after its first scripted_sequence;
  healthkits give 0 too. `play`, `shots` and `playtest` load the map once, run
  `exec skill.cfg`, then load it again. Loading from the menu or a second `map` is
  fine.
- A scripted_sequence on an NPC that's busy with another one waits and retries every
  second. Keep gestures shorter than the lines they go with.
- In a `game_text` message, a literal `\n` is a line break (the engine turns it into
  one). Lines aren't wrapped for you, and scene.Talk wraps them at 64 characters.
- Global state names are shared by every map of a campaign. Flags from `Talk`s
  (`<talk>_running`), switched light groups (`<group>_lit`) and the power (`power`)
  are global states too; give each map's talks and groups distinct names.
- A `map` console command starts a new game (clearing the transition saves); level
  changes need every map installed under `valve/maps`.
- The game queues a level change, and the next map's sign-on, at the end of the
  console buffer. Scripted waits still in the buffer hold it up, and the game sits at
  LOADING. A scripted session must end where a level change should happen
  (`playtest --links` does, then captures the window from outside the game).
- The engine brings the player across only from a map the next map links to by
  name, so a renamed test copy of a map breaks its level changes. `playtest --links`
  runs the copy under the map's own name and restores the installed BSP after.
- Any point entity outside the level makes the compile leak (the `info_texlights`
  helper entity is written at the player start for that reason, and stripped from the
  BSP after RAD: the game doesn't know it and says "Can't init info_texlights").
- Loading a map prints some stock notices that are not problems: "failed to locate
  sequence file", "couldn't exec maps/<map>_load.cfg", "Couldn't open file
  overviews/<map>.txt", "Unable to open commandmenu.txt", "Unknown command:
  VModEnable", and after a level change "Loading game from SAVE\<map>.HL1...
  ERROR: couldn't open." (no saved state on a first visit). Logic entities made
  without a position default to (0, 0, 0): give them one inside the level.
- A `trigger_teleport` can't be switched by firing it; use its `master`. The game
  sets the player's feet 1 unit over the destination's origin and turns them to its
  angles.
- A "not looped" ambient_generic can't be stopped once it plays. A looped one with a
  WAV that has no loop points plays once and stops when turned off, but the game
  counts it as playing until then and plays it again after a save is loaded or the
  map is revisited. `props.sound_effect(..., stoppable=True)` makes the stoppable
  kind; turn it off when done.
- Collision is only trusted after `verify` passes. If you change a geometry
  generator, run `python tests/test_verify.py` and add a verify-based test for it.
- A func_door_rotating needs an ORIGIN brush at the hinge (props.door_rotating adds one).
- Point entities must sit inside air. `build` warns when they're in solid or void.
- `install` refuses to overwrite a map it didn't install, which protects the stock
  maps, so don't name maps c1a0 and the like.
- Compiled maps go to `valve/maps/<name>.bsp` in the user's Half-Life install. The
  compilers reference WADs by path, and players only need halflife.wad.
