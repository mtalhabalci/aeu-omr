import unittest
from unittest import mock

import numpy as np

from homr import baslik_okuyucu
from homr.baslik_okuyucu import Item
from homr.model import MultiStaff, Staff, StaffPoint
from homr.part_names import _at_page_scale, read_part_names

SPACE = 16


def _staff(top: int) -> Staff:
    ys = [float(top + k * SPACE) for k in range(5)]
    return Staff([StaffPoint(x, ys, 0.0) for x in range(200, 901, 20)])


class TestPartNames(unittest.TestCase):
    def _read(self, items: list[Item], slots: list[list[int]]) -> list[str | None]:
        system = MultiStaff([_staff(100), _staff(300), _staff(500)], [])
        image = np.full((700, 950), 255, np.uint8)
        # the OCR sees the strip from one space above the first staff: its boxes are relative to that
        with mock.patch.object(baslik_okuyucu, "ocr_items", return_value=items):
            return read_part_names(image, system, slots)

    def test_names_go_to_the_part_beside_them(self) -> None:
        items = [Item("Soprano", [10, 20, 90, 40], 0.99), Item("Piano", [10, 320, 80, 340], 0.98)]
        self.assertEqual(self._read(items, [[0], [1, 2]]), ["Soprano", "Piano"])

    def test_words_of_one_name_join_left_to_right(self) -> None:
        items = [Item("I", [70, 220, 80, 240], 0.95), Item("Violin", [10, 220, 60, 240], 0.99)]
        self.assertEqual(self._read(items, [[0], [1], [2]]), [None, "Violin I", None])

    def test_unsure_reads_and_signs_are_left_out(self) -> None:
        items = [Item("si", [10, 20, 30, 40], 0.78), Item("{", [100, 220, 110, 300], 0.99),
                 Item("12", [10, 420, 30, 440], 0.99)]
        self.assertEqual(self._read(items, [[0], [1], [2]]), [None, None, None])

    def test_a_narrow_strip_is_read_at_the_page_scale(self) -> None:
        strip = np.full((1311, 46, 3), 230, np.uint8)
        strip[600:620, 5:40] = 0  # a word
        canvas = _at_page_scale(strip)
        self.assertEqual(canvas.shape, (1311, 736, 3))
        np.testing.assert_array_equal(canvas[:, 736 - 46 :], strip)  # at the top right: the y of the boxes stays
        self.assertTrue((canvas[:, : 736 - 46] == 230).all())  # the paper's tone
        wide = np.full((800, 900, 3), 255, np.uint8)
        self.assertIs(_at_page_scale(wide), wide)
