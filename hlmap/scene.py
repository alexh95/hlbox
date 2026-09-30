"""Scripted talks: someone says synthesized lines, with subtitles, while things happen
on cue (slides change, the speaker gestures).

    talk = scene.Talk(m, "talk", head=(390, 312, 66), actor="presenter")
    talk.line("Welcome to the briefing.", gesture="wave", fire=["lights_dim"])
    talk.line("hlbox builds maps from code.", say="H L box builds maps from code.")
    talk.interrupt("What was that?", gesture="startle")    # said if aborted mid-talk
    m.add(talk.entities(), props.trigger(..., talk.start))

Each line is synthesized at build time (hlmap.voice), shipped as a WAV with the map
(Map.add_sound) and played by an ambient_generic at the speaker's head, with a
game_text subtitle for as long as it lasts. The timeline comes from the real clip
lengths: a line's cues fire as it starts, the next line follows after `gap` seconds.

Lips: stock Half-Life only lip-syncs lines from its sentences.txt, which a map can't
extend, so custom lines play from the head position and the actor's gestures carry
the performance (scripted_sequence animations; see a model's sequence list).

Names: fire `start` (only while not already running) and `abort` (only while
running: stops the timeline, says the interrupt line) and `skip` (only while
running: stops it without a word, cutting the line being spoken, and fires `on_skip`
targets, e.g. the state the lines would have reached). An aborted or skipped talk
can't run again: its timeline is removed, the only way to cancel fires the game has
queued. `running` and `skipped` are logic.Flags; `on_start` targets fire as it
starts, `on_end` ones when it finishes, is aborted or is skipped. skip_button() makes
a wall panel that skips talks.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

from . import config, logic, model, props, voice
from .mapfile import Entity


class Talk:
    def __init__(self, m, name, head, actor=None, voice_name="david", rate=0, pitch=1.0, gap=0.8, lead=1.0,
                 radius="small", color=(235, 235, 235), wrap=64, actor_model=None):
        self.m, self.name, self.head, self.actor = m, name, tuple(head), actor
        self.actor_model = actor_model      # e.g. "models/scientist.mdl": gestures are checked against it
        self.voice, self.rate, self.pitch = voice_name, rate, pitch
        self.gap, self.lead, self.radius, self.color, self.wrap = gap, lead, radius, color, wrap
        self.lines = []
        self.interruption = None
        self.on_start, self.on_end = [], []
        self.running = logic.Flag(f"{name}_running", False, head)
        self.skipped = logic.Flag(f"{name}_skipped", False, head)   # the last run was skipped
        self.on_skip = []
        self.cache_dir = Path(config.BUILD_DIR / m.name / "voice")    # synthesized clips (cached)
        self.start, self.abort, self.skip = name, f"{name}_abort", f"{name}_skip"
        self.duration = None

    def line(self, text, say=None, fire=(), gesture=None):
        """Add a line: `text` is the subtitle, `say` what the voice says if different
        (spell out names: "H L box"); `fire` targets and the actor's `gesture`
        (an animation) happen as it starts."""
        self.lines.append({"text": text, "say": say or text, "fire": list(fire), "gesture": gesture})
        return len(self.lines)

    def interrupt(self, text, say=None, gesture=None, fire=()):
        """What is said (and done) if the talk is aborted."""
        self.interruption = {"text": text, "say": say or text, "fire": list(fire), "gesture": gesture}

    def entities(self, cache_dir=None):
        """Build it (lines, cues and on_start/on_end must be set before this)."""
        m, n = self.m, self.name
        cache_dir = Path(cache_dir or self.cache_dir)
        spoken = {f"{n}{i:02d}": ln["say"] for i, ln in enumerate(self.lines, 1)}
        if self.interruption:
            spoken[f"{n}_int"] = self.interruption["say"]
        clips = voice.synthesize(spoken, cache_dir, self.voice, self.rate, self.pitch)
        ents = self.running.entities() + self.skipped.entities()
        gestures = {}
        # voices can be cut short: each has a relay that turns it off, and `hush` fires
        # them all. That also marks finished lines as not playing (see
        # props.sound_effect), so it runs at the start and the end of every run too.
        for key in spoken:
            ents.append(Entity("trigger_relay", targetname=f"{key}_hush", target=f"{key}_voice", triggerstate=0,
                               origin=self.head))
        ents += logic.sequence(f"{n}_hush", [(f"{key}_hush", 0) for key in spoken], self.head)
        ents.append(props.hud_message(f"{n}_clear", self.head, " ", channel=4, hold=0.1))

        def say(key, ln):
            """Entities for one line; returns (targets to fire at its start, seconds)."""
            sound = m.add_sound(f"hlbox/{m.name}/{key}.wav", clips[key])
            dur = voice.duration(clips[key])
            ents.append(props.sound_effect(f"{key}_voice", self.head, sound, radius=self.radius, stoppable=True))
            sub = "\\n".join(textwrap.wrap(ln["text"], self.wrap))
            ents.append(props.hud_message(f"{key}_sub", self.head, sub, color=self.color, y=0.86, channel=4,
                                          hold=round(dur + 0.3, 1)))
            cues = [f"{key}_voice", f"{key}_sub"] + ln["fire"]
            if ln["gesture"] and self.actor:
                g = gestures.setdefault(ln["gesture"], f"{n}_g_{ln['gesture']}")
                cues.append(g)
            return cues, dur

        seqs = model.sequences(self.actor_model) if self.actor_model else None
        for ln in self.lines + ([self.interruption] if self.interruption else []):
            if seqs is not None and ln["gesture"] and ln["gesture"] not in seqs:
                raise ValueError(f"talk {n}: {self.actor_model} has no animation {ln['gesture']!r} "
                                 f"(it has: {', '.join(sorted(seqs))})")
        steps = [(self.running.on, 0), (self.skipped.off, 0), (f"{n}_hush", 0)] + [(e, 0) for e in self.on_start]
        t = self.lead
        for i, ln in enumerate(self.lines, 1):
            cues, dur = say(f"{n}{i:02d}", ln)
            if seqs and ln["gesture"] and seqs[ln["gesture"]][0] > dur + self.gap:
                m.notes.append(f"talk {n} line {i}: gesture {ln['gesture']} ({seqs[ln['gesture']][0]:.1f} s) outlasts "
                               f"the line ({dur:.1f} s); the next gesture will wait for it")
            steps += [(c, round(t, 2)) for c in cues]
            t += dur + self.gap
        self.duration = round(t, 2)
        steps += [(self.running.off, self.duration), (f"{n}_hush", self.duration)]
        steps += [(e, self.duration) for e in self.on_end]
        timeline = logic.sequence(f"{n}_seq", steps, self.head)
        ents += timeline
        ents.append(logic.gate(self.start, f"{n}_seq", self.running.is_off, self.head))
        # abort and skip: remove every part of the timeline and silence the line being
        # said; abort then says the interruption, skip just ends
        stop = [(self.running.off, 0), (f"{n}_hush", 0), (f"{n}_clear", 0)] + [(e, 0) for e in self.on_end]
        for k, mm in enumerate(e["targetname"] for e in timeline):
            ents.append(Entity("trigger_relay", targetname=f"{n}_kill{k}", killtarget=mm, origin=self.head))
            stop.append((f"{n}_kill{k}", 0))
        abort = list(stop)
        if self.interruption:
            cues, dur = say(f"{n}_int", self.interruption)
            abort += [(c, 0.3) for c in cues] + [(f"{n}_int_hush", round(0.3 + dur + 0.2, 2))]
        ents += logic.sequence(f"{n}_abort_seq", abort, self.head)
        ents.append(logic.gate(self.abort, f"{n}_abort_seq", self.running.is_on, self.head))
        ents += logic.sequence(f"{n}_skip_seq", stop + [(self.skipped.on, 0)] + [(e, 0) for e in self.on_skip],
                               self.head)
        ents.append(logic.gate(self.skip, f"{n}_skip_seq", self.running.is_on, self.head))
        for anim, g in gestures.items():   # 4 repeatable, 32 no interruptions, 64 override AI
            ents.append(Entity("scripted_sequence", targetname=g, m_iszEntity=self.actor, m_iszPlay=anim,
                               m_fMoveTo=0, m_flRadius=512, spawnflags=4 | 32 | 64, origin=self.head))
        return ents


def skip_button(pos, facing, talks, name="skip", label="INTERCOM"):
    """A wall panel (pos = centre on the wall) with a button that skips whichever of
    `talks` is running: the line being said stops, and what the talk leads to happens
    right away. Returns the entities."""
    from .art import skip_button as button_art, skip_panel
    from .mapfile import prepare_texture
    fx, fy = props.DIRS[facing]
    x, y, z = pos
    panel = props.sign((x, y, z), facing, image=skip_panel(label), w=24, h=36, depth=1)
    tex = {"+0SKIPBTN": prepare_texture("+0SKIPBTN", button_art(False)),
           "+ASKIPBTN": prepare_texture("+ASKIPBTN", button_art(True))}
    button = props.switch((x + fx, y + fy, z - 10), facing, name, texture="+0SKIPBTN", size=(12, 12), depth=3,
                          sound=0, wait=1)
    button.textures = tex
    return [panel, button] + logic.sequence(name, [(t.skip, 0) for t in talks], (x + fx * 8, y + fy * 8, z))
