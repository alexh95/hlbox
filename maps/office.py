"""Black-Mesa-ish office block over a basement, with a cave that turns into Xen.

Top view (+Y = north), ground floor:

      cafeteria
          \\  corridor at 45 degrees (cuts the storage room's corner)
           \\   +--------------------------------+
            |  |  conference room               |  table for 8, projector + screen
            |  |  (briefing)              [stairs down]
    +---------+------[door]------------------+-+--------------+
    | storage |[locked]      hallway          [locked]| records   |  two levels,
    |  (stairs up from basement)       [cave]         | mezzanine |  ladder up
    +---------+--------------------------------+------+-----------+
                                             |
                          radio camp <-- branch  \\___ rock ___ Xen ___ chamber
                          (access card: opens records)

Basement (z -176): under the conference room, a corridor west under the hallway, and
stairs up into the storage room. The storage door opens from inside (release switch).

The briefing: walking into the conference room starts a talk. A scientist presents 12
slides (starring Boxworth, the facility's crate mascot) with synthesized voice lines and
subtitles; the last one says where the card is. Come back after fixing the power and
he has a word about that too.

Power: taking the access card at the radio camp shorts the radios and trips the main
breaker. Every light on the mains goes out, the projector dies, red emergency lamps
pulse along the way back, and the records door (card AND power) stays shut until the
breaker in the basement is reset. Light switches are dead while the power is out.
"""
import math

from hlmap import Level, Map, Material, box, logic, props, scene, voice
from PIL import Image, ImageDraw

from hlmap.art import DECK, bullets, deck_slide, font, plate, slide, waveform
from hlmap.cave import ROCK

CONFERENCE = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14U", ceiling="FIFTIES_CEIL01",
                      ceiling_align="center")
HALL = Material(floor="FIFTIES_FLR03", wall="FIFTIES_WALL14", ceiling="FIFTIES_CEIL01",
                floor_align="center", ceiling_align="center")
STORAGE = Material(floor="C1A1_FLR2B", wall="FIFTIES_WALL12B", ceiling="FIFTIES_CEIL01", ceiling_align="center")
RECORDS = Material(floor="FIFTIES_FLR02C", wall="FIFTIES_WALL14A", ceiling="FIFTIES_CEIL01", ceiling_align="center")
BASEMENT = Material(floor="CRETE2_FLR01", wall="CRETE4_WALL01", ceiling="CRETE3_CEIL01")
CAFETERIA = Material(floor="FIFTIES_FLR5", wall="FIFTIES_W13", ceiling="FIFTIES_CEIL01",
                     floor_align="min", ceiling_align="center")
XEN = Material(floor="-0XENO_2WA", wall="-0XENO_2W1", ceiling="-0XENO_2W1")

LIGHT_TEX = "+0~FIFTS_LGHT01"       # office-type rooms
HALL_LIGHT_TEX = "+0~FIFTS_LGHT06"  # same look, dimmer (narrow hall)
CRYSTAL_TEX = "CRYS_2A"
YELLOW = (255, 220, 0)
SCREEN_LO, SCREEN_HI = (128, 348, 24), (320, 352, 144)   # conference projection screen


# ---------------------------------------------------------------------------- the briefing

FOOT = "hlbox  \u00b7  quarterly briefing"
WHITE = DECK["text"]
DIM = DECK["dim"]


def talk_lines(stats):
    """(subtitle, what the voice says if different, gesture) for each slide."""
    return [
        ("Ah, good, you made it. Please, have a seat. Welcome to this quarter's facility construction "
         "briefing.", None, "wave"),
        ("Today's subject is hlbox, and its mascot, Boxworth. He insisted on the hard hat. We no longer "
         "build our test facilities by hand. We describe them in code, and the code builds them.",
         "Today's subject is H L box, and its mascot, Boxworth. He insisted on the hard hat. We no longer "
         "build our test facilities by hand. We describe them in code, and the code builds them.", "converse1"),
        ("Why code? A script can be rebuilt in seconds, reviewed like any other program, and edited by "
         "our... automated colleague.", None, "pondering2"),
        ("Rule number one: describe the air, not the walls. You say where the rooms are, and it seals the "
         "walls around them. No leaks.", None, "converse2"),
        ("The caves are grown along a path, as columns of rock. Watertight, by construction. The first "
         "version had holes. We do not discuss the first version.", None, "eye_wipe"),
        ("Every compiled map is checked, region by region. If you could walk through a wall, or bump into "
         "thin air, the build is rejected.", None, "no"),
        ("Then the tool plays the map by itself. Every key, every button, in every order. If any order would "
         "lock you out, we know before you do.", None, "converse1"),
        ("It even checks the lighting. Should the power ever fail, the way to the breaker must stay "
         "visible. Not that it would ever fail. Of course.", None, "checktie"),
        ("Every sign in this building, and every slide you are looking at, was drawn by a script and "
         "packed into the map itself.", None, "converse2"),
        ("And yes, this voice was synthesized when the map was built. Please don't stare at my lips. They "
         "are not involved.", None, "quicklook"),
        (f"By the numbers: over {stats['brushes']:,} brushes, over {stats['entities']} entities, "
         f"{stats['lines']} voice lines, and zero holes. The numbers speak for themselves. Well. I speak "
         "for them.", None, "yes"),
        ("That concludes the briefing. The records access card was left at the survey camp, in the cave off "
         "the hallway. Do try not to touch anything else down there.", None, "wave"),
    ]


INTERRUPTION = ("Hm? The lights... Oh, no. Not again.", None, "startle")

# walking back in once the power is restored: after the briefing, or before it
BACK_AFTER = [
    ("Ah, you're back. And so are the lights. I assume that was you, down in the basement. Splendid work.",
     None, "yes"),
    ("The records door needs power as well as your card, so it should open now. And please, do mind the "
     "crystals down there. They are not for licking.", None, "converse1"),
]
BACK_BEFORE = [
    ("Ah, the lights are back! That must have been you. Splendid.", None, "wave"),
    ("Now that we have power again, please, have a seat. You clearly found the card already, but "
     "attendance at the briefing is mandatory.", None, "converse2"),
]


def deck(stats, clip):
    """The 12 slides (384x240). `clip` is a voice clip to draw as a waveform."""
    mascot = boxworth()
    bg, n, out = DECK["bg"], 12, []
    # 1: title
    img = slide((384, 240), bg, mascot, (18, 30, 178, 206), [
        ("QUARTERLY", (282, 90), 34, YELLOW, "mm"), ("BRIEFING", (282, 128), 34, YELLOW, "mm"),
        ("facility construction", (282, 168), 15, WHITE, "mm")])
    ImageDraw.Draw(img).text((282, 196), "attendance: mandatory", fill=DIM, font=font(12, bold=False), anchor="mm")
    out.append(img)
    # 2: the subject, and its mascot
    img = slide((384, 240), bg, mascot, (132, 10, 252, 134), [
        ("hlbox", (192, 164), 40, YELLOW, "mm"), ("maps as code", (192, 198), 20, (200, 200, 210), "mm")])
    ImageDraw.Draw(img).text((192, 222), "mascot: Boxworth (hard hat his own idea)", fill=DIM,
                             font=font(11, bold=False), anchor="mm")
    out.append(img)
    # 3: why code
    img, d = deck_slide("WHY CODE?", 3, n, footer=FOOT)
    bullets(d, [("The script is the map", "rooms, props, lights and logic in one Python file"),
                ("Rebuilt in seconds", "compile, verify, install, screenshot"),
                ("Reviewed like any program", "diffs, tests, history"),
                ("Edited by your AI colleague", None)], y=58, gap=38)
    out.append(img)
    # 4: describe the air
    img, d = deck_slide("DESCRIBE THE AIR", 4, n, footer=FOOT)
    wall = (118, 124, 142)
    d.rectangle((24, 62, 232, 206), fill=wall)
    for r in ((40, 78, 128, 190), (144, 78, 216, 142), (128, 98, 144, 126)):   # rooms, doorway
        d.rectangle(r, fill=bg)
    d.text((84, 134), "AIR", fill=WHITE, font=font(15), anchor="mm")
    d.text((180, 110), "AIR", fill=WHITE, font=font(15), anchor="mm")
    y = 70
    for k, v in (("you:", "rooms, doorways"), ("tool:", "walls, sealed"), ("leaks:", "impossible")):
        d.text((248, y), k, fill=DIM, font=font(13, bold=False))
        d.text((248, y + 16), v, fill=WHITE, font=font(16))
        y += 46
    out.append(img)
    # 5: caves
    img, d = deck_slide("CAVES", 5, n, footer=FOOT)
    rock, seam = (104, 76, 56), (60, 42, 30)
    d.rectangle((24, 58, 360, 186), fill=rock)
    xs = [24 + i * 24 for i in range(15)]
    top = [96 + 10 * math.sin(i * 0.6 + 1) + 5 * math.sin(i * 1.7) for i in range(15)]
    bot = [162 - 9 * math.sin(i * 0.5) - 5 * math.sin(i * 2.1) for i in range(15)]
    d.polygon(list(zip(xs, top)) + list(zip(xs, bot))[::-1], fill=bg)
    for i, x in enumerate(xs):                       # the columns, and their triangle split
        d.line((x, 58, x, top[i]), fill=seam)
        d.line((x, bot[i], x, 186), fill=seam)
        if i + 1 < len(xs):
            d.line((x, 58, xs[i + 1], top[i + 1]), fill=seam)
            d.line((x, bot[i], xs[i + 1], 186), fill=seam)
    d.text((192, 197), "columns of rock on a grid  \u00b7  watertight", fill=WHITE, font=font(14), anchor="mm")
    d.text((352, 130), "(v1 had holes)", fill=DIM, font=font(11, bold=False), anchor="rm")
    out.append(img)
    # 6: collision
    img, d = deck_slide("BULLETPROOF COLLISION", 6, n, footer=FOOT)
    for i, (h, what) in enumerate((("HULL 0", "sight, bullets"), ("HULL 1", "standing"), ("HULL 3", "crouching"))):
        x = 26 + i * 114
        d.rectangle((x, 62, x + 102, 164), outline=(90, 96, 120), width=2)
        d.text((x + 51, 84), h, fill=YELLOW, font=font(17), anchor="mm")
        d.text((x + 51, 106), what, fill=DIM, font=font(12, bold=False), anchor="mm")
        d.line((x + 34, 136, x + 46, 148, x + 70, 122), fill=(90, 220, 110), width=5)
    d.text((192, 190), "0 holes  \u00b7  0 invisible walls  \u00b7  every face", fill=WHITE, font=font(15),
           anchor="mm")
    out.append(img)
    # 7: plays it first
    img, d = deck_slide("PLAY IT FIRST", 7, n, footer=FOOT)
    steps = ["CARD", "POWER\nOFF", "BREAKER", "RECORDS\nOPEN"]
    for i, t in enumerate(steps):
        x = 19 + i * 90
        d.rounded_rectangle((x, 80, x + 76, 136), radius=8, outline=YELLOW, width=2)
        d.multiline_text((x + 38, 108), t, fill=WHITE, font=font(13), anchor="mm", align="center")
        if i < 3:
            d.line((x + 78, 108, x + 88, 108), fill=YELLOW, width=2)
            d.polygon([(x + 89, 108), (x + 84, 104), (x + 84, 112)], fill=YELLOW)
    d.text((192, 164), "every key, every button, every order", fill=WHITE, font=font(15), anchor="mm")
    d.text((192, 188), "lockouts found before anyone plays", fill=DIM, font=font(13, bold=False), anchor="mm")
    out.append(img)
    # 8: lights out
    img, d = deck_slide("LIGHTS OUT", 8, n, footer=FOOT)
    d.rectangle((30, 66, 94, 190), fill=(150, 158, 176))
    d.rectangle((30, 66, 94, 84), fill=YELLOW)
    d.rectangle((56, 100, 68, 170), fill=(28, 30, 36))
    d.rectangle((52, 150, 72, 168), fill=(178, 24, 20))
    for i in range(5):
        x, y = 140 + i * 44, 92
        red = i in (1, 3)
        if red:
            d.ellipse((x - 20, y - 20, x + 20, y + 20), fill=(90, 14, 10))
        d.ellipse((x - 11, y - 11, x + 11, y + 11), fill=(236, 40, 24) if red else (60, 62, 70))
    d.text((230, 142), "power fails: red lamps", fill=WHITE, font=font(15), anchor="mm")
    d.text((230, 164), "verify: the way to the", fill=DIM, font=font(13, bold=False), anchor="mm")
    d.text((230, 182), "breaker stays lit", fill=DIM, font=font(13, bold=False), anchor="mm")
    out.append(img)
    # 9: signs and slides
    img, d = deck_slide("SIGNS & SLIDES", 9, n, footer=FOOT)
    y = 60
    for text, size, style in (("RECORDS", (64, 16), "red"), ("STORAGE", (56, 14), "brass"),
                              ("CONFERENCE", (64, 16), "steel"), ("MAIN BREAKER", (56, 14), "warning")):
        p = plate(text, size, style).resize((size[0] * 2, size[1] * 2), Image.LANCZOS)
        img.paste(p, (24, y))
        y += size[1] * 2 + 8
    img.paste(poster_texture().resize((80, 120), Image.LANCZOS), (176, 62))    # the hall poster
    d.text((318, 90), "drawn", fill=WHITE, font=font(15), anchor="mm")
    d.text((318, 110), "by a script", fill=WHITE, font=font(15), anchor="mm")
    d.text((318, 142), "packed into", fill=DIM, font=font(13, bold=False), anchor="mm")
    d.text((318, 160), "the map", fill=DIM, font=font(13, bold=False), anchor="mm")
    out.append(img)
    # 10: this voice (its real waveform)
    img, d = deck_slide("THIS VOICE", 10, n, footer=FOOT)
    waveform(d, voice.samples(clip), (24, 66, 360, 158), YELLOW)
    d.text((192, 176), "synthesized when the map was built", fill=WHITE, font=font(15), anchor="mm")
    d.text((192, 198), "lips: not involved", fill=DIM, font=font(13, bold=False), anchor="mm")
    out.append(img)
    # 11: numbers
    img, d = deck_slide("BY THE NUMBERS", 11, n, footer=FOOT)
    for i, (v, label) in enumerate(((f"{stats['brushes']:,}+", "brushes"), (f"{stats['entities']}+", "entities"),
                                    (str(stats["textures"]), "textures"), (str(stats["lines"]), "voice lines"))):
        x, y = 100 + (i % 2) * 184, 82 + (i // 2) * 62
        d.text((x, y), v, fill=YELLOW, font=font(30), anchor="mm")
        d.text((x, y + 24), label, fill=DIM, font=font(13, bold=False), anchor="mm")
    d.text((192, 202), "holes: 0", fill=WHITE, font=font(18), anchor="mm")
    out.append(img)
    # 12: questions
    img = slide((384, 240), bg, mascot, (14, 40, 150, 200), [("QUESTIONS?", (262, 70), 30, YELLOW, "mm")])
    d = ImageDraw.Draw(img)
    for i, t in enumerate(("The records access card:", "survey camp, in the cave", "off the hallway.")):
        d.text((262, 118 + i * 22), t, fill=WHITE if i else DIM, font=font(15, bold=bool(i)), anchor="mm")
    d.text((366, 226), f"{n} / {n}", fill=DIM, font=font(11, bold=False), anchor="rm")
    out.append(img)
    return out


def presentation(m, grid, screen_lo, screen_hi):
    """The scientist's talk: slides, voice lines, subtitles, gestures, and what the
    power does to it. Called last in build(), so its numbers count everything else."""
    stats = {"brushes": sum(len(e.brushes) for e in m.all_entities()) // 100 * 100,
             "entities": len(m.entities) // 50 * 50, "textures": len(m.textures_used()),
             "lines": len(talk_lines({"brushes": 0, "entities": 0, "lines": 0})) + 1 + len(BACK_AFTER) + len(BACK_BEFORE)}
    lines = talk_lines(stats)
    head = (400, 296, 66)
    talk = scene.Talk(m, "talk", head, actor="presenter", rate=-1, actor_model="models/scientist.mdl")
    clip = voice.synthesize({"w": lines[9][1] or lines[9][0]}, talk.cache_dir, talk.voice, talk.rate)["w"]
    names = []
    for k, img in enumerate(deck(stats, clip), 1):
        names.append(m.add_texture(f"HLB_SLIDE{k:02d}", img))
    m.add(props.slideshow("slides", screen_lo, screen_hi, "south", names))
    for k, (text, say, gesture) in enumerate(lines, 1):
        talk.line(text, say=say, gesture=gesture, fire=[f"slides_step{k - 1}"] if k > 1 else [])
    talk.interrupt(INTERRUPTION[0], gesture=INTERRUPTION[2])
    # the remote works once the talk is over (or cut short) and while there's power
    talk.on_end.append("slides_remote_key")
    m.add(props.lock("slides_remote", (224, 176, 40), globalstate=grid.flag.state))
    remote = box((218, 172, 30), (230, 180, 32), "FIFTIES_DSK5B", comment="slide remote")
    remote.fit("top", "+0BUTTON2")
    m.add(props.Entity("func_button", brushes=[remote], target="slides_next", sounds=14, wait=0.5, spawnflags=1,
                       master="slides_remote"))
    # the presenter: pre-disaster (won't follow), gagged (no stock idle chatter)
    m.add(props.point("monster_scientist", (head[0], head[1], 0), facing=207, targetname="presenter", body=1,
                      spawnflags=2 | 256))
    # Walking in (with power), by the door or up the basement stairs:
    #   - first visit, power never failed: the briefing
    #   - power restored, briefing given (or cut short): welcome back, the records door
    #   - power restored, no briefing yet: welcome back, then the briefing anyway
    brief_pending = logic.Flag("brief_pending", True, head)
    back_pending = logic.Flag("back_pending", True, head)
    restored = logic.Flag("power_restored", False, head)
    grid.on_restore(restored.on, 0)
    talk.on_start.append(brief_pending.off)
    m.add(talk.entities())
    backs = {}
    for key, lines_ in (("back_after", BACK_AFTER), ("back_before", BACK_BEFORE)):
        t = scene.Talk(m, key, head, actor="presenter", rate=-1, actor_model="models/scientist.mdl")
        for text, say, gesture in lines_:
            t.line(text, say=say, gesture=gesture)
        t.on_start.append(back_pending.off)
        backs[key] = t
    backs["back_before"].on_end.append(talk.start)
    for t in backs.values():
        m.add(t.entities())
        grid.on_fail(t.abort, 0.5)
    m.add(brief_pending.entities(), back_pending.entities(), restored.entities())
    m.add(logic.when("enter_brief", talk.start, [brief_pending.is_on, restored.is_off], head),
          logic.when("enter_back_after", backs["back_after"].start,
                     [back_pending.is_on, restored.is_on, brief_pending.is_off, talk.running.is_off], head),
          logic.when("enter_back_before", backs["back_before"].start,
                     [back_pending.is_on, restored.is_on, brief_pending.is_on], head),
          logic.sequence("conf_enter", [("enter_brief", 0), ("enter_back_after", 0), ("enter_back_before", 0)],
                         head))
    m.add(props.trigger((8, 8, 0), (440, 344, 100), "conf_enter", once=False, master=grid.live, wait=1))
    grid.on_fail(talk.abort, 0.5)
    m.talk, m.backs = talk, backs
    return talk


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


def boxworth():
    """Boxworth, the facility's mascot: a supply crate with boots and a hard hat, as
    32x32 pixel art (transparent; scale it up with NEAREST)."""
    img = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ink, wood, light, seam = (58, 36, 18), (184, 126, 62), (214, 160, 92), (146, 98, 46)
    d.rectangle((4, 18, 5, 22), fill=wood, outline=ink)                  # arms
    d.rectangle((26, 16, 27, 20), fill=wood, outline=ink)
    d.rectangle((8, 27, 12, 30), fill=(52, 54, 62), outline=ink)         # boots
    d.rectangle((19, 27, 23, 30), fill=(52, 54, 62), outline=ink)
    d.rectangle((6, 11, 25, 28), fill=wood, outline=ink)                 # the crate
    d.rectangle((7, 12, 24, 27), outline=light)
    for x in (12, 19):                                                   # plank seams
        d.line((x, 13, x, 26), fill=seam)
    for x, y in ((7, 12), (23, 12), (7, 26), (23, 26)):                  # corner brackets
        d.rectangle((x, y, x + 1, y + 1), fill=(120, 124, 132))
    d.rectangle((9, 15, 13, 19), fill=(246, 246, 240), outline=ink)      # eyes
    d.rectangle((18, 15, 22, 19), fill=(246, 246, 240), outline=ink)
    d.rectangle((11, 16, 12, 18), fill=ink)
    d.rectangle((20, 16, 21, 18), fill=ink)
    d.point([(10, 16), (19, 16)], fill=(255, 255, 255))
    d.rectangle((8, 21, 9, 21), fill=(232, 124, 110))                    # cheeks
    d.rectangle((22, 21, 23, 21), fill=(232, 124, 110))
    d.line((13, 22, 18, 22), fill=ink)                                   # smile
    d.point([(12, 21), (19, 21)], fill=ink)
    d.pieslice((8, 2, 23, 16), 180, 360, fill=(255, 204, 0), outline=ink)   # hard hat
    d.rectangle((5, 9, 26, 11), fill=(232, 170, 0), outline=ink)
    d.line((15, 3, 15, 8), fill=(255, 232, 110))
    return img


def portrait_texture():
    """'Employee of the Month': Gerald, the ficus from Facilities, in his tie. Or swap
    in a real photo you have permission to use: m.add_texture("PORTRAIT1", path)."""
    img = Image.new("RGB", (128, 160), (22, 26, 38))
    d = ImageDraw.Draw(img)
    for y in range(6, 119):                                               # studio backdrop
        t = (y - 6) / 112
        d.line((6, y, 121, y), fill=(round(70 + 40 * t), round(96 + 30 * t), round(140 + 20 * t)))
    leaf, dark = (74, 160, 70), (40, 110, 48)
    d.line((64, 96, 64, 52), fill=(92, 64, 36), width=3)                  # trunk
    for x, y, r in ((64, 40, 18), (44, 54, 14), (84, 54, 14), (52, 30, 11), (78, 30, 11), (64, 66, 12),
                    (40, 72, 9), (88, 72, 9)):
        d.ellipse((x - r, y - r, x + r, y + r), fill=leaf, outline=dark)
    for x, y in ((58, 36), (72, 46), (48, 58), (80, 56), (66, 24)):       # leaf veins
        d.line((x - 4, y + 3, x + 4, y - 3), fill=dark)
    d.polygon([(42, 92), (86, 92), (80, 118), (48, 118)], fill=(190, 96, 54), outline=(120, 54, 28))
    d.rectangle((40, 88, 88, 94), fill=(206, 110, 64), outline=(120, 54, 28))    # pot rim
    d.ellipse((50, 98, 55, 103), fill=(30, 20, 16))                       # a face on the pot
    d.ellipse((73, 98, 78, 103), fill=(30, 20, 16))
    d.point([(51, 99), (74, 99)], fill=(255, 255, 255))
    d.polygon([(62, 94), (66, 94), (68, 112), (64, 117), (60, 112)], fill=(200, 30, 36))   # the tie
    d.text((64, 127), "EMPLOYEE OF THE MONTH", fill=(230, 230, 235), font=font(8), anchor="mm")
    d.text((64, 142), "GERALD", fill=YELLOW, font=font(15), anchor="mm")
    d.text((64, 155), "facilities  ·  37 months", fill=(150, 156, 176), font=font(9, bold=False), anchor="mm")
    return img


def poster_texture():
    """A safety poster for the hall (the survey cave has crystals)."""
    img = Image.new("RGB", (128, 192), (24, 28, 36))
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 127, 26), fill=(246, 204, 24))
    d.text((64, 13), "SAFETY NOTICE", fill=(20, 20, 20), font=font(14), anchor="mm")
    glow, face, edge = (40, 90, 60), (120, 255, 170), (40, 150, 90)
    d.ellipse((24, 40, 104, 120), fill=glow)
    for pts in ([(50, 110), (46, 70), (56, 50), (64, 72), (62, 110)],          # a crystal cluster
                [(62, 110), (66, 64), (78, 42), (86, 66), (80, 110)],
                [(78, 110), (84, 84), (94, 74), (96, 92), (90, 110)]):
        d.polygon(pts, fill=face, outline=edge)
        d.line((pts[1], pts[3]), fill=(200, 255, 220))
    d.ellipse((22, 38, 106, 122), outline=(226, 36, 30), width=7)          # "no"
    d.line((36, 52, 92, 108), fill=(226, 36, 30), width=7)
    for i, (t, sz) in enumerate((("PLEASE", 13), ("DO NOT LICK", 16), ("THE SAMPLES", 16))):
        d.text((64, 138 + i * 16), t, fill=(240, 240, 240) if i else (190, 196, 210), font=font(sz), anchor="mm")
    d.text((64, 184), "Anomalous Materials", fill=(140, 146, 166), font=font(9, bold=False), anchor="mm")
    return img


def breaker_textures():
    """The main breaker's panel (with the slot its handle travels in) and handle."""
    panel = plate("", (40, 56), "steel", scale=4)
    d = ImageDraw.Draw(panel)
    W, H = panel.size
    d.rectangle((0, 0, W - 1, 44), fill=(246, 204, 24))                    # label band
    d.text((W // 2, 23), "MAIN BREAKER", fill=(18, 18, 18), font=font(15), anchor="mm")
    d.rectangle((W // 2 - 14, 64, W // 2 + 14, H - 40), fill=(28, 30, 36))  # slot
    d.text((W // 2 + 34, 76), "ON", fill=(20, 110, 40), font=font(16), anchor="mm")
    d.text((W // 2 + 34, H - 56), "OFF", fill=(150, 20, 20), font=font(16), anchor="mm")
    d.text((W // 2 - 44, 150), "RESET", fill=(16, 26, 62), font=font(11), anchor="mm")
    d.text((W // 2 - 44, 166), "PUSH UP", fill=(16, 26, 62), font=font(11), anchor="mm")
    for i in range(-8, 12):                                                    # hazard stripes
        x = i * 16
        d.polygon([(x, H - 22), (x + 8, H - 22), (x + 16, H - 6), (x + 8, H - 6)], fill=(20, 20, 20))
    d.rectangle((0, H - 30, W - 1, H - 26), fill=(20, 20, 20))
    handle = Image.new("RGB", (32, 32), (178, 24, 20))
    hd = ImageDraw.Draw(handle)
    for y in range(4, 32, 6):
        hd.line((2, y, 29, y), fill=(110, 12, 10), width=2)
    hd.rectangle((0, 0, 31, 31), outline=(90, 8, 6))
    screen_off = Image.new("RGB", (64, 64), (182, 184, 190))                  # a blank screen
    return panel, handle, screen_off


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
    cafe = lvl.room("cafeteria", (-592, 320, 0), (-160, 656, 144), CAFETERIA)

    conf_door = lvl.doorway(conf, hall, width=64, height=96, center=96)
    west_door = lvl.doorway(hall, storage, width=80, height=96, center=-64)
    east_door = lvl.doorway(hall, records, width=80, height=96, center=-64)
    lvl.doorway(basement, corridor, width=64, height=96, center=-56)
    down_steps, conf_hole = lvl.stairs("conference stairs", basement, conf, top=(408, 48), down="north")
    # comes up at the far (west) end of the storage room, well away from its door
    up_steps, store_hole = lvl.stairs("storage stairs", corridor, storage, top=(-480, -56), down="east")
    # to the cafeteria: north out of the hall, 45 degrees north-west past the storage
    # room (whose north-east corner gets cut to make room), then north again
    walkway = lvl.corridor("cafeteria corridor", [(-88, -64), (-88, 67), (-248, 227), (-248, 400)],
                           width=96, height=112, material=HALL)

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

    # mains power: every light below is on it; the card pickup trips it, the basement
    # breaker resets it (see the module docstring)
    grid = logic.Circuit("power", origin=(224, 176, 140))

    # --- doors & locks ----------------------------------------------------------------------
    m.add(props.door_rotating(conf_door, hinge="right"))
    m.add(props.lock("storage_lock", west_door.center),
          props.lock("records_lock", east_door.center, globalstate=grid.flag.state))   # card AND power
    for door, name in ((west_door, "storage_lock"), (east_door, "records_lock")):
        m.add(props.door_rotating(door, hinge="left", texture="FIFTIES_DR5", edge="FIFTIES_DR5B", master=name))

    # --- hall ------------------------------------------------------------------------------
    m.texlight(LIGHT_TEX, (255, 248, 230), 3000)
    m.texlight(HALL_LIGHT_TEX, (255, 248, 230), 1600)
    for x in (-16, 240, 496):          # hall tiles are centred on the hall
        m.add(props.ceiling_light(x, -64, hall.ceiling, texture=HALL_LIGHT_TEX, name="hall_lights"))
    # outer wall only: +use goes through walls; dead while the power is out
    m.add(props.switch((-96, -112, 48), "north", grid.group("hall_lights", switched=True), master=grid.live))
    for x in (40, 352):
        m.add(props.emergency_light((x, -16, 112), "south"))
    # door plates, a poster and a stock sign
    m.add(props.sign((170, -16, 76), "south", "CONFERENCE", 48, 12, "steel"),
          props.sign((-160, -64, 110), "east", "STORAGE", 56, 14, "brass"),
          props.sign((640, -64, 108), "west", "RECORDS\nAUTHORIZED PERSONNEL", 64, 18, "red"),
          props.sign((150, -112, 68), "north", image=poster_texture(), w=40, h=60, frame="FIFTIES_DSK1"),
          props.sign((-20, -112, 72), "north", texture="SIGN6", w=20, h=25))

    conference(m, conf, conf_hole, grid)
    cafeteria(m, cafe, walkway, grid)
    storage_room(m, storage, store_hole, grid)
    records_room(m, records, grid)
    basement_rooms(m, basement, grid)
    cave_contents(m, cave, grid)
    grid.emergency("emergency")
    m.add(props.hud_message("power_fail_msg", grid.origin, "WARNING: MAIN POWER FAILURE", color=(255, 60, 40),
                            y=0.3, channel=3),
          props.hud_message("power_restore_msg", grid.origin, "MAIN POWER RESTORED", color=(120, 255, 140),
                            y=0.3, channel=3),
          props.sound_effect("power_fail_snd", grid.origin, "ambience/xtal_down1.wav", volume=7, everywhere=True),
          props.sound_effect("power_restore_snd", grid.origin, "buttons/button1.wav", everywhere=True),
          props.point("env_shake", grid.origin, targetname="power_fail_shake", amplitude=3, duration=1.2,
                      frequency=40, radius=4000, spawnflags=1))      # 1 = everywhere
    grid.on_fail("power_fail_snd", 0.1)
    grid.on_fail("power_fail_shake", 0.1)
    grid.on_fail("power_fail_msg", 1.0)
    grid.on_restore("power_restore_snd", 0)
    grid.on_restore("power_restore_msg", 0.3)

    presentation(m, grid, SCREEN_LO, SCREEN_HI)     # last: its slides count everything above
    m.add(grid.entities())
    m.add(props.player_start(hall.floor_point(-120, -64), facing="east"))

    m.checkpoints = [("records upper level", (848, 208, 144)),
                     ("radio camp", cave.floor_point(0.85, branch=1))]
    m.cameras = {
        "conference": (420, 20, 72, 6, 125),
        "screen": (224, 70, 64, -12, 90),
        "screen_next": (224, 70, 64, -12, 90, ["slides_next"]),
        # the briefing: the scientist greets you; slides further in
        "talk": (150, 150, 70, 4, 50, ["talk"]),
        "talk_slide7": (224, 70, 64, -12, 90, [("slides_next", 0.2 * k) for k in range(1, 7)]),
        "talk_slide10": (224, 70, 64, -12, 90, [("slides_next", 0.2 * k) for k in range(1, 10)]),
        "presenter": (300, 200, 64, 0, 45),
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
        # the power failure (taking the card fires it) and the breaker
        "hall_power_out": (-120, -64, 64, 0, 0, ["records_card"]),
        "conference_power_out": (420, 20, 72, 6, 125, ["records_card"]),
        "cave_power_out": cave.camera(0.1, look_ahead=0.45, branch=1) + (["records_card"],),
        "breaker": (190, 64, -112, 10, 180, ["records_card"]),
        "breaker_power_on": (190, 64, -112, 10, 180),
        # switched off before the failure: stays off after the reset; the projector returns
        "power_restored": (420, 20, 72, 6, 125, ["conference_lights_switch", "records_card",
                                                  ("power_restore", 2.2)]),
        # signage
        "hall_signs": (60, -96, 66, 2, 45),
        "poster": (150, -40, 66, 0, 270),
        "records_sign": (560, -64, 72, -12, 0),
        "basement_stencil": (300, 190, -110, 0, 90),
        # the diagonal corridor and the cafeteria
        "corridor": (-88, -100, 64, 0, 90),
        "corridor_diag": (-88, 10, 64, 0, 135),
        "corridor_end": (-230, 250, 64, 0, 110),
        "cafeteria": (-200, 350, 76, 6, 125),
        "cafeteria_counter": (-380, 470, 64, 2, 90),
        "storage_corner": (-330, 10, 72, 0, 50),
    }
    return m


# ---------------------------------------------------------------------------- rooms

def conference(m, conf, hole, grid):
    panel, handle, screen_off = breaker_textures()
    m.add_texture("SCREENOFF", screen_off)
    # table for eight
    m.add(props.table(224, 208, conf.floor, width=256, depth=80, height=30))
    for x in (128, 192, 256, 320):
        m.add(props.chair(x, 148, conf.floor, facing="north"), props.chair(x, 268, conf.floor, facing="south"))
    # screen on the north wall (its slideshow comes with the talk, see presentation()),
    # projector hanging over the south end of the table
    front_lo, front_hi = props.slideshow_front(SCREEN_LO, SCREEN_HI, "south")
    m.add(props.projector((224, 120, 132), front_lo, front_hi, ceiling_z=conf.ceiling, name="projector_beam"))
    # the projected picture's light, on the mains
    m.add(props.light((224, 300, 84), color=(205, 210, 255), brightness=90, targetname="projector"))
    grid.group("projector")
    # without power the beam goes and a blank cover hides the slide (env_render changes
    # only renderamt: spawnflags 1|4|8 keep fx, mode and colour)
    cover = box((front_lo[0], front_lo[1] - 1, front_lo[2]), (front_hi[0], front_lo[1], front_hi[2]), "SCREENOFF",
                comment="screen cover")
    # rendermode 4 (solid) keeps its lightmap; mode 2 (texture) would draw it fullbright
    m.add(props.Entity("func_illusionary", brushes=[cover], targetname="screen_cover", rendermode=4, renderamt=0))
    for name, target, amt in (("beam_off", "projector_beam", 0), ("beam_on", "projector_beam", 28),
                              ("screen_off", "screen_cover", 255), ("screen_on", "screen_cover", 0)):
        m.add(props.point("env_render", (224, 200, 120), targetname=name, target=target, renderamt=amt,
                          spawnflags=13))
    grid.on_fail("beam_off", 0)
    grid.on_fail("screen_off", 0)
    grid.on_restore("beam_on", 0.4)
    grid.on_restore("screen_on", 0.4)
    # switchable ceiling panels on the tile grid, switch by the door (outer wall)
    for x, y in ((96, 96), (96, 256), (352, 256), (352, 96)):
        m.add(props.ceiling_light(x, y, conf.ceiling, name="conference_lights"))
    m.add(props.switch((0, 48, 48), "east", grid.group("conference_lights", switched=True), master=grid.live))
    m.add(props.emergency_light((260, 0, 136), "north"), props.emergency_light((448, 180, 136), "west"))
    m.add(props.sign((448, 60, 104), "west", "BASEMENT", 48, 12, "steel"))
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


def storage_room(m, storage, hole, grid):
    x0, y0, z0 = storage.mins
    x1, y1, z1 = storage.maxs
    # tile centres (room centred at -368, -16); the north-east one moved clear of the
    # corner the cafeteria corridor cuts off
    for x, y in ((-496, -96), (-496, 64), (-240, -96), (-304, 64)):
        m.add(props.ceiling_light(x, y, z1, name="storage_lights"))
    grid.group("storage_lights")
    m.add(props.sign((-300, y0, 72), "north", texture="SIGN17", w=32, h=40))   # days since last injury
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
    # crate stacks: by the cut corner and along the south wall; the middle stays open
    for x, y, z, size, tex in [(-296, 114, 0, 56, "CRATE02B"), (-296, 114, 56, 40, "BCRATE04"),
                               (-232, 46, 0, 48, "CRATE19"),
                               (-520, -140, 0, 64, "BCRATE09A"), (-450, -146, 0, 48, "CRATE25"),
                               (-386, -148, 0, 40, "CRATE02"), (-386, -148, 40, 32, "CRATE19")]:
        m.add(props.crate(x, y, z, size=size, texture=tex))
    for x, y, tex in [(-280, -150, "BARREL2"), (-246, -154, "BARREL3")]:
        m.add(props.barrel(x, y, z0, texture=tex))
    m.add(props.wall_art((x1, 20, 72), "west", "+0FUSEBOX", 24, 48))


def cafeteria(m, cafe, walkway, grid):
    """The cafeteria at the end of the diagonal corridor."""
    x0, y0, z0 = cafe.mins
    x1, y1, z1 = cafe.maxs
    # lights on the ceiling tile grid (centred on the room) and a switch by the way in
    for x in (-504, -248):
        for y in (408, 568):
            m.add(props.ceiling_light(x, y, z1, name="cafeteria_lights"))
    m.add(props.switch((-340, y0, 48), "north", grid.group("cafeteria_lights", switched=True), master=grid.live))
    # the corridor's lights follow it round the bend
    ceiling = walkway.z0 + walkway.height
    for s_ in (0.2, 0.5, 0.82):
        (x, y, _), d, _ = walkway.frame(s_)
        angle = round(math.degrees(math.atan2(d[1], d[0])))
        m.add(props.ceiling_light(round(x), round(y), ceiling, texture=HALL_LIGHT_TEX, name="corridor_lights",
                                  angle=0 if angle % 180 == 90 else angle))
    grid.group("corridor_lights")
    m.add(props.sign((-136, 20, 100), "east", "CAFETERIA", 48, 12, "steel"),
          props.sign((-296, 290, 100), "east", texture="SIGNC1A2_4", w=48, h=24))
    # serving counter with a menu board over it
    counter = props.front_box(-400, y1 - 16, z0, 224, 32, 40, "south", "STEEL", sides="STEEL", top="STEEL")
    m.add(props.detail(counter))
    m.add(props.barrel(-490, y1 - 18, z0 + 40, texture="STEEL", top="STEEL", r=7, h=22),     # coffee urn
          props.detail(props.front_box(-310, y1 - 18, z0 + 40, 20, 16, 14, "south", "C1A1_GAD4")),   # till
          props.flat_prop((-420, y1 - 18, z0 + 40), 28, 20, "PAPER4", thick=4))                # trays
    m.add_texture("MENUBOARD", menu_texture())
    m.add(props.sign((-400, y1, 100), "south", image=menu_texture(), w=144, h=72, frame="FIFTIES_DSK1"))
    # tables for four, clear of the way in (x -296..-200)
    for x in (-512, -392):
        for y in (432, 540):
            m.add(props.table(x, y, z0, width=96, depth=48, height=30, top="FIFTIES_DR1"))
            for dx in (-24, 24):
                m.add(props.chair(x + dx, y - 40, z0, facing="north"), props.chair(x + dx, y + 40, z0, facing="south"))
    m.add(props.vending_machine(x1 - 16, 560, z0, "west"), props.vending_machine(x1 - 16, 500, z0, "west"),
          props.barrel(x1 - 24, y0 + 40, z0, texture="STEEL", top="BARRELTOP", r=12, h=34),   # bin
          props.sign((x0, 480, 72), "east", texture="SIGN5", w=24, h=24))       # no smoking


def menu_texture():
    """Today's menu, in chalk."""
    img = Image.new("RGB", (288, 144), (30, 52, 40))
    d = ImageDraw.Draw(img)
    chalk, dim = (236, 236, 226), (170, 186, 170)
    d.text((144, 18), "TODAY'S MENU", fill=YELLOW, font=font(22), anchor="mm")
    items = [("mystery loaf", "2.50"), ("soup of the day", "ask"), ("Xen fruit salad", "under review"),
             ("coffee", "lukewarm")]
    for i, (dish, price) in enumerate(items):
        y = 46 + i * 20
        d.text((14, y), dish, fill=chalk, font=font(14, bold=False), anchor="lm")
        d.text((274, y), price, fill=chalk, font=font(14), anchor="rm")
        w = d.textlength(dish, font=font(14, bold=False))
        for x in range(int(24 + w), int(274 - d.textlength(price, font=font(14)) - 8), 6):
            d.point((x, y + 4), fill=dim)
    d.text((144, 130), "please return your tray  \u00b7  no samples in the fridge", fill=dim,
           font=font(10, bold=False), anchor="mm")
    b = boxworth().resize((40, 40), Image.NEAREST)
    img.paste(b, (238, 0), b)
    return img


def records_room(m, r, grid):
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
        for y, z in ((-96, z1), (64, z1), (224, mez_z), (224, z1)):
            m.add(props.ceiling_light(x, y, z, name="records_lights"))
    grid.group("records_lights")
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
    m.add(props.point("item_healthkit", (984, 188, upper + 40)))     # front corner: the chair is in the middle


def basement_rooms(m, b, grid):
    x0, y0, z0 = b.mins
    x1, y1, z1 = b.maxs
    # the main breaker on the west wall: only does something while the power is out
    panel, handle, _ = breaker_textures()
    m.add_texture("BRKPANEL", panel)
    m.add_texture("BRKHANDLE", handle)
    by = 64
    m.add(props.wall_art((x0, by, z0 + 56), "east", "BRKPANEL", 40, 56, depth=2))
    m.add(props.lever((x0 + 2, by, z0 + 38), "east", grid.restore, master=grid.dead, size=(8, 12), travel=14))
    m.add(props.emergency_light((x0, by, z0 + 104), "east"),
          props.sign((x0, by + 50, z0 + 60), "east", texture="SIGN74", w=36, h=24),   # disconnect power first
          props.decal("{PSTRIPE3", (x0 + 30, by, z0 + 1)))
    # emergency lamps from the stairs to the breaker
    m.add(props.emergency_light((x1, 250, z1 - 28), "west"), props.emergency_light((220, y0, z1 - 28), "north"))
    # grime and markings (stock decals)
    m.add(props.decal("{OIL1", (180, 100, z0 + 1)), props.decal("{OIL2", (330, 130, z0 + 1)),
          props.decal("{CRACK2", (300, y1 - 1, z0 + 110)), props.decal("{CRACK1", (x1 - 1, 40, z0 + 40)),
          props.decal("{RUST002", (72, y1 - 1, z1 - 30)))
    m.add(props.stencil("BASEMENT", (300, y1, z0 + 76), "south"))
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
    m.add(props.wall_art((x0, 180, z0 + 64), "east", "+0FUSEBOX", 24, 48))
    for x, y, s, t in [(40, 220, 48, "CRATE02"), (40, 172, 40, "CRATE19"), (300, 180, 48, "CRATE25")]:
        m.add(props.crate(x, y, z0, size=s, texture=t))
    # bare bulbs on the mains: steady ones, and a flickering fluorescent by the boiler
    bulb = dict(color=(255, 225, 170), targetname="basement_lights")
    m.add(props.light((200, 160, z1 - 20), brightness=240, **bulb),
          props.light((120, 40, z1 - 20), brightness=180, **bulb),
          props.light((150, -56, z1 - 20), brightness=150, **bulb),
          props.light((-80, -56, z1 - 20), brightness=150, **bulb),
          props.light((-250, -56, z1 - 20), brightness=120, **bulb),
          props.light((260, 290, z1 - 20), color=(255, 225, 170), brightness=170, targetname="basement_flicker",
                      pattern=logic.STYLE_FLUORESCENT))
    grid.group("basement_lights")
    grid.group("basement_flicker")


def cave_contents(m, cave, grid):
    # rock stretch: dim work lights on the building's mains, and emergency lamps on poles
    m.add(props.light(cave.floor_point(0.12, above=110), color=(255, 205, 160), brightness=110,
                      targetname="cave_lights"))
    m.add(props.light(cave.floor_point(0.34, above=100), color=(255, 205, 160), brightness=70,
                      targetname="cave_lights"))
    grid.group("cave_lights")
    amber = dict(color=(255, 120, 30), brightness=90)
    for s, lat, branch in ((0.12, 0.85, 0), (0.3, -0.85, 1)):
        x, y, z = cave.floor_point(s, lat, branch=branch)
        _, t, _ = cave.frame(s, branch=branch)      # facing the way back
        m.add(props.emergency_light((x, y, z + 60), props.compass(-t[0], -t[1]), stand=z, **amber))

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
    # at the front edge: an item is picked up by touching its 32x32 box, and the player
    # can't get closer than 16 to the table edge (verify walks straight at it)
    card_at = (cx + ax * 30 + fx * 18, cy + ay * 30 + fy * 18)
    card_w, card_d = (16, 10) if fy else (10, 16)
    m.add(props.flat_prop((card_at[0], card_at[1], top), card_w, card_d, "ACCESSCARD", name="card_prop"))
    m.texlight("ACCESSCARD", (255, 255, 255), 40)
    # taking it shorts the radios: sparks, a scorch mark, and the building's power trips
    m.add(props.pickup("item_security", (card_at[0], card_at[1], top + 8), fires=["records_lock_key", grid.fail],
                       message="RECORDS ACCESS CARD ACQUIRED", name="records_card",
                       hide=["card_prop"], invisible=True))
    m.add(props.chair(cx - fx * 44, cy - fy * 44, cz - 2, facing=face))
    m.add(props.crate(cx - ax * 76, cy - ay * 76, cz - 4, size=40, texture="CRATE25"))
    m.add(props.light((cx + fx * 24, cy + fy * 24, cz + 80), color=(255, 190, 120), brightness=150,
                      targetname="camp_lamp", pattern=logic.STYLE_FLUORESCENT))
    grid.group("camp_lamp")
    m.add(props.point("env_spark", (cx - fx * 4, cy - fy * 4, top + 14), targetname="camp_sparks",
                      MaxDelay=0.3, spawnflags=32),                          # 32 = toggled on/off
          props.decal("{SMSCORCH1", (cx + fx * 8 - ax * 14, cy + fy * 8 - ay * 14, top + 1), name="camp_scorch"))
    grid.on_fail("camp_sparks", 0)
    grid.on_fail("camp_sparks", 2.5)       # the second fire stops them
    grid.on_fail("camp_scorch", 0.2)
    # the camp's emergency lamp stands behind the table, out of the way in
    lx, ly = cx - fx * 64 - ax * 30, cy - fy * 64 - ay * 30
    lz = cave.heights_at(lx, ly)[0]
    m.add(props.emergency_light((lx, ly, lz + 60), face, stand=lz, **amber))

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
