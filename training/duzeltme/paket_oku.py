"""Training samples from the correction packages the Musiki Akademisi app exports.

    python -m training.duzeltme.paket_oku PAKET [PAKET ...] --cikti C:/projects/yl/musiki-duzeltme/okunmus [--ad train]
                                          [--olcu-maskele] [--yalniz-not]

A user of the app corrects what our model read off a page and the app exports the correction as a package (the
writer: musikiakademisi apps/web/src/lib/server/omr/egitim-paketi.ts, format "musiki-akademisi-duzeltme/1"). A package
is a zip or its unzipped folder holding one or more folders duzeltme-<id>/: the uploaded file as it was (orijinal.*),
the model's reading (model.musicxml), the corrected score (duzeltilmis.musicxml; with several parts also
duzeltilmis-servis-duzeni.musicxml, laid out as the service lays out its parts), the staff boxes the service found
(porteler.json) and how every measure was checked (olcular.json: duzeltildi, onaylandi or bakilmadi).

Every staff the user checked becomes a sample in the layout of the other training sets: the staff's picture, cut out
of the page the way the service cut it for the model (homr.staff_parsing.prepare_staff_image, less the dewarping:
see cut_staff), its token lines (training.duzeltme.etiket), and a line "png,tokens" in index_<ad>.txt. rapor.json
says, staff by staff, what was taken, what was not and why, and which measures were masked.

Which staffs (see OKU_BENI.md):
- a staff is taken only when every measure on it was corrected (duzeltildi) or approved (onaylandi); one measure
  nobody looked at (bakilmadi) leaves the whole staff out. With --olcu-maskele such a staff is taken all the same,
  its unchecked measures written with every field unverified ("?"), which the training loss skips;
- a staff the base model read (aeuDenetlenmeli: it does not know the AEU koma accidentals) only when every measure
  on it was checked, also with --olcu-maskele, each by an approval or a correction of its notes (a structural edit
  or a fermata says nothing of its koma signs);
- in a score of several parts a structural edit is put on every part, by design: a measure corrected with structural
  kinds only is no check of a staff there (yalniz-yapisal). An app that does not name itself (manifest uygulamaSurumu
  missing or null: every version before the field) put an approval on every staff of the measure, every part, too:
  there only a correction of the notes counts (onay-butun-partilere). No option takes such approvals.
  An app that names itself puts an approval on the part the user chose only;
- --yalniz-not counts a corrected measure as checked only when the correction touched its notes (perde, arıza,
  süre, nota, bağ, süsleme); a structural edit (repeat, volta, key, meter, a measure added or taken out) is made for
  every part at once and says nothing about the notes of the parts the user did not look at;
- no staff of a package the app's administrator did not take for training (manifest kontrol.durum other than
  egitime-alindi, or no kontrol: yonetici-kontrolu), nor of the app's format samples (ornek-paket);
- records without a staff (porte: null: no staff boxes from the service) are skipped;
- the staff's tokens must come back as the corrected score when written out again (etiket.round_trip);
- of several corrections of one upload (anonimYukleme, else the original file's SHA-256) only the newest is taken
  (read_packages).

What the app's writer puts in by itself is not taken as the page's: the light-heavy barline after the last measure
and a first-measure time signature the reading does not have and no olcu-isareti operation set (rapor.json
yaziciVarsayilanlari).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from homr.autocrop import autocrop_box
from homr.color_adjust import apply_clahe
from homr.image_utils import crop_image_and_return_new_top
from homr.resize import resize_image
from homr.simple_logging import eprint
from homr.staff_parsing import (
    center_image_on_canvas,
    get_tr_omr_canvas_size,
    remove_black_contours_at_edges_of_image,
)
from training.duzeltme.etiket import (
    APP_COMMA,
    HOMR_COMMA,
    Hints,
    LabelError,
    Measure,
    Piece,
    Row,
    StaffLine,
    key_at,
    read_lines,
    round_trip,
    row_texts,
    carried_marks,
    staff_rows,
    writer_defaults,
)

FORMAT = "musiki-akademisi-duzeltme/1"
SERVICE_LAYOUT = "duzeltilmis-servis-duzeni.musicxml"
# a pdf page is rendered at this width, as the service renders it (servis/nota_servisi.py PAGE_WIDTH)
PAGE_WIDTH = 1920
# the kinds of correction that touch a measure's notes; the others are structural (music-core duzenle/fark.ts)
NOTE_KINDS = frozenset({"perde", "ariza", "sure", "nota-fazla", "nota-eksik", "bag", "susleme"})
# the kinds the app sends to the part the user chose only, of a score of several parts: the note kinds and a fermata
# added or taken away (which does not touch the notes)
PART_KINDS = NOTE_KINDS | {"fermata"}
# the manifest's isaretler: the <notations> kinds the corrected file is written with, by MusicXML name. Those that are
# marks of homr's vocabulary (etiket.mark_kind) are then the user's; tied and tuplet the app has always kept, and the
# label takes them from the corrected file in any case
NOTATION_MARKS = {"fermata": "fermata", "slur": "slur", "arpeggiate": "arpeggiate"}
ALWAYS_KEPT = frozenset({"tied", "tuplet"})

git_root = Path(__file__).resolve().parent.parent.parent


class PackageError(Exception):
    """A package this reader does not read."""


@dataclass
class Options:
    mask_measures: bool = False  # --olcu-maskele
    notes_only: bool = False  # --yalniz-not


@dataclass
class Checks:
    """What counts as a look at a staff in one package (see checks_of)."""

    approval: bool = True  # an approval of the measure
    structure: bool = True  # a correction of structural kinds only


@dataclass
class Package:
    """One correction folder duzeltme-<id>/ and its files, by name."""

    name: str
    files: dict[str, bytes]

    def text(self, name: str) -> str:
        if name not in self.files:
            raise PackageError(f"{self.name}: {name} yok")
        return self.files[name].decode("utf-8")

    def load_json(self, name: str) -> dict:
        return json.loads(self.text(name))


@dataclass
class StaffResult:
    """What became of one staff of the page."""

    entry: dict  # its porteler.json item
    reasons: list[dict] = field(default_factory=list)  # why it is not taken: {"neden", "ayrinti"}
    warnings: list[str] = field(default_factory=list)
    model_measures: list[int] = field(default_factory=list)  # the service's measure numbers on it
    states: dict[int, str] = field(default_factory=dict)  # model measure -> durum
    masked: list[int] = field(default_factory=list)  # corrected measure numbers written unverified
    pieces: list[Piece] = field(default_factory=list)
    rows: list[Row] | None = None
    image: np.ndarray | None = None
    round_trip: str | None = None  # "tamam", or why not
    sample: str | None = None  # the file name the sample is written under (without extension)
    base_model: bool = False  # read by the base model (porteler.json or olcular.json aeuDenetlenmeli)

    @property
    def accepted(self) -> bool:
        return not self.reasons

    def reject(self, reason: str, detail: str = "") -> None:
        if not any(r["neden"] == reason and r["ayrinti"] == detail for r in self.reasons):
            self.reasons.append({"neden": reason, "ayrinti": detail})

    def report(self) -> dict:
        e = self.entry
        return {
            "porte": e.get("porte"),
            "sayfa": e.get("sayfa"),
            "sistem": e.get("sistem"),
            "parti": e.get("parti", 0),
            "partiPortesi": e.get("partiPortesi", 1),
            "okuyan": e.get("okuyan"),
            "aeuDenetlenmeli": self.base_model,
            "olcular": self.model_measures,
            "durumlar": {str(m): s for m, s in self.states.items()},
            "kabul": self.accepted,
            "nedenler": self.reasons,
            "maskelenenOlcular": self.masked,
            "gidisDonus": self.round_trip,
            "uyarilar": self.warnings,
            "ornek": self.sample,
        }


@dataclass
class PackageResult:
    name: str
    manifest: dict
    staffs: list[StaffResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped_records: int = 0  # olcular.json records without a staff (porte: null)
    defaults: list[str] = field(default_factory=list)  # what the app's writer put in by itself (not the page's)
    checks: Checks = field(default_factory=Checks)  # what counts as a look at a staff (checks_of)

    def report(self) -> dict:
        m = self.manifest
        return {
            "klasor": self.name,
            "anonimKimlik": m.get("anonimKimlik"),
            "anonimYukleme": m.get("anonimYukleme"),
            "surum": m.get("surum"),
            "uygulamaSurumu": m.get("uygulamaSurumu"),
            "kontrol": m.get("kontrol"),
            "isaretler": m.get("isaretler"),
            "onayButunPartilere": not self.checks.approval,
            "yapisalDenetimSayilmaz": not self.checks.structure,
            "modelVersion": m.get("modelVersion"),
            "tur": m.get("tur"),
            "cokParti": "cokParti" in m,
            "porteKaynagi": m.get("porteKaynagi"),
            "portesizKayit": self.skipped_records,
            "yaziciVarsayilanlari": self.defaults,
            "uyarilar": self.warnings,
            "porteler": [s.report() for s in self.staffs],
        }


# --- reading packages ---------------------------------------------------------------------------------------------


def _check_index(data: bytes, where: str) -> None:
    index = json.loads(data.decode("utf-8"))
    if index.get("bicim") != FORMAT:
        raise PackageError(f"{where}: bilinmeyen paket biçimi {index.get('bicim')!r}; bu okuyucu yalnız {FORMAT} okur")


def load_packages(path: str) -> list[Package]:
    """The correction folders in a zip, or in a folder (one that is itself a correction folder, or holds some)."""
    groups: dict[str, dict[str, bytes]] = defaultdict(dict)
    source = Path(path)
    if source.is_file():
        with zipfile.ZipFile(source) as archive:
            for info in archive.infolist():
                name = info.filename.replace("\\", "/")
                if info.is_dir() or name.startswith("/") or ".." in name.split("/"):
                    continue
                folder, _, file = name.rpartition("/")
                if not folder and file == "index.json":
                    _check_index(archive.read(info), path)
                    continue
                groups[folder][file] = archive.read(info)
    elif source.is_dir():
        if (source / "index.json").is_file() and not (source / "manifest.json").is_file():
            _check_index((source / "index.json").read_bytes(), path)
        for manifest in sorted(source.rglob("manifest.json")):
            folder = manifest.parent
            groups[str(folder.relative_to(source)).replace("\\", "/")] = {
                f.name: f.read_bytes() for f in folder.iterdir() if f.is_file()
            }
    else:
        raise PackageError(f"{path}: böyle bir dosya ya da klasör yok")
    packages = []
    for folder, files in sorted(groups.items()):
        if "manifest.json" not in files:
            continue
        name = folder.rpartition("/")[2] if folder and folder != "." else source.stem
        packages.append(Package(name, files))
    if not packages:
        raise PackageError(f"{path}: manifest.json bulunamadı")
    return packages


def check_manifest(package: Package) -> dict:
    """The manifest, if this reader knows its format; PackageError if not."""
    manifest = package.load_json("manifest.json")
    form = manifest.get("bicim")
    if form != FORMAT:
        raise PackageError(f"{package.name}: bilinmeyen paket biçimi {form!r}; bu okuyucu yalnız {FORMAT} okur")
    several = manifest.get("cokParti")
    if several is not None:
        if several.get("olcuKaydi") != "porte":
            kind = several.get("olcuKaydi")
            raise PackageError(f"{package.name}: çok partili pakette bilinmeyen ölçü kaydı {kind!r}")
        if several.get("servisDuzeni", SERVICE_LAYOUT) not in package.files:
            raise PackageError(f"{package.name}: {several.get('servisDuzeni', SERVICE_LAYOUT)} yok")
    for name in ("porteler.json", "olcular.json", "model.musicxml", "duzeltilmis.musicxml"):
        if name not in package.files:
            raise PackageError(f"{package.name}: {name} yok")
    return manifest


# --- which measures are on which staff ------------------------------------------------------------------------------


def reviewed(record: dict, options: Options, checks: Checks | None = None, notes_needed: bool = False) -> bool:
    """Whether the user looked at this measure of this staff. A record's onaylandi (newer packages) says the user
    approved it whatever its durum: a structural edit made the measure duzeltildi, the approval is still the user's
    look at this staff. notes_needed (a staff the base model read, whose koma signs are the risk): a correction counts
    only when it touched the notes, as with --yalniz-not."""
    checks = checks or Checks()
    if record.get("durum") == "onaylandi" or record.get("onaylandi") is True:
        if checks.approval:
            return True
    if record.get("durum") == "duzeltildi":
        kinds = set(record.get("turler") or [])
        if NOTE_KINDS & kinds:
            return True
        # a fermata is the chosen part's own edit, a structural one every part's
        return not (options.notes_only or notes_needed) and (bool(PART_KINDS & kinds) or checks.structure)
    return False


def _unreviewed_reason(record: dict) -> str:
    if record.get("durum") == "onaylandi":
        return "onay-butun-partilere"
    if record.get("durum") == "duzeltildi":  # its kinds touch no note: a mark (--yalniz-not), or the structure
        return "yalniz-isaret" if PART_KINDS & set(record.get("turler") or []) else "yalniz-yapisal"
    return "bakilmadi"


def checks_of(manifest: dict, entries: list[dict]) -> Checks:
    """In a score of several parts the app puts a structural edit (repeat, key, meter, barline) on every part by
    design, whatever its version (the part picker sends only note edits to the chosen part): it never says the user
    looked at this staff. An app that does not name itself (no uygulamaSurumu: every version before the field, and a
    tab opened before that release) put an approval of a measure on every staff of the measure, every part, as well:
    no option takes such approvals, so that a staff the base model read is never taken unchecked."""
    several = len({e.get("parti", 0) for e in entries}) > 1
    return Checks(approval=not several or bool(manifest.get("uygulamaSurumu")), structure=not several)


def kept_marks(manifest: dict) -> tuple[frozenset[str], list[str]]:
    """The kinds of mark (etiket.mark_kind) the corrected file holds as the user left them, and notes for the report:
    the manifest's isaretler, from an app that names itself. Without the list (an older package) every mark is the
    reading's, unverified. A tab opened before a release may save a file that lists a kind its reader had dropped on
    loading (uygulamaSurumu null): there too."""
    listed = manifest.get("isaretler")
    if listed is None:
        return frozenset(), []
    marks = set(listed) - ALWAYS_KEPT
    if not manifest.get("uygulamaSurumu"):
        return frozenset(), ([f"isaretler ({', '.join(sorted(marks))}) uygulamaSurumu olmadan: yayından önce açılmış "
                              "sekmeden kayıt olabilir, işaretler okumadan alındı"] if marks else [])
    unknown = sorted(marks - set(NOTATION_MARKS))
    notes = [f"isaretler'de bu okuyucunun bilmediği türler: {', '.join(unknown)} (okumadan alındı)"] if unknown else []
    return frozenset(NOTATION_MARKS[n] for n in marks if n in NOTATION_MARKS), notes


def _model_measure(model: StaffLine | None, number: int) -> Measure | None:
    if model is None:
        return None
    return next((m for m in model.measures if m.number == number), None)


def _split(
    shared: int, owned: list[int], corrected: StaffLine, model: StaffLine | None
) -> tuple[list[Piece], list[Piece]] | str:
    """The corrected measures of a model measure the page breaks over two staffs, cut where the reading's line break
    stands: (pieces on the first staff, pieces on the second), or why it cannot be done."""
    measure = _model_measure(model, shared)
    if measure is None or not measure.breaks:
        return f"ölçü {shared} iki porteye bölünmüş, okumada satır sonu bulunamadı"
    cut = measure.breaks[-1]
    side_of = {e.app_id: int(k >= cut) for k, e in enumerate(measure.events) if e.app_id}
    sides: list[int | None] = []
    events = []
    for index in owned:
        for event in corrected.measures[index].events:
            events.append((index, event))
            sides.append(side_of.get(event.note_id or ""))
    if not events:
        return f"ölçü {shared} iki porteye bölünmüş ve boş"
    for k in range(len(sides)):
        if sides[k] is None:
            after = next((s for s in sides[k + 1 :] if s is not None), None)
            before = next((s for s in reversed(sides[:k]) if s is not None), None)
            if events[k][1].is_grace and after is not None:
                sides[k] = after  # a grace note goes with the note it leads to
            elif before is not None and (after is None or after == before):
                sides[k] = before
            elif after is not None and before is None:
                sides[k] = after
            else:
                return f"ölçü {shared}: satır sonundaki yeni notanın portesi belli değil"
    if any(a > b for a, b in zip(sides, sides[1:], strict=False)):  # type: ignore[operator]
        return f"ölçü {shared}: notalar satır sonunda karışmış"
    first: list[Piece] = []
    second: list[Piece] = []
    k = 0
    for index in owned:
        count = len(corrected.measures[index].events)
        own = sides[k : k + count]
        k += count
        if not own:
            return f"ölçü {shared}: boş ölçü satır sonunda"
        if all(s == 0 for s in own):
            first.append(Piece(index, 0, count, True, True))
        elif all(s == 1 for s in own):
            second.append(Piece(index, 0, count, True, True))
        else:
            cut_at = own.index(1)
            first.append(Piece(index, 0, cut_at, True, False))
            second.append(Piece(index, cut_at, count, False, True))
    return first, second


def inserted_for_line(items: list[dict], key: tuple[int, int], staffs: list[StaffResult]) -> list[dict]:
    """The eklenenOlcular items of one line: a score of several parts has one item per part, named by its staff
    (porte) or, when the app found none, by parti and partiPortesi; an item that names neither (a single part, an
    older package) is every line's."""
    portes = {staff.entry.get("porte") for staff in staffs}
    found = []
    for item in items:
        if item.get("porte") is not None:
            if item["porte"] in portes:
                found.append(item)
        elif "parti" in item or "partiPortesi" in item:
            if (item.get("parti", 0), item.get("partiPortesi", 1)) == key:
                found.append(item)
        else:
            found.append(item)
    return found


def plan_line(
    staffs: list[StaffResult],
    records: list[dict],
    inserted: list[dict],
    corrected: StaffLine,
    model: StaffLine | None,
    options: Options,
    meter_set_first: bool = False,
    checks: Checks | None = None,
) -> dict[int, Hints]:
    """Find the corrected measures of every staff of one line (one part's staff through the score) and which are
    masked; mark the staffs that cannot be taken. Returns the hints of the reading by staff (index in staffs).
    meter_set_first: islemler.json sets the first measure's time signature. checks: see checks_of."""
    by_number: dict[int, list[int]] = defaultdict(list)
    for index, measure in enumerate(corrected.measures):
        by_number[measure.number].append(index)
    record_at = {(r["porte"], r["olcu"]): r for r in records if r.get("porte") is not None}
    owners: dict[int, set[int]] = defaultdict(set)  # corrected measure -> staffs showing it
    of_model: dict[int, list[int]] = {}  # model measure -> its corrected measures
    record_of: dict[int, dict] = {}  # model measure -> its record (the staff that starts it)
    inserted_at: dict[int, dict] = {}  # corrected measure -> its eklenenOlcular item
    shared: dict[int, int] = {}  # staff -> the model measure it breaks over into the next staff
    ranges: dict[int, tuple[int, int]] = {}
    for s, staff in enumerate(staffs):
        first, last = staff.entry.get("olcuBas"), staff.entry.get("olcuSon")
        if first is None or last is None or first > last:
            staff.reject("olcu-yok", "servis bu portede ölçü bulmadı")
            continue
        ranges[s] = (first, last)
    for s, (first, last) in ranges.items():
        staff = staffs[s]
        earlier = [t for t in ranges if t < s]
        previous = max(earlier) if earlier else None
        for number in range(first, last + 1):
            # the service gives a measure the page breaks over a line end to both staffs; olcular.json records it
            # on the first
            continued = number == first and previous is not None and ranges[previous][1] == number
            record = record_at.get((staff.entry["porte"], number))
            if continued:
                shared[previous] = number
                record = record or record_at.get((staffs[previous].entry["porte"], number))
            if record is None:
                staff.reject("kayit-yok", f"ölçü {number} için olcular.json kaydı yok")
                continue
            staff.model_measures.append(number)
            staff.states[number] = record.get("durum", "?")
            staff.base_model = staff.base_model or bool(record.get("aeuDenetlenmeli"))
            record_of[number] = record
            found = []
            for n in record.get("duzeltilmis") or []:
                indices = by_number.get(n, [])
                if len(indices) != 1:
                    staff.reject("olcu-belirsiz", f"düzeltilmiş ölçü {n} {'yok' if not indices else 'iki kez var'}")
                    continue
                found.append(indices[0])
            of_model[number] = found
            if not continued:  # the measure's pieces on the two staffs are cut below
                for index in found:
                    owners[index].add(s)
    for item in inserted:
        indices = [by_number.get(n, []) for n in item.get("duzeltilmis") or []]
        if any(len(i) != 1 for i in indices) or not indices:
            continue
        before = item.get("oncekiModelOlcusu")
        if before is None:
            at = [min(ranges, key=lambda t: ranges[t][0])] if ranges else []
        else:
            at = [s for s, (first, last) in ranges.items() if first <= before <= last]
        if item.get("porte") is not None:
            # The app names the staff of the model measure before the added one (else the one after it). That
            # confirms the staff, but it is a rule, not what the page shows: a measure added after the last measure
            # of a staff may as well open the next one, so that stays unclear below.
            on = [s for s, staff in enumerate(staffs) if staff.entry.get("porte") == item["porte"]]
            if not on or on[0] not in ranges:
                continue
            if at and on[0] not in at:
                staffs[on[0]].reject("olcu-belirsiz", f"ölçü {before} ardından eklenen ölçünün portesi "
                                                      f"(porte {item['porte']}) o ölçünün portesi değil")
                continue
            at = on
        if len(at) != 1:
            continue
        s = at[0]
        later = [t for t in ranges if t > s]
        if before is not None and before == ranges[s][1] and later:
            # added after the last measure of a staff: the end of this staff or the head of the next one?
            for t in (s, min(later)):
                staffs[t].reject("olcu-belirsiz", f"ölçü {before} ardından eklenen ölçü porte sınırında")
            continue
        for i in indices:
            owners[i[0]].add(s)
            inserted_at[i[0]] = item
    # a corrected measure on two staffs: the page breaks it over a line end (split below), else it is unclear
    split_pieces: dict[int, list[Piece]] = defaultdict(list)
    for s, number in shared.items():
        nxt = min(t for t in ranges if t > s)
        cut = _split(number, of_model.get(number, []), corrected, model)
        if isinstance(cut, str):
            staffs[s].reject("bolunmus-olcu", cut)
            staffs[nxt].reject("bolunmus-olcu", cut)
            continue
        split_pieces[s] += cut[0]
        split_pieces[nxt] += cut[1]
    in_split = {p.measure for pieces in split_pieces.values() for p in pieces}
    for index, holders in owners.items():
        if len(holders) > 1 and index not in in_split:
            for s in holders:
                staffs[s].reject("olcu-belirsiz", f"düzeltilmiş ölçü {corrected.measures[index].number} iki portede")

    def checked(index: int, notes_needed: bool) -> tuple[bool, str]:
        """Whether every record behind a corrected measure says it was looked at."""
        behind = [record_of[m] for m, found in of_model.items() if index in found]
        if index in inserted_at:
            behind.append({"durum": "duzeltildi", "turler": inserted_at[index].get("turler") or []})
        for record in behind:
            if not reviewed(record, options, checks, notes_needed):
                return False, _unreviewed_reason(record)
        return bool(behind), ""

    hints: dict[int, Hints] = {}
    model_events = {e.app_id: e for m in (model.measures if model else []) for e in m.events if e.app_id}
    for s in ranges:
        staff = staffs[s]
        pieces = [p for p in split_pieces.get(s, [])]
        pieces += [Piece(i, 0, len(corrected.measures[i].events), True, True)
                   for i, holders in owners.items() if s in holders and i not in in_split]
        pieces.sort(key=lambda p: (p.measure, p.first))
        indices = sorted({p.measure for p in pieces})
        if indices and indices != list(range(indices[0], indices[-1] + 1)):
            staff.reject("olcu-belirsiz", "portenin düzeltilmiş ölçüleri ardışık değil")
        if not pieces and not staff.reasons:
            staff.reject("olcu-yok", "portede düzeltilmiş ölçü kalmadı")
        unchecked: dict[str, list[int]] = defaultdict(list)
        for piece in pieces:
            ok, why = checked(piece.measure, staff.base_model)
            if not ok:
                piece.masked = True
                unchecked[why or "bakilmadi"].append(corrected.measures[piece.measure].number)
        for number in staff.model_measures:  # measures the user took out are no piece, but were looked at or not
            record = record_of[number]
            if not of_model.get(number) and not reviewed(record, options, checks, staff.base_model):
                unchecked[_unreviewed_reason(record)].append(number)
        if unchecked:
            detail = "; ".join(f"{why}: ölçü {', '.join(map(str, sorted(set(n))))}" for why, n in unchecked.items())
            if not options.mask_measures:
                for why, numbers in unchecked.items():
                    staff.reject(why, f"ölçü {', '.join(map(str, sorted(set(numbers))))}")
            if staff.base_model:
                # the base model does not know the koma signs: what nobody checked may be a plain sharp or flat
                staff.reject("aeu-denetlenmedi", f"temel modelin okuduğu porte tamamen denetlenmemiş ({detail})")
            elif options.mask_measures and all(p.masked for p in pieces):
                staff.reject("hic-bakilmamis", detail)
            elif options.mask_measures:
                staff.masked = sorted({corrected.measures[p.measure].number for p in pieces if p.masked})
        staff.pieces = pieces
        for index in indices:
            m = corrected.measures[index]
            if not m.events:
                # a measure the user added and left empty: the page has no such measure to show
                staff.reject("bos-olcu", f"düzeltilmiş ölçü {m.number} boş")
            if m.chord_notes or m.other_voices:
                staff.reject("akor-ikinci-ses", f"düzeltmede ölçü {m.number} akor ya da ikinci ses taşıyor")
        for number in staff.model_measures:
            m = _model_measure(model, number)
            if m is not None and (m.chord_notes or m.other_voices):
                staff.reject("akor-ikinci-ses", f"okumada ölçü {number} akor ya da ikinci ses taşıyor; "
                                                "düzeltme yalnız ilk sesi tutar")
        cut = staff.entry.get("ustSesKirpildi")  # true | false; missing or not a boolean: not known
        if cut is True:
            # the service cut the staff's chords or second voice down to its top line: the page holds more than the
            # correction can
            staff.reject("ust-ses-kirpildi", "serviste akor ya da ikinci ses üst sese indirildi; etiket eksik olur")
        elif staff.entry.get("okuyan") == "temel" and not isinstance(cut, bool):
            # an answer from before the service said which staffs it cut down
            staff.warnings.append("temel model okudu: sayfada akor ya da ikinci ses varsa servis yalnız üst sesi "
                                  "yazmış olabilir, etiket o sesleri taşımaz")
        # the reading's hints
        hint = Hints(events=model_events, drawn=model is not None and not staff.base_model,
                     meter_set_first=meter_set_first, last_measure=len(corrected.measures) - 1,
                     reading_end=model.measures[-1] if model and model.measures else None)
        for index in indices:
            behind = [m for m, found in of_model.items() if index in found]
            hint.edited[index] = {t for m in behind for t in record_of[m].get("turler") or []}
            if index in inserted_at:
                hint.edited[index] |= set(inserted_at[index].get("turler") or [])
            if len(behind) == 1 and of_model[behind[0]] == [index]:
                twin = _model_measure(model, behind[0])
                if twin is not None:
                    hint.twins[index] = twin
        head = _model_measure(model, ranges[s][0])
        if head is not None:
            continues = any(shared.get(t) == ranges[s][0] for t in ranges if t < s)
            start = head.breaks[-1] if continues and head.breaks else 0
            keys = [entries for at, entries in head.keys if at == start]
            hint.key_at_start = bool(keys)
            hint.key_order = [step for step, _ in keys[0]] if keys else None
            hint.time_at_start = any(at == start for at, _ in head.times)
        hints[s] = hint
    return hints


# --- the page and the staff's picture -------------------------------------------------------------------------------


@dataclass
class Page:
    """A page as the service read it: preprocessed as homr preprocesses it for staff finding (cut to the paper,
    1920 wide, CLAHE), and how its pixels map to the page image's, where the staff boxes are."""

    pixels: np.ndarray
    left: int
    top: int
    scale_x: float
    scale_y: float


def _decode(data: bytes, suffix: str) -> np.ndarray | None:
    # read from a file as the service does (cv2.imread, which turns a photo by its EXIF orientation)
    with tempfile.TemporaryDirectory() as scratch:
        path = os.path.join(scratch, "sayfa" + suffix)
        Path(path).write_bytes(data)
        return cv2.imread(path)


def page_images(package: Package, manifest: dict, pages: list[int], sizes: dict[int, dict]) -> dict[int, Page | str]:
    """Every page asked for, or why it cannot be had."""
    original = manifest.get("orijinal") or {}
    name = original.get("dosya")
    if not name or name not in package.files:
        return {page: "orijinal dosya pakette yok" for page in pages}
    data = package.files[name]
    if original.get("sha256") and hashlib.sha256(data).hexdigest() != original["sha256"]:
        return {page: "orijinal dosyanın SHA-256'sı manifest'tekiyle aynı değil" for page in pages}
    images: dict[int, np.ndarray | None] = {}
    if original.get("mime") == "application/pdf" or name.endswith(".pdf"):
        import fitz  # noqa: PLC0415  (only for pdfs)

        with fitz.open(stream=data, filetype="pdf") as document:
            for page in pages:
                if not 1 <= page <= document.page_count:
                    images[page] = None
                    continue
                pdf_page = document[page - 1]
                zoom = PAGE_WIDTH / pdf_page.rect.width
                png = pdf_page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).tobytes("png")
                images[page] = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    else:
        image = _decode(data, Path(name).suffix)
        for page in pages:
            images[page] = image if page == 1 else None
    result: dict[int, Page | str] = {}
    for page, image in images.items():
        if image is None:
            result[page] = f"sayfa {page} okunamadı"
            continue
        size = sizes.get(page)
        if size and (size.get("genislik"), size.get("yukseklik")) != (image.shape[1], image.shape[0]):
            result[page] = (f"sayfa {page} {image.shape[1]}×{image.shape[0]}, servis "
                            f"{size.get('genislik')}×{size.get('yukseklik')} okumuş")
            continue
        box = autocrop_box(image) or (0, 0, image.shape[1], image.shape[0])
        x, y, w, h = box
        pixels = apply_clahe(resize_image(image[y : y + h, x : x + w]))
        result[page] = Page(pixels, x, y, w / pixels.shape[1], h / pixels.shape[0])
    return result


def cut_staff(page: Page, box: list[int], boxes: list[list[int]]) -> np.ndarray:
    """The staff's picture as homr.staff_parsing.prepare_staff_image cuts it for the model, from its box: the same
    margins (two staff spaces left and right, four above and below, up to the next staff), scale, edge cleaning and
    canvas. Only the dewarping is left out: it needs the staff lines homr found, which the box does not keep."""

    def inside(b: list[int]) -> tuple[float, float, float, float]:
        return ((b[0] - page.left) / page.scale_x, (b[1] - page.top) / page.scale_y,
                (b[2] - page.left) / page.scale_x, (b[3] - page.top) / page.scale_y)

    min_x, min_y, max_x, max_y = inside(box)
    others = [inside(b) for b in boxes]
    unit = (max_y - min_y) / 4
    above = [o[3] for o in others if o[1] < min_y]
    below = [o[1] for o in others if o[3] > max_y]
    region = np.array([
        int(min_x - 2 * unit),
        int(max(min_y - 4 * unit, max(above) if above else 0)),
        int(max_x + 2 * unit),
        int(min(max_y + 4 * unit, min(below) if below else 1e12)),
    ])
    dimensions = get_tr_omr_canvas_size((int(region[3] - region[1]), int(region[2] - region[0])))
    scaling = dimensions[1] / (region[3] - region[1])
    pixels = cv2.resize(page.pixels, (int(page.pixels.shape[1] * scaling), int(page.pixels.shape[0] * scaling)))
    region = np.round(region * scaling)
    staff, _ = crop_image_and_return_new_top(pixels, *region)
    staff = remove_black_contours_at_edges_of_image(staff, unit * scaling)
    return center_image_on_canvas(staff, dimensions)


# --- one package ------------------------------------------------------------------------------------------------


def process_package(package: Package, options: Options) -> PackageResult:
    manifest = check_manifest(package)
    result = PackageResult(package.name, manifest)
    staff_doc = package.load_json("porteler.json")
    measure_doc = package.load_json("olcular.json")
    several = manifest.get("cokParti")
    name = several.get("servisDuzeni", SERVICE_LAYOUT) if several else "duzeltilmis.musicxml"
    try:
        corrected = read_lines(package.text(name), APP_COMMA)
    except (ET.ParseError, ValueError) as error:
        raise PackageError(f"{package.name}: {name} okunamadı ({error})") from error
    carried, notes = kept_marks(manifest)
    result.warnings += notes
    stray = carried_marks(corrected) - carried
    if stray:
        result.warnings.append(f"düzeltilmiş nota isaretler'de olmayan işaretler taşıyor ({', '.join(sorted(stray))}): "
                               "okumadakiler alındı")
    try:
        model = read_lines(package.text("model.musicxml"), HOMR_COMMA)
    except Exception as error:  # noqa: BLE001
        model = []
        result.warnings.append(f"model.musicxml okunamadı ({error}); okumanın ipuçları kullanılmadı")
    records = measure_doc.get("olcular") or []
    try:
        operations = [op for op in package.load_json("islemler.json") if isinstance(op, dict)]
    except (PackageError, json.JSONDecodeError, TypeError):
        operations = []  # an older package without it: no operation is known
    result.skipped_records = sum(1 for r in records if r.get("porte") is None)
    entries = sorted(staff_doc.get("porteler") or [], key=lambda p: p.get("porte", 0))
    result.staffs = [StaffResult(entry, base_model=bool(entry.get("aeuDenetlenmeli"))) for entry in entries]
    if staff_doc.get("kaynak") != "servis":
        result.warnings.append("porte kutuları servisten değil (print-new-system tahmini): porte resmi kesilemez")
    if not entries:
        result.warnings.append("porteler.json boş")
    result.checks = checks_of(manifest, entries)

    by_line: dict[tuple[int, int], list[StaffResult]] = defaultdict(list)
    for staff in result.staffs:
        by_line[(staff.entry.get("parti", 0), staff.entry.get("partiPortesi", 1))].append(staff)
    all_hints: dict[int, Hints] = {}
    lines: dict[tuple[int, int], StaffLine] = {}
    for key, staffs in by_line.items():
        line = next((x for x in corrected if (x.part, x.staff) == key), None)
        if line is None:
            for staff in staffs:
                staff.reject("olcu-belirsiz", f"düzeltmede parti {key[0]}, porte {key[1]} yok")
            continue
        lines[key] = line
        model_line = next((x for x in model if (x.part, x.staff) == key), None)
        if model_line is None and model:
            result.warnings.append(f"okumada parti {key[0]}, porte {key[1]} yok; ipuçları kullanılmadı")
        if several is None:
            line_records = records
        else:
            line_records = [r for r in records if (r.get("parti", 0), r.get("partiPortesi", 1)) == key]
        first = line.measures[0].number if line.measures else 1
        meter_set_first = any(op.get("tur") == "olcu-isareti" and op.get("olcu") == first for op in operations)
        line_inserted = inserted_for_line(measure_doc.get("eklenenOlcular") or [], key, staffs)
        hints = plan_line(staffs, line_records, line_inserted, line, model_line, options,
                          meter_set_first, result.checks)
        where = f"parti {key[0]}, porte {key[1]}: " if several else ""
        result.defaults += [where + found for found in writer_defaults(line, model_line, meter_set_first)]
        for s, hint in hints.items():
            hint.carried = carried
            all_hints[id(staffs[s])] = hint

    # tokens, and the round trip line by line
    for key, staffs in by_line.items():
        if key not in lines:
            continue
        written: list[tuple[list[Row], list[int]]] = []
        built: list[StaffResult] = []
        for staff in staffs:
            if not staff.pieces or id(staff) not in all_hints:
                continue
            try:
                staff.rows = staff_rows(lines[key], staff.pieces, all_hints[id(staff)])
            except LabelError as error:
                staff.reject("jeton", str(error))
                continue
            written.append((staff.rows, [p.measure for p in staff.pieces]))
            built.append(staff)
            hint = all_hints[id(staff)]
            if hint.key_at_start is False and staff.rows and not any(r.rhythm == "keyAccidental" for r in staff.rows):
                if key_at(lines[key], staff.pieces[0].measure):
                    staff.warnings.append("okuma bu portenin başında donanım görmedi: etikete donanım yazılmadı")
        problems = round_trip(written, lines[key]) if written else {}
        for staff in built:
            own = [p for piece in staff.pieces for p in problems.get(piece.measure, [])]
            if own:
                staff.round_trip = "; ".join(dict.fromkeys(own))
                staff.reject("gidis-donus", staff.round_trip)
            else:
                staff.round_trip = "tamam"

    # what the app's administrator decided: only a correction version the administrator took for training
    # ("egitime-alindi") gives samples, and no option changes that; a package from before the field (413e4b9 and
    # earlier) had no such decision. The user only saves; a version taken with its koma check unfinished keeps its
    # unchecked base-model staffs out by aeu-denetlenmedi. The app's own format samples never give samples.
    control = manifest.get("kontrol") or {}
    if control.get("durum") != "egitime-alindi":
        detail = f"kontrol: {control.get('durum') or 'yok'}"
        result.warnings.append(f"yönetici eğitime almadı ({detail}): hiçbir porte alınmaz")
        for staff in result.staffs:
            staff.reject("yonetici-kontrolu", detail)
    if manifest.get("modelVersion") == "v-ornek" or (manifest.get("riza") or {}).get("metinSurumu") == "ornek":
        result.warnings.append("uygulamanın biçim örneği: hiçbir porte alınmaz")
        for staff in result.staffs:
            staff.reject("ornek-paket", "uygulamanın biçim örneği (EĞİTİME GİRMEZ)")

    # pictures, for the staffs still taken
    wanted = sorted({s.entry.get("sayfa") for s in result.staffs if s.accepted and s.entry.get("sayfa")})
    sizes = {p.get("sayfa"): p for p in staff_doc.get("sayfaResimleri") or []}
    pages = page_images(package, manifest, wanted, sizes) if wanted else {}
    for staff in result.staffs:
        if not staff.accepted:
            continue
        page = pages.get(staff.entry.get("sayfa"))
        box = staff.entry.get("kutu")
        if not box:
            staff.reject("kutu-yok", "servis bu porte için kutu yazmamış")
        elif page is None or isinstance(page, str):
            staff.reject("resim-yok", page or "portenin sayfası bilinmiyor")
        else:
            same_page = [s.entry["kutu"] for s in result.staffs
                         if s.entry.get("sayfa") == staff.entry.get("sayfa") and s.entry.get("kutu")]
            try:
                staff.image = cut_staff(page, box, same_page)
            except cv2.error as error:
                staff.reject("kesim", str(error)[:120])
    return result


# --- the dataset ------------------------------------------------------------------------------------------------


def _index_path(path: Path) -> str:
    """As the other index files write it: relative to the repository, with forward slashes."""
    try:
        return os.path.relpath(path, git_root).replace(os.sep, "/")
    except ValueError:  # another drive
        return str(path).replace(os.sep, "/")


def write_dataset(results: list[PackageResult], out: str, subset: str, options: Options,
                  refused: list[str] | None = None) -> dict:
    """The accepted staffs as png + tokens under out/subset/, their index out/index_<subset>.txt (and one per kind
    of reading, index_<subset>_basili.txt and _el_yazisi.txt: the training roughens handwriting by the picture's
    folder, training/transformer/data_loader.py HANDWRITTEN_SETS) and the report out/rapor.json. Returns the
    report."""
    folder = Path(out) / subset
    folder.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    by_kind: dict[str, list[str]] = defaultdict(list)
    for package in results:
        for staff in package.staffs:
            if not staff.accepted or staff.rows is None or staff.image is None:
                continue
            base = folder / f"{package.name}__porte{staff.entry['porte']:03d}"
            cv2.imwrite(str(base) + ".png", staff.image)
            Path(str(base) + ".tokens").write_text("\n".join(row_texts(staff.rows)) + "\n", encoding="utf-8")
            staff.sample = base.name
            lines.append(f"{_index_path(Path(str(base) + '.png'))},{_index_path(Path(str(base) + '.tokens'))}\n")
            by_kind[package.manifest.get("tur") or "bilinmiyor"].append(lines[-1])
    Path(out, f"index_{subset}.txt").write_text("".join(lines), encoding="utf-8")
    for kind, kind_lines in by_kind.items():
        Path(out, f"index_{subset}_{kind}.txt").write_text("".join(kind_lines), encoding="utf-8")
    reasons: Counter = Counter()
    for package in results:
        for staff in package.staffs:
            reasons.update({r["neden"] for r in staff.reasons})
    staffs = [s for p in results for s in p.staffs]
    report = {
        "bicim": FORMAT,
        "ayarlar": {"olcuMaskele": options.mask_measures, "yalnizNot": options.notes_only},
        "ozet": {
            "paket": len(results),
            "porte": len(staffs),
            "kabul": sum(1 for s in staffs if s.accepted),
            "red": sum(1 for s in staffs if not s.accepted),
            "nedenler": dict(sorted(reasons.items())),
            "maskelenenOlcu": sum(len(s.masked) for s in staffs if s.accepted),
            "gidisDonusTamam": sum(1 for s in staffs if s.round_trip == "tamam"),
        },
        "reddedilenPaketler": refused or [],
        "paketler": [p.report() for p in results],
    }
    Path(out, "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return report


def read_packages(paths: list[str], options: Options, refused: list[str] | None = None) -> list[PackageResult]:
    """Every correction of the given packages. A package this reader does not read raises PackageError, or, when
    refused is a list, is told there and left out, so that one bad folder does not stop a whole export. Of several
    corrections of one uploaded file (the same SHA-256: a later export carries the version the user saved since,
    under a new anonimKimlik) only the newest is taken."""
    results = []
    for path in paths:
        try:
            packages = load_packages(path)
        except (PackageError, zipfile.BadZipFile, json.JSONDecodeError) as error:
            if refused is None:
                raise
            refused.append(str(error))
            continue
        for package in packages:
            try:
                results.append(process_package(package, options))
            except (PackageError, json.JSONDecodeError, UnicodeDecodeError) as error:
                if refused is None:
                    raise
                refused.append(f"{package.name}: {error}" if not str(error).startswith(package.name) else str(error))

    def sha(result: PackageResult) -> str | None:
        return (result.manifest.get("orijinal") or {}).get("sha256")

    # anonimYukleme names the upload, the same in every correction version of it; a package from before the field
    # joins the upload whose file has its SHA-256, when only one upload has that file
    uploads_of: dict[str, set[str]] = defaultdict(set)
    for result in results:
        if result.manifest.get("anonimYukleme") and sha(result):
            uploads_of[sha(result) or ""].add(result.manifest["anonimYukleme"])

    def upload(result: PackageResult) -> str | None:
        if result.manifest.get("anonimYukleme"):
            return "yukleme:" + result.manifest["anonimYukleme"]
        known = uploads_of.get(sha(result) or "", set())
        if len(known) == 1:
            return "yukleme:" + next(iter(known))
        file = sha(result)
        return "sha256:" + file if file else None

    def age(result: PackageResult, key: str) -> tuple:
        # the versions of one upload are numbered; between uploads of one file only the day tells
        version = int(result.manifest.get("surum") or 0)
        day = str(result.manifest.get("tarih") or "")
        return (version, day) if key.startswith("yukleme:") else (day, version)

    newest: dict[str, PackageResult] = {}
    for result in results:
        key = upload(result)
        if key and (key not in newest or age(result, key) > age(newest[key], key)):
            newest[key] = result
    for result in results:
        key = upload(result)
        if key and newest[key] is not result:
            what = "yüklemenin" if key.startswith("yukleme:") else "dosyanın"
            result.warnings.append(f"aynı {what} daha yeni düzeltmesi var: {newest[key].name}")
            for staff in result.staffs:
                staff.reject("yinelenen", f"aynı {what} daha yeni düzeltmesi: {newest[key].name}")
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Musiki Akademisi düzeltme paketlerinden AEU-OMR eğitim verisi")
    parser.add_argument("paketler", nargs="+", help="paket: zip ya da açılmış klasör")
    parser.add_argument("--cikti", required=True, help="veri seti klasörü (index_<ad>.txt ve rapor.json buraya)")
    parser.add_argument("--ad", default="train", help="örneklerin alt klasörü ve dizin adı (index_<ad>.txt)")
    parser.add_argument("--olcu-maskele", action="store_true",
                        help="bakılmamış ölçüleri maskeleyip portenin kalanını al (temel modelin portelerinde değil)")
    parser.add_argument("--yalniz-not", action="store_true",
                        help="düzeltilen ölçü yalnız notasına dokunulduysa denetlenmiş sayılır")
    args = parser.parse_args(argv)
    out = Path(args.cikti).resolve()
    if out == git_root or git_root in out.parents:
        # Talha's decision: what comes from the app is kept for some later use, apart from our training data, which
        # the repository's datasets/ holds (the vocabulary build alone reads every .tokens there)
        parser.error(f"--cikti depo içinde olamaz ({out}): uygulamadan gelen düzeltmeler bizim veriye karışmaz, "
                     "depo dışında ayrı klasörde saklanır (OKU_BENI.md)")
    options = Options(mask_measures=args.olcu_maskele, notes_only=args.yalniz_not)
    refused: list[str] = []
    results = read_packages(args.paketler, options, refused)
    for message in refused:
        eprint(f"Paket okunamadı: {message}")
    report = write_dataset(results, args.cikti, args.ad, options, refused)
    summary = report["ozet"]
    eprint(f"{summary['paket']} paket, {summary['porte']} porte: {summary['kabul']} alındı, {summary['red']} alınmadı "
           f"({', '.join(f'{k} {v}' for k, v in summary['nedenler'].items()) or 'neden yok'}); "
           f"maskelenen ölçü {summary['maskelenenOlcu']}")
    return 2 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
