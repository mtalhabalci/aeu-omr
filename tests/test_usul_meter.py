import unittest
import xml.etree.ElementTree as ET
from fractions import Fraction

from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
from homr.usul_meter import bar_of, section_bars
from training.transformer.training_vocabulary import read_token_lines


def _xml(lines: str) -> ET.Element:
    tokens = read_token_lines(lines.splitlines())
    return ET.fromstring(generate_xml(XmlGeneratorArguments(), [tokens], "").to_string())


def _times(root: ET.Element) -> list[ET.Element]:
    return root.findall("./part/measure/attributes/time")


class TestUsulMeter(unittest.TestCase):
    def test_a_long_usul_barred_in_four_gets_its_bar_in_parentheses(self) -> None:
        """Atkoşar's "28/4 (4/4)": seven 4/4 measures, dashed lines inside the cycle, a solid one ending it."""
        measure = "note_1 C5 _ _ upper\n"
        lines = "clef_G2 . . . upper\ntimeSignature_28/4 . . . .\n" + (measure + "dashedbarline . . . .\n") * 6 + \
            measure + "barline . . . .\n" + (measure + "dashedbarline . . . .\n") * 6 + measure + "barline . . . ."
        root = _xml(lines)
        (time,) = _times(root)
        self.assertEqual((time.findtext("beats"), time.findtext("beat-type")), ("28", "4"))
        other = time.find("interchangeable")
        self.assertIsNotNone(other)
        self.assertEqual(other.findtext("time-relation"), "parentheses")
        self.assertEqual(bar_of(time), Fraction(1))
        # the page's bars are kept, the dashed ones drawn dashed
        self.assertEqual(len(root.findall("./part/measure")), 14)
        self.assertEqual(len(root.findall("./part/measure/barline[bar-style='dashed']")), 12)

    def test_a_few_misread_measures_do_not_hide_the_bar(self) -> None:
        """On handwriting a misread duration leaves a measure off; most measures still show the bar."""
        lines = "clef_G2 . . . upper\ntimeSignature_32/4 . . . .\n" + "note_1 C5 _ _ upper\nbarline . . . .\n" * 6 + \
            "note_2. C5 _ _ upper\nbarline . . . .\n" + "note_1 C5 _ _ upper\nbarline . . . ."
        (time,) = _times(_xml(lines))
        self.assertEqual(bar_of(time), Fraction(1))

    def test_a_finer_bar_takes_a_finer_beat_type(self) -> None:
        """Muhammes as "32/8" barred every two quarters: (4/8)."""
        lines = "clef_G2 . . . upper\ntimeSignature_32/8 . . . .\n" + "note_2 C5 _ _ upper\ndashedbarline . . . .\n" * 7
        (time,) = _times(_xml(lines))
        other = time.find("interchangeable")
        self.assertEqual((other.findtext("beats"), other.findtext("beat-type")), ("4", "8"))

    def test_no_bar_without_most_measures_agreeing(self) -> None:
        lines = "clef_G2 . . . upper\ntimeSignature_28/4 . . . .\n" + "note_1 C5 _ _ upper\nbarline . . . .\n" * 2 + \
            "note_2. C5 _ _ upper\nbarline . . . .\n" + "note_2 C5 _ _ upper\nbarline . . . .\n" * 2
        (time,) = _times(_xml(lines))
        self.assertIsNone(time.find("interchangeable"))

    def test_no_bar_that_does_not_divide_the_usul(self) -> None:
        """Measures of 5/8 under a 3/8 read for a 5: the time signature is wrong, not barred."""
        lines = "clef_G2 . . . upper\ntimeSignature_3/8 . . . .\n" + \
            "note_4 C5 _ _ upper\nnote_4. D5 _ _ upper\nbarline . . . .\n" * 4
        (time,) = _times(_xml(lines))
        self.assertIsNone(time.find("interchangeable"))

    def test_measures_that_fit_the_usul_need_no_bar(self) -> None:
        lines = "clef_G2 . . . upper\ntimeSignature_2/4 . . . .\n" + "note_4 C5 _ _ upper\nnote_4 D5 _ _ upper\nbarline . . . .\n" * 3
        root = _xml(lines)
        self.assertEqual(section_bars(root.find("part")), {})
        (time,) = _times(root)
        self.assertIsNone(time.find("interchangeable"))


if __name__ == "__main__":
    unittest.main()
