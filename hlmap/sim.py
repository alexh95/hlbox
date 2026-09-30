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
"""
from __future__ import annotations

import heapq

OFF, ON, SET, TOGGLE = 0, 1, 2, 3
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
ITEMS = ("item_", "weapon_", "ammo_")
# fired but only make sounds, messages or effects (recorded, no state)
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

    def __init__(self, ents, globals=None):
        """globals: global states carried over from the previous map ({name: 0 off,
        1 on, 2 dead}); env_globals that set an initial state leave those alone, as
        in the game (the state is only created if it doesn't exist yet)."""
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
        self.opened = set()   # doors opened by being fired
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
        """Map start: trigger_autos fire."""
        for i, e in enumerate(self.ents):
            if e.get("classname") == "trigger_auto":
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
        self.gone.add(i)
        self._use_targets(i, TOGGLE, None)
        return self.run(self._until(until))

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
        elif c in DOORS:
            if self.master_ok(e.get("master")):
                self.opened.add(i)
        elif c == "trigger_changetarget":
            for j in self.names.get(self.target(i) or "", ()):
                self.retarget[j] = e.get("m_iszNewTarget")
        elif c == "infodecal" or c in EFFECTS:
            self.effects.append((i, c, USE_NAMES[use]))
        else:
            self.effects.append((i, c, USE_NAMES[use]))

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
        rel, rel_globals = relevance
        return (tuple(sorted((g, self.globals.get(g, 0)) for g in rel_globals)),
                tuple((i, tuple(self.bits[i])) for i in sorted(rel) if i in self.bits),
                tuple(sorted(self.gone & rel)), tuple(sorted(self.pressed & rel)),
                tuple(sorted(self.opened & rel)),
                tuple(sorted((i, v) for i, v in self.count.items() if i in rel)),
                tuple(sorted((i, v) for i, v in self.retarget.items() if i in rel)))

    def describe_change(self, before):
        """Human-readable differences from an earlier World."""
        out = []
        for g in sorted(set(self.globals) | set(before.globals)):
            a, b = before.globals.get(g, 0), self.globals.get(g, 0)
            if a != b and not g.endswith("_not"):
                out.append(f"{g} {'on' if b == 1 else 'off' if b == 0 else 'dead'}")
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
