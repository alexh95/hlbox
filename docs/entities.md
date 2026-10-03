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

## Teleporters

`hlmap.teleport` writes these; see CLAUDE.md "Teleporters".

- **trigger_teleport** (brush): `target` = where to (usually an
  info_teleport_destination), `master` (the only way to switch it; firing it does
  nothing). `spawnflags` 1 = monsters too, 2 = not players. The player's feet land 1
  unit over the target's origin, turned to its `angles`, with no speed.
- **info_teleport_destination**: `targetname`, `angles`. Put it on the floor.
- **env_sprite**: `model` (e.g. "sprites/exit1.spr"), `rendermode` 5 (additive),
  `renderamt`, `rendercolor`, `scale`, `framerate`, `spawnflags` 1 = starts on. Fire
  it to toggle.
- **env_fade**: `duration`, `holdtime`, `renderamt`, `rendercolor`; `spawnflags` 1 =
  fade from the colour (a flash), 2 = modulate, 4 = only the player who fired it.
- Pads into other maps (`link=`) use a **trigger_changelevel** with `spawnflags` 2
  (use only) and a `targetname`, fired by the pad's depart sequence; see Level
  transitions.

## Level transitions

`hlmap.campaign.Link.place()` writes all three; see CLAUDE.md "Campaigns".

- **info_landmark**: `targetname`. The same name must be in both maps, once each. The
  player keeps their offset from it (translation only, no rotation), so the geometry
  around it must match.
- **trigger_changelevel** (brush): `map` (next map), `landmark`. Touching it changes
  level (`spawnflags 2` = only when fired). Put the other map's trigger well away from
  where the player lands, or they bounce straight back.
- **trigger_transition** (brush): `targetname` = the landmark's name. Only entities
  inside it travel with the player (without one, anything in the landmark's view that
  can travel: monsters and items). The changelevel must be inside it, or the game
  refuses to change level ("Player isn't in the transition volume").
- What carries over: the player (health, suit, weapons), entities in the transition
  volume, and every global state (`env_global`). An `env_global` with `spawnflags 1`
  only sets its initial state if the state doesn't exist yet, so carried states win.
  Returning to a map restores it as it was left.

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
  `locked_sound` 2 = access denied (played when its `master` says no).
- **func_door_rotating**: needs an ORIGIN brush at the hinge. `distance` 90, `speed`,
  `wait`. `spawnflags`: 2 reverse, 16 one-way, 64 X-axis, 128 Y-axis, 256 use only.
  Without one-way, it opens away from the player.
- **func_button**: `target`, `wait` (-1 stays pressed: one use), `sounds` (14 light
  switch, 21-25 levers), `angles` ("0 -1 0" moves up), `lip`, `master`. `spawnflags`
  1 = don't move, 32 = toggle, 256 = touch activates. A locked button still plays
  its `sounds`. In toggle mode, the release doesn't check the master.
- **func_breakable**: `health`, `material` (0 glass, 1 wood, 2 metal, 3 flesh, 4
  cinder, 5 ceiling tile, 6 computer, 7 unbreakable glass, 8 rocks), `spawnobject`,
  `explodemagnitude`, `target` (fired when it breaks). `spawnflags` 1 = only by a
  trigger. A `{` texture needs `rendermode 4` to be see-through.
- **func_pushable**: `material`, `friction`, `buoyancy`. `spawnflags` 128 = breakable.
- **func_water**: water that moves like a door (`speed`, `wait` -1, `lip`, `angle`
  -1 up / -2 down; it moves its size - 2 - lip). `skin` -3 (water). Needs a `!`
  texture. Named, it moves when fired (props.water_mover: a tank draining, a
  cistern flooding). Not solid.
- **func_plat**: a lift, placed at its top. `height` (travel; default its size - 8),
  `speed`, `movesnd`, `stopsnd`. Unnamed, it starts at the bottom and rises when
  stood on, then returns; named, it waits at the top for a trigger.
- **func_rot_button**: a turning button (a valve wheel). ORIGIN brush at its axis;
  `distance` (degrees), `speed`, `wait` (-1 stays turned), `spawnflags` 64 X axis,
  128 Y axis (Z by default), 1 not solid, 32 toggle.
- **func_ladder**: invisible climbable volume. Pair it with a visible ladder brush.
- **func_wall_toggle**: shown and solid, or hidden and non-solid; each fire toggles.
  `spawnflags` 1 = starts hidden. `props.slideshow` uses one per slide.
- **func_train** / **path_corner**: moving platforms. `target` = first path_corner,
  `speed`.

## Trains and tracks (hlmap/track.py builds these)

- **path_track**: a node of track. `target` = the next node (forward), `altpath` = a
  switch's other way. Fired, a node with an altpath toggles between the two ("off"
  throws it, "on" sets it back); one without toggles `spawnflags` 1 (disabled: trains
  stop at the node before). `netname` fires when a train stops at it at a dead end,
  `message` when one passes. `spawnflags` 4 makes the altpath apply going backward, 8
  takes the controls from the player, 32768 starts it switched. Each node keeps ONE
  previous node: the last whose link points at it as the map starts (entity order).
- **func_tracktrain**: the drivable train. Built facing WEST (the engine turns it to
  face the track + 180), ORIGIN brush required (and no `origin` key: SDHLT reads it
  as a second ORIGIN brush). `target` = its first node, `height` = its origin over
  the nodes, `wheels` = how far ahead it looks to face along the track (and, for a
  lift, how close to its centre it must stop), `speed` (top speed; +forward/+back
  step a quarter at a time), `startspeed`, `dmg` (to what blocks it), `sounds` 1-6
  (`plats/ttrain*.wav`), `volume` (x0.1), `bank`. `spawnflags` 1 no pitch, 2 no
  player control, 4 forward only, 8 not solid. A player standing on it presses +use
  to drive (anywhere on it, unless a func_traincontrols says where). It passes through
  walls: only the track stops it.
- **func_traincontrols**: a box (AAATRIGGER) on the train, `target` = the train: the
  player must stand in it to drive. Optional.
- **func_trackchange**: a track lift. ORIGIN brush at its centre, built at the top;
  `toptrack`/`bottomtrack` = nodes at its two levels (the nearest of each named
  node's chain), `train`, `height` (travel), `speed`, `rotation` (degrees turned on
  the way), `spawnflags` 8 starts at the bottom, `movesnd`/`stopsnd`. Fired, it moves
  to its other level, with the train if that's stopped on it (within `wheels` of its
  centre, on or next to its node); close but not on it, it buzzes and stays. It
  disables its node at the level it isn't at.
- **func_tank** / **func_tankcontrols**: a mounted gun the player can use. ORIGIN at
  the pivot, built pointing east, `angle` = where it points; `yawrange`/`pitchrange`
  (degrees each way), `yawrate`/`pitchrate`, `barrel` (muzzle distance), `bullet` (1
  9mm, 2 MP5, 3 12mm), `bullet_damage`, `firerate`, `spawnflags` 32 = player
  controllable. func_tankcontrols: a box (AAATRIGGER) where the gunner stands,
  `target` = the gun; +use there to take it, +use again to let go.
- **func_rotating**: fan. ORIGIN brush, `speed`, `spawnflags` 1 = start on.
- **trigger_once** / **trigger_multiple**: AAATRIGGER texture. `target`, `delay`,
  `wait` (for trigger_multiple).
- **trigger_hurt**: `dmg` per second (dealt half each half second), `damagetype`
  (1048576 acid, 256 shock, 8 burn, 32 fall), `spawnflags` 2 = starts off. Monsters
  die in it too.
- **trigger_gravity**: `gravity` (1 normal, 0.6 low). Sets the touching player's
  gravity, which stays after they leave (and across a level change).
- **func_recharge** / **func_healthcharger**: wall chargers for the HEV's armour and
  health (`+0RECHARGE` has its `+A` empty frame).
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
  **ammo_9mmclip**, **item_suit** (needed for a HUD and weapons; `spawnflags` 1 = the
  short logon), **item_longjump** (only taken with the suit; crouch and jump while
  running). Items and weapons fire their `target` when taken. They don't respawn.
- **player_weaponstrip**: fired, takes the player's weapons and ammo (not the suit or
  the long jump module).
- **game_player_equip**: a key per item to give (`weapon_crowbar 1`), `spawnflags` 1 =
  only when fired. It equips the activator: fire it from something the player set
  off (a trigger they walk into), not a trigger_auto.
- **monstermaker**: `monstertype` (e.g. monster_headcrab), `monstercount` (-1 = no
  end), `m_imaxlivechildren` (how many at once), `delay` (seconds between),
  `spawnflags` 1 = starts on (on anyway without a targetname). It can make items and
  weapons too. Nothing appears while something stands under it.
- **env_beam**: `LightningStart`, `LightningEnd` (named entities, e.g. info_target),
  `texture` "sprites/laserbeam.spr", `BoltWidth`, `NoiseAmplitude`, `damage` per
  second to whatever it crosses, `life` 0 = for ever, `spawnflags` 1 = starts on.
- **monster_barnacle**: hangs from the ceiling (origin just under it); its tongue
  drops straight down and hauls up whoever walks under. **monster_leech**: in water.
  **monster_houndeye**: packs; sonic blast. Moving monsters need info_nodes.
- **info_node**: a point monsters navigate by; the game links them into a graph at
  the first load (maps/graphs/<map>.nod). Put them on the floor, about 200 apart
  (m.auto_nodes does).
- **xen_tree** (attacks the player close in front; a solid box), **xen_hair**
  (decoration), **xen_plantlight**, **xen_spore_small/medium/large** (solid).
