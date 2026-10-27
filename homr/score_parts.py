"""A score of several staffs per system, each staff read on its own, written as MusicXML parts.

homr's reader merges a grand staff into one image and pairs the staffs of a system two by two; the makam model
then reads only the top line of a merged grand staff. The service instead reads every staff alone and puts the
readings together here, by the layout found on the page (homr.staff_groups):

- a brace makes its staffs one part of as many staves (a piano: <staves>2</staves>, every note with its <staff>),
  inside a <part-group> with the brace symbol;
- a bracket makes a <part-group> with the bracket symbol over one part per staff;
- every other staff is a part of its own.

The parts come from the system with the most staffs (the most common layout among those). Another system with as
many staffs fills the same parts staff by staff; one with fewer staffs fills the parts whose clefs and braces fit
it best, in order, and the parts it lacks get a whole-measure rest. Within a system every part gets as many
measures as its longest staff reading; a shorter one is filled up with whole-measure rests, so that a misread
barline does not shift the parts against each other beyond its own system.

Also here: the test the service routes a staff to homr's base model by (is_polyphonic) and the reduction of a
polyphonic reading to one line (top_voice).
"""

import copy
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field

from homr.music_xml_generator import (
    XmlGeneratorArguments,
    _header_text,
    _part_metadata,
    build_defaults,
    build_identification,
    build_staff_measures,
    build_tempo_direction,
    build_work,
    stream_division,
)
from homr.staff_groups import BRACE, BRACKET, StaffGroup
from homr.transformer.vocabulary import EncodedSymbol, empty, sort_token_chords

# the order of <attributes>' children in the MusicXML 4.0 schema
_ATTRIBUTE_ORDER = (
    "footnote",
    "level",
    "divisions",
    "key",
    "time",
    "staves",
    "part-symbol",
    "instruments",
    "clef",
    "staff-details",
    "transpose",
    "for-part",
    "directive",
    "measure-style",
)
_STEPS = "CDEFGAB"
# voices per staff, as homr numbers them (music_xml_generator.get_xml_voice): staff 2 has voices 5-8
_VOICES_PER_STAFF = 4


def is_polyphonic(symbols: list[EncodedSymbol]) -> bool:
    """What the base model's reading of a staff shows that the makam model cannot read: a chord, a symbol on a
    second staff, or a clef other than the treble clef. The polyphony exam's hybrid reader took such staffs from
    the base model and every other staff from the makam model (note F1 0.90 overall, 0.95 on makam melodies)."""
    for symbol in symbols:
        if symbol.rhythm == "chord" or symbol.position == "lower":
            return True
        if symbol.rhythm.startswith("clef_") and symbol.rhythm != "clef_G2":
            return True
    return False


def on_one_staff(symbols: list[EncodedSymbol]) -> list[EncodedSymbol]:
    """A staff read alone is one staff: what the model put on a lower staff goes on it too."""
    return [symbol.to_upper_position() for symbol in symbols]


def _is_grace(symbol: EncodedSymbol) -> bool:
    return "G" in symbol.rhythm.split("_", 1)[-1]


def _is_pitched_note(symbol: EncodedSymbol) -> bool:
    return (
        symbol.rhythm.startswith("note")
        and len(symbol.pitch) >= 2
        and symbol.pitch[0] in _STEPS
        and symbol.pitch[1:].lstrip("-").isdigit()
    )


def _height(symbol: EncodedSymbol) -> tuple[int, int]:
    return int(symbol.pitch[1:]), _STEPS.index(symbol.pitch[0])


def top_voice(symbols: list[EncodedSymbol]) -> tuple[list[EncodedSymbol], bool]:
    """One line out of a reading with chords and second voices, and whether anything was left out.

    At every onset the highest note that starts there is kept (of a chord: its highest pitch), lasting until the
    next onset: a held note of the upper voice under which a lower voice moves is cut where the lower voice moves
    on, and the line goes on with what starts there (the "skyline" of the staff). A cut note loses a tie it
    started. Where only rests start, the shortest is kept. Grace notes in a chord go with it."""
    result: list[EncodedSymbol] = []
    reduced = False
    for group in sort_token_chords(symbols):
        if len(group) == 1:
            result.append(group[0])
            continue
        reduced = True
        timed = [s for s in group if s.rhythm.startswith(("note", "rest"))]
        if not timed:
            result.extend(group)
            continue
        result.extend(s for s in group if s not in timed)
        notes = [s for s in timed if _is_pitched_note(s) and not _is_grace(s)]
        lasting = [s for s in timed if not _is_grace(s) and s.get_duration().fraction > 0]
        if notes:
            top = max(notes, key=_height)
            shortest = min(lasting, key=lambda s: s.get_duration().fraction) if lasting else top
            if shortest.get_duration().fraction < top.get_duration().fraction:
                cut = copy.copy(top)
                cut.rhythm = "note_" + shortest.rhythm.split("_", 1)[1]
                cut._duration = None
                kept = [a for a in top.articulation.split("_") if a and a != "tieStart"]
                cut.articulation = "_".join(kept) if kept else empty
                top = cut
            result.append(top)
        elif lasting:
            result.append(min(lasting, key=lambda s: s.get_duration().fraction))
        else:
            graces = [s for s in timed if _is_pitched_note(s)]
            result.append(max(graces, key=_height) if graces else timed[0])
    return result, reduced


# ----------------------------------------------------------------------------- layout


@dataclass
class SystemLayout:
    """A system on the page: how many staffs it has, the braces and brackets over them and the names printed
    beside its slots (homr.part_names), when read."""

    staffs: int
    groups: list[StaffGroup] = field(default_factory=list)
    names: list[str | None] = field(default_factory=list)

    def slots(self) -> list[list[int]]:
        """The system's staffs by part: a braced run of staffs is one slot, every other staff a slot alone."""
        braced = {g.first: g.last for g in self.groups if g.kind == BRACE}
        result, k = [], 0
        while k < self.staffs:
            last = min(braced.get(k, k), self.staffs - 1)
            result.append(list(range(k, last + 1)))
            k = last + 1
        return result

    def signature(self) -> tuple:
        slots = self.slots()
        slot_of = {k: n for n, slot in enumerate(slots) for k in slot}
        brackets = tuple(
            (slot_of[g.first], slot_of[min(g.last, self.staffs - 1)])
            for g in self.groups
            if g.kind == BRACKET and g.first < self.staffs
        )
        return tuple(len(slot) for slot in slots), brackets


@dataclass
class Part:
    staves: int
    brace: bool
    name: str | None = None


@dataclass
class ScorePlan:
    parts: list[Part]
    # (first part, last part) of every bracket
    brackets: list[tuple[int, int]]
    # per system, per staff from the top: (part, staff in that part from 1), None for a staff left out
    placement: list[list[tuple[int, int] | None]]


def _fit(clefs: list[str | None], braced: list[bool], ref_clefs: list[str | None], ref_braced: list[bool]) -> list[int]:
    """The reference staffs a system's fewer staffs go to: in order, as many clefs and brace memberships alike
    as possible (a voice and piano score whose voice rests for a system: the piano stays the piano)."""
    n, m = len(clefs), len(ref_clefs)
    score = [[-1.0] * (m + 1) for _ in range(n + 1)]
    choice: dict[tuple[int, int], bool] = {}
    for j in range(m + 1):
        score[0][j] = 0.0
    for i in range(1, n + 1):
        for j in range(i, m + 1):
            skip = score[i][j - 1] if j - 1 >= i else -1.0
            alike = (clefs[i - 1] is not None and clefs[i - 1] == ref_clefs[j - 1]) + (
                braced[i - 1] == ref_braced[j - 1]
            )
            take = score[i - 1][j - 1] + alike if score[i - 1][j - 1] >= 0 else -1.0
            # on a tie the lower placement: the backtrack gives the last staff the last fitting place
            if take >= skip:
                score[i][j], choice[(i, j)] = take, True
            else:
                score[i][j], choice[(i, j)] = skip, False
    picked, i, j = [], n, m
    while i > 0:
        if choice[(i, j)]:
            picked.append(j - 1)
            i -= 1
        j -= 1
    return picked[::-1]


def plan_score(layouts: list[SystemLayout], clefs: list[list[str | None]] | None = None) -> ScorePlan:
    """The parts of the score and where every staff of every system goes. clefs, when known, are the first clef
    each staff was read with (per system, per staff), to fit a system with fewer staffs."""
    clefs = clefs or [[None] * layout.staffs for layout in layouts]
    most = max(layout.staffs for layout in layouts)
    candidates = [n for n, layout in enumerate(layouts) if layout.staffs == most]
    common = Counter(layouts[n].signature() for n in candidates).most_common(1)[0][0]
    ref_no = next(n for n in candidates if layouts[n].signature() == common)
    ref = layouts[ref_no]
    parts, ref_staffs, ref_braced = [], [], []
    for slot in ref.slots():
        number = len(parts)
        parts.append(Part(len(slot), len(slot) > 1))
        ref_staffs.extend((number, k + 1) for k in range(len(slot)))
        ref_braced.extend([len(slot) > 1] * len(slot))
    part_of = {k: ref_staffs[k][0] for k in range(ref.staffs)}
    brackets = sorted(
        {
            (part_of[g.first], part_of[min(g.last, ref.staffs - 1)])
            for g in ref.groups
            if g.kind == BRACKET and g.first < ref.staffs
        }
    )
    placement: list[list[tuple[int, int] | None]] = []
    for n, layout in enumerate(layouts):
        if layout.staffs == ref.staffs:
            placement.append(list(ref_staffs))
            continue
        braced = [False] * layout.staffs
        for slot in layout.slots():
            for k in slot:
                braced[k] = len(slot) > 1
        picked = _fit(clefs[n], braced, clefs[ref_no], ref_braced)
        placement.append([ref_staffs[j] for j in picked])
    # a part is named by the first system that prints a name beside it (the first system names in full)
    for n, layout in enumerate(layouts):
        for slot, name in zip(layout.slots(), layout.names, strict=False):
            part = placement[n][slot[0]][0] if placement[n][slot[0]] is not None else None
            if name and part is not None and parts[part].name is None:
                parts[part].name = name
    return ScorePlan(parts, brackets, placement)


# ----------------------------------------------------------------------------- writing


@dataclass
class StaffReading:
    """One staff's symbols (no newline) and where it stands: its system and its place there from the top."""

    system: int
    staff: int
    symbols: list[EncodedSymbol]


@dataclass
class WrittenScore:
    musicxml: str  # without the XML declaration
    # (first, last) measure of every reading, in the order given; None for a reading of no measure
    measures: list[tuple[int, int] | None]
    # lowest symbol confidence of every measure over all its staffs
    confidence: dict[int, float]


def _element(xml_element) -> ET.Element:  # noqa: ANN001  (a musicxml library element)
    return ET.fromstring(xml_element.to_string())


def _duration(element: ET.Element) -> int:
    return int(element.findtext("duration") or 0)


def _cursor(children: list[ET.Element]) -> tuple[int, int]:
    """Where the time cursor stands after the children, and the furthest it went."""
    cursor = furthest = 0
    for child in children:
        if child.tag == "note":
            if child.find("chord") is None and child.find("grace") is None:
                cursor += _duration(child)
        elif child.tag == "backup":
            cursor -= _duration(child)
        elif child.tag == "forward":
            cursor += _duration(child)
        furthest = max(furthest, cursor)
    return cursor, furthest


def _measure_rest(length: int, staff: int) -> list[ET.Element]:
    if length <= 0:
        return []
    note = ET.Element("note")
    ET.SubElement(note, "rest", measure="yes")
    ET.SubElement(note, "duration").text = str(length)
    ET.SubElement(note, "voice").text = str((staff - 1) * _VOICES_PER_STAFF + 1)
    ET.SubElement(note, "staff").text = str(staff)
    return [note]


def _timing(tag: str, value: int) -> ET.Element:
    element = ET.Element(tag)
    ET.SubElement(element, "duration").text = str(value)
    return element


def _insert_attribute(attributes: ET.Element, element: ET.Element) -> None:
    rank = _ATTRIBUTE_ORDER.index(element.tag)
    for index, child in enumerate(attributes):
        if child.tag in _ATTRIBUTE_ORDER and _ATTRIBUTE_ORDER.index(child.tag) > rank:
            attributes.insert(index, element)
            return
    attributes.append(element)


def _onto_staff(children: list[ET.Element], staff: int, first_staff_times: bool) -> list[ET.Element]:
    """A lower staff's measure content for a part of several staves: its notes on that staff and in its voices,
    its clef and key numbered, no divisions (the part's first staff gives them) and no system break; its time
    signature only where the first staff has none."""
    shift = (staff - 1) * _VOICES_PER_STAFF
    result = []
    for child in children:
        if child.tag == "print":
            continue
        if child.tag in ("note", "forward"):
            if child.find("staff") is not None:
                child.find("staff").text = str(staff)
            else:
                ET.SubElement(child, "staff").text = str(staff)
            voice = child.find("voice")
            if voice is not None and (voice.text or "").strip().isdigit():
                voice.text = str(int(voice.text) + shift)
        elif child.tag == "attributes":
            for removed in child.findall("divisions"):
                child.remove(removed)
            if first_staff_times:
                for removed in child.findall("time"):
                    child.remove(removed)
            for numbered in child.findall("clef") + child.findall("key"):
                numbered.set("number", str(staff))
            if len(child) == 0:
                continue
        result.append(child)
    return result


def _merge_staves(contents: list[ET.Element | None], number: int, length: int) -> ET.Element:
    """One measure of a part from its staves' measures (None: the staff has none here, a whole-measure rest)."""
    merged = ET.Element("measure", number=str(number))
    if len(contents) == 1:
        merged.extend(list(contents[0]) if contents[0] is not None else _measure_rest(length, 1))
        return merged
    barlines: dict[str, ET.Element] = {}
    first_staff_times = contents[0] is not None and contents[0].find("attributes/time") is not None
    cursor = 0
    for staff, content in enumerate(contents, 1):
        children = list(content) if content is not None else _measure_rest(length, staff)
        if staff > 1:
            children = _onto_staff(children, staff, first_staff_times)
        body = []
        for child in children:
            if child.tag == "barline":
                barlines.setdefault(child.get("location", "right"), child)
            else:
                body.append(child)
        if staff > 1 and cursor > 0 and body:
            merged.append(_timing("backup", cursor))
        merged.extend(body)
        cursor, _ = _cursor(body)
    if "left" in barlines:
        merged.insert(0, barlines.pop("left"))
    merged.extend(barlines.values())
    return merged


def _first_attributes(measure: ET.Element) -> ET.Element:
    """The measure's <attributes> before its first note, made at its start if it has none."""
    for child in measure:
        if child.tag == "attributes":
            return child
        if child.tag in ("note", "backup", "forward"):
            break
    attributes = ET.Element("attributes")
    measure.insert(0, attributes)
    return attributes


def _part_list(plan: ScorePlan) -> ET.Element:
    part_list = ET.Element("part-list")
    groups = [(first, last, BRACKET) for first, last in plan.brackets]
    groups += [(p, p, BRACE) for p, part in enumerate(plan.parts) if part.brace]
    # outer groups open first and close last
    groups.sort(key=lambda g: (g[0], -g[1], g[2] != BRACKET))
    numbers = {group: n for n, group in enumerate(groups, 1)}
    for index, part in enumerate(plan.parts):
        for group in groups:
            if group[0] == index:
                start = ET.SubElement(part_list, "part-group", type="start", number=str(numbers[group]))
                ET.SubElement(start, "group-symbol").text = group[2]
        name, instrument, sound, program = _part_metadata(part.staves > 1)
        part_id = f"P{index + 1}"
        score_part = ET.SubElement(part_list, "score-part", id=part_id)
        ET.SubElement(score_part, "part-name").text = part.name or name
        score_instrument = ET.SubElement(score_part, "score-instrument", id=part_id + "-I1")
        ET.SubElement(score_instrument, "instrument-name").text = instrument
        ET.SubElement(score_instrument, "instrument-sound").text = sound
        midi = ET.SubElement(score_part, "midi-instrument", id=part_id + "-I1")
        ET.SubElement(midi, "midi-channel").text = str(index % 16 + 1)
        ET.SubElement(midi, "midi-program").text = str(program)
        ET.SubElement(midi, "volume").text = "100"
        ET.SubElement(midi, "pan").text = "0"
        for group in sorted(groups, key=lambda g: -g[0]):
            if group[1] == index:
                ET.SubElement(part_list, "part-group", type="stop", number=str(numbers[group]))
    return part_list


def write_score(
    args: XmlGeneratorArguments,
    layouts: list[SystemLayout],
    readings: list[StaffReading],
    plan: ScorePlan,
) -> WrittenScore:
    """The score of the readings, laid out by plan. Uses from args: software, header, tempo_marks (by measure
    number of the score, written in the first part) and split_rest_chords."""
    systems = len(layouts)
    # per part and staff in it: the reading of every system (index into readings, or None)
    streams: dict[tuple[int, int], list[int | None]] = {
        (p, k): [None] * systems for p, part in enumerate(plan.parts) for k in range(1, part.staves + 1)
    }
    for index, reading in enumerate(readings):
        place = plan.placement[reading.system][reading.staff]
        if place is not None and streams[place][reading.system] is None:
            streams[place][reading.system] = index
    # one division for the whole score: the staffs of a part must share it, and a whole-measure rest that fills up
    # one part is as long as another part's measure
    division = stream_division([s for reading in readings for s in reading.symbols])
    # every staff of every part, built as one staff over all systems: its measures by system
    built: dict[tuple[int, int], list[list[ET.Element]]] = {}
    confidences: dict[tuple[int, int], list[dict[int, float]]] = {}
    for (p, k), segments in streams.items():
        present = [s for s in range(systems) if segments[s] is not None]
        stream: list[EncodedSymbol] = []
        for s in present:
            stream += readings[segments[s]].symbols + [EncodedSymbol("newline")]
        staff_args = XmlGeneratorArguments(
            software=args.software, measure_confidence={}, staff_measures=[],
            split_rest_chords=args.split_rest_chords,
        )
        measures = [_element(m) for m in build_staff_measures(staff_args, stream, division)] if stream else []
        by_system: list[list[ET.Element]] = [[] for _ in range(systems)]
        sure: list[dict[int, float]] = [{} for _ in range(systems)]
        done = 0
        for s, (first, last) in zip(present, staff_args.staff_measures, strict=False):
            first = max(first, done + 1)  # a measure run on into the next system stays with the first
            by_system[s] = measures[first - 1 : last]
            sure[s] = {m - first: staff_args.measure_confidence[m] for m in range(first, last + 1)
                       if m in staff_args.measure_confidence}
            done = max(done, last)
        built[(p, k)], confidences[(p, k)] = by_system, sure

    root = ET.Element("score-partwise", version="4.0")
    root.append(_element(build_work(_header_text(args.header, "eserAdi") or "")))
    root.append(_element(build_identification(args)))
    root.append(_element(build_defaults(args)))
    root.append(_part_list(plan))
    part_elements = [ET.SubElement(root, "part", id=f"P{p + 1}") for p in range(len(plan.parts))]
    confidence: dict[int, float] = {}
    system_measures: list[tuple[int, int] | None] = []
    number = 0
    for s in range(systems):
        count = max((len(built[key][s]) for key in built), default=0)
        if count == 0:
            system_measures.append(None)
            continue
        for j in range(count):
            number += 1
            present = [built[key][s][j] for key in built if j < len(built[key][s])]
            length = max((_cursor(list(m))[1] for m in present), default=0)
            for p, part in enumerate(plan.parts):
                contents = [
                    built[(p, k)][s][j] if j < len(built[(p, k)][s]) else None for k in range(1, part.staves + 1)
                ]
                part_elements[p].append(_merge_staves(contents, number, length))
                for k in range(1, part.staves + 1):
                    if j in confidences[(p, k)][s]:
                        known = confidence.get(number, 1.0)
                        confidence[number] = min(known, confidences[(p, k)][s][j])
        system_measures.append((number - count + 1, number))
    for p, part in enumerate(plan.parts):
        measures = list(part_elements[p])
        if not measures:
            continue
        attributes = _first_attributes(measures[0])
        if attributes.find("divisions") is None:
            divisions = ET.Element("divisions")
            divisions.text = str(division // 4)
            _insert_attribute(attributes, divisions)
        if part.staves > 1:
            staves = ET.Element("staves")
            staves.text = str(part.staves)
            _insert_attribute(attributes, staves)
            symbol = ET.Element("part-symbol")
            symbol.text = BRACE
            _insert_attribute(attributes, symbol)
    if part_elements and len(part_elements[0]):
        first_part = list(part_elements[0])
        for measure_number, mark in args.tempo_marks.items():
            if 1 <= measure_number <= len(first_part):
                first_part[measure_number - 1].insert(0, _element(build_tempo_direction(*mark)))
    ET.indent(root, space="  ")
    return WrittenScore(
        ET.tostring(root, encoding="unicode"),
        [system_measures[r.system] for r in readings],
        confidence,
    )

