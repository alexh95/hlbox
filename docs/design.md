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
- **Limitation:** everything is axis-aligned. There are no slopes, angled walls,
  multi-level floors or non-box spaces.

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
  - `ceiling_light`: a flush panel that emits light through its texture.
  - `light`, `player_start` and `yaw_towards`.

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

### 3.8 Game integration (`hlmap/game.py`)
- **Install.** Maps go to `valve/maps/`. The tool refuses to overwrite files it didn't
  install, using a manifest in `build/installed.json`.
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
  - `--fire` triggers entities first. `@doors` opens every door and keeps it open.
- **Limitations:**
  - Needs a desktop session and takes over the screen for about 15 s.
  - Can't test collision or gameplay.
  - Timing is frame-based, not event-based.

## 4. Geometry roadmap

### 4.1 Convex geometry core (foundation for everything below)
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
The world can only be made of convex brushes; GoldSrc has no heightmaps,
displacements or collidable static meshes. Four generators, all producing brushes:

| Technique | Use | Output | Sealing |
|---|---|---|---|
| Heightfield | Outdoor ground, slopes | Two triangular prisms per grid cell, extruded down to a flat base | By construction |
| Lofted tunnel | Passages from A to B | Irregular rings along a path; one outward-extruded brush per quad | By construction (closed rings, capped ends) |
| Mesh to brushes | Organic caves, rock formations | One brush per triangle, pushed outward, from a closed mesh (noise field → surface nets / marching cubes, or imported from Blender as OBJ) | Needs a check that the mesh has no holes |
| Convex blob carving | Chambers, grottos | Irregular convex air blobs cut out of solid with the core from §4.1 | By construction; faceted look |

Integration: tunnels and blobs become new kinds of space in the level builder, and
openings can join them to rooms, e.g. `lvl.tunnel(...)` then `lvl.connect(hall, cave)`.

Quality and budget measures:
- **Grid.** Put vertices on a 32–64 unit grid, snap them to integers, and drop sliver
  triangles after snapping.
- **Visibility.** Make the rock surface `func_detail` inside a coarse world shell that
  seals the level, so the rock doesn't shatter visibility into thousands of pieces.
- **Collision.** Angled brushes can snag the player. Options are the
  `-cliptype precise` compile option, SDHLT's BEVEL/BEVELHINT textures, or turning
  collision off on the visible rock (`zhlt_noclip`) and adding a simplified CLIP hull.
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
    lock.
  - One-shot and repeatable triggers.
  - Timed sequences with `multi_manager`.
  - Hurt, push and teleport volumes.
- **NPCs and items.**
  - Scientists, security guards and monsters placed on the floor with checks.
  - `scripted_sequence` and `scripted_sentence` using the existing sentences.
  - Weapons, ammo, health, batteries and the HEV suit.
- **Multi-map campaigns.** Scripts that emit several linked maps, with
  `trigger_changelevel` plus `info_landmark` pairs placed consistently in both maps.
- **Narrative and screen effects (all stock):**
  - `game_text` for on-screen notes, triggered by a button on a note or sign.
  - `env_fade`, `env_shake` and `ambient_generic`.
  - `trigger_camera` cutscenes, reusing the screenshot camera code.

## 6. Custom content within a map-only scope

Custom assets must ship next to the map. Where they live is an open decision (§10.1).

- **Textures.**
  - Write WAD3 files from PNG: quantize to 256 colours, generate the four mip levels,
    and make sizes multiples of 16, preferably no more than 512 px.
  - Embed them in the BSP with `-wadinclude` so the map stays self-contained.
- **Models.**
  - Generate the mesh file and model script from Python (procedural props) or export
    from Blender. Compile to `.mdl` with Valve's model compiler.
  - Place them with `monster_furniture`, `monster_generic` or `cycler`. Collision is an
    unrotated box.
  - Optionally bake model shadows (`zhlt_studioshadow 1`).
  - Needs Valve's model compiler, which is a separate download.
- **Sounds.**
  - Convert to mono PCM WAV (8 or 16-bit; 11, 22 or 44 kHz), with loop points for
    ambient loops.
  - Play them with `ambient_generic`.
  - Build-time text-to-speech: voice each scripted line while building (Windows'
    built-in voices, or a local neural TTS), write the WAV plus a `game_text` subtitle,
    and trigger both together.
  - Use generic or original voices only; don't imitate the original voice actors.
- **Sprites.** A `.spr` writer for `env_sprite` and `env_glow` (glows, signs, effects).
- **Distribution.** A `.res` file listing custom content, and a zip of the map with
  its assets.

## 7. Lighting roadmap
- **More light types:** `light_spot` (a cone with pitch) and `light_environment` with
  sky brushes and `skyname` for outdoor areas.
- **Switchable lights.** A named light gets its own light style from the compiler, so
  buttons can turn it on and off. Pair this with the lit (`+0`) and unlit (`+A`)
  animated light textures.
- **Presets per room type** (office, lab, industrial, emergency), with brightness tuned
  against screenshots.

## 8. Verification roadmap
- **Tests (pytest):**
  - Geometry invariants: valid convex brushes, outward normals, and CSG results that
    add back up to the original volume.
  - Every level builder output is sealed.
  - Golden `.map` output for the example maps.
  - A compile smoke test.
- **Budget report.** Read the "Objects/Maxobjs" table from each compile step and warn
  at about 70% of any limit (§11).
- **Performance per view.** Record the `r_speeds` output (world and entity polygon
  counts) during screenshot runs to measure detail at each camera.
- **Headless renderer.** Render the compiled BSP, with textures and lightmaps, from
  camera poses without launching the game. This complements in-engine shots for quick
  iteration.
- **Map sanity checks:**
  - Point entities stand on floors, not floating.
  - Player-start clearance: 32×32×72 of free space.
  - Doorway clearance.
  - Reachability: a flood fill over walkable floor from the player start, checking step
    height (18) and jump height, reports areas that can't be reached.

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

1. **Where custom assets go.**
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
