"""A small office with a table and a chair; a door opens onto a hallway.

Layout (top view, +Y = north):

    +-----------------------------+
    |           office            |   office: x 0..320, y 0..240, ceiling 128
    |        [ table ]            |
    |          (chair)            |
    |                             |
    +-----------[door]------------+
    |           hallway                          |   hall: x -160..480, y -112..-16
    +--------------------------------------------+
"""
from hlmap import Map, Level, Material, props

OFFICE = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01",
                  floor_align="min", ceiling_align="min")
HALL = Material(floor="FIFTIES_FLR03", wall="FIFTIES_WALL14U", ceiling="FIFTIES_CEIL01",
                floor_align="center", ceiling_align="center")

LIGHT_TEX = "+0~FIFTS_LGHT01"      # office panel
HALL_LIGHT_TEX = "+0~FIFTS_LGHT06"  # same look, separate brightness (narrow hall needs less)

# default screenshot cameras: (x, y, z_eye, pitch, yaw)
CAMERAS = [
    (300, 20, 64, 8, 145),     # office, SE corner by the door, looking at the table
    (250, 200, 64, 12, 245),   # office, NE corner, looking back at the door
    (40, -104, 60, 0, 40),     # hallway, looking at the office door
]


def build():
    m = Map("office")
    lvl = Level(wall=16)

    office = lvl.room("office", (0, 0, 0), (320, 240, 128), OFFICE)
    hall = lvl.room("hall", (-160, -112, 0), (480, -16, 128), HALL)
    door = lvl.doorway(office, hall, width=64, height=96, center=160)
    lvl.build(m)

    # door: hinged on the west jamb as seen from inside the office
    m.add(props.door_rotating(door, hinge="right"))

    # furniture
    m.add(props.table(160, 168, office.floor, width=96, depth=48))
    m.add(props.chair(160, 124, office.floor, facing="north"))

    # lighting: fluorescent panels aligned to the 64x80 ceiling tile grid
    m.texlight(LIGHT_TEX, (255, 248, 230), 3000)
    m.texlight(HALL_LIGHT_TEX, (255, 248, 230), 1600)
    m.add(props.ceiling_light(160, 120, office.ceiling))
    for x in (-32, 160, 352):   # hall tiles are centered on the hall (x = 160 + 64k)
        m.add(props.ceiling_light(x, -64, hall.ceiling, texture=HALL_LIGHT_TEX))

    m.add(props.player_start(hall.floor_point(-100, -64), facing="east"))
    return m
