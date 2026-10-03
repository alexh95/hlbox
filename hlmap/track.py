"""Railways: a tram the player drives along lines of path_tracks that loop, branch
and rejoin, switches, a track lift between levels, platforms to get on and off at,
and the live rail that keeps the player on the tram between them.

    line = track.Track("freight")
    low = line.line("low", [(704, -768), (256, -768), (-1024, -768), ...], z=0, closed=True)
    chord = line.branch("chord", low.at((256, -768)), [(0, -512), (0, 512)], to=low.at((256, 768)))
    line.gate(low.at((-1280, 64)), "west_door")       # dead until "west_door" fires
    line.stop(low.at((704, -768)), "DISPATCH", board=(704, -856, 48))
    line.lift(low.at((1280, 0)), up.at((1280, 0)), "lift")
    tram = line.tram(low.at((704, -768)))
    m.add(*line.entities())

How the game runs them (HLSDK plats.cpp, pathcorner.cpp; Track.Graph follows it):
  - A path_track `target`s the next one; that's "forward". Each node also knows ONE
    previous node, the last one whose link pointed at it as the map started
    (CPathTrack::Link runs in entity order). The entities are written branches first,
    main lines last, so where two ways join, reversing takes the main line.
  - A switch is a node with an `altpath`: firing it (toggle) sends trains to the
    alternate instead of its target; firing it again switches back. Spawnflag 32768
    would start it switched; never used here.
  - A node without an altpath that's fired toggles "disabled": a train can't enter it
    and stops at the node before (a gate: a blast door, a barricade). It stops there
    exactly, and fires that node's `netname` (a dead end).
  - The train (func_tracktrain) is built facing WEST at its first node (the engine
    turns it to face along the track, plus 180 degrees). `height` lifts its origin
    over the nodes. A player standing on it presses +use to take the controls
    (anywhere on it, without a func_traincontrols), then +forward / +back step the
    speed in quarters, both ways; jumping, strafing or +use again lets go. Moving
    trains go through walls: what stops them is the track.
  - The lift (func_trackchange) carries the train between a node on the lower line
    and one on the upper line straight above. Each level's node before the lift
    `target`s a dead-end node on the lift (its `netname` fires the lift), and has the
    lift node as its altpath, so trains always stop on the lift going forward (and go
    up or down), while reversing they cross it. The lift enables its node at the
    level it's at and disables the other one: no train falls down the shaft. It moves
    with the train only if it's stopped on it.
  - Following `target`s (as switched) from each lift node must come back to it or
    reach a dead end (HLSDK Nearest gives up after 9999 nodes and loses the train):
    every loop a lift node is on must pass through it. Track.check() says so.

The live rail: trigger_hurt over the track bed (`live_rail`), so a player can only
get off at the platforms. verify treats the tram as a ride between stops (path_tracks
with `hlmap_stop`): it drives it along the track as switched, through what its dead
ends set off (the lift), and the player gets off where it can be stopped at a stop.
"""
from __future__ import annotations

import math

from .geometry import box, prism
from .mapfile import Entity

GAUGE = 64            # between the rails
DECK = 48             # the tram's deck over the track bed: platforms are this high
HEIGHT = 24           # the tram's origin over its path_track (func_tracktrain "height")
LENGTH, WIDTH = 192, 104
ROOF = 152            # the tram's canopy top over the bed (tunnels must be taller)
ROUND = 64            # corners are cut this far each side: two half turns, so the tram swings less
SPEED = 300
WHEELS = 96           # how far ahead the tram looks to face along the track

SF_DISABLED, SF_FIREONCE, SF_ALTREVERSE, SF_DISABLE_TRAIN, SF_ALTERNATE = 1, 2, 4, 8, 32768
TRAIN_NOPITCH, TRAIN_NOCONTROL, TRAIN_FORWARDONLY, TRAIN_PASSABLE = 1, 2, 4, 8
TRACKCHANGE_STARTBOTTOM = 8
NEAREST_LIMIT = 9999

RAIL_TEX, SLEEPER_TEX = "GENERIC015K", "TRRM_WOOD"
TRAM_TEX = {"deck": "FLATBED_TOP", "body": "FLATBED_POD", "trim": "LAB1_TRIM3", "front": "FLATBED_ENGINE",
            "bumper": "FLATBED_BUMPER", "head": "FLATBED_HLITE2", "tail": "FLATBED_TLITE2", "rail": "GENERIC015K"}


class Node:
    def __init__(self, name, pos, line, priority):
        self.name, self.pos, self.line, self.priority = name, tuple(pos), line, priority
        self.target = None          # Node: forward
        self.alt = None             # Node: the switch's other way
        self.disabled = False
        self.netname = None         # fired when a train stops here at a dead end
        self.message = None         # fired when a train passes
        self.stop = None            # a platform: (label, board point on the platform floor)
        self.lift_link = False      # its altpath only links a lift node behind it (never switched)
        self.kv = {}

    def __repr__(self):
        return f"<Node {self.name} {self.pos}>"


class Line:
    def __init__(self, name, nodes, closed):
        self.name, self.nodes, self.closed = name, nodes, closed

    def at(self, xy):
        """The node at (x, y)."""
        for n in self.nodes:
            if abs(n.pos[0] - xy[0]) < 1e-6 and abs(n.pos[1] - xy[1]) < 1e-6:
                return n
        raise KeyError(f"line {self.name}: no node at {xy}")

    def __iter__(self):
        return iter(self.nodes)


class Track:
    def __init__(self, name="track", tram_name="tram"):
        self.name, self.tram_name = name, tram_name
        self.nodes: list[Node] = []
        self.lines: list[Line] = []
        self.lifts = []
        self.train = None           # (node, Entity)
        self._names = set()
        self._smoothed = False

    # ------------------------------------------------------------ building the network
    def _node(self, name, pos, line, priority):
        if name in self._names:
            raise ValueError(f"track: two nodes named {name}")
        self._names.add(name)
        n = Node(name, pos, line, priority)
        self.nodes.append(n)
        return n

    def line(self, name, points, z=0, closed=False):
        """A run of track through `points` [(x, y), ...] at height z (the track bed),
        one node per point, forward in that order; `closed` joins the last back to the
        first (a loop). Keep corners at 45 or 90 degrees."""
        nodes = [self._node(f"{name}{k}", (x, y, z), name, 2) for k, (x, y) in enumerate(points)]
        for a, b in zip(nodes, nodes[1:] + ([nodes[0]] if closed else [])):
            a.target = b
        ln = Line(name, nodes, closed)
        self.lines.append(ln)
        return ln

    def branch(self, name, frm: Node, points, to: Node | None = None, z=None):
        """A branch off `frm` (which becomes a switch: firing frm.name sends trains this
        way, firing it again back), through `points`, joining the track at `to` (a
        merge) or ending in buffers (a dead end) without one."""
        if frm.alt is not None:
            raise ValueError(f"track: {frm.name} is already a switch")
        z = frm.pos[2] if z is None else z
        nodes = [self._node(f"{name}{k}", (x, y, z), name, 0) for k, (x, y) in enumerate(points)]
        frm.alt = nodes[0]
        for a, b in zip(nodes, nodes[1:]):
            a.target = b
        if to is not None:
            nodes[-1].target = to
        ln = Line(name, nodes, False)
        ln.switch, ln.merge = frm, to
        self.lines.append(ln)
        return ln

    def gate(self, node: Node, name):
        """The track is closed at `node` until `name` fires (and closed again if it
        fires again): trains stop at the node before. Name a door or a breakable's
        target the same."""
        node.disabled = True
        self._rename(node, name)
        return node

    def stop(self, node: Node, label, board):
        """A platform beside `node`: the tram can be stopped here and the player get on
        and off. board: a point on the platform floor at its edge, next to the tram."""
        node.stop = (label, tuple(board))
        return node

    def rename(self, node, name):
        """Give a node a name of its own (a switch or a gate the map fires by name)."""
        self._rename(node, name)
        return node

    def _rename(self, node, name):
        if name in self._names and name != node.name:
            raise ValueError(f"track: two nodes named {name}")
        self._names.discard(node.name)
        self._names.add(name)
        node.name = name

    def before(self, node):
        """The node whose target is `node` (exactly one)."""
        found = [n for n in self.nodes if n.target is node]
        if len(found) != 1:
            raise ValueError(f"track: {node.name} has {len(found)} nodes leading into it, not 1")
        return found[0]

    def lift(self, bottom: Node, top: Node, name="lift", size=(LENGTH + 64, WIDTH + 48), speed=64,
             texture="-0CRETE2_FLR5", edge="LAB1_BRD3"):
        """A track lift (func_trackchange) between `bottom` and `top`, the same (x, y)
        on two lines, both running straight through it (size = along the track, across;
        the track runs along x or y there). It starts at the bottom. Going forward, a
        train always stops on it, and goes up or down with it; reversing, it crosses."""
        if bottom.pos[:2] != top.pos[:2] or top.pos[2] <= bottom.pos[2]:
            raise ValueError("track.lift: the top node must be straight above the bottom one")
        rise = top.pos[2] - bottom.pos[2]
        along = _heading(self.before(top), top)
        stops = []
        for n, tag in ((bottom, "down"), (top, "up")):
            p = self.before(n)
            if p.alt is not None:
                raise ValueError(f"track.lift: {p.name} (before the lift) is a switch")
            q = self.before(p)
            if _turn(_heading(q, p), _heading(p, n)) > 1:
                raise ValueError(f"track.lift: the track must run straight through {p.name}, the node before the "
                                 "lift (the game only sees the tram on the lift if it comes in from that node)")
            s = self._node(f"{name}_{tag}", n.pos, n.line, 1)
            s.netname = name
            p.target, p.alt = s, n                 # forward: onto the lift's dead end; n's previous stays p
            p.lift_link = True
            stops.append(s)
        lx, ly = (size[0], size[1]) if abs(along[0]) > abs(along[1]) else (size[1], size[0])
        x, y, z = top.pos
        slab = box((x - lx / 2, y - ly / 2, z - 16), (x + lx / 2, y + ly / 2, z),
                   {"top": texture, "default": edge}, comment="lift platform")
        ent = Entity("func_trackchange", brushes=[slab, box((x - 8, y - 8, z - 16), (x + 8, y + 8, z), "ORIGIN")],
                     targetname=name, toptrack=top.name, bottomtrack=bottom.name, train=self.tram_name,
                     height=rise, speed=speed, spawnflags=TRACKCHANGE_STARTBOTTOM, movesnd=8, stopsnd=4,
                     volume=0.85)                   # (the ORIGIN brush gives it its origin)
        half = (along[0] * lx / 2, along[1] * lx / 2)
        ent.add(*_rails((x - half[0], y - half[1], z), (x + half[0], y + half[1], z), ends=0))
        self.lifts.append((bottom, top, ent, stops, (lx, ly)))
        return ent

    def lift_holes(self):
        """Where each lift passes through a level above its bottom: [((x0, y0, x1, y1),
        z)] (the shaft's opening, the lift's footprint). Keep the live rail out of them
        (live_rail(..., holes=)): the tram rides up through them, with the player."""
        out = []
        for bottom, top, _, _, (lx, ly) in self.lifts:
            x, y, z = top.pos
            out.append(((x - lx / 2 - 8, y - ly / 2 - 8, x + lx / 2 + 8, y + ly / 2 + 8), z))
        return out

    def tram(self, at: Node, name=None, speed=SPEED, dmg=25, sounds=6):
        """The tram (func_tracktrain), built where it starts: at `at`, whose track must
        run west from there (the engine turns a train to face along the track plus 180
        degrees, so it's built facing west and needs no turn at the start)."""
        if at.target is None or not (at.target.pos[0] < at.pos[0] and at.target.pos[1] == at.pos[1]):
            raise ValueError(f"track.tram: the track must run west from {at.name}")
        name = name or self.tram_name
        self.tram_name = name
        for _, _, ent, _, _ in self.lifts:
            ent["train"] = name
        x, y, z = at.pos
        ent = Entity("func_tracktrain", brushes=tram_brushes((x, y, z)), targetname=name, target=at.name,
                     speed=speed, height=HEIGHT, wheels=WHEELS, startspeed=0, bank=0, dmg=dmg, sounds=sounds,
                     volume=10, spawnflags=TRAIN_NOPITCH, kv={"_minlight": 0.15, "hlmap_deck": DECK})
        self.train = (at, ent)
        return ent

    # ------------------------------------------------------------ output
    def edges(self):
        """(a, b) for every stretch of track: targets and switches' other ways (each
        stretch once, however many links run along it)."""
        out, seen = [], set()
        for n in self.nodes:
            for b in (n.target, n.alt):
                if b is None or b.pos == n.pos:
                    continue
                key = frozenset((n.pos, b.pos))
                if key not in seen:
                    seen.add(key)
                    out.append((n, b))
        return out

    def switches(self):
        """Nodes that are switches (a branch leaves there), not lift links."""
        return [n for n in self.nodes if n.alt is not None and not n.lift_link]

    def check(self):
        """Mistakes the game won't tell you about: a lift node a loop goes round without
        passing (the train gets lost there), a tram missing, a dead end with no stop."""
        problems = []
        if self.train is None:
            problems.append("no tram")
        g = Graph.from_track(self)
        sw = [g.by_name[n.name] for n in self.switches()]
        for bottom, top, *_ in self.lifts:
            for n in (bottom, top):
                for alts in _switch_states(sw):
                    if g.nearest_chain(g.by_name[n.name], alts) is None:
                        names = sorted(g.nodes[k]["name"] for k in alts)
                        problems.append(f"lift node {n.name}: following the track from it (switched: "
                                        f"{names or 'none'}) goes round a loop that doesn't pass it again (the "
                                        "game would lose the tram)")
                        break
        return problems

    def smooth(self, d=ROUND):
        """Round the corners, so the tram swings less (the game aims it at the track
        `wheels` ahead: at a 45-degree corner its ends swing ~80 units out): a corner
        node becomes two, `d` before and after it (two half turns); where a node can't
        move (a switch, a stop, a gate, a merge, the lift's), a node `d` out on each
        way that turns off makes the first half turn. Runs once, from entities().
        Line.at() finds nodes by where they were placed: look them up before."""
        if self._smoothed:
            return
        self._smoothed = True
        pinned = {n for n in self.nodes if n.stop or n.netname or n.disabled or n.alt is not None}
        for bottom, top, _, stops, _ in self.lifts:
            pinned |= {bottom, top, *stops, *(self.before_any(n) for n in (bottom, top))}
        if self.train:
            pinned.add(self.train[0])

        def preds(n):
            return [p for p in self.nodes if p.target is n or p.alt is n]
        for n in list(self.nodes):                       # plain corners: one way in, one way out
            ps = preds(n)
            if n in pinned or len(ps) != 1 or n.target is None:
                continue
            p, q = ps[0], n.target
            if not p.pos[2] == n.pos[2] == q.pos[2] or _turn(_heading(p, n), _heading(n, q)) < 20:
                continue
            u, v = _heading(p, n), _heading(n, q)
            dd = min(d, _dist(p, n) / 2 - 1, _dist(n, q) / 2 - 1)
            x, y, z = n.pos
            nb = self._node(f"{n.name}r", (round(x + v[0] * dd), round(y + v[1] * dd), z), n.line, n.priority)
            nb.target, n.target = q, nb
            n.pos = (round(x - u[0] * dd), round(y - u[1] * dd), z)
        for n in list(self.nodes):                       # turning off where a node can't move
            ps = [p for p in preds(n) if p.target is n] or preds(n)
            if not ps or n.lift_link:
                continue
            u = _heading(max(ps, key=lambda p: p.priority), n)
            for attr in ("target", "alt"):
                q = getattr(n, attr)
                if q is None or q.pos[2] != n.pos[2] or _dist(n, q) < 4 * d or _turn(u, _heading(n, q)) < 20:
                    continue
                if n not in pinned and len(preds(n)) == 1 and attr == "target":
                    continue                             # (already rounded)
                h = _unit((u[0] + _heading(n, q)[0], u[1] + _heading(n, q)[1]))
                x, y, z = n.pos
                prio = q.priority if attr == "alt" else n.priority
                xn = self._node(f"{n.name}{attr[0]}", (round(x + h[0] * d), round(y + h[1] * d), z), n.line, prio)
                xn.target = q
                setattr(n, attr, xn)
        for m in list(self.nodes):                       # joining where a node can't move (merges)
            ps = preds(m)
            if len(ps) < 2 or m.target is None:
                continue
            v = _heading(m, m.target)
            for p in ps:
                if p.lift_link or _dist(p, m) < 4 * d or _turn(_heading(p, m), v) < 20:
                    continue
                w = _heading(p, m)
                h = _unit((w[0] + v[0], w[1] + v[1]))
                x, y, z = m.pos
                xn = self._node(f"{m.name}j{p.name}", (round(x - h[0] * d), round(y - h[1] * d), z), p.line,
                                p.priority)
                xn.target = m
                if p.target is m:
                    p.target = xn
                else:
                    p.alt = xn

    def before_any(self, node):
        """A node leading into `node` (its target, else its altpath)."""
        return next((n for n in self.nodes if n.target is node), None) or \
            next((n for n in self.nodes if n.alt is node), None)

    def entities(self):
        """The path_tracks (branches and lift stops first, so where ways join, the
        main line is the one behind), the rails and sleepers (one func_illusionary per
        stretch, so each is drawn only where it's seen), the lifts and the tram.
        Rounds the corners first (smooth)."""
        self.smooth()
        problems = self.check()
        if problems:
            raise ValueError("track: " + "; ".join(problems))
        out = []
        for n in sorted(self.nodes, key=lambda n: n.priority):
            kv = {"targetname": n.name, "origin": n.pos}
            if n.target is not None:
                kv["target"] = n.target.name
            if n.alt is not None:
                kv["altpath"] = n.alt.name
            if n.disabled:
                kv["spawnflags"] = SF_DISABLED
            if n.netname:
                kv["netname"] = n.netname
            if n.message:
                kv["message"] = n.message
            if n.stop:
                kv["hlmap_stop"], kv["hlmap_board"] = n.stop[0], n.stop[1]
            kv.update(n.kv)
            out.append(Entity("path_track", kv=kv))
        for a, b in self.edges():
            pa, pb = a.pos, b.pos
            for bottom, _, _, _, (lx, _) in self.lifts:     # on the lift its platform carries the rails
                if pa[:2] == bottom.pos[:2]:
                    pa = _toward(pa, pb, lx / 2 + 6)
                if pb[:2] == bottom.pos[:2]:
                    pb = _toward(pb, pa, lx / 2 + 6)
            brushes = _rails(pa, pb)
            if brushes:
                out.append(Entity("func_illusionary", brushes=brushes))
        for *_, ent, _, _ in self.lifts:
            out.append(ent)
        if self.train:
            out.append(self.train[1])
        return out

    def diagram(self, size=(256, 192), title="LINE MAP", levels=None):
        """A board of the network in plan: lines (each level its own colour), switches,
        the lift, stops by name."""
        from .art import line_map
        lvls = sorted({n.pos[2] for n in self.nodes}) if levels is None else levels
        segs = [((a.pos[0], a.pos[1]), (b.pos[0], b.pos[1]), lvls.index(a.pos[2]) if a.pos[2] in lvls else 0)
                for a, b in self.edges()]
        stops = [(n.stop[0], (n.pos[0], n.pos[1])) for n in self.nodes if n.stop]
        switches = [(n.pos[0], n.pos[1]) for n in self.nodes if n.alt is not None and not n.netname
                    and not any(n.alt is b for b, *_ in self.lifts)]
        lifts = [(b.pos[0], b.pos[1]) for b, *_ in self.lifts]
        return line_map(segs, stops, switches, lifts, size=size, title=title)


# ------------------------------------------------------------ the engine's view (shared with sim and verify)

class Graph:
    """The path_tracks as the game links them (HLSDK CPathTrack::Link, in entity
    order): next, alternate, previous. Built from compiled entity dicts (sim, verify)
    or from a Track (its own check)."""

    def __init__(self, nodes):
        # nodes: [{name, origin, target, altpath, flags, netname, message, stop, board, index}]
        self.nodes = nodes
        self.by_name = {}
        for k, n in enumerate(nodes):
            self.by_name.setdefault(n["name"], k)
        self.next = [None] * len(nodes)
        self.alt = [None] * len(nodes)
        self.prev = [None] * len(nodes)
        for k, n in enumerate(nodes):           # Activate -> Link, in entity order; unnamed ones don't link
            if not n["name"]:
                continue
            t = self.by_name.get(n["target"]) if n["target"] else None
            if t is not None:
                self.next[k] = t
                self._set_prev(t, k)
            a = self.by_name.get(n["altpath"]) if n["altpath"] else None
            if a is not None:
                self.alt[k] = a
                self._set_prev(a, k)

    def _set_prev(self, k, p):
        if self.nodes[p]["name"] != (self.nodes[k]["altpath"] or None):   # not my own alternate
            self.prev[k] = p

    @classmethod
    def from_entities(cls, ents):
        nodes = []
        for i, e in enumerate(ents):
            if e.get("classname") != "path_track":
                continue
            nodes.append({"index": i, "name": e.get("targetname") or "",
                          "origin": tuple(float(c) for c in (e.get("origin") or "0 0 0").split()),
                          "target": e.get("target"), "altpath": e.get("altpath"),
                          "flags": int(float(e.get("spawnflags") or 0)), "netname": e.get("netname"),
                          "message": e.get("message"), "stop": e.get("hlmap_stop"),
                          "board": tuple(float(c) for c in e["hlmap_board"].split()) if e.get("hlmap_board") else None})
        return cls(nodes)

    @classmethod
    def from_track(cls, track):
        def kv(n):
            return {"index": None, "name": n.name, "origin": n.pos,
                    "target": n.target.name if n.target else None, "altpath": n.alt.name if n.alt else None,
                    "flags": SF_DISABLED if n.disabled else 0, "netname": n.netname, "message": n.message,
                    "stop": n.stop[0] if n.stop else None, "board": n.stop[1] if n.stop else None}
        return cls([kv(n) for n in sorted(track.nodes, key=lambda n: n.priority)])

    def get_next(self, k, alternate):
        """CPathTrack::GetNext with `alternate` the set of switched nodes."""
        if self.alt[k] is not None and k in alternate and not self.nodes[k]["flags"] & SF_ALTREVERSE:
            return self.alt[k]
        return self.next[k]

    def get_prev(self, k, alternate):
        if self.alt[k] is not None and k in alternate and self.nodes[k]["flags"] & SF_ALTREVERSE:
            return self.alt[k]
        return self.prev[k]

    def nearest_chain(self, k, alternate):
        """The nodes CPathTrack::Nearest looks through from k (following next as
        switched), or None if it gives up (a loop that never comes back to k)."""
        chain, p = [k], self.get_next(k, alternate)
        while p is not None and p != k:
            chain.append(p)
            if len(chain) > NEAREST_LIMIT or len(chain) > 2 * len(self.nodes):
                return None
            p = self.get_next(p, alternate)
        return chain

    def nearest(self, k, pos, alternate):
        """CPathTrack::Nearest: the node of k's chain closest to pos in plan (None:
        "bad sequence of path_tracks", the train is lost)."""
        chain = self.nearest_chain(k, alternate)
        if chain is None:
            return None
        best, dist = k, None
        for c in chain:
            o = self.nodes[c]["origin"]
            d = math.hypot(o[0] - pos[0], o[1] - pos[1])
            if dist is None or d < dist:
                best, dist = c, d
        return best

    def drive(self, start, alternate, disabled):
        """Where a train at node `start` can go (forward and back, as switched, never
        into a disabled node): {node: how}, how = 'f'/'b' (arrived going forward /
        backward; 'fb' both) or '' for the start; and the dead ends it can run into:
        [(node, direction)] where a node's next (going forward) or previous (going
        back) is missing or closed: the train stops there and fires its netname."""
        def ok(n):
            return n is not None and n not in disabled
        seen = {start: ""}
        todo = [start]
        ends = set()
        while todo:
            k = todo.pop()
            for nxt, d in ((self.get_next(k, alternate), "f"), (self.get_prev(k, alternate), "b")):
                if ok(nxt):
                    if d not in seen.get(nxt, "x"):
                        seen[nxt] = seen.get(nxt, "") + d
                        todo.append(nxt)
                elif d in seen[k] or (k == start and seen[k] == ""):
                    # moving this way into k (or starting from k): the train runs into the end here
                    ends.add((k, d))
        return seen, sorted(ends)


def _switch_states(sw):
    """Every combination of the switches `sw` (up to 2^10 of them; beyond that, each
    switch on its own)."""
    if len(sw) <= 10:
        for mask in range(1 << len(sw)):
            yield {s for b, s in enumerate(sw) if mask >> b & 1}
    else:
        yield set()
        for s in sw:
            yield {s}


def _unit(v):
    L = math.hypot(*v) or 1
    return (v[0] / L, v[1] / L)


def _dist(a, b):
    return math.hypot(b.pos[0] - a.pos[0], b.pos[1] - a.pos[1])


def _turn(u, v):
    """The angle between two directions, degrees."""
    return math.degrees(math.acos(max(-1.0, min(1.0, u[0] * v[0] + u[1] * v[1]))))


def _toward(p, q, d):
    L = math.hypot(q[0] - p[0], q[1] - p[1]) or 1
    return (p[0] + (q[0] - p[0]) * d / L, p[1] + (q[1] - p[1]) * d / L, p[2])


def _heading(a, b):
    dx, dy = b.pos[0] - a.pos[0], b.pos[1] - a.pos[1]
    d = math.hypot(dx, dy) or 1
    return (dx / d, dy / d)


def _quad(c, u, v, hu, hv, z0, z1, tex):
    """A box `2hu` along u by `2hv` along v, centred on c (x, y), rounded to whole units."""
    pts = [(round(c[0] + su * hu * u[0] + sv * hv * v[0]), round(c[1] + su * hu * u[1] + sv * hv * v[1]))
           for su, sv in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    if len(set(pts)) < 4:
        return None
    return prism(pts, z0, z1, tex)


def _rails(a, b, ends=6, gauge=GAUGE, sleeper_every=48):
    """Two rails from a to b (stretched `ends` past each, to meet at corners) on
    sleepers."""
    (ax, ay, z), (bx, by, _) = a, b
    L = math.hypot(bx - ax, by - ay)
    if L < 1:
        return []
    u = ((bx - ax) / L, (by - ay) / L)
    v = (-u[1], u[0])
    mid = ((ax + bx) / 2, (ay + by) / 2)
    out = []
    for side in (-1, 1):
        c = (mid[0] + side * gauge / 2 * v[0], mid[1] + side * gauge / 2 * v[1])
        q = _quad(c, u, v, L / 2 + ends, 2, z + 4, z + 10, RAIL_TEX)
        if q:
            out.append(q)
    n = int(L // sleeper_every)
    for k in range(n):
        s = (k + 0.5) * L / n
        c = (ax + u[0] * s, ay + u[1] * s)
        q = _quad(c, u, v, 6, gauge / 2 + 16, z, z + 4, SLEEPER_TEX)
        if q:
            out.append(q)
    return out


def tram_brushes(at):
    """The tram, built at node `at` facing west (-x): a flatbed on two bogies, a
    driver's console at the front, side rails with a gap in the middle of each side
    (to get on and off), a canopy on four posts. Its origin brush is HEIGHT over the
    node."""
    x, y, z = at
    L2, W2 = LENGTH / 2, WIDTH / 2
    T = TRAM_TEX
    deck = z + DECK
    b = []
    for bx in (x - 60, x + 60):                            # bogies on the rails
        b.append(box((bx - 24, y - 40, z + 6), (bx + 24, y + 40, z + 30), T["body"], comment="bogie"))
    b.append(box((x - L2, y - W2 + 4, z + 30), (x + L2, y + W2 - 4, deck - 8),
                 {"default": T["trim"], "west": T["bumper"], "east": T["bumper"]}, comment="chassis"))
    b.append(box((x - L2, y - W2, deck - 8), (x + L2, y + W2, deck),
                 {"top": T["deck"], "default": T["trim"]}, comment="deck").fit("top", T["deck"],
                                                                                 u_axis=(0, -1, 0), v_axis=(1, 0, 0)))
    con = box((x - L2, y - 32, deck), (x - L2 + 20, y + 32, deck + 40), {"default": T["trim"], "east": T["front"]},
              comment="console")
    con.fit("east", T["front"])
    b.append(con)
    for sy in (-1, 1):                                      # head and tail lamps
        b.append(box((x - L2 - 2, y + sy * 40 - 6, z + 32), (x - L2, y + sy * 40 + 6, z + 44), T["head"]))
        b.append(box((x + L2, y + sy * 40 - 6, z + 32), (x + L2 + 2, y + sy * 40 + 6, z + 44), T["tail"]))
    for sy in (-1, 1):                                      # side rails, a gap of 80 in the middle
        y0, y1 = (y - W2, y - W2 + 4) if sy < 0 else (y + W2 - 4, y + W2)
        for x0, x1 in ((x - L2, x - 40), (x + 40, x + L2)):
            b.append(box((x0, y0, deck + 36), (x1, y1, deck + 42), T["rail"], comment="side rail"))
        for px in (x - L2 + 2, x - 42, x + 42, x + L2 - 2):
            b.append(box((px - 2, y0, deck), (px + 2, y1, deck + 36), T["rail"]))
    for x0 in (x - L2, x + L2 - 4):                         # end rails
        b.append(box((x0, y - W2 + 4, deck + 36), (x0 + 4, y + W2 - 4, deck + 42), T["rail"]))
    for px in (x - L2 + 2, x + L2 - 2):                     # canopy posts and roof
        for py in (y - W2 + 2, y + W2 - 2):
            b.append(box((px - 2, py - 2, deck + 42), (px + 2, py + 2, z + ROOF - 8), T["rail"]))
    b.append(box((x - L2, y - W2, z + ROOF - 8), (x + L2, y + W2, z + ROOF),
                 {"default": T["trim"], "top": T["deck"]}, comment="canopy"))
    b.append(box((x - 8, y - 8, z + HEIGHT - 8), (x + 8, y + 8, z + HEIGHT + 8), "ORIGIN"))
    return b


def live_rail(floors, top=DECK - 8, dmg=1000, holes=()):
    """The live rail: one trigger_hurt (shock) over track beds, `top` units deep, up to
    under the tram's deck and the platforms. floors: [(convex polygon [(x, y), ...], bed
    z)]. Anyone on the bed dies; riders and people on platforms don't touch it. (The
    game tests a brush trigger's own hull, not its bounding box, so one entity can
    cover a whole level of track: verify does the same.)
    holes: [((x0, y0, x1, y1), z)] kept clear on the floors at height z: a lift's
    opening (Track.lift_holes()), which the tram rides up through with the player."""
    pieces = []
    for poly, z in floors:
        parts = [poly]
        for (x0, y0, x1, y1), hz in holes:
            if hz != z:
                continue
            nxt = []
            for p in parts:                  # outside the hole: west, east, and south / north between
                nxt += [_clip(p, [(1, 0, x0)]), _clip(p, [(-1, 0, -x1)]),
                        _clip(p, [(-1, 0, -x0), (1, 0, x1), (0, 1, y0)]),
                        _clip(p, [(-1, 0, -x0), (1, 0, x1), (0, -1, -y1)])]
            parts = [q for q in nxt if q]
        pieces += [(q, z) for q in parts]
    return Entity("trigger_hurt", brushes=[prism(q, z, z + top, "AAATRIGGER") for q, z in pieces],
                  kv={"dmg": dmg, "damagetype": 256})


def _clip(poly, halfplanes):
    """A convex polygon cut down to a*x + b*y <= c for each (a, b, c); None if (almost)
    nothing is left."""
    pts = [tuple(p) for p in poly]
    for a, b, c in halfplanes:
        out = []
        for i, p in enumerate(pts):
            q = pts[(i + 1) % len(pts)]
            fp, fq = a * p[0] + b * p[1] - c, a * q[0] + b * q[1] - c
            if fp <= 0:
                out.append(p)
            if (fp < 0 < fq) or (fq < 0 < fp):
                t = fp / (fp - fq)
                out.append((round(p[0] + (q[0] - p[0]) * t), round(p[1] + (q[1] - p[1]) * t)))
        pts = list(dict.fromkeys(out))
        if len(pts) < 3:
            return None
    area = sum(pts[i][0] * pts[(i + 1) % len(pts)][1] - pts[(i + 1) % len(pts)][0] * pts[i][1]
               for i in range(len(pts))) / 2
    return pts if abs(area) >= 16 else None


def switch_sign(pos, facing, name, labels, w=64, h=24):
    """A route indicator next to a switch's lever: shows labels[0] (the switch's
    target) and flips to labels[1] (its altpath) each time `name` (the switch node's
    name, which the lever fires) fires: a func_wall named the same, on +0/+A frames."""
    from . import props
    from .art import plate
    from .mapfile import prepare_texture
    stem = props._texname("SW", name)[:13]
    tex = {f"+0{stem}": plate(labels[0], (w, h), "white"), f"+A{stem}": plate(labels[1], (w, h), "warning")}
    prepared = {k: prepare_texture(k, v) for k, v in tex.items()}     # (registers them for fit)
    art = props.wall_art(pos, facing, f"+0{stem}", w, h, depth=1, frame="OUT_GALV1")
    ent = Entity("func_wall", brushes=art.brushes, targetname=name)
    ent.textures = prepared
    return ent
