import unittest
import xml.etree.ElementTree as ET

from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
from homr.volta_mend import mend_voltas
from training.transformer.training_vocabulary import read_token_lines

HEAD = """clef_G2 . . . upper
timeSignature_2/4 . . . ."""


def _tokens(body: str):
    return read_token_lines((HEAD + "\n" + body.strip()).splitlines())


def _endings(tokens) -> list[tuple[int, str, str, bool]]:
    """(measure, ending type, number, backward repeat on the same barline) as the writer writes them."""
    root = ET.fromstring(generate_xml(XmlGeneratorArguments(), [tokens], "").to_string())
    found = []
    for measure in root.iter("measure"):
        for barline in measure.findall("barline"):
            ending, repeat = barline.find("ending"), barline.find("repeat")
            if ending is not None:
                backward = repeat is not None and repeat.get("direction") == "backward"
                found.append((int(measure.get("number")), ending.get("type"), ending.get("number"), backward))
    return found


def _bar(note: str) -> str:
    return f"note_4 {note} _ _ upper\nnote_4 {note} _ _ upper"


class TestVoltaMend(unittest.TestCase):
    def test_two_endings_as_read_stay(self) -> None:
        tokens = _tokens(f"""{_bar("C5")}
barline . . . .
voltaStart . . . .
{_bar("D5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("E5")}
bolddoublebarline . . . .
voltaStop . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual([s.rhythm for s in mended], [s.rhythm for s in tokens])
        self.assertEqual(notes, [])

    def test_a_missed_first_ending_start_is_the_measure_the_repeat_closes(self) -> None:
        # 11820, Atkoşar: the "1" bracket has no left hook and is not read
        tokens = _tokens(f"""{_bar("C5")}
barline . . . .
{_bar("D5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("E5")}
bolddoublebarline . . . .
voltaStop . . . .""")
        self.assertEqual(_endings(tokens)[0][1:3], ("stop", "1"))  # a closing with no start before it
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "baslangic")])
        self.assertEqual(_endings(mended), [(2, "start", "1", False), (2, "stop", "1", True),
                                            (3, "start", "2", False), (3, "stop", "2", False)])

    def test_a_third_ending_that_never_closes_is_left_out(self) -> None:
        # 13283, Atkoşar: "2." closed by a hook and a double barline, read as a repeat and a third ending
        tokens = _tokens(f"""voltaStart . . . .
{_bar("C5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("D5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("E5")}
barline . . . .
{_bar("F5")}
barline . . . .""")
        self.assertIn((3, "start", "3", False), _endings(tokens))
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "ucuncu")])
        self.assertEqual(_endings(mended), [(1, "start", "1", False), (1, "stop", "1", True),
                                            (2, "start", "2", False), (2, "stop", "2", False)])

    def test_three_endings_that_close_stay(self) -> None:
        tokens = _tokens(f"""voltaStart . . . .
{_bar("C5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("D5")}
repeatEnd . . . .
voltaStop . . . .
voltaStart . . . .
{_bar("E5")}
bolddoublebarline . . . .
voltaStop . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual([s.rhythm for s in mended], [s.rhythm for s in tokens])
        self.assertEqual(notes, [])

    def test_a_closing_with_no_ending_open_is_a_barline(self) -> None:
        tokens = _tokens(f"""{_bar("C5")}
voltaStop . . . .
{_bar("D5")}
barline . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "kapanis")])
        self.assertEqual(_endings(mended), [])
        self.assertIn("barline", [s.rhythm for s in mended][2:8])

    def test_a_closing_right_after_a_double_barline_ends_an_ending_whose_start_was_missed(self) -> None:
        # 1713, Atkoşar: one-measure brackets marked "MEYÂN'A" and "KARAR" for numbers
        tokens = _tokens(f"""{_bar("C5")}
bolddoublebarline . . . .
voltaStop . . . .
{_bar("D5")}
barline . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "baslangic")])
        self.assertEqual(_endings(mended), [(1, "start", "1", False), (1, "stop", "1", False)])

    def test_both_endings_with_missed_starts(self) -> None:
        # 2738, Atkoşar: "1" over the repeat's measure, "2" at the start of the next staff
        tokens = _tokens(f"""{_bar("C5")}
barline . . . .
{_bar("D5")}
repeatEnd . . . .
voltaStop . . . .
newline . . . .
clef_G2 . . . upper
{_bar("E5")}
bolddoublebarline . . . .
voltaStop . . . .
{_bar("F5")}
barline . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "baslangic"), (2, "baslangic")])
        self.assertEqual(_endings(mended), [(2, "start", "1", False), (2, "stop", "1", True),
                                            (3, "start", "2", False), (3, "stop", "2", False)])
        rhythms = [s.rhythm for s in mended]
        self.assertEqual(rhythms[rhythms.index("clef_G2", 2) + 1], "voltaStart")  # inside the new staff

    def test_a_second_closing_is_dropped(self) -> None:
        tokens = _tokens(f"""voltaStart . . . .
{_bar("C5")}
bolddoublebarline . . . .
voltaStop . . . .
voltaStop . . . .
{_bar("D5")}
barline . . . .""")
        mended, notes = mend_voltas(tokens)
        self.assertEqual(notes, [(1, "kapanis")])
        self.assertEqual([s.rhythm for s in mended].count("voltaStop"), 1)
        self.assertEqual(_endings(mended), [(1, "start", "1", False), (1, "stop", "1", False)])
