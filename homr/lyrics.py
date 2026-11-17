"""Lyrics: the syllables written under a staff, given to the notes they stand under as MusicXML <lyric>.

Words. A typeset PDF page that carries its text (Finale or Mus2 printed to PDF) gives its words with their boxes, exact;
a page that is a picture gives them by OCR (RapidOCR's latin recogniser, which has the Turkish letters, with a box for
each word), read in each staff's lyric band only.

Bands and verses. A staff's lyric band is the strip under it, as wide as the staff, down to the next staff below it (and
no further than a few staff heights). The band's words fall into lines by their height; line n from the top is verse n.
Words that are not sung are left out: section and instrument names (ARANAĞMESİ, GİRİŞ SAZI, SAZ, NAKARAT, MEYAN, SON...),
a heading written in capitals (but not a line of syllables in capitals: AK SA RAY DAN), a person's name beside the lyrics
(the arranger's), numbers, and the signs of the music font.

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
    "alcoda", "dalsegno", "dacapo", "bis", "ara", "nagme", "nagmesi", "koda", "kodaya", "meyansazi",
    # tempo words written under or over a staff
    "agir", "agirca", "agirdan", "cabuk", "cabukca", "orta", "ortaagir", "yavas", "yavasca", "hizli", "yuruk",
    "sert", "agirlasarak", "hizlanarak", "agirlasir", "serbest", "rubato", "moderato", "andante", "allegro",
    "adagio", "largo", "lento", "presto", "tempo",
    # usul names (written over the next staff)
    "aksak", "duyek", "sofyan", "semai", "curcuna", "nimsofyan", "turkaksagi", "devrihindi", "agiraksak",
    "yuruksemai", "aksaksemai", "agirsemai", "devrikebir", "cenber", "zencir", "muhammes", "darbeyn", "frenkcin",
    "lenkfahte", "evfer", "nimevfer", "devrituran", "raksaksagi", "usul", "usulu", "mertebe",
}
# the syllables an usul is said with (velvele), written under a staff: DÜM TEK TE KE, DÜM TÂ HEK
VELVELE = {"dum", "tek", "te", "ke", "ta", "hek", "teke", "tekke", "tahek"}
# a line holding one of these is a credit or a date, not sung (Güfte: ..., B.T.: 07 Ağustos 1963)
CREDITS = {"gufte", "beste", "bestekar", "guftekar", "notaya", "notayaalan", "bt", "derleyen", "duzenleyen", "kitaya"}
# Turkish letters of a font encoded in Windows-1254 but read as Windows-1252 (Faruk Þahin): none of these is Turkish
_CP1254 = str.maketrans("ÞþÝýÐð", "ŞşİıĞğ")
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
    left: bool = False  # written from its note (typewriter, hand lettering), not centred under it (typeset)

    @property
    def cx(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def anchor(self) -> float:
        """Where the syllable's note stands: under its middle when typeset, under its first letter when written
        from the note."""
        if not self.left:
            return self.cx
        return self.box[0] + (self.box[2] - self.box[0]) / max(1, len(self.text)) / 2

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
            words.append(Word(text.translate(_CP1254), (r.x0, r.y0, r.x1, r.y1)))
    return words


_ocr = None


def _ocr_engine():  # noqa: ANN202
    """RapidOCR with the latin recogniser (it has ç ğ ı ö ş ü â î û); loaded once."""
    global _ocr  # noqa: PLW0603
    if _ocr is None:
        from rapidocr import LangRec, ModelType, OCRVersion, RapidOCR  # noqa: PLC0415

        # the latin recogniser exists as PP-OCRv5 mobile (latin_PP-OCRv5_rec_mobile). The detector is not to enlarge
        # a band (its default brings the shorter side up to 736 px, a band 4,700 px wide): as good on the Üsküdar
        # pages read as pictures (83.8 % of the text layer's syllables against 84.3), 2.7 times as fast on Atkoşar's
        _ocr = RapidOCR(params={"Global.log_level": "warning", "Rec.lang_type": LangRec.LATIN,
                                "Rec.ocr_version": OCRVersion.PPOCRV5, "Rec.model_type": ModelType.MOBILE,
                                "Det.limit_type": "max", "Det.limit_side_len": 4000,
                                "EngineConfig.onnxruntime.use_cuda": os.environ.get("OMR_SOZ_OCR_GPU") == "1"})
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
        # lyrics stand upright: the angle classifier only turns some syllables upside down (sun -> uns)
        result = engine(rgb, use_cls=False, return_word_box=True)
        if result is None or result.boxes is None:
            continue
        for line_words in result.word_results or []:
            # a line is its words (text, score, box) each; a line read empty comes as one ('', 1.0, None)
            items = [line_words] if line_words and isinstance(line_words[0], str) else list(line_words or [])
            for item in items:
                if not isinstance(item, (tuple, list)) or len(item) != 3 or item[2] is None:
                    continue
                text, score, box = item
                if not text or not text.strip():
                    continue
                points = np.asarray(box, dtype=float) / scale
                bx0, by0 = points[:, 0].min() + x0, points[:, 1].min() + y0
                bx1, by1 = points[:, 0].max() + x0, points[:, 1].max() + y0
                for part, part_box in _split_spaces(text, (bx0, by0, bx1, by1)):
                    if _letters(part):
                        words.append(Word(part, part_box, float(score), left=True))
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
        out.append(Word(part, (x0 + (x1 - x0) * start / total, y0, x0 + (x1 - x0) * end / total, y1), word.score,
                        word.left))
        start = end
    return out


def _poem(line: list[Word]) -> bool:
    """A line of whole words (the poem printed under the score), not of syllables: most of its words long."""
    lengths = [len(_letters(w.text)) for w in line]
    return len(lengths) >= 3 and (float(np.median(lengths)) >= 5 or sum(n >= 7 for n in lengths) * 2 > len(lengths))


def _closes(word: Word) -> bool:
    return word.text.rstrip(".,;").endswith(")")


def _outside_parentheses(line: list[Word], ocr: bool = False) -> list[Word]:
    """A line (left to right) without what stands in parentheses: a direction, (2'ye), (III ve IV KITA'YA). A
    parenthesis that nothing closes runs to the end of the line, but on a line read by OCR, which misses the ')' of a
    written (- - SAZ - -), only the opening word is left out, not the syllables after it."""
    out, i = [], 0
    while i < len(line):
        if line[i].text.startswith("("):
            close = next((j for j in range(i, len(line)) if _closes(line[j])), None)
            if close is None and not ocr:
                break
            i = i + 1 if close is None else close + 1
            continue
        out.append(line[i])
        i += 1
    return out


def _credit(line: list[Word], ocr: bool = False) -> bool:
    """A line (left to right) of a credit or a date: a colon (Güfte:, B.T.:), two digits in a word (07 Ağustos 1963)
    or a credit's word (Güfte Vâhid Özaydın). On a line read by OCR a colon counts only after letters among the line's
    first two words, and a number only as digits alone (or four in a word): a colon further on is a misread of the
    dots after a held syllable (ben de ği im :.SAZ), digits among letters a misread syllable (son as 50n)."""
    if not ocr:
        return any(":" in w.text or sum(c.isdigit() for c in w.text) >= 2 or _fold(w.text) in CREDITS for w in line)
    return any((i < 2 and ":" in w.text and _letters(w.text.split(":")[0])) or _number(w.text)
               or _fold(w.text) in CREDITS for i, w in enumerate(line))


def _number(text: str) -> bool:
    """A number of a date or a credit (07, 1963, 7.8.1963): digits only, two or more, or four digits in a word
    (1963'te). A word of digits and letters is a misread syllable (son read as 50n)."""
    core = re.sub(r"\W", "", text)
    digits = sum(c.isdigit() for c in core)
    return (len(core) >= 2 and core.isdigit()) or digits >= 4


def _without_spaced_letters(words: list[Word]) -> list[Word]:
    """Without the letters of a word written letter-spaced (A r a n a ğ m e s i ' n e, K a r a r): three or more
    one-letter words at about one height, each within a letter's height of the next."""
    singles = sorted((w for w in words if len(_letters(w.text)) == 1), key=lambda w: (round(w.cy / 4), w.box[0]))
    drop: set[int] = set()
    run: list[Word] = []
    for w in singles:
        if run and abs(w.cy - run[-1].cy) < 0.5 * w.height and w.box[0] - run[-1].box[2] < 1.2 * w.height:
            run.append(w)
        else:
            if len(run) >= 3:
                drop |= {id(x) for x in run}
            run = [w]
    if len(run) >= 3:
        drop |= {id(x) for x in run}
    return [w for w in words if id(w) not in drop]


def _vowels(text: str) -> int:
    return sum(c in _VOWELS for c in text)


def _heading(line: list[Word], ocr: bool = False) -> bool:
    """A line (left to right) in capitals that is not sung: a heading (a section's name, the work's name, its makam
    or usul, an abbreviation: ARANAĞME, RAST MARŞ, EVÇ SAZ SEMÂİSİ, ÜMC), a title in quotes or the syllables an usul is
    said with (DÜM TEK TE KE), not a line of syllables written in capitals (AK SA RAY DAN GE ÇER, HEY HEY HEY). A line
    of syllables has two or more, most of one vowel, and they stand apart, each under its note; a heading is one word,
    or words of several syllables, or words a space apart. On a line read by OCR, six or more short pieces (half of
    them three letters or fewer) are syllables even when OCR has joined some of them (EY Â HIDI GAYB AL ELI NI HAK KII
    ZÂ RIN): only their spacing is asked."""
    parts = [_letters(p) for w in line for p in re.split(r"[-–]", w.text) if _letters(p)]
    if not parts or not all(p.isupper() for p in parts):
        return False
    if len(parts) == 1:
        return len(parts[0]) >= 2  # a lone vowel is a syllable
    if all(_fold(p) in VELVELE for p in parts):
        return True
    short = ocr and len(parts) >= 6 and float(np.median([len(p) for p in parts])) <= 3
    if not short and sum(_vowels(p) > 1 for p in parts) * 4 > len(parts):  # words (OCR joins a few: GELIN, 2 in 9)
        return True
    gaps = [b.box[0] - a.box[2] for a, b in zip(line, line[1:])]
    return not gaps or float(np.median(gaps)) < 0.5 * float(np.median([w.height for w in line]))


def _name(word: Word) -> bool:
    """A word of a person's name (the arranger's, written beside the lyrics: Faruk Şahin): a capital and small letters,
    several syllables in one word. A syllable has one vowel."""
    letters = _letters(word.text)
    return len(letters) >= 2 and letters[0].isupper() and letters[1:].islower() and _vowels(letters) >= 2


def _names(line: list[Word]) -> list[Word]:
    """A line without a person's name written in it: two to four name words, side by side, in a line whose other
    words are syllables (one vowel each) or that holds nothing else."""
    out, n = list(line), len(line)
    i = 0
    while i < n:
        j = i
        while j < n and _name(line[j]):
            j += 1
        rest = line[:i] + line[j:]
        if 2 <= j - i <= 4 and all(_vowels(_letters(w.text)) <= 1 for w in rest):
            out = rest
            break
        i = j + 1 if j > i else i + 1
    return out


def _sung(word: Word) -> bool:
    """A syllable: letters with a vowel (a lone consonant is a sign of the music font: v, d), not a section's name."""
    letters = _letters(word.text)
    if not letters or _music_font(word.text) or not any(c in _VOWELS for c in letters):
        return False
    return _fold(word.text) not in NOT_SUNG


def _lines(words: list[Word]) -> list[list[Word]]:
    """A band's words in lines by height, top first, each left to right; a heading in capitals, a person's name and
    the words that are not sung are left out."""
    if not words:
        return []
    words = sorted(words, key=lambda w: w.cy)
    tolerance = 0.6 * float(np.median([w.height for w in words]))
    words = _without_spaced_letters(words)
    if not words:
        return []
    lines: list[list[Word]] = [[words[0]]]
    for word in words[1:]:
        if word.cy - np.mean([w.cy for w in lines[-1]]) > tolerance:
            lines.append([word])
        else:
            lines[-1].append(word)
    out = []
    for line in lines:
        line = sorted(line, key=lambda w: w.box[0])
        ocr = any(w.left for w in line)  # read by OCR from a scan, not from a page's exact text layer
        if ocr and _credit(line, ocr):  # a credit in parentheses, its ')' missed: (B.T.: Fuad Edip Baksı
            continue
        line = _outside_parentheses(line, ocr)
        if not line or _credit(line, ocr):
            continue
        if _heading(line, ocr):
            continue
        kept = sorted((Word(_clean(w.text), w.box, w.score, w.left) for w in line if _sung(w)), key=lambda w: w.cx)
        kept = [w for w in kept if w.text]
        if kept and _poem(kept):
            break  # the poem under the score; nothing under it is sung either
        kept = [part for w in _names(kept) for part in _split_syllables(w)]
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
        syllables_kept = sorted(range(m), key=lambda i: min(abs(syllables[i].anchor - notes[t].x) for t in takers))[:k]
        result: list[int | None] = [None] * m
        sub = _assign([syllables[i] for i in sorted(syllables_kept)], notes, unit)
        for i, r in zip(sorted(syllables_kept), sub, strict=True):
            result[i] = r
        return result
    dist = np.array([[abs(s.anchor - notes[t].x) / unit for t in takers] for s in syllables])
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
