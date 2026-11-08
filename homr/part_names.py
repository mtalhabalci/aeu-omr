"""The instrument or voice names printed left of a system ("Soprano", "Piano", "Vl. I"), read by OCR.

A system of several staffs often names its staffs at the left margin: in full on the first system, shortened or not
at all on the next ones. The margin left of the system's start is read once (RapidOCR, as the title block), and each
text goes to the part whose staffs it stands beside: a single staff's height, or a braced group's from its top line
to its bottom line, a space either way. A text without a letter, or longer than a name is, is left out.
"""

import cv2
import numpy as np

from homr.model import MultiStaff
from homr.type_definitions import NDArray

_MARGIN = 1.0  # staff spaces above and below a part's staffs that its name may reach
_GAP = 0.25  # staff spaces left of the staffs' start where the margin ends
_MAX_LENGTH = 30
_MIN_SCORE = 0.85  # "Piano", "S", "A" read at 0.96-1.0; a stray "3." came out "si" at 0.78
_OCR_SIDE = 736  # RapidOCR's text detector enlarges an image whose shorter side is under this to it


def _at_page_scale(strip: NDArray) -> NDArray:
    """The strip on a canvas at least _OCR_SIDE pixels each way, in the tone of its paper, the strip at the top
    right. Alone, a margin strip goes through the text detector enlarged until its width is _OCR_SIDE: one 46 pixels
    wide and 1,311 high (a system of nine staffs) went through 16 times larger, ~21,000 pixels high, in 9.7 s and
    2.1 GB, for two words. On the canvas its text is read at the page's scale. The boxes keep their y; their x moves
    by the canvas's left part, and the words of a name keep their order."""
    height, width = strip.shape[:2]
    if min(height, width) >= _OCR_SIDE:
        return strip
    paper = np.median(strip.reshape(-1, strip.shape[2]), axis=0).astype(np.uint8)
    canvas = np.empty((max(height, _OCR_SIDE), max(width, _OCR_SIDE), strip.shape[2]), np.uint8)
    canvas[:] = paper
    canvas[:height, canvas.shape[1] - width :] = strip
    return canvas


def _clean(text: str) -> str | None:
    text = text.strip(" |[]{}()_-:;,")
    if not any(c.isalpha() for c in text) or len(text) > _MAX_LENGTH:
        return None
    return text


def read_part_names(image: NDArray, system: MultiStaff, slots: list[list[int]]) -> list[str | None]:
    """The name printed beside each slot of the system (a slot: the staffs of one part, by index from the top),
    None where nothing is read."""
    from homr.baslik_okuyucu import ocr_items  # noqa: PLC0415  (loads the OCR on first use)

    staffs = system.staffs
    unit = float(np.median([staff.average_unit_size for staff in staffs]))
    right = int(min(staff.min_x for staff in staffs) - _GAP * unit)
    top = int(max(0, min(staff.min_y for staff in staffs) - _MARGIN * unit))
    bottom = int(min(image.shape[0], max(staff.max_y for staff in staffs) + _MARGIN * unit))
    if right < 2 * unit or bottom <= top:
        return [None] * len(slots)
    strip = image[top:bottom, :right]
    if strip.ndim == 2:
        strip = cv2.cvtColor(strip, cv2.COLOR_GRAY2BGR)
    words: list[list[tuple[float, str]]] = [[] for _ in slots]
    for item in ocr_items(_at_page_scale(strip)):
        text = _clean(item.text)
        if text is None or item.score < _MIN_SCORE:
            continue
        middle = top + item.centre_y
        best, distance = None, None
        for n, slot in enumerate(slots):
            low = staffs[slot[0]].min_y - _MARGIN * unit
            high = staffs[slot[-1]].max_y + _MARGIN * unit
            if low <= middle <= high:
                d = abs(middle - (staffs[slot[0]].min_y + staffs[slot[-1]].max_y) / 2)
                if distance is None or d < distance:
                    best, distance = n, d
        if best is not None:
            words[best].append((item.box[0], text))
    names = [" ".join(text for _, text in sorted(found)) or None for found in words]
    return [name if name is None or len(name) <= _MAX_LENGTH else None for name in names]
