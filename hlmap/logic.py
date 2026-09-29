"""Map state and conditional logic, built from stock Half-Life entities.

GoldSrc has no variables and no if-statement. These helpers build them from entities
every copy of Half-Life has:

  Flag      a true/false state kept in the engine's global state table (env_global).
            Anything that takes a `master` (doors, buttons, gates, triggers) can read
            it through a multisource: master=flag.is_on / flag.is_off.
  gate      a relay that only passes while its master is on (a game_counter with a
            limit of 1 that resets). trigger_relay and multi_manager ignore masters.
  when      a relay that passes only if several masters are all on (chained gates).
  sequence  a timed list of targets (multi_manager): the same target may appear more
            than once, and lists longer than the engine's 16 are chained.
  Circuit   building power: light groups that die in a power failure and come back
            when it is restored (switched groups remember their switch position),
            emergency lights that do the opposite, extra effects on failure/restore,
            and switches that are dead while the power is out.

`python -m hlmap verify` simulates these entities (hlmap/sim.py), so a map's event
sequences are checked like its geometry.
"""
from __future__ import annotations

from .mapfile import Entity
from .sim import STYLE_PATTERNS

MAX_MULTI_TARGETS = 16      # multi_manager limit (HLSDK triggers.cpp)
# light patterns for named lights (light(..., pattern=)); a named light gets its own
# style number from the compiler, so a stock `style` would be lost
STYLE_FLUORESCENT = STYLE_PATTERNS[10]      # flickering fluorescent tube
STYLE_FLICKER = STYLE_PATTERNS[1]
STYLE_CANDLE = STYLE_PATTERNS[3]


class Flag:
    """A named true/false map state. Fire `flag.on`, `flag.off` or `flag.toggle` to
    change it; use `master=flag.is_on` (or `flag.is_off`) to make an entity depend on
    it. `flag.state` is the global state name (e.g. for props.lock(..., globalstate=)).
    Global states also survive level changes."""

    def __init__(self, name, initially=True, origin=(0, 0, 0)):
        self.name = name
        self.state = name
        self.initially = bool(initially)
        self.origin = tuple(origin)
        self.on, self.off, self.toggle = f"{name}_on", f"{name}_off", f"{name}_toggle"
        self.is_on, self.is_off = f"{name}_is_on", f"{name}_is_off"

    def entities(self):
        # two global states, the flag and its inverse, so both "on" and "off" can be masters
        inv = f"{self.state}_not"
        init = {self.state: int(self.initially), inv: int(not self.initially)}
        ents = [Entity("multisource", targetname=self.is_on, globalstate=self.state, origin=self.origin),
                Entity("multisource", targetname=self.is_off, globalstate=inv, origin=self.origin)]
        # triggermode: 0 off, 1 on, 3 toggle; spawnflags 1 = set the initial state
        for tname, modes in ((self.on, (1, 0)), (self.off, (0, 1)), (self.toggle, (3, 3))):
            for state, mode in zip((self.state, inv), modes):
                ents.append(Entity("env_global", targetname=tname, globalstate=state, triggermode=mode,
                                   initialstate=init[state], spawnflags=1, origin=self.origin))
        return ents


def gate(name, target, master, origin=(0, 0, 0)):
    """Fire `target` (toggle) when `name` is fired, but only while `master` is on."""
    return Entity("game_counter", targetname=name, target=target, master=master,
                  health=1, frags=0, spawnflags=2, origin=tuple(origin))   # 2 = reset on fire


def when(name, target, masters, origin=(0, 0, 0)):
    """Fire `target` when `name` is fired, but only if every master is on (AND): a
    chain of gates, e.g. when("greet", "hello", [power.is_on, visited.is_off])."""
    masters = list(masters)
    ents = []
    for k, master in enumerate(masters):
        src = name if k == 0 else f"{name}_{k}"
        dst = target if k == len(masters) - 1 else f"{name}_{k + 1}"
        ents.append(gate(src, dst, master, origin))
    return ents


def sequence(name, steps, origin=(0, 0, 0)):
    """multi_manager `name` firing [(target, delay_seconds)...] in time order (toggle).
    Repeated targets get '#n' suffixes; more than 16 steps are chained."""
    steps = sorted(steps, key=lambda s: s[1])
    ents = []
    if len(steps) > MAX_MULTI_TARGETS:
        rest = sequence(f"{name}_more", steps[MAX_MULTI_TARGETS - 1:], origin)
        ents += rest
        steps = steps[:MAX_MULTI_TARGETS - 1] + [(f"{name}_more", 0)]
    kv, seen = {}, {}
    for target, delay in steps:
        n = seen.get(target, 0)
        seen[target] = n + 1
        kv[target if n == 0 else f"{target}#{n}"] = delay
    return [Entity("multi_manager", targetname=name, origin=tuple(origin), kv=kv)] + ents


class Circuit:
    """Mains power for a building.

        grid = logic.Circuit("power", origin)
        grid.group("hall_lights", switched=True)   # lights named hall_lights + a wall switch
        grid.group("storage_lights")               # always on while there is power
        grid.emergency("emergency")                # named lights that start dark
        grid.on_fail("camp_sparks", 0); grid.on_restore("beam_on", 0.5)
        m.add(props.switch(pos, facing, grid.switch("hall_lights"), master=grid.live))
        ... fire grid.fail (e.g. from a pickup) and grid.restore (e.g. a breaker)
        m.add(grid.entities())

    A power failure turns off every group whose lights are on and turns the
    emergency groups on; restoring does the reverse. A switched group that was
    switched off stays off either way. Switches are dead (master=grid.live) while the
    power is out, which is what keeps the switch positions and the lights in step."""

    def __init__(self, name="power", origin=(0, 0, 0), emergency_delay=1.2):
        self.name = name
        self.origin = tuple(origin)
        self.flag = Flag(name, True, origin)
        self.live = self.flag.is_on           # master for things that need power
        self.dead = self.flag.is_off
        self.fail, self.restore = f"{name}_fail", f"{name}_restore"
        self.emergency_delay = emergency_delay
        self.switched, self.unswitched, self.emergencies = [], [], []
        self._fail_extra, self._restore_extra = [], []

    def group(self, lights, switched=False):
        """A group of named lights (all lights/panels with targetname `lights`) on this
        circuit. Returns the name a switch should fire (switched groups only)."""
        (self.switched if switched else self.unswitched).append(lights)
        return self.switch(lights) if switched else None

    def switch(self, lights):
        return f"{lights}_switch"

    def emergency(self, lights):
        """Named lights that start dark (spawnflags 1) and run while the power is out."""
        self.emergencies.append(lights)

    def on_fail(self, target, delay=0.0):
        self._fail_extra.append((target, delay))

    def on_restore(self, target, delay=0.0):
        self._restore_extra.append((target, delay))

    def entities(self):
        o = self.origin
        ents = self.flag.entities()
        cuts = []
        for g in self.switched:
            lit = Flag(f"{g}_lit", True, o)            # the switch position
            ents += lit.entities()
            ents += sequence(self.switch(g), [(g, 0), (lit.toggle, 0)], o)
            ents.append(gate(f"{g}_cut", g, lit.is_on, o))   # toggles the group if switched on
            cuts.append(f"{g}_cut")
        both = [(c, 0) for c in cuts] + [(g, 0) for g in self.unswitched]
        fail = [(self.flag.off, 0)] + both + [(e, self.emergency_delay) for e in self.emergencies]
        restore = [(self.flag.on, 0)] + both + [(e, 0) for e in self.emergencies]
        ents.append(gate(self.fail, f"{self.fail}_seq", self.live, o))
        ents += sequence(f"{self.fail}_seq", fail + self._fail_extra, o)
        ents.append(gate(self.restore, f"{self.restore}_seq", self.dead, o))
        ents += sequence(f"{self.restore}_seq", restore + self._restore_extra, o)
        return ents
