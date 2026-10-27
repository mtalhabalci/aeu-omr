"""Braces and brackets at the start of a system: which staffs one instrument plays (a brace, as a piano's two
staffs: one part) and which are only grouped (a bracket, as a choir or a string section: one part per staff).

homr joins the staffs of a system by the tall marks between them (brace_dot_detection) without saying what joined
them, and its own reader then pairs the staffs two by two, which makes a choir's four staffs two pianos. Here every
tall mark at the left of the system is measured on the page image, over the staffs it spans: per row, the thickest
run of ink.

- A brace bends: the run's middle strays from a straight line by 0.21-0.68 staff spaces on the 40 braces of the
  polyphony exam (90th percentile of the distance).
- A bracket is a straight bar (at most 0.09 spaces from a straight line, a tilted scan included) at least a quarter
  space thick whose ends run on past the outer staff lines into its hooks (0.32-1.7 spaces both ends together).
- The system's start line is straight and thinner (0.05-0.22 spaces) and ends at the outer lines; it groups nothing.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from homr.bounding_boxes import RotatedBoundingBox
from homr.model import MultiStaff, Staff, StaffPoint
from homr.type_definitions import NDArray

BRACE = "brace"
BRACKET = "bracket"

# prepare_brace_dot_image dilates the marks with a 5 x 35 ellipse, so a mark's box is larger than its ink by this
_DILATION_X = 2
_DILATION_Y = 17
# below this gray level a pixel of the (contrast-adjusted) page is ink
_INK = 150
# all in staff spaces
_LEFT_OF_START = 1.0  # a group mark stands left of the staffs' start, or at most this far into them
_MIN_THICKNESS = 0.25  # thinner marks are the system's start line
_BRACE_BEND = 0.15
_BRACKET_BEND = 0.12
_BRACKET_OVERRUN = 0.25
_MAX_OVERRUN = 3.0


@dataclass(frozen=True)
class StaffGroup:
    """A brace or a bracket over the staffs first..last of a system (0 is the top staff, last included)."""

    kind: str
    first: int
    last: int


@dataclass(frozen=True)
class _Mark:
    kind: str
    first: int
    last: int
    bend: float


def _closest_point(staff: Staff, x: float) -> StaffPoint:
    return min(staff.grid, key=lambda point: abs(point.x - x))


def _thickest_run(row: NDArray) -> tuple[int, int] | None:
    """(start, end) of the longest run of ink in a row of booleans, end excluded."""
    edges = np.flatnonzero(np.diff(np.concatenate(([0], row.astype(np.int8), [0]))))
    if len(edges) == 0:
        return None
    starts, ends = edges[::2], edges[1::2]
    longest = int(np.argmax(ends - starts))
    return int(starts[longest]), int(ends[longest])


def _overrun(ink: NDArray, row: int, step: int, left: int, right: int, limit: int) -> int:
    """How many rows the ink between columns left..right continues from row on, upwards (step -1) or down."""
    count = 0
    while count < limit:
        y = row + step * (count + 1)
        if not 0 <= y < ink.shape[0] or not ink[y, max(0, left) : right + 1].any():
            break
        count += 1
    return count


def _measure(ink: NDArray, staffs: list[Staff], mark: RotatedBoundingBox) -> _Mark | None:
    center_x, center_y = mark.center
    width, height = mark.size
    x0 = int(center_x - width / 2 + _DILATION_X) - 1
    x1 = int(round(center_x + width / 2 - _DILATION_X)) + 2
    y0 = center_y - height / 2 + _DILATION_Y
    y1 = center_y + height / 2 - _DILATION_Y
    spanned = [
        k
        for k, staff in enumerate(staffs)
        if min(y1, staff.max_y) - max(y0, staff.min_y) > 0.5 * (staff.max_y - staff.min_y)
    ]
    if len(spanned) < 2:
        return None
    unit = float(np.median([staffs[k].average_unit_size for k in spanned]))
    top = int(round(_closest_point(staffs[spanned[0]], center_x).y[0]))
    bottom = int(round(_closest_point(staffs[spanned[-1]], center_x).y[-1]))
    x0, x1 = max(0, x0), min(ink.shape[1], x1)
    rows, middles, widths = [], [], []
    for y in range(max(0, top), min(ink.shape[0], bottom + 1)):
        run = _thickest_run(ink[y, x0:x1])
        if run is not None:
            rows.append(y)
            middles.append(x0 + (run[0] + run[1]) / 2)
            widths.append(run[1] - run[0])
    if len(rows) < 10 or len(rows) < 0.5 * (bottom - top):
        return None
    thickness = float(np.median(widths))
    if thickness < _MIN_THICKNESS * unit:
        return None
    ys, xs = np.array(rows, dtype=float), np.array(middles)
    line = np.polyfit(ys, xs, 1)
    bend = float(np.percentile(np.abs(xs - np.polyval(line, ys)), 90)) / unit
    if bend >= _BRACE_BEND:
        return _Mark(BRACE, spanned[0], spanned[-1], bend)
    if bend >= _BRACKET_BEND:
        return None
    middle = int(round(float(np.median(xs))))
    half = max(1, int(thickness / 2))
    limit = int(_MAX_OVERRUN * unit)
    overrun = _overrun(ink, top, -1, middle - half, middle + half, limit) + _overrun(
        ink, bottom, 1, middle - half, middle + half, limit
    )
    if overrun >= _BRACKET_OVERRUN * unit:
        return _Mark(BRACKET, spanned[0], spanned[-1], bend)
    return None


def _overlaps(a: _Mark, b: _Mark) -> bool:
    return a.first <= b.last and b.first <= a.last


def find_staff_groups(image: NDArray, system: MultiStaff) -> list[StaffGroup]:
    """The braces and brackets of a system whose staffs were kept apart (detect_staffs_in_image with
    merge_grand_staffs False), by the system's tall marks and the page image they were found on.

    Braces do not overlap each other, nor brackets each other (the widest wins: an inner bracket over two violins
    is left out); a bracket over exactly the staffs of a brace is the brace."""
    staffs = system.staffs
    if len(staffs) < 2:
        return []
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    ink = gray < _INK
    unit = float(np.median([staff.average_unit_size for staff in staffs]))
    start = min(staff.min_x for staff in staffs)
    marks = [
        _measure(ink, staffs, mark)
        for mark in system.tall_marks
        if mark.center[0] <= start + _LEFT_OF_START * unit
    ]
    braces: list[_Mark] = []
    for mark in sorted((m for m in marks if m and m.kind == BRACE), key=lambda m: -m.bend):
        if not any(_overlaps(mark, other) for other in braces):
            braces.append(mark)
    brackets: list[_Mark] = []
    for mark in sorted(
        (m for m in marks if m and m.kind == BRACKET), key=lambda m: m.first - m.last
    ):
        same_as_brace = any((mark.first, mark.last) == (b.first, b.last) for b in braces)
        if not same_as_brace and not any(_overlaps(mark, other) for other in brackets):
            brackets.append(mark)
    return sorted(
        (StaffGroup(m.kind, m.first, m.last) for m in braces + brackets),
        key=lambda g: (g.first, -g.last, g.kind),
    )
