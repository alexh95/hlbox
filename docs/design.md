# hlbox design: mapping tool capabilities

This covers what the tool can do today, what it should be able to do, and the engine
constraints behind both. The scope is **maps for stock Half-Life**. Maps run on the
unmodified game code (`valve/dlls/hl.dll`), so a map can only use the entities that
game code provides. Features that need our own game code (a mod) are recorded in §9
and are not planned for now.

## 1. Principles

- **The script is the source of truth.** Each `maps/<name>.py` builds the whole map
  in memory, and everything in `build/` can be regenerated from it. Nothing is
  hand-edited downstream.
- **Standard formats and compilers.** The output is a Valve 220 `.map`, compiled by
  SDHLT (CSG, BSP, VIS, RAD). The `.map` also opens in J.A.C.K. or TrenchBroom for
  inspection.
- **Describe the air, not the walls.** Layout helpers take the empty space as input
  and generate the solid around it, so levels are sealed by construction wherever
  possible.
- **Verify in the real engine.** Compile logs, cutaway previews and in-engine
  screenshots are the acceptance checks. A map isn't done until its screenshots
  have been looked at.
- **Don't touch stock content.** Installs only add files the tool owns and tracks,
  and never overwrite anything else.

## 2. Pipeline

```
maps/<name>.py ──build()──▶ Map (brushes + entities, in memory)
      │                      │  checks: degenerate brushes, missing textures, entities outside air,
      │                      │          openings that would leak
      ▼                      ▼
build/<name>/plan.png   build/<name>/<name>.map  (Valve 220)
                             │  SDHLT: CSG → BSP → VIS → RAD   (profiles: fast / normal / final)
                             ▼
                        <name>.bsp ── summary: errors, warnings, leak + pointfile
                             │
             install ──▶ valve/maps/<name>.bsp   (manifest-guarded)
                             │
             shots  ──▶ temporary camera variants → hl.exe → snapshot → build/<name>/shots/*.png
                                                   + console log scan
```

## 3. Current capabilities

### 3.1 Geometry (`hlmap/geometry.py`)
- **Brushes.** A `Brush` is a list of `Face`s. Each face is a plane given by three
  points, in the compilers' winding convention, plus a Valve 220 texture projection
  (u/v axes, offsets, scale).
- **Primitives:**
  - `box`: axis-aligned box.
  - `prism`: a convex 2D polygon extruded vertically.
  - `wedge`: a ramp.
  - `cylinder`: an n-sided vertical cylinder.
  - `hull`: the convex hull of a set of points.
  - Textures can be set per side (`top`, `bottom`, `sides`, `north`...).
- **Texture alignment.** World alignment (the Quake/Hammer projection axes) is the
  default, so textures tile seamlessly across brushes. `Brush.fit()` stretches exactly
  one copy of a texture over a face, with explicit axes for mirrored or oriented cases
  such as a door's two sides. `Brush.align()` sets offsets and scale.
- **Queries:** vertices, face polygons, bounds and a validity check.
- **Limitations:**
  - Vertices are found by brute force over every triple of planes, which is slow for
    many-sided brushes.
  - Brushes can be translated but not rotated.
  - There are no groups or prefabs.

### 3.2 Level builder (`hlmap/level.py`)
- **Rooms.** `room(name, mins, maxs, material)` is an axis-aligned box of air.
- **Doorways and windows.** `doorway(a, b, width, height, center, sill)` finds the
  wall two rooms share and cuts an opening through it. `sill > 0` makes it a window.
- **Other air.** `air(...)` adds alcoves, vents and similar spaces, textured like a
  given room.
- **How the solid is built:**
  1. Each room gets a solid shell `wall` units thick.
  2. The shells are merged without overlaps.
  3. All air is subtracted from them.
  4. The result is split at air boundaries and greedily re-merged.
  5. Each face is textured from the air it touches: the floor texture on upward
     faces, ceiling downward, walls sideways.
- **Materials.** Each room has a floor, wall and ceiling texture and alignment modes.
  Walls can put the texture's bottom edge on the floor. Floor and ceiling tile grids
  can be anchored to the room corner or centre.
- **Sealing check.** `check()` rejects any opening that pokes outside every room shell.
- **Room groups.** Rooms that touch or overlap are rejected unless they share a
  `group`.
- **Caves.** `Level.tunnel(...)` adds organic caves as a heightfield of columns
  (§4.3), with branches (side passages leaving the main path). The level knows each
  cave's air for entity checks and verification.
- **Stairs.** `Level.stairs(name, lower, upper, top, down)` connects stacked rooms
  through a slab hole sized for a standing player's head (including their 32-unit
  width), with fitted treads and risers.
- **Corridors at any angle.** `Level.corridor(name, path=[(x, y), ...], width, height)`
  runs a corridor along a polyline from inside one room to inside another.
  - Each segment's air, walls, floor and ceiling are convex prisms, mitred at the
    joints. Their side lines are integer lines, so segments at 0, 45 and 90 degrees
    meet at exact points.
  - The rooms' walls are carved where it passes through: the box cells it crosses
    go through the exact convex pass (`hlmap/csg.py`).
- **Corner cuts.** A room a corridor passes within a wall of (not one it connects)
  gets its corner cut, parallel to the corridor and one wall away.
  - The cut corner becomes a solid fill, and `is_air`, `room_at` and `checkpoints`
    follow the cut.
  - A cut over `max_cut` of the floor (30%), or one that reaches a doorway, is an
    error. `build` prints each cut ("storage: corner cut ... 3% of its floor").
- **Texturing convex pieces:** each face probes a point just in front of it for the
  air it faces. Floors and ceilings keep world alignment; angled walls get
  face-aligned axes, so wainscots run unbroken round the bends.
- **Limitation:** rooms themselves are still boxes (plus cut corners). There are no
  slopes or ramps; corridors and tunnels are the non-box spaces.

### 3.3 Entities and props (`hlmap/mapfile.py`, `hlmap/props.py`)
- **Entities.** `Entity(classname, brushes, kv, **keyvalues)` covers every stock
  entity. Tuples are written space-separated.
- **Map-level checks** (`Map.check()`):
  - textures missing from every WAD
  - texture names over 15 characters
  - degenerate brushes
  - rotating entities without an ORIGIN brush
  - a missing player start
- **Props:**
  - `detail`: wraps brushes in a `func_detail`.
  - `table` and `chair`: made from brushes.
  - `door_rotating`: hinge side, one-way swing, sounds and a wait time. Handles the
    ORIGIN brush and mirrored door textures.
  - `door_sliding`.
  - `ceiling_light`: a flush panel that emits light through its texture. With `name=`
    it becomes switchable: a func_wall with `style -3`, a "piggyback" texture light
    that follows a named light's switchable style.
  - `switch`: a func_button (optionally dead without its `master`).
  - `lock`: a multisource plus a fire-once trigger_relay "key"; doors use it as their
    `master`. With `globalstate=` it also needs a global state (e.g. power).
  - `lever`: a handle that slides up when used (a moving func_button).
  - `emergency_light`: a lamp that starts dark and pulses when fired, on the wall or
    on a pole.
  - `sign`: nameplates (`art.plate`), posters (any image) or stock signs. Its texture
    travels with the entity (`Entity.textures`).
  - `decal` and `stencil`: stock decals (infodecal), and words spelled from decal
    letters.
  - `hud_message` and `sound_effect`: `game_text` and a one-shot `ambient_generic`.
  - `slideshow`: any number of slides (one func_wall_toggle each), with a relay that
    `trigger_changetarget` re-aims at every step.
  - `trigger`: a trigger_once or trigger_multiple volume, optionally with a master.
  - `crate`, `crystal` and `xen_plantlight`.
  - `light`, `point`, `player_start` and `yaw_towards`.
  - Doors block light while compiling (`zhlt_lightflags 2`).
- **Target checks.** `Map.check()` also flags any `target`/`master`/`killtarget`
  that names no entity. A lock whose name matches nothing would leave the door unlocked.

### 3.4 Lighting
- **Point lights** with colour and brightness.
- **Texture lights.** `Map.texlight()` writes an `info_texlights` entity. Different
  light textures can get different brightness.
- **Compile profiles:**
  - `fast` has no bounced light, so ceilings come out black. Use it for layout only.
  - `normal` uses 8 bounces.
  - `final` adds full vis, `-extra` supersampling, 12 bounces and ambient occlusion.

### 3.5 Textures (`hlmap/wad.py`)
- **Reading.** A WAD3 reader over halflife, liquids, xeno and decals, plus SDHLT's
  tool textures.
- **Search.** Name lookup, sizes, and decoding to images.
- **Contact sheets.** `python -m hlmap tex <pattern> --sheet` renders a labelled grid
  so textures are chosen by eye.

### 3.6 Compile (`hlmap/compile.py`, `hlmap/setup.py`)
- **Setup.** `setup` downloads SDHLT v1.3.0 and checks its SHA-256 checksums.
- **Compiling.** Runs the four compile tools with profile options and saves a combined
  log.
- **Reporting.**
  - Errors and warnings are summarized.
  - A budget line reports the share of each engine limit used, read from the
    compiler's own chart, and warns at 70%.
  - A leak names the entity it was found from, keeps the pointfile, and draws the leak
    path on the plan preview.

### 3.7 Previews (`hlmap/preview.py`)
- **Cutaway views.** `top` shows a plan cut at a height. `x` and `y` are sections cut
  by a vertical plane.
- **What's drawn:**
  - Surfaces beyond the cut in the average colour of their texture.
  - Cut solids in dark grey.
  - Entity brushes tinted by class, with ORIGIN brushes marked.
  - Point entities with labels and facing arrows.
  - Room names and sizes, a 64-unit grid with coordinates, and the leak path.

### 3.8 Verification (`hlmap/verify.py`, `hlmap/checks.py`, `tests/`)
A clean compile doesn't mean clean collision, so `build` verifies the compiled BSP
against the level's intended air and refuses to install on failure:
- **Holes.** Every empty leaf of the world's BSP trees is computed exactly as a convex
  polytope, for the sight/bullet hull and the standing and crouching player hulls. Any
  empty region reaching more than 1 unit into intended solid is a hole.
- **Invisible walls.** Solid leaves of the player hulls must not contain positions
  where the player's box is inside air and touches no intended brush. The box is
  tested against brush planes pushed out by the box, as the compiler does.
- **Walkability and progression.** From the start, the player walks on foot (steps
  up to 18, jumps up to 45, falls under 600, `func_ladder` volumes). Every
  progress-relevant action is tried in every order: pickups, buttons and trigger
  volumes within reach. Each one's effects are simulated through the entity logic
  (§3.10). Doors block while locked.
  - Relevance is a static backward slice from the doors: whatever can change a lock,
    a global state it reads, or whether such a chain can run. Light switches and
    slide remotes don't multiply the states.
  - Every room, cave stretch and `m.checkpoints` entry must be reached, and the
    shortest line of play is logged with what each step changes.
- **Lockout.** Every state of play must still be able to reach the state that sees
  everything. Otherwise the line of play leading there is reported (e.g. a one-shot
  breaker used before the outage, which locks a power-dependent door for good).
- **Darkness.** There's no flashlight without the HEV suit. For every state on the
  way, the way to the next useful objective must be visible.
  - `FloorLight` reads every upward face's lightmap samples per light style.
  - The simulated light states give each style's level (patterns averaged).
  - A position is seeable within 64 units of a floor at 24 or more (max of R, G, B,
    so red emergency light counts).
  - A 0-1 search finds the fewest units walked unseeing. Over 192 fails.
  - Calibration on the office: lit rooms read 110-220, a switched-off hall 6-8,
    dim cave stretches 40-80. Without its emergency lamps, the route from the
    card to the breaker crossed 1,688 dark units.
- **Decals.** Every infodecal must have solid within 4 units (the game traces 5
  units from it), or it silently doesn't appear.
- **Pickups.** Every item is walked at straight, as a player who has spotted it does.
  - The walk starts from each compass direction where there is open ground 72-104
    units out, clear to within 40 units of the item.
  - It moves in 1-unit steps, with 18-unit step-ups and gravity, and doesn't slide
    along obstacles.
  - It succeeds if the player's box touches the item's 32x32x16 box where the item
    comes to rest.
  - If half or more of the approaches stop short, a keyed item fails.
  - Playtest origin: the access card could be reached, but walking straight at it
    stopped 8 units short at a lamp pole. The loose reach test and the grid walk
    both passed it. `playtest --pickups` agreed with the model on all 6 approaches
    after the fix, and on the failing one before it.
- **Coverage.** Every generated face with real air in front has a matching face in
  the BSP. That catches polygons the compiler deleted, which you'd see through.
- **Self-tests.** `tests/test_verify.py` compiles rooms with known defects and checks
  each one is caught:
  - holes, invisible walls and missing faces;
  - a key locked behind its own door;
  - stairs whose hole is too short (the too-short formula makes the test fail);
  - a power-gated door with a one-shot breaker (a lockout);
  - a route to the breaker with no emergency lights (dark), and the same route lit;
  - a card on a table behind a pole (the playtest bug), and the same card at the edge;
  - a diagonal corridor that cuts a room's corner: sealed in every hull, walkable, and
    the cut room stays unreachable (the corridor mustn't break into it).
  A clean room must pass. `tests/test_logic.py` checks the logic helpers against the
  simulator without compiling (switch positions through an outage, gates, chaining
  past 16 multi_manager targets, locks needing key and power).
- **Gameplay lint** (`checks.py`):
  - `use_reach` flags usable entities that can be `+use`d from more than one room
    (`+use` reaches 64 units through walls), and pairs close enough to be confused.
  - `doorway_clearance` flags stair holes, railings and furniture within 64 units in
    front of a doorway. Playtest feedback: a stairwell in front of a door reads as
    blocked, even though the 44-unit path around it was walkable.

### 3.9 Game integration (`hlmap/game.py`)
- **Install.** Maps go to `valve/maps/`, with their sounds and `.res`. The tool refuses
  to overwrite files it didn't install, using a manifest in `build/installed.json`
  (map names and file paths). It removes this map's earlier files that it no longer
  uses.
- **Play.** `play` launches Half-Life straight into a map.
- **Screenshots** (`shots`):
  1. For each camera, write a temporary copy of the BSP with extra entities: a
     `trigger_camera` at the pose, fired by a `trigger_auto`, with the player parked
     behind the camera.
  2. Run a generated config that loads each copy, waits a set number of frames, runs
     `snapshot`, then quits.
  3. Collect the BMPs as PNGs.
  4. Scan the console log.
  5. Delete all temporary files and restore the registry video settings.
  - Cameras can be named, and defined in `build()` as `m.cameras`. `--only` retakes
    a subset.
  - Each camera can toggle entities first (`fire`), in order and 0.3 s apart, or at
    a given time (`("name", seconds)`). `@doors` opens every door and keeps it open.
  - `--console "developer 2" --log` saves the game console, which shows every entity
    that received a trigger.
- **Playtests** (`playtest`): the same temporary-map mechanism, without a camera.
  - The player spawns at a scripted pose, targets can be fired first, then a script
    of console commands and frame waits runs (`+forward`, `+use`, ...).
  - With `developer 2`, the console log shows everything that fired. That's how a
    pickup or a button press is confirmed.
  - `--pickups` walks at every item from the verifier's approach positions, one map
    load each. The item is swapped for an item_security, which has the same touch
    box but no "does the player need it" rule. It then reports whether the game
    agrees with the static model.
- **Limitations:**
  - Needs a desktop session and takes over the screen for about 15 s.
  - Movement is scripted input, not a bot. It checks specific walks, not whole
    playthroughs.
  - Timing is frame-based, not event-based.

### 3.10 Map logic and state (`hlmap/logic.py`, `hlmap/sim.py`)
GoldSrc has no variables or conditions, but stock entities can build them. These
helpers do, and the verifier runs them:
- **`Flag`** is a boolean in the engine's global state table. It's a pair of
  env_globals (the state and its inverse), so both "on" and "off" can be masters
  through a multisource with `globalstate`. Global states survive level changes.
- **`gate`** is a conditional relay: a game_counter with limit 1, reset on fire, and
  a `master`. trigger_relay and multi_manager have no master support. **`when`**
  chains gates for AND conditions.
- **`sequence`** is a multi_manager with repeated targets (`name#1`), chained past
  the engine's 16-target limit.
- **`Circuit`** is building power:
  - Each switched light group has a Flag for its switch position.
  - Failure and restore toggle a group through a gate on that flag, so a group
    switched off stays off.
  - Unswitched groups toggle directly. Emergency groups start dark.
  - Both events are gated on the power flag, so neither can run twice.
  - Switches get `master=grid.live`, so positions can't change during an outage.
- **Simulator** (`sim.World`): the state that matters for play, from the compiled
  entity lump.
  - State covered: global states, multisource inputs (with HLSDK's quirks: inputs
    toggle, a non-member flips the last input), lights (ShouldToggle), func_wall
    frames, game_counters, env_render, removed entities (items, fire-once relays,
    killtargets), pressed buttons (toggle buttons skip the master on release) and
    opened doors.
  - Events run in time order (delays, multi_manager timings).
  - `style_levels()` gives every light style's brightness in the current state,
    which feeds the darkness check.
- **In-engine check:** the office's `power_restored` camera switches the conference
  lights off, fails the power, then resets the breaker. In the game, the conference
  stays dark while the projector comes back, matching the simulation.

## 4. Geometry roadmap

### 4.1 Convex geometry core (foundation for everything below)
**Done:** `hlmap/csg.py`, exact (rational) convex solids with intersection, `subtract`
into convex fragments, face ordering, redundant-plane removal, and exact .map face
points. Level corridors and corner cuts use it. A verify test compiles a diagonal
corridor that cuts a room's corner, with no holes, no invisible walls, every face
present, and the cut room still closed off. Still to do below: rotation transforms,
prefabs, and general (sloped) air volumes.
- **Face polygons ("windings").** Compute each face's polygon by clipping a huge
  starting polygon with all the other planes. This is O(n²) and replaces the
  brute-force vertex search.
- **Operations:**
  - `split(brush, plane)`.
  - `subtract(brush, cutter)`, which yields convex fragments.
  - `merge_coplanar`.
  - Snapping to integer coordinates, then dropping faces that collapse.
- **Transforms:** translate, rotate and mirror, with texture lock (the texture axes
  move with the brush).
- **Groups and prefabs:** a named collection of brushes and entities, placed with a
  transform.
- **General air volumes.** The level builder accepts any convex air volume, not just
  boxes. That covers angled walls, sloped ceilings, arches and ramps. Assigning
  textures then needs overlap tests between coplanar polygons instead of rectangles.

### 4.2 Architectural helpers
**Done:** stairs between stacked rooms (`Level.stairs`), railings, ladders on a solid
backing, and a two-storey room with a mezzanine (the records room in
`maps/office.py`).

- **Stairs:** a `stairs(start, end, width)` helper with 16-unit risers, and an
  optional invisible CLIP ramp so walking up isn't bumpy.
- **Openings with content:**
  - Windows with glass: a `func_wall` with `rendermode` 2 and `renderamt` of about
    100, or a breakable version.
  - Door frames, baseboards and trim: thin `func_detail` strips along room edges.
- **Structure:** pillars, beams and raised floors.
- **Multiple floors:** vertically stacked rooms joined by stairs, lifts (`func_train`
  or `func_door` platforms) and ladders (a `func_ladder` volume plus a visible
  ladder brush).

### 4.3 Terrain and caves
**Status:** caves are implemented as a heightfield (`hlmap/cave.py`, used by
`maps/office.py`). All verification checks pass: no holes in any hull, no invisible
walls, full reachability, full face coverage.

A cave is a floor path leaving a room through a wall hole. Around the path, an
axis-aligned grid (32 units) stores a floor and ceiling height per vertex:
- the floor is flat near the path;
- towards the edge the floor rises and the ceiling falls until they meet (closed);
- noise is smoothed in 2-D;
- the first cell row is exactly the doorway rectangle, then it flares;
- materials change along the length with a ragged, noise-driven boundary.

Every triangle becomes a floor column and a ceiling column, or one full column where
it's closed. Cells away from the cave are merged solid columns. All vertices are
integers and every side is a vertical plane through a shared grid edge, so it's exact
by construction. The office cave comes to 1,040 world brushes: 11.8% of clipnodes and
9.4% of world leaves. The compiler still prints 6 ambiguous-leaf warnings (3 in the
large-monster hull), but verification shows none of them opens a hole or makes an
invisible wall.

**What failed first: lofted ring shells.** The first version lofted irregular rings
along the path. Each surface triangle became a thin (8-unit) slanted rock plate. It
compiled without leaks and looked right in screenshots. Playtesting then found
walk-through walls, walk-through cave walls and a see-through polygon. The verifier
reproduced all three on that BSP: empty player-hull regions over 100 units deep inside
the rock. Thin slanted plates, rounded vertex positions and plates poking through each
other at creases produce misclassified ("ambiguous") collision leaves and deleted
faces. Measured variants of that design, all rejected:

| Sealing | Leak | World leaves | Clipnodes | Ambiguous-leaf warnings (hulls 0/1/2/3) |
|---|---|---|---|---|
| Hidden rooms around func_detail rock | no | 36.1% | 16.7% | 0/5/0/5 |
| Rock shell, back faces along vertex normals (default) | no | 7.5% | 9.8% | 3/9/7/6 |
| Rock shell, back faces along face normals | **leaks** | ~33% | 9.4% | 11/10/11/7 |
| Default + thicker rock (16) | no | 7.6% | 9.9% | 31/6/3/9 |
| Default + `-cliptype precise` | no | 7.5% | 11.7% | 3/29/18/27 |

Lessons:
- Face-normal extrusion leaves wedge gaps that the compiler treats as leaks.
- "No leak" and good screenshots say nothing about player collision.
- Generated geometry needs thick, simple, exactly shared brushes, and verification of
  the compiled hulls.

The world can only be made of convex brushes; GoldSrc has no heightmaps,
displacements or collidable static meshes. Four generators, all producing brushes:

| Technique | Use | Output | Sealing |
|---|---|---|---|
| Heightfield | Outdoor ground, slopes, **caves (done: floor + ceiling heightfields)** | Triangular columns per grid cell | By construction |
| Lofted tunnel | Passages from A to B | Irregular rings along a path; one outward-extruded brush per quad | **Tried and rejected:** thin slanted plates break the collision hulls |
| Mesh to brushes | Organic caves, rock formations | One brush per triangle, pushed outward, from a closed mesh (noise field → surface nets / marching cubes, or imported from Blender as OBJ) | Needs a check that the mesh has no holes |
| Convex blob carving | Chambers, grottos | Irregular convex air blobs cut out of solid with the core from §4.1 | By construction; faceted look |

Integration: tunnels and blobs become new kinds of space in the level builder, and
openings can join them to rooms, e.g. `lvl.tunnel(...)` then `lvl.connect(hall, cave)`.

Quality and budget measures:
- **Grid.** Put vertices on a 32–64 unit grid, snap them to integers, and drop sliver
  triangles after snapping.
- **Visibility.** Heightfield rock is structural world geometry. It blocks vis, and
  its big columns keep leaf counts moderate (9% for the office cave).
- **Collision.** Prefer thick convex brushes with vertical sides, as the heightfield
  uses. `-cliptype precise` made the thin-plate design worse (more ambiguous leaves).
  Every generator must pass `verify`.
- **Look.** RAD can smooth lighting across faces meeting at a shallow angle (default
  threshold 50°; `info_smoothvalue` sets it per texture), which makes faceted rock read
  smooth. Rock textures use world or face alignment.
- **Budgets.** Every generator reports its brush count, and the compile budget report
  (§8) flags when clipnodes get close to the limit.

## 5. Entities and map logic roadmap

- **Entity validation from FGD files.** Parse `sdhlt.fgd` plus a Half-Life FGD to check
  classnames, keys, value types and spawnflag names. That catches typos and lets the
  entity list be looked up.
- **Logic helpers** for common patterns:
  - A button that opens a door.
  - A locked door with a key or keycard, using `multisource` or `env_global` as the
    lock. Done: `props.lock` (a multisource plus a fire-once key, optionally needing a
    global state), and `props.pickup` (e.g. the access card, `item_security`) that
    fires the key. The progression check proves the key is reachable before its door.
  - One-shot and repeatable triggers.
  - Timed sequences with `multi_manager`. Done: `logic.sequence`.
  - Map state and conditions. Done: `logic.Flag`, `logic.gate`, and `logic.Circuit`
    for power failures (§3.10).
  - Hurt, push and teleport volumes.
- **NPCs and items.**
  - Scientists, security guards and monsters placed on the floor with checks.
  - `scripted_sequence` and `scripted_sentence` using the existing sentences.
  - Weapons, ammo, health, batteries and the HEV suit.
- **Multi-map campaigns.** Scripts that emit several linked maps, with
  `trigger_changelevel` plus `info_landmark` pairs placed consistently in both maps.
- **Narrative and screen effects (all stock):**
  - `game_text` for on-screen notes, triggered by a button on a note or sign.
    Done: `props.hud_message`.
  - `env_fade`, `env_shake` and `ambient_generic`. Done: `props.sound_effect`; the
    office's power failure uses env_shake.
  - Signage. Done: `props.sign` (generated plates, posters, stock signs), and
    `props.decal`/`props.stencil` (stock decals, triggered decals).
  - `trigger_camera` cutscenes, reusing the screenshot camera code.

## 6. Custom content within a map-only scope

Textures ship inside the BSP. Other assets ship next to it, in namespaced folders
inside `valve/` that the install manifest tracks (§10.1, option a).

- **Textures. Done.**
  - `Map.add_texture(name, image)` goes to `wadwrite.py`, which quantizes to 256
    colours, builds the four mip levels and rounds sizes to multiples of 16.
  - `-wadinclude` embeds the result in the BSP. Toggle pairs (`+0`/`+A`) and
    transparent (`{`) textures work.
  - `art.py` rasterizes pixel-art SVGs, draws sign plates and composes slides. Example:
    the office briefing's 12 slides, Boxworth the crate mascot, Gerald the Employee of
    the Month and the hall's safety poster, all drawn in code.
- **Models.**
  - Generate the mesh file and model script from Python (procedural props) or export
    from Blender. Compile to `.mdl` with Valve's model compiler.
  - Place them with `monster_furniture`, `monster_generic` or `cycler`. Collision is an
    unrotated box.
  - Optionally bake model shadows (`zhlt_studioshadow 1`).
  - Needs Valve's model compiler, which is a separate download.
- **Sounds. Done.**
  - `Map.add_sound(name, wav)` takes a mono PCM WAV (8 or 16-bit; 11, 22 or 44 kHz),
    which `check()` validates. It installs to `valve/sound/<name>` and is listed in
    `maps/<map>.res`.
  - Play them with `ambient_generic` (`props.sound_effect`). Ambient loops need
    loop points; without them, a "looped" sound plays once.
- **Voice. Done** (`hlmap/voice.py`, `hlmap/scene.py`).
  - Build-time text-to-speech with Windows' built-in voices (System.Speech: David,
    Zira), written as 22 kHz 16-bit mono.
  - Clips are trimmed, normalized and cached by text and settings.
  - `scene.Talk` turns lines into a timeline from the real clip lengths: the voice
    at the speaker's head, a `game_text` subtitle, cues and gestures, an abort that
    says an interruption, and a `running` flag.
  - Generic voices only; no imitating the original voice actors.
  - Limitation: no lip-sync. Stock Half-Life lip-syncs only `sentences.txt` lines,
    which only a mod can add to.
  - The office briefing has 12 slides and 13 lines, 142 s in all. Walking back in
    after restoring the power gets one of two welcome-backs, depending on whether
    the briefing was given. That's chosen by `logic.when` on three Flags, and
    `tests/test_office.py` simulates each path. In-game playtests
    confirmed the whole run: all 12 lines, 11 slide steps and 9 gestures, with the
    remote unlocking at the end. A power cut 12 s in stopped it after line 2 with the
    interruption. The build checks gesture names and lengths against the model's
    sequences (`hlmap/model.py`).
  - Found in playtests: the first map of a Half-Life session spawns its NPCs before
    `skill.cfg` is read, so they get 0 health and stop taking scripted sequences
    after one. `play`, `shots` and `playtest` load the map, read `skill.cfg`, then
    load it again.
- **Sprites.** A `.spr` writer for `env_sprite` and `env_glow` (glows, signs, effects).
- **Distribution.** A `.res` file listing custom content, and a zip of the map with
  its assets.

## 7. Lighting roadmap
- **More light types:** `light_spot` (a cone with pitch) and `light_environment` with
  sky brushes and `skyname` for outdoor areas.
- **Switchable lights.** Done. A named light gets its own light style from the
  compiler, so buttons can turn it on and off. Texture lights follow it when their
  brush entity has `style -3` and the same targetname (sdHLCSG `qcsg.cpp`); the entity
  also flips its lit `+0` texture to the unlit `+A` frame. `zhlt_usestyle` is only read
  after that style check, so on its own it does nothing.
- **Presets per room type** (office, lab, industrial, emergency), with brightness tuned
  against screenshots.

## 8. Verification roadmap
Done: compiled-hull hole detection, invisible-wall detection, on-foot walkability
with keys and locked doors, face coverage, the verifier self-tests, the `+use` reach
lint and the budget report (§3.6, §3.8).
- **More tests (pytest):**
  - Geometry invariants: valid convex brushes, outward normals, and CSG results that
    add back up to the original volume.
  - A verify-based test per geometry generator (rooms, caves).
  - Golden `.map` output for the example maps.
- **Return paths.** Walkability checks the way there, not back. Check that a player
  can always return from every area (no one-way drops that trap them).
- **Performance per view.** Record the `r_speeds` output (world and entity polygon
  counts) during screenshot runs to measure detail at each camera.
- **Headless renderer.** Render the compiled BSP, with textures and lightmaps, from
  camera poses without launching the game. This complements in-engine shots for quick
  iteration.
- **Map sanity checks:**
  - Point entities stand on floors, not floating.
  - Player-start clearance: 32×32×72 of free space.
  - Doorway clearance.
  - Reachability with gravity (see Walkability above).

## 9. Out of scope: features that need a mod

Explored, not planned. These need our own game code: a game folder with a server DLL
and a client DLL built from a Half-Life SDK, launched with `-game hlbox`.

| Feature | Why a map can't do it |
|---|---|
| Inventory with slots; pick up, carry and place objects with a chosen rotation | No carry mechanic or inventory in stock code (only push/pull boxes); needs player state, networking and a HUD |
| On-screen UI beyond text (image notes, panels, cursor) | The HUD is drawn by the client DLL |
| Speech generated during play | The engine only plays sound files; it can't receive generated audio |
| Replacing the speech word set or voice | `sound/sentences.txt` is one global file for the game |
| Hidden stats, XP, levelling, abilities | No player variables or maths; map logic only has flags and counters |

Notes for if that changes:
- Pick a maintained SDK base.
- Define each custom entity once and generate the C++ loading and save code, the FGD
  and the Python helpers from that one definition.
- Choose between hard-coded C++ features and an embedded scripting language, as Sven
  Co-op does with AngelScript. Saving script state in savegames is the hard part.
- Brush-built objects collide with their rotated shape; model-based objects only as
  unrotated boxes.

## 10. Open decisions

1. **Where custom assets go.** Decided: option (a) for sounds (textures are embedded
   in the BSP).
   - Option (a): namespaced folders inside `valve/` (`models/hlbox/`, `sound/hlbox/`),
     tracked by the install manifest so they can be removed cleanly.
   - Option (b): `valve_addon/`, which is only read when the player enables custom
     addon content in the game options.
   - Textures avoid the question by being embedded in the BSP.
2. **Valve's model compiler.** Download it when the model pipeline starts; it needs
   approval.
3. **numpy.** Pure Python is fine for today's geometry. Large terrain or noise grids
   would benefit from numpy, which is a new dependency and needs approval.
4. **Campaign structure.** One script per map, or one script emitting a linked set of
   maps.

Suggested order:
1. The convex geometry core, tests and the budget report (§4.1, §8).
2. Entity validation and logic helpers (§5).
3. Architectural helpers (§4.2).
4. Terrain and caves (§4.3).
5. The custom content pipeline (§6).
6. Multi-map campaigns.

## 11. Engine and compiler limits

These are the maximums from SDHLT's compile chart. Entries marked * are engine-side
limits the chart also tracks.

| Object | Max | Object | Max |
|---|---|---|---|
| models (world + brush entities) | 512 | clipnodes | 32,767 |
| planes | 32,768 | leaves | 32,760 |
| vertexes | 65,535 | * world leaves | 8,192 |
| nodes | 32,767 | marksurfaces | 65,535 |
| texinfos | 32,767 | surfedges | 512,000 |
| faces | 65,535 | edges | 256,000 |
| * world faces | 32,768 | * lightmap blocks (AllocBlock) | 64 |
| entity data | 2 MB | visibility data | 8 MB |

Other limits:
- **Precache:** 512 models and 512 sounds per map.
- **Coordinates:** geometry within ±32,768 (SDHLT's default world extent); entities
  within ±8,192 (engine).
- **Texture names:** 15 characters maximum.
- **Texture sizes:** multiples of 16.
- **Player:** 32×32×72 (36 crouched), step height 18, eye height 64.
