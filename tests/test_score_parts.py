import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import musicxml

from homr.music_xml_generator import XmlGeneratorArguments
from homr.score_parts import (
    StaffReading,
    SystemLayout,
    is_polyphonic,
    on_one_staff,
    plan_score,
    top_voice,
    write_score,
)
from homr.staff_groups import BRACE, BRACKET, StaffGroup
from homr.transformer.vocabulary import EncodedSymbol
from training.transformer.training_vocabulary import read_token_lines

XSD = Path(musicxml.__file__).parent / "generate_classes" / "musicxml_4_0.xsd"
# the schema imports the W3C xml and xlink schemas, which the package does not ship: stubs for what MusicXML uses
XLINK_STUB = b"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://www.w3.org/1999/xlink"
           attributeFormDefault="qualified">
  <xs:attribute name="href" type="xs:anyURI"/><xs:attribute name="type" type="xs:token"/>
  <xs:attribute name="role" type="xs:token"/><xs:attribute name="title" type="xs:token"/>
  <xs:attribute name="show" type="xs:token"/><xs:attribute name="actuate" type="xs:token"/>
</xs:schema>"""
XML_STUB = b"""<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" targetNamespace="http://www.w3.org/XML/1998/namespace"
           attributeFormDefault="qualified">
  <xs:attribute name="lang" type="xs:language"/><xs:attribute name="space" type="xs:NCName"/>
  <xs:attribute name="base" type="xs:anyURI"/><xs:attribute name="id" type="xs:ID"/>
</xs:schema>"""


def _schema():  # noqa: ANN202
    try:
        from lxml import etree  # noqa: PLC0415
    except ImportError:
        return None
    if not XSD.exists():
        return None
    folder = Path(tempfile.mkdtemp(prefix="mxsd_"))
    (folder / "xlink.xsd").write_bytes(XLINK_STUB)
    (folder / "xml.xsd").write_bytes(XML_STUB)
    text = XSD.read_bytes()
    text = text.replace(b"http://www.musicxml.org/xsd/xml.xsd", (folder / "xml.xsd").as_uri().encode())
    text = text.replace(b"http://www.musicxml.org/xsd/xlink.xsd", (folder / "xlink.xsd").as_uri().encode())
    return etree.XMLSchema(etree.fromstring(text, base_url=XSD.as_uri()))


def tokens(text: str) -> list[EncodedSymbol]:
    return read_token_lines([line for line in text.strip().splitlines() if line.strip()])


TREBLE = """clef_G2 . . . upper
keySignature_0 . . . .
timeSignature/4 . . . .
note_4 C5 _ _ upper
note_4 D5 _ _ upper
note_4 E5 _ _ upper
note_4 F5 _ _ upper
barline . . . .
note_2 G5 _ _ upper
note_2 A5 _ _ upper
barline . . . ."""

BASS = """clef_F4 . . . upper
keySignature_0 . . . .
timeSignature/4 . . . .
note_1 C3 _ _ upper
barline . . . .
note_2 G2 _ _ upper&note_2 G3 _ _ upper
note_2 C3 _ _ upper
barline . . . ."""

PIANO = SystemLayout(2, [StaffGroup(BRACE, 0, 1)])


def write(layouts: list[SystemLayout], readings: list[StaffReading], **kwargs) -> tuple[ET.Element, object]:
    plan = plan_score(layouts, kwargs.pop("clefs", None))
    args = XmlGeneratorArguments(software=["Test"], **kwargs)
    written = write_score(args, layouts, readings, plan)
    return ET.fromstring(written.musicxml), written


def notes(part: ET.Element) -> list[ET.Element]:
    return part.findall("./measure/note")


class TestPolyphonyTest(unittest.TestCase):
    def test_melody_is_not_polyphonic(self) -> None:
        self.assertFalse(is_polyphonic(tokens(TREBLE)))

    def test_chord_bass_clef_and_lower_staff_are(self) -> None:
        self.assertTrue(is_polyphonic(tokens("note_4 C4 _ _ upper&note_4 E4 _ _ upper")))
        self.assertTrue(is_polyphonic(tokens("clef_F4 . . . upper\nnote_4 C3 _ _ upper")))
        self.assertTrue(is_polyphonic(tokens("clef_C3 . . . upper\nnote_4 C4 _ _ upper")))
        self.assertTrue(is_polyphonic(tokens("note_4 C3 _ _ lower")))

    def test_on_one_staff(self) -> None:
        self.assertEqual({s.position for s in on_one_staff(tokens("note_4 C3 _ _ lower"))}, {"upper"})


class TestTopVoice(unittest.TestCase):
    def test_chord_keeps_its_highest_pitch(self) -> None:
        line, reduced = top_voice(tokens("note_4 C4 _ _ upper&note_4 G4 _ _ upper&note_4 E4 _ _ upper"))
        self.assertTrue(reduced)
        self.assertEqual([(s.rhythm, s.pitch) for s in line], [("note_4", "G4")])

    def test_octave_counts_before_the_step(self) -> None:
        line, _ = top_voice(tokens("note_4 B3 _ _ upper&note_4 C4 _ _ upper"))
        self.assertEqual(line[0].pitch, "C4")

    def test_held_upper_note_is_cut_where_the_lower_voice_moves(self) -> None:
        line, _ = top_voice(tokens("note_2 G4 _ tieStart upper&note_4 C4 _ _ upper\nnote_4 D4 _ _ upper"))
        self.assertEqual([(s.rhythm, s.pitch) for s in line], [("note_4", "G4"), ("note_4", "D4")])
        self.assertNotIn("tieStart", line[0].articulation)

    def test_rests_only(self) -> None:
        line, _ = top_voice(tokens("rest_2 _ _ _ upper&rest_4 _ _ _ upper"))
        self.assertEqual([s.rhythm for s in line], ["rest_4"])

    def test_melody_is_left_alone(self) -> None:
        melody = tokens(TREBLE)
        line, reduced = top_voice(melody)
        self.assertFalse(reduced)
        self.assertEqual(line, melody)


class TestPlan(unittest.TestCase):
    def test_piano_is_one_part_of_two_staves(self) -> None:
        plan = plan_score([PIANO, PIANO])
        self.assertEqual([(p.staves, p.brace) for p in plan.parts], [(2, True)])
        self.assertEqual(plan.placement, [[(0, 1), (0, 2)], [(0, 1), (0, 2)]])

    def test_choir_is_four_parts_in_a_bracket(self) -> None:
        plan = plan_score([SystemLayout(4, [StaffGroup(BRACKET, 0, 3)])])
        self.assertEqual([p.staves for p in plan.parts], [1, 1, 1, 1])
        self.assertEqual(plan.brackets, [(0, 3)])

    def test_unbraced_staffs_are_parts_of_their_own(self) -> None:
        plan = plan_score([SystemLayout(2)])
        self.assertEqual([(p.staves, p.brace) for p in plan.parts], [(1, False), (1, False)])

    def test_a_system_with_a_missed_brace_follows_the_common_layout(self) -> None:
        plan = plan_score([PIANO, SystemLayout(2), PIANO])
        self.assertEqual(len(plan.parts), 1)
        self.assertEqual(plan.placement[1], [(0, 1), (0, 2)])

    def test_parts_take_the_names_the_first_system_prints(self) -> None:
        first = SystemLayout(3, [StaffGroup(BRACE, 1, 2)], ["Soprano", "Piano"])
        later = SystemLayout(3, [StaffGroup(BRACE, 1, 2)], ["S.", None])
        plan = plan_score([first, later])
        self.assertEqual([p.name for p in plan.parts], ["Soprano", "Piano"])
        plan = plan_score([SystemLayout(3, [StaffGroup(BRACE, 1, 2)], [None, None]), later])
        self.assertEqual([p.name for p in plan.parts], ["S.", None])

    def test_piano_only_system_of_a_song_goes_to_the_piano(self) -> None:
        song = SystemLayout(3, [StaffGroup(BRACE, 1, 2)])
        plan = plan_score([song, PIANO], clefs=[["clef_G2", "clef_G2", "clef_F4"], ["clef_G2", "clef_F4"]])
        self.assertEqual([p.staves for p in plan.parts], [1, 2])
        self.assertEqual(plan.placement[1], [(1, 1), (1, 2)])


class TestWriteScore(unittest.TestCase):
    def test_piano_part(self) -> None:
        root, written = write(
            [PIANO], [StaffReading(0, 0, tokens(TREBLE)), StaffReading(0, 1, tokens(BASS))]
        )
        parts = root.findall("part")
        self.assertEqual(len(parts), 1)
        self.assertEqual(parts[0].findtext("measure/attributes/staves"), "2")
        group = root.find("part-list/part-group")
        self.assertEqual((group.get("type"), group.findtext("group-symbol")), ("start", "brace"))
        self.assertEqual(root.find("part-list/score-part/part-name").text, "Piano")
        named = SystemLayout(2, [StaffGroup(BRACE, 0, 1)], ["Piyano"])
        root, _ = write([named], [StaffReading(0, 0, tokens(TREBLE)), StaffReading(0, 1, tokens(BASS))])
        self.assertEqual(root.find("part-list/score-part/part-name").text, "Piyano")
        clefs = {c.get("number"): c.findtext("sign") for c in parts[0].iter("clef")}
        self.assertEqual(clefs, {"1": "G", "2": "F"})
        lower = [n for n in notes(parts[0]) if n.findtext("staff") == "2"]
        self.assertEqual(len(lower), 4)
        self.assertTrue(all(int(n.findtext("voice")) >= 5 for n in lower))
        self.assertEqual(sum(1 for n in lower if n.find("chord") is not None), 1)
        first = parts[0].find("measure")
        self.assertEqual([c.tag for c in first].count("backup"), 1)
        self.assertEqual(written.measures, [(1, 2), (1, 2)])

    def test_choir_in_a_bracket(self) -> None:
        layout = SystemLayout(4, [StaffGroup(BRACKET, 0, 3)])
        root, _ = write([layout], [StaffReading(0, k, tokens(TREBLE)) for k in range(4)])
        self.assertEqual(len(root.findall("part")), 4)
        children = [(c.tag, c.get("type")) for c in root.find("part-list")]
        self.assertEqual(children[0], ("part-group", "start"))
        self.assertEqual(children[-1], ("part-group", "stop"))
        self.assertEqual(root.find("part-list/part-group/group-symbol").text, "bracket")

    def test_shorter_staff_is_filled_with_a_measure_rest(self) -> None:
        one_measure = "\n".join(TREBLE.splitlines()[:8])
        root, _ = write([SystemLayout(2)], [StaffReading(0, 0, tokens(TREBLE)), StaffReading(0, 1, tokens(one_measure))])
        second = root.findall("part")[1].findall("measure")
        self.assertEqual(len(second), 2)
        rest = second[1].find("note")
        self.assertEqual(rest.find("rest").get("measure"), "yes")
        divisions = int(root.findtext("part/measure/attributes/divisions"))
        self.assertEqual(int(rest.findtext("duration")), 4 * divisions)

    def test_missing_part_in_a_system_rests(self) -> None:
        song = SystemLayout(3, [StaffGroup(BRACE, 1, 2)])
        readings = [StaffReading(0, 0, tokens(TREBLE)), StaffReading(0, 1, tokens(TREBLE)),
                    StaffReading(0, 2, tokens(BASS)), StaffReading(1, 0, tokens(TREBLE)),
                    StaffReading(1, 1, tokens(BASS))]
        root, written = write([song, PIANO], readings,
                              clefs=[["clef_G2", "clef_G2", "clef_F4"], ["clef_G2", "clef_F4"]])
        voice = root.findall("part")[0].findall("measure")
        self.assertEqual(len(voice), 4)
        self.assertTrue(all(n.find("rest") is not None for m in voice[2:] for n in m.findall("note")))
        self.assertEqual(written.measures[3:], [(3, 4), (3, 4)])

    def test_rest_and_note_of_one_length_are_not_a_chord(self) -> None:
        reading = tokens("clef_G2 . . . upper\nrest_4 _ _ _ upper&note_4 C5 _ _ upper\nnote_2. D5 _ _ upper\nbarline . . . .")
        root, _ = write([SystemLayout(2)], [StaffReading(0, 0, reading), StaffReading(0, 1, tokens(BASS))],
                        split_rest_chords=True)
        measure = root.find("part/measure")
        elements = [c for c in measure if c.tag in ("note", "backup")]
        for before, after in zip(elements, elements[1:]):
            if after.tag == "note" and after.find("chord") is not None:
                self.assertIsNone(before.find("rest"))
        self.assertEqual(sum(1 for n in measure.findall("note") if n.find("rest") is not None), 1)

    def test_confidence_and_tempo(self) -> None:
        upper, lower = tokens(TREBLE), tokens(BASS)
        for symbol in upper:
            symbol.confidence = 0.9
        for symbol in lower:
            symbol.confidence = 0.4
        root, written = write([PIANO], [StaffReading(0, 0, upper), StaffReading(0, 1, lower)],
                              tempo_marks={2: ("quarter", False, 80, None)})
        self.assertEqual(written.confidence, {1: 0.4, 2: 0.4})
        second = root.findall("part/measure")[1]
        self.assertEqual(second[0].tag, "direction")
        self.assertEqual(second.findtext("direction/direction-type/metronome/per-minute"), "80")

    def test_valid_against_the_schema(self) -> None:
        schema = _schema()
        if schema is None:
            self.skipTest("MusicXML schema or lxml not available")
        from lxml import etree  # noqa: PLC0415

        song = SystemLayout(5, [StaffGroup(BRACKET, 0, 2), StaffGroup(BRACE, 3, 4)])
        chordal = tokens(TREBLE.replace("note_4 C5 _ _ upper", "note_4 C5 _ _ upper&note_4 E5 _ _ upper"))
        readings = [StaffReading(0, k, tokens(TREBLE)) for k in range(3)]
        readings += [StaffReading(0, 3, chordal), StaffReading(0, 4, tokens(BASS))]
        _, written = write([song], readings, tempo_marks={1: ("quarter", True, 60, None)})
        document = etree.fromstring(written.musicxml.encode("utf-8"))
        self.assertTrue(schema.validate(document), [str(e) for e in schema.error_log][:3])

