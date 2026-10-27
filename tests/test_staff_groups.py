import unittest

import cv2
import numpy as np

from homr.bounding_boxes import RotatedBoundingBox
from homr.model import MultiStaff, Staff, StaffPoint
from homr.staff_groups import BRACE, BRACKET, StaffGroup, find_staff_groups

SPACE = 16  # staff space in pixels
LEFT, RIGHT = 120, 900


def _staff(image: np.ndarray, top: int) -> Staff:
    ys = [top + k * SPACE for k in range(5)]
    for y in ys:
        cv2.line(image, (LEFT, y), (RIGHT, y), 0, 2)
    return Staff([StaffPoint(x, [float(y) for y in ys], 0.0) for x in range(LEFT, RIGHT + 1, 20)])


def _mark_box(x0: int, y0: int, x1: int, y1: int) -> RotatedBoundingBox:
    """The box homr's tall-mark finder gives the ink x0..x1, y0..y1: dilated by 2 and 17 pixels."""
    center = ((x0 + x1) / 2, (y0 + y1) / 2)
    size = (x1 - x0 + 4, y1 - y0 + 34)
    return RotatedBoundingBox((center, size, 0.0), None)


def _start_line(image: np.ndarray, top: int, bottom: int) -> RotatedBoundingBox:
    cv2.line(image, (LEFT, top), (LEFT, bottom), 0, 2)
    return _mark_box(LEFT - 1, top, LEFT + 1, bottom)


def _brace(image: np.ndarray, top: int, bottom: int, right: int) -> RotatedBoundingBox:
    """A brace: tips at the right, a point to the left at the middle, thick in each half."""
    width = int(1.2 * SPACE)
    points = []
    for y in range(top, bottom + 1):
        s = (y - top) / (bottom - top)
        bulge = 0.55 * np.sin(np.pi * s) + 0.45 * max(0.0, 1 - abs(s - 0.5) / 0.1)
        points.append((right - int(width * bulge), y))
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        s = (ya - top) / (bottom - top)
        thickness = 1 + int(6 * abs(np.sin(2 * np.pi * s)))
        cv2.line(image, (xa, ya), (xb, yb), 0, thickness)
    return _mark_box(right - width - 3, top, right + 3, bottom)


def _bracket(image: np.ndarray, top: int, bottom: int, x: int, tilt: int = 0) -> RotatedBoundingBox:
    """A bracket: a bar half a space thick running past the outer lines into hooks to the right."""
    overrun = SPACE // 2
    cv2.line(image, (x, top - overrun), (x + tilt, bottom + overrun), 0, SPACE // 2)
    cv2.line(image, (x, top - overrun), (x + SPACE, top - overrun - SPACE // 2), 0, 2)
    cv2.line(image, (x + tilt, bottom + overrun), (x + tilt + SPACE, bottom + overrun + SPACE // 2), 0, 2)
    return _mark_box(min(x, x + tilt) - SPACE // 4, top - overrun, max(x, x + tilt) + SPACE // 4, bottom + overrun)


def _system(count: int, gap: int = 9 * SPACE) -> tuple[np.ndarray, list[Staff], list[int]]:
    tops = [60 + k * gap for k in range(count)]
    image = np.full((tops[-1] + 6 * SPACE + 60, RIGHT + 40), 255, np.uint8)
    staffs = [_staff(image, top) for top in tops]
    return image, staffs, tops


def _bottom(top: int) -> int:
    return top + 4 * SPACE


class TestStaffGroups(unittest.TestCase):
    def test_piano_brace(self) -> None:
        image, staffs, tops = _system(2)
        system = MultiStaff(staffs, [])
        system.tall_marks = [
            _start_line(image, tops[0], _bottom(tops[1])),
            _brace(image, tops[0], _bottom(tops[1]), LEFT - 6),
        ]
        self.assertEqual(find_staff_groups(image, system), [StaffGroup(BRACE, 0, 1)])

    def test_choir_bracket(self) -> None:
        image, staffs, tops = _system(4)
        system = MultiStaff(staffs, [])
        system.tall_marks = [
            _start_line(image, tops[0], _bottom(tops[3])),
            _bracket(image, tops[0], _bottom(tops[3]), LEFT - 12),
        ]
        self.assertEqual(find_staff_groups(image, system), [StaffGroup(BRACKET, 0, 3)])

    def test_tilted_bracket_is_still_a_bracket(self) -> None:
        image, staffs, tops = _system(4)
        system = MultiStaff(staffs, [])
        system.tall_marks = [_bracket(image, tops[0], _bottom(tops[3]), LEFT - 14, tilt=10)]
        self.assertEqual(find_staff_groups(image, system), [StaffGroup(BRACKET, 0, 3)])

    def test_voice_and_piano(self) -> None:
        image, staffs, tops = _system(3)
        system = MultiStaff(staffs, [])
        system.tall_marks = [
            _start_line(image, tops[0], _bottom(tops[2])),
            _brace(image, tops[1], _bottom(tops[2]), LEFT - 6),
        ]
        self.assertEqual(find_staff_groups(image, system), [StaffGroup(BRACE, 1, 2)])

    def test_start_line_alone_groups_nothing(self) -> None:
        image, staffs, tops = _system(2)
        system = MultiStaff(staffs, [])
        system.tall_marks = [_start_line(image, tops[0], _bottom(tops[1]))]
        self.assertEqual(find_staff_groups(image, system), [])

    def test_bracket_over_the_staffs_of_a_brace_is_the_brace(self) -> None:
        image, staffs, tops = _system(2)
        system = MultiStaff(staffs, [])
        system.tall_marks = [
            _brace(image, tops[0], _bottom(tops[1]), LEFT - 30),
            _bracket(image, tops[0], _bottom(tops[1]), LEFT - 10),
        ]
        self.assertEqual(find_staff_groups(image, system), [StaffGroup(BRACE, 0, 1)])

    def test_marks_inside_the_staffs_are_not_groups(self) -> None:
        image, staffs, tops = _system(2)
        system = MultiStaff(staffs, [])
        x = LEFT + 300  # a barline through both staffs, drawn thick
        cv2.line(image, (x, tops[0]), (x, _bottom(tops[1])), 0, 8)
        system.tall_marks = [_mark_box(x - 4, tops[0], x + 4, _bottom(tops[1]))]
        self.assertEqual(find_staff_groups(image, system), [])

    def test_single_staff(self) -> None:
        image, staffs, tops = _system(1)
        system = MultiStaff(staffs, [])
        system.tall_marks = [_bracket(image, tops[0], _bottom(tops[0]), LEFT - 12)]
        self.assertEqual(find_staff_groups(image, system), [])
