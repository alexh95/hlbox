"""Teleporters: pads that send the player to other pads, organised as networks.

    net = teleport.Network("transit", online=False)       # dark until net.start is fired
    chamber = net.pad("chamber", (1704, 592, 0), "south", site="TEST CHAMBER")
    hub = net.pad("hub1", (1024, -200, 0), "south", site="HUB")
    net.route(chamber, hub)              # both ways: each pad sends to the other's landing
    net.pad("hub4", (784, -400, 0), "east", site="HUB", label="SITE 2", offline=True)
    m.add(net.entities())
    board = net.diagram()                # a picture of the network, for a wall

A pad is a raised disc with a sign on a post behind it saying where it goes. Stepping
onto its middle (a trigger_teleport) puts the player on the landing spot in front of
the destination pad, facing away from it, with a flash and a whoosh. Landing on the
pad itself would send them straight back, hence the spot in front.

Power: a network that starts offline is a logic.Flag (`net.flag`); its pads are dark
(the disc's '+A' frame, sprite and light off) and do nothing until `net.start` fires,
which lights them all and turns the flag on. Pads work while the flag is on
(trigger_teleport masters), so anything that can clear the flag cuts the power.

Offline pads have no route: dark for good, with a sign naming the destination to
come. They are the slots new places plug into: give the pad a route (or, for another
map, a campaign Link) and it lights up with the rest.

verify: the walker takes active teleporters as moves; every landing must stand
clear, off every pad and level change; every trip needs a way back (or at least must
not cut the player off from anything). playtest --teleports tries them in the game.
"""
from __future__ import annotations

import math

from . import logic, props
from .art import network_diagram, transit_pad
from .geometry import box, cylinder
from .mapfile import Entity, prepare_texture

PAD_TEX = {"on": "+0TRANSITPAD", "off": "+ATRANSITPAD", "offline": "TRANSITPADOFF"}


class Pad:
    def __init__(self, net, name, pos, facing, site, label, offline, radius, arrive):
        self.net, self.name, self.pos, self.facing = net, name, tuple(pos), facing
        self.site, self.label, self.offline = site, label, offline
        self.radius, self.arrive = radius, arrive
        self.to = None                     # the pad it sends the player to

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
        self.master = self.flag.is_on if self.flag else None

    def pad(self, name, pos, facing, site, label=None, offline=False, radius=40, arrive=88):
        """A pad on the floor at `pos` (its centre), its landing spot `arrive` units
        toward `facing`. site: where it is (for the diagram); label: its sign (default:
        the site of the pad it sends to)."""
        p = Pad(self, name, pos, facing, site, label, offline, radius, arrive)
        self.pads.append(p)
        return p

    def route(self, a, b, two_way=True):
        """Pad a sends the player to pad b's landing (and b to a's, if two_way)."""
        for src, dst in ((a, b), (b, a)) if two_way else ((a, b),):
            if src.offline:
                raise ValueError(f"pad {src.name} is offline: it can't send anyone anywhere")
            if src.to is not None:
                raise ValueError(f"pad {src.name} already sends to {src.to.name}")
            src.to = dst

    # ------------------------------------------------------------------ building
    def entities(self):
        for p in self.pads:
            if p.to is None and not p.offline:
                raise ValueError(f"pad {p.name} goes nowhere: give it a route or make it offline")
        tex = {PAD_TEX[k]: prepare_texture(PAD_TEX[k], transit_pad(k, self.color)) for k in PAD_TEX}
        ents, glow = [], []
        lights = f"{self.name}_lights"
        for p in self.pads:
            ents += self._pad(p, lights)
            if not p.offline:
                glow += [f"{p.name}_disc", f"{p.name}_sprite"]
        for e in ents:
            if e.brushes and any(f.texture in tex for b in e.brushes for f in b.faces):
                e.textures = tex
        if self.flag:
            o = self.pads[0].pos if self.pads else (0, 0, 0)
            o = (o[0], o[1], o[2] + 64)           # somewhere inside the level (by a pad)
            self.flag.origin = o
            steps = [(self.flag.on, 0), (lights, 0)] + [(g, 0.1 * k) for k, g in enumerate(glow)]
            ents += self.flag.entities()
            # only once: a second start would toggle the pads dark again
            ents.append(logic.gate(self.start, f"{self.name}_power", self.flag.is_off, o))
            ents += logic.sequence(f"{self.name}_power", steps, o)
        return ents

    def _pad(self, p, lights):
        x, y, z = p.pos
        R = p.radius
        fx, fy = props.DIRS[p.facing]
        ents = [props.detail(cylinder((x, y), R, z, z + 8, sides=16, tex="OUT_GALV1", comment="transit pad"))]
        disc = cylinder((x, y), R - 6, z + 8, z + 9, sides=16, tex="OUT_GALV1", comment="transit pad disc")
        state = "offline" if p.offline else ("off" if self.flag else "on")
        disc.fit("top", PAD_TEX[state])
        if p.offline:
            ents.append(props.detail(disc))
        else:
            ents.append(Entity("func_wall", brushes=[disc], targetname=f"{p.name}_disc",
                               frame=1 if self.flag else 0))
        # the sign on a post behind the pad, facing the way in
        bx, by = x - fx * (R + 10), y - fy * (R + 10)
        label = p.label or (p.to.site if p.to else "OFFLINE")
        text = f"{label}\nOFFLINE" if p.offline else label
        ents.append(props.detail(box((bx - 3, by - 3, z), (bx + 3, by + 3, z + 84), "OUT_GALV1", comment="pad post")))
        ents.append(props.sign((bx + fx * 3, by + fy * 3, z + 96), p.facing, text, 64, 24 if p.offline else 16,
                               "red" if p.offline else "steel"))
        # where arrivals land (an offline pad can still be the end of a one-way route)
        lx, ly, lz = p.landing
        ents.append(props.point("info_teleport_destination", (lx, ly, lz), facing=p.facing,
                                targetname=p.land_name))
        if p.offline:
            return ents
        # the glow over it, and its light
        on = 0 if self.flag else 1
        ents.append(props.point("env_sprite", (x, y, z + 44), targetname=f"{p.name}_sprite", model="sprites/exit1.spr",
                                rendermode=5, renderamt=170, rendercolor=self.color, scale=0.6, framerate=10,
                                spawnflags=on))
        ents.append(props.light((x, y, z + 60), color=self.color, brightness=70, targetname=lights,
                                spawnflags=0 if on else 1))
        # the teleporter proper (its middle), and where it lands
        inner = R - 14
        kv = {"master": self.master} if self.master else {}
        ents.append(Entity("trigger_teleport", brushes=[box((x - inner, y - inner, z + 9), (x + inner, y + inner, z + 88),
                                                            "AAATRIGGER", comment="teleporter")],
                           target=p.to.land_name, **kv))
        # stepping on: a whoosh here, a flash, and the arrival sound over there (fired
        # by a slightly larger volume, so it goes off just before the jump)
        tx, ty, tz = p.to.landing
        ents.append(props.trigger((x - inner - 6, y - inner - 6, z + 9), (x + inner + 6, y + inner + 6, z + 88),
                                  f"{p.name}_depart", once=False, master=self.master, wait=1))
        ents.append(props.sound_effect(f"{p.name}_whoosh", (x, y, z + 40), "debris/beamstart2.wav", radius="small"))
        ents.append(props.sound_effect(f"{p.name}_arrive", (tx, ty, tz + 40), "ambience/port_suckout1.wav",
                                       radius="small"))
        ents.append(props.point("env_fade", (x, y, z + 40), targetname=f"{p.name}_flash", duration=0.6, holdtime=0.1,
                                renderamt=255, rendercolor=(200, 230, 255), spawnflags=1 | 4))  # from, this player
        ents += logic.sequence(f"{p.name}_depart", [(f"{p.name}_whoosh", 0), (f"{p.name}_flash", 0),
                                                    (f"{p.name}_arrive", 0.05)], (x, y, z + 40))
        return ents

    # ------------------------------------------------------------------ the map of it
    def diagram(self, size=(256, 192), title=None):
        """A picture of the network: its sites, the routes between them, and offline
        slots (dashed). Put it on a wall: props.sign(..., image=net.diagram())."""
        sites, edges = [], []
        for p in self.pads:
            if p.site not in sites:
                sites.append(p.site)
        for p in self.pads:
            if p.to and (p.to.site, p.site, True) not in edges and (p.site, p.to.site, True) not in edges:
                edges.append((p.site, p.to.site, True))
            if p.offline:
                label = p.label or p.name
                if label not in sites:
                    sites.append(label)
                edges.append((p.site, label, False))
        return network_diagram(sites, edges, size, title or f"{self.name.upper()} NETWORK", self.color)
