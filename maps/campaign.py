"""The campaign: its maps in the order a player meets them, and where they join.

    office  --(road tunnel)-->  labs  --(transit pad)-->  xen
       ^                          |  ^ |                   |
       +--(pad in the basement)---+  | +--(SITE 3 pad,     +--(one way: the field lab's pad,
                                     |    the Xen card)-->  pumps      after the course)
                                     +---------------------------+
                                  labs --(SITE 4 pad, the pumps running)--> freight

Each map is its own script. The stretch of road tunnel where the level changes is
built here, once, so both maps have exactly the same copy of it (verify compares
them surface by surface). Top view of the zone, relative to its origin (the landmark):

                      +----------------------------+
                      |  C2          T3 stub  ->   |  y 256..512   labs goes on east
                +-----+     .------------------------+
                |  T2 |     |   office's trigger at y 128..192
                |     |     |
                |     |     |   labs' trigger at y -192..-128
    office  +---+     +-----+
    comes   |  T1 stub   C1 |                          y -512..-256
    in from +---------------+
    the west   x -512 .. 128     (T2: x -128..128)

The triggers sit in T2, before each corner, so neither map's dead end (office has no
T3 beyond the stub, labs no T1) is in view when the level changes, and each lands the
player well away from the other map's trigger.
"""
from hlmap import Material, box, props
from hlmap.campaign import Link, PadLink
from hlmap.mapfile import Entity, prepare_texture

MAPS = ["office", "labs", "xen", "pumps", "freight"]

TUNNEL_HEIGHT = 192
TUNNEL = Material(floor="OUT_PAVE1", wall="TNNL_W12", ceiling="TNNL_C1")
LAMP_TEX = "+0~TNNL_LGT4"          # sodium lamp fixture
SODIUM = (255, 176, 96)


def tunnel_zone(m, lvl, o):
    """The shared stretch of road tunnel (see the module docstring). Returns its rooms
    {"west": T1 stub + C1, "mid": T2, "east": C2 + T3 stub}, to join onto."""
    x, y, z = o
    H = TUNNEL_HEIGHT

    def room(name, lo, hi):
        return lvl.room(name, (x + lo[0], y + lo[1], z), (x + hi[0], y + hi[1], z + H), TUNNEL, group="tunnel")

    rooms = {"west": room("tunnel west", (-512, -512), (128, -256)),
             "mid": room("tunnel", (-128, -256), (128, 256)),
             "east": room("tunnel east", (-128, 256), (512, 512))}
    at = lambda dx, dy, dz=0: (x + dx, y + dy, z + dz)
    # sodium lamps on the walls, away from the zone's two ends
    m.texlight(LAMP_TEX, SODIUM, 700)
    for dx, dy, facing in ((-256, -512, "north"), (0, -512, "north"), (128, -384, "west"),         # T1 stub, C1
                           (-128, -32, "east"), (-128, 192, "east"), (128, 16, "west"),            # T2
                           (-128, 384, "east"), (0, 512, "south"), (256, 512, "south"), (320, 256, "north")):
        fx, fy = props.DIRS[facing]
        m.add(props.wall_art(at(dx, dy, 150), facing, LAMP_TEX, 48, 32, depth=6, frame="OUT_GALV1"),
              props.light(at(dx + fx * 24, dy + fy * 24, 140), color=SODIUM, brightness=150))
    # centre-line dashes along the road, round both corners
    dashes = []
    for s in range(-512 + 24, 0, 96):
        dashes.append(box(at(s, -386), at(s + 48, -382, 1), "PAINTY", comment="road dash"))
    for s in range(-384 + 48, 384, 96):
        dashes.append(box(at(-2, s), at(2, s + 48, 1), "PAINTY", comment="road dash"))
    for s in range(48, 512, 96):
        dashes.append(box(at(s, 382), at(s + 48, 386, 1), "PAINTY", comment="road dash"))
    from hlmap.art import paint
    paint_ent = Entity("func_illusionary", brushes=dashes)
    paint_ent.textures = {"PAINTY": prepare_texture("PAINTY", paint((232, 196, 40), gloss=False, noise=10))}
    m.add(paint_ent)
    # tunnel section numbers painted on the walls, and a direction sign
    m.add(props.wall_art(at(-128, -160, 64), "east", "TNNL_W12C16", 128, 128, depth=1, frame="TNNL_W12"),
          props.wall_art(at(128, 160, 64), "west", "TNNL_W12C17", 128, 128, depth=1, frame="TNNL_W12"),
          props.sign(at(128, -128, 120), "west", "MATERIALS LAB ↑\nSURFACE ↓", 96, 40, "warning"))
    # a cable tray along the ceiling
    m.add(props.pipe(at(96, -384, H - 12), at(96, 384, H - 12), size=10, texture="GENERIC030"))
    return rooms


# office's origin is on its road (x 1232.. is the tunnel from the portal); labs' is
# 3072 west and 1536 south of that, in its own frame (multiples of 512: see Link)
LINK = Link("tunnel", ("office", "labs"),
            zone=((-512, -512, 0), (512, 512, TUNNEL_HEIGHT)),
            origins={"office": (2128, 1632, 0), "labs": (-944, 96, 0)},
            triggers={"office": ((-128, 128, 0), (128, 192, TUNNEL_HEIGHT)),
                      "labs": ((-128, -192, 0), (128, -128, TUNNEL_HEIGHT))},
            build=tunnel_zone,
            carries=["sector_pass",       # the pass from records opens the lab door
                     "brief_pending"])    # the guard and the lab's intercom know if you skipped the briefing


# teleporter pads that change level (hlmap.teleport: net.pad(..., link=...)); in each
# pair the two pads face opposite ways
OFFICE_PAD = PadLink("pad_office", ("office", "labs"),
                     carries=["transit_online"])     # the network, switched on in labs, powers the basement pad
XEN_GATE = PadLink("pad_xen", ("labs", "xen"),       # the hub <-> the Xen field station
                   carries=["gear_confiscated"])     # the field lab took the crowbar: the station gives one back
XEN_RETURN = PadLink("pad_xen_lab", ("labs", "xen"),  # the Xen field lab (the course's end) -> the hub
                     one_way_from="xen",             # the hub's end only receives: no way back to the lab
                     carries=["xen_clearance"])      # the field lab's keycard: it powers the hub's SITE 3 pad
PUMPS_PAD = PadLink("pad_pumps", ("labs", "pumps"),  # the hub's SITE 3 <-> the pump station (needs the Xen card)
                    carries=["pumps_running"])        # the station's pumps, restarted
FREIGHT_PAD = PadLink("pad_freight", ("labs", "freight"),   # the hub's SITE 4 <-> the freight line (needs the pumps)
                      carries=["freight_power"])      # the line's power, back on
