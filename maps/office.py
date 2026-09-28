"""Black-Mesa-ish office block over a basement, with a cave that turns into Xen.

Top view (+Y = north), ground floor:

              +--------------------------------+
              |  conference room               |  table for 8, projector + screen
              |  (CCC slides)            [stairs down]
    +---------+------[door]------------------+-+--------------+
    | storage |[locked]      hallway          [locked]| records   |  two levels,
    |  (stairs up from basement)       [cave]         | mezzanine |  ladder up
    +---------+--------------------------------+------+-----------+
                                             |
                          radio camp <-- branch  \\___ rock ___ Xen ___ chamber
                          (access card: opens records)

Basement (z -176): under the conference room, a corridor west under the hallway, and
stairs up into the storage room. The storage door opens from inside (release switch).
"""
import math

from hlmap import Level, Map, Material, box, props
from PIL import Image, ImageDraw

from hlmap.art import font, pixel_svg, slide
from hlmap.cave import ROCK
from hlmap.config import PROJECT_DIR

CONFERENCE = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14U", ceiling="FIFTIES_CEIL01",
                      ceiling_align="center")
HALL = Material(floor="FIFTIES_FLR03", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01",
                floor_align="center", ceiling_align="center")
STORAGE = Material(floor="C1A1_FLR2B", wall="FIFTIES_WALL12B", ceiling="FIFTIES_CEIL01", ceiling_align="center")
RECORDS = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14A", ceiling="FIFTIES_CEIL01", ceiling_align="center")
BASEMENT = Material(floor="CRETE2_FLR01", wall="CRETE4_WALL01", ceiling="CRETE3_CEIL01")
XEN = Material(floor="-0XENO_2WA", wall="-0XENO_2W1", ceiling="-0XENO_2W1")

LIGHT_TEX = "+0~FIFTS_LGHT01"       # office-type rooms
HALL_LIGHT_TEX = "+0~FIFTS_LGHT06"  # same look, dimmer (narrow hall)
CRYSTAL_TEX = "CRYS_2A"
YELLOW = (255, 220, 0)


def slides(m):
    """The projector's two slides, drawn from the CCC mascot (a pixel-art SVG)."""
    mascot = pixel_svg(PROJECT_DIR / "assets" / "ccc_mascot.svg")
    bg = (14, 16, 24)
    m.add_texture("+0CCCSLIDE", slide((256, 160), bg, mascot, (6, 22, 126, 118), [
        ("CCC", (192, 62), 50, YELLOW, "mm"),
        ("CODING", (192, 102), 18, (240, 240, 240), "mm"),
        ("CONTEST", (192, 122), 18, (240, 240, 240), "mm")]))
    m.add_texture("+ACCCSLIDE", slide((256, 160), bg, mascot, (64, 8, 192, 96), [
        ("hlbox", (128, 118), 26, YELLOW, "mm"),
        ("maps as code", (128, 144), 14, (200, 200, 210), "mm")]))
    for t in ("+0CCCSLIDE", "+ACCCSLIDE"):
        m.texlight(t, (200, 200, 255), 250)


def access_card_texture():
    img = Image.new("RGB", (128, 80), (236, 238, 240))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 127, 20), fill=(24, 60, 140))
    d.text((64, 10), "BLACK MESA", fill=(255, 255, 255), font=font(13), anchor="mm")
    d.rectangle((8, 30, 34, 50), fill=(205, 170, 70), outline=(150, 120, 40))      # chip
    d.line((8, 40, 34, 40), fill=(150, 120, 40))
    d.line((21, 30, 21, 50), fill=(150, 120, 40))
    d.text((82, 38), "RECORDS", fill=(24, 60, 140), font=font(16), anchor="mm")
    d.text((82, 56), "ACCESS", fill=(60, 60, 70), font=font(12), anchor="mm")
    d.rectangle((0, 68, 127, 79), fill=YELLOW)
    return img


def portrait_texture():
    """Placeholder 'Employee of the Month' frame (the Codinator). Swap in a real photo
    you have permission to use: m.add_texture("PORTRAIT1", "assets/<photo>.png")."""
    mascot = pixel_svg(PROJECT_DIR / "assets" / "ccc_mascot.svg")
    img = Image.new("RGB", (128, 160), (22, 26, 38))
    d = ImageDraw.Draw(img)
    d.rectangle((6, 6, 121, 118), fill=(40, 46, 66))
    a = mascot.resize((mascot.width * 2, mascot.height * 2), Image.NEAREST)
    img.paste(a, ((128 - a.width) // 2, 6 + (112 - a.height) // 2), a)
    d.text((64, 132), "EMPLOYEE OF", fill=(230, 230, 235), font=font(12), anchor="mm")
    d.text((64, 148), "THE MONTH", fill=YELLOW, font=font(14), anchor="mm")
    return img


def build():
    m = Map("office")
    lvl = Level(wall=16)

    # --- rooms --------------------------------------------------------------------------
    conf = lvl.room("conference", (0, 0, 0), (448, 352, 160), CONFERENCE)
    hall = lvl.room("hall", (-160, -112, 0), (640, -16, 128), HALL)
    storage = lvl.room("storage", (-560, -176, 0), (-176, 144, 128), STORAGE)
    records = lvl.room("records", (656, -176, 0), (1040, 304, 256), RECORDS)
    basement = lvl.room("basement", (0, -96, -176), (448, 352, -16), BASEMENT)
    corridor = lvl.room("basement corridor", (-480, -96, -176), (-16, -16, -16), BASEMENT)

    conf_door = lvl.doorway(conf, hall, width=64, height=96, center=96)
    west_door = lvl.doorway(hall, storage, width=80, height=96, center=-64)
    east_door = lvl.doorway(hall, records, width=80, height=96, center=-64)
    lvl.doorway(basement, corridor, width=64, height=96, center=-56)
    down_steps, conf_hole = lvl.stairs("conference stairs", basement, conf, top=(408, 48), down="north")
    # comes up at the far (west) end of the storage room, well away from its door
    up_steps, store_hole = lvl.stairs("storage stairs", corridor, storage, top=(-480, -56), down="east")

    # the cave: a hole in the hall's south wall, a bend into Xen, and a side branch to a
    # radio camp where the records access card lies
    cave = lvl.tunnel(
        "cave", hall, "south", center=352, mouth=(96, 112),
        path=[(352, -250, -8), (362, -400, -24), (420, -525, -40), (560, -600, -48),
              (740, -610, -56), (900, -575, -56)],
        width=176, height=144, roughness=18, seed=11,
        materials=[(0.0, ROCK), (0.52, XEN)], blend=0.08,
        scale=lambda s: 1 + 0.5 * max(0.0, min(1.0, (s - 0.78) / 0.15)),   # end chamber
        branches=[{"at": 0.25, "path": [(270, -390, -22), (170, -430, -26), (80, -450, -28)],
                   "width": 144, "height": 128, "materials": [(0.0, ROCK)],
                   "scale": lambda s: 1 + 0.45 * max(0.0, min(1.0, (s - 0.55) / 0.3))}],
    )
    lvl.build(m)
    m.add(down_steps, up_steps)

    # --- doors & locks ----------------------------------------------------------------------
    m.add(props.door_rotating(conf_door, hinge="right"))
    for door, name in ((west_door, "storage_lock"), (east_door, "records_lock")):
        m.add(props.lock(name, door.center))
        m.add(props.door_rotating(door, hinge="left", texture="FIFTIES_DR5", edge="FIFTIES_DR5B", master=name))

    # --- hall ------------------------------------------------------------------------------
    m.texlight(LIGHT_TEX, (255, 248, 230), 3000)
    m.texlight(HALL_LIGHT_TEX, (255, 248, 230), 1600)
    for x in (-16, 240, 496):          # hall tiles are centred on the hall
        m.add(props.ceiling_light(x, -64, hall.ceiling, texture=HALL_LIGHT_TEX, name="hall_lights"))
    m.add(props.switch((-96, -16, 48), "south", "hall_lights"))     # outer wall only: +use goes through walls

    conference(m, conf, conf_hole)
    storage_room(m, storage, store_hole)
    records_room(m, records)
    basement_rooms(m, basement)
    cave_contents(m, cave)

    m.add(props.player_start(hall.floor_point(-120, -64), facing="east"))

    m.checkpoints = [("records upper level", (848, 208, 144)),
                     ("radio camp", cave.floor_point(0.85, branch=1))]
    m.cameras = {
        "conference": (420, 20, 72, 6, 125),
        "screen": (224, 70, 64, -12, 90),
        "screen_next": (224, 70, 64, -12, 90, ["slides"]),
        "conference_dark": (420, 20, 72, 6, 125, ["conference_lights"]),
        "stairs_down": (408, 10, 72, 45, 90),
        "basement": (40, -60, -112, 8, 40),
        "basement_stairs": (300, 330, -112, 12, 250),
        "corridor": (-40, -56, -112, 4, 180),
        "storage": (-208, -24, 80, 12, 170),
        "storage_door": (-520, -56, 72, 4, 0),
        "portrait": (300, 250, 64, -6, 60),
        "records": (680, -150, 72, -8, 45),
        "records_upper": (1000, 150, 212, 12, 195),
        "records_ladder": (960, -40, 72, -12, 80),
        "hall": (-120, -64, 64, 0, 0),
        "cave_branch": cave.camera(0.1, look_ahead=0.45, branch=1),
        "radio_camp": cave.camera(0.62, eye=76, look_ahead=0.23, branch=1),
        "radio_camp_taken": cave.camera(0.62, eye=76, look_ahead=0.23, branch=1) + (["records_card"],),
        "cave_xen": cave.camera(0.58, look_ahead=0.25),
        "records_unlocked": (560, -64, 64, 0, 0, ["records_lock_key", "@doors"]),
    }
    return m


# ---------------------------------------------------------------------------- rooms

def conference(m, conf, hole):
    slides(m)
    # table for eight
    m.add(props.table(224, 208, conf.floor, width=256, depth=80, height=30))
    for x in (128, 192, 256, 320):
        m.add(props.chair(x, 148, conf.floor, facing="north"), props.chair(x, 268, conf.floor, facing="south"))
    # screen on the north wall, projector hanging over the south end of the table
    lo, hi = (128, 348, 24), (320, 352, 144)
    m.add(props.screen(lo, hi, "south", "+0CCCSLIDE", name="slides"))
    m.add(props.projector((224, 120, 132), lo, hi, ceiling_z=conf.ceiling))
    remote = box((218, 172, 30), (230, 180, 32), "FIFTIES_DSK5B", comment="slide remote")
    remote.fit("top", "+0BUTTON2")
    m.add(props.Entity("func_button", brushes=[remote], target="slides", sounds=14, wait=0.5, spawnflags=1))
    # switchable ceiling panels on the tile grid, switch by the door (outer wall)
    for x, y in ((96, 96), (96, 256), (352, 256), (352, 96)):
        m.add(props.ceiling_light(x, y, conf.ceiling, name="conference_lights"))
    m.add(props.switch((0, 48, 48), "east", "conference_lights"))
    # railing around the stair hole (open on the south side, where the stairs start)
    (x0, y0, _), (x1, y1, _) = hole.mins, hole.maxs
    m.add(props.railing((x0, y0), (x0, y1), conf.floor, side="west"),
          props.railing((x0, y1), (x1, y1), conf.floor, side="north"))
    # walls: whiteboard, clock, pictures
    m.add(props.wall_art((0, 200, 80), "east", "FIFTIES_TBL1", 112, 56),
          props.wall_art((0, 300, 120), "east", "CLOCK1", 24, 24),
          props.wall_art((448, 300, 88), "west", "PICTURE0", 48, 36),
          props.wall_art((64, 352, 88), "south", "PICTURE10", 30, 40))
    m.add_texture("PORTRAIT1", portrait_texture())
    m.add(props.wall_art((384, 352, 88), "south", "PORTRAIT1", 36, 45, frame="FIFTIES_DSK1"))


def storage_room(m, storage, hole):
    x0, y0, z0 = storage.mins
    x1, y1, z1 = storage.maxs
    for x in (-496, -240):                 # tile centres (room centred at -368, -16)
        for y in (-96, 64):
            m.add(props.ceiling_light(x, y, z1))
    # stair hole railings (the stairs arrive at the west end, which stays open)
    (hx0, hy0, _), (hx1, hy1, _) = hole.mins, hole.maxs
    m.add(props.railing((hx0, hy1), (hx1, hy1), z0, side="north"),
          props.railing((hx0, hy0), (hx1, hy0), z0, side="south"),
          props.railing((hx1, hy0), (hx1, hy1), z0, side="east"))
    # the hallway door is locked; a release switch at the stair top opens it from inside
    m.add(props.switch((x0, -56, 48), "east", "storage_lock_key", texture="+0~LAB1_SW1", size=(16, 16)))
    # shelving with boxes along the north wall
    for x in (-520, -456, -392):
        m.add(props.detail(props.front_box(x, y1 - 12, z0, 60, 24, 96, "south", "CARDBOX1",
                                           sides="FIFTIES_DSK5B", repeat=(2, 3))))
    # crate stacks: north-east corner and along the south wall; the middle stays open
    for x, y, z, size, tex in [(-232, 110, 0, 64, "CRATE02"), (-232, 110, 64, 48, "BCRATE04"),
                               (-296, 114, 0, 56, "CRATE02B"), (-232, 46, 0, 48, "CRATE19"),
                               (-520, -140, 0, 64, "BCRATE09A"), (-450, -146, 0, 48, "CRATE25"),
                               (-386, -148, 0, 40, "CRATE02"), (-386, -148, 40, 32, "CRATE19")]:
        m.add(props.crate(x, y, z, size=size, texture=tex))
    for x, y, tex in [(-280, -150, "BARREL2"), (-246, -154, "BARREL3")]:
        m.add(props.barrel(x, y, z0, texture=tex))
    m.add(props.wall_art((x1, 90, 72), "west", "+0FUSEBOX", 24, 48))


def records_room(m, r):
    x0, y0, z0 = r.mins
    x1, y1, z1 = r.maxs
    mez_y, mez_z = 112, 128              # mezzanine over the north part, its floor at z 144
    upper = mez_z + 16
    m.add_world(box((x0, mez_y, mez_z), (x1, y1, upper),
                    {"top": "FIFTIES_FLR02C", "bottom": "FIFTIES_CEIL01", "default": "FIFTIES_DSK1"},
                    comment="mezzanine"))
    # a partition under the east end of the mezzanine edge carries the ladder
    m.add(props.detail(box((976, mez_y, z0), (x1, mez_y + 16, mez_z), "FIFTIES_WALL14A")))
    m.add(props.ladder((1008, mez_y, z0), upper, "north"))
    # railing along the edge, leaving 64 units open at the ladder (the player is 32 wide)
    m.add(props.railing((x0, mez_y), (976, mez_y), upper, side="north"))
    for x in (752, 880):                 # columns under the edge
        m.add(props.detail(box((x - 8, mez_y, z0), (x + 8, mez_y + 16, mez_z), "FIFTIES_DSK1")))
    # lights on the ceiling tile grid (centred on the room: x 848 +- 128, y 64 + 80k)
    for x in (720, 976):
        m.add(props.ceiling_light(x, -96, z1), props.ceiling_light(x, 64, z1),
              props.ceiling_light(x, 224, mez_z), props.ceiling_light(x, 224, z1))
    # ground floor: reception desk, filing cabinets, vending machine, computer banks,
    # reading table, bookshelves under the mezzanine, cardboard boxes, wall decor
    m.add(props.table(736, 16, z0, width=96, depth=40), props.chair(736, -16, z0, facing="north"))
    m.add(props.detail(props.front_box(712, 24, 34, 20, 16, 16, "south", "FIFTIES_MON3")))
    paper = box((748, 6, 34), (764, 26, 35), "PAPER4", comment="paper")
    paper.fit("top", "PAPER4")
    m.add(props.detail(paper))
    for i, x in enumerate(range(700, 924, 32)):
        m.add(props.filing_cabinet(x, y0 + 14, z0, "north", drawers=4 if i % 3 else 3))
    m.add(props.vending_machine(960, y0 + 16, z0, "north"))
    for yb, tex in ((-144, "FIFTIES_CMP1A"), (-48, "FIFTIES_CMP3A")):
        bank = box((x1 - 32, yb, z0), (x1, yb + 96, 128), "FIFTIES_CMP1B")
        bank.fit("west", tex)
        m.add(props.detail(bank))
    m.add(props.table(864, -40, z0, width=96, depth=48), props.chair(864, -84, z0, facing="north"),
          props.chair(864, 4, z0, facing="south"))
    for y in (152, 216, 280):
        m.add(props.bookshelf(x0 + 8, y, z0, "east", w=56, h=96, texture="PFAB_BKS1A" if y != 216 else "PFAB_BKS2A"))
    for x, y, z, s, t in [(800, 250, 0, 32, "CARDBOX1"), (832, 250, 0, 32, "CARDBOX2"),
                          (816, 250, 32, 32, "CARDBOX3"), (900, 270, 0, 40, "CARDBOX4")]:
        m.add(props.crate(x, y, z, size=s, texture=t))
    m.add(props.wall_art((x0, 40, 116), "east", "CLOCK1", 24, 24),
          props.wall_art((820, y0, 100), "north", "PICTURE4", 48, 36),
          props.wall_art((x1, 60, 190), "west", "PICTURE7", 64, 76))
    # upper level: server racks, archive shelves, a desk with a radio and a medkit
    for x, tex in ((720, "~LAB1_COMP7"), (824, "LAB1_COMP8"), (928, "~LAB1_COMP7")):
        m.add(props.detail(props.front_box(x, y1 - 16, upper, 96, 32, 96, "south", tex, sides="FIFTIES_CMP1B")))
    m.texlight("~LAB1_COMP7", (120, 200, 255), 150)
    for y in (160, 224):
        m.add(props.bookshelf(x0 + 8, y, upper, "east", w=56, h=80, texture="PFAB_BKS3A"))
    m.add(props.table(960, 200, upper, width=64, depth=40), props.chair(960, 164, upper, facing="north"))
    m.add(props.radio(946, 210, upper + 34, "south", texture="C1A1_GAD1", w=20, h=18))
    m.add(props.point("item_healthkit", (978, 200, upper + 40)))


def basement_rooms(m, b):
    x0, y0, z0 = b.mins
    x1, y1, z1 = b.maxs
    # boiler with pipes up into the ceiling, barrels, a workbench, crates, fuse box
    boiler = box((24, 256, z0), (120, 336, z0 + 96), "OUT_TNK1", comment="boiler")
    boiler.fit("south", "GENERIC_111D")
    m.add(props.detail(boiler))
    for x in (48, 96):
        m.add(props.pipe((x, 296, z0 + 96), (x, 296, z1), size=8, texture="GENERIC031"))
    m.add(props.pipe((72, 296, z1 - 12), (440, 296, z1 - 12), size=8, texture="GENERIC029"),
          props.pipe((-330, -24, z1 - 10), (440, -24, z1 - 10), size=6, texture="GENERIC030"))
    for x, y, tex in [(200, 320, "BARREL2"), (236, 326, "BARREL3"), (218, 290, "BARREL4")]:
        m.add(props.barrel(x, y, z0, texture=tex))
    m.add(props.table(220, 40, z0, width=112, depth=40, top="FIFTIES_DSK5B", legs="FIFTIES_DSK5B"))
    m.add(props.radio(200, 48, z0 + 34, "south", texture="C1A1_GAD4", w=18, h=24))
    m.add(props.wall_art((x0, 120, z0 + 64), "east", "+0FUSEBOX", 24, 48))
    for x, y, s, t in [(40, 200, 48, "CRATE02"), (40, 152, 40, "CRATE19"), (300, 180, 48, "CRATE25")]:
        m.add(props.crate(x, y, z0, size=s, texture=t))
    # bare bulbs: steady ones, and a flickering fluorescent by the boiler
    m.add(props.light((200, 160, z1 - 20), color=(255, 225, 170), brightness=240),
          props.light((120, 40, z1 - 20), color=(255, 225, 170), brightness=180),
          props.light((260, 290, z1 - 20), color=(255, 225, 170), brightness=170, style=10),
          props.light((150, -56, z1 - 20), color=(255, 225, 170), brightness=150),
          props.light((-80, -56, z1 - 20), color=(255, 225, 170), brightness=150),
          props.light((-250, -56, z1 - 20), color=(255, 225, 170), brightness=120))


def cave_contents(m, cave):
    # rock stretch: dim work lights
    m.add(props.light(cave.floor_point(0.12, above=110), color=(255, 205, 160), brightness=110))
    m.add(props.light(cave.floor_point(0.34, above=100), color=(255, 205, 160), brightness=70))

    # branch: the radio camp - a table with radio sets and the records access card, laid
    # out to face whoever walks in (i.e. against the branch's direction)
    (cx, cy, cz), t, _ = cave.frame(0.85, branch=1)
    face = props.compass(-t[0], -t[1])                  # toward the approaching player
    fx, fy = props.DIRS[face]
    ax, ay = abs(fy), abs(fx)                          # along the table's long side
    m.add(props.table(cx, cy, cz - 4, width=96 if fy else 48, depth=48 if fy else 96, height=38))
    top = cz - 4 + 38
    for k, (tex, w, h) in zip((-30, -4, 22), (("C1A1_GGT8", 24, 24), ("C1A1_GAD1", 22, 20), ("C1A1_GAD3", 18, 26))):
        m.add(props.radio(cx + ax * k - fx * 8, cy + ay * k - fy * 8, top, face, texture=tex, w=w, h=h))
    # the card: a visible prop on the table (custom texture) stands in for the item, whose
    # own model is hidden; picking the item up removes the prop from the table
    m.add_texture("ACCESSCARD", access_card_texture())
    card_at = (cx + ax * 30 + fx * 12, cy + ay * 30 + fy * 12)
    card_w, card_d = (16, 10) if fy else (10, 16)
    m.add(props.flat_prop((card_at[0], card_at[1], top), card_w, card_d, "ACCESSCARD", name="card_prop"))
    m.texlight("ACCESSCARD", (255, 255, 255), 40)
    m.add(props.pickup("item_security", (card_at[0], card_at[1], top + 8), fires=["records_lock_key"],
                       message="RECORDS ACCESS CARD ACQUIRED", name="records_card",
                       hide=["card_prop"], invisible=True))
    m.add(props.chair(cx - fx * 44, cy - fy * 44, cz - 2, facing=face))
    m.add(props.crate(cx - ax * 76, cy - ay * 76, cz - 4, size=40, texture="CRATE25"))
    m.add(props.light((cx + fx * 24, cy + fy * 24, cz + 80), color=(255, 190, 120), brightness=150, style=10))

    # Xen part
    m.texlight(CRYSTAL_TEX, (110, 255, 170), 600)
    for s, lat, name in [(0.68, 0.6, "xen_plant1"), (0.83, -0.6, "xen_plant2"), (0.95, 0.35, "xen_plant3")]:
        m.add(props.xen_plantlight(cave.floor_point(s, lat), name))
    for s, lat in [(0.6, -0.85), (0.64, 0.9), (0.73, -0.9), (0.9, 0.9), (0.97, -0.85)]:
        m.add(props.point("xen_hair", cave.floor_point(s, lat), facing=int(s * 997) % 360))
    for cls, s, lat in [("xen_spore_small", 0.7, -0.5), ("xen_spore_medium", 0.8, 0.85),
                        ("xen_spore_large", 0.88, -0.85), ("xen_spore_small", 0.85, 0.4)]:
        m.add(props.point(cls, cave.floor_point(s, lat), facing=int(s * 431) % 360))
    for k, (s, lat) in enumerate([(0.86, 0.95), (0.92, -0.95), (0.99, 0.55)]):
        base = cave.floor_point(s, lat)
        _, _, rt = cave.frame(s)
        lean = (-rt[0] * 28 * math.copysign(1, lat), -rt[1] * 28 * math.copysign(1, lat))
        m.add(props.crystal(base, height=88 + 12 * k, radius=12, lean=lean, seed=k))
    for s in (0.7, 0.9):
        m.add(props.light(cave.floor_point(s, above=90), color=(110, 255, 150), brightness=70))
    end, tangent, _ = cave.frame(0.97)
    m.add(props.point("xen_tree", end, facing=round(math.degrees(math.atan2(-tangent[1], -tangent[0]))) % 360))
    m.add(props.point("ambient_generic", cave.floor_point(0.8, above=64),
                      message="ambience/aliencave1.wav", health=6, spawnflags=4, pitch=100))
