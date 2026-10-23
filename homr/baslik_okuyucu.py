"""Read the title block of a makam score: the work's name, makam, form, usul, composer, lyricist and source.

The block is the text above the first staff. It is read by OCR (RapidOCR, already a dependency for homr's title
detection) and its lines are sorted into fields in three ways:

- a label in front of the value: "Usûlü: Ağır Düyek", "Beste: Dede Efendi", "Güfte: …", "Makam: …", "Söz ve
  Müzik: …" (both), also with the colon lost or misread; a label alone on its line takes the line under it
  ("BESTEKÂRI" over "SARI ONNİK", "YÖRESİ" over "KIRŞEHİR"); the labels of a collection record that are no field
  here ("Derleyen", "Kimden Alındığı") are left out with their values;
- a known name: a line that starts with a makam (and goes on with a form) is the makam and form line, "Acemaşîrân
  Şarkı", even when the form stands apart, beside or under the makam; an usul is known alone or after an "Usul"
  that lost its colon; the names come from the SymbTr Mus2 headers (training works only, see
  training/baslik/isimler.py);
- the layout: the largest centred line is the work's name; a publisher's line takes the lines stacked with it
  ("EMİN ONGAN / ÜSKÜDAR MÛSİKİ / CEMİYETİ NEŞRİYÂTI"); a composer's name may run on to the line under it.

Values are kept as printed (the app normalises them); every field carries its box in the page image and a
confidence, the OCR score lowered when the field was placed by layout alone.
"""
import json
import os
import re
import threading
import unicodedata
from dataclasses import dataclass, field

import numpy as np

NAMES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "baslik_isimleri.json")
BOTH = "bestekar+gufte"  # "Söz ve Müzik: Nâzım Yahya Efendi": one person wrote both

# label words (folded, words apart) -> field; a label may be followed by ":" or not
LABELS = {
    "usul": "usul", "usulu": "usul",
    "beste": "bestekar", "besteci": "bestekar", "bestekar": "bestekar", "bestekari": "bestekar", "muzik": "bestekar",
    "beste eden": "bestekar", "bestesi": "bestekar",
    "gufte": "gufte", "guftekar": "gufte", "soz": "gufte", "sozler": "gufte", "soz yazari": "gufte", "siir": "gufte",
    "soz ve muzik": BOTH, "soz muzik": BOTH, "muzik ve soz": BOTH, "gufte ve beste": BOTH, "beste ve gufte": BOTH,
    "soz ve beste": BOTH, "gufte beste": BOTH, "beste gufte": BOTH,
    "makam": "makam", "makami": "makam",
    "form": "form", "formu": "form", "tur": "form",
    "yore": "yore", "yoresi": "yore",  # a türkü's region: "Yöre: Bursa"
}
# labels that may stand alone on their line, the value under them (or beside them)
LONE_LABELS = {k: v for k, v in LABELS.items() if v in ("bestekar", "gufte", BOTH, "yore")}
SOURCE = re.compile(r"(?i)(www\.|https?://|\.com\b|\.org\b|\.net\b|\bT\s?R\s?T\b|kaynak\s*:|ne[sş]riy[aâ]t|"
                    r"yay[ıi]nlar[ıi]|cemiyeti|radyosu|m[uü]zik\s+dairesi|repertuv?ar|bakanl[ıi][gğ][ıi]|korosu|"
                    r"konservatuv?ar|ar[sş]ivi|derne[gğ]i|vakf[ıi]\b)")
SECTION = re.compile(r"(?i)^\s*(\d+\.?|birinci|ikinci|üçüncü|dördüncü)\s*h[aâ]ne\b|^\s*teslim\b|^\s*aranağme\b")
SECTION_WORDS = {"saz", "zemin", "nakarat", "meyan", "miyan", "aranagme", "aranagmesi", "teslim", "giris"}
TEMPO = re.compile(r"(?:=|♩|M\.?\s?M\.?)\s*(\d{2,3})\b|\b(\d{2,3})\s*⇒")
# a tempo mark inside a line, "Düyek (♩=160)", "(d= 72) Sengin Semâî": taken out, the rest is read
TEMPO_PART = re.compile(r"\(?\s*(?:\b[^\W\d_]{1,2}\b|[^\w\s=()]{1,2})?\s*\.?\s*=\s*\d{2,3}\b\s*\)?|\b\d{2,3}\s*⇒")
LENGTH = re.compile(r"\b(\d+\s*Dk)?\s*\d+\s*Sn\b|\b\d+\s*Dk\b")
LABEL_LINE = re.compile(r"^\s*([^\W\d_]+(?:(?:\s*,\s*|\s+|-)[^\W\d_]+){0,2})\s*[:：;?·•,=]\s*(.*)$")
# person labels that may lose their colon: "Beste Ömer Dilek", "Güftei Bâkî Nedim" (OCR made the colon an "i")
PERSON_WORDS = {"beste": "bestekar", "besteci": "bestekar", "bestekar": "bestekar", "bestekari": "bestekar",
                "muzik": "bestekar", "gufte": "gufte", "guftekar": "gufte"}
UNKNOWN = {"?", "-", "—", '"', "''"}  # Mus2 prints "Güfte: ?" for an unknown lyricist, others "Söz: -"
# labels of a collection record that name no field here ("Kimden Alındığı: …", "Derleyen: …"): the line is left out
OTHER_LABELS = {"kimden alindigi", "kimden alindi", "derleyen", "derleyenler", "notaya alan", "notaya alinis",
                "inceleme tarihi", "derleme tarihi", "duzenleyen", "duzenleme", "seslendiren", "icra eden",
                "derlendigi yer", "derleme yeri", "notaya alma tarihi", "kaynak kisi", "notalayan", "derleme",
                "inceleme"}
OTHER = "diger"  # a lone collection label: the line under it is its value, taken out and not kept


def fold(text: str) -> str:
    """ASCII form of a name as SymbTr's file names spell it (Bûselikaşîrân -> buselikasiran); accents and the comma
    letters OCR sometimes reads for ş (ș) go by Unicode decomposition."""
    text = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "I").replace("$", "s"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def near(a: str, b: str) -> bool:
    """At most one letter apart (a swap, a missing or an extra letter): OCR reads "Usul" as "Įsul" now and then."""
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


def distance(a: str, b: str) -> int:
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, y in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (x != y))
    return row[-1]


def label_field(words: str, letters: int = 1) -> tuple[str | None, float]:
    """The field a label names and how sure that is: exact, or a letter or two off for labels of four letters or
    more (OCR reads "Usûlü" as "Įsul", "USÓLÔ")."""
    if words in LABELS:
        return LABELS[words], 1.0
    for label, name in LABELS.items():
        if len(label) >= 4 + (letters - 1) and distance(words, label) <= letters:
            return name, 0.9 if letters == 1 else 0.8
    return None, 0.0


def fold_words(text: str) -> str:
    return " ".join(fold(w) for w in text.split() if fold(w))


def letters(text: str) -> int:
    """Latin letters, Turkish ones included; the odd CJK sign OCR makes of a note head ("二上二") is none."""
    return sum(c.isalpha() for c in fold(text))


@dataclass
class Item:
    text: str
    box: list[float]  # x0, y0, x1, y1 in the cropped image
    score: float

    @property
    def height(self) -> float:
        return self.box[3] - self.box[1]

    @property
    def width(self) -> float:
        return self.box[2] - self.box[0]

    @property
    def centre_x(self) -> float:
        return (self.box[0] + self.box[2]) / 2

    @property
    def centre_y(self) -> float:
        return (self.box[1] + self.box[3]) / 2


def _joined(a: Item, b: Item, text: str | None = None) -> Item:
    return Item(text if text is not None else a.text + " " + b.text,
                [min(a.box[0], b.box[0]), min(a.box[1], b.box[1]), max(a.box[2], b.box[2]), max(a.box[3], b.box[3])],
                min(a.score, b.score))


@dataclass
class Header:
    fields: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    boxes: dict[str, list[int]] = field(default_factory=dict)

    def put(self, name: str, value: str, item: "Item", confidence: float, offset: tuple[int, int]) -> None:
        if name == BOTH:
            for each in ("bestekar", "gufte"):
                self.put(each, value, item, confidence, offset)
            return
        if name in ("bestekar", "gufte"):  # "Dede Efendi (9/1/1778 - 29/11/1846)": the life dates go
            value = re.sub(r"\s*\([^()]*\d[^()]*\)\s*$", "", value)
        if name == "usul":  # "Devrikebîr (28/4)": the usul's numbers go, the name stays
            value = re.sub(r"\s*\(\s*\d+\s*/\s*\d+\s*\)", "", value)
        value = value.strip(" :;,.-='\"`·•" + ("()[]“”«»" if name == "eser_adi" else ""))
        # the "$" OCR reads for Ş ("HICAZ $ARKI"); a title block prints no dollar sign
        value = re.sub(r"\$(?=[^\W\d_])", lambda m: "Ş" if value[m.end()].isupper() else "ş", value)
        if not value or value in UNKNOWN or name in self.fields:
            return
        self.fields[name] = value
        self.confidence[name] = round(float(confidence), 3)
        dx, dy = offset
        self.boxes[name] = [round(float(item.box[0]) + dx), round(float(item.box[1]) + dy),
                            round(float(item.box[2]) + dx), round(float(item.box[3]) + dy)]

    def as_dict(self) -> dict:
        """The service's baslikBilgisi: the fields by their camelCase names, guven and kutu per field."""
        names = {"eser_adi": "eserAdi", "makam": "makam", "form": "form", "usul": "usul", "bestekar": "bestekar",
                 "gufte": "gufte", "yore": "yore", "kaynak": "kaynak"}
        out: dict = {names[k]: self.fields.get(k) for k in names}
        out["guven"] = {names[k]: v for k, v in self.confidence.items()}
        out["kutu"] = {names[k]: v for k, v in self.boxes.items()}
        return out


class NameLists:
    """Makam, form and usul names as SymbTr spells them in its file names, longest first, so that "Hicazkâr" is not
    read as "Hicaz"."""

    def __init__(self, path: str = NAMES) -> None:
        data = json.load(open(path, encoding="utf-8"))
        self.aliases = data.get("takma", {})
        self.lists = {kind: sorted(set(data[kind]) | set(self.aliases.get(kind, {})), key=len, reverse=True)
                      for kind in ("makam", "form", "usul")}
        self.forms = set(self.lists["form"])
        self.printed = data.get("yazilis", {})

    def canonical(self, kind: str, slug: str) -> str:
        return self.aliases.get(kind, {}).get(slug, slug)

    def spelling(self, kind: str, slug: str, fallback: str) -> str:
        """How the Mus2 headers print a name, for a name OCR read a letter off ("MANUR" -> "Mâhur")."""
        return self.printed.get(kind, {}).get(self.canonical(kind, slug), fallback)

    def checked(self, kind: str, value: str) -> tuple[str, float]:
        """A labelled value against the list: as printed when it is a known name, the list's spelling when it is a
        letter off, as printed (and less sure) when it is not on the list."""
        folded = fold(re.sub(r"\s+[IVX]+$", "", value))
        if folded in self.lists[kind] or not folded:
            return value, 1.0
        slug = self.whole(kind, folded)
        if slug:
            return self.spelling(kind, slug, value), 0.9
        return value, 0.8

    def leading(self, kind: str, folded: str) -> str | None:
        for slug in self.lists[kind]:
            if folded.startswith(slug):
                return slug
        return None

    def leading_near(self, kind: str, words: list[str], longer_than: int = 0) -> tuple[str, int] | None:
        """A name a letter off at the start of the line ("SÜZNÂK", "HOZZAM", "KARCIČAR"): the slug and how many
        words it takes. Names of five letters or more only, so that a short word is not taken for a makam; with
        longer_than, only names longer than that ("ACEM KÜRDÊ" is acemkürdî, not acem)."""
        for n in (3, 2, 1):
            if len(words) < n:
                continue
            head = fold(" ".join(words[:n]))
            for slug in self.lists[kind]:
                if len(slug) >= max(5, longer_than + 1) and abs(len(head) - len(slug)) <= 1 \
                        and distance(head, slug) <= 1:
                    return slug, n
        return None

    def whole(self, kind: str, folded: str) -> str | None:
        """The line is just this name, maybe a letter off: an usul printed alone ("Aksak Semâi", "Düyek"); the name
        itself before one a letter from it ("Curcuna" is not "K. Curcuna")."""
        if folded in self.lists[kind]:
            return folded
        for slug in self.lists[kind]:
            if len(slug) >= 5 and abs(len(folded) - len(slug)) <= 1 and distance(folded, slug) <= 1:
                return slug
        return None

    def split_near(self, word: str) -> tuple[str, str] | None:
        """A makam a letter off run together with a known form ("BÍCAZSARKI": hicaz and şarkı): both slugs."""
        folded = fold(word)
        for slug in self.lists["makam"]:
            if len(slug) < 5:
                continue
            for cut in (len(slug) - 1, len(slug), len(slug) + 1):
                if folded[cut:] in self.forms and distance(folded[:cut], slug) <= 1:
                    return slug, folded[cut:]
        return None

    def anywhere(self, kind: str, folded: str) -> str | None:
        for slug in self.lists[kind]:
            if len(slug) >= 4 and slug in folded:
                return slug
        return None

    def starts_with_form(self, text: str) -> bool:
        """A short line that is a form ("ŞARKI", "SAZ SEMÂİSİ", "BESTE"), as it may stand apart from its makam."""
        words = text.split()
        return 1 <= len(words) <= 3 and bool(self.leading("form", fold(text)) or self.leading_near("form", words))


def _form_of(rest: str, names: "NameLists") -> tuple[str | None, str | None]:
    """The form in what follows the makam: a known form, one a letter off (in its list spelling), or the words as
    printed when they name no known form."""
    if not rest:
        return None, None
    form = names.leading("form", fold(rest))
    if form:
        return form, _cut(rest, form)[0]
    near_form = names.leading_near("form", rest.split())
    if near_form:
        slug, n = near_form
        return slug, names.spelling("form", slug, " ".join(rest.split()[:n]))
    return None, rest


def _cut(text: str, slug: str) -> tuple[str, str]:
    """Split the printed words where their folded form has used up the slug: ("Acemaşîrân", "Şarkı")."""
    words = text.split()
    for n in range(1, len(words) + 1):
        if fold(" ".join(words[:n])) == slug:
            return " ".join(words[:n]), " ".join(words[n:])
    for i in range(1, len(text)):  # OCR ran the words together: "HicazŞarkı", "BUSELIKSARKI"
        # but the possessive ending stays on its word: "PEŞREVİ" is not "PEŞREV" and "İ"
        if fold(text[:i]) == slug and ((text[i].isalpha() and text[i].isupper()) or text[i] == "$") \
                and fold(text[i:]) not in ("i", "si"):
            return text[:i], text[i:]
    return text, ""


_ocr = None
_ocr_lock = threading.Lock()


def _engine():
    global _ocr  # noqa: PLW0603
    with _ocr_lock:
        if _ocr is None:
            from rapidocr import RapidOCR  # noqa: PLC0415

            _ocr = RapidOCR(params={"Global.log_level": "warning"})
    return _ocr


def prepare() -> None:
    """Load the OCR models and the name lists now (a service does it at start-up) rather than in the first read."""
    _engine()
    _names()


def ocr_items(image: np.ndarray) -> list[Item]:
    result = _engine()(image)
    if result.txts is None:
        return []
    items = []
    for box, text, score in zip(result.boxes, result.txts, result.scores, strict=True):
        xs, ys = [float(p[0]) for p in box], [float(p[1]) for p in box]
        items.append(Item(text.strip(), [min(xs), min(ys), max(xs), max(ys)], float(score)))
    return [i for i in items if i.text]


def _rows(items: list[Item]) -> list[list[Item]]:
    """Items grouped into text rows by their vertical centres, top to bottom, each row left to right."""
    rows: list[list[Item]] = []
    for item in sorted(items, key=lambda i: i.centre_y):
        for row in rows:
            centre = sum(i.centre_y for i in row) / len(row)
            if abs(centre - item.centre_y) < 0.5 * max(max(i.height for i in row), item.height):
                row.append(item)
                break
        else:
            rows.append([item])
    rows.sort(key=lambda r: min(i.box[1] for i in r))
    return [sorted(r, key=lambda i: i.box[0]) for r in rows]


def _join_labels(items: list[Item], names: "NameLists | None" = None) -> list[Item]:
    """Pieces OCR read apart on one line are joined: a label and its value ("Beste:" | "Dede Efendi") at any short
    gap, other words of a like size at a word's gap ("Segâh Aranağme" | "(Yürüksemâî)"); boxes may overlap a little
    ("Gazi" | "Ğiray"). A label, a section word ("Aranağme"), a makam and form line or a piece with no letters is
    not joined on."""
    out: list[Item] = []
    for row in _rows(items):
        line: list[Item] = []
        for item in row:
            prev = line[-1] if line else None
            if prev is None:
                line.append(item)
                continue
            gap = item.box[0] - prev.box[2]
            low, high = sorted((prev.height, item.height))
            ending = re.match(r"^(.*?)\s*[:：;·]\s*$", prev.text)
            after_label = bool(ending) and bool(label_field(fold_words(ending.group(1)))[0] or _lone_label(prev.text))
            if after_label:
                join = -0.5 * low <= gap < 4 * prev.height
            else:
                join = (-0.5 * low <= gap < 0.8 * low and high <= 1.43 * low and letters(item.text) > 0
                        and letters(prev.text) > 0 and not _label_of(item.text) and not _lone_label(item.text)
                        and not _person_label(item.text)
                        and fold(item.text) not in SECTION_WORDS and not SECTION.search(item.text)
                        and not (names is not None and names.leading("makam", fold(item.text))
                                 and _form_of(_cut(item.text, names.leading("makam", fold(item.text)))[1],
                                              names)[0]))
            if join:
                line[-1] = _joined(prev, item)
            else:
                line.append(item)
        out += line
    return out


def _merge_makam_form(items: list[Item], names: NameLists) -> list[Item]:
    """A makam printed alone with its form beside it or under it ("HİCAZ" | "ŞARKI", "MÂHUR   BESTE") becomes one
    makam and form line."""
    out = list(items)
    for item in list(out):
        if item not in out:
            continue
        bare = fold(re.sub(r"\([^()]*\)", " ", item.text))
        if not bare or not names.whole("makam", bare):
            continue
        for other in out:
            if other is item or not names.starts_with_form(other.text):
                continue
            h = max(item.height, other.height)
            beside = abs(other.centre_y - item.centre_y) < 0.5 * h and -0.5 * h <= other.box[0] - item.box[2] < 3 * h
            under = 0 <= other.box[1] - item.box[3] < h and abs(other.centre_x - item.centre_x) < max(item.width,
                                                                                                    other.width)
            if beside or under:
                out[out.index(item)] = _joined(item, other)
                out.remove(other)
                break
    return out


def _strip_tempo(text: str) -> str | None:
    """The line without a tempo mark in it; None when nothing else is left (the tempo reader reads the mark)."""
    rest = TEMPO_PART.sub(" ", text).strip()
    if rest != text.strip() or TEMPO.search(text):
        if letters(rest) < 3:
            return None
        return re.sub(r"\s+", " ", rest)
    return text


def _label_of(text: str) -> tuple[str, float, str] | None:
    """(field, sureness, value) when the line opens with a label and a separator."""
    match = LABEL_LINE.match(text)
    if not match:
        return None
    words = fold_words(match.group(1).replace(",", " "))
    name, sure = label_field(words)
    if not name and ":" in text:
        name, sure = label_field(words, letters=2)
    return (name, sure, match.group(2)) if name else None


def _lone_label(text: str) -> str | None:
    """The field a label standing alone on its line names ("BESTEKÂRI", "SÖZ VE MÜZİK"), a letter off for the longer
    ones ("sÖz VE NÜziK")."""
    words = fold_words(text.strip(" ()[]").rstrip(":："))  # "(Beste ve Güfte)"
    if words in LONE_LABELS:
        return LONE_LABELS[words]
    for label, name in LONE_LABELS.items():
        if len(label) >= 6 and distance(words, label) <= 1:
            return name
    return None


def _person_label(text: str) -> tuple[str, str] | None:
    """(field, name) for a composer's or lyricist's label that lost its colon, followed by a name of one to five
    words with no digits: "Beste Ömer Dilek", "Bester ZEkai DEDE"."""
    words = text.split()
    if not 2 <= len(words) <= 6 or re.search(r"\d", text):
        return None
    head = fold(words[0])
    for label, name in PERSON_WORDS.items():
        if head == label or (len(head) >= 5 and distance(head, label) <= 1):
            return name, " ".join(words[1:])
    return None


def _other_label(text: str) -> bool:
    """A collection label standing alone, a letter off for the longer ones ("DERLEVEN" for "DERLEYEN")."""
    words = fold_words(text.rstrip(" :："))
    return any(len(label) >= 6 and distance(words, label) <= 1 for label in OTHER_LABELS)


def _unseparated_usul(text: str, names: NameLists) -> tuple[str, str] | None:
    """An usul label that lost its colon, followed by a known usul: "USÚLU CURCUNA", "uSLÜ DEVRI HINDI"."""
    words = text.split()
    splits = [("".join(words[:n]), " ".join(words[n:])) for n in (1, 2) if len(words) > n]
    joined = re.match(r"^([^\W\d_]{4,6})[-.=]\s*(\S.*)$", text)
    if joined:
        splits.append((joined.group(1), joined.group(2)))
    for head, rest in splits:
        head = fold(head)
        if len(head) >= 4 and min(distance(head, "usul"), distance(head, "usulu")) <= (1 if len(head) == 4 else 2):
            slug = names.whole("usul", fold(rest))
            if slug:
                return rest, slug
    return None


def _value_distance(label: Item, item: Item, names: NameLists) -> float | None:
    """How far the line is from a lone label whose value it may be (under it, or beside it on its right, and of a
    like size); None when it cannot be its value (a makam, form or usul line, a bracketed subtitle, a big title)."""
    h = label.height
    if names.leading("makam", fold(item.text)) or names.starts_with_form(item.text) \
            or names.whole("usul", fold(item.text)) or item.text.strip().startswith("(") or letters(item.text) < 3 \
            or item.height > 1.6 * h:
        return None
    if abs(item.centre_y - label.centre_y) < 0.5 * max(h, item.height) and 0 <= item.box[0] - label.box[2] < 4 * h:
        return (item.box[0] - label.box[2]) / 2
    if -0.3 * h <= item.box[1] - label.box[3] < 2.5 * h and item.box[2] > label.box[0] - 2 * h \
            and item.box[0] < label.box[2] + 2 * h:
        return max(0.0, item.box[1] - label.box[3]) + 0.1 * abs(item.box[0] - label.box[0])
    return None


def _stacked(a: Item, b: Item) -> bool:
    """b sits right under or over a in the same block of lines: close, overlapping, of a like size."""
    h = max(a.height, b.height)
    gap = b.box[1] - a.box[3] if b.centre_y > a.centre_y else a.box[1] - b.box[3]
    return (-0.3 * h <= gap < 0.8 * h and min(a.box[2], b.box[2]) > max(a.box[0], b.box[0])
            and abs(a.centre_x - b.centre_x) < max(a.width, b.width) / 2 and 0.6 <= a.height / max(b.height, 1) <= 1.7)


def parse(items: list[Item], width: float, names: NameLists, offset: tuple[int, int] = (0, 0)) -> Header:
    header = Header()
    free: list[Item] = []
    sources: list[Item] = []
    lone: list[tuple[str, Item]] = []
    people: list[tuple[str, Item]] = []  # labelled composer and lyricist lines, whose names may run on below
    for item in _merge_makam_form(_join_labels(items, names), names):
        text = _strip_tempo(item.text)
        if text is None or LENGTH.search(text) or SECTION.search(text) or fold(text) in SECTION_WORDS:
            continue  # the tempo mark is read by the tempo reader; "1. Hane" belongs to the music
        text = text.lstrip(" .,;:-·•*")
        if letters(text) == 0 or (fold(text).startswith("sure") and letters(text) <= 5):
            continue  # nothing to read, or the piece's length ("Süre: 6'46"")
        item = Item(text, item.box, item.score)
        head = LABEL_LINE.match(text)
        words = text.split()
        if (head and fold_words(head.group(1).replace(",", " ")) in OTHER_LABELS) \
                or any(fold_words(" ".join(words[:n])) in OTHER_LABELS for n in (1, 2, 3)) or _other_label(text):
            if fold_words(text.rstrip(" :：")) in OTHER_LABELS or _other_label(text):  # alone: value under it
                lone.append((OTHER, item))
            continue
        label = _label_of(text)
        if label:
            name, sure, value = label
            if not value.strip():
                if name in LONE_LABELS.values():
                    lone.append((name, item))
                continue
            if name in ("makam", "form", "usul"):
                value, known = names.checked(name, value)
                sure *= known
            header.put(name, value, item, item.score * sure, offset)
            if name in ("bestekar", "gufte", BOTH):
                people.append((name, item))
            continue
        lone_name = _lone_label(text)
        if lone_name:
            lone.append((lone_name, item))
            continue
        person = _person_label(text)
        if person:
            name, value = person
            header.put(name, value, item, item.score * 0.8, offset)
            people.append((name, item))
            continue
        usul = _unseparated_usul(text, names)
        if usul:
            value, slug = usul
            exact = fold(value) == slug
            header.put("usul", value if exact else names.spelling("usul", slug, value), item,
                       item.score * (0.9 if exact else 0.8), offset)
            continue
        if SOURCE.search(text):
            sources.append(item)
            continue
        free.append(item)
    used: set[int] = set()
    # a lone label takes the line under it or beside it, the nearest pairs first
    pairs = sorted((d, n, i) for n, (_, label) in enumerate(lone) for i, value in enumerate(free)
                   if (d := _value_distance(label, value, names)) is not None)
    taken: set[int] = set()
    for _, n, i in pairs:
        if n in taken or id(free[i]) in used:
            continue
        taken.add(n)
        used.add(id(free[i]))
        name, value = lone[n][0], free[i]
        if name == OTHER:
            continue
        header.put(name, value.text, value, value.score * 0.8, offset)
        if name != "yore":
            people.append((name, value))
    # a source line takes the lines stacked with it
    blocks = []
    for source in sources:
        if id(source) in used:
            continue
        block = [source]
        used.add(id(source))
        grown = True
        while grown:
            grown = False
            for other in free + sources:
                # not a catalogue number ("TSM Repertuar Sıra No: 1797"), an usul or a makam line
                if id(other) not in used and any(_stacked(member, other) for member in block) \
                        and not re.search(r"[\d:]", other.text) and not names.whole("usul", fold(other.text)) \
                        and not names.leading("makam", fold(other.text)):
                    block.append(other)
                    used.add(id(other))
                    grown = True
        block.sort(key=lambda i: i.box[1])
        merged = block[0]
        for member in block[1:]:
            merged = _joined(merged, member)
        blocks.append(merged)
    if blocks:  # the publisher's name before a catalogue number ("TSM Repertuar No: 5252")
        source = min(blocks, key=lambda i: (bool(re.search(r"\d", i.text)), i.box[1]))
        header.put("kaynak", source.text, source, source.score, offset)
    # a composer's or lyricist's name may run on to the line under it ("BESTE: HAFIZ ZEKÂİ" / "DEDE EFENDİ")
    for name, person in people:
        for other in free:
            h = person.height
            if (id(other) not in used and -0.3 * h <= other.box[1] - person.box[3] < 0.8 * h
                    and (abs(other.box[0] - person.box[0]) < 2 * h or abs(other.box[2] - person.box[2]) < 2 * h)
                    and 0.7 <= other.height / max(h, 1) <= 1.4 and not re.search(r"[\d:]", other.text)
                    and 1 <= len(other.text.split()) <= 4 and not names.whole("usul", fold(other.text))
                    and other.score >= 0.85 and all(letters(w) >= 2 for w in other.text.split())
                    and not label_field(fold(other.text.split()[0]))[0]):
                used.add(id(other))
                for each in ("bestekar", "gufte") if name == BOTH else (name,):
                    # only onto the field this line gave (a second "Beste:" line is not kept)
                    if each in header.fields and header.boxes[each][1] == round(person.box[1] + offset[1]):
                        header.fields[each] += " " + other.text.strip()
                        box = header.boxes[each]
                        header.boxes[each] = [min(box[0], round(other.box[0] + offset[0])), box[1],
                                              max(box[2], round(other.box[2] + offset[0])),
                                              round(other.box[3] + offset[1])]
                break
    free = [i for i in free if id(i) not in used]
    # the makam and form line: "Acemaşîrân Şarkı", "Eviç Aranağme (Sofyan)"
    candidates = []
    for item in free:
        bare = re.sub(r"\([^()]*\)", " ", item.text).strip()
        words = bare.split()
        makam = names.leading("makam", fold(bare))
        longer = names.leading_near("makam", words, longer_than=len(makam)) if makam else None
        if makam and not longer:
            makam_text, rest = _cut(bare, makam)
            form, form_text = _form_of(rest, names)
            # a known form after the makam is the surest sign; a bare makam word may open a title
            candidates.append((3 if form else 2 if not rest else 1, item, makam_text, form_text, 1.0 if form else 0.7))
        elif longer or names.leading_near("makam", words):
            slug, n = longer or names.leading_near("makam", words)
            form, form_text = _form_of(" ".join(words[n:]), names)
            candidates.append((2 if form else 1, item, names.spelling("makam", slug, " ".join(words[:n])), form_text,
                               0.8 if form else 0.6))
        elif words and names.split_near(words[0]):
            slug, form = names.split_near(words[0])
            form_text = next((words[0][i:] for i in range(len(words[0])) if fold(words[0][i:]) == form), form)
            candidates.append((2, item, names.spelling("makam", slug, words[0]), form_text, 0.7))
        elif len(words) >= 2:
            for n in range(len(words) - 1, 0, -1):  # an unknown makam before a known form: "Geveşt Sazsemâîsi"
                if fold(" ".join(words[n:])) in names.forms:
                    candidates.append((2, item, " ".join(words[:n]), " ".join(words[n:]), 0.7))
                    break
    makam_line = None
    if candidates:
        rank, makam_line, makam_text, form_text, sure = max(candidates, key=lambda c: (c[0], -c[1].box[1]))
        header.put("makam", makam_text, makam_line, makam_line.score * sure, offset)
        if form_text:
            header.put("form", form_text, makam_line, makam_line.score * sure, offset)
        inner = re.search(r"\(([^()]+)\)", makam_line.text)
        if inner and names.anywhere("usul", fold(inner.group(1))):
            header.put("usul", inner.group(1), makam_line, makam_line.score * 0.9, offset)
    # the makam line as the page's heading, when it is centred; lines on its row, right of it, are a composer and
    # not the work's name ("HÜZZAM SAZ SEMAİ   Tatar Gazi …")
    heading = makam_line if makam_line is not None and abs(makam_line.centre_x - width / 2) < width * 0.2 else None
    beside = [i for i in free if i is not heading and i.centre_x > width / 2 and i.height <= 1.1 * heading.height
              and abs(i.centre_y - heading.centre_y) < 0.5 * max(i.height, heading.height)
              and i.box[0] - heading.box[2] > heading.height] if heading is not None else []
    # an usul printed alone on its line, with no label
    if "usul" not in header.fields:
        for item in free:
            if item is makam_line or len(item.text.split()) > 3:
                continue
            bare = re.sub(r"\([^()]*\)?", " ", item.text).strip()
            slug = names.whole("usul", fold(item.text)) or (names.whole("usul", fold(bare)) if letters(bare) else None)
            if slug:
                text = item.text if names.whole("usul", fold(item.text)) else bare
                exact = fold(text) == slug
                header.put("usul", text if exact else names.spelling("usul", slug, text), item,
                           item.score * (0.8 if exact else 0.7), offset)
                break
    # the work's name: the highest of the largest centred lines; a line in brackets ("(Didem yüzüne nazır)") when
    # there is no other; the makam line only when there is neither (an instrumental work is named by its makam and
    # form: "Rast Peşrev"); a number is never a name; under a centred heading, the name stands on its axis or is as
    # large (a composer set right of the axis is not the name)
    centred = [i for i in free if abs(i.centre_x - width / 2) < width * 0.2 and letters(i.text) >= 3
               and letters(i.text) >= sum(c.isdigit() for c in i.text) and i not in beside
               and (heading is None or i is heading or abs(i.centre_x - heading.centre_x) < 0.08 * width
                    or i.height >= 0.85 * heading.height)]
    plain = [i for i in centred if i is not makam_line and not re.fullmatch(r"\s*\(.*\)\s*", i.text)]
    bracketed = [i for i in centred if i is not makam_line and re.fullmatch(r"\s*\(.*\)\s*", i.text)]
    tier = plain or bracketed or [i for i in centred if i is makam_line]
    if tier:
        tallest = max(i.height for i in tier)
        title = min((i for i in tier if i.height >= tallest * 0.85), key=lambda i: i.box[1])
        header.put("eser_adi", title.text, title, title.score * 0.9, offset)
    # a composer printed without a label: a name of two words or more on the right, under the title, or on the
    # makam line's row
    if "bestekar" not in header.fields:
        for item in beside + sorted(free, key=lambda i: i.box[1]):
            words = item.text.split()
            if ((item.centre_x > width * 0.66 or item in beside) and item is not makam_line and 2 <= len(words) <= 5
                    and not re.search(r"\d", item.text) and item.text != header.fields.get("eser_adi")
                    and not names.whole("usul", fold(item.text))):
                header.put("bestekar", item.text, item, item.score * 0.6, offset)
                break
    return header


def read_header(page: np.ndarray, first_staff_top: int, names: NameLists | None = None) -> Header:
    """The title block of a page image (BGR or gray), above its first staff (y in the same image)."""
    bottom = max(int(first_staff_top) - 4, 0)
    if bottom < 20:
        return Header()
    crop = page[:bottom]
    names = names or _names()
    return parse(ocr_items(crop), crop.shape[1], names)


_name_lists: NameLists | None = None


def _names() -> NameLists:
    global _name_lists  # noqa: PLW0603
    if _name_lists is None:
        _name_lists = NameLists()
    return _name_lists
