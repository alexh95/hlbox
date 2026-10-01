"""Teleporters: pads that send the player to other pads, organised as networks.

    net = teleport.Network("transit", online=False)       # dark until net.start is fired
    chamber = net.pad("chamber", (1704, 592, 0), "south", site="TEST CHAMBER")
    hub = net.pad("hub1", (1024, -200, 0), "south", site="HUB")
    net.route(chamber, hub)              # both ways: each pad sends to the other's landing
    net.pad("hub2", (832, -200, 0), "south", site="HUB", label="OFFICE BASEMENT",
            link=campaign.OFFICE_PAD)    # a pad into another map
    net.pad("hub4", (784, -400, 0), "east", site="HUB", label="SITE 2", offline=True)
    m.add(net.entities(m))
    board = net.diagram()                # a picture of the network, for a wall

A pad is a raised disc with a sign on a post behind it saying where it goes. Stepping
onto its middle (a trigger_teleport) puts the player on the landing spot in front of
the destination pad, facing away from it, with a flash and a whoosh. Landing on the
pad itself would send them straight back, hence the spot in front.

Pads into other maps (`link=`, a campaign.PadLink): stepping on fires a changelevel
to the other map, where the same link's pad stands. The two pads face opposite ways
and the landmark sits half the landing distance in front of each, so the player lands
in front of the other pad facing away from it (Half-Life keeps the facing). A one-way
link (PadLink(..., one_way_from=map)) makes the other map's pad an arrivals pad: it
looks dark, says ARRIVALS, and does nothing when stepped on. (It still has a
changelevel back, which nothing can fire: the engine only brings the player across
between maps that link to each other.)

Power: a network that starts offline is a logic.Flag (`net.flag`, a global state, so
it's the same in every map of the campaign); its pads are dark (the disc's '+A'
frame, sprite and light off) and do nothing until `net.start` fires. A pad can have a
power of its own (`power=` a Flag, e.g. a clearance). Pads work while their power is
on (trigger_teleport masters). Each map lights its pads the first time it finds
their power on (at start, or on coming back), and remembers that it did.

Offline pads have no route: dark for good, with a sign naming the destination to
come. They are the slots new places plug into: give the pad a route or a link and it
lights up with the rest.

verify: the walker takes active teleporters as moves; every landing must stand
clear, off every pad and level change; every trip needs a way back (or at least must
not cut the player off from anything). Pads into other maps are checked like level
changes (campaign.check_transition). playtest --teleports / --links try them.
"""
from __future__ import annotations

from . import logic, props
from .art import network_diagram, transit_pad
from .geometry import box, cylinder
from .mapfile import Entity, prepare_texture

PAD_TEX = {"on": "+0TRANSITPAD", "off": "+ATRANSITPAD", "offline": "TRANSITPADOFF"}
DEPART = 0.1          # seconds from stepping on a pad into another map to the level change


class Pad:
    def __init__(self, net, name, pos, facing, site, label, offline, radius, arrive, link, power):
        self.net, self.name, self.pos, self.facing = net, name, tuple(pos), facing
        self.site, self.label, self.offline = site, label, offline
        self.radius, self.arrive = radius, (link.arrive if link else arrive)
        self.link = link                   # a campaign.PadLink: this pad leads to another map
        self.power = power                 # a logic.Flag of its own, else the network's
        self.to = None                     # the pad it sends the player to (same map)
        self.arrive_only = False           # the end of a one-way link: set by Network.entities

    @property
    def landing(self):
        """Where arrivals stand: in front of the pad, on its floor."""
        fx, fy = props.DIRS[self.facing]
        x, y, z = self.pos
        return (x + fx * self.arrive, y + fy * self.arrive, z)

    @property
    def land_name(self):
        return f"{self.name}_land"

    def __repr__(self):
        return f"<Pad {self.name} at {self.site}>"


class Network:
    def __init__(self, name, online=True, color=(120, 200, 255)):
        self.name = name
        self.color = color
        self.pads: list[Pad] = []
        self.flag = None if online else logic.Flag(f"{name}_online", False)
        self.start = f"{name}_start"       # fire to bring an offline network online
        self.sync = f"{name}_sync"         # fire after turning a pad's own power on (lights it)

    def pad(self, name, pos, facing, site, label=None, offline=False, radius=40, arrive=88, link=None,
            power=None):
        """A pad on the floor at `pos` (its centre), its landing spot `arrive` units
        toward `facing`. site: where it is (for the diagram); label: its sign (default:
        the site of the pad it sends to). link: a campaign.PadLink (the pad leads to
        another map); power: a logic.Flag that must be on (default: the network's)."""
        p = Pad(self, name, pos, facing, site, label, offline, radius, arrive, link, power)
        self.pads.append(p)
        return p

    def route(self, a, b, two_way=True):
        """Pad a sends the player to pad b's landing (and b to a's, if two_way)."""
        for src, dst in ((a, b), (b, a)) if two_way else ((a, b),):
            if src.offline or src.link:
                raise ValueError(f"pad {src.name} is {'offline' if src.offline else 'a link to another map'}: "
                                 "it can't have a route")
            if src.to is not None:
                raise ValueError(f"pad {src.name} already sends to {src.to.name}")
            src.to = dst

    def _power(self, p):
        return p.power or self.flag

    # ------------------------------------------------------------------ building
    def entities(self, m):
        """Everything the network needs in map `m` (its name keeps each map's record of
        which pads it has lit)."""
        for p in self.pads:
            if p.to is None and not p.offline and not p.link:
                raise ValueError(f"pad {p.name} goes nowhere: give it a route or a link, or make it offline")
            if p.link and m.name not in p.link.maps:
                raise ValueError(f"pad {p.name}: its link {p.link.name} joins {p.link.maps}, not {m.name}")
            p.arrive_only = bool(p.link) and not p.link.departs(m.name)
            if p.link and getattr(p.link, "network", self.name) != self.name:
                raise ValueError(f"pad {p.name}: its link {p.link.name} is on network {p.link.network!r}, "
                                 f"not {self.name!r} (the arrival flash would never go off)")
        self.map_name = m.name
        tex = {PAD_TEX[k]: prepare_texture(PAD_TEX[k], transit_pad(k, self.color)) for k in PAD_TEX}
        live = [p for p in self.pads if not p.offline and not p.arrive_only]
        o = self.pads[0].pos if self.pads else (0, 0, 0)
        o = (o[0], o[1], o[2] + 64)                  # logic entities: by a pad, inside the level
        groups = {}                                 # power flag -> pads (None: always on)
        for p in live:
            groups.setdefault(self._power(p), []).append(p)
        ents = []
        for p in self.pads:
            if p.offline or p.arrive_only:
                ents += self._pad(p, m, None, None)
        for k, (flag, pads) in enumerate(groups.items()):
            lights = f"{self.name}_lights{k}"
            for p in pads:
                ents += self._pad(p, m, lights, flag)
            if flag is None:
                continue
            # light this map's pads the first time their power is found on
            lit = logic.Flag(f"{flag.name}_lit_{m.name}", False, o)
            glow = [(g, 0.1 * j) for j, g in enumerate(x for p in pads for x in (f"{p.name}_disc", f"{p.name}_sprite"))]
            ents += lit.entities()
            ents += logic.when(f"{self.name}_sync{k}", f"{self.name}_light{k}", [flag.is_on, lit.is_off], o)
            ents += logic.sequence(f"{self.name}_light{k}", [(lit.on, 0), (lights, 0)] + glow, o)
        flags = [f for f in groups if f is not None]
        if self.flag:                               # a pad's own power flag belongs to the map
            self.flag.origin = o
            ents += self.flag.entities()
        if flags:
            ents += logic.sequence(f"{self.name}_sync", [(f"{self.name}_sync{k}", 0)
                                                         for k, f in enumerate(groups) if f is not None], o)
            ents.append(props.point("trigger_auto", o, target=f"{self.name}_sync", triggerstate=2, delay=0.2))
        if self.flag:
            ents.append(logic.gate(self.start, f"{self.name}_power", self.flag.is_off, o))
            ents += logic.sequence(f"{self.name}_power", [(self.flag.on, 0), (f"{self.name}_sync", 0.1)], o)
        if any(p.link for p in self.pads if not p.offline):
            ents += self._arrivals(o)
        for e in ents:
            if e.brushes and any(f.texture in tex for b in e.brushes for f in b.faces):
                e.textures = tex
        return ents

    def _arrivals(self, o):
        """Coming in by a pad from another map: a flash and a whoosh. The departing
        pad sets a global state; this map's trigger_auto (it fires at every load and
        return) sees it and clears it."""
        arriving = logic.Flag(f"{self.name}_arriving", False, o)
        return arriving.entities() + [
            props.point("trigger_auto", o, target=f"{self.name}_arrive", triggerstate=2, delay=0.1,
                        globalstate=arriving.state),
            props.point("env_fade", o, targetname=f"{self.name}_arrive_flash", duration=0.8, holdtime=0.2,
                        renderamt=255, rendercolor=(200, 230, 255), spawnflags=1),         # 1 = fade from
            props.sound_effect(f"{self.name}_arrive_snd", o, "ambience/port_suckout1.wav", everywhere=True),
            *logic.sequence(f"{self.name}_arrive", [(arriving.off, 0), (f"{self.name}_arrive_flash", 0),
                                                    (f"{self.name}_arrive_snd", 0)], o)]

    def _pad(self, p, m, lights, flag):
        x, y, z = p.pos
        R = p.radius
        fx, fy = props.DIRS[p.facing]
        master = flag.is_on if flag else None
        ents = [props.detail(cylinder((x, y), R, z, z + 8, sides=16, tex="OUT_GALV1", comment="transit pad"))]
        disc = cylinder((x, y), R - 6, z + 8, z + 9, sides=16, tex="OUT_GALV1", comment="transit pad disc")
        disc.fit("top", PAD_TEX["offline" if p.offline or p.arrive_only else ("off" if flag else "on")])
        if p.offline or p.arrive_only:
            ents.append(props.detail(disc))
        else:
            ents.append(Entity("func_wall", brushes=[disc], targetname=f"{p.name}_disc", frame=1 if flag else 0))
        # the sign on a post behind the pad, facing the way in
        bx, by = x - fx * (R + 10), y - fy * (R + 10)
        label = p.label or (p.to.site if p.to else "OFFLINE")
        text = f"{label}\nOFFLINE" if p.offline else f"ARRIVALS\n{label}" if p.arrive_only else label
        ents.append(props.detail(box((bx - 3, by - 3, z), (bx + 3, by + 3, z + 84), "OUT_GALV1", comment="pad post")))
        ents.append(props.sign((bx + fx * 3, by + fy * 3, z + 96), p.facing, text, 64,
                               24 if p.offline or p.arrive_only else 16, "red" if p.offline else "steel"))
        if p.arrive_only:                 # where the other map's pad puts the player
            half = p.arrive / 2
            ents.append(Entity("info_landmark", targetname=p.link.name, origin=(x + fx * half, y + fy * half, z + 32)))
            # the engine only brings the player across between maps that link to each
            # other: a changelevel back, use only and unnamed (nothing can fire it)
            inner = R - 14
            ents.append(Entity("trigger_changelevel", brushes=[box((x - inner, y - inner, z + 9), (x + inner, y + inner, z + 88),
                                                                   "AAATRIGGER", comment="link back (inert)")],
                               map=p.link.other(m.name), landmark=p.link.name, spawnflags=2,
                               kv={"hlmap_style": "portal", "hlmap_arrivals": 1}))
            return ents
        # where arrivals land (an offline pad can still be the end of a one-way route)
        lx, ly, lz = p.landing
        ents.append(props.point("info_teleport_destination", (lx, ly, lz), facing=p.facing, targetname=p.land_name))
        if p.offline:
            return ents
        # the glow over it, and its light
        ents.append(props.point("env_sprite", (x, y, z + 44), targetname=f"{p.name}_sprite", model="sprites/exit1.spr",
                                rendermode=5, renderamt=170, rendercolor=self.color, scale=0.6, framerate=10,
                                spawnflags=0 if flag else 1))
        ents.append(props.light((x, y, z + 60), color=self.color, brightness=70, targetname=lights,
                                spawnflags=1 if flag else 0))
        inner = R - 14
        pad_box = ((x - inner, y - inner, z + 9), (x + inner, y + inner, z + 88))
        # stepping on: a whoosh here and a flash (fired by a slightly larger volume, so
        # it goes off just before the jump)
        ents.append(props.sound_effect(f"{p.name}_whoosh", (x, y, z + 40), "debris/beamstart2.wav", radius="small"))
        ents.append(props.point("env_fade", (x, y, z + 40), targetname=f"{p.name}_flash", duration=0.6, holdtime=0.1,
                                renderamt=255, rendercolor=(200, 230, 255), spawnflags=1 | 4))  # from, this player
        if p.link:
            # into another map: the pad fires a changelevel (use only), after the flash
            other = p.link.other(m.name)
            kv = {"hlmap_style": "portal"}
            if master:
                kv["hlmap_master"] = master          # verify: usable only while powered
            ents.append(Entity("trigger_changelevel", brushes=[box(*pad_box, "AAATRIGGER", comment=f"to {other}")],
                               targetname=f"{p.name}_go", map=other, landmark=p.link.name, spawnflags=2, kv=kv))
            half = p.arrive / 2
            ents.append(Entity("info_landmark", targetname=p.link.name, origin=(x + fx * half, y + fy * half, z + 32)))
            # the game only changes level if the player is in the transition volume when
            # it fires: a player running across the pad (320 units/s, the pad lighting up
            # under them) is 32 on in the 0.1 s, well inside a volume 48 wider than the pad
            ents.append(Entity("trigger_transition", targetname=p.link.name,
                               brushes=[box((x - R - 48, y - R - 48, z), (x + R + 48, y + R + 48, z + 128),
                                            "AAATRIGGER", comment="transition volume")]))
            steps = [(f"{p.name}_whoosh", 0), (f"{p.name}_flash", 0), (f"{self.name}_arriving_on", 0),
                     (f"{p.name}_go", DEPART)]
        else:
            kv = {"master": master} if master else {}
            ents.append(Entity("trigger_teleport", brushes=[box(*pad_box, "AAATRIGGER", comment="teleporter")],
                               target=p.to.land_name, **kv))
            tx, ty, tz = p.to.landing
            ents.append(props.sound_effect(f"{p.name}_arrive", (tx, ty, tz + 40), "ambience/port_suckout1.wav",
                                           radius="small"))
            steps = [(f"{p.name}_whoosh", 0), (f"{p.name}_flash", 0), (f"{p.name}_arrive", 0.05)]
        ents.append(props.trigger((x - inner - 6, y - inner - 6, z + 9), (x + inner + 6, y + inner + 6, z + 88),
                                  f"{p.name}_depart", once=False, master=master, wait=1))
        ents += logic.sequence(f"{p.name}_depart", steps, (x, y, z + 40))
        return ents

    # ------------------------------------------------------------------ the map of it
    def diagram(self, size=(256, 192), title=None):
        """A picture of the network: its sites, the routes between them (and pads into
        other maps), and offline slots (dashed). Put it on a wall: props.sign(...,
        image=net.diagram())."""
        sites, edges = [], []
        for p in self.pads:
            if p.site not in sites:
                sites.append(p.site)
        for p in self.pads:
            if p.to and (p.to.site, p.site, True) not in edges and (p.site, p.to.site, True) not in edges:
                edges.append((p.site, p.to.site, True))
            if p.link or p.offline:
                label = p.label or p.name
                if label not in sites:
                    sites.append(label)
                edge = (p.site, label, not p.offline)
                if p.link and p.link.one_way_from:          # an arrow the way it goes
                    edge += (label if p.link.departs(getattr(self, "map_name", None)) else p.site,)
                edges.append(edge)
        return network_diagram(sites, edges, size, title or f"{self.name.upper()} NETWORK", self.color)
