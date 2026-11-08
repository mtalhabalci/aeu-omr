import unittest

import cv2
import numpy as np

from homr.bounding_boxes import (
    BoundingEllipse,
    RotatedBoundingBox,
    _no_ellipse_through,
    create_bounding_ellipses,
)

empty = np.array([])


class TestBoundingBoxes(unittest.TestCase):

    unit_size = 3

    def test_is_overlapping_rotated_box_extrapolated(self) -> None:
        box1 = RotatedBoundingBox(((100, 200), (10, 10), 0), empty)
        touching_box = RotatedBoundingBox(((110, 200), (10, 10), 0), empty)
        samle_line_box = RotatedBoundingBox(((140, 200), (10, 10), 0), empty)
        different_line_box = RotatedBoundingBox(((220, 300), (10, 10), 0), empty)
        self.assertTrue(box1.is_overlapping_extrapolated(touching_box, self.unit_size))
        self.assertTrue(box1.is_overlapping_extrapolated(samle_line_box, self.unit_size))
        self.assertFalse(box1.is_overlapping_extrapolated(different_line_box, self.unit_size))

        box2 = RotatedBoundingBox(((100, 200), (10, 10), 45), empty)
        touching_box = RotatedBoundingBox(((110, 200), (10, 20), 50), empty)
        samle_line_box = RotatedBoundingBox(((110, 200), (10, 10), 45), empty)
        different_line_box = RotatedBoundingBox(((140, 220), (10, 10), 0), empty)
        self.assertTrue(box2.is_overlapping_extrapolated(touching_box, self.unit_size))
        self.assertFalse(box2.is_overlapping_extrapolated(samle_line_box, self.unit_size))
        self.assertTrue(box2.is_overlapping_extrapolated(different_line_box, self.unit_size))

    def test_is_overlapping_rotated_box_with_rotated_box(self) -> None:
        box1 = RotatedBoundingBox(((100, 200), (10, 10), 0), empty)
        touching_box = RotatedBoundingBox(((110, 200), (10, 10), 0), empty)
        inside_box = RotatedBoundingBox(((105, 200), (10, 10), 0), empty)
        far_away_box = RotatedBoundingBox(((200, 200), (10, 10), 0), empty)
        crossing_box = RotatedBoundingBox(((105, 205), (10, 10), 90), empty)

        self.assertTrue(box1.is_overlapping(touching_box))
        self.assertTrue(box1.is_overlapping(inside_box))
        self.assertFalse(box1.is_overlapping(far_away_box))
        self.assertTrue(box1.is_overlapping(crossing_box))

    def test_is_overlapping_rotated_box_with_ellipse(self) -> None:
        box1 = RotatedBoundingBox(((100, 200), (10, 10), 0), empty)
        touching_box = BoundingEllipse(((110, 200), (10, 10), 0), empty)
        inside_box = BoundingEllipse(((105, 200), (10, 10), 0), empty)
        far_away_box = BoundingEllipse(((200, 200), (10, 10), 0), empty)

        self.assertTrue(box1.is_overlapping(touching_box))
        self.assertTrue(box1.is_overlapping(inside_box))
        self.assertFalse(box1.is_overlapping(far_away_box))

        box2 = RotatedBoundingBox(
            ((570.1167602539062, 506.98968505859375), (2, 60), -5.042449951171875), empty
        )
        ellipse2 = BoundingEllipse(((536.93896484375, 470.5845947265625), (13, 17), 5), empty)
        self.assertFalse(box2.is_overlapping(ellipse2))

    def test_no_ellipse_goes_through_a_sliver_or_too_few_points(self) -> None:
        def contour(points: list[list[int]]) -> np.ndarray:
            return np.array(points, np.int32).reshape(-1, 1, 2)

        # notehead contours of Atkoşar 1416 whose cv2.fitEllipse changed from call to call
        self.assertTrue(_no_ellipse_through(contour([[1374, 2388], [1373, 2389], [1372, 2389], [1377, 2389],
                                                     [1376, 2388]])))  # two rows
        self.assertTrue(_no_ellipse_through(contour([[840, 1253], [840, 1258], [842, 1258], [842, 1256],
                                                     [840, 1254]])))  # two columns
        self.assertTrue(_no_ellipse_through(contour([[1795, 2409], [1796, 2409], [1797, 2410], [1796, 2411],
                                                     [1797, 2410], [1796, 2409]])))  # four points apart
        self.assertFalse(_no_ellipse_through(contour([[10, 0], [13, 1], [14, 4], [13, 7], [10, 8], [7, 7],
                                                      [6, 4], [7, 1]])))

    def test_a_notehead_keeps_its_ellipse_beside_a_sliver(self) -> None:
        image = np.zeros((40, 60), np.uint8)
        image[10:12, 5:25] = 1
        cv2.ellipse(image, (40, 25), (6, 4), 0, 0, 360, 1, -1)
        ellipses = create_bounding_ellipses(image, skip_merging=True)
        self.assertEqual(len(ellipses), 1)
        self.assertAlmostEqual(ellipses[0].center[0], 40, delta=1)
        self.assertAlmostEqual(ellipses[0].center[1], 25, delta=1)
