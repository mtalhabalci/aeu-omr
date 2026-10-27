"""training.duzeltme: Musiki Akademisi correction packages read into training samples, on synthetic packages only.

The model's reading (model.musicxml) is written by homr's own writer from token lines, as the service writes it;
the corrected score is written the way the app writes it (music-core scoreToMusicXML: note ids kept from the
reading, 53-TET <alter>s, the accidentals worked out again from the pitches, a light-heavy barline after the last
measure)."""

import hashlib
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import cv2
import numpy as np

from homr.music_xml_generator import XmlGeneratorArguments, generate_xml
from homr.transformer.vocabulary import EncodedSymbol
from training.duzeltme.etiket import (
    APP_COMMA,
    _articulation,
    Row,
    read_lines,
    round_trip,
    row_texts,
)
from training.duzeltme.paket_oku import (
    Options,
    PackageError,
    StaffResult,
    inserted_for_line,
    load_packages,
    main,
    process_package,
    read_packages,
)
from training.transformer.training_vocabulary import read_token_lines

FOLDER = "duzeltme-11111111-2222-4333-8444-555555555555"
# the app's <accidental> for a drawn sign (value, smufl) and the commas it stands for
APP_SIGNS = {
    "flat1": ("other", "accidentalKomaFlat", -1),
    "sharp4": ("sharp", "accidentalBakiyeSharp", 4),
    "flat5": ("flat", "accidentalKucukMucennebFlat", -5),
    "N": ("natural", "accidentalNatural", 0),
}
QUARTERS = {"whole": 4, "half": 2, "quarter": 1, "eighth": 0.5}


def tokens(text: str) -> list[EncodedSymbol]:
    return read_token_lines([line for line in text.strip().splitlines() if line.strip()])


def model_xml(*staffs: str) -> str:
    """The reading of a page of single staffs, as the service writes it: every staff's tokens and a newline."""
    voice: list[EncodedSymbol] = []
    for staff in staffs:
        voice += tokens(staff) + [EncodedSymbol("newline")]
    return generate_xml(XmlGeneratorArguments(), [voice], "").to_string()


def app_note(note_id: str, pitch: str | None, kind: str, commas: int = 0, sign: str | None = None,
             tie: str | None = None, staff: int | None = None, voice: int = 1, divisions: int = 2) -> str:
    """A <note> as scoreToMusicXML writes it."""
    parts = [f'<note id="{note_id}">']
    if pitch is None:
        parts.append("<rest/>")
    else:
        alter = f"<alter>{commas * 12 / 53:.4f}</alter>" if commas else ""
        parts.append(f"<pitch><step>{pitch[0]}</step>{alter}<octave>{pitch[1:]}</octave></pitch>")
    parts.append(f"<duration>{int(QUARTERS[kind] * divisions)}</duration>")
    if tie:
        parts.append(f'<tie type="{tie}"/>')
    parts.append(f"<voice>{voice}</voice><type>{kind}</type>")
    if sign:
        value, smufl, _ = APP_SIGNS[sign]
        parts.append(f'<accidental smufl="{smufl}">{value}</accidental>')
    if staff is not None:
        parts.append(f"<staff>{staff}</staff>")
    if tie:
        parts.append(f'<notations><tied type="{tie}"/></notations>')
    parts.append("</note>")
    return "".join(parts)


def app_score(parts: list[tuple[str, str, list[str]]], groups: str = "") -> str:
    """score-partwise of (id, name, measures)."""
    part_list = "".join(f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>' for pid, name, _ in parts)
    if groups:
        part_list = groups.format(*[f'<score-part id="{pid}"><part-name>{name}</part-name></score-part>'
                                    for pid, name, _ in parts])
    body = "".join(f'<part id="{pid}">{"".join(measures)}</part>' for pid, _, measures in parts)
    return ('<?xml version="1.0" encoding="UTF-8" standalone="no"?>\n<score-partwise version="4.0"><identification>'
            '<encoding><software>Musiki Akademisi nota düzeltme</software></encoding></identification>'
            f"<part-list>{part_list}</part-list>{body}</score-partwise>\n")


def page_png(boxes: list[list[int]], width: int = 1920, height: int = 1300) -> bytes:
    """A white page with five staff lines in every box."""
    page = np.full((height, width, 3), 255, np.uint8)
    for x0, y0, x1, y1 in boxes:
        for k in range(5):
            y = round(y0 + k * (y1 - y0) / 4)
            cv2.line(page, (x0, y), (x1, y), (0, 0, 0), 2)
        cv2.ellipse(page, ((x0 + x1) // 2, (y0 + y1) // 2), (11, 8), -20, 0, 360, (0, 0, 0), -1)
    ok, data = cv2.imencode(".png", page)
    assert ok
    return data.tobytes()


def write_package(root: Path, files: dict[str, object], several: dict | None = None, image: bytes | None = None,
                  form: str = "musiki-akademisi-duzeltme/1", folder_name: str = FOLDER, version: int = 1,
                  upload: str | None = None, app_version: str | None = None) -> Path:
    folder = root / folder_name
    folder.mkdir(parents=True)
    for name, content in files.items():
        data = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        (folder / name).write_text(data, encoding="utf-8")
    original = {"dosya": None, "mime": "image/png", "eksik": True}
    if image is not None:
        (folder / "orijinal.png").write_bytes(image)
        original = {"dosya": "orijinal.png", "mime": "image/png", "boyut": len(image),
                    "sha256": hashlib.sha256(image).hexdigest(), "sha256Dogrulandi": True}
    manifest = {"bicim": form, "anonimKimlik": FOLDER[9:], "rol": "ogrenci", "modelVersion": "v-test",
                "tur": "basili", "surum": version, "tarih": "2026-10-27", "orijinal": original,
                "porteKaynagi": "servis", "ozet": {}, "dosyalar": sorted(files)}
    if several:
        manifest["cokParti"] = several
    if upload:
        manifest["anonimYukleme"] = upload
    if app_version:
        manifest["uygulamaSurumu"] = app_version
    (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (folder / "tempolar.json").write_text('{"kaynak": "musicxml", "kayitlar": []}', encoding="utf-8")
    if "islemler.json" not in files:
        (folder / "islemler.json").write_text("[]", encoding="utf-8")
    return folder


# --- a single-part page: three staffs, the third empty ------------------------------------------------------------

READ_1 = """
clef_G2 _ _ _ upper
keyAccidental B4 flat1 _ upper
timeSignature_4/4 . . . .
note_4 A4 _ _ upper
note_4 B4 _ _ upper
note_4 C5 sharp4 _ upper
note_4 C5 _ _ upper
barline . . . .
note_2 D5 _ slurStart upper
note_2 C5 N slurStop upper
barline . . . .
"""
READ_2 = """
clef_G2 _ _ _ upper
keyAccidental B4 flat1 _ upper
note_8 B4 N _ upper
note_8 A4 _ _ upper
note_4 G4 _ _ upper
note_2 A4 _ tieStart upper
dashedbarline . . . .
note_1 A4 _ tieStop upper
barline . . . .
"""
SINGLE_BOXES = [[100, 300, 1800, 380], [100, 600, 1800, 680], [100, 900, 1800, 980]]
KEY = ('<key><key-step>B</key-step><key-alter>-0.2264</key-alter>'
       '<key-accidental smufl="accidentalKomaFlat">other</key-accidental></key>')


def single_corrected(second_c5_sharp_unsigned: bool = False) -> str:
    """The user approved measures 1 and 2 and changed the G4 of measure 3 to F4."""
    first = ('<measure number="1"><attributes><divisions>2</divisions>' + KEY +
             '<time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef>'
             '</attributes><direction placement="above"><direction-type><metronome print-object="no">'
             '<beat-unit>quarter</beat-unit><per-minute>120</per-minute></metronome></direction-type>'
             '<sound tempo="120"/></direction>'
             + app_note("m1n1", "A4", "quarter") + app_note("m1n2", "B4", "quarter", -1)
             + app_note("m1n3", "C5", "quarter", 4, "sharp4") + app_note("m1n4", "C5", "quarter", 4)
             + "</measure>")
    c5 = app_note("m2n2", "C5", "half", 4) if second_c5_sharp_unsigned else app_note("m2n2", "C5", "half")
    second = '<measure number="2">' + app_note("m2n1", "D5", "half") + c5 + "</measure>"
    third = ('<measure number="3">' + app_note("m3n1", "B4", "eighth", 0, "N") + app_note("m3n2", "A4", "eighth")
             + app_note("m3n3", "F4", "quarter") + app_note("m3n4", "A4", "half", tie="start") + "</measure>")
    fourth = ('<measure number="4">' + app_note("m4n1", "A4", "whole", tie="stop")
              + '<barline location="right"><bar-style>light-heavy</bar-style></barline></measure>')
    return app_score([("P1", "Ses", [first, second, third, fourth])])


def single_records(fourth: str = "onaylandi", third_kinds: tuple = ("perde",)) -> dict:
    return {"olcular": [
        {"olcu": 1, "durum": "onaylandi", "turler": [], "duzeltilmis": [1], "porte": 1},
        {"olcu": 2, "durum": "onaylandi", "turler": [], "duzeltilmis": [2], "porte": 1},
        {"olcu": 3, "durum": "duzeltildi", "turler": list(third_kinds), "duzeltilmis": [3], "porte": 2},
        {"olcu": 4, "durum": fourth, "turler": [], "duzeltilmis": [4], "porte": 2},
    ], "eklenenOlcular": []}


def single_package(root: Path, image: bool = True, folder_name: str = FOLDER, version: int = 1,
                   read: tuple[str, str] = (READ_1, READ_2), corrected: str | None = None, records: dict | None = None,
                   operations: list | None = None, upload: str | None = None, page: bytes | None = None,
                   **kwargs) -> Path:
    corrected = corrected or single_corrected(kwargs.pop("second_c5_sharp_unsigned", False))
    staffs = [
        {"porte": 1, "sayfa": 1, "kutu": SINGLE_BOXES[0], "olcuBas": 1, "olcuSon": 2},
        {"porte": 2, "sayfa": 1, "kutu": SINGLE_BOXES[1], "olcuBas": 3, "olcuSon": 4},
        {"porte": 3, "sayfa": 1, "kutu": SINGLE_BOXES[2], "olcuBas": None, "olcuSon": None},
    ]
    files = {
        "model.musicxml": model_xml(*read, ""),
        "duzeltilmis.musicxml": corrected,
        "porteler.json": {"kaynak": "servis", "porteler": staffs,
                          "sayfaResimleri": [{"sayfa": 1, "genislik": 1920, "yukseklik": 1300, "dpi": None,
                                              "kaynak": "fotograf"}]},
        "olcular.json": records or single_records(**kwargs),
    }
    if operations is not None:
        files["islemler.json"] = operations
    image_bytes = (page or page_png(SINGLE_BOXES)) if image else None
    return write_package(root, files, image=image_bytes, folder_name=folder_name, version=version, upload=upload)


# --- a multi-part page: voice + piano, two systems; the piano read by the base model ------------------------------

MULTI_BOXES = [[100, 100, 1800, 160], [100, 260, 1800, 320], [100, 400, 1800, 460],
               [100, 700, 1800, 760], [100, 860, 1800, 920], [100, 1000, 1800, 1060]]
GROUPS = ('{0}<part-group type="start" number="1"><group-symbol>brace</group-symbol></part-group>{1}'
          '<part-group type="stop" number="1"/>')


def multi_model() -> str:
    """As the service's multi-part writer lays it out (homr.score_parts): the piano one part of two staves."""
    voice = ['<measure number="1"><attributes><divisions>2</divisions><key><fifths>0</fifths></key><time><beats>2'
             '</beats><beat-type>4</beat-type></time><clef number="1"><sign>G</sign><line>2</line></clef>'
             '</attributes><note><pitch><step>A</step><octave>4</octave></pitch><duration>2</duration><voice>1'
             '</voice><type>quarter</type><staff>1</staff></note><note><pitch><step>B</step><alter>-0.222</alter>'
             '<octave>4</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type>'
             '<accidental smufl="accidentalKomaFlat">quarter-flat</accidental><staff>1</staff></note></measure>',
             '<measure number="2"><print new-system="yes"/><attributes><clef number="1"><sign>G</sign><line>2'
             '</line></clef></attributes><note><pitch><step>A</step><octave>4</octave></pitch><duration>4'
             '</duration><voice>1</voice><type>half</type><staff>1</staff></note></measure>']
    piano = ['<measure number="1"><attributes><divisions>2</divisions><key><fifths>0</fifths></key><time><beats>2'
             '</beats><beat-type>4</beat-type></time><staves>2</staves><clef number="1"><sign>G</sign><line>2'
             '</line></clef><clef number="2"><sign>F</sign><line>4</line></clef></attributes>'
             '<note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration><voice>1</voice>'
             '<type>eighth</type><staff>1</staff></note><note><pitch><step>D</step><octave>5</octave></pitch>'
             '<duration>1</duration><voice>1</voice><type>eighth</type><staff>1</staff></note><note><pitch><step>E'
             '</step><octave>5</octave></pitch><duration>2</duration><voice>1</voice><type>quarter</type><staff>1'
             '</staff></note><backup><duration>4</duration></backup><note><pitch><step>A</step><octave>3</octave>'
             '</pitch><duration>4</duration><voice>5</voice><type>half</type><staff>2</staff></note></measure>',
             '<measure number="2"><print new-system="yes"/><attributes><key number="2"><fifths>-1</fifths></key>'
             '<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line>'
             '</clef></attributes><note><pitch><step>D</step><octave>5</octave></pitch><duration>4</duration>'
             '<voice>1</voice><type>half</type><staff>1</staff></note><backup><duration>4</duration></backup>'
             '<note><pitch><step>D</step><octave>3</octave></pitch><duration>2</duration><voice>5</voice><type>'
             'quarter</type><staff>2</staff></note><note><pitch><step>B</step><alter>-1</alter><octave>2</octave>'
             '</pitch><duration>2</duration><voice>5</voice><type>quarter</type><staff>2</staff></note>'
             '</measure>']
    return app_score([("P1", "Voice", voice), ("P2", "Piano", piano)], GROUPS)


def multi_corrected() -> str:
    """The piano's right hand: C5 of measure 1 changed to B4; the voice: A4 of measure 2 changed to E4."""
    voice = ['<measure number="1"><attributes><divisions>1</divisions><key><fifths>0</fifths></key><time><beats>2'
             '</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>'
             + app_note("p1m1n1", "A4", "quarter", divisions=1)
             + app_note("p1m1n2", "B4", "quarter", -1, "flat1", divisions=1) + "</measure>",
             '<measure number="2">' + app_note("p1m2n1", "E4", "half", divisions=1)
             + '<barline location="right"><bar-style>light-heavy</bar-style></barline></measure>']
    piano = ['<measure number="1"><attributes><divisions>2</divisions><key><fifths>0</fifths></key><time><beats>2'
             '</beats><beat-type>4</beat-type></time><staves>2</staves><part-symbol>brace</part-symbol>'
             '<clef number="1"><sign>G</sign><line>2</line></clef><clef number="2"><sign>F</sign><line>4</line>'
             '</clef></attributes>' + app_note("p2m1n1", "B4", "eighth", staff=1)
             + app_note("p2m1n2", "D5", "eighth", staff=1) + app_note("p2m1n3", "E5", "quarter", staff=1)
             + "<backup><duration>4</duration></backup>" + app_note("p3m1n1", "A3", "half", staff=2, voice=5)
             + "</measure>",
             '<measure number="2"><attributes><key number="2"><fifths>-1</fifths></key></attributes>'
             + app_note("p2m2n1", "D5", "half", staff=1) + "<backup><duration>4</duration></backup>"
             + app_note("p3m2n1", "D3", "quarter", staff=2, voice=5)
             + app_note("p3m2n2", "B2", "quarter", -5, staff=2, voice=5)
             + '<barline location="right"><bar-style>light-heavy</bar-style></barline></measure>']
    return app_score([("P1", "Ses", voice), ("P2", "Piyano", piano)], GROUPS)


def multi_package(root: Path, left_hand_first: str = "bakilmadi", cut_down: tuple[int, ...] | None = None,
                  app_version: str | None = None) -> Path:
    """cut_down: the staffs the service marked ustSesKirpildi (None: an answer from before the field existed).
    app_version: the manifest's uygulamaSurumu (None: an app from before the field)."""
    places = [(1, 0, 1, "v24"), (1, 1, 1, "temel"), (1, 1, 2, "temel"), (2, 0, 1, "v24"), (2, 1, 1, "temel"),
              (2, 1, 2, "temel")]
    staffs = []
    for number, ((system, part, staff, by), box) in enumerate(zip(places, MULTI_BOXES, strict=True), 1):
        entry = {"porte": number, "sayfa": 1, "kutu": box, "olcuBas": system, "olcuSon": system, "sistem": system,
                 "parti": part, "partiPortesi": staff, "okuyan": by}
        if by == "temel":
            entry["aeuDenetlenmeli"] = True
        if cut_down is not None:
            entry["ustSesKirpildi"] = number in cut_down
        staffs.append(entry)
    states = [("bakilmadi", []), ("duzeltildi", ["perde"]), (left_hand_first, []), ("duzeltildi", ["perde"]),
              ("onaylandi", []), ("onaylandi", [])]
    records = []
    for entry, (state, kinds) in zip(staffs, states, strict=True):
        record = {"olcu": entry["olcuBas"], "durum": state, "turler": kinds, "duzeltilmis": [entry["olcuBas"]],
                  "porte": entry["porte"], "sistem": entry["sistem"], "parti": entry["parti"],
                  "partiPortesi": entry["partiPortesi"]}
        if entry.get("aeuDenetlenmeli"):
            record["aeuDenetlenmeli"] = True
        records.append(record)
    files = {
        "model.musicxml": multi_model(),
        "duzeltilmis.musicxml": "<score-partwise/>",  # the app's own layout: not what this reader reads here
        "duzeltilmis-servis-duzeni.musicxml": multi_corrected(),
        "porteler.json": {"kaynak": "servis", "porteler": staffs, "sayfaResimleri": None},
        "olcular.json": {"olcular": records, "eklenenOlcular": []},
    }
    several = {"olcuKaydi": "porte", "partiPorteSayilari": [1, 2], "servisDuzeni": "duzeltilmis-servis-duzeni.musicxml"}
    return write_package(root, files, several, image=page_png(MULTI_BOXES), app_version=app_version)


def by_staff(result) -> dict:  # noqa: ANN001
    return {s.entry["porte"]: s for s in result.staffs}


def reasons(staff) -> set[str]:  # noqa: ANN001
    return {r["neden"] for r in staff.reasons}


class SinglePart(unittest.TestCase):
    def test_checked_staff_is_taken_with_page_signs_from_the_reading(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp))))
            staffs = by_staff(process_package(package, Options()))
        self.assertTrue(staffs[1].accepted, staffs[1].reasons)
        self.assertEqual(row_texts(staffs[1].rows), [
            "clef_G2 _ _ _ upper",
            "keyAccidental B4 flat1 _ upper",
            "timeSignature_4/4 . . . .",
            "note_4 A4 _ _ upper",
            "note_4 B4 _ _ upper",
            "note_4 C5 sharp4 _ upper",
            "note_4 C5 _ _ upper",
            "barline . . . .",
            # the slur and the courtesy natural are the reading's: the app's file has neither
            "note_2 D5 _ ?slurStart upper",
            "note_2 C5 ?N ?slurStop upper",
            "barline . . . .",
        ])
        self.assertTrue(staffs[2].accepted, staffs[2].reasons)
        self.assertEqual(row_texts(staffs[2].rows), [
            "clef_G2 _ _ _ upper",
            "keyAccidental B4 flat1 _ upper",
            "note_8 B4 N _ upper",
            "note_8 A4 _ _ upper",
            "note_4 F4 _ _ upper",  # the user's correction
            "note_2 A4 _ tieStart upper",
            "?dashedbarline . . . .",  # the reading's style; the app draws every barline plain
            "note_1 A4 _ tieStop upper",
            "barline . . . .",  # not the app's light-heavy: the reading saw a plain barline
        ])
        self.assertEqual(staffs[1].round_trip, "tamam")
        self.assertEqual(staffs[2].round_trip, "tamam")
        self.assertEqual(reasons(staffs[3]), {"olcu-yok"})
        image = staffs[1].image
        self.assertEqual(image.shape, (256, 1280))
        self.assertLess(int(image[100:160, 200:1000].min()), 100)  # the staff lines are on it

    def test_one_unchecked_measure_leaves_the_staff_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp), fourth="bakilmadi")))
            staffs = by_staff(process_package(package, Options()))
        self.assertTrue(staffs[1].accepted)
        self.assertFalse(staffs[2].accepted)
        self.assertEqual(staffs[2].reasons, [{"neden": "bakilmadi", "ayrinti": "ölçü 4"}])

    def test_masking_keeps_the_staff_with_the_unchecked_measure_unverified(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp), fourth="bakilmadi")))
            staffs = by_staff(process_package(package, Options(mask_measures=True)))
        self.assertTrue(staffs[2].accepted, staffs[2].reasons)
        self.assertEqual(staffs[2].masked, [4])
        self.assertEqual(row_texts(staffs[2].rows)[-2:], ["?note_1 ?A4 ?_ ?tieStop upper", "?barline . . . ."])
        # the training reads them as fields to skip
        symbols = read_token_lines(row_texts(staffs[2].rows))
        self.assertEqual(symbols[-1].unverified, {"rhythm"})
        self.assertEqual(symbols[-2].unverified, {"rhythm", "pitch", "lift", "articulation"})

    def test_structural_edit_is_not_a_check_of_the_notes_with_notes_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp), third_kinds=("isaret",))))
            plain = by_staff(process_package(package, Options()))
            strict = by_staff(process_package(package, Options(notes_only=True)))
        self.assertTrue(plain[2].accepted)
        self.assertEqual(reasons(strict[2]), {"yalniz-yapisal"})

    def test_staff_whose_tokens_do_not_say_the_corrected_score_is_left_out(self) -> None:
        # a sharp the file sounds but does not draw: the tokens cannot carry it
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp), second_c5_sharp_unsigned=True)))
            staffs = by_staff(process_package(package, Options()))
        self.assertEqual(reasons(staffs[1]), {"gidis-donus"})
        self.assertIn("ölçü 2: olay 2: C5+4 half yerine C5 half", staffs[1].round_trip)
        self.assertTrue(staffs[2].accepted)

    def test_without_the_page_no_sample(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(single_package(Path(tmp), image=False)))
            staffs = by_staff(process_package(package, Options()))
        self.assertEqual(reasons(staffs[1]), {"resim-yok"})
        self.assertEqual(staffs[1].round_trip, "tamam")

    def test_dataset_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            single_package(root / "paket", fourth="bakilmadi")
            out = root / "veri"
            self.assertEqual(main([str(root / "paket"), "--cikti", str(out)]), 0)
            index = (out / "index_train.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(index), 1)
            png, token_file = index[0].split(",")
            self.assertTrue(png.endswith(f"train/{FOLDER}__porte001.png"))
            self.assertTrue((out / "train" / f"{FOLDER}__porte001.png").is_file())
            self.assertEqual(Path(out / "train" / f"{FOLDER}__porte001.tokens").read_text(encoding="utf-8")
                             .splitlines()[1], "keyAccidental B4 flat1 _ upper")
            self.assertTrue(token_file.endswith(".tokens"))
            report = json.loads((out / "rapor.json").read_text(encoding="utf-8"))
            self.assertEqual(report["ozet"]["kabul"], 1)
            self.assertEqual(report["ozet"]["nedenler"], {"bakilmadi": 1, "olcu-yok": 1})
            staff = report["paketler"][0]["porteler"][1]
            self.assertEqual((staff["porte"], staff["kabul"], staff["durumlar"]),
                             (2, False, {"3": "duzeltildi", "4": "bakilmadi"}))

    def test_zip_reads_as_the_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = single_package(Path(tmp) / "paket")
            archive = Path(tmp) / f"{FOLDER}.zip"
            with zipfile.ZipFile(archive, "w") as z:
                for file in folder.iterdir():
                    z.write(file, f"{FOLDER}/{file.name}")
            [result] = read_packages([str(archive)], Options())
        self.assertEqual(result.name, FOLDER)
        self.assertEqual([s.accepted for s in result.staffs], [True, True, False])

    def test_pdf_page_is_rendered_as_the_service_renders_it(self) -> None:
        import fitz

        document = fitz.open()
        page = document.new_page(width=480, height=325)  # 1920 wide when rendered: four pixels a point
        for x0, y0, x1, y1 in SINGLE_BOXES:
            for k in range(5):
                y = (y0 + k * (y1 - y0) / 4) / 4
                page.draw_line((x0 / 4, y), (x1 / 4, y), width=0.5)
        pdf = document.tobytes()
        with tempfile.TemporaryDirectory() as tmp:
            folder = single_package(Path(tmp), image=False)
            (folder / "orijinal.pdf").write_bytes(pdf)
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            manifest["orijinal"] = {"dosya": "orijinal.pdf", "mime": "application/pdf",
                                    "sha256": hashlib.sha256(pdf).hexdigest()}
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            [package] = load_packages(str(folder))
            staffs = by_staff(process_package(package, Options()))
            self.assertTrue(staffs[1].accepted, staffs[1].reasons)
            self.assertLess(int(staffs[1].image[100:160, 200:1000].min()), 150)
            # a page of another size than the service read is not cut
            doc = json.loads((folder / "porteler.json").read_text(encoding="utf-8"))
            doc["sayfaResimleri"][0]["yukseklik"] = 1400
            (folder / "porteler.json").write_text(json.dumps(doc), encoding="utf-8")
            [package] = load_packages(str(folder))
            self.assertEqual(reasons(by_staff(process_package(package, Options()))[1]), {"resim-yok"})

    def test_of_two_corrections_of_one_file_the_newer_is_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            single_package(Path(tmp), folder_name="duzeltme-eski", version=1)
            single_package(Path(tmp), folder_name="duzeltme-yeni", version=2)
            old, new = read_packages([tmp], Options())
        self.assertEqual((old.name, new.name), ("duzeltme-eski", "duzeltme-yeni"))
        self.assertEqual({r["neden"] for s in old.staffs for r in s.reasons}, {"yinelenen", "olcu-yok"})
        self.assertTrue(new.staffs[0].accepted)

    def test_unknown_format_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = single_package(Path(tmp))
            manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
            manifest["bicim"] = "musiki-akademisi-duzeltme/2"
            (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            [package] = load_packages(str(folder))
            with self.assertRaisesRegex(PackageError, "bilinmeyen paket biçimi 'musiki-akademisi-duzeltme/2'"):
                process_package(package, Options())
            # in an export of several, the others are still read; the refused one is in the report
            single_package(Path(tmp), folder_name="duzeltme-iyi")
            self.assertEqual(main([tmp, "--cikti", str(Path(tmp) / "veri")]), 2)
            report = json.loads((Path(tmp) / "veri" / "rapor.json").read_text(encoding="utf-8"))
            self.assertEqual([p["klasor"] for p in report["paketler"]], ["duzeltme-iyi"])
            self.assertEqual(len(report["reddedilenPaketler"]), 1)
            self.assertIn("musiki-akademisi-duzeltme/2", report["reddedilenPaketler"][0])


class MultiPart(unittest.TestCase):
    def test_staffs_by_their_own_measures(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(multi_package(Path(tmp), app_version="5e1c0d2")))
            staffs = by_staff(process_package(package, Options()))
        self.assertEqual(reasons(staffs[1]), {"bakilmadi"})  # the voice, system 1
        self.assertEqual(reasons(staffs[3]), {"bakilmadi", "aeu-denetlenmedi"})  # the left hand, system 1
        # the piano of system 2 was approved on the part the user chose
        self.assertEqual([n for n, s in staffs.items() if s.accepted], [2, 4, 5, 6])
        self.assertEqual(row_texts(staffs[2].rows), [
            "clef_G2 _ _ _ upper",
            "timeSignature_2/4 . . . .",
            "note_8 B4 _ _ upper",
            "note_8 D5 _ _ upper",
            "note_4 E5 _ _ upper",
            "barline . . . .",
        ])
        self.assertEqual(row_texts(staffs[6].rows), [
            "clef_F4 _ _ _ upper",
            "keyAccidental B2 flat5 _ upper",  # the bass staff's flat, where a bass staff draws it
            "note_4 D3 _ _ upper",
            "note_4 B2 _ _ upper",
            "barline . . . .",
        ])
        self.assertEqual(row_texts(staffs[4].rows), ["clef_G2 _ _ _ upper", "note_2 E4 _ _ upper",
                                                     "barline . . . ."])
        self.assertTrue(all(s.round_trip == "tamam" for s in staffs.values()))
        self.assertTrue(all("temel model" in " ".join(staffs[n].warnings) for n in (2, 5, 6)))

    def test_base_model_staff_is_not_masked_into_the_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(multi_package(Path(tmp))))
            staffs = by_staff(process_package(package, Options(mask_measures=True)))
        self.assertEqual(reasons(staffs[3]), {"aeu-denetlenmedi"})
        # a staff nobody looked at is not taken masked either
        self.assertEqual(reasons(staffs[1]), {"hic-bakilmamis"})

    def test_staff_cut_down_to_its_top_line_is_left_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(multi_package(Path(tmp), cut_down=(5,))))
            staffs = by_staff(process_package(package, Options(approval_enough=True)))
        self.assertEqual(reasons(staffs[5]), {"ust-ses-kirpildi"})
        self.assertEqual([n for n, s in staffs.items() if s.accepted], [2, 4, 6])
        # the service said which staffs it cut down: no guessing warning on the others
        self.assertFalse(any("temel model" in " ".join(staffs[n].warnings) for n in (2, 6)))

    def test_checked_base_model_staff_is_taken(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(multi_package(Path(tmp), left_hand_first="onaylandi")))
            staffs = by_staff(process_package(package, Options(approval_enough=True)))
        self.assertTrue(staffs[3].accepted, staffs[3].reasons)
        self.assertEqual(row_texts(staffs[3].rows), ["clef_F4 _ _ _ upper", "timeSignature_2/4 . . . .",
                                                     "note_2 A3 _ _ upper", "barline . . . ."])


class ApprovalOfEveryPart(unittest.TestCase):
    @staticmethod
    def staffs_of(folder: Path, options: Options) -> dict:
        [package] = load_packages(str(folder))
        return by_staff(process_package(package, options))

    @staticmethod
    def structural_edit_on_staff_5(folder: Path) -> None:
        doc = json.loads((folder / "olcular.json").read_text(encoding="utf-8"))
        doc["olcular"][4].update({"durum": "duzeltildi", "turler": ["isaret"]})
        (folder / "olcular.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_approval_counts_where_the_app_names_itself(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old = multi_package(Path(tmp) / "eski")
            new = multi_package(Path(tmp) / "yeni", app_version="5e1c0d2")
            before = self.staffs_of(old, Options())
            enough = self.staffs_of(old, Options(approval_enough=True))
            named = self.staffs_of(new, Options())
            # a structural edit was put on every part as well: no check of this staff in the old package
            self.structural_edit_on_staff_5(old)
            self.structural_edit_on_staff_5(new)
            structural_before, structural_named = self.staffs_of(old, Options()), self.staffs_of(new, Options())
            out = Path(tmp) / "veri"
            self.assertEqual(main([str(old), "--cikti", str(out)]), 0)
            report = json.loads((out / "rapor.json").read_text(encoding="utf-8"))["paketler"][0]
            out = Path(tmp) / "veri-yeter"
            self.assertEqual(main([str(old), "--cikti", str(out), "--onay-yeter"]), 0)
            report_enough = json.loads((out / "rapor.json").read_text(encoding="utf-8"))
        self.assertEqual([n for n, s in before.items() if s.accepted], [2, 4])  # pitches corrected on them
        self.assertEqual([n for n, s in before.items() if "onay-butun-partilere" in reasons(s)], [5, 6])
        self.assertEqual([n for n, s in enough.items() if s.accepted], [2, 4, 5, 6])
        self.assertEqual([n for n, s in named.items() if s.accepted], [2, 4, 5, 6])
        self.assertEqual(reasons(structural_before[5]), {"yalniz-yapisal", "aeu-denetlenmedi"})
        self.assertTrue(structural_named[5].accepted, structural_named[5].reasons)
        self.assertIsNone(report["uygulamaSurumu"])
        self.assertTrue(report["onayButunPartilere"])
        self.assertTrue(report_enough["ayarlar"]["onayYeter"])
        self.assertFalse(report_enough["paketler"][0]["onayButunPartilere"])
        self.assertEqual([s["porte"] for s in report_enough["paketler"][0]["porteler"] if s["kabul"]], [2, 4, 5, 6])

    def test_single_part_approval_is_that_parts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            staffs = self.staffs_of(single_package(Path(tmp)), Options())
        self.assertTrue(staffs[1].accepted, staffs[1].reasons)  # measures 1 and 2 only approved


class WriterDefaults(unittest.TestCase):
    def test_final_barline_of_the_writer_gives_way_to_the_readings(self) -> None:
        bold = READ_2.replace("note_1 A4 _ tieStop upper\nbarline", "note_1 A4 _ tieStop upper\nbolddoublebarline")
        self.assertNotEqual(bold, READ_2)
        with tempfile.TemporaryDirectory() as tmp:
            [plain] = read_packages([str(single_package(Path(tmp) / "a"))], Options())
            [heavy] = read_packages([str(single_package(Path(tmp) / "b", read=(READ_1, bold)))], Options())
        self.assertEqual(plain.defaults, ["son ölçü çizgisi (ölçü 4, ince-kalın)"])
        self.assertEqual(row_texts(by_staff(plain)[2].rows)[-1], "barline . . . .")
        self.assertEqual(heavy.defaults, ["son ölçü çizgisi (ölçü 4, ince-kalın)"])
        self.assertEqual(row_texts(by_staff(heavy)[2].rows)[-1], "?bolddoublebarline . . . .")

    def test_last_measure_merged_by_the_user_still_closes_with_the_readings_barline(self) -> None:
        bold = READ_2.replace("note_1 A4 _ tieStop upper\nbarline", "note_1 A4 _ tieStop upper\nbolddoublebarline")
        corrected = single_corrected()
        start, end = corrected.index('</measure><measure number="4">'), corrected.index('<barline location="right">')
        corrected = corrected[:start] + corrected[start + len('</measure><measure number="4">'):end] \
            + corrected[end:]
        records = single_records()
        records["olcular"][2].update({"turler": ["olcu-cizgisi"], "duzeltilmis": [3]})
        records["olcular"][3].update({"durum": "duzeltildi", "turler": ["olcu-cizgisi"], "duzeltilmis": [3]})
        with tempfile.TemporaryDirectory() as tmp:
            [result] = read_packages([str(single_package(Path(tmp), read=(READ_1, bold), corrected=corrected,
                                                         records=records))], Options())
        staff = by_staff(result)[2]
        self.assertTrue(staff.accepted, staff.reasons)
        self.assertEqual(row_texts(staff.rows)[-3:], ["note_2 A4 _ tieStart upper", "note_1 A4 _ tieStop upper",
                                                      "?bolddoublebarline . . . ."])

    def test_first_time_signature_of_the_writer_is_left_out_unless_the_user_set_it(self) -> None:
        unmetered = READ_1.replace("timeSignature_4/4 . . . .\n", "")
        self.assertNotEqual(unmetered, READ_1)
        meter = [{"tur": "olcu-isareti", "olcu": 1, "once": "4/4", "sonra": "4/4"}]
        elsewhere = [{"tur": "olcu-isareti", "olcu": 3, "once": "4/4", "sonra": "4/4"}]
        with tempfile.TemporaryDirectory() as tmp:
            [default] = read_packages([str(single_package(Path(tmp) / "a", read=(unmetered, READ_2)))], Options())
            [user] = read_packages([str(single_package(Path(tmp) / "b", read=(unmetered, READ_2),
                                                       operations=meter))], Options())
            [other] = read_packages([str(single_package(Path(tmp) / "c", read=(unmetered, READ_2),
                                                        operations=elsewhere))], Options())
        self.assertIn("1. ölçünün ölçü işareti (4/4)", default.defaults)
        self.assertNotIn("timeSignature_4/4 . . . .", row_texts(by_staff(default)[1].rows))
        self.assertEqual(by_staff(default)[1].round_trip, "tamam")
        self.assertNotIn("1. ölçünün ölçü işareti (4/4)", user.defaults)
        self.assertEqual(row_texts(by_staff(user)[1].rows)[2], "timeSignature_4/4 . . . .")
        self.assertIn("1. ölçünün ölçü işareti (4/4)", other.defaults)  # an operation on another measure


class Uploads(unittest.TestCase):
    def test_one_upload_by_its_stable_id_else_by_its_file(self) -> None:
        other_page = page_png([*SINGLE_BOXES, [100, 1150, 1800, 1230]])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # two versions of one upload: the file is the same upload's, whatever its bytes
            single_package(root / "a", folder_name="duzeltme-v1", version=1, upload="Y1")
            single_package(root / "a", folder_name="duzeltme-v2", version=2, upload="Y1", page=other_page)
            # one file uploaded twice: two uploads, both taken
            single_package(root / "b", folder_name="duzeltme-x", upload="Y2")
            single_package(root / "b", folder_name="duzeltme-z", upload="Y3")
            # an export from before the field joins the upload that has its file
            single_package(root / "c", folder_name="duzeltme-eski", version=1)
            single_package(root / "c", folder_name="duzeltme-yeni", version=2, upload="Y4")
            versions = {r.name: r for r in read_packages([str(root / "a")], Options())}
            twice = {r.name: r for r in read_packages([str(root / "b")], Options())}
            mixed = {r.name: r for r in read_packages([str(root / "c")], Options())}
        self.assertIn("yinelenen", reasons(versions["duzeltme-v1"].staffs[0]))
        self.assertTrue(versions["duzeltme-v2"].staffs[0].accepted)
        self.assertTrue(twice["duzeltme-x"].staffs[0].accepted and twice["duzeltme-z"].staffs[0].accepted)
        self.assertIn("yinelenen", reasons(mixed["duzeltme-eski"].staffs[0]))
        self.assertTrue(mixed["duzeltme-yeni"].staffs[0].accepted)


def inserted_package(root: Path, after: int, porte: int | None) -> Path:
    """The user added a measure after model measure `after`; the app's record names the staff when porte (the app
    gives the staff of the measure before it)."""
    corrected = single_corrected()
    for number in (4, 3, 2):
        if number > after:
            corrected = corrected.replace(f'<measure number="{number}">', f'<measure number="{number + 1}">')
    at = corrected.index(f'<measure number="{after + 2}">')
    corrected = (corrected[:at] + f'<measure number="{after + 1}">' + app_note("e1", "G4", "whole") + "</measure>"
                 + corrected[at:])
    records = single_records()
    for record in records["olcular"]:
        if record["olcu"] == after:
            record.update({"durum": "duzeltildi", "turler": [*record["turler"], "olcu-cizgisi"]})
        elif record["olcu"] > after:
            record["duzeltilmis"] = [record["olcu"] + 1]
    item = {"duzeltilmis": [after + 1], "oncekiModelOlcusu": after, "turler": ["nota-eksik", "olcu-cizgisi"]}
    if porte is not None:
        item.update({"porte": porte, "parti": 0, "partiPortesi": 1})
    records["eklenenOlcular"] = [item]
    return single_package(root, corrected=corrected, records=records)


class Inserted(unittest.TestCase):
    def test_measure_added_inside_a_staff_is_on_it(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            [result] = read_packages([str(inserted_package(Path(tmp), after=1, porte=1))], Options())
        staffs = by_staff(result)
        self.assertTrue(staffs[1].accepted and staffs[2].accepted, (staffs[1].reasons, staffs[2].reasons))
        self.assertEqual(row_texts(staffs[1].rows)[7:11], ["barline . . . .", "note_1 G4 _ _ upper",
                                                           "barline . . . .", "note_2 D5 _ ?slurStart upper"])
        self.assertEqual(staffs[1].round_trip, "tamam")

    def test_measure_added_at_a_line_end_stays_unclear_with_or_without_the_apps_staff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            # the app gives the staff of the measure before: a rule, the page may have it at the next line's head
            [named] = read_packages([str(inserted_package(Path(tmp) / "a", after=2, porte=1))], Options())
            [unnamed] = read_packages([str(inserted_package(Path(tmp) / "b", after=2, porte=None))], Options())
            [wrong] = read_packages([str(inserted_package(Path(tmp) / "c", after=1, porte=2))], Options())
        for result in (named, unnamed, wrong):
            self.assertEqual(reasons(by_staff(result)[1]), {"olcu-belirsiz"})
            self.assertEqual(reasons(by_staff(result)[2]), {"olcu-belirsiz"})

    def test_items_of_a_score_of_several_parts_go_to_their_own_line(self) -> None:
        staffs = [StaffResult({"porte": 2, "parti": 1, "partiPortesi": 1}),
                  StaffResult({"porte": 5, "parti": 1, "partiPortesi": 1})]
        items = [{"duzeltilmis": [3], "porte": 5, "parti": 1, "partiPortesi": 1},
                 {"duzeltilmis": [3], "porte": 4, "parti": 0, "partiPortesi": 1},
                 {"duzeltilmis": [3], "porte": None, "parti": 1, "partiPortesi": 1},
                 {"duzeltilmis": [3], "porte": None, "parti": 1, "partiPortesi": 2},
                 {"duzeltilmis": [3], "oncekiModelOlcusu": 2}]
        self.assertEqual(inserted_for_line(items, (1, 1), staffs), [items[0], items[2], items[4]])


FERMATA_1 = READ_1.replace("note_2 C5 N slurStop upper", "note_2 C5 N fermata_slurStop upper")


def with_fermata(xml: str, note_id: str) -> str:
    """The corrected file with a fermata on one note, as the app will write it once it keeps fermatas."""
    start = xml.index(f'<note id="{note_id}">')
    end = xml.index("</note>", start)
    return xml[:end] + "<notations><fermata/></notations>" + xml[end:]


def replace_note(xml: str, note_id: str, note: str) -> str:
    start = xml.index(f'<note id="{note_id}">')
    end = xml.index("</note>", start) + len("</note>")
    return xml[:start] + note + xml[end:]


def first_staff(root: Path, **kwargs) -> object:  # noqa: ANN003
    [result] = read_packages([str(single_package(root, **kwargs))], Options())
    return by_staff(result)[1], result


class Marks(unittest.TestCase):
    """The app keeps no fermata, slur or articulation: they come from the reading, unverified."""

    def test_fermata_comes_from_the_reading_unverified(self) -> None:
        self.assertNotEqual(FERMATA_1, READ_1)
        with tempfile.TemporaryDirectory() as tmp:
            staff, result = first_staff(Path(tmp), read=(FERMATA_1, READ_2))
        self.assertTrue(staff.accepted, staff.reasons)
        self.assertEqual(row_texts(staff.rows)[-2], "note_2 C5 ?N ?fermata_slurStop upper")
        self.assertEqual(read_token_lines(row_texts(staff.rows))[-2].unverified, {"lift", "articulation"})
        self.assertEqual(staff.round_trip, "tamam")
        self.assertFalse(any("taşıyor" in w for w in result.warnings))

    def test_fermata_stays_on_a_note_whose_pitch_the_user_corrected(self) -> None:
        corrected = replace_note(single_corrected(), "m2n2", app_note("m2n2", "B4", "half", -1))
        records = single_records()
        records["olcular"][1].update({"durum": "duzeltildi", "turler": ["perde"]})
        with tempfile.TemporaryDirectory() as tmp:
            staff, _ = first_staff(Path(tmp), read=(FERMATA_1, READ_2), corrected=corrected, records=records)
        self.assertTrue(staff.accepted, staff.reasons)
        # the courtesy natural was the old note's; the fermata and the slur's end stay on the note
        self.assertEqual(row_texts(staff.rows)[-2], "note_2 B4 _ ?fermata_slurStop upper")
        self.assertEqual(staff.round_trip, "tamam")

    def test_fermata_over_a_rest(self) -> None:
        resting = READ_1.replace("note_4 C5 _ _ upper\nbarline", "rest_4 _ _ fermata upper\nbarline")
        self.assertNotEqual(resting, READ_1)
        corrected = replace_note(single_corrected(), "m1n4", app_note("m1n4", None, "quarter"))
        # and a note with a fermata and a slur the user made a rest: only the fermata goes with it
        rested = replace_note(single_corrected(), "m2n2", app_note("m2n2", None, "half"))
        records = single_records()
        records["olcular"][1].update({"durum": "duzeltildi", "turler": ["perde"]})
        with tempfile.TemporaryDirectory() as tmp:
            on_rest, _ = first_staff(Path(tmp) / "a", read=(resting, READ_2), corrected=corrected)
            made_rest, _ = first_staff(Path(tmp) / "b", read=(FERMATA_1, READ_2), corrected=rested, records=records)
        self.assertEqual(row_texts(on_rest.rows)[6], "rest_4 _ _ ?fermata upper")
        self.assertEqual(row_texts(made_rest.rows)[-2], "rest_2 _ _ ?fermata upper")
        self.assertEqual((on_rest.round_trip, made_rest.round_trip), ("tamam", "tamam"))

    def test_a_combination_the_vocabulary_lacks_keeps_the_fermata(self) -> None:
        self.assertEqual(_articulation({"tieStop"}, set(), {"fermata", "slurStart", "staccato"}),
                         ("fermata_tieStop", True))
        self.assertEqual(_articulation(set(), set(), {"slurStop", "staccato"}), ("slurStop_staccato", True))
        self.assertEqual(_articulation({"tieStart"}, set(), set()), ("tieStart", False))
        crowded = READ_2.replace("note_1 A4 _ tieStop upper", "note_1 A4 _ fermata_slurStart_staccato_tieStop upper")
        with tempfile.TemporaryDirectory() as tmp:
            [result] = read_packages([str(single_package(Path(tmp), read=(READ_1, crowded)))], Options())
        self.assertEqual(row_texts(by_staff(result)[2].rows)[-2], "note_1 A4 _ ?fermata_tieStop upper")

    def test_marks_the_corrected_file_holds_are_taken_from_it(self) -> None:
        # once the app keeps fermatas: its fermata is the user's, and a fermata it does not have is not there
        corrected = with_fermata(single_corrected(), "m1n4")
        with tempfile.TemporaryDirectory() as tmp:
            staff, result = first_staff(Path(tmp), read=(FERMATA_1, READ_2), corrected=corrected)
        rows = row_texts(staff.rows)
        self.assertEqual(rows[6], "note_4 C5 _ fermata upper")
        self.assertEqual(rows[-2], "note_2 C5 ?N ?slurStop upper")  # slurs are still the reading's
        self.assertIn("düzeltilmiş nota şu işaretleri kendisi taşıyor: fermata", result.warnings)


class Measures(unittest.TestCase):
    def test_measure_broken_over_a_line_end_is_cut_where_the_reading_breaks(self) -> None:
        read_1 = """
        clef_G2 _ _ _ upper
        timeSignature_3/4 . . . .
        note_4 C5 _ _ upper
        note_4 D5 _ _ upper
        note_4 E5 _ _ upper
        barline . . . .
        note_4 D5 _ _ upper
        note_4 E5 _ _ upper
        """
        read_2 = """
        clef_G2 _ _ _ upper
        note_4 F5 _ _ upper
        barline . . . .
        note_2. G5 _ _ upper
        barline . . . .
        """
        notes = [("m1n1", "C5"), ("m1n2", "D5"), ("m1n3", "E5")], [("m2n1", "D5"), ("m2n2", "E5"),
                                                                    ("m2n3", "F5")]
        measures = []
        for number, group in enumerate(notes, 1):
            head = ('<attributes><divisions>1</divisions><time><beats>3</beats><beat-type>4</beat-type></time><clef>'
                    '<sign>G</sign><line>2</line></clef></attributes>' if number == 1 else "")
            measures.append(f'<measure number="{number}">{head}'
                            + "".join(app_note(i, p, "quarter", divisions=1) for i, p in group) + "</measure>")
        measures.append('<measure number="3"><note id="m3n1"><pitch><step>G</step><octave>5</octave></pitch>'
                        '<duration>3</duration><voice>1</voice><type>half</type><dot/></note>'
                        '<barline location="right"><bar-style>light-heavy</bar-style></barline></measure>')
        boxes = [[100, 300, 1800, 380], [100, 600, 1800, 680]]
        files = {
            "model.musicxml": model_xml(read_1, read_2),
            "duzeltilmis.musicxml": app_score([("P1", "Ses", measures)]),
            "porteler.json": {"kaynak": "servis", "porteler": [
                {"porte": 1, "sayfa": 1, "kutu": boxes[0], "olcuBas": 1, "olcuSon": 2},
                {"porte": 2, "sayfa": 1, "kutu": boxes[1], "olcuBas": 2, "olcuSon": 3}]},
            "olcular.json": {"olcular": [
                {"olcu": 1, "durum": "onaylandi", "turler": [], "duzeltilmis": [1], "porte": 1},
                {"olcu": 2, "durum": "onaylandi", "turler": [], "duzeltilmis": [2], "porte": 1},
                {"olcu": 3, "durum": "onaylandi", "turler": [], "duzeltilmis": [3], "porte": 2}],
                "eklenenOlcular": []},
        }
        with tempfile.TemporaryDirectory() as tmp:
            [package] = load_packages(str(write_package(Path(tmp), files, image=page_png(boxes))))
            staffs = by_staff(process_package(package, Options()))
        self.assertTrue(staffs[1].accepted and staffs[2].accepted, (staffs[1].reasons, staffs[2].reasons))
        self.assertEqual(row_texts(staffs[1].rows)[-3:], ["barline . . . .", "note_4 D5 _ _ upper",
                                                          "note_4 E5 _ _ upper"])
        self.assertEqual(row_texts(staffs[2].rows), ["clef_G2 _ _ _ upper", "note_4 F5 _ _ upper",
                                                     "barline . . . .", "note_2. G5 _ _ upper", "barline . . . ."])
        self.assertEqual(staffs[2].model_measures, [2, 3])

    def test_round_trip_names_the_measure_that_does_not_come_back(self) -> None:
        line = read_lines(single_corrected(), APP_COMMA)[0]
        rows = [Row(*s.split()) for s in """clef_G2 _ _ _ upper
keyAccidental B4 flat1 _ upper
timeSignature_4/4 . . . .
note_4 A4 _ _ upper
note_4 B4 _ _ upper
note_4 C5 sharp4 _ upper
note_4 C5 _ _ upper
barline . . . .
note_2 D5 _ _ upper
note_2 C5 _ _ upper
barline . . . .""".splitlines()]
        self.assertEqual(round_trip([(rows, [0, 1])], line), {})
        rows[4] = Row("note_4", "B4", "N", "_", "upper")  # the key's koma flat cancelled
        self.assertEqual(round_trip([(rows, [0, 1])], line), {0: ["ölçü 1: olay 2: B4-1 quarter yerine B4 quarter"]})
        # a measure lost on the way: every measure is named, the writer's count no longer matches
        problems = round_trip([(rows[:8], [0, 1])], line)
        self.assertEqual(sorted(problems), [0, 1])
        self.assertIn("yazıcı 1 ölçü yazdı, düzeltmede 2 ölçü var", problems[1][0])


if __name__ == "__main__":
    unittest.main()
