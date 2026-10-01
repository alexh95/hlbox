r"""Site 3: the pump station, reached from the transit hub with the Xen field lab's card.

The station flooded when its main pumps tripped; the pump controls are on the far
side of the hall, and the lockdown sealed the way round. So the way is through the
water:

  A  the control room: the pad from the hub, a sidearm and a crowbar (the door to the
     hall opens for an armed player), the intercom.
  B  the flooded hall: catwalks round it at the control room's level, barnacles over
     the south one; dive in (leeches).
  C  a corridor full of water, an air pocket half way, more corridor: hold your breath.
  D  the pump deck. A valve drains the settling tank (E) next to it; the gate at the
     bottom of the tank only opens once it's empty.
  E  down the ladder, through the gate.
  G  the outflow tunnel (houndeyes); a grate to smash. (Not under the tank: a
     func_water drains by moving down, so under it must be solid rock.)
  H  the cistern: its exit is 320 up the wall. A valve floods it (sealing the tunnel
     door first); swim up.
  I  the exit corridor, to J, a lift up to K, the pump control: START PUMPS restarts
     them (the hall's lights come back on, a global state for what comes next) and
     opens the door onto the hall's north catwalk, back round to A and the pad.

Top view (+Y = north; G, H, I under the rest):

        E~~D==C3        D: the deck (north half) over the pool
         |  |           E: the settling tank (water to the deck, drains)
         G  C2 (air)    G runs south from the tank's bottom gate to H
         |  |
         G  C1     J  K (pump control, up the lift)
         |  |     /
        H--I-----   (I under C1, J's lift up to K)
           B (the flooded hall, catwalks south, west and north)
           A (control room, the pad)

verify swims (hlmap.verify: water, breath, func_waters moving, lifts, the grate),
and places info_nodes for the houndeyes (m.auto_nodes).
"""
from hlmap import Level, Map, Material, box, logic, props, scene, teleport
from hlmap.mapfile import Entity
from maps.campaign import PUMPS_PAD

CONTROL = Material(floor="C1A0_LABFLRD", wall="-0C2A4_W1", ceiling="LAB1_W8CEIL1A", floor_align="center",
                   ceiling_align="center")
HALL = Material(floor="C3A1_W3C", wall="C3A1_W1", ceiling="C3A1_W2")
PIPE = Material(floor="-0C2A4_COR2", wall="-0C2A4_COR2", ceiling="-0C2A4_COR2")
DECK = Material(floor="-0C2A4_FLR6", wall="C3A2A_W1", ceiling="C3A1_W2")
TANK = Material(floor="C3A1_W3C", wall="C3A2A_TNK1", ceiling="C3A1_W2")
LIFT = Material(floor="-0C2A4_FLR6", wall="C2A2A_LIFT2", ceiling="C3A1_W2")
STRIP = "+0~C2A4_LGT1"           # a light strip, for the industrial rooms
LAB_LAMP = "+0~LIGHT1"
INTERCOM = dict(voice_name="zira", radius="medium", color=(170, 220, 255))

ARRIVAL = [
    ("Pump station three. The main pumps tripped, and the lower levels flooded.", None, None),
    ("The pump controls are on the far side of the hall, and the lockdown sealed the way round. You will have to "
     "go through the water.", None, None),
    ("Take a sidearm from the desk. The leeches came in with the flood. And watch the ceiling over the catwalk.",
     None, None),
]
FINALE = [
    ("Pumps online. Lockdown lifted.", None, None),
    ("The catwalk will take you back to the transit pad. Nice swimming.", None, None),
]


def build():
    m = Map("pumps")
    lvl = Level(wall=16)
    control = lvl.room("control room", (0, 0, 256), (512, 384, 416), CONTROL)
    hall = lvl.room("flooded hall", (0, 400, 0), (1024, 1040, 448), HALL, water=192)
    c1 = lvl.room("flooded corridor", (752, 1056, 0), (848, 1504, 128), PIPE, water=128)
    pocket = lvl.room("air pocket", (704, 1520, 0), (896, 1712, 320), PIPE, water=192)
    c3 = lvl.room("flooded corridor 2", (752, 1728, 0), (848, 2176, 128), PIPE, water=128)
    deck = lvl.room("pump deck", (512, 2192, 0), (1152, 2704, 384), DECK, water=152)   # 8 under the deck
    tank = lvl.room("settling tank", (1168, 2448, -256), (1424, 2704, 384), TANK)
    outflow_ = lvl.room("outflow tunnel", (1232, 1328, -256), (1360, 2432, -128), PIPE)
    cistern = lvl.room("cistern", (896, 784, -448), (1424, 1312, -16), TANK)
    exit_ = lvl.room("exit corridor", (672, 1200, -128), (880, 1328, -16), PIPE)
    shaft = lvl.room("lift shaft", (528, 1184, -128), (656, 1440, 416), LIFT)
    pumpctl = lvl.room("pump control", (0, 1056, 256), (512, 1312, 416), CONTROL)
    hall_door = lvl.doorway(control, hall, width=64, height=96, center=448)
    lvl.doorway(control, hall, width=256, height=80, center=208, sill=40)          # window
    lvl.doorway(hall, c1, width=64, height=96, center=800)
    lvl.doorway(c1, pocket, width=64, height=96, center=800)
    lvl.doorway(pocket, c3, width=64, height=96, center=800)
    lvl.doorway(c3, deck, width=64, height=96, center=800)
    lvl.doorway(deck, tank, width=128, height=128, center=2576, sill=160)
    gate = lvl.doorway(tank, outflow_, width=96, height=96, center=1296)
    seal = lvl.doorway(outflow_, cistern, width=96, height=96, center=1296)
    lvl.doorway(cistern, exit_, width=96, height=96, center=1256)
    lvl.doorway(exit_, shaft, width=96, height=96, center=1264)
    lvl.doorway(shaft, pumpctl, width=96, height=96, center=1248)
    north_door = lvl.doorway(hall, pumpctl, width=64, height=96, center=256)
    lvl.doorway(hall, pumpctl, width=160, height=80, center=400, sill=40)           # window
    lvl.build(m)

    o = (256, 192, 400)
    armed = logic.Flag("pumps_armed", False, o)              # took a weapon in the control room
    running = logic.Flag("pumps_running", False, o)          # the pumps are back on (for what comes next)
    drained = logic.Flag("pumps_tank_drained", False, (1296, 2576, 300))
    m.add(armed.entities(), running.entities(), drained.entities())

    net = teleport.Network("transit")
    net.pad("station_pad", (128, 128, 256), "north", site="PUMP STATION", label="TRANSIT HUB", link=PUMPS_PAD)
    m.add(net.entities(m))

    control_room(m, control, hall_door, armed)
    flooded_hall(m, hall)
    water_route(m, c1, pocket, c3)
    pump_deck(m, deck, tank, gate, drained)
    outflow(m, outflow_)
    cistern_room(m, cistern, seal)
    lift_and_control(m, exit_, shaft, pumpctl, north_door, running)

    m.add(props.player_start((128, 232, 256), facing="north"))     # where the hub's pad lands you
    m.auto_nodes = True
    m.cameras = {
        "control": (256, 40, 320, 6, 90),
        "hall": (900, 440, 330, 18, 150),
        "hall_from_window": (208, 360, 320, 14, 90),
        "pocket": (800, 1540, 260, 25, 90),
        "deck": (600, 2500, 240, 10, 30),
        "tank_full": (1180, 2580, 260, 30, 0),
        "tank_drained": (1180, 2580, 260, 40, 0, ["drain_tank"]),
        "outflow": (1296, 2400, -192, 4, 270),
        "grate": (1296, 1600, -192, 4, 270),
        "cistern": (1296, 1250, -400, -10, 250),
        "cistern_flooded": (1296, 1250, -60, 20, 250, ["flood_cistern"]),
        "lift": (600, 1420, -60, 10, 270),
        "pump_control": (420, 1100, 320, 8, 120),
        "pumps_on": (208, 360, 320, 14, 90, ["start_pumps"]),
    }
    return m


def ceiling_strips(m, room, xs, ys):
    z1 = room.maxs[2]
    for x in xs:
        for y in ys:
            m.add(props.ceiling_light(x, y, z1, width=64, depth=16, texture=STRIP))


def control_room(m, room, hall_door, armed):
    """The pad from the hub, the desk with a sidearm and a crowbar (taking one opens
    the door to the hall: touch-open while `armed` is on), the window over the hall,
    the intercom."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    m.texlight(LAB_LAMP, (200, 230, 255), 2200)
    m.texlight(STRIP, (230, 240, 255), 900)
    for x in (128, 384):
        for y in (96, 288):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    m.add(props.light((256, 192, z1 - 30), color=(210, 230, 255), brightness=140))
    # the desk along the east wall: the weapons at its front edge
    m.add(props.table(x1 - 40, 160, z0, width=48, depth=192, height=36, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"),
          props.pickup("weapon_9mmhandgun", (x1 - 54, 120, z0 + 40), fires=[armed.on], sound=None),
          props.pickup("weapon_crowbar", (x1 - 54, 200, z0 + 40), fires=[armed.on], sound=None),
          props.point("ammo_9mmclip", (x1 - 54, 90, z0 + 40)), props.point("ammo_9mmclip", (x1 - 54, 150, z0 + 40)),
          props.point("ammo_9mmclip", (x1 - 54, 230, z0 + 40)),
          props.sign((x1, 160, z0 + 100), "west", "SIDEARMS\nSIGN OUT", 64, 28, "warning"),
          props.sign((256, y0, z0 + 120), "north", "PUMP STATION 3", 144, 16, "steel"))
    # the door to the hall (for an armed player), the window
    m.add(props.door_sliding(hall_door, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=2, master=armed.is_on),
          props.sign((392, y1, z0 + 76), "south", "HALL", 40, 12, "warning"),
          props.Entity("func_wall", brushes=[box((80, y1 + 7, z0 + 40), (336, y1 + 9, z0 + 120), "GLASS_BRIGHT",
                                                 comment="window")], rendermode=2, renderamt=60))
    # the intercom: says what happened on arrival; a panel skips it
    head = (x0 + 6, 300, z0 + 120)
    talk = scene.Talk(m, "pumps_hello", head, **INTERCOM)
    for text, say, _ in ARRIVAL:
        talk.line(text, say=say)
    m.add(talk.entities(), props.trigger((x0, y0, z0), (x1, y1, z0 + 128), talk.start),
          props.wall_art((x0, 300, z0 + 120), "east", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          scene.skip_button((x0, 220, z0 + 60), "east", [talk], name="pumps_hello_skip"))


def flooded_hall(m, room):
    """Water 192 deep; catwalks at the control room's level along the south, west and
    north walls (see-through grating), barnacles over the south one, leeches below;
    red emergency light until the pumps start (then the hall lights)."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    walk = 256                                                  # the catwalks' top
    grate = {"top": "{GRATESTEP2", "default": "OUT_GALV1"}
    for lo, hi in (((x0, y0, walk - 16), (x1, y0 + 96, walk)),            # south
                   ((x0, y0 + 96, walk - 16), (x0 + 96, y1 - 96, walk)),  # west
                   ((x0, y1 - 96, walk - 16), (352, y1, walk))):          # north, to the pump control door
        cat = box(lo, hi, grate, comment="catwalk")
        m.add(props.Entity("func_wall", brushes=[cat], rendermode=4, renderamt=255))
    m.add(props.railing((x0 + 96, y0 + 96), (320, y0 + 96), walk, texture="OUT_GALV1"),
          props.railing((576, y0 + 96), (x1, y0 + 96), walk, texture="OUT_GALV1"),
          props.railing((x0 + 96, y1 - 96), (352, y1 - 96), walk, texture="OUT_GALV1"))
    for x in (160, 640, 880):                                   # over the south catwalk
        m.add(props.point("monster_barnacle", (x, y0 + 48, z1 - 1)))
    for p in ((512, 700, 96), (300, 850, 120), (850, 600, 60)):
        m.add(props.point("monster_leech", p))
    # light: red emergency lamps now, the hall lights when the pumps start
    for x in (256, 768):
        for y in (560, 880):
            m.add(props.light((x, y, z1 - 40), color=(255, 50, 30), brightness=110, targetname="hall_emergency"),
                  props.light((x, y, z1 - 40), color=(220, 235, 255), brightness=220, targetname="hall_lights",
                              spawnflags=1))
    m.add(props.light((512, 720, 120), color=(80, 140, 200), brightness=90))      # under the water
    m.add(props.sign((x1, 720, 320), "west", "DANGER\nDEEP WATER", 80, 28, "warning"))


def water_route(m, c1, pocket, c3):
    """The corridor full of water, the air pocket, more corridor. Lit under water."""
    for r in (c1, c3):
        cx = (r.mins[0] + r.maxs[0]) / 2
        for y in range(int(r.mins[1]) + 96, int(r.maxs[1]), 192):
            m.add(props.light((cx, y, 96), color=(90, 170, 220), brightness=80))
    cx = (pocket.mins[0] + pocket.maxs[0]) / 2
    cy = (pocket.mins[1] + pocket.maxs[1]) / 2
    m.add(props.light((cx, cy, 280), color=(200, 230, 255), brightness=120),
          props.point("monster_leech", (cx, cy, 100)),
          props.sign((pocket.maxs[0], cy, 240), "west", "AIR", 40, 16, "warning"))


def pump_deck(m, deck, tank, gate, drained):
    """The pool and the deck (just over the water: climb out), the valve that drains
    the settling tank, the tank: water to the deck while full, a ladder down, the
    gate at its bottom (opens only when the tank is empty)."""
    x0, y0, z0 = deck.mins
    x1, y1, z1 = deck.maxs
    top = 160
    m.add(props.detail(box((x0, 2448, z0), (x1, y1, top), {"top": "-0C2A4_FLR6", "default": "C3A2A_W1"},
                           comment="pump deck")))
    ceiling_strips(m, deck, (640, 832, 1024), (2320, 2576))
    for x in (640, 1024):
        for y in (2320, 2576):
            m.add(props.light((x, y, z1 - 40), color=(220, 230, 255), brightness=200))
    m.add(props.light((832, 2320, 100), color=(90, 170, 220), brightness=90))          # in the pool
    for x, y in ((640, 2640), (1024, 2640)):                    # the pumps (still)
        m.add(props.detail(box((x - 48, y - 48, top), (x + 48, y + 48, top + 128),
                               {"default": "C3A2A_TNK1", "top": "C3A1_GEAR1"}, comment="pump")))
    # the drain valve on a standpipe; a sign; health and ammo
    m.add(props.detail(box((816, 2544, top), (848, 2576, top + 48), "OUT_GALV1", comment="standpipe")),
          props.valve((832, 2544, top + 30), "south", "drain_tank"),
          props.sign((832, 2544, top + 64), "south", "DRAIN\nSETTLING TANK", 56, 24, "warning"),
          props.point("item_healthkit", (600, 2480, top + 8)), props.point("ammo_9mmclip", (660, 2480, top + 8)))
    # the tank: water to the deck, draining down out of sight when the valve turns
    tx0, ty0, tz0 = tank.mins
    tx1, ty1, tz1 = tank.maxs
    o = ((tx0 + tx1) / 2, (ty0 + ty1) / 2, top + 100)
    # (it drains 16 past the floor: a surface left level with the floor would show)
    m.add(props.water_mover((tx0, ty0, tz0), (tx1, ty1, top), "tank_water", direction="down",
                            travel=top - tz0 + 16),
          props.sound_effect("drain_snd", o, "ambience/waterfall2.wav", stoppable=True),
          props.Entity("trigger_relay", targetname="drain_snd_off", target="drain_snd", triggerstate=0, origin=o),
          props.hud_message("drain_msg", o, "SETTLING TANK: DRAINING", color=(120, 200, 255), y=0.3, channel=3),
          props.hud_message("drained_msg", o, "SETTLING TANK EMPTY: HATCH UNLOCKED", color=(90, 255, 120), y=0.3,
                            channel=3),
          logic.sequence("drain_tank", [("tank_water", 0), ("drain_snd", 0), ("drain_msg", 0), (drained.on, 10),
                                        ("drain_snd_off", 10), ("drained_msg", 10)], o))
    m.add(props.ladder((tx0, (ty0 + ty1) / 2 + 80, tz0), top, "east"),
          props.light(((tx0 + tx1) / 2, (ty0 + ty1) / 2, tz0 + 60), color=(200, 220, 255), brightness=130),
          props.light(((tx0 + tx1) / 2, (ty0 + ty1) / 2, 300), color=(200, 220, 255), brightness=120),
          props.sign((1296, ty0, tz0 + 128), "north", "GATE OPENS\nWHEN EMPTY", 72, 24, "warning"))
    # the gate to the outflow: opens for a player once the tank is empty
    m.add(props.door_sliding(gate, texture="LAB1_DOOR2A", edge="LAB1_DOOR2B", wait=-1, master=drained.is_on))


def outflow(m, room):
    """From the tank's bottom gate south to the cistern: the dry outflow tunnel,
    houndeyes, a grate to smash."""
    (x0, y0, z0), (x1, y1, z1) = room.mins, room.maxs
    cx = (x0 + x1) / 2
    for y in range(int(y0) + 96, int(y1), 256):
        m.add(props.light((cx, y, z1 - 20), color=(255, 210, 150), brightness=110))
    m.add(props.breakable((x0, 1440, z0), (x1, 1448, z1), texture="{GRATE2", material=2, health=30),
          props.point("monster_houndeye", (cx, 1900, z0), facing=90),
          props.point("monster_houndeye", (cx, 2150, z0), facing=90),
          props.point("item_healthkit", (1264, 1500, z0 + 8)), props.point("ammo_9mmclip", (1328, 1500, z0 + 8)),
          props.sign((x1, 1600, z0 + 96), "west", "OUTFLOW\nTO CISTERN", 64, 24, "warning"))


def cistern_room(m, room, seal):
    """The cistern: its exit is 320 up the west wall. The valve seals the tunnel door
    and floods it (a func_water rising from under the floor) to the exit's sill."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    o = ((x0 + x1) / 2, (y0 + y1) / 2, -200)
    # full to the exit's sill; it waits lowered (16 under the floor, out of sight) and rises
    m.add(props.water_mover((x0, y0, z0), (x1, y1, -128), "cistern_water", direction="up", speed=30, travel=336),
          props.door_sliding(seal, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=-1, targetname="cistern_seal",
                             spawnflags=1 | 32),                        # starts open; the flood closes it
          props.detail(box((1160, 1040, z0), (1192, 1072, z0 + 48), "OUT_GALV1", comment="standpipe")),
          props.valve((1176, 1072, z0 + 30), "north", "flood_cistern"),
          props.sign((1176, 1072, z0 + 64), "north", "FILL\nCISTERN", 48, 24, "warning"),
          props.sign((x0, 1176, -80), "east", "EXIT", 40, 14, "warning"),          # beside the exit, 320 up
          props.sound_effect("flood_snd", o, "ambience/waterfall1.wav", stoppable=True),
          props.Entity("trigger_relay", targetname="flood_snd_off", target="flood_snd", triggerstate=0, origin=o),
          props.hud_message("flood_msg", o, "CISTERN FILLING", color=(120, 200, 255), y=0.3, channel=3),
          logic.sequence("flood_cistern", [("cistern_seal", 0), ("flood_msg", 0), ("cistern_water", 1.0),
                                           ("flood_snd", 1.0), ("flood_snd_off", 12)], o))
    for x in (1024, 1296):
        for y in (912, 1184):
            m.add(props.light((x, y, z1 - 40), color=(190, 215, 255), brightness=160))
    m.add(props.light(((x0 + x1) / 2, (y0 + y1) / 2, z0 + 60), color=(190, 215, 255), brightness=120))


def lift_and_control(m, exit_, shaft, pumpctl, north_door, running):
    """The exit corridor, the lift up to the pump control, START PUMPS: the pumps run,
    the hall's lights come on, the door onto its north catwalk opens."""
    for x in (720, 840):
        m.add(props.light((x, 1264, -40), color=(255, 210, 150), brightness=100))
    m.add(props.lift((592, 1264), (96, 96), 256, 384),
          props.light((592, 1400, 380), color=(255, 220, 160), brightness=150),
          props.light((592, 1400, -60), color=(255, 220, 160), brightness=120),
          props.sign((656, 1360, -40), "west", "LIFT", 40, 14, "warning"))
    x0, y0, z0 = pumpctl.mins
    x1, y1, z1 = pumpctl.maxs
    o = (256, 1184, 380)
    for x in (128, 384):
        for y in (1120, 1248):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    console = props.front_box(256, y1 - 40, z0, 160, 32, 40, "south", "LAB1_PANELF", sides="FIFTIES_DSK5B",
                              top="FIFTIES_DSK5B")
    m.add(props.detail(console),
          props.lever((256, y1 - 40, z0 + 40), "south", "start_pumps", master=running.is_off,
                      texture="+0~C2A4_SCH1", size=(16, 24)),
          props.sign((256, y1, z0 + 110), "south", "MAIN PUMPS", 96, 16, "red"),
          props.door_sliding(north_door, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=-1, targetname="pumps_out"),
          props.Entity("func_wall", brushes=[box((320, y0 - 9, z0 + 40), (480, y0 - 7, z0 + 120), "GLASS_BRIGHT",
                                                 comment="window")], rendermode=2, renderamt=60),
          props.point("item_battery", (60, 1100, z0 + 8)),
          props.sound_effect("pumps_snd", o, "ambience/pumper.wav", stoppable=True),
          props.Entity("trigger_relay", targetname="pumps_snd_off", target="pumps_snd", triggerstate=0, origin=o),
          props.hud_message("pumps_msg", o, "MAIN PUMPS: RUNNING", color=(90, 255, 120), y=0.3, channel=3))
    talk = scene.Talk(m, "pumps_done", (x1 - 6, 1184, z0 + 120), **INTERCOM)
    for text, say, _ in FINALE:
        talk.line(text, say=say)
    m.add(talk.entities(),
          props.wall_art((x1, 1184, z0 + 120), "west", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          logic.sequence("start_pumps", [(running.on, 0), ("pumps_msg", 0), ("pumps_snd", 0), ("pumps_snd_off", 8),
                                         ("hall_lights", 0.5), ("hall_emergency", 0.5), ("pumps_out", 1.0),
                                         (talk.start, 1.5)], o))
