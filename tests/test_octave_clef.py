import unittest
import xml.etree.ElementTree as ET
from unittest import mock

import cv2
import numpy as np

from homr import octave_clef
from homr.model import Staff, StaffPoint
from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
from homr.octave_clef import find_octave_mark, find_octave_mark_at, mark_octave_clef
from homr.score_parts import StaffReading, SystemLayout, plan_score, write_score
from homr.transformer.vocabulary import EncodedSymbol
from tests.test_score_parts import _schema
from training.transformer.training_vocabulary import read_token_lines

UNIT = 20  # pixels between staff lines
TOP = 100  # the top line's row
START = 60  # where the staff lines start
LINES = [TOP + k * UNIT for k in range(5)]
BOTTOM = LINES[-1]


def page() -> np.ndarray:
    """A white page with a staff: five lines from START on."""
    image = np.full((360, 600), 255, np.uint8)
    for y in LINES:
        cv2.line(image, (START, y), (590, y), 0, 2)
    return image


def treble_clef(image: np.ndarray, x: int = START + 25) -> None:
    """Something with a treble clef's outline: a stem from 2 spaces over the staff to 1 space under it, a loop
    around the middle lines and a ball at the tail's end."""
    cv2.line(image, (x + 22, TOP - 2 * UNIT), (x + 22, BOTTOM + UNIT), 0, 3)
    cv2.ellipse(image, (x + 22, TOP - 2 * UNIT + 12), (8, 12), 0, 0, 360, 0, 3)
    cv2.ellipse(image, (x + 20, TOP + 2 * UNIT + 8), (20, 24), 0, 0, 360, 0, 3)
    cv2.ellipse(image, (x + 14, BOTTOM + UNIT), (8, 6), 0, 0, 180, 0, 3)
    cv2.circle(image, (x + 8, BOTTOM + UNIT - 2), 8, 0, -1)


def digit(image: np.ndarray, text: str, x: int, top: int) -> None:
    """text in a plain font, its top at row top: an 8 is 1.2 spaces tall."""
    scale = 1.2 * UNIT / 22
    (_, height), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 2)
    cv2.putText(image, text, (x, top + height), cv2.FONT_HERSHEY_SIMPLEX, scale, 0, 2, cv2.LINE_AA)


def staff() -> Staff:
    return Staff([StaffPoint(float(x), [float(y) for y in LINES], 0.0) for x in range(START, 591, 10)])


def tokens(text: str) -> list[EncodedSymbol]:
    return read_token_lines([line for line in text.strip().splitlines() if line.strip()])


TENOR = """clef_G2 . . . upper
keySignature_0 . . . .
timeSignature/4 . . . .
note_4 B4 _ _ upper
note_4 C5 _ _ upper
note_2 D5 _ _ upper
barline . . . ."""


def reads(text: str, score: float = 0.95):  # noqa: ANN201
    """OCR stubbed to read text."""
    return mock.patch.object(octave_clef, "_read", return_value=(text, score))


class TestFindOctaveMark(unittest.TestCase):
    def test_eight_under_the_clef(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "8", START + 37, BOTTOM + 2 * UNIT)
        with reads("8") as ocr:
            mark = find_octave_mark(image, staff())
        self.assertIsNotNone(mark)
        self.assertEqual(mark.change, -1)
        x0, y0, x1, y1 = ocr.call_args[0][1]
        self.assertTrue(START + 30 <= x0 < x1 <= START + 60 and BOTTOM + UNIT < y0 < y1 < BOTTOM + 4 * UNIT)

    def test_eight_touching_the_tail(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "8", START + 37, BOTTOM + UNIT + 8)
        cv2.line(image, (START + 39, BOTTOM + UNIT + 2), (START + 41, BOTTOM + UNIT + 10), 0, 3)
        with reads("8"):
            self.assertEqual(find_octave_mark(image, staff()).change, -1)

    def test_eight_over_the_clef(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "8", START + 39, TOP - 3 * UNIT - 10)
        with reads("8"):
            self.assertEqual(find_octave_mark(image, staff()).change, 1)

    def test_no_eight_over_a_systems_top_staff(self) -> None:
        """There stands the number of the system's first measure."""
        image = page()
        treble_clef(image)
        digit(image, "8", START + 39, TOP - 3 * UNIT - 10)
        with reads("8") as ocr:
            self.assertIsNone(find_octave_mark(image, staff(), above=False))
        ocr.assert_not_called()

    def test_plain_treble_clef(self) -> None:
        image = page()
        treble_clef(image)
        with reads("8") as ocr:
            self.assertIsNone(find_octave_mark(image, staff()))
        ocr.assert_not_called()

    def test_a_letter_of_one_loop_is_no_eight(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "O", START + 35, BOTTOM + 2 * UNIT)
        with reads("O"):
            self.assertIsNone(find_octave_mark(image, staff()))

    def test_one_hole_needs_a_surer_reading(self) -> None:
        """A blurred 8 shows one hole: taken for an 8 only when OCR is surer than of an 8 with both holes."""
        image = page()
        treble_clef(image)
        digit(image, "O", START + 35, BOTTOM + 2 * UNIT)
        with reads("8", 0.52):
            self.assertIsNone(find_octave_mark(image, staff()))
        with reads("8", 0.9):
            self.assertEqual(find_octave_mark(image, staff()).change, -1)
        both = page()
        treble_clef(both)
        digit(both, "8", START + 37, BOTTOM + 2 * UNIT)
        with reads("8", 0.52):
            self.assertEqual(find_octave_mark(both, staff()).change, -1)

    def test_an_eight_away_from_the_clef_is_a_lyric_or_a_number(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "8", START + 6 * UNIT, BOTTOM + 2 * UNIT)
        with reads("8") as ocr:
            self.assertIsNone(find_octave_mark(image, staff()))
        ocr.assert_not_called()

    def test_an_eight_in_a_word_is_no_clef_mark(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "88", START + 30, BOTTOM + 2 * UNIT)
        with reads("8"):
            self.assertIsNone(find_octave_mark(image, staff()))

    def test_ocr_must_read_an_eight(self) -> None:
        image = page()
        treble_clef(image)
        digit(image, "8", START + 37, BOTTOM + 2 * UNIT)
        with reads("3"):
            self.assertIsNone(find_octave_mark(image, staff()))
        with reads("8", 0.2):
            self.assertIsNone(find_octave_mark(image, staff()))

    def test_no_treble_clef(self) -> None:
        image = page()
        digit(image, "8", START + 37, BOTTOM + 2 * UNIT)
        with reads("8"):
            self.assertIsNone(find_octave_mark_at(image, START, [float(y) for y in LINES], UNIT))

    def test_reading_by_ocr(self) -> None:
        """The recogniser itself on a drawn 8 (skipped where RapidOCR's models are not installed)."""
        try:
            from homr.baslik_okuyucu import prepare  # noqa: PLC0415

            prepare()
        except Exception as error:  # noqa: BLE001
            self.skipTest(f"no OCR: {error}")
        image = page()
        treble_clef(image)
        digit(image, "8", START + 37, BOTTOM + 2 * UNIT)
        mark = find_octave_mark(image, staff())
        self.assertIsNotNone(mark)
        self.assertEqual((mark.change, mark.text), (-1, "8"))
        other = page()
        treble_clef(other)
        digit(other, "O", START + 35, BOTTOM + 2 * UNIT)
        self.assertIsNone(find_octave_mark(other, staff()))


class TestMarkOctaveClef(unittest.TestCase):
    def test_reading_that_starts_with_the_treble_clef(self) -> None:
        found = octave_clef.OctaveMark(-1, (0, 0, 1, 1), "8", 0.9)
        with mock.patch.object(octave_clef, "find_octave_mark", return_value=found):
            symbols, change = mark_octave_clef(tokens(TENOR), page(), staff())
        self.assertEqual(change, -1)
        self.assertEqual(symbols[0].clef_octave, -1)
        self.assertEqual([s.clef_octave for s in symbols[1:]], [0] * (len(symbols) - 1))

    def test_other_clefs_are_not_looked_at(self) -> None:
        bass = tokens(TENOR.replace("clef_G2", "clef_F4"))
        late = tokens("note_4 B4 _ _ upper\n" + TENOR)
        with mock.patch.object(octave_clef, "find_octave_mark") as find:
            for reading in (bass, late, tokens("note_4 B4 _ _ upper")):
                symbols, change = mark_octave_clef(reading, page(), staff())
                self.assertIs(symbols, reading)
                self.assertEqual(change, 0)
        find.assert_not_called()

    def test_no_mark_leaves_the_reading_as_it_was(self) -> None:
        reading = tokens(TENOR)
        with mock.patch.object(octave_clef, "find_octave_mark", return_value=None):
            symbols, change = mark_octave_clef(reading, page(), staff())
        self.assertIs(symbols, reading)
        self.assertEqual(change, 0)


def octaves(part: ET.Element) -> list[str]:
    pitched = [n for n in part.iter("note") if n.find("pitch") is not None]
    return [n.findtext("pitch/step") + n.findtext("pitch/octave") for n in pitched]


class TestOctaveClefWritten(unittest.TestCase):
    def tenor(self, change: int) -> list[EncodedSymbol]:
        symbols = tokens(TENOR)
        symbols[0] = symbols[0].with_clef_octave(change)
        return symbols

    def test_tenor_clef_and_its_notes(self) -> None:
        voice = self.tenor(-1) + [EncodedSymbol("newline")] + tokens(TENOR)
        root = ET.fromstring(generate_xml(XmlGeneratorArguments(), [voice], "").to_string())
        clefs = root.findall(".//clef")
        self.assertEqual([c.findtext("clef-octave-change") for c in clefs], ["-1", None])
        self.assertEqual(octaves(root), ["B3", "C4", "D4", "B4", "C5", "D5"])

    def test_eight_over_the_clef(self) -> None:
        root = ET.fromstring(generate_xml(XmlGeneratorArguments(), [self.tenor(1)], "").to_string())
        self.assertEqual(root.findtext(".//clef/clef-octave-change"), "1")
        self.assertEqual(octaves(root), ["B5", "C6", "D6"])

    def test_plain_clef_is_written_as_before(self) -> None:
        plain = generate_xml(XmlGeneratorArguments(), [tokens(TENOR)], "").to_string()
        self.assertNotIn("clef-octave-change", plain)
        self.assertEqual(plain, generate_xml(XmlGeneratorArguments(), [self.tenor(0)], "").to_string())

    def test_choir_tenor_part(self) -> None:
        layout = SystemLayout(2)
        readings = [StaffReading(0, 0, tokens(TENOR)), StaffReading(0, 1, self.tenor(-1))]
        written = write_score(XmlGeneratorArguments(software=["Test"]), [layout], readings, plan_score([layout]))
        parts = ET.fromstring(written.musicxml).findall("part")
        self.assertIsNone(parts[0].find(".//clef/clef-octave-change"))
        self.assertEqual(parts[1].findtext(".//clef/clef-octave-change"), "-1")
        self.assertEqual(octaves(parts[0]), ["B4", "C5", "D5"])
        self.assertEqual(octaves(parts[1]), ["B3", "C4", "D4"])
        schema = _schema()
        if schema is not None:
            from lxml import etree  # noqa: PLC0415

            document = etree.fromstring(written.musicxml.encode("utf-8"))
            self.assertTrue(schema.validate(document), [str(e) for e in schema.error_log][:3])
