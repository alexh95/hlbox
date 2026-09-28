"""An office off a hallway. The hallway has a locked room at each end and a hole in its
south wall that opens into a cave. Past a bend, the cave turns into Xen.

Layout (top view, +Y = north):

                          +---------------------+
                          |       office        |  table, chair, light switch
                          +--------[door]-------+
    +---------+-----------------------------------------------+---------+
    | storage |[locked]             hallway           [locked]| records |
    +---------+-------------------------------[cave]----------+---------+
                                                |
                                                 \\___ rock ___ Xen ___ chamber
"""
import math

from hlmap import Level, Map, Material, box, props
from hlmap.cave import ROCK

OFFICE = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01",
                  floor_align="min", ceiling_align="min")
HALL = Material(floor="FIFTIES_FLR03", wall="FIFTIES_WALL14U", ceiling="FIFTIES_CEIL01",
                floor_align="center", ceiling_align="center")
STORAGE = Material(floor="C1A1_FLR2B", wall="FIFTIES_WALL12B", ceiling="FIFTIES_CEIL01",
                   ceiling_align="center")
RECORDS = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14A", ceiling="FIFTIES_CEIL01",
                   ceiling_align="center")
XEN = Material(floor="-0XENO_2WA", wall="-0XENO_2W1", ceiling="-0XENO_2W1")

LIGHT_TEX = "+0~FIFTS_LGHT01"       # office + side rooms
HALL_LIGHT_TEX = "+0~FIFTS_LGHT06"  # same look, separate brightness (narrow hall needs less)
CRYSTAL_TEX = "CRYS_2A"


def build():
    m = Map("office")
    lvl = Level(wall=16)

    office = lvl.room("office", (0, 0, 0), (320, 240, 128), OFFICE)
    hall = lvl.room("hall", (-160, -112, 0), (480, -16, 128), HALL)
    storage = lvl.room("storage", (-400, -176, 0), (-176, 48, 128), STORAGE)
    records = lvl.room("records", (496, -176, 0), (720, 48, 128), RECORDS)

    office_door = lvl.doorway(office, hall, width=64, height=96, center=160)
    west_door = lvl.doorway(hall, storage, width=80, height=96, center=-64)
    east_door = lvl.doorway(hall, records, width=80, height=96, center=-64)

    # the cave: a hole in the hall's south wall, a gentle downhill bend, then Xen
    cave = lvl.tunnel(
        "cave", hall, "south", center=352, mouth=(96, 112),
        path=[(352, -250, -8), (362, -400, -24), (420, -525, -40), (560, -600, -48),
              (740, -610, -56), (900, -575, -56)],
        width=176, height=144, roughness=18, seed=11,
        materials=[(0.0, ROCK), (0.52, XEN)], blend=0.08,
        scale=lambda s: 1 + 0.5 * max(0.0, min(1.0, (s - 0.78) / 0.15)),   # end chamber
    )
    lvl.build(m)

    # --- doors: the office door opens; the two end doors are locked ------------------
    m.add(props.door_rotating(office_door, hinge="right"))
    for door, name in ((west_door, "storage_lock"), (east_door, "records_lock")):
        m.add(props.lock(name, door.center))
        m.add(props.door_rotating(door, hinge="left", texture="FIFTIES_DR5", edge="FIFTIES_DR5B",
                                  master=name))

    # --- office ----------------------------------------------------------------------
    m.add(props.table(160, 168, office.floor, width=96, depth=48))
    m.add(props.chair(160, 124, office.floor, facing="north"))

    # --- lights + switches -----------------------------------------------------------
    m.texlight(LIGHT_TEX, (255, 248, 230), 3000)
    m.texlight(HALL_LIGHT_TEX, (255, 248, 230), 1600)
    m.add(props.ceiling_light(160, 120, office.ceiling, name="office_lights"))
    for x in (-32, 160, 352):   # hall tiles are centred on the hall (x = 160 + 64k)
        m.add(props.ceiling_light(x, -64, hall.ceiling, texture=HALL_LIGHT_TEX, name="hall_lights"))
    # +use reaches 64 units THROUGH walls, so switches never go on a wall shared with
    # another room: office switch on the office's outer west wall, hall switch on the
    # hall's north wall west of the office (nothing behind it), by the player start
    m.add(props.switch((0, 48, 48), "east", "office_lights"))
    m.add(props.switch((-96, -16, 48), "south", "hall_lights"))

    # --- storage: stacked crates ------------------------------------------------------
    m.add(props.ceiling_light(*storage.center[:2], storage.ceiling))
    sx, sy, _ = storage.mins
    for dx, dy, z, size, tex in [(40, 40, 0, 64, "CRATE02"), (104, 40, 0, 64, "CRATE02B"),
                                 (40, 40, 64, 48, "BCRATE04"), (40, 184, 0, 64, "BCRATE09A"),
                                 (184, 188, 0, 48, "CRATE19"), (180, 36, 0, 56, "CRATE25")]:
        m.add(props.crate(sx + dx, sy + dy, z, size=size, texture=tex))

    # --- records: computer banks along the east wall, a desk ---------------------------
    m.add(props.ceiling_light(*records.center[:2], records.ceiling))
    ex = records.maxs[0]
    for y0, tex in ((-160, "FIFTIES_CMP1A"), (-64, "FIFTIES_CMP3A")):
        bank = box((ex - 32, y0, 0), (ex, y0 + 96, 128), "FIFTIES_CMP1B")
        bank.fit("west", tex)
        m.add(props.detail(bank))
    m.add(props.table(580, 0, records.floor, width=96, depth=48))
    m.add(props.chair(580, -44, records.floor, facing="north"))

    # --- cave: dim work light in the rock part, Xen life after the bend ----------------
    m.add(props.light(cave.floor_point(0.12, above=110), color=(255, 205, 160), brightness=110))
    m.add(props.light(cave.floor_point(0.34, above=100), color=(255, 205, 160), brightness=70))

    m.texlight(CRYSTAL_TEX, (110, 255, 170), 600)
    for i, (s, lat, name) in enumerate([(0.68, 0.6, "xen_plant1"), (0.83, -0.6, "xen_plant2"),
                                        (0.95, 0.35, "xen_plant3")]):
        m.add(props.xen_plantlight(cave.floor_point(s, lat), name))
    for s, lat in [(0.6, -0.85), (0.64, 0.9), (0.73, -0.9), (0.9, 0.9), (0.97, -0.85)]:   # hug the walls
        m.add(props.point("xen_hair", cave.floor_point(s, lat), facing=int(s * 997) % 360))
    for cls, s, lat in [("xen_spore_small", 0.7, -0.5), ("xen_spore_medium", 0.8, 0.85),
                        ("xen_spore_large", 0.88, -0.85), ("xen_spore_small", 0.85, 0.4)]:
        m.add(props.point(cls, cave.floor_point(s, lat), facing=int(s * 431) % 360))
    for k, (s, lat) in enumerate([(0.86, 0.95), (0.92, -0.95), (0.99, 0.55)]):
        base = cave.floor_point(s, lat)
        _, _, right = cave.frame(s)
        lean = (-right[0] * 28 * math.copysign(1, lat), -right[1] * 28 * math.copysign(1, lat))
        m.add(props.crystal(base, height=88 + 12 * k, radius=12, lean=lean, seed=k))
    for s in (0.7, 0.9):
        m.add(props.light(cave.floor_point(s, above=90), color=(110, 255, 150), brightness=70))
    end, tangent, _ = cave.frame(0.97)
    m.add(props.point("xen_tree", end, facing=round(math.degrees(math.atan2(-tangent[1], -tangent[0]))) % 360))
    m.add(props.point("ambient_generic", cave.floor_point(0.8, above=64),
                      message="ambience/aliencave1.wav", health=6, spawnflags=4, pitch=100))

    m.add(props.player_start(hall.floor_point(-100, -64), facing="east"))

    # named screenshot cameras: (x, y, z_eye, pitch, yaw[, things to fire first])
    m.cameras = {
        "office": (300, 20, 64, 8, 145),
        "office_switch": (200, 120, 64, 8, 180),
        "office_dark": (300, 20, 64, 8, 145, ["office_lights"]),
        "hall_doors": (300, -64, 64, 0, 180, ["@doors"]),      # office door opens, storage stays locked
        "storage_unlocked": (40, -64, 64, 0, 180, ["storage_lock_key", "@doors"]),
        "hall_east": (40, -40, 64, 4, -12),
        "hall_switch": (40, -90, 64, 4, 160),
        "hall_dark": (40, -40, 64, 4, -12, ["hall_lights"]),
        "cave_mouth": (330, -40, 60, 18, -75),
        "cave_rock": cave.camera(0.1, look_ahead=0.2),
        "cave_bend": cave.camera(0.4, look_ahead=0.15),
        "cave_xen": cave.camera(0.58, look_ahead=0.25),
        "chamber": cave.camera(0.68, eye=80, look_ahead=0.28),
        "storage": (-196, -40, 72, 12, 215),
        "records": (512, 32, 72, 10, -40),
    }
    return m
