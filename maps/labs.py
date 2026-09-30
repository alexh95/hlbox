"""The materials lab, at the far end of the road tunnel from the office.

Top view (+Y = north):

                                   +-----------------------------+
      (tunnel from the office)     | loading dock  [roll-up doors]|
    +---------------------------+  |                              |  +--------------+
    | C2 ---- T3 ---- tunnel exit ==> loading bay       [guard]   |  |   lab        |===+--------------+
    +--+   (shared stretch,     +--+  car, crates,  forklift [post]=>[door]  samples  [window]  test    |
       |    maps/campaign.py)      |                              |  | console  [door]==  chamber      |
       | T2  <- arrival            |                              |  +--------------+   +--------------+
    ---+                           +------------------------------+
     C1 (the way back to the office)

Arriving from the office: the security guard greets you, one way if you sat through
the office briefing and another if you skipped it; that's the office's
`brief_pending` global state, carried across the level change. The lab door's card
reader wants the sector pass from the office's records room (global `sector_pass`).
In the lab an intercom asks you not to press the red button. Pressing it runs the
test: alarms, shaking, sparks, a flash, and the test chamber holds something new.
What the intercom makes of it depends on the briefing again. The chamber opens with
the flash (no waiting for the intercom), and an intercom panel on the lab wall skips
whatever it is saying.

The test also brings the resonance transit network online (hlmap.teleport): a pad in
the chamber and one in the loading bay send you to the transit hub, a room with no
doors, somewhere in Xen by the look out of its window. Its pads go back to both, and
three more wait offline for sites still to come ("SITE 2" to "SITE 4").

The tunnel leads back to the office.
"""
import math

from hlmap import Level, Map, Material, box, logic, props, scene, teleport
from hlmap.art import boxworth_faces, font, paint
from hlmap.geometry import cylinder, hull
from hlmap.mapfile import prepare_texture
from maps.campaign import LAMP_TEX, LINK, SODIUM, TUNNEL
from PIL import Image, ImageDraw

BAY = Material(floor="TNNL_FLR4", wall="TNNL_W12C2", ceiling="TNNL_C1", floor_align="min")
LAB = Material(floor="C1A0_LABFLR", wall="C1A0_LABW4", ceiling="FIFTIES_CEIL01", floor_align="min",
               ceiling_align="center")
CHAMBER = Material(floor="C1A0_LABFLRD", wall="C1A0_LABW7", ceiling="C1A0_LABW7", floor_align="center")
BAY_LAMP = "+0~GYMLIGHT"
LAB_LAMP = "+0~LIGHT1"
CRYSTAL = "CRYS_2A"
HUB = Material(floor="C1A0_LABFLRD", wall="C1A0_LABW7B", ceiling="LAB1_W8CEIL1A", floor_align="center",
               ceiling_align="center")
SKY = Material(floor="sky", wall="sky", ceiling="sky")

# the guard, as you walk into the bay: after the office briefing, or without it
GREET_BRIEFED = [
    ("Afternoon. You must be the one from the briefing. They said you'd be coming down.", None, "barn_wave"),
    ("The lab's through that door, and your sector pass works the reader. Oh, and don't press anything red in "
     "there.", None, "idle3"),
]
GREET_SKIPPED = [
    ("Hold on. You're the one who skipped the quarterly briefing, aren't you? Relax, I won't tell.", None, "idle3"),
    ("The lab's through that door, and your sector pass works the reader. They'll fill you in. Probably.", None,
     "barn_wave"),
]
# the lab's intercom
WELCOME = [
    ("Welcome to the Materials Lab. Please keep to the marked walkways.", None, None),
    ("The sample in the test chamber is perfectly stable. Please do not press the red button.", None, None),
]
TEST = [
    ("Oh. You pressed it.", None, None),
    ("Resonance at one hundred and five percent. One hundred and ten. That is quite a lot of percent.", None, None),
    ("Everything is fine. Please remain calm, and behind the glass.", None, None),
]
TEST_BRIEFED = [
    ("Well. That is new.", None, None),
    ("Is that... Boxworth? The mascot from the briefing slides? He's real?", None, None),
    ("The chamber door is open. Go and say hello. He seems friendly.", None, None),
    ("Oh, and the transit pads have switched themselves on. I suppose that is how he got here.", None, None),
]
TEST_SKIPPED = [
    ("Well. That is new.", None, None),
    ("It appears to be a crate. With boots. And a hard hat. If only someone had explained this at the briefing.",
     None, None),
    ("The chamber door is open. Go and see for yourself.", None, None),
    ("Also, the transit pads have switched themselves on. That is probably related.", None, None),
]
# the transit hub's intercom, the first time you arrive
HUB_WELCOME = [
    ("Welcome to the resonance transit hub. Please step away from the pads.", None, None),
    ("Its location is classified. Also, unknown. Please do not tap on the glass.", None, None),
    ("Sites two to four are offline, pending construction. Watch this space.", None, None),
]


def whiteboard_texture():
    """The lab's whiteboard: sample notes, and a sketch of the chamber."""
    img = Image.new("RGB", (256, 128), (236, 238, 234))
    d = ImageDraw.Draw(img)
    blue, red, black = (40, 70, 170), (190, 40, 30), (30, 30, 36)
    d.text((12, 8), "SAMPLE 7 - RESONANCE TEST", fill=blue, font=font(14))
    for i, t in enumerate(("stable (!)", "hums in B flat", "do NOT lick", "do NOT press red button")):
        d.text((16, 32 + i * 18), f"- {t}", fill=black if i < 2 else red, font=font(12, bold=False))
    d.polygon([(200, 104), (194, 60), (206, 36), (214, 62), (210, 104)], outline=(40, 140, 90), width=2)
    d.rectangle((180, 104, 232, 112), outline=black, width=2)
    d.text((214, 20), "?", fill=red, font=font(20))
    d.text((170, 20), "B7", fill=blue, font=font(12))
    return img


def build():
    m = Map("labs", skyname="xen9")
    lvl = Level(wall=16)

    # --- rooms: the shared stretch of tunnel, its exit, the bay, the lab, the chamber
    LINK.place(m, lvl)
    tunnel_exit = lvl.room("tunnel exit", (-432, 352, 0), (-48, 608, 192), TUNNEL, group="tunnel")
    bay = lvl.room("loading bay", (-32, 96, 0), (736, 864, 256), BAY)
    lab = lvl.room("lab", (752, 224, 0), (1392, 736, 160), LAB)
    chamber = lvl.room("test chamber", (1408, 288, 0), (1792, 672, 224), CHAMBER)
    lvl.doorway(tunnel_exit, bay, width=256, height=192, center=480)
    lab_door = lvl.doorway(bay, lab, width=96, height=112, center=480)
    window = lvl.doorway(lab, chamber, width=160, height=80, center=416, sill=24)   # low: see the chamber floor
    chamber_door = lvl.doorway(lab, chamber, width=128, height=112, center=592)
    # the transit hub: no doors, only pads; its window looks out on Xen (a room made of
    # sky, with floating rocks, that nobody needs to reach)
    hub = lvl.room("transit hub", (704, -608, 0), (1344, -96, 192), HUB)
    view = lvl.room("xen view", (256, -1856, -768), (1792, -624, 640), SKY, checkpoints=[])
    hub_window = lvl.doorway(hub, view, width=384, height=104, center=1024, sill=40)
    lvl.build(m)

    # carried over from the office (global states); these give them their starting
    # values when the map is loaded on its own
    sector_pass = logic.Flag("sector_pass", False, (600, 200, 200))
    briefing = logic.Flag("brief_pending", True, (600, 200, 200))
    m.add(sector_pass.entities(), briefing.entities())

    tunnel(m, tunnel_exit)
    loading_bay(m, bay, lab_door, sector_pass, briefing)
    welcome = lab_room(m, lab, window)
    net = teleport.Network("transit", online=False)
    talks = test(m, chamber, chamber_door, briefing, net)
    # the intercom panel by the console: skips whatever the intercom is saying
    m.add(scene.skip_button((1296, 224, 60), "north", [welcome] + talks, name="intercom_skip"))
    transit_hub(m, hub, view, hub_window, net)

    m.add(props.player_start((-944, 208, 0), facing="north"))     # where the office's tunnel lands you
    m.checkpoints = [("the loading dock", (320, 832, 48))]
    m.cameras = {
        "arrival": (-944, 150, 64, 0, 90),
        "tunnel_exit": (-400, 480, 64, 0, 0),
        "bay": (30, 740, 130, 14, 325),
        "bay_guard": (300, 420, 64, 0, 0),
        "dock": (500, 300, 110, 8, 120),
        "lab_door": (560, 480, 64, 0, 0),
        "lab_door_open": (560, 480, 64, 0, 0, ["lab_door"]),
        "lab": (780, 250, 100, 12, 30),
        "lab_window": (1250, 416, 64, 0, 0),
        "test_flash": (1250, 416, 64, 0, 0, ["lab_test"]),
        "test_after": (1250, 416, 64, 0, 0, [("boxworth", 0.3), ("chamber_door", 0.6)]),
        "chamber": (1440, 600, 90, 10, 330, [("boxworth", 0.3), ("chamber_door", 0.6)]),
        "way_back": (-944, 300, 64, 0, 270),
        # the transit network, online
        "chamber_pad": (1500, 330, 80, 8, 15, ["transit_start"]),
        "skip_panel": (1296, 300, 64, 8, 270),
        "bay_pad": (340, 420, 80, 10, 270, ["transit_start"]),
        "hub": (1024, -560, 110, 12, 90, ["transit_start"]),
        "hub_window": (1024, -300, 90, 4, 270, ["transit_start"]),
        "hub_board": (900, -400, 70, 0, 250, ["transit_start"]),
        "hub_offline": (1024, -420, 70, 0, 20, ["transit_start"]),
    }
    return m


def tunnel(m, tunnel_exit):
    """The tunnel's last stretch in this map: lamps, centre line, and the dead end of
    the shared stretch where the office side would go on."""
    for x, y, facing in ((-256, 608, "south"), (-128, 352, "north")):
        fx, fy = props.DIRS[facing]
        m.add(props.wall_art((x, y, 150), facing, LAMP_TEX, 48, 32, depth=6, frame="OUT_GALV1"),
              props.light((x + fx * 24, y + fy * 24, 140), color=SODIUM, brightness=150))
    m.add(props.Entity("func_illusionary", brushes=[box((x, 478, 0), (x + 48, 482, 1), "PAINTY", comment="road dash")
                                                    for x in range(-400, -64, 96)]))
    west = LINK.origins["labs"][0] - 512
    y0 = LINK.origins["labs"][1]
    m.add(props.Entity("func_wall", brushes=[box((west, y0 - 512, 0), (west + 2, y0 - 256, 192), "BLACK",
                                                 comment="tunnel dark")]))


def loading_bay(m, bay, lab_door, sector_pass, briefing):
    x0, y0, z0 = bay.mins
    x1, y1, z1 = bay.maxs
    # lamps: round industrial lamps on the ceiling, lit by point lights below them
    m.texlight(BAY_LAMP, (255, 236, 200), 2500)
    for x in (96, 352, 608):
        for y in (256, 640):
            lamp = box((x - 24, y - 24, z1 - 6), (x + 24, y + 24, z1), "OUT_GALV1", comment="bay lamp")
            lamp.fit("bottom", BAY_LAMP)
            m.add(props.detail(lamp), props.light((x, y, z1 - 40), color=(255, 236, 200), brightness=200))
    # the loading dock along the north wall, steps at its west end, bumpers, roll-up doors
    dock_y, dock_h = y1 - 96, 48
    m.add(props.detail(box((64, dock_y, 0), (640, y1, dock_h), {"default": "TNNL_W12C2", "top": "TNNL_FLR4"},
                           comment="loading dock")))
    for k in range(3):                                     # 16-high steps up from the west
        m.add(props.detail(box((16 + k * 16, dock_y, 0), (64, y1, 16 * (k + 1)), {"default": "TNNL_W12C2",
                                                                                  "top": "TNNL_FLR4"},
                               comment="dock step")))
    for x in (160, 352, 544):
        m.add(props.detail(box((x - 12, dock_y - 6, 12), (x + 12, dock_y, 40), "BLACK", comment="dock bumper")))
        m.add(props.wall_art((x, y1, dock_h + 80), "south", "LAB1_DOOR01", 144, 144, depth=2, frame="OUT_GALV1"))
    m.add(props.stencil("DOCK", (x0, 640, 120), "east"))
    # a Black Mesa car by the west wall, crates on pallets, a forklift
    m.add(props.car(40 + 88, 180, 0, "east", "white"))
    for x, y, stack in ((520, 160, ("XCRATE1A", "XCRATE1B")), (600, 160, ("CRATE02B",)),
                        (440, 700, ("BCRATE09A", "CRATE19")), (240, 710, ("CRATE25",))):
        m.add(props.detail(box((x - 30, y - 30, 0), (x + 30, y + 30, 6), "FIFTIES_DR1", comment="pallet")))
        z = 6
        for tex in stack:
            m.add(props.crate(x, y, z, size=48, texture=tex))
            z += 48
    m.add(forklift(300, 690, 0))
    # painted floor: the walkway from the tunnel to the lab door, the car's bay
    m.add(floor_lines([((16, 428), (720, 436)), ((16, 524), (720, 532)),
                       ((30, 128), (226, 132)), ((30, 228), (226, 232)), ((222, 132), (226, 228))]))
    # the security desk by the lab door, and its guard (pre-disaster: won't follow,
    # gagged: only says his lines)
    m.add(props.table(620, 320, 0, width=40, depth=112, height=36, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"),
          props.detail(props.front_box(626, 290, 36, 18, 22, 16, "west", "FIFTIES_MON3")),
          props.sign((x1, 300, 110), "west", "SECURITY CHECKPOINT", 80, 16, "steel"),
          props.sign((x1, 480, 132), "west", "MATERIALS LAB", 72, 16, "red"),
          props.point("monster_barney", (672, 336, 0), facing=180, targetname="guard", spawnflags=2 | 256))
    head = (672, 336, 66)
    talks = {}
    for key, lines in (("greet_briefed", GREET_BRIEFED), ("greet_skipped", GREET_SKIPPED)):
        t = scene.Talk(m, key, head, actor="guard", pitch=0.92, rate=1, actor_model="models/barney.mdl")
        for text, say, gesture in lines:
            t.line(text, say=say, gesture=gesture)
        m.add(t.entities())
        talks[key] = t
    m.add(logic.when("greet_if_briefed", talks["greet_briefed"].start, [briefing.is_off], head),
          logic.when("greet_if_skipped", talks["greet_skipped"].start, [briefing.is_on], head),
          logic.sequence("greet", [("greet_if_briefed", 0), ("greet_if_skipped", 0)], head),
          props.trigger((x0, 352, 0), (x0 + 128, 608, 128), "greet"))
    # the lab door opens for the sector pass, at a reader on a post in front of it
    # (not on the wall: +use reaches through walls, into the lab)
    m.add(props.door_sliding(lab_door, texture="LAB1_DOOR1", edge="LAB1_DOOR2B", direction="up", wait=-1,
                             targetname="lab_door"),
          props.detail(box((688, 556, 0), (700, 572, 60), "OUT_GALV1", comment="reader post")),
          props.card_reader((688, 564, 48), "west", "lab_door", sector_pass, "lab_reader",
                            denied="SECTOR PASS REQUIRED"),
          props.Entity("func_illusionary", brushes=[box((704, 432, 0), (736, 528, 1), "STRIPES1",
                                                        comment="hazard stripes")]))


def floor_lines(rects, texture="PAINTY"):
    """Painted lines on the floor: [((x0, y0), (x1, y1))] rectangles (non-solid)."""
    return props.Entity("func_illusionary", brushes=[box((x0, y0, 0), (x1, y1, 1), texture, comment="floor line")
                                                     for (x0, y0), (x1, y1) in rects])


def forklift(x, y, z, paint_tex="PAINTFORK"):
    """A little forklift facing west (forks raised a bit), as brush detail."""
    fork = props.detail(
        box((x - 28, y - 22, z + 6), (x + 28, y + 22, z + 34), paint_tex, comment="forklift body"),
        box((x + 10, y - 22, z + 34), (x + 28, y + 22, z + 46), "BLACK", comment="counterweight"),
        box((x - 8, y - 12, z + 34), (x + 6, y + 12, z + 40), "BLACK", comment="seat"),
        box((x - 36, y - 20, z + 6), (x - 30, y - 14, z + 84), "OUT_GALV1", comment="mast"),
        box((x - 36, y + 14, z + 6), (x - 30, y + 20, z + 84), "OUT_GALV1", comment="mast"),
        box((x - 76, y - 16, z + 14), (x - 36, y - 10, z + 17), "OUT_GALV1", comment="fork"),
        box((x - 76, y + 10, z + 14), (x - 36, y + 16, z + 17), "OUT_GALV1", comment="fork"),
        box((x - 20, y - 22, z + 80), (x + 20, y + 22, z + 84), paint_tex, comment="guard roof"),
        *[box((px - 2, py - 2, z + 34), (px + 2, py + 2, z + 80), "OUT_GALV1", comment="guard post")
          for px in (x - 18, x + 18) for py in (y - 20, y + 20)],
        *[cylinder((wx, wy), 7, z, z + 14, sides=8, tex="TIRES", comment="wheel")
          for wx in (x - 18, x + 18) for wy in (y - 24, y + 24)])
    fork.textures = {paint_tex: prepare_texture(paint_tex, paint((236, 176, 20), noise=8, seed=3))}
    return fork


def lab_room(m, lab, window):
    x0, y0, z0 = lab.mins
    x1, y1, z1 = lab.maxs
    m.texlight(LAB_LAMP, (200, 230, 255), 2200)
    for x in (848, 1072, 1296):
        for y in (352, 608):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    m.add(props.light((1072, 480, z1 - 24), color=(220, 236, 255), brightness=120))
    # equipment panels on the walls (the c1a0 lab look), a whiteboard, the intercom
    for x, tex in ((880, "C1A0_LABW1"), (1136, "C1A0_LABW3")):
        m.add(props.wall_art((x, y1, 80), "south", tex, 256, 160, depth=1, frame="C1A0_LABW4"))
    m.add(props.wall_art((880, y0, 80), "north", "C1A0_LABW8", 256, 160, depth=1, frame="C1A0_LABW4"))
    m.add(props.sign((1160, y0, 84), "north", image=whiteboard_texture(), w=128, h=64, frame="FIFTIES_DSK5B"),
          props.wall_art((x0, 640, 120), "east", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"))
    # sample cases along the north wall: glass over small crystals
    m.texlight(CRYSTAL, (110, 255, 170), 500)
    for k, x in enumerate((1040, 1136, 1232)):
        m.add(props.detail(box((x - 28, y1 - 64, 0), (x + 28, y1 - 16, 40), "LAB1_CAB2", comment="sample stand")),
              props.crystal((x, y1 - 40, 40), height=30 + 6 * k, radius=7, lean=(3 - 3 * k, 2), seed=20 + k))
        glass = box((x - 26, y1 - 62, 40), (x + 26, y1 - 18, 90), "GLASS_MED", comment="sample case")
        m.add(props.Entity("func_wall", brushes=[glass], rendermode=2, renderamt=70))
    # workbenches along the south wall
    for x in (1000, 1160):
        m.add(props.table(x, y0 + 30, 0, width=112, depth=44, height=34, top="FIFTIES_DSK5B",
                          legs="FIFTIES_DSK5B"),
              props.detail(props.front_box(x - 24, y0 + 22, 34, 32, 18, 24, "north", "+0~LAB1_CMP1")))
    m.texlight("+0~LAB1_CMP1", (140, 200, 255), 80)
    # the marked walkway, from the door to the console
    m.add(floor_lines([((768, 428), (1320, 436)), ((768, 524), (1320, 532))]))
    # the observation window's glass, and the console in front of it with THE button
    (wx0, wy0, wz0), (wx1, wy1, wz1) = window.mins, window.maxs
    m.add(props.Entity("func_wall", brushes=[box((wx0 + 7, wy0, wz0), (wx0 + 9, wy1, wz1), "GLASS_BRIGHT",
                                                 comment="window")], rendermode=2, renderamt=60))
    console = props.front_box(x1 - 40, 416, 0, 32, 144, 40, "west", "LAB1_PANELF", sides="FIFTIES_DSK5B",
                              top="FIFTIES_DSK5B")
    m.add(props.detail(console),
          props.sign((x1 - 56, 416, 26), "west", "DO NOT PRESS", 48, 10, "red"))
    button = box((x1 - 52, 408, 40), (x1 - 36, 424, 43), "FIFTIES_DSK5B", comment="test button")
    button.fit("top", "+0BUTTON2")                   # red; lit while pressed
    m.add(props.Entity("func_button", brushes=[button], target="lab_test", sounds=10, wait=-1, spawnflags=1))
    head = (x0 + 6, 640, 120)
    welcome = scene.Talk(m, "welcome", head, voice_name="zira", radius="medium", color=(170, 220, 255))
    for text, say, _ in WELCOME:
        welcome.line(text, say=say)
    m.add(welcome.entities(), props.trigger((x0, 224, 0), (x0 + 96, y1, 128), welcome.start))
    return welcome


def test(m, chamber, chamber_door, briefing, net):
    """The resonance test: the button starts it, effects on cue, then the flash:
    Boxworth appears and the chamber opens, and the intercom reacts (briefing or not)
    unless the test talk was skipped. Returns the talks (for the skip button)."""
    x0, y0, z0 = chamber.mins
    x1, y1, z1 = chamber.maxs
    cx, cy = 1600, 480
    # the chamber: a pedestal with a big crystal, an emitter above it, lights
    m.add(props.detail(cylinder((cx, cy), 40, 0, 16, sides=12, tex={"top": "C1A0_LABFLRE", "bottom": "C1A0_LABFLRE",
                                                                    "sides": "OUT_GALV1"}, comment="pedestal")),
          props.crystal((cx, cy, 16), height=120, radius=20, lean=(6, -4), seed=5),
          props.detail(cylinder((cx, cy), 20, z1 - 40, z1, sides=10, tex="OUT_GALV1", comment="emitter"),
                       cylinder((cx, cy), 8, z1 - 56, z1 - 40, sides=8, tex="+0~LIGHT5A", comment="emitter tip")))
    m.texlight("+0~LIGHT5A", (120, 220, 255), 200)
    m.add(props.light((cx - 120, cy, z1 - 30), color=(200, 255, 220), brightness=160, targetname="chamber_lights"),
          props.light((cx + 120, cy, z1 - 30), color=(200, 255, 220), brightness=160, targetname="chamber_lights"))
    m.add(props.door_sliding(chamber_door, texture="LAB1_DOOR2A", edge="LAB1_DOOR2B", direction="up", wait=-1,
                             targetname="chamber_door"),
          props.sign((1392, 592, 136), "west", "TEST CHAMBER", 64, 14, "warning"))
    # Boxworth: a crate with boots, arms and a hard hat, hidden until the flash
    front, side = boxworth_faces()
    textures = {"BWFACE": prepare_texture("BWFACE", front), "BWSIDE": prepare_texture("BWSIDE", side),
                "PAINTBOOT": prepare_texture("PAINTBOOT", paint((52, 54, 62), seed=4)),
                "PAINTHAT": prepare_texture("PAINTHAT", paint((255, 204, 0), seed=5))}
    bx, by = 1528, 480
    body = box((bx - 20, by - 20, 8), (bx + 20, by + 20, 48), "BWSIDE", comment="boxworth")
    body.fit("west", "BWFACE")
    for s in ("north", "south", "east", "top"):
        body.fit(s, "BWSIDE")
    parts = [body,
             box((bx - 12, by - 18, 0), (bx + 12, by - 4, 8), "PAINTBOOT", comment="boot"),
             box((bx - 12, by + 4, 0), (bx + 12, by + 18, 8), "PAINTBOOT", comment="boot"),
             box((bx - 6, by - 26, 20), (bx + 6, by - 20, 40), "BWSIDE", comment="arm"),
             box((bx - 6, by + 20, 20), (bx + 6, by + 26, 40), "BWSIDE", comment="arm"),
             cylinder((bx, by), 24, 48, 50, sides=12, tex="PAINTHAT", comment="hat brim"),
             cylinder((bx, by), 17, 50, 62, sides=12, tex="PAINTHAT", comment="hard hat")]
    boxworth = props.Entity("func_wall_toggle", brushes=parts, targetname="boxworth", spawnflags=1)
    boxworth.textures = textures
    m.add(boxworth)
    # effects
    o = (cx, cy, 120)
    # the alarm loops (its WAV has loop points) until the reveal turns it off
    m.add(props.sound_effect("test_alarm", (1300, 480, 120), "ambience/warn2.wav", volume=8, radius="large",
                             stoppable=True),
          props.Entity("trigger_relay", targetname="test_alarm_off", target="test_alarm", triggerstate=0,
                       origin=(1300, 480, 120)),
          props.sound_effect("test_hum", o, "ambience/particle_suck1.wav", volume=10, radius="large"),
          props.sound_effect("test_pop", o, "ambience/port_suckout1.wav", volume=10, radius="large"),
          props.point("env_shake", o, targetname="test_shake", amplitude=4, duration=2.5, frequency=30, radius=1200),
          props.point("env_spark", (cx, cy, 60), targetname="test_sparks", MaxDelay=0.2, spawnflags=32),
          props.point("env_fade", o, targetname="test_flash", duration=2, holdtime=0.4, renderamt=255,
                      rendercolor="255 255 255", spawnflags=1))     # 1 = fade from white
    flicker = [("chamber_lights", 0.15 * k) for k in range(8)]      # an even number: ends on
    m.add(logic.sequence("test_flicker", flicker, o))
    head = (752 + 6, 640, 120)                                      # the intercom
    talk = scene.Talk(m, "lab_test", head, voice_name="zira", radius="medium", color=(170, 220, 255))
    cues = [["test_alarm"], ["test_hum", "test_shake", "test_sparks"], ["test_flicker", "test_shake"]]
    for (text, say, _), fire in zip(TEST, cues):
        talk.line(text, say=say, fire=fire)
    talk.on_end.append("test_after")
    m.add(talk.entities())
    endings = {}
    for key, lines in (("test_briefed", TEST_BRIEFED), ("test_skipped", TEST_SKIPPED)):
        t = scene.Talk(m, key, head, voice_name="zira", radius="medium", color=(170, 220, 255))
        for text, say, _ in lines:
            t.line(text, say=say)
        m.add(t.entities())
        endings[key] = t
    # the reveal (after the test talk, or right away if it's skipped); the intercom's
    # reaction only if nobody skipped the test
    m.add(logic.sequence("test_after", [("test_flash", 0), ("test_pop", 0), ("boxworth", 0.2), ("test_sparks", 0.4),
                                        ("test_alarm_off", 0.4), ("chamber_door", 0.6), (net.start, 1.5),
                                        ("test_if_briefed", 2.5),
                                        ("test_if_skipped", 2.5)], o),
          logic.when("test_if_briefed", endings["test_briefed"].start, [briefing.is_off, talk.skipped.is_off], o),
          logic.when("test_if_skipped", endings["test_skipped"].start, [briefing.is_on, talk.skipped.is_off], o))
    return [talk] + list(endings.values())


def transit_hub(m, hub, view, window, net):
    """The resonance transit hub and its network: pads here, in the test chamber and in
    the loading bay; three offline slots for sites to come; the view out; the intercom."""
    x0, y0, z0 = hub.mins
    x1, y1, z1 = hub.maxs
    # the network: two-way routes to the chamber and the bay, three slots
    chamber_pad = net.pad("pad_chamber", (1736, 400, 0), "west", site="TEST CHAMBER")   # arrive facing Boxworth
    bay_pad = net.pad("pad_bay", (340, 200, 0), "north", site="LOADING BAY")
    net.route(net.pad("hub_chamber", (1024, -200, 0), "south", site="TRANSIT HUB"), chamber_pad)
    net.route(net.pad("hub_bay", (832, -200, 0), "south", site="TRANSIT HUB"), bay_pad)
    for k, (pos, facing) in enumerate((((1216, -200, 0), "south"), ((784, -400, 0), "east"),
                                       ((1264, -400, 0), "west")), 2):
        net.pad(f"hub_site{k}", pos, facing, site="TRANSIT HUB", label=f"SITE {k}", offline=True)
    m.add(net.entities())
    # the room: lab lights, the network board, the window and what's out there
    for x in (832, 1216):
        for y in (-480, -224):
            m.add(props.ceiling_light(x, y, z1, width=64, depth=32, texture=LAB_LAMP))
    for x, y in ((1024, -352), (832, -300), (1216, -300), (1024, -520)):
        m.add(props.light((x, y, z1 - 30), color=(210, 230, 255), brightness=170))
    m.add(props.sign((768, y0, 96), "north", image=net.diagram(size=(224, 168)), w=112, h=84, frame="FIFTIES_DSK5B"),
          props.sign((1024, y1, 150), "south", "RESONANCE TRANSIT HUB", 144, 18, "steel"))
    (wx0, wy0, wz0), (wx1, wy1, wz1) = window.mins, window.maxs
    m.add(props.Entity("func_wall", brushes=[box((wx0, wy0 + 7, wz0), (wx1, wy0 + 9, wz1), "GLASS_BRIGHT",
                                                 comment="hub window")], rendermode=2, renderamt=50))
    # Xen out there: its sky (worldspawn skyname) and light, rocks drifting with crystals on
    m.add(props.point("light_environment", (1024, -1200, 400), pitch=-35, angles="0 80 0",
                      kv={"_light": "200 150 255 110", "_diffuse_light": "120 90 190 40"}))
    for k, (c, size) in enumerate((((640, -1120, 40), 150), ((1420, -980, -120), 110), ((1120, -1560, 260), 190),
                                   ((520, -1640, -260), 120), ((1560, -1500, 60), 90))):
        m.add(xen_rock(c, size, seed=k))
    # the intercom: says hello on the first arrival; a panel skips it
    head = (x1 - 6, -300, 150)
    hello = scene.Talk(m, "hub_hello", head, voice_name="zira", radius="medium", color=(170, 220, 255))
    for text, say, _ in HUB_WELCOME:
        hello.line(text, say=say)
    m.add(hello.entities(), props.trigger((x0, y0, 0), (x1, y1, 128), hello.start),
          props.wall_art((x1, -300, 150), "west", "LAB1_SKR1", 20, 24, depth=4, frame="FIFTIES_DSK5B"),
          scene.skip_button((1296, y0, 60), "north", [hello], name="hub_skip"))


def xen_rock(center, size, seed=0):
    """A floating Xen rock: a lumpy convex hull, crystals on top."""
    import random
    rnd = random.Random(seed)
    cx, cy, cz = center
    snap = lambda v: 8 * round(v / 8)                 # a coarse grid: no sliver faces
    pts = []
    for k in range(9):                                 # a flat, lumpy-edged top (crystals sit on it)
        a = 2 * math.pi * k / 9 + rnd.uniform(-0.15, 0.15)
        r = size * rnd.uniform(0.7, 1.0)
        pts.append((snap(cx + r * math.cos(a)), snap(cy + r * math.sin(a)), snap(cz)))
    for k in range(3):
        a = 2 * math.pi * k / 3 + rnd.uniform(-0.3, 0.3)
        r = size * rnd.uniform(0.2, 0.4)
        pts.append((snap(cx + r * math.cos(a)), snap(cy + r * math.sin(a)), snap(cz - size * rnd.uniform(0.8, 1.1))))
    rock = props.detail(hull(pts, {"top": "-0XENO_2WA", "default": "-0XENO_2W1"}, comment="xen rock"))
    n = 2 if size > 100 else 1                         # apart from each other (touching ones lose faces)
    a0 = rnd.uniform(0, 2 * math.pi)
    crystals = [props.crystal((round(cx + math.cos(a0 + j * math.pi) * size * 0.3 * (n > 1)),
                               round(cy + math.sin(a0 + j * math.pi) * size * 0.3 * (n > 1)), snap(cz) + 8),
                              height=round(size * rnd.uniform(0.4, 0.7)), radius=round(size * 0.08),
                              lean=(rnd.randint(-8, 8), rnd.randint(-8, 8)), seed=seed * 7 + j)
                for j in range(n)]
    return [rock] + crystals
