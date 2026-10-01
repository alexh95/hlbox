r"""Xen: the field station, the long jump course across the islands, the field lab.

The labs' transit hub has a pad to the Xen field station (campaign.XEN_GATE). The
station hands out the field kit: the HEV suit, the long jump module and a crowbar. Its
airlock won't cycle without the module and the crowbar, and it's one way: once you
step outside it seals behind you. Past it the gravity is 60%. Outside is a course of
floating islands and cliff ledges over a void (falling in is death), with two gaps
only the long jump clears, headcrabs that keep coming back (monstermakers), an acid
pool guarded by a xen tree, and an arc between two crystals. At the far end a
decontamination airlock takes the crowbar ("held for analysis") and locks the way
back out. The field lab behind it has the clearance card, which powers its pad back
to the hub: one way (campaign.XEN_RETURN), onto an arrivals pad.

Coming back in through the station (the hub's pad), the station issues a new crowbar
(game_player_equip), opens the airlock to you again, and the decontamination airlock
is ready again, so the course can be run again; verify plays that too
(m.verify_round_trips). The suit and the long jump module stay with the player: no
stock entity takes them.

Top view (+Y = north), not to scale:

    +-------------------------------------------------------------------------+
    |                north cliff:  L1  L2  L3  L4 ..LJ.. L5  L6              |
    |                             /                          \               |
    |                           I6                         I7 acid pool,      |
    |                          /                             | xen tree       |
    |                        I5                              I8 arc            +--[field lab]
    |           I2  I3 ..LJ.. I4                               \ ..LJ.. shelf [decon]
 [station][airlock] shelf  I1                                               |
    |                                                                         |
    +------------------ the void (a lethal trigger_hurt) ---------------------+
"""
from hlmap import Level, Map, Material, box, logic, props, scene, teleport
from hlmap.geometry import cylinder
from hlmap.mapfile import Entity
from maps.campaign import XEN_GATE, XEN_RETURN

STATION = Material(floor="C1A0_LABFLRD", wall="C1A0_LABW7B", ceiling="LAB1_W8CEIL1A", floor_align="center",
                   ceiling_align="center")
LOCK = Material(floor="C1A0_LABFLRD", wall="C1A0_LABW7", ceiling="C1A0_LABW7", floor_align="center")
SKY = Material(floor="sky", wall="sky", ceiling="sky")
LAB_LAMP = "+0~LIGHT1"
CRYSTAL = "CRYS_2A"
GRAVITY = 0.6                      # outside the station and the field lab
INTERCOM = dict(voice_name="zira", radius="medium", color=(170, 220, 255))

# the course (see the module docstring). Islands: (name, centre, radius, top); gaps
# between neighbours are about 160 (a running jump in low gravity), and 460 at the two
# long jumps (I3 -> I4, L4 -> L5), and 420 from I8 up to the end shelf
ISLANDS = [("I1", (-1844, 0), 96, 0), ("I2", (-1513, 120), 96, 24), ("I3", (-1181, 275), 110, 48),
           ("I4", (-461, 275), 150, 48), ("I5", (-256, 630), 90, 88), ("I6", (-168, 958), 80, 128),
           ("I7", (1900, 840), 200, 152), ("I8", (1900, 340), 120, 168)]
CLIFF = 1344                       # the north cliff's face (y); ledges stick out of it to y 1184
LEDGES = [("L1", -248, -88, 168), ("L2", 82, 226, 200), ("L3", 396, 540, 176), ("L4", 710, 918, 208),
          ("L5", 1378, 1538, 208), ("L6", 1708, 1852, 184)]
START_SHELF = (-2080, 0)           # the shelf outside the airlock: its far edge (x), top
END_SHELF = (2440, 208)            # the shelf by the decontamination airlock: its near edge (x), top

HELLO = [
    ("Welcome to Xen Field Station Four. Please do not lick the plants.", None, None),
    ("Before you go out, take the field kit: the HEV suit, the long jump module and a crowbar. The airlock "
     "will not cycle without them.", "Before you go out, take the field kit: the H E V suit, the long jump module "
     "and a crowbar. The airlock will not cycle without them.", None),
    ("Gravity out there is sixty percent. To long jump, run, then crouch and jump together.", None, None),
    ("The field lab is on the far side of the islands. Mind the edges. And the headcrabs.", None, None),
]
LAB_HELLO = [
    ("Decontamination complete. Welcome to the field lab.", None, None),
    ("Your crowbar is being held for analysis. The field station will issue you another.", None, None),
    ("The clearance card on the desk powers the pad here, and its twin in the transit hub.", None, None),
]


def build():
    m = Map("xen", skyname="xen9")
    lvl = Level(wall=16)
    station = lvl.room("field station", (-3008, -224, 0), (-2560, 224, 160), STATION)
    lock = lvl.room("airlock", (-2544, -64, 0), (-2416, 64, 128), LOCK)
    field = lvl.room("the islands", (-2400, -800, -1024), (2680, 1600, 1024), SKY, checkpoints=[])
    decon = lvl.room("decontamination", (2696, 320, 208), (2824, 448, 336), LOCK)
    lab = lvl.room("field lab", (2696, 464, 208), (3160, 864, 368), STATION)
    inner = lvl.doorway(station, lock, width=96, height=112, center=0)
    outer = lvl.doorway(lock, field, width=96, height=112, center=0)
    decon_out = lvl.doorway(field, decon, width=96, height=112, center=384)
    decon_in = lvl.doorway(decon, lab, width=96, height=112, center=2760)
    window = lvl.doorway(field, lab, width=192, height=80, center=720, sill=40)
    lvl.build(m)

    # global states: the kit (the airlock checks it), what the field lab took, its card
    o = (-2784, 0, 140)
    crowbar = logic.Flag("xen_crowbar", False, o)             # holding a crowbar from the station
    longjump = logic.Flag("xen_longjump", False, o)           # the module is on the suit
    confiscated = logic.Flag("gear_confiscated", False, o)    # the field lab holds the crowbar
    clearance = logic.Flag("xen_clearance", False, (2928, 664, 340))
    m.add(crowbar.entities(), longjump.entities(), confiscated.entities(), clearance.entities())

    net = teleport.Network("transit")                         # online: the hub's side switched it on
    net.pad("station_pad", (-2784, -128, 0), "north", site="XEN FIELD STATION", label="TRANSIT HUB",
            link=XEN_GATE)
    net.pad("lab_pad", (2976, 600, 208), "east", site="XEN FIELD LAB", label="TRANSIT HUB", link=XEN_RETURN,
            power=clearance)                                  # dark until the card
    m.add(net.entities(m))

    field_station(m, station, net, crowbar, longjump, confiscated)
    airlock(m, lock, inner, outer, crowbar, longjump)
    islands(m, field)
    decontamination(m, decon, decon_out, decon_in, crowbar, confiscated)
    field_lab(m, lab, window, net, clearance)
    m.add(props.gravity_zone(decon.mins, lab.maxs, 1.0))         # the decontamination airlock and the lab

    m.add(props.player_start((-2784, -24, 0), facing="north"))   # where the hub's pad lands you
    m.checkpoints = ([("the start shelf", (-2200, 0, 0)), ("the end shelf", (2528, 384, 208))]
                     + [(f"island {n}", (x, y, top)) for n, (x, y), _, top in ISLANDS]
                     + [(f"ledge {n}", ((x0 + x1) / 2, CLIFF - 96, top)) for n, x0, x1, top in LEDGES])
    m.verify_round_trips = True          # the course can be run again (the station re-issues the crowbar)
    kit = ["xen_longjump_on", "xen_crowbar_on"]
    m.cameras = {
        "station": (-2784, -40, 64, 6, 90),
        "station_back": (-2784, 150, 70, 8, 270),
        "airlock": (-2530, 0, 64, 0, 0, kit + ["airlock_try"]),
        "shelf": (-2300, -40, 70, 4, 10, kit + ["airlock_try"]),
        "course": (-2350, -600, 700, 26, 40),
        "long_jump": (-1181, 275, 110, 4, 0),
        "ledges": (-168, 958, 200, 4, 30),
        "cliff": (600, 700, 400, 12, 70),
        "acid": (1900, 1120, 280, 22, 270),
        "arc": (1900, 520, 250, 14, 270),
        "end_shelf": (1900, 340, 240, 4, 0),
        "decon": (2720, 384, 272, 0, 0),
        "lab": (2720, 520, 272, 6, 30),
        "lab_pad": (2860, 600, 272, 8, 0, ["xen_clearance_on", ("transit_sync", 0.5)]),
        "lab_window": (2760, 720, 272, 6, 180),
    }
    return m


# ---------------------------------------------------------------- the station

def field_station(m, room, net, crowbar, longjump, confiscated):
    """The field station: the pad from the hub, the field kit on a bench, the HEV
    charger, the intercom. Coming back with the crowbar held by the field lab, a new
    one (and the decontamination airlock ready again)."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    cx = (x0 + x1) / 2
    m.texlight(LAB_LAMP, (200, 230, 255), 2200)
    for x in (x0 + 112, x1 - 112):
        for y in (y0 + 112, y1 - 112):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    m.add(props.light((cx, 0, z1 - 30), color=(210, 230, 255), brightness=150))
    # the field kit on a bench along the north wall, each at its front edge; the suit
    # first (the module only goes on the suit)
    m.add(props.table(cx, y1 - 28, 0, width=288, depth=48, height=36, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"))
    ky = y1 - 42
    m.add(props.point("item_suit", (cx - 96, ky, 40), facing=270, spawnflags=1),     # 1 = the short logon
          props.pickup("item_longjump", (cx, ky, 40), fires=[longjump.on], sound=None,
                       message="LONG JUMP MODULE: RUN, THEN CROUCH AND JUMP"),
          props.pickup("weapon_crowbar", (cx + 96, ky, 40), fires=[crowbar.on], sound=None))
    for dx, text in ((-96, "HEV SUIT"), (0, "LONG JUMP"), (96, "CROWBAR")):
        m.add(props.sign((cx + dx, y1, 72), "south", text, 64, 12, "steel"))
    m.add(props.sign((cx, y1, 118), "south", "FIELD KIT\nTAKE ALL THREE", 112, 32, "warning"),
          props.sign((cx, y0, 140), "north", "XEN FIELD STATION 4", 144, 16, "steel"))
    # the HEV charger and the network board on the west wall
    charger = box((x0, 96, 36), (x0 + 6, 144, 108), "FIFTIES_DSK5B", comment="hev charger")
    charger.fit("east", "+0RECHARGE")
    m.add(Entity("func_recharge", brushes=[charger]),
          props.sign((x0, -112, 96), "east", image=net.diagram(size=(224, 168)), w=112, h=84, frame="FIFTIES_DSK5B"))
    # the intercom: hello on the first arrival; a panel skips it
    head = (x0 + 6, 0, 130)
    hello = scene.Talk(m, "xen_hello", head, **INTERCOM)
    for text, say, _ in HELLO:
        hello.line(text, say=say)
    m.add(hello.entities(), props.trigger((x0, y0, 0), (x1, y1, 128), hello.start),
          props.wall_art((x0, 0, 130), "east", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          scene.skip_button((x1 - 96, y0, 60), "north", [hello], name="xen_hello_skip"))
    # back without the crowbar (the field lab took it): a new one, and the
    # decontamination airlock takes it again at the end; the airlock opens to the
    # station again (see airlock). Anywhere in the station: the pad lands you in it
    # (game_player_equip gives to whoever fired it, the player)
    o = (cx, 0, 120)
    m.add(props.trigger((x0, y0, 0), (x1, y1, 128), "station_enter", once=False, wait=1),
          logic.sequence("station_enter", [("resupply", 0), ("airlock_reset", 0)], o),
          logic.when("resupply", "resupply_go", [confiscated.is_on], o),
          props.point("game_player_equip", o, targetname="resupply_equip", weapon_crowbar=1, spawnflags=1),
          props.hud_message("resupply_msg", o, "EQUIPMENT ISSUED: CROWBAR", color=(90, 255, 120), y=0.62, channel=3),
          props.sound_effect("resupply_snd", o, "items/gunpickup2.wav", everywhere=True),
          logic.sequence("resupply_go", [(confiscated.off, 0), (crowbar.on, 0), ("resupply_equip", 0.1),
                                         ("resupply_msg", 0.1), ("resupply_snd", 0.1)], o))
    # a bench of samples in the south-west corner
    m.add(props.table(x0 + 80, y0 + 30, 0, width=128, depth=44, height=34, top="FIFTIES_DSK5B",
                      legs="FIFTIES_DSK5B"),
          props.crystal((x0 + 56, y0 + 30, 34), height=26, radius=6, lean=(2, 1), seed=31),
          props.crystal((x0 + 104, y0 + 34, 34), height=18, radius=5, lean=(-2, 2), seed=32))
    m.texlight(CRYSTAL, (110, 255, 170), 500)


def airlock(m, room, inner, outer, crowbar, longjump):
    """One way out. Two doors, never both open: `airlock_in` on opens the inner one
    (touch), `airlock_out` the outer one. CYCLE (with the long jump module and a
    crowbar) shuts the inner door and opens the outer; stepping out onto the shelf
    seals it behind you. Until then CYCLE takes you back in; sealed with the player
    still inside (they turned back in the doorway), it lets them out. Whenever the
    player is in the station (back from the hub), the station opens it to them again
    (`airlock_reset`)."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    cx = (x0 + x1) / 2
    o = (cx, 0, 110)
    inside = logic.Flag("airlock_in", True, o)                # the inner door works
    outside = logic.Flag("airlock_out", False, o)             # the outer door works
    busy = logic.Flag("airlock_busy", False, o)
    m.add(inside.entities(), outside.entities(), busy.entities())
    m.add(props.door_sliding(inner, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=1, master=inside.is_on),
          props.door_sliding(outer, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=1, master=outside.is_on))
    m.add(props.switch((cx, y0, 56), "north", "airlock_try", texture="+0BUTTON2", size=(16, 16), depth=3, sound=4),
          props.sign((cx, y0, 80), "north", "CYCLE", 40, 12, "warning"),
          props.sign((x0 - 16, -96, 100), "west", "FIELD ACCESS\nONE WAY", 64, 24, "warning"))
    lamp = [("airlock_lamp", 0), ("airlock_lamp", 2.2)]       # amber while it cycles
    m.add(logic.sequence("airlock_try", [("airlock_go_out", 0), ("airlock_go_back", 0), ("airlock_let_out", 0),
                                         ("airlock_no_lj", 0), ("airlock_no_bar", 0)], o),
          logic.when("airlock_go_out", "airlock_out_run", [busy.is_off, inside.is_on, longjump.is_on, crowbar.is_on],
                     o),
          logic.when("airlock_go_back", "airlock_back_run", [busy.is_off, outside.is_on], o),
          logic.when("airlock_let_out", "airlock_let_run", [busy.is_off, inside.is_off, outside.is_off], o),
          logic.when("airlock_no_lj", "airlock_denied", [inside.is_on, longjump.is_off], o),
          logic.when("airlock_no_bar", "airlock_denied", [inside.is_on, crowbar.is_off], o),
          props.hud_message("airlock_denied", o, "AIRLOCK LOCKED: FULL FIELD KIT REQUIRED", color=(255, 70, 50),
                            y=0.62, channel=3),
          logic.sequence("airlock_out_run", [(busy.on, 0), (inside.off, 0), ("airlock_hiss", 0), (outside.on, 2.2),
                                             (busy.off, 2.4)] + lamp, o),
          logic.sequence("airlock_back_run", [(busy.on, 0), (outside.off, 0), ("airlock_hiss", 0), (inside.on, 2.2),
                                              (busy.off, 2.4)] + lamp, o),
          logic.sequence("airlock_let_run", [(busy.on, 0), ("airlock_hiss", 0), (outside.on, 0.5), (busy.off, 0.8)], o),
          # out on the shelf: sealed behind you
          props.trigger((x1 + 80, -176, 0), (x1 + 112, 176, 112), "airlock_seal", once=False, wait=1),
          logic.when("airlock_seal", "airlock_seal_run", [outside.is_on], o),
          logic.sequence("airlock_seal_run", [(outside.off, 0), ("airlock_hiss", 0), ("airlock_sealed", 0)], o),
          props.hud_message("airlock_sealed", o, "AIRLOCK SEALED", color=(255, 180, 60), y=0.36, channel=4),
          # the station opens it to the player again (back from the hub)
          logic.when("airlock_reset", "airlock_back_run", [busy.is_off, inside.is_off], o),
          props.sound_effect("airlock_hiss", o, "ambience/steamburst1.wav", radius="small"))
    # lit, with an amber lamp while it cycles; the gravity notice stepping out
    m.add(props.light((cx, 0, z1 - 24), color=(220, 230, 255), brightness=110),
          props.light((cx, 40, z1 - 24), color=(255, 150, 40), brightness=120, targetname="airlock_lamp",
                      spawnflags=1),
          props.gravity_zone((x0 - 16 - 448, -224, 0), (x1, 224, 160), 1.0),     # the station and the airlock
          props.hud_message("gravity_msg", o, "LOCAL GRAVITY: 60%", color=(170, 220, 255), y=0.3, channel=3),
          props.trigger((x1 + 16, -48, 0), (x1 + 80, 48, 112), "gravity_msg", once=False, wait=8))


# ---------------------------------------------------------------- outside

def islands(m, field):
    """The course: rock faces at both ends and a cliff along the north, islands and
    ledges, the void under them all, low gravity over it, hazards, headcrabs."""
    (fx0, fy0, fz0), (fx1, fy1, fz1) = field.mins, field.maxs
    rock = props.XEN_ROCK
    # the station's rock (the airlock's passage through it at y -48..48, z 0..112),
    # the shelf outside it; the field lab's at the east end; the north cliff
    m.add(props.rock_wall("x", fx0, fx0 + 64, [-448, -256, -48, 48, 256, 448], [-560, -240, 0, 112, 336, 576],
                          holes=[(-48, 48, 0, 112)], seed=1, tex=rock),
          props.rock_shelf("x", fx0 + 48, START_SHELF[0], -176, 176, START_SHELF[1], seed=2, tex=rock),
          # (round the decontamination airlock's door, and the field lab's window)
          props.rock_wall("x", fx1, fx1 - 64, [144, 240, 336, 432, 528, 624, 816, 944],
                          [-360, -40, 208, 248, 320, 328, 480, 720],
                          holes=[(336, 432, 208, 320), (624, 816, 248, 328)], seed=3, tex=rock),
          props.rock_shelf("x", fx1 - 48, END_SHELF[0], 224, 544, END_SHELF[1], seed=4, tex=rock),
          props.rock_wall("y", fy1, CLIFF, list(range(-704, 2113, 128)), [-640, -400, -160, 40, 280, 520, 800],
                          jitter=48, seed=5, tex=rock))
    for n, x0, x1, top in LEDGES:
        m.add(props.rock_shelf("y", CLIFF + 64, CLIFF - 160, x0, x1, top, depth=220, jitter=8, seed=len(n) + x0,
                               tex=rock))
    for k, (n, (x, y), r, top) in enumerate(ISLANDS):
        m.add(props.floating_island((x, y), r, top, seed=10 + k))
    # the passages through the rock to the two airlocks' outer doors, lit
    m.add(props.light((fx0 + 40, 0, 96), color=(200, 220, 255), brightness=90),
          props.light((fx1 - 40, 384, 304), color=(200, 220, 255), brightness=90))
    # the void: death below, low gravity above
    m.add(props.hurt_zone((fx0, fy0, fz0), (fx1, fy1, -700), 1000),
          props.gravity_zone((fx0, fy0, -700), (fx1, fy1, fz1), GRAVITY))
    # Xen's light and sound
    # (high, from the south: it lights the island tops, the ledges and the cliff, and no
    # rock face shadows the shelf at its foot)
    m.add(props.point("light_environment", (0, 400, 900), pitch=-70, angles="0 90 0",
                      kv={"_light": "215 190 255 180", "_diffuse_light": "140 110 210 110"}),
          props.ambient_loop((-1300, 200, 300), "ambience/alienwind1.wav", volume=4),
          props.ambient_loop((400, 1000, 400), "ambience/aliencave1.wav", volume=4),
          props.ambient_loop((1900, 600, 400), "ambience/alienwind1.wav", volume=4))
    isl = {n: (x, y, r, top) for n, (x, y), r, top in ISLANDS}

    def on(name, dx, dy, dz=0):
        x, y, r, top = isl[name]
        return (x + dx, y + dy, top + dz)
    # plants and crystals, off the lines of the jumps
    for name, dx, dy in (("I1", -30, -60), ("I3", 20, -80), ("I6", 40, -40)):
        m.add(props.point("xen_hair", on(name, dx, dy)))
    for k, (name, dx, dy) in enumerate((("I2", 0, -50), ("I5", -40, -30), ("I7", 120, 60))):
        m.add(props.xen_plantlight(on(name, dx, dy), f"plant{k}", color=(255, 180, 90)))
    for k, (name, dx, dy, h) in enumerate((("I4", -40, -100, 96), ("I4", 60, -110, 70), ("I7", -40, -150, 90))):
        m.add(props.crystal(on(name, dx, dy), height=h, radius=12, lean=(4, -6), seed=40 + k))
    m.add(props.crystal((-2140, 150, 0), height=80, radius=12, lean=(-6, 4), seed=50),
          props.crystal((2560, 520, 208), height=90, radius=12, lean=(6, -4), seed=51))
    # headcrabs: they keep coming, a few at a time; health on the way
    m.add(props.monster_maker(on("I4", 40, 40, 16), "monster_headcrab", live=2),
          props.monster_maker((814, CLIFF - 80, 224), "monster_headcrab", live=1),
          props.monster_maker(on("I7", 60, -40, 16), "monster_headcrab", live=2),
          props.point("item_healthkit", on("I4", -30, 60, 8)),
          props.point("item_battery", (154, CLIFF - 100, 208)),
          props.point("item_healthkit", on("I7", 100, 110, 8)))
    # I7: an acid pool in the middle, a xen tree guarding its west side
    ax, ay, _ = on("I7", 0, 0)
    pool = Entity("func_illusionary", brushes=[cylinder((ax, ay), 72, isl["I7"][3], isl["I7"][3] + 1, sides=12,
                                                        tex="!TOXICGRN", comment="acid pool")])
    m.add(pool,
          props.hurt_zone((ax - 64, ay - 64, isl["I7"][3]), (ax + 64, ay + 64, isl["I7"][3] + 40), 10,
                          damagetype=1048576),
          props.light((ax, ay, isl["I7"][3] + 40), color=(120, 255, 90), brightness=90),
          props.point("xen_tree", on("I7", -150, 10), facing=0))
    # I8: an arc between two crystals across its middle; jump it
    y = isl["I8"][1] + 40
    top = isl["I8"][3]
    m.add(props.crystal((1818, y, top), height=80, radius=10, seed=61),
          props.crystal((1982, y, top), height=80, radius=10, seed=62),
          props.point("info_target", (1830, y, top + 22), targetname="arc_a"),
          props.point("info_target", (1970, y, top + 22), targetname="arc_b"),
          props.point("env_beam", (1900, y, top + 22), LightningStart="arc_a", LightningEnd="arc_b",
                      texture="sprites/laserbeam.spr", BoltWidth=24, NoiseAmplitude=40, renderamt=200,
                      rendercolor=(140, 255, 180), damage=25, life=0, StrikeTime=0, TextureScroll=35, spawnflags=1),
          props.ambient_loop((1900, y, top + 22), "ambience/zapmachine.wav", volume=3, radius="small"))
    # rocks drifting out of reach, with crystals
    for k, (c, size) in enumerate((((-1500, -560, 300), 140), ((200, -600, -120), 180), ((1300, -640, 420), 120),
                                   ((-700, -420, 760), 100), ((2200, -520, 120), 150), ((600, 380, 760), 90),
                                   ((-1650, 1150, 160), 160))):
        m.add(props.xen_rock(c, size, seed=70 + k))


# ---------------------------------------------------------------- the far end

def decontamination(m, room, out_door, in_door, crowbar, confiscated):
    """Walk in from the islands holding the crowbar: the doors lock behind you, green
    mist, the crowbar goes ("held for analysis"), and the door to the field lab opens.
    With the crowbar gone the outer door stays locked, so there's no way back out
    (until the station issues another)."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    o = ((x0 + x1) / 2, (y0 + y1) / 2, z1 - 24)
    m.add(props.door_sliding(out_door, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", wait=2, master=crowbar.is_on),
          props.door_sliding(in_door, texture="LAB1_DOOR2A", edge="LAB1_DOOR2B", wait=-1, targetname="decon_inner"),
          props.trigger((x0 + 16, y0, z0), (x1, y1, z0 + 112), "decon", once=False, master=crowbar.is_on, wait=5))
    m.add(logic.sequence("decon", [(crowbar.off, 0), (confiscated.on, 0), ("decon_hiss", 0), ("decon_msg", 0),
                                   ("decon_fade", 0.4), ("decon_shake", 0.4), ("decon_strip", 1.2),
                                   ("decon_msg2", 1.6), ("decon_hiss", 1.8), ("decon_inner", 3.0),
                                   ("decon_chime", 3.0)], o),
          props.sound_effect("decon_hiss", o, "ambience/steamburst1.wav"),
          props.sound_effect("decon_chime", o, "buttons/bell1.wav"),
          props.point("env_fade", o, targetname="decon_fade", duration=1.5, holdtime=0.6, renderamt=170,
                      rendercolor=(90, 255, 130), spawnflags=1 | 4),
          props.point("env_shake", o, targetname="decon_shake", amplitude=2, duration=1.5, frequency=40, radius=300),
          props.point("player_weaponstrip", o, targetname="decon_strip"),
          props.hud_message("decon_msg", o, "DECONTAMINATION IN PROGRESS", color=(90, 255, 130), y=0.3, channel=3),
          props.hud_message("decon_msg2", o, "EQUIPMENT HELD FOR ANALYSIS", color=(255, 220, 0), y=0.36, channel=4),
          props.light(o, color=(140, 255, 160), brightness=110),
          props.sign((x1, (y0 + y1) / 2, z0 + 90), "west", "DECONTAMINATION", 96, 16, "warning"))
    for dx in (32, 96):                       # shower heads
        m.add(props.detail(box((x0 + dx - 6, y0 + 58, z1 - 10), (x0 + dx + 6, y0 + 70, z1), "OUT_GALV1",
                               comment="nozzle")))


def field_lab(m, room, window, net, clearance):
    """The field lab: the clearance card on a desk (it powers the pad back to the hub,
    and the hub's pad back here), the window out over the course, the intercom."""
    x0, y0, z0 = room.mins
    x1, y1, z1 = room.maxs
    for x in (x0 + 112, x1 - 112):
        for y in (y0 + 96, y1 - 96):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    m.add(props.light(((x0 + x1) / 2, (y0 + y1) / 2, z1 - 30), color=(210, 230, 255), brightness=150))
    # the card, at the front edge of a desk on the north wall
    dx = 2880
    m.add(props.table(dx, y1 - 26, z0, width=128, depth=44, height=36, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"),
          props.pickup("item_security", (dx, y1 - 40, z0 + 40), fires=["card_taken"],
                       message="XEN CLEARANCE CARD: THE FIELD LAB PADS ARE ON"),
          logic.sequence("card_taken", [(clearance.on, 0), (net.sync, 0.2)], (dx, y1 - 60, z0 + 90)),
          props.sign((dx, y1, z0 + 96), "south", "CLEARANCE", 72, 14, "red"),
          props.sign(((x0 + x1) / 2, y1, z0 + 136), "south", "XEN FIELD LAB", 112, 16, "steel"))
    # the window over the islands
    (wx0, wy0, wz0), (wx1, wy1, wz1) = window.mins, window.maxs
    m.add(props.Entity("func_wall", brushes=[box((wx0 + 7, wy0, wz0), (wx0 + 9, wy1, wz1), "GLASS_BRIGHT",
                                                 comment="lab window")], rendermode=2, renderamt=50))
    # the intercom: says what happened as you come in; a panel skips it
    head = (x1 - 6, 760, z0 + 120)
    talk = scene.Talk(m, "xen_lab", head, **INTERCOM)
    for text, say, _ in LAB_HELLO:
        talk.line(text, say=say)
    m.add(talk.entities(), props.trigger((x0, y0, z0), (x0 + 160, y0 + 96, z0 + 112), talk.start),
          props.wall_art((x1, 760, z0 + 120), "west", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          scene.skip_button((x1, 680, z0 + 60), "west", [talk], name="xen_lab_skip"),
          props.ambient_loop((x1 - 60, y0 + 60, z0 + 60), "ambience/alien_zonerator.wav", volume=2, radius="small"))
