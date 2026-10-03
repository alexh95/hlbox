"""Simulate a compiled map's entity logic: what firing a targetname does.

The verifier walks a map as a player would: picking things up and pressing buttons,
each of which fires targetnames through relays, multi_managers, gates and global
state. World models the state that matters (locks, global state, lights and their
light styles, used items and buttons) and applies each entity's Use the way the
Half-Life game code (HLSDK) does, including its quirks:
  - multisource: every input toggles, so firing a key twice relocks
  - light/func_wall: "on" or "off" is ignored when already in that state
  - trigger_relay: triggerstate missing = off
  - trigger_relay, multi_manager: no master; func_button, func_door, game_counter
    and trigger_once/multiple honour one
  - func_door: a named door opens when fired (a "toggle" one, spawnflags 32, also
    closes); "starts open" (1) doors start open, and fired move to where they were
    built (HLSDK swaps the two positions); a func_water moves the same way
  - func_breakable: broken by an armed player, then gone (firing its target)
  - gear: the HEV suit, the long jump module (only taken with the suit) and weapons
    go into the player's inventory; player_weaponstrip takes weapons and ammo (not
    the suit or the long jump); game_player_equip gives what it names
  - path_track: fired, a switch (one with an altpath) toggles between its target
    and its altpath, any other toggles "disabled"; func_trackchange (a track lift)
    moves to its other level, taking the tram with it if it's stopped on it, and
    enables the track at the level it's at only (HLSDK EvaluateTrain,
    UpdateAutoTargets); where the tram stands (a path_track) is state too, and
    `rides` drives it as far as the track lets it (hlmap/track.py)
"""
from __future__ import annotations

import heapq
import math

OFF, ON, SET, TOGGLE = 0, 1, 2, 3
SF_PATH_DISABLED, SF_PATH_ALTERNATE = 1, 32768
USE_NAMES = {OFF: "off", ON: "on", SET: "set", TOGGLE: "toggle"}

# stock light styles (HLSDK world.cpp); 'a' = dark, 'm' = normal, 'z' = double
STYLE_PATTERNS = {
    0: "m", 1: "mmnmmommommnonmmonqnmmo", 2: "abcdefghijklmnopqrstuvwxyzyxwvutsrqponmlkjihgfedcba",
    3: "mmmmmaaaaammmmmaaaaaabcdefgabcdefg", 4: "mamamamamama", 5: "jklmnopqrstuvwxyzyxwvutsrqponmlkj",
    6: "nmonqnmomnmomomno", 7: "mmmaaaabcdefgmmmmaaaaaaaaabcdefgmmmaaaa",
    8: "mmmaaammmaaammmabcdefaaaammmmabcdefmmmaaaa", 9: "aaaaaaaazzzzzzzz",
    10: "mmamammmmammamamaaamammma", 11: "abcdefghijklmnopqrrqponmlkjihgfedcba", 12: "mmnnmmnnnmmnn",
}
# keys a multi_manager does NOT treat as targets (engine-parsed entvars + its own "wait")
_MM_RESERVED = {"classname", "targetname", "origin", "angles", "spawnflags", "target", "netname", "wait",
                "model", "rendermode", "renderamt", "rendercolor", "renderfx", "message", "globalname"}
LIGHTS = ("light", "light_spot")
BUTTONS = ("func_button", "func_rot_button")
DOORS = ("func_door", "func_door_rotating")
MOVERS = DOORS + ("func_water",)      # move when fired (a func_water is water that moves like a door)
ITEMS = ("item_", "weapon_", "ammo_")
# fired but only make sounds, messages or effects (recorded, no state)
GEAR = ("item_suit", "item_longjump")          # kept for good once taken
GEAR_NAMES = {"item_suit": "HEV suit", "item_longjump": "long jump module", "weapon_crowbar": "crowbar",
              "weapon_9mmhandgun": "pistol"}
EFFECTS = {"ambient_generic", "game_text", "env_shake", "env_fade", "env_spark", "env_sprite", "env_beam",
           "env_message", "speaker", "trigger_camera", "env_explosion", "env_funnel", "env_laser",
           "scripted_sequence", "scripted_sentence"}


def pattern_level(pattern):
    """Average brightness of a light style pattern, 1.0 = normal ('m')."""
    return sum(max(0, ord(c) - 97) for c in pattern) / (12 * len(pattern)) if pattern else 1.0


def should_toggle(use, state):
    """CBaseEntity::ShouldToggle: 'on' when on / 'off' when off does nothing."""
    return not ((use == ON and state) or (use == OFF and not state))


def strip_token(key):
    return key.split("#", 1)[0]


class World:
    """The logic state of a map (from its compiled entity lump) and how it changes."""

    def __init__(self, ents, globals=None, inventory=()):
        """globals: global states carried over from the previous map ({name: 0 off,
        1 on, 2 dead}); env_globals that set an initial state leave those alone, as
        in the game (the state is only created if it doesn't exist yet).
        inventory: the player's gear and weapons on arrival (classnames)."""
        self.ents = ents
        self.names = {}
        for i, e in enumerate(ents):
            if e.get("targetname"):
                self.names.setdefault(e["targetname"], []).append(i)
        self.inputs = {}      # multisource -> entities registered as its inputs (HLSDK Register)
        for i, e in enumerate(ents):
            if e.get("classname") == "multisource" and e.get("targetname"):
                n = e["targetname"]
                self.inputs[i] = [j for j, f in enumerate(ents) if f.get("target") == n] + \
                                 [j for j, f in enumerate(ents) if f.get("classname") == "multi_manager"
                                  and any(strip_token(k) == n for k in f if k not in _MM_RESERVED)]
        self.globals = dict(globals or {})     # global state -> 0 off, 1 on, 2 dead
        for e in ents:
            if e.get("classname") == "env_global" and int(e.get("spawnflags") or 0) & 1 and e.get("globalstate"):
                self.globals.setdefault(e["globalstate"], int(e.get("initialstate") or 0))
        self.bits = {i: [0] * len(v) for i, v in self.inputs.items()}
        self.lit = {i: not int(e.get("spawnflags") or 0) & 1 for i, e in enumerate(ents)
                    if e.get("classname") in LIGHTS and e.get("targetname")}
        self.frame = {i: int(float(e.get("frame") or 0)) for i, e in enumerate(ents)
                      if e.get("classname") == "func_wall" and e.get("targetname")}
        self.shown = {i: not int(e.get("spawnflags") or 0) & 1 for i, e in enumerate(ents)
                      if e.get("classname") == "func_wall_toggle"}   # 1 = starts hidden
        self.count = {i: int(float(e.get("frags") or 0)) for i, e in enumerate(ents)
                      if e.get("classname") == "game_counter"}
        self.render = {}      # entity -> renderamt set by env_render
        self.gone = set()     # removed: picked-up items, fire-once relays, killtargets
        self.pressed = set()  # toggle buttons in their pressed state; wait -1 buttons used up
        self.opened = {i for i, e in enumerate(ents) if e.get("classname") in MOVERS and e.get("targetname")
                       and int(e.get("spawnflags") or 0) & 1}   # named doors open now (1 = starts open)
        self.inventory = set(inventory)   # the player's gear and weapons
        # tracks (hlmap/track.py): switches thrown, nodes closed, lifts at the top, trams' nodes
        self._graph = None
        self.switched = {i for i, e in enumerate(ents) if e.get("classname") == "path_track"
                         and int(float(e.get("spawnflags") or 0)) & SF_PATH_ALTERNATE}
        self.closed = {i for i, e in enumerate(ents) if e.get("classname") == "path_track"
                       and int(float(e.get("spawnflags") or 0)) & SF_PATH_DISABLED}
        self.lift_top = {i: not int(float(e.get("spawnflags") or 0)) & 8 for i, e in enumerate(ents)
                         if e.get("classname") == "func_trackchange"}
        self.train = {}
        for i, e in enumerate(ents):
            if e.get("classname") == "func_tracktrain":
                self.train[i] = next((j for j in self.names.get(e.get("target") or "", ())
                                      if ents[j].get("classname") == "path_track"), None)
        self._lift_cache = {}
        for i in self.lift_top:            # CFuncTrackChange::Find -> UpdateAutoTargets
            self._lift_targets(i)
        self.retarget = {}    # trigger_changetarget
        self.effects = []     # what happened, for logs: (entity, classname, use)
        self.warnings = []
        self._queue, self._seq, self.time = [], 0, 0.0

    def copy(self):
        w = World.__new__(World)
        w.ents, w.names, w.inputs = self.ents, self.names, self.inputs
        w.globals = dict(self.globals)
        w.bits = {k: list(v) for k, v in self.bits.items()}
        w.lit, w.frame, w.count, w.render = dict(self.lit), dict(self.frame), dict(self.count), dict(self.render)
        w.shown = dict(self.shown)
        w.gone, w.pressed, w.opened = set(self.gone), set(self.pressed), set(self.opened)
        w.inventory = set(self.inventory)
        w._graph, w._lift_cache = self._graph, self._lift_cache
        w.switched, w.closed = set(self.switched), set(self.closed)
        w.lift_top, w.train = dict(self.lift_top), dict(self.train)
        w.retarget = dict(self.retarget)
        w.effects, w.warnings = [], []
        w._queue, w._seq, w.time = [], 0, self.time
        return w

    # ------------------------------------------------------------ queries
    def cls(self, i):
        return self.ents[i].get("classname", "")

    def target(self, i):
        return self.retarget.get(i, self.ents[i].get("target"))

    def master_ok(self, name):
        """UTIL_IsMasterTriggered: the first entity with that name decides; only a
        multisource can say no (all inputs on, and its global state on if it has one)."""
        if not name:
            return True
        for i in self.names.get(name, ()):
            if i in self.gone:
                continue
            return self._ms_triggered(i) if self.cls(i) == "multisource" else True
        return True

    def _ms_triggered(self, i):
        gs = self.ents[i].get("globalstate")
        return all(self.bits[i]) and (not gs or self.globals.get(gs, 0) == 1)

    def door_passable(self, i):
        e = self.ents[i]
        if i in self.gone:
            return True
        if e.get("targetname"):        # a named door only opens when fired
            return i in self.opened
        return self.master_ok(e.get("master"))

    def teleport_enabled(self, i):
        """A trigger_teleport works while its master is on (firing it does nothing)."""
        return i not in self.gone and self.master_ok(self.ents[i].get("master"))

    def style_levels(self):
        """Light style -> brightness factor (1.0 = normal) in the current state."""
        levels = {s: pattern_level(p) for s, p in STYLE_PATTERNS.items()}
        for i, on in self.lit.items():
            e = self.ents[i]
            s = int(e.get("style") or 0)
            if s >= 32:
                lv = pattern_level(e.get("pattern") or "m") if on else 0.0
                levels[s] = max(levels.get(s, 0.0), lv) if s in levels else lv
        return levels

    # ------------------------------------------------------------ player actions
    def start(self):
        """Map start: trigger_autos fire. Called again on a World that was left, it is
        coming back into the map: the ones still there fire again, as in the game."""
        for i, e in enumerate(self.ents):
            if e.get("classname") == "trigger_auto" and i not in self.gone:
                gs = e.get("globalstate")
                if gs and self.globals.get(gs, 0) != 1:
                    continue
                self._use_targets(i, self._relay_use(e), None)
                if int(e.get("spawnflags") or 0) & 1:
                    self.gone.add(i)
        self.run()
        return self

    def available(self, i):
        """Can the player still do this (item not taken, stay-pressed button not used)?"""
        return i not in self.gone and not (self.cls(i) in BUTTONS and i in self.pressed
                                           and float(self.ents[i].get("wait") or 0) < 0)

    def _until(self, until):
        return None if until is None else self.time + until

    def pickup(self, i, until=None):
        c = self.cls(i)
        if c == "item_longjump" and "item_suit" not in self.inventory:
            return self                   # the module only goes on the suit: it stays put
        if c.startswith("weapon_") and c in self.inventory:
            return self                   # already have one (a crowbar has no ammo to give)
        self.gone.add(i)
        if c in GEAR or c.startswith("weapon_"):
            self.inventory.add(c)
        self._use_targets(i, TOGGLE, None)
        return self.run(self._until(until))

    def break_(self, i, until=None):
        """The player breaks a func_breakable (with a weapon): it's gone, and fires its
        target."""
        if not self.armed:
            return self
        self.gone.add(i)
        self._use_targets(i, TOGGLE, None)
        return self.run(self._until(until))

    def shoot(self, i, until=None):
        """A mounted gun (func_tank) the player mans breaks a func_breakable: gone, and
        fires its target (no weapon of their own needed)."""
        self.gone.add(i)
        self._use_targets(i, TOGGLE, None)
        return self.run(self._until(until))

    @property
    def armed(self):
        return any(c.startswith("weapon_") for c in self.inventory)

    @property
    def long_jump(self):
        return "item_longjump" in self.inventory

    def press(self, i, until=None):
        self._button(i)
        return self.run(self._until(until))

    def touch(self, i, until=None):
        """The player walks into a trigger volume (respecting its master)."""
        e = self.ents[i]
        if self.master_ok(e.get("master")):
            self._use_targets(i, TOGGLE, None)
            if e.get("classname") == "trigger_once":
                self.gone.add(i)
        return self.run(self._until(until))

    def fire(self, name, use=TOGGLE, until=None):
        """Fire a targetname and run the logic; until= stops after that many seconds
        (later events stay queued, e.g. to act in the middle of a timed sequence)."""
        self._schedule(0, name, use, None)
        return self.run(self._until(until))

    # ------------------------------------------------------------ the entity I/O
    def _schedule(self, delay, name, use, caller):
        self._seq += 1
        heapq.heappush(self._queue, (self.time + max(0.0, float(delay)), self._seq, name, use, caller))

    def run(self, until=None, limit=10000):
        n = 0
        while self._queue and n < limit and (until is None or self._queue[0][0] <= until):
            t, _, name, use, caller = heapq.heappop(self._queue)
            self.time = max(self.time, t)
            if caller is not None and caller in self.gone and self.cls(caller) == "multi_manager":
                continue          # a removed multi_manager fires nothing more
            if name.startswith("!kill "):
                for j in self.names.get(name[6:], ()):
                    self.gone.add(j)
                continue
            for j in list(self.names.get(name, ())):
                if j not in self.gone:
                    self._use(j, use, caller)
            n += 1
        if self._queue and until is None:
            self.warnings.append("entity logic did not settle (an endless trigger loop?)")
            self._queue.clear()
        return self

    def _use_targets(self, i, use, caller):
        """SUB_UseTargets: after `delay`, remove the killtarget and fire the target."""
        e = self.ents[i]
        delay = float(e.get("delay") or 0)
        if e.get("killtarget"):
            self._schedule(delay, "!kill " + e["killtarget"], use, i)
        if self.target(i):
            self._schedule(delay, self.target(i), use, i)

    @staticmethod
    def _relay_use(e):
        ts = int(e.get("triggerstate") or 0)
        return OFF if ts == 0 else TOGGLE if ts == 2 else ON

    def _button(self, i):
        e = self.ents[i]
        sf = int(e.get("spawnflags") or 0)
        if sf & 32 and i in self.pressed:        # toggle button going back: no master check
            self.pressed.discard(i)
            self._use_targets(i, TOGGLE, None)
            return
        if not self.master_ok(e.get("master")):
            self.effects.append((i, self.cls(i), "locked"))
            return
        if sf & 32 or float(e.get("wait") or 0) < 0:
            self.pressed.add(i)
        self._use_targets(i, TOGGLE, None)

    def _use(self, i, use, caller):
        e = self.ents[i]
        c = e.get("classname", "")
        if c in ("trigger_relay", "trigger_auto"):
            self._use_targets(i, self._relay_use(e), i)
            if int(e.get("spawnflags") or 0) & 1:
                self.gone.add(i)
        elif c == "multi_manager":
            for k, v in e.items():
                if k not in _MM_RESERVED:
                    self._schedule(float(v or 0), strip_token(k), TOGGLE, i)
        elif c == "multisource":
            ins = self.inputs.get(i, [])
            if caller in ins:
                self.bits[i][ins.index(caller)] ^= 1
            else:
                self.warnings.append(f"multisource {e.get('targetname')} fired by entity {caller} "
                                     f"({self.cls(caller) if caller is not None else '?'}), which is not one "
                                     "of its inputs: the engine toggles its LAST input (or corrupts memory)")
                if self.bits[i]:
                    self.bits[i][-1] ^= 1
            if self._ms_triggered(i) and self.target(i):
                self._schedule(0, self.target(i), ON if e.get("globalstate") else TOGGLE, i)
        elif c == "env_global":
            gs = e.get("globalstate")
            mode = int(e.get("triggermode") or 0)
            old = self.globals.get(gs, 0)
            self.globals[gs] = {0: 0, 1: 1, 2: 2}.get(mode, {1: 0, 0: 1}.get(old, old))
        elif c == "game_counter":
            if not self.master_ok(e.get("master")):
                return
            self.count[i] = self.count.get(i, 0) + (-1 if use == OFF else 1)
            if self.count[i] == int(float(e.get("health") or 0)):
                self._use_targets(i, TOGGLE, i)
                sf = int(e.get("spawnflags") or 0)
                if sf & 1:
                    self.gone.add(i)
                if sf & 2:
                    self.count[i] = int(float(e.get("frags") or 0))
        elif c in LIGHTS:
            if i in self.lit and should_toggle(use, self.lit[i]):
                self.lit[i] = not self.lit[i]
        elif c == "func_wall":
            if i in self.frame and should_toggle(use, self.frame[i]):
                self.frame[i] = 1 - self.frame[i]
        elif c == "func_wall_toggle":
            if should_toggle(use, self.shown[i]):
                self.shown[i] = not self.shown[i]
        elif c == "env_render":
            sf = int(e.get("spawnflags") or 0)
            if not sf & 2:
                for j in self.names.get(self.target(i) or "", ()):
                    self.render[j] = int(float(e.get("renderamt") or 0))
        elif c in BUTTONS:
            self._button(i)
        elif c in MOVERS:
            if self.master_ok(e.get("master")):
                sf = int(e.get("spawnflags") or 0)
                if sf & 32 and i in self.opened:
                    self.opened.discard(i)        # a toggle door closes again
                elif sf & 1 and not sf & 32 and e.get("targetname"):
                    self.opened.discard(i)        # starts open: fired, it moves to where it was built
                else:
                    self.opened.add(i)
        elif c == "player_weaponstrip":
            self.inventory = {g for g in self.inventory if not g.startswith(("weapon_", "ammo_"))}
            self.effects.append((i, c, USE_NAMES[use]))
        elif c == "game_player_equip":
            for k in e:
                if k.startswith(("weapon_", "item_suit", "item_longjump")):
                    if k == "item_longjump" and "item_suit" not in self.inventory:
                        continue
                    self.inventory.add(k)
            self.effects.append((i, c, USE_NAMES[use]))
        elif c == "path_track":
            g = self.graph
            k = g.by_entity.get(i)
            if k is not None and g.alt[k] is not None:
                if should_toggle(use, i not in self.switched):
                    self.switched ^= {i}
            elif should_toggle(use, i not in self.closed):
                self.closed ^= {i}
        elif c == "func_trackchange":
            self._trackchange(i)
        elif c == "trigger_changetarget":
            for j in self.names.get(self.target(i) or "", ()):
                self.retarget[j] = e.get("m_iszNewTarget")
        elif c == "infodecal" or c in EFFECTS:
            self.effects.append((i, c, USE_NAMES[use]))
        else:
            self.effects.append((i, c, USE_NAMES[use]))

    # ------------------------------------------------------------ tracks
    @property
    def graph(self):
        """The path_tracks as the game links them (track.Graph), shared by copies."""
        if self._graph is None:
            from .track import Graph
            g = Graph.from_entities(self.ents)
            g.by_entity = {n["index"]: k for k, n in enumerate(g.nodes)}
            self._graph = g
        return self._graph

    def _alts(self):
        g = self.graph
        return {g.by_entity[i] for i in self.switched if i in g.by_entity}

    def _node_entity(self, k):
        return self.graph.nodes[k]["index"]

    def _lift_targets(self, i):
        """A track lift's (top, bottom) path_tracks (the named ones' nearest to it, as
        CFuncTrackChange::Find picks them when the map starts), the tram it carries
        and its centre."""
        if i not in self._lift_cache:
            e, g = self.ents[i], self.graph
            o = tuple(float(c) for c in (e.get("origin") or "0 0 0").split())
            ends = []
            for key in ("toptrack", "bottomtrack"):
                j = next((j for j in self.names.get(e.get(key) or "", ()) if self.cls(j) == "path_track"), None)
                k = g.nearest(g.by_entity[j], o, self._alts()) if j is not None else None
                if j is not None and k is None:
                    self.warnings.append(f"track lift {e.get('targetname')}: following the track from {e.get(key)} "
                                         "never comes back (HLSDK: bad sequence of path_tracks; the tram gets lost)")
                ends.append(self._node_entity(k) if k is not None else None)
            t = next((j for j in self.names.get(e.get("train") or "", ()) if self.cls(j) == "func_tracktrain"), None)
            self._lift_cache[i] = (ends[0], ends[1], t, o)
            self._update_lift(i)
        return self._lift_cache[i]

    def _update_lift(self, i):
        """UpdateAutoTargets: the lift's node at the level it's at is open, the other
        one closed."""
        top, bottom, _, _ = self._lift_cache[i]
        at_top = self.lift_top[i]
        for node, open_ in ((top, at_top), (bottom, not at_top)):
            if node is not None:
                if open_:
                    self.closed.discard(node)
                else:
                    self.closed.add(node)

    def _trackchange(self, i):
        """CFuncTrackChange::Use: go to the other level; the tram goes with it if it's
        stopped on it (EvaluateTrain: following), and the lift refuses (an alarm) if
        the tram is close but not on it."""
        top, bottom, t, o = self._lift_targets(i)
        cur = top if self.lift_top[i] else bottom
        code = self._evaluate_train(t, cur, o)
        if code == "blocking":
            self.effects.append((i, "func_trackchange", "blocked"))
            return
        self.lift_top[i] = not self.lift_top[i]
        self._update_lift(i)
        if code == "following":
            g = self.graph
            dest = top if self.lift_top[i] else bottom
            k = g.nearest(g.by_entity[dest], o, self._alts()) if dest is not None else None
            if k is None:
                self.warnings.append(f"track lift {self.ents[i].get('targetname')}: the tram is lost at the "
                                     "other level")
            self.train[t] = self._node_entity(k) if k is not None else None

    def _evaluate_train(self, t, cur, origin):
        """HLSDK EvaluateTrain, with the tram stopped at its node: it counts as at the
        lift's node `cur` if its node is cur or next to it (the engine's m_ppath can be
        the node before where it stands), and as following the lift if within `wheels`
        of its centre (in plan); close but not on it, it blocks."""
        if t is None or cur is None or self.train.get(t) is None:
            return "safe"
        g = self.graph
        k, c = g.by_entity[self.train[t]], g.by_entity[cur]
        mine = {k, g.prev[k]}
        if not mine & {c, g.prev[c], g.next[c]}:
            return "safe"
        p = g.nodes[k]["origin"]
        d = math.hypot(p[0] - origin[0], p[1] - origin[1])
        wheels = float(self.ents[t].get("wheels") or 0)
        if d < wheels:
            return "following"
        return "safe" if d > 150 + wheels else "blocking"

    def rides(self, t, stops_only=True):
        """Where the player can drive tram `t` from where it stands, forward and back as
        the track is switched, and through what its dead ends set off (a lift taking
        it up): [(World with the tram there, path_track entity index)], at the stops
        (path_tracks with hlmap_stop) unless stops_only is False."""
        g = self.graph
        out, seen, todo = [], set(), [self]
        while todo:
            w = todo.pop()
            if w.train.get(t) is None:
                continue
            closed = {g.by_entity[i] for i in w.closed if i in g.by_entity}
            reach, ends = g.drive(g.by_entity[w.train[t]], w._alts(), closed)
            for k in reach:
                if stops_only and not g.nodes[k]["stop"]:
                    continue
                w2 = w.copy()
                w2.train[t] = g.nodes[k]["index"]
                out.append((w2, g.nodes[k]["index"]))
            for k, _ in ends:
                net = g.nodes[k]["netname"]
                if not net:
                    continue
                w2 = w.copy()
                w2.train[t] = g.nodes[k]["index"]
                w2.fire(net)
                state = w2.key(None)
                if state not in seen:
                    seen.add(state)
                    todo.append(w2)
        return out

    # ------------------------------------------------------------ progress-relevant state
    def relevance(self, doors, watch=()):
        """Static backward slice: which entities and global states can (through any
        chain of firing) change whether one of `doors` is passable, or whether such a
        chain can run. Only these matter for progression; e.g. a light switch does not.
        watch: global states that matter too (e.g. ones the next map reads)."""
        ents = self.ents
        firers = {}                                   # name -> entities that fire it
        for j, f in enumerate(ents):
            outs = []
            if f.get("classname") == "multi_manager":
                outs = [strip_token(k) for k in f if k not in _MM_RESERVED]
            else:
                outs = [v for v in (f.get("target"), f.get("killtarget")) if v]
            for n in outs:
                firers.setdefault(n, set()).add(j)
        setters = {}                                  # global state -> env_globals setting it
        for j, f in enumerate(ents):
            if f.get("classname") == "env_global" and f.get("globalstate"):
                setters.setdefault(f["globalstate"], set()).add(j)
        rel, rel_globals = set(), set()
        todo = []

        def need_master(name):
            for j in self.names.get(name or "", ()):
                if ents[j].get("classname") == "multisource" and j not in rel:
                    rel.add(j)
                    todo.append(j)

        def need_entity(j):
            if j not in rel:
                rel.add(j)
                todo.append(j)

        for d in doors:
            need_entity(d)
        for gs in watch:
            if gs not in rel_globals:
                rel_globals.add(gs)
                for s in setters.get(gs, ()):
                    need_entity(s)
        while todo:
            j = todo.pop()
            e = ents[j]
            c = e.get("classname", "")
            need_master(e.get("master"))
            if c == "multisource":
                gs = e.get("globalstate")
                if gs and gs not in rel_globals:
                    rel_globals.add(gs)
                    for s in setters.get(gs, ()):
                        need_entity(s)
                for k in self.inputs.get(j, ()):
                    need_entity(k)
            # whoever fires this entity (by name) matters too
            for k in firers.get(e.get("targetname") or "", ()):
                need_entity(k)
        return rel, rel_globals

    def key(self, relevance):
        """The state that matters (relevance: from relevance(); None: all of it)."""
        if relevance is None:
            relevance = (set(range(len(self.ents))), set(self.globals))
        rel, rel_globals = relevance
        return (tuple(sorted(self.switched)), tuple(sorted(self.closed)), tuple(sorted(self.lift_top.items())),
                tuple(sorted(self.train.items())),
                tuple(sorted((g, self.globals.get(g, 0)) for g in rel_globals)),
                tuple((i, tuple(self.bits[i])) for i in sorted(rel) if i in self.bits),
                tuple(sorted(self.gone & rel)), tuple(sorted(self.pressed & rel)),
                tuple(sorted(self.opened & rel)), tuple(sorted(self.inventory)),
                tuple(sorted((i, v) for i, v in self.count.items() if i in rel)),
                tuple(sorted((i, v) for i, v in self.retarget.items() if i in rel)))

    def describe_change(self, before):
        """Human-readable differences from an earlier World."""
        out = [f"got the {GEAR_NAMES.get(g, g)}" for g in sorted(self.inventory - before.inventory)]
        out += [f"lost the {GEAR_NAMES.get(g, g)}" for g in sorted(before.inventory - self.inventory)]
        for g in sorted(set(self.globals) | set(before.globals)):
            a, b = before.globals.get(g, 0), self.globals.get(g, 0)
            if a != b and not g.endswith("_not"):
                out.append(f"{g} {'on' if b == 1 else 'off' if b == 0 else 'dead'}")
        for i in sorted(self.switched ^ before.switched):
            out.append(f"switch {self.ents[i].get('targetname')} {'thrown' if i in self.switched else 'back'}")
        lift_nodes = {n for v in self._lift_cache.values() for n in v[:2]}
        for i in sorted(self.closed ^ before.closed):
            if i not in lift_nodes:
                out.append(f"track at {self.ents[i].get('targetname')} {'closed' if i in self.closed else 'open'}")
        for i, top in sorted(self.lift_top.items()):
            if before.lift_top.get(i) != top:
                out.append(f"{self.ents[i].get('targetname')} {'up' if top else 'down'}")
        groups = {}
        for i, on in self.lit.items():
            if before.lit.get(i) != on:
                groups.setdefault(self.ents[i].get("targetname"), on)
        if groups:
            off = sorted(n for n, on in groups.items() if not on)
            on = sorted(n for n, on in groups.items() if on)
            if off:
                out.append("lights off: " + ", ".join(off))
            if on:
                out.append("lights on: " + ", ".join(on))
        return out
