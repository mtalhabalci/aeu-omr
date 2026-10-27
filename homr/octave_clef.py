"""The small 8 under (or over) a treble clef: the octave treble clef of a tenor staff, which sounds an octave lower
than it is written (above: an octave higher).

The models' vocabulary has the treble clef on lines 1 and 2 and no octave clef, so a tenor staff comes out read as
clef_G2 and every pitch an octave too high. The 8 is looked for on the page image, at the clef the staff starts
with:

1. The clef: staff lines are taken out of the start of the staff (short vertical runs of ink on a line) and the
   leftmost tall component that rises over the top line, reaches down to the bottom line and is wide across the
   middle lines is the clef (a bracket's or a brace's bar is narrow there).
2. The digit: in the band under the clef (over it for 8va), two holes one above the other in one piece of ink, of a
   printed digit's size, under the clef's middle and close to it, with white beside it: an 8, even where it touches
   the clef's tail. A lyric syllable or a word does not stand under the clef's middle with white beside it; an "O"
   has one hole. A blurred or coarse print fills one of the 8's holes: one hole is then taken for either loop.
3. OCR (RapidOCR's recogniser, the one the title block is read with) reads the digit's box and must read "8", with
   a confidence of 0.5 (0.55 where one hole was seen: a measure number "4" or "6" has one hole too).

An 8 over the clef is not looked for over a system's top staff: the number of the system's first measure stands
there, right over the clef (a "4" and a "6" on the polyphony exam's staff crops), and a measure 8 would be read as an
8va clef.

find_octave_mark(image, staff) -> OctaveMark | None, the change being -1 (8 below) or +1 (8 above);
mark_octave_clef(symbols, image, staff) looks only at a reading that starts with clef_G2 and sets the clef's
clef_octave, which the MusicXML writer turns into <clef-octave-change> and the notes' octave.
"""

from dataclasses import dataclass

import cv2
import numpy as np

from homr.model import Staff
from homr.transformer.vocabulary import EncodedSymbol
from homr.type_definitions import NDArray

# below this gray level a pixel of the (contrast-adjusted) page is ink, as in homr.staff_groups
_INK = 150
# all in staff spaces
_LEFT = 1.0  # the window starts this far left of the staff's start ...
_RIGHT = 7.0  # ... and ends this far right of it: the clef stands first
_ABOVE = 5.0  # the window's rows: over the top line ...
_BELOW = 5.0  # ... and under the bottom line
_LINE_RUN = 0.45  # a vertical run of ink on a staff line at most this long is the line itself
_CLEF_MIN_HEIGHT = 4.0  # a treble clef is 6.5-7.5 spaces tall, with an 8 joined to it up to 9
_CLEF_MAX_HEIGHT = 9.5  # a brace or a bracket runs on past the window
_CLEF_MIN_WIDTH = 1.0  # the system's start line and a barline are thin
_CLEF_MAX_START = 6.0  # the clef's middle is at most this far right of the staff's start
_CLEF_BODY = 1.0  # between the second and the fourth line the clef is at least this wide
_BAND_NEAR = 0.8  # the digit's band starts this far from the outer line ...
_BAND_FAR = 4.0  # ... and ends this far
_SIDE = 0.4  # the band reaches this far left and right of the clef
_HOLE_MIN_AREA = 0.008  # square spaces; an 8's holes on the polyphony exam's prints are about 0.1
_HOLE_MAX_AREA = 0.4
_HOLE_MAX_HEIGHT = 0.8
_HOLES_DX = 0.35  # the two holes of an 8 stand one above the other ...
_HOLES_DY = (0.2, 1.0)  # ... this far apart
_STROKE = 0.3  # the digit's box: its holes and this much ink around them
_DIGIT_HEIGHT = (0.6, 2.0)
_DIGIT_WIDTH = (0.35, 1.4)
_DIGIT_GAP = 2.7  # the digit's near edge is at most this far from the outer line ...
_CLEF_GAP = 1.0  # ... and this far from the clef's end
_MIDDLE = 0.15  # the digit's middle is under (over) the clef, at least this share of its width from its edges
_CLEAR = 0.5  # beside the digit, at its height, this much is white
_MIN_SCORE = 0.5  # OCR's confidence in its "8" where both holes are seen ...
_MIN_SCORE_ONE_HOLE = 0.55  # ... and where one is: other shapes of one loop read as what they are ("4", "6")
_ONE_HOLE_DIGIT = 1.25  # an 8 seen by one hole: this tall from that loop's edge


@dataclass
class OctaveMark:
    change: int  # -1: the 8 is under the clef (an octave lower), +1: over it
    box: tuple[int, int, int, int]  # the digit, x0, y0, x1, y1 in the image's pixels
    text: str  # what OCR read
    score: float


def _line_rows(ink: NDArray, lines: list[float], unit: float, start: int) -> NDArray:
    """The rows the staff lines cover: near each line, the rows whose ink runs along most of the staff's start (a
    scan's line is several pixels thick, and not always where the staff's grid puts it to the pixel)."""
    height = ink.shape[0]
    along = ink[:, max(0, start) :].mean(axis=1) if ink.shape[1] > start else np.zeros(height)
    rows = np.zeros(height, dtype=bool)
    reach = max(2, round(0.45 * unit))
    for y in lines:
        low, high = max(0, round(y) - reach), min(height, round(y) + reach + 1)
        if high <= low:
            continue
        near = along[low:high]
        rows[low:high] |= (near >= 0.3) & (near >= 0.5 * near.max())
        # a row or so either side, where the line's edge is grayer than the threshold
        centre = low + int(np.argmax(near))
        rows[max(0, centre - 1) : centre + 2] = True
    return cv2.dilate(rows.astype(np.uint8)[:, None], np.ones((3, 1), np.uint8))[:, 0].astype(bool)


def _line_free(ink: NDArray, lines: list[float], unit: float, start: int) -> NDArray:
    """ink without the staff lines: on a line's rows, vertical runs no longer than a line is thick are taken out
    (a symbol crossing the line makes a longer run), and what a symbol lost on the line is closed again."""
    height = ink.shape[0]
    up = np.zeros(ink.shape, dtype=np.int32)
    down = np.zeros(ink.shape, dtype=np.int32)
    for r in range(height):
        up[r] = (up[r - 1] + 1) * ink[r] if r else ink[r]
    for r in range(height - 1, -1, -1):
        down[r] = (down[r + 1] + 1) * ink[r] if r < height - 1 else ink[r]
    run = up + down - 1
    on_line = _line_rows(ink, lines, unit, start)
    free = ink & ~(on_line[:, None] & (run <= max(3, _LINE_RUN * unit)))
    tall = max(3, round(0.4 * unit)) | 1
    return cv2.morphologyEx(free.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((tall, 3), np.uint8)).astype(bool)


def _clef_box(ink: NDArray, lines: list[float], unit: float, start: float) -> tuple[int, int, int, int] | None:
    """The treble clef's box (x0, y0, x1, y1, in the window): the leftmost component near the staff's start that is
    tall and wide enough, rises over the top line, reaches down to the bottom line (its tail may have been cut off
    where it crosses that line) and is wide across the middle lines, where it curls (a bracket, a brace or a barline
    is a narrow bar there, whatever its hooks)."""
    free = _line_free(ink, lines, unit, int(start))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(free.astype(np.uint8), 8)
    middle_rows = labels[max(0, round(lines[1])) : round(lines[3]) + 1]
    best = None
    for k in range(1, count):
        x, y, w, h = stats[k, :4]
        middle = x + w / 2
        if not (_CLEF_MIN_HEIGHT * unit <= h <= _CLEF_MAX_HEIGHT * unit and w >= _CLEF_MIN_WIDTH * unit):
            continue
        if y > lines[0] - 0.3 * unit or y + h < lines[-1] - 0.5 * unit:
            continue
        if not start - 0.5 * unit <= middle <= start + _CLEF_MAX_START * unit:
            continue
        if best is not None and middle >= best[0] + (best[2] - best[0]) / 2:
            continue
        columns = np.flatnonzero((middle_rows == k).any(axis=0))
        if len(columns) == 0 or columns[-1] - columns[0] + 1 < _CLEF_BODY * unit:
            continue
        best = (int(x), int(y), int(x + w), int(y + h))
    return best


def _holes(band: NDArray, unit: float) -> list[tuple[int, int, int, int, int]]:
    """The holes of the band's ink: (x0, y0, x1, y1, outline), outline naming the piece of ink they are in."""
    contours, hierarchy = cv2.findContours(band.astype(np.uint8), cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if hierarchy is None:
        return []
    result = []
    for k, contour in enumerate(contours):
        parent = hierarchy[0][k][3]
        if parent < 0:
            continue
        x, y, w, h = cv2.boundingRect(contour)
        area = max(cv2.contourArea(contour), 1.0)
        if not (_HOLE_MIN_AREA <= area / unit**2 <= _HOLE_MAX_AREA and h <= _HOLE_MAX_HEIGHT * unit):
            continue
        result.append((x, y, x + w, y + h, parent))
    return result


def _digit_boxes(
    ink: NDArray, unit: float, lines: list[float], clef: tuple[int, int, int, int], change: int
) -> list[tuple[tuple[int, int, int, int], bool]]:
    """Where an 8 may be (boxes in the window) in the band under the clef (change -1) or over it (+1), each with
    whether both its holes were seen: two holes one above the other in one piece of ink; failing that (a blurred
    or coarse print fills one), one hole, as the 8's upper or lower loop. A box is of a digit's size, under (over)
    the middle of the clef and close to it, with white beside it."""
    if change < 0:
        top, bottom = int(lines[-1] + _BAND_NEAR * unit), int(lines[-1] + _BAND_FAR * unit)
    else:
        top, bottom = int(lines[0] - _BAND_FAR * unit), int(lines[0] - _BAND_NEAR * unit)
    left, right = int(clef[0] - _SIDE * unit), int(clef[2] + _SIDE * unit)
    top, bottom, left, right = max(0, top), min(ink.shape[0], bottom), max(0, left), min(ink.shape[1], right)
    if bottom - top < unit or right <= left:
        return []
    holes = [(x0 + left, y0 + top, x1 + left, y1 + top, outline)
             for x0, y0, x1, y1, outline in _holes(ink[top:bottom, left:right], unit)]
    stroke = _STROKE * unit
    pairs, singles = [], []
    for a in holes:
        for b in holes:
            if a is b or a[4] != b[4] or (a[1] + a[3]) >= (b[1] + b[3]):
                continue
            dx = abs((a[0] + a[2]) - (b[0] + b[2])) / 2
            dy = ((b[1] + b[3]) - (a[1] + a[3])) / 2
            if dx <= _HOLES_DX * unit and _HOLES_DY[0] * unit <= dy <= _HOLES_DY[1] * unit:
                pairs.append((min(a[0], b[0]) - stroke, a[1] - stroke, max(a[2], b[2]) + stroke, b[3] + stroke))
    for a in holes:
        sides = (a[0] - stroke, a[2] + stroke)
        singles.append((sides[0], a[1] - stroke, sides[1], a[1] - stroke + _ONE_HOLE_DIGIT * unit))  # upper loop
        singles.append((sides[0], a[3] + stroke - _ONE_HOLE_DIGIT * unit, sides[1], a[3] + stroke))  # lower loop
    width = clef[2] - clef[0]
    clear = max(1, round(_CLEAR * unit))
    found = []
    for candidates, both in ((pairs, True), (singles, False)):
        for x0, y0, x1, y1 in candidates:
            x0, y0 = max(0, int(x0)), max(0, int(y0))
            x1, y1 = min(ink.shape[1], int(x1 + 1)), min(ink.shape[0], int(y1 + 1))
            if not (_DIGIT_HEIGHT[0] * unit <= y1 - y0 <= _DIGIT_HEIGHT[1] * unit):
                continue
            if not (_DIGIT_WIDTH[0] * unit <= x1 - x0 <= _DIGIT_WIDTH[1] * unit):
                continue
            # under (over) the clef's middle, not its edge: a measure number stands at the staff's start
            if not clef[0] + _MIDDLE * width <= (x0 + x1) / 2 <= clef[2] - _MIDDLE * width:
                continue
            # close to the clef: right under its tail (over its top), the staff's lines not far
            if change < 0 and (y0 > lines[-1] + _DIGIT_GAP * unit or y0 > clef[3] + _CLEF_GAP * unit):
                continue
            if change > 0 and (y1 < lines[0] - _DIGIT_GAP * unit or y1 < clef[1] - _CLEF_GAP * unit):
                continue
            # white beside the digit, at its height (away from the clef, which may touch it): not a word's letter
            quarter = (y1 - y0) // 4
            rows = slice(y0 + quarter, y1) if change < 0 else slice(y0, y1 - quarter)
            if ink[rows, max(0, x0 - clear) : x0].any() or ink[rows, x1 : x1 + clear].any():
                continue
            found.append(((x0, y0, x1, y1), both))
    return found


def _read(gray: NDArray, box: tuple[int, int, int, int], unit: float) -> tuple[str, float]:
    """What OCR reads in the box (the recogniser alone: the box is the text)."""
    from rapidocr.ch_ppocr_rec import TextRecInput  # noqa: PLC0415

    from homr.baslik_okuyucu import _engine  # noqa: PLC0415  (loads the OCR on first use)

    x0, y0, x1, y1 = box
    pad = max(2, round(0.3 * unit))
    crop = gray[max(0, y0) : y1, max(0, x0) : x1]
    crop = cv2.copyMakeBorder(crop, pad, pad, 2 * pad, 2 * pad, cv2.BORDER_CONSTANT, value=255)
    result = _engine().text_rec(TextRecInput(img=[cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)]))
    if not result.txts:
        return "", 0.0
    return result.txts[0].strip(), float(result.scores[0])


def find_octave_mark_at(
    gray: NDArray, start: float, lines: list[float], unit: float, above: bool = True
) -> OctaveMark | None:
    """The 8 of an octave treble clef at a staff that starts at x start, with its five lines at the rows lines
    (top to bottom, at the clef) and unit pixels between lines; None when there is none, or no treble clef.
    above: an 8 over the clef is looked for too."""
    left = max(0, int(start - _LEFT * unit))
    top = max(0, int(lines[0] - _ABOVE * unit))
    right = min(gray.shape[1], int(start + _RIGHT * unit))
    bottom = min(gray.shape[0], int(lines[-1] + _BELOW * unit))
    if right - left < 3 * unit or bottom <= lines[-1]:
        return None
    ink = gray[top:bottom, left:right] < _INK
    local = [y - top for y in lines]
    clef = _clef_box(ink, local, unit, start - left)
    if clef is None:
        return None
    for change in (-1, 1) if above else (-1,):
        for box, both in _digit_boxes(ink, unit, local, clef, change):
            found = (left + box[0], top + box[1], left + box[2], top + box[3])
            text, score = _read(gray, found, unit)
            if text == "8" and score >= (_MIN_SCORE if both else _MIN_SCORE_ONE_HOLE):
                return OctaveMark(change, found, text, score)
    return None


def find_octave_mark(image: NDArray, staff: Staff, above: bool = True) -> OctaveMark | None:
    """The octave mark of the clef a staff starts with, on the page image the staff was found on."""
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    unit = float(staff.average_unit_size)
    at = min(staff.grid, key=lambda p: abs(p.x - (staff.min_x + 3 * unit)))
    return find_octave_mark_at(gray, float(staff.min_x), [float(y) for y in at.y], unit, above)


def mark_octave_clef(
    symbols: list[EncodedSymbol], image: NDArray, staff: Staff, above: bool = True
) -> tuple[list[EncodedSymbol], int]:
    """A staff's reading with the clef it starts with marked as an octave clef when the page shows an 8 at it, and
    the octave change (0: none). Only a reading whose first clef is clef_G2, before any note or rest, is looked at;
    a page without an 8 keeps its reading as it was. above: an 8 over the clef counts too (not over a system's top
    staff, where the measure number stands)."""
    first = None
    for index, symbol in enumerate(symbols):
        if symbol.rhythm.startswith(("note", "rest")):
            break
        if symbol.rhythm.startswith("clef"):
            first = index
            break
    if first is None or symbols[first].rhythm != "clef_G2":
        return symbols, 0
    mark = find_octave_mark(image, staff, above)
    if mark is None:
        return symbols, 0
    marked = list(symbols)
    marked[first] = symbols[first].with_clef_octave(mark.change)
    return marked, mark.change
