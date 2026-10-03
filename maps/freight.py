r"""Site 4: the freight line, reached from the transit hub's SITE 4 pad once the pumps run.

The line lost power when the pumps tripped: the sector gates sealed, and only the
tram, on its reserve, still runs. The track loops: a lower loop round a block of
rock with a chord through it, a lift up to an upper loop on the next level, and a
spur off that into the yard, where the line's breaker is.

  A  DISPATCH: the pad from the hub, a shotgun, the line map; the tram waits at the
     platform, facing west. Between platforms the rail is live: stay on the tram.
  B  WEST PORTAL: west, the tram stops at the sealed west gate. In the signal box,
     throw the chord switch; back up past it, then forward: the chord.
  C  DEPOT, in the tunnel through the rock: chargers, ammo, headcrabs.
  D  out of the chord, east, round under the upper line: the tram stops on the lift
     and goes up with it.
  E  TOWER on the upper loop: the yard spur is barricaded. Climb the tower and shoot
     the barricade with the mounted gun; the yard switch is on the platform.
  F  YARD at the end of the spur (zombies): the breaker in the yard office brings the
     line power back, opening both gates. Round the upper loop the tram stops on the
     lift and goes down; on through the sector gate, home to DISPATCH.

Top view (+Y = north; the upper loop, 384 up, east of the lower one; the lift where
the lower loop's east side runs under the upper loop's west side):

         +-----NW------- gorge ---- N --------------NE-+           +--NW----- N -----NE-+
         |              (bridge)        \              |           |                    |
     west|tunnel                       chord           |east tunnel|                    |
         |gate                        (DEPOT)          | (under) LIFT                     |
   PORTAL|                                 \           |           |                    | east
         +-----SW-------------- S --------chord switch-+--SE       +--SW---- S --TOWER---+--- spur -- YARD
                           DISPATCH             sector gate             (upper)    yard switch

verify drives the tram (hlmap/track.py): from each stop to every stop it can reach as
the track is switched and gated, through the lift; the live rail means it's the only
way between platforms.
"""
from hlmap import Level, Map, Material, box, logic, props, scene, teleport, track
from hlmap.mapfile import Entity
from maps.campaign import FREIGHT_PAD

CUT = Material(floor="OUT_GRAVEL", wall="-0OUT_RK3", ceiling="sky")          # a cutting, open to the sky
TUNNEL = Material(floor="OUT_GRAVEL", wall="TNNL_W12A", ceiling="TNNL_C1")
GORGE = Material(floor="-0OUT_RK3", wall="-0OUT_RK3", ceiling="sky")
SHAFT = Material(floor="-0CRETE2_FLR5", wall="C2A2A_LIFT2", ceiling="sky")
STATION = Material(floor="-0TNNL_CRT1", wall="C1A4TNNL1", ceiling="TNNL_C1")
OPEN_STATION = STATION.with_(ceiling="sky")
OFFICE = Material(floor="C1A0_LABFLRD", wall="-0C2A4_W1", ceiling="LAB1_W8CEIL1A", floor_align="center",
                  ceiling_align="center")
EDGE = {"top": "-0TNNL_FLR7", "default": "TNNL_CRT1"}     # platform edges: hazard stripes
LAMP = "+0~TNNL_LGT1"
LEVER = dict(texture="HANDLESIDE", size=(16, 24))
OFFICE_LAMP = "+0~LIGHT1"
WIDTH = 192            # the track's channel: the tram is 112 wide
UP = 384               # the upper level's track bed
INTERCOM = dict(voice_name="david", radius="medium", color=(255, 210, 140))

ARRIVAL = [
    ("Freight dispatch. The line lost its power when the pumps tripped, and the sector gates sealed.", None),
    ("The tram still runs on its reserve. Take it west to the signal box and switch it through the depot.", None),
    ("The line breaker is in the yard office, up the lift. And stay on the tram between platforms: the rail is live.",
     None),
]
POWER = [
    ("Line power restored. Sector gates open.", None),
    ("Bring the tram home to dispatch. The loop's clear all the way round.", None),
]


def build():
    m = Map("freight", skyname="desert")
    lvl = Level(wall=16)
    W = WIDTH // 2
    # ---- the lower level (bed at 0)
    s_cut = lvl.room("south cutting", (-1088, -768 - W, 0), (1088, -768 + W, 320), CUT, group="s", checkpoints=[])
    dispatch = lvl.room("dispatch platform", (448, -1056, 48), (896, -864, 208), STATION, group="s")
    office = lvl.room("dispatch office", (448, -1312, 48), (896, -1072, 208), OFFICE)
    w_south = lvl.room("west cutting", (-1280 - W, -576, 0), (-1280 + W, 32, 320), CUT, group="w", checkpoints=[])
    portal = lvl.room("west portal platform", (-1632, -320, 48), (-1376, -32, 208), STATION, group="w")
    signal = lvl.room("signal box", (-1888, -288, 48), (-1648, -64, 192), OFFICE)
    w_north = lvl.room("west tunnel", (-1280 - W, 48, 0), (-1280 + W, 576, 224), TUNNEL, checkpoints=[])
    n_west = lvl.room("north cutting west", (-1088, 768 - W, 0), (-704, 768 + W, 320), CUT, group="n", checkpoints=[])
    gorge = lvl.room("gorge", (-704, 256, -512), (-320, 1280, 448), GORGE, group="n", checkpoints=[])
    n_east = lvl.room("north cutting", (-320, 768 - W, 0), (1088, 768 + W, 320), CUT, group="n", checkpoints=[])
    e_tunnel = lvl.room("east tunnel", (1280 - W, -576, 0), (1280 + W, 576, 224), TUNNEL, group="e", checkpoints=[])
    shaft = lvl.room("lift shaft", (1280 - W, -160, -16), (1280 + W, 160, UP + 320), SHAFT, group="e",
                     checkpoints=[])
    chord = lvl.room("chord tunnel", (-W, -448, 0), (W, 448, 224), TUNNEL, group="c", checkpoints=[])
    depot = lvl.room("depot platform", (W, -192, 48), (416, 192, 224), STATION, group="c")
    # ---- the upper level (bed at UP)
    u_west = lvl.room("upper west cutting", (1280 - W, -416, UP), (1280 + W, 416, UP + 320), CUT, group="e",
                      checkpoints=[])
    u_south = lvl.room("upper south cutting", (1472, -640 - W, UP), (2624, -640 + W, UP + 320), CUT, group="us",
                       checkpoints=[])
    tower = lvl.room("tower platform", (1856, -1056, UP + 48), (2240, -640 - W, UP + 576), OPEN_STATION, group="us")
    junction = lvl.room("yard junction", (2448, -640 - W, UP), (2912, -288, UP + 320), CUT, group="us", checkpoints=[])
    u_east = lvl.room("upper east cutting", (2816 - W, -288, UP), (2816 + W, 576, UP + 320), CUT, group="us",
                      checkpoints=[])
    u_north = lvl.room("upper north cutting", (1472, 640 - W, UP), (2624, 640 + W, UP + 320), CUT, group="un",
                       checkpoints=[])
    spur = lvl.room("yard spur", (2928, -640 - W, UP), (3456, -640 + W, UP + 320), CUT, group="yard", checkpoints=[])
    yard = lvl.room("yard platform", (3072, -1056, UP + 48), (3456, -640 - W, UP + 256), OPEN_STATION, group="yard")
    yard_office = lvl.room("yard office", (3136, -1312, UP + 48), (3456, -1072, UP + 208), OFFICE)
    # ---- openings and the curves (45-degree corners)
    office_door = lvl.doorway(dispatch, office, width=64, height=96, center=640)
    lvl.doorway(portal, signal, width=64, height=96, center=-128)
    lvl.doorway(portal, signal, width=96, height=48, center=-240, sill=40)            # a window onto the platform
    west_gate = lvl.doorway(w_south, w_north, width=160, height=200, center=-1280)
    lvl.doorway(junction, spur, width=160, height=256, center=-640)
    lvl.doorway(yard, yard_office, width=64, height=96, center=3296)
    curves = []

    def curve(name, path, width, height, material, checkpoints):
        return lvl.corridor(name, path, width=width, height=height, material=material, checkpoints=checkpoints)
    curves.append(curve("south west curve", [(-960, -768), (-1024, -768), (-1280, -512), (-1280, -448)], width=WIDTH,
                 height=320, material=CUT, checkpoints=False))
    curves.append(curve("north west curve", [(-1280, 448), (-1280, 512), (-1024, 768), (-960, 768)], width=WIDTH,
                 height=224, material=TUNNEL, checkpoints=False))
    curves.append(curve("north east curve", [(960, 768), (1024, 768), (1280, 512), (1280, 432)], width=WIDTH,
                 height=224, material=TUNNEL, checkpoints=False))
    curves.append(curve("south east curve", [(1280, -432), (1280, -512), (1024, -768), (960, -768)], width=WIDTH,
                 height=224, material=TUNNEL, checkpoints=False))
    curves.append(curve("chord south", [(320, -768), (256, -768), (0, -512), (0, -384)], width=WIDTH, height=224,
                 material=TUNNEL, checkpoints=False))
    curves.append(curve("chord north", [(0, 384), (0, 512), (256, 768), (320, 768)], width=WIDTH, height=224,
                 material=TUNNEL, checkpoints=False))
    curves.append(curve("upper south west curve", [(1280, -320), (1280, -384), (1536, -640), (1600, -640)], width=WIDTH,
                 height=320, material=CUT, checkpoints=False))
    curves.append(curve("upper north east curve", [(2816, 320), (2816, 384), (2560, 640), (2496, 640)], width=WIDTH,
                 height=320, material=CUT, checkpoints=False))
    curves.append(curve("upper north west curve", [(1600, 640), (1536, 640), (1280, 384), (1280, 320)], width=WIDTH,
                 height=320, material=CUT, checkpoints=False))
    lvl.build(m)

    # ---- the track
    t = track.Track("freight")
    low = t.line("low", [(704, -768), (256, -768), (-1024, -768), (-1280, -512), (-1280, -160), (-1280, 40),
                         (-1280, 512), (-1024, 768), (256, 768), (1024, 768), (1280, 512), (1280, 384), (1280, 0),
                         (1280, -192), (1280, -400), (1280, -512), (1024, -768)], z=0, closed=True)
    up = t.line("up", [(1280, 0), (1280, -384), (1536, -640), (2048, -640), (2560, -640), (2816, -384), (2816, 384),
                       (2560, 640), (1536, 640), (1280, 384), (1280, 256)], z=UP, closed=True)
    ch = t.branch("chord", low.at((256, -768)), [(0, -512), (0, 0), (0, 512)], to=low.at((256, 768)))
    yd = t.branch("yard", up.at((2560, -640)), [(2816, -640), (3328, -640)])
    t.rename(low.at((256, -768)), "chord_switch")
    t.rename(up.at((2560, -640)), "yard_switch")
    t.gate(low.at((-1280, 40)), "west_gate")
    t.gate(low.at((1280, -400)), "sector_gate")
    t.gate(yd.at((2816, -640)), "yard_barricade")
    t.stop(low.at((704, -768)), "DISPATCH", board=(704, -846, 48))
    t.stop(low.at((-1280, -160)), "WEST PORTAL", board=(-1358, -160, 48))
    t.stop(ch.at((0, 0)), "DEPOT", board=(78, 0, 48))
    t.stop(up.at((2048, -640)), "TOWER", board=(2048, -718, UP + 48))
    t.stop(yd.at((3328, -640)), "YARD", board=(3328, -718, UP + 48))
    t.lift(low.at((1280, 0)), up.at((1280, 0)), "lift")
    t.tram(low.at((704, -768)))
    m.add(*t.entities())
    # the live rail over every channel the track runs in (and the bridge's deck), the
    # gorge's floor far down
    channels = [s_cut, w_south, w_north, n_west, n_east, e_tunnel, shaft, chord, u_west, u_south, junction, u_east,
                u_north, spur]
    beds = lvl.floor_polygons(channels + curves) + [([(-704, 680), (-320, 680), (-320, 856), (-704, 856)], 0)]
    m.add(track.live_rail(beds, holes=t.lift_holes()),        # (not over the lift's opening: you ride through)
          track.live_rail([([(-704, 256), (-320, 256), (-320, 1280), (-704, 1280)], -512)], top=96))
    # platform edges, out to the tram (8 from its side)
    for lo, hi in (((448, -864, 0), (896, -828, 48)), ((-1376, -320, 0), (-1340, -32, 48)),
                   ((60, -192, 0), (96, 192, 48)), ((1856, -736, UP), (2240, -700, UP + 48)),
                   ((3072, -736, UP), (3456, -700, UP + 48))):
        m.add(props.detail(box(lo, hi, EDGE, comment="platform edge")))

    o = (640, -1200, 180)
    power = logic.Flag("freight_power", False, o)            # the line's power is back (for what comes next)
    armed = logic.Flag("freight_armed", False, o)            # took the shotgun: the platform door opens
    m.add(power.entities(), armed.entities())
    net = teleport.Network("transit")
    net.pad("freight_pad", (832, -1192, 48), "west", site="FREIGHT DISPATCH", label="TRANSIT HUB", link=FREIGHT_PAD)
    m.add(net.entities(m))

    sun_and_lamps(m, t)
    dispatch_area(m, dispatch, office, office_door, t, armed)
    west_portal(m, portal, signal, west_gate, t)
    depot_area(m, depot)
    gorge_bridge(m, gorge)
    lift_shaft(m)
    sector_gate(m)
    tower_area(m, tower)
    yard_area(m, yard, yard_office, power)

    m.add(props.player_start((728, -1192, 48), facing="west"))     # where the hub's pad lands you
    m.auto_nodes = True
    m.checkpoints = [("the gun deck", (2176, -800, UP + 48 + 192)), ("the yard office", (3296, -1200, UP + 48)),
                     ("the signal box", (-1760, -176, 48))]
    m.cameras = {
        "dispatch": (520, -1000, 150, 8, 20),
        "tram": (900, -1000, 140, 14, 150),
        "south_cutting": (-200, -768, 110, 2, 180),
        "west_portal": (-1500, -100, 140, 10, 300),
        "west_gate_open": (-1280, -400, 110, 0, 90, ["west_gate"]),
        "chord": (0, -300, 120, 4, 90),
        "depot": (360, 150, 140, 12, 220),
        "gorge": (-280, 768, 110, 18, 180),
        "lift_bottom": (1280, -360, 110, 4, 90),
        "lift_top": (1280, -360, UP + 160, 12, 90, ["lift"]),
        "tower": (1880, -1000, UP + 140, 10, 30),
        "gun": (2120, -880, UP + 260, 8, 0),
        "barricade": (2400, -640, UP + 120, 4, 0),
        "yard": (3100, -1000, UP + 140, 10, 40),
        "yard_office": (3180, -1280, UP + 130, 10, 45),
    }
    return m


def sun_and_lamps(m, t):
    """The desert sun over the cuttings; lamps along the tunnels, every 256 on
    alternate walls."""
    m.add(props.point("light_environment", (704, -768, 300), pitch=-62, angles="0 125 0",
                      kv={"_light": "255 232 196 300", "_diffuse_light": "150 170 205 110"}))
    m.texlight(LAMP, (255, 214, 160), 900)
    runs = [((1280, -544), (1280, 544), None), ((-1280, 80), (-1280, 544), None), ((0, -416), (0, 416), -1)]
    for (x0, y0), (x1, y1), only in runs:
        for k, y in enumerate(range(int(y0), int(y1) + 1, 256)):
            side = only or (1 if k % 2 else -1)              # (the chord: the depot is on its east side)
            wx = x0 + side * WIDTH / 2
            facing = "west" if side > 0 else "east"
            # (up over the tram's canopy: it passes close to the walls on the curves)
            m.add(props.wall_art((wx, y, 196), facing, LAMP, 48, 24, depth=2, frame="OUT_GALV1"),
                  props.light((wx - side * 24, y, 180), color=(255, 214, 160), brightness=120))
    for x, y in ((1152, 640), (1152, -640), (128, -640), (128, 640), (-1152, 640)):     # the tunnel curves
        m.add(props.light((x, y, 160), color=(255, 214, 160), brightness=130))


def platform_lights(m, room, every=128):
    (x0, y0, z0), (x1, y1, z1) = room.mins, room.maxs
    m.texlight("+0~LIGHT3A", (230, 240, 255), 1400)
    if (x1 - x0) >= (y1 - y0):
        for x in range(int(x0) + every // 2, int(x1), every):
            m.add(props.ceiling_light(x, (y0 + y1) / 2, z1, width=32, depth=32, texture="+0~LIGHT3A"))
    else:
        for y in range(int(y0) + every // 2, int(y1), every):
            m.add(props.ceiling_light((x0 + x1) / 2, y, z1, width=32, depth=32, texture="+0~LIGHT3A"))


def dispatch_area(m, plat, office, door, t, armed):
    """The dispatch office (the pad, the shotgun, the line map, the intercom; the door
    to the platform opens once the shotgun's taken) and its covered platform, where
    the tram waits."""
    (x0, y0, z0), (x1, y1, z1) = office.mins, office.maxs
    m.texlight(OFFICE_LAMP, (200, 230, 255), 2000)
    for x in (544, 800):
        m.add(props.ceiling_light(x, -1192, z1, width=64, depth=32, texture=OFFICE_LAMP))
    m.add(props.light((640, -1192, z1 - 30), color=(210, 230, 255), brightness=120))
    m.add(props.table(x0 + 40, -1192, z0, width=48, depth=160, height=36, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"),
          props.pickup("weapon_shotgun", (x0 + 54, -1230, z0 + 40), fires=[armed.on], sound=None),
          props.point("ammo_buckshot", (x0 + 54, -1170, z0 + 40)),
          props.point("ammo_buckshot", (x0 + 54, -1140, z0 + 40)),
          props.sign((x0, -1192, z0 + 100), "east", "LINE CREW\nSIGN OUT", 64, 28, "warning"),
          props.sign((640, y0, z0 + 110), "north", image=t.diagram(size=(192, 144)), w=192, h=144),
          props.sign((640, y1, z0 + 128), "south", "FREIGHT DISPATCH", 144, 16, "steel"))
    talk = scene.Talk(m, "freight_hello", (x1 - 6, -1120, z0 + 120), **INTERCOM)
    for text, say in ARRIVAL:
        talk.line(text, say=say)
    m.add(talk.entities(), props.trigger((x0, y0, z0), (x1, y1, z0 + 128), talk.start),
          props.wall_art((x1, -1120, z0 + 120), "west", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          scene.skip_button((x1, -1260, z0 + 60), "west", [talk], name="freight_hello_skip"))
    # the platform: a roof on the cutting side, the station name, the live rail warning
    platform_lights(m, plat)
    (px0, py0, pz0), (px1, py1, pz1) = plat.mins, plat.maxs
    m.add(props.door_sliding(door, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=2, master=armed.is_on),
          props.sign((520, py0, pz0 + 100), "north", "DISPATCH", 96, 20, "steel"),
          props.sign((800, py0, pz0 + 100), "north", "DANGER\nLIVE RAIL", 64, 32, "red"),
          props.sign((560, -1072, z0 + 76), "north", "PLATFORM", 64, 16, "warning"))


def west_portal(m, plat, box_room, gate, t):
    """The platform at the sealed west gate, the signal box with the chord switch (a
    lever, and a sign saying where the switch sends the tram), the gate itself."""
    platform_lights(m, plat)
    (x0, y0, z0), (x1, y1, z1) = box_room.mins, box_room.maxs
    m.texlight(OFFICE_LAMP, (200, 230, 255), 2000)
    m.add(props.ceiling_light(-1768, -176, z1, width=64, depth=32, texture=OFFICE_LAMP),
          props.light((-1768, -176, z1 - 30), color=(210, 230, 255), brightness=90))
    m.add(props.lever((x0, -200, z0 + 40), "east", "chord_switch", wait=1, **LEVER),
          track.switch_sign((x0, -140, z0 + 72), "east", "chord_switch", ("ROUTE: WEST", "ROUTE: DEPOT")),
          props.sign((x0, -200, z0 + 96), "east", "CHORD\nSWITCH", 48, 24, "warning"),
          props.sign((x0 + 0, -250, z0 + 64), "east", image=t.diagram(size=(96, 72)), w=64, h=48),
          props.sign((-1504, -320, 48 + 100), "north", "WEST PORTAL", 96, 20, "steel"))
    m.add(props.door_sliding(gate, texture="TNNL_DR1", edge="TNNL_W4", thickness=16, wait=-1, speed=60,
                             targetname="west_gate", lip=8),
          props.sign((-1280, 32, 252), "south", "SECTOR GATE W\nLINE POWER OFF", 96, 28, "red"))


def depot_area(m, plat):
    """The depot in the chord tunnel: chargers, ammo, headcrabs and a zombie."""
    platform_lights(m, plat)
    (x0, y0, z0), (x1, y1, z1) = plat.mins, plat.maxs
    hc = box((x1 - 4, -96, z0 + 24), (x1, -64, z0 + 72), "MEDKITEDGE1").fit("west", "+0MEDKIT")
    rc = box((x1 - 4, 64, z0 + 24), (x1, 96, z0 + 72), "RECHARGEB").fit("west", "+0RECHARGE")
    m.add(Entity("func_healthcharger", brushes=[hc]), Entity("func_recharge", brushes=[rc]),
          props.point("ammo_9mmclip", (x1 - 40, -150, z0 + 8)), props.point("ammo_buckshot", (x1 - 40, 150, z0 + 8)),
          props.sign((x1, 0, z0 + 110), "west", "DEPOT", 96, 20, "steel"),
          props.point("monster_headcrab", (300, -120, z0 + 8), facing=180),
          props.point("monster_headcrab", (320, 110, z0 + 8), facing=180),
          props.point("monster_zombie", (360, 0, z0 + 8), facing=180))


def gorge_bridge(m, gorge):
    """The north cutting crosses a gorge on a girder bridge (the track bed); a toxic
    pool far down."""
    (x0, y0, z0), (x1, y1, z1) = gorge.mins, gorge.maxs
    m.add(props.detail(box((x0, 768 - 88, -24), (x1, 768 + 88, 0), {"top": "OUT_GRAVEL", "default": "GENERIC015K"},
                           comment="bridge deck")))
    for y in (768 - 80, 768 + 72):
        m.add(props.detail(box((x0, y, -96), (x1, y + 8, -24), "GENERIC015K", comment="girder")))
    for x in range(int(x0) + 96, int(x1), 192):
        m.add(props.detail(box((x - 16, 768 - 72, z0 + 64), (x + 16, 768 + 72, -96), "-0OUT_RK3", comment="pier")))
    m.add(Entity("func_water", brushes=[box((x0, y0, z0), (x1, y1, z0 + 48), "!TOXICGRN")], kv={"skin": -4}),
          props.light(((x0 + x1) / 2, 520, -440), color=(120, 255, 90), brightness=160))


def lift_shaft(m):
    """The shaft between the levels: lights down its walls, signs at both ends."""
    for z in (120, 300, UP + 140):
        for x in (1192, 1368):
            m.add(props.light((x, 0, z), color=(255, 220, 170), brightness=110))
    m.add(props.sign((1280 + WIDTH / 2, 120, 150), "west", "LIFT\nTO UPPER LINE", 64, 28, "warning"),
          props.sign((1280 - WIDTH / 2, -120, UP + 150), "east", "LIFT\nTO LOWER LINE", 64, 28, "warning"))


def sector_gate(m):
    """The blast door across the east tunnel, opened by the line power."""
    door = box((1184, -408, 0), (1376, -392, 224), "TNNL_W4", comment="sector gate")
    door.fit("north", "TNNL_DR1").fit("south", "TNNL_DR1")
    m.add(Entity("func_door", brushes=[door], targetname="sector_gate", angle=-1, speed=60, wait=-1, lip=8,
                 movesnd=1, stopsnd=1),
          props.sign((1280 + WIDTH / 2, -340, 150), "west", "SECTOR GATE E\nLINE POWER OFF", 96, 28, "red"))


def tower_area(m, plat):
    """The tower platform on the upper loop: a ladder up to the gun deck, the mounted
    gun covering the yard spur's barricade, the yard switch."""
    (x0, y0, z0), (x1, y1, z1) = plat.mins, plat.maxs
    deck = z0 + 192
    # the deck reaches out over the platform edge (above the tram's roof), so the gun
    # sits in the cutting and sees along it to the spur
    m.add(props.detail(box((2112, -1008, z0), (2240, -864, deck - 16), "TNNL_CRT1", comment="tower"),
                       box((2112, -1016, deck - 16), (2248, -704, deck), {"top": "-0TNNL_FLR7", "default": "OUT_GALV1"},
                           comment="gun deck")))
    m.add(props.railing((2112, -704), (2248, -704), deck, texture="OUT_GALV1"),
          props.railing((2248, -1016), (2248, -704), deck, texture="OUT_GALV1"),
          props.railing((2112, -1016), (2248, -1016), deck, texture="OUT_GALV1"))
    m.add(*props.ladder((2112, -940, z0), deck, "east"))
    m.add(*props.mounted_gun((2200, -730, deck + 52), "yard_gun", yaw=10, yaw_range=50, pitch_range=40))
    # the barricade across the spur: crates, until shot to pieces
    m.add(Entity("func_breakable", brushes=[box((2752, -704, UP), (2784, -576, UP + 112), "CRATE02",
                                                comment="barricade")],
                 kv={"material": 1, "health": 150, "target": "yard_barricade"}))
    m.add(props.lever((1960, y0, z0 + 40), "north", "yard_switch", wait=1, **LEVER),
          track.switch_sign((1960, y0, z0 + 76), "north", "yard_switch", ("ROUTE: LOOP", "ROUTE: YARD")),
          props.sign((1880, y0, z0 + 96), "north", "YARD\nSWITCH", 48, 24, "warning"),
          props.sign((2160, y0, z0 + 104), "north", "TOWER", 96, 20, "steel"),
          props.point("item_healthkit", (1900, -1000, z0 + 8)),
          props.point("monster_houndeye", (2000, -1010, z0 + 8), facing=90),
          props.point("monster_houndeye", (2080, -1020, z0 + 8), facing=90),
          props.light((2000, -900, z0 + 160), color=(255, 230, 200), brightness=120))


def yard_area(m, plat, office, power):
    """The yard at the end of the spur (buffers, zombies) and its office with the line
    breaker: line power on, both gates open, the dispatcher says so."""
    (x0, y0, z0), (x1, y1, z1) = plat.mins, plat.maxs
    m.add(props.detail(box((3440, -712, UP), (3456, -568, UP + 64), {"default": "FLATBED_BUMPER"}, comment="buffers")),
          props.sign((3200, y0, z0 + 104), "north", "YARD", 96, 20, "steel"),
          props.point("monster_zombie", (3200, -960, z0 + 8), facing=90),
          props.point("monster_zombie", (3400, -1000, z0 + 8), facing=90),
          props.point("ammo_buckshot", (3264, -900, z0 + 8)),
          props.light((3264, -900, z0 + 160), color=(255, 230, 200), brightness=120))
    for x in (3104, 3152, 3424):                        # (clear of the office door)
        m.add(props.crate(x, -1030, z0, size=40))
    (ox0, oy0, oz0), (ox1, oy1, oz1) = office.mins, office.maxs
    m.texlight(OFFICE_LAMP, (200, 230, 255), 2000)
    m.add(props.ceiling_light(3296, -1192, oz1, width=64, depth=32, texture=OFFICE_LAMP),
          props.light((3296, -1192, oz1 - 30), color=(210, 230, 255), brightness=100))
    talk = scene.Talk(m, "line_restored", (ox1 - 6, -1192, oz0 + 120), **INTERCOM)
    for text, say in POWER:
        talk.line(text, say=say)
    m.add(talk.entities())
    m.add(logic.sequence("line_power", [(power.on, 0), ("west_gate", 0.5), ("sector_gate", 0.5),
                                        (talk.start, 1.5)], (3296, -1150, oz0 + 100)),
          props.lever((3296, oy0, oz0 + 40), "north", "line_power", wait=-1, **LEVER),
          props.sign((3296, oy0, oz0 + 96), "north", "LINE POWER", 64, 20, "red"),
          props.wall_art((ox1, -1192, oz0 + 120), "west", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"))
