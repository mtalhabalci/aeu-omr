"""Lyrics: the syllables written under a staff, given to the notes they stand under as MusicXML <lyric>.

Words. A typeset PDF page that carries its text (Finale or Mus2 printed to PDF) gives its words with their boxes, exact;
a page that is a picture gives them by OCR (RapidOCR's latin recogniser, which has the Turkish letters, with a box for
each word), read in each staff's lyric band only.

Bands and verses. A staff's lyric band is the strip under it, as wide as the staff, down to the next staff below it (and
no further than a few staff heights). The band's words fall into lines by their height; line n from the top is verse n.
Words that are not sung are left out: section and instrument names (ARANAĞMESİ, GİRİŞ SAZI, SAZ, NAKARAT, MEYAN, SON...),
a line written all in capitals, numbers, and the signs of the music font.

Notes. Each syllable goes to the note whose head stands nearest above it. The heads are those the staff detection found
(x and place on the staff); they are matched to the staff's written notes in order by their place on the staff (the
diatonic step), so that a head the detection missed or one too many shifts nothing; a written note without a head gets
an x between its neighbours'. A line's syllables are given to the notes left to right, one to a note, the nearest in all;
a rest, a grace note and the second note of a tie take none.

Every syllable is written as 'single': the printed scores read here draw no hyphens between syllables, so the word
boundaries are not on the page, and a 'single' draws the syllables as the page does.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from xml.sax.saxutils import escape

import numpy as np

# words of a lyric band that are not sung: section and instrument names, written in the band of a staff with no lyrics
NOT_SUNG = {
    "aranagme", "aranagmesi", "aranagmeler", "saz", "sazi", "giris", "girissazi", "nakarat", "meyan", "meyana", "son",
    "fine", "teslim", "zemin", "karar", "karara", "tekrar", "hane", "mulazime", "terennum", "dc", "ds", "coda", "segno",
    "alcoda", "dalsegno", "dacapo", "bis", "ara", "nagme", "nagmesi",
}
_FOLD = str.maketrans("çğıİöşüâîûÇĞÖŞÜÂÎÛ", "cgiiosuaiuCGOSUAIU")
_VOWELS = set("aeıioöuüâîûAEIİOÖUÜÂÎÛ")
_STEPS = "CDEFGAB"
_E4 = 4 * 7 + 2  # the bottom line of a treble staff, its place 1


@dataclass
class Word:
    """A word on the page: its text and its box in the page image's pixels (x0, y0, x1, y1)."""

    text: str
    box: tuple[float, float, float, float]
    score: float = 1.0

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def cy(self) -> float:
        return (self.box[1] + self.box[3]) / 2

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]


@dataclass
class StaffLyrics:
    """A staff's lyric lines (verse 1 first), each its syllables left to right."""

    lines: list[list[Word]] = field(default_factory=list)


def _fold(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.translate(_FOLD).lower())


def _letters(text: str) -> str:
    return "".join(c for c in text if c.isalpha())


def _music_font(text: str) -> bool:
    """Signs of a music font: private-use characters (Maestro, Petrucci, Mus2 fonts printed to PDF)."""
    return any(0xE000 <= ord(c) <= 0xF8FF for c in text)


def text_layer_words(pdf_path: str, page_no: int, zoom: float) -> list[Word]:
    """The words of a PDF page's text layer, their boxes in the pixels of the page rendered at zoom (page_no from 1).
    Words of a music font and words without a letter are left out."""
    import fitz  # noqa: PLC0415

    words = []
    with fitz.open(pdf_path) as document:
        page = document[page_no - 1]
        to_pixels = page.rotation_matrix * fitz.Matrix(zoom, zoom)
        for x0, y0, x1, y1, text, *_ in page.get_text("words"):
            if _music_font(text) or not _letters(text):
                continue
            r = fitz.Rect(x0, y0, x1, y1) * to_pixels
            words.append(Word(text, (r.x0, r.y0, r.x1, r.y1)))
    return words


_ocr = None


def _ocr_engine():  # noqa: ANN202
    """RapidOCR with the latin recogniser (it has ç ğ ı ö ş ü â î û); loaded once."""
    global _ocr  # noqa: PLW0603
    if _ocr is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR  # noqa: PLC0415

        # the latin recogniser exists as PP-OCRv5 mobile (latin_PP-OCRv5_rec_mobile)
        _ocr = RapidOCR(params={"Global.log_level": "warning", "Rec.lang_type": LangRec.LATIN,
                                "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE})
    return _ocr


def ocr_words(gray: np.ndarray, bands: list[tuple[int, int, int, int]]) -> list[Word]:
    """The words OCR reads in the given bands (x0, y0, x1, y1) of a page image, their boxes in the page's pixels.
    A band is read on its own, enlarged so that its text stands about 48 pixels high."""
    import cv2  # noqa: PLC0415

    engine = _ocr_engine()
    words: list[Word] = []
    for x0, y0, x1, y1 in bands:
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(gray.shape[1], int(x1)), min(gray.shape[0], int(y1))
        if x1 - x0 < 8 or y1 - y0 < 8:
            continue
        crop = gray[y0:y1, x0:x1]
        scale = 2.0
        crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        result = engine(rgb, return_word_box=True)
        if result is None or result.boxes is None:
            continue
        for line_words in result.word_results or []:
            for text, score, box in line_words:
                if not text or not text.strip():
                    continue
                points = np.asarray(box, dtype=float) / scale
                bx0, by0 = points[:, 0].min() + x0, points[:, 1].min() + y0
                bx1, by1 = points[:, 0].max() + x0, points[:, 1].max() + y0
                for part, part_box in _split_spaces(text, (bx0, by0, bx1, by1)):
                    if _letters(part):
                        words.append(Word(part, part_box, float(score)))
    return words


def _split_spaces(text: str, box: tuple[float, float, float, float]) -> list[tuple[str, tuple]]:
    """A box holding several space-separated words, split by their share of the characters."""
    parts = text.split()
    if len(parts) <= 1:
        return [(text.strip(), box)]
    total = len(text)
    out, start = [], 0
    for part in parts:
        begin = text.index(part, start)
        end = begin + len(part)
        start = end
        x0 = box[0] + (box[2] - box[0]) * begin / total
        x1 = box[0] + (box[2] - box[0]) * end / total
        out.append((part, (x0, box[1], x1, box[3])))
    return out


def lyric_bands(staff_boxes: list[tuple[float, float, float, float]],
                page_height: float) -> list[tuple[float, float, float, float]]:
    """Each staff's lyric band on its page (staff boxes in the page's pixels, any order): from a little above the
    staff's bottom line down to the next staff below it, no more than four staff heights."""
    bands = []
    for box in staff_boxes:
        height = box[3] - box[1]
        below = [b[1] for b in staff_boxes if b[1] > box[3] and min(b[2], box[2]) - max(b[0], box[0]) > 0]
        bottom = min([*below, box[3] + 4 * height, page_height])
        bands.append((box[0] - height, box[3] - 0.25 * height, box[2] + height * 0.5, bottom))
    return bands


def staff_lyrics(words: list[Word], staff_boxes: list[tuple[float, float, float, float]],
                 page_height: float) -> list[StaffLyrics]:
    """The lyric lines under each of a page's staffs (staff boxes in the page's pixels). The lines follow one
    another from under the staff: the first within two staff heights of its bottom line, each next within two
    line heights of the one before; text farther down (a poem printed under the last staff) is not the staff's."""
    bands = lyric_bands(staff_boxes, page_height)
    taken: list[list[Word]] = [[] for _ in staff_boxes]
    for word in words:
        best = None
        for n, (x0, y0, x1, y1) in enumerate(bands):
            if x0 <= word.cx <= x1 and y0 <= word.cy <= y1 and word.box[1] >= y0 - 0.1 * (y1 - y0):
                # the band of the nearest staff above the word
                if best is None or staff_boxes[n][3] > staff_boxes[best][3]:
                    best = n
        if best is not None:
            taken[best].append(word)
    out = []
    for box, ws in zip(staff_boxes, taken, strict=True):
        lines = _lines(ws)
        kept, last = [], box[3]
        for n, line in enumerate(lines):
            top = min(w.box[1] for w in line)
            height = float(np.median([w.height for w in line]))
            if top - last > (2 * (box[3] - box[1]) if n == 0 else 2 * height):
                break
            kept.append(line)
            last = max(w.box[3] for w in line)
        out.append(StaffLyrics(kept))
    return out


def _clean(text: str) -> str:
    """A syllable without the dots, dashes and underlines written after it (a held syllable: 'hep..', 'sin___')
    and without stray signs; an apostrophe inside (n'olur) stays."""
    kept = "".join(c for c in text if c.isalpha() or c in "'’")
    return kept.strip("'’")


def syllables(word: str) -> list[str]:
    """A Turkish word in its syllables: one vowel to a syllable; between two vowels a single consonant goes with the
    second (ye-le), of several the last does (kay-nar-sın, Türk-çe)."""
    vowels = [i for i, c in enumerate(word) if c in _VOWELS]
    if len(vowels) <= 1:
        return [word]
    cuts = [b if b - a == 1 else b - 1 for a, b in zip(vowels, vowels[1:])]
    return [word[i:j] for i, j in zip([0, *cuts], [*cuts, len(word)])]


def _split_syllables(word: Word) -> list[Word]:
    """A word of several syllables (written close together, or typed as one word) as its syllables, each with its
    share of the box by its letters."""
    parts = syllables(word.text)
    if len(parts) == 1:
        return [word]
    out, start, total = [], 0, len(word.text)
    x0, y0, x1, y1 = word.box
    for part in parts:
        end = start + len(part)
        out.append(Word(part, (x0 + (x1 - x0) * start / total, y0, x0 + (x1 - x0) * end / total, y1), word.score))
        start = end
    return out


def _poem(line: list[Word]) -> bool:
    """A line of whole words (the poem printed under the score), not of syllables: most of its words long."""
    lengths = [len(_letters(w.text)) for w in line]
    return len(lengths) >= 3 and (float(np.median(lengths)) >= 5 or sum(n >= 7 for n in lengths) * 2 > len(lengths))


def _sung(word: Word) -> bool:
    """A syllable: letters with a vowel (a lone consonant is a sign of the music font: v, d), not a section's name."""
    letters = _letters(word.text)
    if not letters or _music_font(word.text) or not any(c in _VOWELS for c in letters):
        return False
    return _fold(word.text) not in NOT_SUNG


def _lines(words: list[Word]) -> list[list[Word]]:
    """A band's words in lines by height, top first, each left to right; a line of capitals only (a section's name)
    and the words that are not sung are left out."""
    if not words:
        return []
    words = sorted(words, key=lambda w: w.cy)
    tolerance = 0.6 * float(np.median([w.height for w in words]))
    lines: list[list[Word]] = [[words[0]]]
    for word in words[1:]:
        if word.cy - np.mean([w.cy for w in lines[-1]]) > tolerance:
            lines.append([word])
        else:
            lines[-1].append(word)
    out = []
    for line in lines:
        capitals = all(_letters(w.text).isupper() and len(_letters(w.text)) >= 2 for w in line)
        if capitals and not any(_letters(w.text).islower() for w in line):
            continue
        kept = sorted((Word(_clean(w.text), w.box, w.score) for w in line if _sung(w)), key=lambda w: w.cx)
        kept = [w for w in kept if w.text]
        if kept and _poem(kept):
            break  # the poem under the score; nothing under it is sung either
        kept = [part for w in kept for part in _split_syllables(w)]
        if kept:
            out.append(kept)
    return out


@dataclass
class _Note:
    measure: int
    start: int  # the <note> element's place in the MusicXML text
    end: int
    place: int | None  # place on a treble staff (1 = bottom line), None for a rest
    takes_syllable: bool
    x: float | None = None


_MEASURE = re.compile(r'<measure number="(\d+)"[^>]*>.*?</measure>', re.S)
_NOTE = re.compile(r"<note\b[^>]*>.*?</note>", re.S)
_PITCH = re.compile(r"<step>([A-G])</step>(?:\s*<alter>[^<]*</alter>)?\s*<octave>(-?\d+)</octave>")


def _staff_notes(musicxml: str, first: int, last: int) -> list[_Note]:
    notes = []
    for m in _MEASURE.finditer(musicxml):
        number = int(m.group(1))
        if not first <= number <= last:
            continue
        for n in _NOTE.finditer(musicxml, m.start(), m.end()):
            text = n.group(0)
            pitch = _PITCH.search(text)
            rest = "<rest" in text or pitch is None
            place = None if rest else int(pitch.group(2)) * 7 + _STEPS.index(pitch.group(1)) - _E4 + 1
            tie_stop = '<tie type="stop"' in text
            notes.append(_Note(number, n.start(), n.end(), place,
                               not rest and "<grace" not in text and not tie_stop and "<chord" not in text))
    return notes


def _match_heads(notes: list[_Note], heads: list[tuple[float, int]], left: float, right: float) -> None:
    """Gives each written note an x: its head's, matched in order by place on the staff (Needleman-Wunsch), or one
    between its neighbours'."""
    pitched = [n for n in notes if n.place is not None]
    heads = sorted(heads)
    a, b = [n.place for n in pitched], [p for _, p in heads]
    gap = 1.0

    def cost(i: int, j: int) -> float:
        d = abs(a[i] - b[j])
        return 0.0 if d == 0 else 0.6 if d == 1 else 1.6 if d == 2 else 99.0

    rows, cols = len(a) + 1, len(b) + 1
    table = np.zeros((rows, cols))
    table[:, 0] = np.arange(rows) * gap
    table[0, :] = np.arange(cols) * gap
    for i in range(1, rows):
        for j in range(1, cols):
            table[i, j] = min(table[i - 1, j - 1] + cost(i - 1, j - 1), table[i - 1, j] + gap, table[i, j - 1] + gap)
    i, j = len(a), len(b)
    while i > 0 and j > 0:
        if table[i, j] == table[i - 1, j - 1] + cost(i - 1, j - 1) and cost(i - 1, j - 1) < 99:
            pitched[i - 1].x = heads[j - 1][0]
            i, j = i - 1, j - 1
        elif table[i, j] == table[i - 1, j] + gap:
            i -= 1
        else:
            j -= 1
    # notes without a head, rests too: between their neighbours'
    known = [(k, n.x) for k, n in enumerate(notes) if n.x is not None]
    for k, n in enumerate(notes):
        if n.x is not None:
            continue
        before = [(kk, x) for kk, x in known if kk < k]
        after = [(kk, x) for kk, x in known if kk > k]
        lo = before[-1] if before else (-1, left)
        hi = after[0] if after else (len(notes), right)
        n.x = lo[1] + (hi[1] - lo[1]) * (k - lo[0]) / (hi[0] - lo[0])


def _assign(syllables: list[Word], notes: list[_Note], unit: float) -> list[int | None]:
    """The note (index into notes) of each syllable of a line: one to a note, in order, the nearest in all."""
    takers = [k for k, n in enumerate(notes) if n.takes_syllable]
    m, k = len(syllables), len(takers)
    if m == 0 or k == 0:
        return [None] * m
    if m > k:  # more syllables than notes: the farthest are left out
        syllables_kept = sorted(range(m), key=lambda i: min(abs(syllables[i].cx - notes[t].x) for t in takers))[:k]
        result: list[int | None] = [None] * m
        sub = _assign([syllables[i] for i in sorted(syllables_kept)], notes, unit)
        for i, r in zip(sorted(syllables_kept), sub, strict=True):
            result[i] = r
        return result
    dist = np.array([[abs(s.cx - notes[t].x) / unit for t in takers] for s in syllables])
    inf = float("inf")
    best = np.full((m, k), inf)
    back = np.zeros((m, k), dtype=int)
    best[0] = dist[0]
    for i in range(1, m):
        run_min, run_arg = inf, -1
        for j in range(k):
            if j - 1 >= 0 and best[i - 1, j - 1] < run_min:
                run_min, run_arg = best[i - 1, j - 1], j - 1
            if run_arg >= 0:
                best[i, j] = run_min + dist[i, j]
                back[i, j] = run_arg
    j = int(np.argmin(best[m - 1]))
    out = [0] * m
    for i in range(m - 1, -1, -1):
        out[i] = takers[j]
        j = back[i, j]
    return out


def add_lyrics(musicxml: str, staff_measures: list[tuple[int, int]], heads: list[list[tuple[float, int]]],
               lyrics: list[StaffLyrics], staff_boxes: list[tuple[float, float, float, float]]
               ) -> tuple[str, list[dict]]:
    """The MusicXML with each staff's syllables written to its notes, and a record of every syllable (staff, verse,
    text, measure, the note's place in the measure among its notes, or None when no note took it). For each staff,
    in order: its first and last measure, its heads (x, place on the staff) and its box in the page's pixels.
    A score of several parts or a staff with a clef other than the treble clef is left as it is."""
    if musicxml.count("<score-part ") > 1 or re.search(r"<sign>[FC]</sign>", musicxml):
        return musicxml, []
    inserts: dict[int, list[str]] = {}
    record: list[dict] = []
    for staff, ((first, last), staff_heads, staff_lyrics_, box) in enumerate(
            zip(staff_measures, heads, lyrics, staff_boxes, strict=True), 1):
        if first > last or not staff_lyrics_.lines:
            continue
        notes = _staff_notes(musicxml, first, last)
        if not notes:
            continue
        unit = (box[3] - box[1]) / 4
        _match_heads(notes, staff_heads, box[0], box[2])
        in_measure: dict[int, int] = {}
        place_in_measure = []
        for n in notes:
            place_in_measure.append(in_measure.get(n.measure, 0))
            in_measure[n.measure] = place_in_measure[-1] + 1
        for verse, line in enumerate(staff_lyrics_.lines, 1):
            for word, k in zip(line, _assign(line, notes, unit), strict=True):
                record.append({"porte": staff, "kita": verse, "hece": word.text,
                               "olcu": None if k is None else notes[k].measure,
                               "nota": None if k is None else place_in_measure[k],
                               "x": round(word.cx, 1), "notaX": None if k is None else round(notes[k].x, 1),
                               "guven": round(word.score, 3)})
                if k is None:
                    continue
                inserts.setdefault(notes[k].end, []).append(
                    f'<lyric number="{verse}"><syllabic>single</syllabic><text>{escape(word.text)}</text></lyric>')
    out, at = [], 0
    for end in sorted(inserts):
        close = musicxml.rfind("</note>", 0, end)
        out.append(musicxml[at:close])
        out.append("".join(sorted(inserts[end], key=lambda s: int(re.search(r'number="(\d+)"', s).group(1)))))
        at = close
    out.append(musicxml[at:])
    return "".join(out), record
