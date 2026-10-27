"""Token lines for a staff from the corrected score of a Musiki Akademisi correction package, and the check that
they say what the corrected score says.

The app writes its own MusicXML (music-core's scoreToMusicXML). It holds what the user checked: every note's step,
octave, sounding accidental (a 53-TET <alter>, 12/53 of a semitone per comma), duration, tuplet, tie and grace note,
and the repeats, endings, jumps, key and meter. It does not hold what the page draws, which is what the model is
trained on (see training/datasets/convert_symbtr.py EngravingState):

- the accidentals it writes are worked out again from the pitches (music-core yazim.ts ArizaIzleyici: a sign where
  the sounding accidental differs from what the key and the measure lead the reader to expect), so a courtesy sign
  the page prints is not there;
- it has no barline styles: every barline is plain except the light-heavy one it puts after the last measure, and a
  repeat's;
- no slurs, no fermatas and no other articulations, only ties (MARK_KINDS);
- a time signature in the first measure whether or not the page prints one, and a key only where it changes;
- one voice per staff, without chords.

What the corrected file cannot tell, the model's reading of the same page (model.musicxml, written by
homr.music_xml_generator from the model's tokens) can: a courtesy sign the model read on a note the user left as it
was, a dashed or double barline, a slur, a fermata or another articulation on the same note or rest (by its id,
whatever the user changed in it), whether a key or a time signature is printed at the head of a staff. Those
fields are taken from the reading and written unverified, with the "?" the training reads as "the loss skips this"
(training/transformer/training_vocabulary.py UNVERIFIED), since nothing the user did confirms them.

round_trip writes the tokens of a staff line back with homr's own writer, as the service does, and compares the
result with the corrected file measure by measure: pitch with its sounding accidental, duration, ties, grace notes,
repeats, endings, jumps, key, meter and clef. A staff whose measures do not come back is not used.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import combinations

from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
from homr.transformer.vocabulary import (
    EncodedSymbol,
    Vocabulary,
    aeu_commas,
    empty,
    key_accidental,
    nonote,
)

# What one comma is in an <alter>: the app writes 53-TET semitones, homr's writer 2/9 of a semitone (a whole tone is
# 9 commas and 2 semitones).
APP_COMMA = Fraction(12, 53)
HOMR_COMMA = Fraction(2, 9)

BRANCHES = ("rhythm", "pitch", "lift", "articulation")
ALL_BRANCHES = frozenset(BRANCHES)

# The drawn sign by its SMuFL name (the app writes one on every <accidental> and <key-accidental>; homr's writer too)
SMUFL_LIFTS = {
    "accidentalKomaSharp": "sharp1",
    "accidental2CommaSharp": "sharp2",
    "accidental3CommaSharp": "sharp3",
    "accidentalBakiyeSharp": "sharp4",
    "accidentalKucukMucennebSharp": "sharp5",
    "accidentalBuyukMucennebSharp": "sharp8",
    "accidentalKomaFlat": "flat1",
    "accidental2CommaFlat": "flat2",
    "accidental3CommaFlat": "flat3",
    "accidentalBakiyeFlat": "flat4",
    "accidentalKucukMucennebFlat": "flat5",
    "accidentalBuyukMucennebFlat": "flat8",
    "accidentalNatural": "N",
    "accidentalDoubleSharp": "##",
    "accidentalDoubleFlat": "bb",
    # the plain signs, as the app reads them: a sharp is the bakiye sharp, a flat the küçük mücenneb flat
    "accidentalSharp": "sharp4",
    "accidentalFlat": "flat5",
}
# ... and by the MusicXML name, for a sign without one (the app's reading of these, music-core accidentals.ts)
VALUE_LIFTS = {
    "sharp": "sharp4",
    "flat": "flat5",
    "natural": "N",
    "quarter-sharp": "sharp1",
    "quarter-flat": "flat1",
    "slash-flat": "flat4",
    "slash-quarter-sharp": "sharp5",
    "slash-sharp": "sharp8",
    "double-slash-flat": "flat8",
    "sharp-2": "sharp2",
    "sharp-3": "sharp3",
    "flat-2": "flat2",
    "flat-3": "flat3",
    "double-sharp": "##",
    "sharp-sharp": "##",
    "flat-flat": "bb",
}
# The commas a drawn sign stands for; the double signs are the app's tanînî, a whole tone (homr writes 2 semitones)
LIFT_COMMAS: dict[str, int] = {
    "N": 0,
    "##": 9,
    "bb": -9,
    **{f"sharp{c}": c for c in aeu_commas},
    **{f"flat{c}": -c for c in aeu_commas},
}

TYPE_KERN = {
    "breve": 0,
    "whole": 1,
    "half": 2,
    "quarter": 4,
    "eighth": 8,
    "16th": 16,
    "32nd": 32,
    "64th": 64,
    "128th": 128,
}

# Barline styles homr's writer gives its barline tokens (music_xml_generator.build_barline_style)
STYLE_TOKENS = {
    "light-light": "doublebarline",
    "heavy-heavy": "bolddoublebarline",
    "light-heavy": "bolddoublebarline",
    "heavy": "bolddoublebarline",
    "dashed": "dashedbarline",
}

ARTICULATION_NAMES = {
    "staccato": "staccato",
    "staccatissimo": "staccatissimo",
    "tenuto": "tenuto",
    "accent": "accent",
    "strong-accent": "accent",
    "breath-mark": "breathMark",
}
ORNAMENT_NAMES = {
    "trill-mark": "trill",
    "wavy-line": "trill",
    "inverted-mordent": "trill",
    "turn": "turn",
    "inverted-turn": "turn",
    "tremolo": "tremolo",
}
# What the app's MusicXML keeps of a note besides its pitch and duration: ties and tuplet brackets only. Its reader
# (music-core musicxml.ts) drops <notations> but for <tied> and <tuplet>, and duzeltilmis.musicxml is written anew
# from its Score (musicxml-yaz.ts), so every slur, fermata, staccato, staccatissimo, tenuto, accent, breath mark,
# trill, turn, tremolo and arpeggio the model read is gone from the corrected file. Those marks are taken from the
# reading, by note id, unverified (MARK_KINDS, carried_marks). A caesura has no token: homr's vocabulary leaves it
# out, so the model never reads one.
MARK_KINDS = ("slur", "fermata", "staccato", "staccatissimo", "tenuto", "accent", "breathMark", "trill", "turn",
              "tremolo", "arpeggiate")


def mark_kind(name: str) -> str:
    """slurStart and slurStop are one kind of mark; every other mark is its own."""
    return "slur" if name.startswith("slur") else name

# Where a key signature's sign stands on a treble staff, in staff steps above the bottom line (E4): the sharps
# F5 C5 G5 D5 A4 E5 B4 and the flats B4 E5 A4 D5 G4 C5 F4, as every training set spells them (convert_lieder_makam)
SHARP_PLACES = {"F": 8, "C": 5, "G": 9, "D": 6, "A": 3, "E": 7, "B": 4}
FLAT_PLACES = {"B": 4, "E": 7, "A": 3, "D": 6, "G": 2, "C": 5, "F": 1}
# The clefs the app knows (G2, its octave form G2-8, F4): how many staff steps lower their signs stand than on a
# treble staff (a bass staff's sharps F3 C3 G3 D3 A2 E3 B2), and the bottom line's note in steps from C0 (E4, G2)
KEY_SHIFT = {("G", 2): 0, ("F", 4): 2}
BOTTOM_LINE = {("G", 2): 4 * 7 + 2, ("F", 4): 2 * 7 + 4}
STEPS = "CDEFGAB"

_vocabulary = Vocabulary()


class LabelError(Exception):
    """A staff whose corrected music cannot be spelled in the model's tokens."""


@dataclass
class Clef:
    sign: str
    line: int
    octave: int = 0  # <clef-octave-change>: -1 for the treble clef with an 8 under it


@dataclass
class Event:
    """A note, rest or grace note of a staff's first voice."""

    is_note: bool
    is_grace: bool
    measure_rest: bool
    step: str | None
    octave: int | None
    commas: int  # what it sounds, from <alter>
    drawn: str | None  # the sign the file draws (a lift token), None for none
    type: str
    dots: int
    tuplet: tuple[int, int] | None
    duration: Fraction  # in quarters; 0 for a grace note
    tie_start: bool
    tie_stop: bool
    marks: tuple[str, ...]  # slurs and articulations, homr's names
    note_id: str | None  # <note id>, which the app keeps from the model's reading
    app_id: str | None  # the id the app gives this event when it reads the file (music-core musicxml.ts)
    offset: Fraction  # from the start of the measure, in quarters


@dataclass
class Measure:
    number: int
    events: list[Event] = field(default_factory=list)
    # (index of the event they stand before, value)
    clefs: list[tuple[int, Clef]] = field(default_factory=list)
    keys: list[tuple[int, list[tuple[str, str]]]] = field(default_factory=list)
    times: list[tuple[int, tuple[int, int]]] = field(default_factory=list)
    breaks: list[int] = field(default_factory=list)  # <print new-system|new-page="yes">
    repeat_start: bool = False
    repeat_end: bool = False
    ending_start: bool = False
    ending_stop: str | None = None  # "stop" | "discontinue"
    right_style: str | None = None
    jumps: list[tuple[Fraction, str]] = field(default_factory=list)  # (offset, token)
    chord_notes: int = 0  # notes the first voice leaves out: chord members ...
    other_voices: int = 0  # ... and other voices
    unknown: list[str] = field(default_factory=list)  # what cannot be read into tokens
    length: Fraction = Fraction(0)


@dataclass
class StaffLine:
    """One staff of a part through the whole score, its first voice."""

    part: int  # <part> order, from 0
    staff: int  # <staff> number, from 1
    measures: list[Measure]


# --- reading MusicXML ---------------------------------------------------------------------------------------------


def read_lines(text: str, comma: Fraction) -> list[StaffLine]:
    """Every staff of every part, in part order. comma: the unit of the file's <alter> (APP_COMMA, HOMR_COMMA)."""
    root = ET.fromstring(text)  # noqa: S314  (the package's own files)
    parts = root.findall("part")
    staves = [_staves(part) for part in parts]
    several = sum(staves) > 1
    lines: list[StaffLine] = []
    inner = 0
    for index, (part, count) in enumerate(zip(parts, staves, strict=True)):
        for staff in range(1, count + 1):
            inner += 1
            lines.append(_read_line(part, index, staff, f"p{inner}" if several else "", comma))
    return lines


def _staves(part: ET.Element) -> int:
    count = 1
    for element in part.iter("staves"):
        text = (element.text or "").strip()
        if text.isdigit() and 1 < int(text) <= 16:
            count = max(count, int(text))
    return count


def _number(element: ET.Element) -> int | None:
    value = (element.get("number") or "").strip()
    return int(value) if value.isdigit() else None


def _for_staff(elements: list[ET.Element], staff: int, unnumbered_for_all: bool) -> ET.Element | None:
    """The element of this staff: its own number, else an unnumbered one (a key is every staff's, a clef the
    first staff's), as the app reads them."""
    own = [e for e in elements if _number(e) == staff]
    if own:
        return own[0]
    unnumbered = [e for e in elements if _number(e) is None]
    if unnumbered and (unnumbered_for_all or staff == 1):
        return unnumbered[0]
    return None


def _quarters(element: ET.Element | None, divisions: Fraction) -> Fraction:
    text = (element.findtext("duration") or "0").strip() if element is not None else "0"
    try:
        return Fraction(text) / divisions
    except (ValueError, ZeroDivisionError):
        return Fraction(0)


def _lift_for_commas(commas: int) -> str | None:
    for lift, value in LIFT_COMMAS.items():
        if value == commas:
            return lift
    return None


def _commas(alter: str | None, comma: Fraction) -> int:
    if alter is None or not alter.strip():
        return 0
    try:
        return round(Fraction(alter.strip()) / comma)
    except ValueError:
        return 0


def _drawn(accidental: ET.Element | None, commas: int) -> str | None:
    if accidental is None:
        return None
    value = (accidental.text or "").strip()
    lift = SMUFL_LIFTS.get(accidental.get("smufl") or "") or VALUE_LIFTS.get(value)
    if lift is None and value == "other":
        lift = _lift_for_commas(commas)
    return lift if lift is not None else f"unknown:{accidental.get('smufl') or value}"


def _key_entries(key: ET.Element, comma: Fraction) -> list[tuple[str, str]]:
    """A key signature as (step, lift) in the order the file writes it."""
    fifths = key.findtext("fifths")
    if fifths is not None and fifths.strip().lstrip("-").isdigit():
        count = int(fifths)
        if count > 0:
            return [(step, "sharp4") for step in "FCGDAEB"[:count]]
        return [(step, "flat5") for step in "BEADGCF"[: -count]]
    entries: list[list] = []
    for child in key:
        if child.tag == "key-step":
            entries.append([(child.text or "").strip(), None, None])
        elif child.tag == "key-alter" and entries:
            entries[-1][1] = (child.text or "").strip()
        elif child.tag == "key-accidental" and entries:
            entries[-1][2] = child
    result = []
    for step, alter, accidental in entries:
        commas = _commas(alter, comma)
        lift = _drawn(accidental, commas) if accidental is not None else _lift_for_commas(commas)
        if lift and lift != "N":
            result.append((step, lift))
    return result


def _marks(note: ET.Element) -> tuple[str, ...]:
    names: set[str] = set()
    for notations in note.findall("notations"):
        for child in notations:
            if child.tag == "slur" and child.get("type") in ("start", "stop"):
                names.add("slur" + child.get("type", "").capitalize())
            elif child.tag == "fermata":
                names.add("fermata")
            elif child.tag == "arpeggiate":
                names.add("arpeggiate")
            elif child.tag == "articulations":
                names.update(ARTICULATION_NAMES[a.tag] for a in child if a.tag in ARTICULATION_NAMES)
            elif child.tag == "ornaments":
                names.update(ORNAMENT_NAMES[o.tag] for o in child if o.tag in ORNAMENT_NAMES)
    return tuple(sorted(names))


def _ties(note: ET.Element) -> set[str]:
    kinds = {t.get("type") for t in note.findall("tie")}
    for notations in note.findall("notations"):
        kinds.update(t.get("type") for t in notations.findall("tied"))
    return {k for k in kinds if k}


def _event(note: ET.Element, offset: Fraction, duration: Fraction, comma: Fraction, app_id: str | None) -> Event:
    pitch = note.find("pitch")
    rest = note.find("rest")
    step = octave = None
    commas = 0
    if pitch is not None:
        step = (pitch.findtext("step") or "").strip()
        octave = int((pitch.findtext("octave") or "0").strip())
        commas = _commas(pitch.findtext("alter"), comma)
    modification = note.find("time-modification")
    tuplet = None
    if modification is not None:
        actual = int((modification.findtext("actual-notes") or "1").strip())
        normal = int((modification.findtext("normal-notes") or "1").strip())
        if actual != normal:
            tuplet = (actual, normal)
    ties = _ties(note)
    return Event(
        is_note=pitch is not None,
        is_grace=note.find("grace") is not None,
        measure_rest=rest is not None and rest.get("measure") == "yes",
        step=step,
        octave=octave,
        commas=commas,
        drawn=_drawn(note.find("accidental"), commas) if pitch is not None else None,
        type=(note.findtext("type") or "").strip(),
        dots=len(note.findall("dot")),
        tuplet=tuplet,
        duration=duration,
        tie_start="start" in ties,
        tie_stop="stop" in ties,
        marks=_marks(note),
        note_id=(note.get("id") or "").strip() or None,
        app_id=app_id,
        offset=offset,
    )


def _jumps(direction: ET.Element) -> list[str]:
    found = []
    for kind in direction.findall("direction-type"):
        for child in kind:
            if child.tag == "segno":
                found.append("segno")
            elif child.tag == "coda":
                found.append("coda")
            elif child.tag == "words":
                words = (child.text or "").replace(" ", "").upper()
                if words.startswith("D.C"):
                    found.append("daCapo")
                elif words.startswith("D.S"):
                    found.append("daSegno")
    return found


def _read_line(part: ET.Element, part_index: int, staff: int, prefix: str, comma: Fraction) -> StaffLine:
    """A staff's first voice, as music-core's parsePart reads it, with the ids it gives the events."""
    divisions = Fraction(1)
    primary: str | None = None
    used: set[int] = set()
    measures: list[Measure] = []
    repeat_next = False
    for index, element in enumerate(part.findall("measure")):
        raw = (element.get("number") or "").strip()
        number = int(raw) if raw.isdigit() else index + 1
        base = prefix + (f"m{number}-{index + 1}" if number in used else f"m{number}")
        used.add(number)
        measure = Measure(number, repeat_start=repeat_next)
        repeat_next = False
        position = furthest = Fraction(0)
        counted = 0
        for child in element:
            tag = child.tag
            if tag == "attributes":
                text = (child.findtext("divisions") or "").strip()
                if text:
                    divisions = Fraction(text)
                key = _for_staff(child.findall("key"), staff, unnumbered_for_all=True)
                if key is not None:
                    measure.keys.append((len(measure.events), _key_entries(key, comma)))
                time = child.find("time")
                if time is not None:
                    beats = (time.findtext("beats") or "").strip()
                    beat_type = (time.findtext("beat-type") or "").strip()
                    if beats.isdigit() and beat_type.isdigit():
                        measure.times.append((len(measure.events), (int(beats), int(beat_type))))
                    else:
                        measure.unknown.append(f"ölçü işareti {beats}/{beat_type}")
                clef = _for_staff(child.findall("clef"), staff, unnumbered_for_all=False)
                if clef is not None:
                    line = (clef.findtext("line") or "").strip()
                    change = (clef.findtext("clef-octave-change") or "0").strip()
                    measure.clefs.append((len(measure.events), Clef(
                        (clef.findtext("sign") or "").strip().upper(),
                        int(line) if line.isdigit() else 0,
                        int(change) if change.lstrip("-").isdigit() else 0,
                    )))
            elif tag == "barline":
                location = child.get("location", "right")
                if location == "middle":
                    continue
                repeat = child.find("repeat")
                if repeat is not None and repeat.get("direction") == "forward":
                    if location == "left":
                        measure.repeat_start = True
                    else:
                        repeat_next = True
                elif repeat is not None and repeat.get("direction") == "backward":
                    if location == "right":
                        measure.repeat_end = True
                    elif measures:
                        measures[-1].repeat_end = True
                ending = child.find("ending")
                if ending is not None:
                    if ending.get("type") == "start":
                        measure.ending_start = True
                    elif ending.get("type") in ("stop", "discontinue"):
                        measure.ending_stop = ending.get("type")
                style = (child.findtext("bar-style") or "").strip()
                if location == "right" and style:
                    measure.right_style = style
                for sign in ("segno", "coda"):
                    if child.find(sign) is not None:
                        measure.jumps.append((Fraction(0) if location == "left" else Fraction(-1), sign))
            elif tag == "direction":
                on = (child.findtext("staff") or "").strip()
                if (int(on) if on.isdigit() else 1) != staff:
                    continue
                try:
                    offset = Fraction((child.findtext("offset") or "0").strip() or "0") / divisions
                except ValueError:
                    offset = Fraction(0)
                measure.jumps.extend((position + offset, kind) for kind in _jumps(child))
            elif tag == "print":
                if child.get("new-system") == "yes" or child.get("new-page") == "yes":
                    measure.breaks.append(len(measure.events))
            elif tag == "backup":
                position = max(Fraction(0), position - _quarters(child, divisions))
            elif tag == "forward":
                position += _quarters(child, divisions)
                furthest = max(furthest, position)
            elif tag == "note":
                chord = child.find("chord") is not None
                grace = child.find("grace") is not None
                duration = Fraction(0) if grace else _quarters(child, divisions)
                on = (child.findtext("staff") or "").strip()
                if chord:
                    if (int(on) if on.isdigit() else 1) == staff:
                        measure.chord_notes += 1
                    continue
                if (int(on) if on.isdigit() else 1) != staff or child.find("cue") is not None:
                    position += duration
                    furthest = max(furthest, position)
                    continue
                voice = (child.findtext("voice") or "").strip() or None
                if grace:
                    if voice and primary and voice != primary:
                        measure.other_voices += 1
                    else:
                        measure.events.append(_event(child, position, duration, comma, None))
                    continue
                if voice and primary is None:
                    primary = voice
                if voice and primary and voice != primary:
                    measure.other_voices += 1
                else:
                    if child.find("pitch") is None and child.find("rest") is None:
                        measure.unknown.append("perdesiz nota (unpitched)")
                    counted += 1
                    measure.events.append(_event(child, position, duration, comma, f"{base}n{counted}"))
                position += duration
                furthest = max(furthest, position)
        measure.length = furthest
        measure.jumps = [(furthest if offset < 0 else offset, kind) for offset, kind in measure.jumps]
        measures.append(measure)
    return StaffLine(part_index, staff, measures)


# --- what is in force where -------------------------------------------------------------------------------------


def clef_at(line: StaffLine, measure: int, event: int = 0) -> Clef | None:
    """The clef in force before the given event of the given measure."""
    found = None
    for index, m in enumerate(line.measures[: measure + 1]):
        for at, clef in m.clefs:
            if index < measure or at <= event:
                found = clef
    return found


def key_at(line: StaffLine, measure: int, event: int = 0) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for index, m in enumerate(line.measures[: measure + 1]):
        for at, entries in m.keys:
            if index < measure or at <= event:
                found = entries
    return found


def time_at(line: StaffLine, measure: int) -> tuple[int, int] | None:
    found = None
    for m in line.measures[: measure + 1]:
        for _, time in m.times:
            found = time
    return found


def _key_commas(entries: list[tuple[str, str]]) -> dict[str, int]:
    return {step: LIFT_COMMAS.get(lift, 0) for step, lift in entries if LIFT_COMMAS.get(lift, 0)}


# --- token rows ---------------------------------------------------------------------------------------------------


@dataclass
class Row:
    """One token line; unverified names the fields written with "?" (the loss skips them)."""

    rhythm: str
    pitch: str = nonote
    lift: str = nonote
    articulation: str = nonote
    position: str = nonote
    unverified: frozenset[str] = frozenset()
    clef_octave: int = 0  # for the round trip only: the octave clef the tokens cannot hold

    def text(self) -> str:
        values = (self.rhythm, self.pitch, self.lift, self.articulation)
        fields = [
            "?" + value if branch in self.unverified and value != nonote else value
            for branch, value in zip(BRANCHES, values, strict=True)
        ]
        return " ".join([*fields, self.position])

    def symbol(self) -> EncodedSymbol:
        symbol = EncodedSymbol(self.rhythm, self.pitch, self.lift, self.articulation, self.position)
        return symbol.with_clef_octave(self.clef_octave) if self.clef_octave else symbol

    def masked(self) -> Row:
        return Row(self.rhythm, self.pitch, self.lift, self.articulation, self.position, ALL_BRANCHES,
                   self.clef_octave)

    def check(self) -> None:
        """Raises LabelError if the model's vocabulary cannot hold the row."""
        v = _vocabulary
        if (self.rhythm not in v.rhythm or self.pitch not in v.pitch or self.lift not in v.lift
                or self.articulation not in v.articulation or self.position not in v.position):
            raise LabelError(f"sözlükte yok: {self.text()}")
        if not self.symbol().is_valid():
            raise LabelError(f"geçersiz satır: {self.text()}")


def row_texts(rows: list[Row]) -> list[str]:
    return [row.text() for row in rows]


@dataclass
class Piece:
    """The part of a corrected measure that one staff image shows: all of it, or the events before or after the
    line break of a measure the page breaks over two staffs."""

    measure: int  # index into the StaffLine's measures
    first: int  # first event
    last: int  # one past the last event
    starts: bool  # the measure begins on this staff
    ends: bool  # ... and ends on it
    masked: bool = False  # nobody looked at it: every field unverified


@dataclass
class Hints:
    """What the model's reading of the page says about one staff (see the module's docstring)."""

    events: dict[str, Event] = field(default_factory=dict)  # model events by the app's id
    drawn: bool = True  # the reading's <accidental>s show the drawn signs (not for the base model's staffs)
    twins: dict[int, Measure] = field(default_factory=dict)  # corrected measure index -> its model measure, 1:1
    edited: dict[int, set[str]] = field(default_factory=dict)  # corrected measure index -> its record's turler
    key_at_start: bool | None = None  # the reading has a key signature at the head of this staff (None: unknown)
    key_order: list[str] | None = None  # ... in this order of steps
    time_at_start: bool | None = None
    # islemler.json has an olcu-isareti on the first measure: its time signature is the user's, not the default
    # the app's writer puts there
    meter_set_first: bool = False
    # the reading's last measure and the corrected line's last measure (index): the barline that closes the score
    # is the reading's, the app writes a light-heavy one there whatever the page has
    reading_end: Measure | None = None
    last_measure: int | None = None
    # the kinds of mark (mark_kind) the corrected file holds itself: those are the user's, the others the reading's
    carried: frozenset[str] = frozenset()


def _kern(event: Event) -> str:
    base = TYPE_KERN.get(event.type)
    if base is None:
        raise LabelError(f"süre türü yok: '{event.type}'")
    if event.tuplet is not None and base:
        actual, normal = event.tuplet
        value = Fraction(base * actual, normal)
        if value.denominator != 1:
            raise LabelError(f"üçleme {actual}:{normal} {event.type} jetonla yazılamaz")
        base = int(value)
    return str(base)


def _twin(event: Event, hints: Hints) -> Event | None:
    """The reading's note this note was, with the same pitch: whose drawn sign it can take."""
    twin = _same_event(event, hints)
    if twin is None or not twin.is_note:
        return None
    return twin if (twin.step, twin.octave) == (event.step, event.octave) else None


def _same_event(event: Event, hints: Hints) -> Event | None:
    """The reading's event this event was (the app keeps the id), whatever the user changed in it: the marks drawn
    over and under it stay its own."""
    twin = hints.events.get(event.note_id or "")
    return None if twin is None or twin.is_grace else twin


def carried_marks(lines: list[StaffLine]) -> frozenset[str]:
    """The kinds of mark a corrected file holds, found in the file itself.

    TODO(fermata): the app is to read and write fermatas (and may other marks later). A file that holds one proves
    that its writer keeps that kind, and then that kind is taken from the corrected file, as the user left it. A
    file that holds none cannot tell "kept, but none on this page" (or the user took the reading's away) from "not
    kept", so the reading's then come back, unverified. When the package says what its MusicXML keeps (a new
    bicim than musiki-akademisi-duzeltme/1, or a manifest field listing it), take the kinds from there instead.
    """
    return frozenset(mark_kind(name) for line in lines for m in line.measures for e in m.events for name in e.marks)


def _articulation(ties: set[str], own: set[str], read: set[str]) -> tuple[str, bool]:
    """The articulation field and whether it is unverified: the ties and the marks the corrected file holds are
    the user's, the reading's other marks are not. A combination the vocabulary does not hold (it knows the ones
    the Lieder set has) keeps as many of the reading's marks as it can, the fermata first: it is the mark the app
    loses for sure and the training sets hold least."""
    names = sorted(read)
    subsets = [set(c) for size in range(len(names), -1, -1) for c in combinations(names, size)]
    subsets.sort(key=lambda c: ("fermata" not in c, -len(c)))
    for marks in subsets:
        text = "_".join(sorted(ties | own | marks)) or empty
        if text in _vocabulary.articulation:
            return text, bool(read)
    text = "_".join(sorted(ties)) or empty
    return (text if text in _vocabulary.articulation else empty), True


def _marks_of(event: Event, hints: Hints) -> tuple[set[str], set[str]]:
    """The event's marks: those of the kinds the corrected file holds, from it; the others from the reading's
    same event. A rest the user made of a note keeps only its fermata."""
    own = {m for m in event.marks if mark_kind(m) in hints.carried}
    same = _same_event(event, hints)
    read = {m for m in same.marks if mark_kind(m) not in hints.carried} if same is not None else set()
    if not event.is_note and same is not None and same.is_note:
        read &= {"fermata"}
    return own, read


def event_row(event: Event, octave_shift: int, hints: Hints) -> Row:
    if not event.is_note:
        rhythm = ("rest_1" if event.measure_rest or (event.type == "whole" and not event.tuplet)
                  else f"rest_{_kern(event)}{'.' * event.dots}")
        own, read = _marks_of(event, hints)
        articulation, doubtful = _articulation(set(), own, read)
        return Row(rhythm, empty, empty, articulation, "upper",
                   frozenset({"articulation"}) if doubtful else frozenset())
    if event.drawn is not None and event.drawn.startswith("unknown:"):
        raise LabelError(f"bilinmeyen arıza: {event.drawn[8:]}")
    rhythm = f"note_{_kern(event)}{'G' if event.is_grace else ''}{'.' * event.dots}"
    pitch = f"{event.step}{(event.octave or 0) + octave_shift}"
    unverified: set[str] = set()
    twin = _twin(event, hints)
    lift = event.drawn or empty
    if twin is not None and hints.drawn and twin.commas == event.commas:
        if event.drawn is None and twin.drawn is not None and LIFT_COMMAS.get(twin.drawn) == event.commas:
            # the reading saw a sign that says what the note sounds anyway (a courtesy sign): the app's file
            # leaves it out, the page may well print it
            lift = twin.drawn
            unverified.add("lift")
        elif event.drawn is not None and twin.drawn is None:
            # the app wants a sign where the reading saw none and still heard the same pitch
            unverified.add("lift")
    ties = {name for name, on in (("tieStart", event.tie_start), ("tieStop", event.tie_stop)) if on}
    own, read = _marks_of(event, hints)
    articulation, doubtful = _articulation(ties, own, read)
    if doubtful:
        unverified.add("articulation")
    return Row(rhythm, pitch, lift, articulation, "upper", frozenset(unverified))


def key_rows(entries: list[tuple[str, str]], clef: Clef, order: list[str] | None) -> list[Row]:
    shift = KEY_SHIFT.get((clef.sign, clef.line))
    if entries and shift is None:
        raise LabelError(f"donanım işaretlerinin yeri bilinmiyor: {clef.sign}{clef.line} anahtarı")
    if order is not None and sorted(order) == sorted(step for step, _ in entries):
        lifts = dict(entries)
        entries = [(step, lifts[step]) for step in order]
    rows = []
    for step, lift in entries:
        if lift not in LIFT_COMMAS or step not in SHARP_PLACES:
            raise LabelError(f"donanımda bilinmeyen arıza: {step} {lift}")
        places = FLAT_PLACES if LIFT_COMMAS[lift] < 0 else SHARP_PLACES
        # staff steps above the bottom line, counted as steps from C0
        degree = BOTTOM_LINE[(clef.sign, clef.line)] + places[step] - (shift or 0)
        rows.append(Row(key_accidental, f"{STEPS[degree % 7]}{degree // 7}", lift, empty, "upper"))
    return rows


def time_row(time: tuple[int, int]) -> Row:
    rhythm = f"timeSignature_{time[0]}/{time[1]}"
    if rhythm not in _vocabulary.rhythm:
        raise LabelError(f"ölçü işareti sözlükte yok: {time[0]}/{time[1]}")
    return Row(rhythm)


def closing_rows(measure: Measure, reading: Measure | None) -> list[Row]:
    """The tokens that close a measure: a repeat or an ending's end as the corrected file has it, else the
    barline style the reading saw on the same measure (unverified: the app draws every barline plain, and the last
    one light-heavy), else a plain barline. The corrected file's own bar-style is never used."""
    stop = {"stop": "voltaStop", "discontinue": "voltaDiscontinue"}.get(measure.ending_stop or "")
    if measure.repeat_end:
        return [Row("repeatEnd")] + ([Row(stop)] if stop else [])
    if stop:
        return [Row(stop)]
    style = STYLE_TOKENS.get(reading.right_style or "") if reading is not None else None
    if style:
        return [Row(style, unverified=frozenset({"rhythm"}))]
    return [Row("barline")]


def _time_printed(line: StaffLine, measure: int, hints: Hints, at_start: bool) -> bool:
    """Whether the page prints a time signature at the start of this measure. The app writes one in the first
    measure whatever the page has, and elsewhere only where the meter changes. In the first measure it is the
    page's when the reading has one there or the user set it (islemler.json olcu-isareti), else the default."""
    m = line.measures[measure]
    if measure == 0 and hints.meter_set_first:
        return True
    if measure > 0 and any(at == 0 for at, _ in m.times):
        return True
    if "olcu-isareti" in hints.edited.get(measure, set()):
        return True
    if at_start and hints.time_at_start is not None:
        return hints.time_at_start
    twin = hints.twins.get(measure)
    if twin is not None:
        return any(at == 0 for at, _ in twin.times)
    return measure == 0 and bool(m.times)


def staff_rows(line: StaffLine, pieces: list[Piece], hints: Hints) -> list[Row]:
    """The token rows of one staff image, in the order the training sets write them: clef, key signature, time
    signature where printed, then measure by measure the opening repeat and ending, the notes with the jumps where
    they stand, and the closing barline."""
    if not pieces:
        raise LabelError("portede ölçü yok")
    head = pieces[0]
    clef = clef_at(line, head.measure, head.first)
    if clef is None:
        raise LabelError("anahtar yok")
    octave_shift = -clef.octave  # the tokens hold the staff position, which an octave clef moves from the pitch
    rows = [Row(f"clef_{clef.sign}{clef.line}", empty, empty, empty, "upper", clef_octave=clef.octave)]
    if hints.key_at_start is not False or "donanim" in hints.edited.get(head.measure, set()):
        rows += key_rows(key_at(line, head.measure, head.first), clef, hints.key_order)
    if head.starts and _time_printed(line, head.measure, hints, at_start=True):
        time = time_at(line, head.measure)
        if time is not None:
            rows.append(time_row(time).masked() if head.masked else time_row(time))
    for number, piece in enumerate(pieces):
        measure = line.measures[piece.measure]
        events = measure.events
        if measure.unknown:
            raise LabelError(f"ölçü {measure.number}: {', '.join(measure.unknown)}")
        out: list[Row] = []
        if piece.starts:
            if number > 0:
                twin = hints.twins.get(piece.measure)
                if any(at == 0 for at, _ in measure.keys) or (twin is not None and any(at == 0 for at, _ in twin.keys)):
                    out += key_rows(key_at(line, piece.measure), clef, None)
                if _time_printed(line, piece.measure, hints, at_start=False):
                    time = time_at(line, piece.measure)
                    if time is not None:
                        out.append(time_row(time))
            if measure.repeat_start:
                out.append(Row("repeatStart"))
            if measure.ending_start:
                out.append(Row("voltaStart"))
        low = None if piece.starts else events[piece.first].offset
        high = None if piece.ends else events[piece.last].offset
        jumps = sorted(
            (offset, kind) for offset, kind in measure.jumps
            if (low is None or offset >= low) and (high is None or offset < high)
        )
        for event in events[piece.first : piece.last]:
            while jumps and jumps[0][0] <= event.offset:
                out.append(Row(jumps.pop(0)[1]))
            out.append(event_row(event, octave_shift, hints))
        out += [Row(kind) for _, kind in jumps]
        if piece.ends:
            reading = hints.twins.get(piece.measure)
            if reading is None and piece.measure == hints.last_measure:
                reading = hints.reading_end  # the last measure, merged or split by the user: the reading's end
            out += closing_rows(measure, reading)
        rows += [row.masked() for row in out] if piece.masked else out
    for row in rows:
        row.check()
    return rows


def writer_defaults(line: StaffLine, model: StaffLine | None, meter_set_first: bool) -> list[str]:
    """What the app's writer put into this line by itself, which the labels do not take as the page's: a
    light-heavy barline after the last measure the reading does not have, and a first-measure time signature the
    reading does not have and the user did not set."""
    found: list[str] = []
    if not line.measures:
        return found
    last = line.measures[-1]
    if last.right_style == "light-heavy" and not last.repeat_end and (
        model is None or not model.measures or model.measures[-1].right_style != "light-heavy"
    ):
        found.append(f"son ölçü çizgisi (ölçü {last.number}, ince-kalın)")
    first = line.measures[0]
    times = [t for at, t in first.times if at == 0]
    if times and not meter_set_first and (
        model is not None and model.measures and not any(at == 0 for at, _ in model.measures[0].times)
    ):
        found.append(f"1. ölçünün ölçü işareti ({times[0][0]}/{times[0][1]})")
    return found


# --- the round trip -----------------------------------------------------------------------------------------------


def _start_states(line: StaffLine) -> list[tuple[dict[str, int], tuple[int, int] | None, tuple | None]]:
    """Per measure: the key (step -> commas), meter and clef in force at its start."""
    states = []
    key: dict[str, int] = {}
    time: tuple[int, int] | None = None
    clef: tuple | None = None
    for m in line.measures:
        for at, entries in m.keys:
            if at == 0:
                key = _key_commas(entries)
        for at, value in m.times:
            if at == 0:
                time = value
        for at, found in m.clefs:
            if at == 0:
                clef = (found.sign, found.line, found.octave)
        states.append((key, time, clef))
        for at, entries in m.keys:
            if at > 0:
                key = _key_commas(entries)
        for at, value in m.times:
            if at > 0:
                time = value
        for at, found in m.clefs:
            if at > 0:
                clef = (found.sign, found.line, found.octave)
    return states


def _event_text(event: Event) -> str:
    if not event.is_note:
        return f"sus {event.type}{'.' * event.dots}"
    sign = f"{event.commas:+d}" if event.commas else ""
    grace = " süsleme" if event.is_grace else ""
    return f"{event.step}{event.octave}{sign} {event.type}{'.' * event.dots}{grace}"


def compare_measure(corrected: Measure, written: Measure) -> list[str]:
    """What differs between a corrected measure and the same measure written back from the tokens."""
    problems = []
    if len(corrected.events) != len(written.events):
        problems.append(f"{len(corrected.events)} olay yerine {len(written.events)}")
    for k, (a, b) in enumerate(zip(corrected.events, written.events, strict=False), 1):
        if a.is_note != b.is_note or a.is_grace != b.is_grace:
            problems.append(f"olay {k}: {_event_text(a)} yerine {_event_text(b)}")
            continue
        if a.is_note and (a.step, a.octave, a.commas) != (b.step, b.octave, b.commas):
            problems.append(f"olay {k}: {_event_text(a)} yerine {_event_text(b)}")
        whole_rest = not a.is_note and (a.measure_rest or a.type == "whole")
        if not whole_rest:
            if (a.type, a.dots, a.tuplet) != (b.type, b.dots, b.tuplet):
                problems.append(f"olay {k}: süre {_event_text(a)} yerine {_event_text(b)}")
            elif not a.is_grace and a.duration != b.duration:
                problems.append(f"olay {k}: süre {a.duration} yerine {b.duration} dörtlük")
        if a.is_note and (a.tie_start, a.tie_stop) != (b.tie_start, b.tie_stop):
            problems.append(f"olay {k}: bağ")
    if (corrected.repeat_start, corrected.repeat_end) != (written.repeat_start, written.repeat_end):
        problems.append("tekrar işareti")
    if (corrected.ending_start, corrected.ending_stop is not None) != (written.ending_start,
                                                                        written.ending_stop is not None):
        problems.append("volta")
    if Counter(k for _, k in corrected.jumps) != Counter(k for _, k in written.jumps):
        problems.append("atlama işareti")
    return problems


def round_trip(staffs: list[tuple[list[Row], list[int]]], line: StaffLine) -> dict[int, list[str]]:
    """Write the staffs' rows (in page order, each with the corrected measures it shows) back with homr's writer,
    joined by newline as the service joins its staffs, and compare every measure with the corrected one.
    Returns the problems by corrected measure index; a measure without problems is not in it."""
    stream: list[EncodedSymbol] = []
    order: list[int] = []
    for rows, measures in staffs:
        stream += [row.symbol() for row in rows]
        stream.append(EncodedSymbol("newline"))
        for index in measures:
            if line.measures[index].events and (not order or order[-1] != index):
                order.append(index)
    problems: dict[int, list[str]] = {}
    try:
        text = generate_xml(XmlGeneratorArguments(), [stream], "").to_string()
        written = read_lines(text, HOMR_COMMA)[0]
    except Exception as error:  # noqa: BLE001
        return {index: [f"yazıcı hatası: {error}"] for index in order}
    if len(written.measures) != len(order):
        message = f"yazıcı {len(written.measures)} ölçü yazdı, düzeltmede {len(order)} ölçü var"
        return {index: [message] for index in order}
    corrected_states = _start_states(line)
    written_states = _start_states(written)
    for k, index in enumerate(order):
        found = compare_measure(line.measures[index], written.measures[k])
        (key, time, clef), (written_key, written_time, written_clef) = corrected_states[index], written_states[k]
        if key != written_key:
            found.append(f"donanım {key} yerine {written_key}")
        if written_time is not None and time != written_time:
            found.append(f"ölçü işareti {time} yerine {written_time}")
        if clef != written_clef:
            found.append(f"anahtar {clef} yerine {written_clef}")
        if found:
            problems[index] = [f"ölçü {line.measures[index].number}: {p}" for p in found]
    return problems
