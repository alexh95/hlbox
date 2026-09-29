# Half-Life entity quick reference

Keyvalues are strings in the .map file. `spawnflags` is a bit sum. Angles are
"pitch yaw roll", with yaw 0 = east (+X) and 90 = north (+Y). "Brush" entities need
brushes; the others are point entities with an `origin`.

## World / spawn

- **worldspawn**: `wad`, `mapversion 220` (written automatically), `skyname`
  (desert, dusk, morning, night, space, 2desert, alien1...), `sounds` (CD track),
  `MaxRange` (far clip, default 4096), `chaptertitle`, `startdark 1`, `newunit 1`
  (clears the level-transition memory).
- **info_player_start**: the single-player spawn. Origin = floor + 36. `angles "0 yaw 0"`.
- **info_player_deathmatch**: the multiplayer spawn (same placement rules).
- **info_landmark**: shared point for level transitions (`targetname`).
- **trigger_changelevel** (brush): `map`, `landmark`.

## Lights

- **light**: `_light "r g b brightness"`, `style` (0 normal, 1-12 flicker/pulse
  presets, 32+ switchable), `targetname` (makes it toggleable), `_fade`, `_falloff`
  (0 default, 1 inverse, 2 inverse-square).
- **light_spot**: as for light, plus `_cone` (inner), `_cone2` (outer), `angles`
  (pitch negative = down; use `pitch` key e.g. "-90" straight down).
- **light_environment**: sun/sky light for `sky` faces. `_light`, `angles`, `pitch`,
  `_diffuse_light` (sky ambient), `_spread`.
- **info_texlights**: key = texture name, value = "r g b intensity"
  (`Map.texlight()` writes this).
- **Named lights.** The compiler gives every light targetname its own style (32+).
  `style` on a named light is ignored; `pattern` ("a" dark .. "m" normal .. "z" double,
  10 per second) sets its look while on, and `spawnflags 1` starts it dark. The
  stock pattern strings are in `hlmap.sim.STYLE_PATTERNS`.

## Brush entities

- **func_detail**: merged into the world by the compiler, never splits vis. Use it
  for furniture and trim. `zhlt_detaillevel 1`.
- **func_wall**: static solid. `rendermode`/`renderamt` for glass
  (rendermode 2 = texture, renderamt 80-120).
- **func_illusionary**: visible and non-solid. Rendermode 2 (texture) draws it
  fullbright; rendermode 4 keeps the lightmap. `renderamt 0` hides it (see env_render).
- **func_door**: sliding. `angle` (-1 up, -2 down, or yaw), `speed` 100, `wait`
  (seconds before closing, -1 stays open), `lip` (how much stays visible), `movesnd`
  1-10, `stopsnd` 1-8, `targetname`, `spawnflags` (1 starts open, 32 toggle, 256 use
  only).
- **func_door_rotating**: needs an ORIGIN brush at the hinge. `distance` 90, `speed`,
  `wait`. `spawnflags`: 2 reverse, 16 one-way, 64 X-axis, 128 Y-axis, 256 use only.
  Without one-way, it opens away from the player.
- **func_button**: `target`, `wait` (-1 stays pressed: one use), `sounds` (14 light
  switch, 21-25 levers), `angles` ("0 -1 0" moves up), `lip`, `master`. `spawnflags`
  1 = don't move, 32 = toggle, 256 = touch activates. A locked button still plays
  its `sounds`. In toggle mode, the release doesn't check the master.
- **func_breakable**: `health`, `material` (0 glass, 1 wood, 2 metal, 3 flesh, 4
  cinder, 5 ceiling tile, 6 computer, 7 unbreakable glass, 8 rocks), `spawnobject`,
  `explodemagnitude`.
- **func_pushable**: `material`, `friction`, `buoyancy`. `spawnflags` 128 = breakable.
- **func_water**: acts like a door and is used for water. `skin` -3 (water).
  Needs a `!` texture.
- **func_ladder**: invisible climbable volume. Pair it with a visible ladder brush.
- **func_wall_toggle**: shown and solid, or hidden and non-solid; each fire toggles.
  `spawnflags` 1 = starts hidden. `props.slideshow` uses one per slide.
- **func_train** / **path_corner**: moving platforms. `target` = first path_corner,
  `speed`.
- **func_rotating**: fan. ORIGIN brush, `speed`, `spawnflags` 1 = start on.
- **trigger_once** / **trigger_multiple**: AAATRIGGER texture. `target`, `delay`,
  `wait` (for trigger_multiple).
- **trigger_hurt**: `dmg`, `damagetype`.
- **trigger_push**: `speed`, `angles`.
- **trigger_teleport**: `target` = info_teleport_destination.

## Point logic

- **trigger_auto**: fires `target` at map start. `triggerstate 1` (on), `delay`,
  `spawnflags` 1 = remove after firing.
- **trigger_relay**: `target`, `delay`, `triggerstate` (0 or missing = off, 1 on,
  2 toggle), `killtarget`, `spawnflags` 1 = fire once. No `master`.
- **multi_manager**: keys are targetnames and values are delays. At most 16 targets;
  `name#1` fires `name` again. No `master` (the key would become a target).
- **multisource**: AND of its inputs (the entities whose `target` is its name). It's
  a `master` for doors, buttons, triggers and game_counters. Each fire from an input
  toggles that input. `globalstate` also requires a global state to be on.
- **env_global**: `globalstate` (a name), `triggermode` (0 off, 1 on, 2 dead,
  3 toggle), `initialstate`, `spawnflags` 1 = set the initial state at spawn.
  Global states survive level changes.
- **game_counter**: counts fires and fires `target` at `health` (limit), with
  `master`. `spawnflags` 1 = remove after, 2 = reset after. With limit 1 and reset
  it's a conditional relay (`logic.gate`).
- **trigger_changetarget**: sets the `target` of the entity named `target` to
  `m_iszNewTarget` (a relay that points somewhere else each time: state machines).
- **scripted_sequence**: makes an NPC act. `m_iszEntity` (its targetname), `m_iszPlay`
  (animation), `m_iszIdle` (loop until fired), `m_fMoveTo` (0 in place, 1 walk,
  2 run, 4 teleport, 5 turn), `m_flRadius`. `spawnflags`: 4 repeatable, 32 no
  interruptions, 64 override AI. It waits while the NPC is busy with another script.
- **monster_scientist**: `body` -1 random, 0 glasses, 1 Einstein, 2 Luther, 3 Slick.
  `spawnflags` 2 = gag (no idle talk), 256 = pre-disaster (declines to follow).
  Its origin is at the feet.
- **env_render**: sets `rendermode`/`renderamt`/`rendercolor`/`renderfx` of its
  `target` when fired. `spawnflags` 1/2/4/8 leave fx/amt/mode/colour alone.
- **env_spark**: `MaxDelay` between sparks. `spawnflags` 32 = toggled on and off by
  fires, 64 = starts on.
- **infodecal**: `texture` from decals.wad, within 5 units of a surface. With a
  `targetname` it's applied when fired. Its colour is the decal's own (e.g. {CAPS
  letters are yellow).
- **ambient_generic**: `message` = sound path (e.g. "ambience/computalk1.wav"),
  `health` (volume 0-10), `spawnflags` 1 = play everywhere, 2 = small radius,
  4 = medium, 8 = large, 16 = start silent, 32 = not toggled (loop).
- **env_sprite**: `model` "sprites/xxx.spr", `rendermode` 5 (additive), `renderamt`,
  `scale`, `framerate`.
- **env_glow**: as for env_sprite, plus `model`.
- **env_shake**, **env_fade**, **env_message**, **game_text**: effects and HUD text.
  In a game_text `message`, a literal `\n` is a line break. `channel` 1-4: each
  channel shows one message at a time.
- **cycler**: shows a model, for any `model` path (e.g. "models/scientist.mdl").
- **monster_scientist** / **monster_barney** / **monster_zombie** /
  **monster_headcrab**: `angles`, `body`, `skin`, `targetname`. Origin sits on the
  floor. Scientists and barneys follow the player when used.
- **item_healthkit**, **item_battery**, **weapon_crowbar**, **weapon_9mmhandgun**,
  **ammo_9mmclip**, **item_suit** (needed for a HUD and weapons).
