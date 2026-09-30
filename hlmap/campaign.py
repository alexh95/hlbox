"""Campaigns: maps joined by level transitions.

Each map is its own script (maps/<name>.py). maps/campaign.py lists them in the order
a player meets them and defines the Links between them:

    from hlmap.campaign import Link
    MAPS = ["office", "labs"]
    LINK = Link("tunnel", ("office", "labs"), zone=((-512, -512, 0), (512, 512, 192)),
                origins={"office": (2128, 1632, 0), "labs": (-944, 96, 0)},
                triggers={"office": ((-128, 128, 0), (128, 192, 192)),
                          "labs": ((-128, -192, 0), (128, -128, 192))},
                build=tunnel_zone,          # tunnel_zone(m, lvl, origin) builds the zone
                carries=["sector_pass", "brief_pending"])

A Link is a stretch of level that both maps build identically (the zone), around a
landmark at `origin`. Each map calls link.place(m, lvl) before lvl.build(m) and gets:
  - the zone, from the shared build function (rooms, lights, signs),
  - an info_landmark named after the link,
  - a trigger_transition over the zone (only entities inside it travel along),
  - a trigger_changelevel to the other map over its side's trigger box.

Half-Life keeps the player's offset from the landmark, so walking into one map's
trigger puts them at the same spot of the other map's copy of the zone. Put each map's
trigger where the zone's far end is out of sight, and the other map's trigger well
away from where the player lands (or they bounce straight back). Global states
(logic.Flag) carry over; everything else is fresh, or as it was left when returning.
`carries` names the global states the other map cares about: verify explores every
way of setting them before the player leaves (even ones no door depends on), so the
next map is checked with each combination the player can arrive with.

Coordinates in `zone` and `triggers` are relative to the origin. The origins must
differ by multiples of 512, so textures aligned to the world line up in both copies.

Checks (python -m hlmap verify <map>, see check_transition):
  - every changelevel is reachable, and the global states the player can leave with
    (build/<map>/exits.json) are where the next map's verification starts;
  - both maps have the landmark, once;
  - the changelevel is inside the transition volume (else the game refuses to change);
  - every spot where the player touches the trigger lands them standing in the other
    map, not in a wall, not in mid-air, not touching a trigger that sends them back;
  - the zone looks the same: every visible surface inside it has a match in the other
    map (plane, texture, texture alignment), and the floor light where the player
    lands is about the same.
"""
from __future__ import annotations

import importlib
import json
import sys

from . import config
from .geometry import box
from .mapfile import Entity

ALIGN = 512       # origins differ by multiples of this (textures up to 512 line up)


class Link:
    def __init__(self, name, maps, zone, origins, triggers, build, carries=()):
        self.name = name                     # the landmark's and the transition volume's name
        self.carries = tuple(carries)        # global states that matter on the other side
        self.maps = tuple(maps)              # (earlier map, later map) in campaign order
        self.zone = (tuple(zone[0]), tuple(zone[1]))
        self.origins = {k: tuple(v) for k, v in origins.items()}
        self.triggers = {k: (tuple(v[0]), tuple(v[1])) for k, v in triggers.items()}
        self.build = build
        if set(self.origins) != set(self.maps) or set(self.triggers) != set(self.maps):
            raise ValueError(f"link {name}: origins and triggers are needed for both {self.maps}")
        a, b = (self.origins[m] for m in self.maps)
        if any((b[k] - a[k]) % ALIGN for k in range(3)):
            raise ValueError(f"link {name}: the origins {a} and {b} must differ by multiples of {ALIGN} "
                             "(or textures aligned to the world won't line up across the transition)")
        (zl, zh) = self.zone
        for m_, (lo, hi) in self.triggers.items():
            if not all(zl[k] <= lo[k] and hi[k] <= zh[k] for k in range(3)):
                raise ValueError(f"link {name}: {m_}'s trigger must lie inside the zone "
                                 "(the game only changes level from inside the transition volume)")

    def other(self, map_name):
        a, b = self.maps
        if map_name not in self.maps:
            raise ValueError(f"link {self.name} joins {a} and {b}, not {map_name}")
        return b if map_name == a else a

    def landmark(self, map_name):
        o = self.origins[map_name]
        return (o[0], o[1], o[2] + 32)       # a little above the zone's floor

    def absolute(self, rel_box, map_name):
        o = self.origins[map_name]
        return tuple(tuple(c[k] + o[k] for k in range(3)) for c in rel_box)

    def place(self, m, lvl):
        """Build the zone in map `m` (before lvl.build(m)) and add the landmark, the
        transition volume and the changelevel to the other map. Returns whatever the
        zone's build function returns (e.g. its rooms, to connect to)."""
        other = self.other(m.name)
        out = self.build(m, lvl, self.origins[m.name])
        zlo, zhi = self.absolute(self.zone, m.name)
        tlo, thi = self.absolute(self.triggers[m.name], m.name)
        m.add(Entity("info_landmark", targetname=self.name, origin=self.landmark(m.name)),
              Entity("trigger_transition", brushes=[box(zlo, zhi, "AAATRIGGER", comment="transition volume")],
                     targetname=self.name),
              Entity("trigger_changelevel", brushes=[box(tlo, thi, "AAATRIGGER", comment=f"to {other}")],
                     map=other, landmark=self.name))
        return out


# ---------------------------------------------------------------- the campaign file

def definition():
    """maps/campaign.py as a module (None if there is none); the same module the map
    scripts import."""
    if not (config.MAPS_SRC_DIR / "campaign.py").exists():
        return None
    root = str(config.MAPS_SRC_DIR.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    return importlib.import_module("maps.campaign")


def order():
    mod = definition()
    return list(getattr(mod, "MAPS", [])) if mod else []


def links():
    """Every Link defined in maps/campaign.py."""
    mod = definition()
    return [v for v in vars(mod).values() if isinstance(v, Link)] if mod else []


def carried(map_name):
    """Global states the campaign's links from or to `map_name` carry."""
    return sorted({g for ln in links() if map_name in ln.maps for g in ln.carries})


def exits_path(map_name):
    return config.BUILD_DIR / map_name / "exits.json"


def save_exits(map_name, hulls, found, reached):
    """Record how the player can leave `map_name` (build/<map>/exits.json):
    {target map: {"landmark":, "at": landmark origin, "states": [{"globals":,
    "position":, "path":}], "touch": [every position touching the trigger]}}.
    found: progression's exits {(target, landmark): [(globals, position, path)]}."""
    from .verify import touches_box
    marks = _landmarks(hulls.entities)
    boxes = {(t, lm): b for t, lm, b in changelevels(hulls)}
    data = {}
    for (target, lm), states in found.items():
        lo, hi = boxes[(target, lm)]
        data[target] = {"landmark": lm, "at": list(marks.get(lm, [(0, 0, 0)])[0]),
                        "states": [{"globals": g, "position": list(p), "path": path} for g, p, path in states],
                        "touch": sorted(list(p) for p in reached if touches_box(p, lo, hi))}
    exits_path(map_name).parent.mkdir(parents=True, exist_ok=True)
    exits_path(map_name).write_text(json.dumps(data, indent=1))


def touched_from(map_name, target):
    """Positions in `map_name` from which the player touches its changelevel into
    `target` (from its last verify), or None."""
    p = exits_path(map_name)
    if not p.exists():
        return None
    data = json.loads(p.read_text()).get(target)
    return [tuple(x) for x in data["touch"]] if data else None


def entries(map_name):
    """How the player arrives in `map_name` from earlier maps of the campaign:
    [(from map, landmark, globals, position in THIS map)]. Positions are translated
    through the landmarks of the two compiled maps. Returns None when an earlier map
    that links here hasn't been verified yet."""
    maps = order()
    if map_name not in maps:
        return []
    from .verify import Hulls
    here = config.BUILD_DIR / map_name / f"{map_name}.bsp"
    marks_here = _landmarks(Hulls(here).entities) if here.exists() else {}
    out, missing = [], False
    for prev in maps[:maps.index(map_name)]:
        p = exits_path(prev)
        if not p.exists():
            missing = True
            continue
        data = json.loads(p.read_text()).get(map_name)
        if not data:
            continue
        name = data["landmark"]
        if len(marks_here.get(name, [])) != 1:
            continue                         # check_transition reports it
        d = tuple(marks_here[name][0][k] - data["at"][k] for k in range(3))
        for s in data["states"]:
            pos = tuple(s["position"][k] + d[k] for k in range(3))
            out.append((prev, name, {k: int(v) for k, v in s["globals"].items()}, pos))
    return None if missing and not out else out


# ---------------------------------------------------------------- checking a transition

def _landmarks(ents):
    out = {}
    for e in ents:
        if e.get("classname") == "info_landmark" and e.get("targetname") and e.get("origin"):
            out.setdefault(e["targetname"], []).append(tuple(float(c) for c in e["origin"].split()))
    return out


def changelevels(hulls):
    """[(target map, landmark, (mins, maxs))] of a compiled map's trigger_changelevels."""
    from .verify import _placed
    models = hulls.models()
    return [(e.get("map", ""), e.get("landmark", ""), _placed(models, e)) for e in hulls.entities
            if e.get("classname") == "trigger_changelevel" and e.get("model", "").startswith("*")]


def check_transition(ha, hb, a_name, b_name, reached_a, light_levels=None):
    """Check the level change from compiled map A (Hulls ha) into B (hb).
    reached_a: standing positions the player can reach in A (verify's progression).
    Returns (problems, warnings, notes), each a list of strings."""
    from .verify import FloorLight, Walker, _placed, touches_box
    problems, warnings, notes = [], [], []
    links = [(lm, box_) for target, lm, box_ in changelevels(ha) if target == b_name]
    if not links:
        return problems, warnings, notes
    marks_a, marks_b = _landmarks(ha.entities), _landmarks(hb.entities)
    models_a = ha.models()
    for lm, (lo, hi) in links:
        what = f"{a_name} -> {b_name} ({lm})"
        if len(marks_a.get(lm, [])) != 1 or len(marks_b.get(lm, [])) != 1:
            problems.append(f"{what}: landmark {lm!r} appears {len(marks_a.get(lm, []))} time(s) in {a_name} and "
                            f"{len(marks_b.get(lm, []))} in {b_name}; it must be in each exactly once")
            continue
        la, lb = marks_a[lm][0], marks_b[lm][0]
        d = tuple(lb[k] - la[k] for k in range(3))
        volumes = [_placed(models_a, e) for e in ha.entities
                   if e.get("classname") == "trigger_transition" and e.get("targetname") == lm]
        if volumes and not any(all(v[0][k] <= lo[k] and hi[k] <= v[1][k] for k in range(3)) for v in volumes):
            problems.append(f"{what}: the changelevel is not inside the transition volume {lm!r}: "
                            "the game refuses to change level from outside it")
        # where the player touches the trigger, and where that lands them
        touch = sorted(p for p in reached_a if touches_box(p, lo, hi))
        if not touch:
            problems.append(f"{what}: no reachable position touches the changelevel")
            continue
        back = [box_ for target, lm2, box_ in changelevels(hb)]
        walker = Walker(hb)
        stuck, falling, bounce = [], [], []
        for p in touch:
            q = tuple(p[k] + d[k] for k in range(3))
            if hb.contents(1, q) != -1:
                stuck.append(q)
                continue
            ground = walker._drop(*[round(c) for c in q])
            if ground is None or q[2] - ground[2] > 18:
                falling.append(q)
            if any(touches_box(q, blo, bhi) for blo, bhi in back):
                bounce.append(q)
        for bad, why in ((stuck, "inside a wall"), (falling, "in mid-air (they fall)"),
                         (bounce, f"touching a changelevel (straight back to {a_name}?)")):
            if bad:
                problems.append(f"{what}: {len(bad)} of {len(touch)} landing spots are {why}, e.g. "
                                f"{tuple(round(c) for c in bad[0])}")
        if not (stuck or falling or bounce):
            notes.append(f"{what}: all {len(touch)} landing spots stand clear in {b_name}")
        # the zone must look the same in both maps
        zone = volumes[0] if volumes else None
        if zone is None:
            warnings.append(f"{what}: no trigger_transition named {lm!r}; everything in the landmark's view "
                            "that can travel (monsters, items) goes along, and the zone can't be compared")
        else:
            bad_a = _zone_mismatches(ha, hb, zone, d)
            bad_b = _zone_mismatches(hb, ha, tuple(tuple(c[k] + d[k] for k in range(3)) for c in zone),
                                     tuple(-c for c in d))
            total = bad_a[1] + bad_b[1]
            if bad_a[0] or bad_b[0]:
                problems.append(f"{what}: the zone differs between the maps at {len(bad_a[0]) + len(bad_b[0])} of "
                                f"{total} surface points, e.g.:")
                for m_, other, bad in ((a_name, b_name, bad_a[0]), (b_name, a_name, bad_b[0])):
                    for where, msg in bad[:3]:
                        problems.append(f"    {m_} at {where}: {msg} in {other}")
            else:
                notes.append(f"{what}: zone surfaces match ({total} points: planes, textures, alignment)")
        # light where the player lands, before and after
        if ha.bsp.lumps["lighting"] and hb.bsp.lumps["lighting"]:
            from .sim import World
            la_, lb_ = FloorLight(ha.bsp), FloorLight(hb.bsp)
            lv_a = light_levels or World(ha.entities).start().style_levels()
            lv_b = World(hb.entities).start().style_levels()
            worst = (0, None, 0, 0)
            for p in touch:
                q = tuple(p[k] + d[k] for k in range(3))
                va, vb = la_.at(p, lv_a), lb_.at(q, lv_b)
                diff = abs(va - vb)
                if diff > max(12, 0.25 * max(va, vb)) and diff > worst[0]:
                    worst = (diff, q, va, vb)
            if worst[1] is not None:
                warnings.append(f"{what}: the light jumps where the player lands: {worst[2]:.0f} in {a_name}, "
                                f"{worst[3]:.0f} in {b_name} at {tuple(round(c) for c in worst[1])}")
            else:
                notes.append(f"{what}: the light matches where the player lands")
    return problems, warnings, notes


def _tex_faces(hulls):
    """World faces with texture mapping: (normal, dist, polygon, texture, w, h, S, T)."""
    import struct
    b = hulls.bsp
    L = b.lumps
    verts = [struct.unpack_from("<3f", L["vertices"], i * 12) for i in range(len(L["vertices"]) // 12)]
    edges = [struct.unpack_from("<2H", L["edges"], i * 4) for i in range(len(L["edges"]) // 4)]
    surf = struct.unpack_from(f"<{len(L['surfedges']) // 4}i", L["surfedges"])
    tex = b.textures()
    info = [struct.unpack_from("<8fii", L["texinfo"], i * 40) for i in range(len(L["texinfo"]) // 40)]
    m = struct.unpack_from("<9f4i3i", L["models"], 0)
    out = []
    for i in range(m[14], m[14] + m[15]):
        plane, side, fe, ne, ti = struct.unpack_from("<HHiHH", L["faces"], i * 20)
        nx, ny, nz, dist, _ = struct.unpack_from("<3ffi", L["planes"], plane * 20)
        n = (nx, ny, nz)
        if side:
            n, dist = (-nx, -ny, -nz), -dist
        poly = [verts[edges[e][0]] if e >= 0 else verts[edges[-e][1]] for e in surf[fe:fe + ne]]
        t = info[ti]
        name, w, h = tex[t[8]]
        out.append((n, dist, poly, name.upper(), w, h, t[0:4], t[4:8]))
    return out


def _samples(poly, n, step=32):
    """Points spread over a face: a grid in its plane, kept inside the polygon."""
    from .geometry import cross, dot, normalize, sub
    from .verify import _in_polygon
    u = normalize(sub(poly[1], poly[0]))
    v = cross(n, u)
    o = poly[0]
    us = [dot(sub(p, o), u) for p in poly]
    vs = [dot(sub(p, o), v) for p in poly]
    out = []
    a = min(us) + step / 2
    while a < max(us):
        b = min(vs) + step / 2
        while b < max(vs):
            p = tuple(o[k] + u[k] * a + v[k] * b for k in range(3))
            if _in_polygon(p, poly, n):
                out.append(p)
            b += step
        a += step
    c = tuple(sum(p[k] for p in poly) / len(poly) for k in range(3))
    return out or [c]


def _zone_mismatches(ha, hb, zone, d):
    """Surface points of A's world in `zone` (its walls, floor and ceiling included)
    with no matching surface in B at p + d: same plane, same texture, same texture
    alignment. A surface on the zone's boundary that B is open behind is where B's
    level goes on (the zone's far ends): not a mismatch.
    Returns ([(where, what)], points checked)."""
    from .geometry import dot
    from .verify import _in_polygon
    lo = tuple(zone[0][k] - 1 for k in range(3))
    hi = tuple(zone[1][k] + 1 for k in range(3))
    inside = lambda p: all(lo[k] <= p[k] <= hi[k] for k in range(3))

    def goes_on(p, q, n):
        on_edge = any(abs(n[k]) > 0.99 and min(abs(p[k] - zone[0][k]), abs(p[k] - zone[1][k])) < 1
                      for k in range(3))
        return on_edge and all(hb.contents(0, tuple(q[k] - n[k] * s for k in range(3))) != -2 for s in (4, 16))
    fb = _tex_faces(hb)
    index = {}
    for f in fb:
        index.setdefault((round(f[0][0], 2), round(f[0][1], 2), round(f[0][2], 2)), []).append(f)
    bad, checked = [], 0
    for n, dist, poly, name, w, h, S, T in _tex_faces(ha):
        if name.upper() in ("SKY", "AAATRIGGER", "NULL", "CLIP", "ORIGIN"):
            continue
        if not all(min(p[k] for p in poly) <= hi[k] and max(p[k] for p in poly) >= lo[k] for k in range(3)):
            continue
        for p in _samples(poly, n):
            if not inside(p):
                continue
            checked += 1
            q = tuple(p[k] + d[k] for k in range(3))
            want = dist + dot(n, d)
            match, why = None, f"{name} here, no surface"
            for f in index.get((round(n[0], 2), round(n[1], 2), round(n[2], 2)), ()):
                if abs(f[1] - want) > 0.1 or not _in_polygon(q, f[2], f[0]):
                    continue
                if f[3].upper() != name.upper():
                    why = f"{name} here, {f[3]}"
                    continue
                # the same texel lands on the same spot (texture coordinates agree mod size)
                s_a = dot(p, S[:3]) + S[3]
                t_a = dot(p, T[:3]) + T[3]
                s_b = dot(q, f[6][:3]) + f[6][3]
                t_b = dot(q, f[7][:3]) + f[7][3]
                ds, dt = (s_a - s_b) % w, (t_a - t_b) % h
                if min(ds, w - ds) > 0.5 or min(dt, h - dt) > 0.5:
                    why = f"{name} here, shifted by ({min(ds, w - ds):.0f}, {min(dt, h - dt):.0f}) texels"
                    continue
                match = f
                break
            if match is None and not (why.endswith("no surface") and goes_on(p, q, n)):
                bad.append((tuple(round(c) for c in p), why))
    return bad, checked
