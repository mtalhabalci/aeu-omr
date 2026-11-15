"""Lyric layer: the lyrics of works already read, without reading their notes again.

A reading's notes stay as they are (its MusicXML, and the corrections made on it, keep their sha256). For each page
the staffs are found again (segmentation and staff detection only, no transformer: the staff finding gives the same
staffs as when the work was read), matched to the reading's staffs by their boxes, and the lyric band under each is
read (the text layer of a digital page, OCR on a scan: homr/lyrics.py). The syllables are given to the reading's notes
as the service gives them, and written as a layer: for each syllable its measure, its note's place in the measure
(from 0, among all the measure's <note> elements: rests and grace notes count), its verse, its text and its
recognition score. With each measure that has lyrics, the number of its notes, so that a MusicXML corrected since
(its notes changed) takes the layer only where the measure's notes are as many as in the reading.

    python -m servis.soz_katmani <out> <parti folder>... [--parca i/n] [--gpu] [--hepsi] [--dusuk]

A parti folder holds okuma/<id>.json (the service's answer, under 'okuma'), okuma/<id>.musicxml and pdf/<id>.pdf; the
layer goes to <out>/<id>.json (one already there is left). --parca i/n takes every n-th work from the i-th (from 0),
for runs side by side. The works of an instrumental form (peşrev, saz semaisi...: the reading's 'form') are left out,
unless --hepsi. --dusuk runs the process at below-normal priority (Windows), so that the machine stays responsive.
"""

import glob
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time

import cv2
import fitz

from homr.autocrop import autocrop_box
from homr.lyrics import StaffLyrics, add_lyrics, lyric_bands, ocr_words, staff_lyrics, text_layer_words
from homr.main import ProcessingConfig, detect_staffs_in_image
from servis.nota_servisi import PAGE_WIDTH, lyrics_summary, scanned

# forms without lyrics
INSTRUMENTAL = {"Peşrev", "Saz Semaisi", "Saz Eseri", "Sirto", "Medhal", "Longa", "Oyun Havası", "Taksim", "Etüd",
                "Saz Semâisi", "Peşrevi", "Fasıl Peşrevi", "Mandıra"}
_MEASURE = re.compile(r'<measure number="(\d+)"[^>]*>(.*?)</measure>', re.S)


def _staffs(image: str, processing: ProcessingConfig, pixels) -> list[tuple[list[int], list[tuple[float, int]]]]:  # noqa: ANN001
    """The page's staffs, top to bottom: each its box and its noteheads (x, place on the staff) in the page's
    pixels, as the service computes them."""
    multi_staffs, preprocessed, _, _ = detect_staffs_in_image(image, processing, merge_grand_staffs=False)
    height, width = pixels.shape[:2]
    box = autocrop_box(pixels) or (0, 0, width, height)
    scale_x, scale_y = box[2] / preprocessed.shape[1], box[3] / preprocessed.shape[0]
    found = sorted((s for multi in multi_staffs for s in multi.staffs), key=lambda s: s.min_y)
    return [([round(box[0] + s.min_x * scale_x), round(box[1] + s.min_y * scale_y),
              round(box[0] + s.max_x * scale_x), round(box[1] + s.max_y * scale_y)],
             [(box[0] + n.center[0] * scale_x, n.position) for n in s.get_notes()]) for s in found]


def _match(stored: list[int], found: list[tuple[list[int], list]]) -> list | None:
    """The noteheads of the found staff that is the reading's staff (its box within half a staff height)."""
    h = stored[3] - stored[1]
    best = min(found, key=lambda f: abs(f[0][1] - stored[1]) + abs(f[0][3] - stored[3]), default=None)
    if best is None or abs(best[0][1] - stored[1]) + abs(best[0][3] - stored[3]) > 0.5 * h:
        return None
    return best[1]


def layer(pdf: str, answer: dict, musicxml: str, processing: ProcessingConfig, ocr: bool = True) -> dict:
    """The lyric layer of one work (answer: the service's answer it was read with)."""
    porteler = answer["porteler"]
    heads: list[list] = []
    lyrics: list[StaffLyrics] = []
    boxes: list[tuple] = []
    measures: list[tuple[int, int]] = []
    sources: set[str] = set()
    unmatched = 0
    with tempfile.TemporaryDirectory() as scratch, fitz.open(pdf) as document:
        for page_no in sorted({p["sayfa"] for p in porteler}):
            stored = [p for p in porteler if p["sayfa"] == page_no]
            page = document[page_no - 1]
            zoom = PAGE_WIDTH / page.rect.width
            image = os.path.join(scratch, f"sayfa-{page_no}.png")
            page.get_pixmap(matrix=fitz.Matrix(zoom, zoom)).save(image)
            pixels = cv2.imread(image)
            gray = cv2.cvtColor(pixels, cv2.COLOR_BGR2GRAY)
            try:
                found = _staffs(image, processing, pixels)
            except Exception:  # noqa: BLE001
                found = []
            page_boxes = [tuple(p["kutu"]) for p in stored]
            words = [] if scanned(page) else text_layer_words(pdf, page_no, zoom)
            kind = "katman"
            if not words and ocr:
                words = ocr_words(gray, lyric_bands(page_boxes, gray.shape[0]))
                kind = "ocr"
            page_lyrics = staff_lyrics(words, page_boxes, gray.shape[0])
            if any(s.lines for s in page_lyrics):
                sources.add(kind)
            for p, staff_lyrics_ in zip(stored, page_lyrics, strict=True):
                matched = _match(p["kutu"], found)
                if matched is None:
                    unmatched += 1
                    staff_lyrics_ = StaffLyrics()
                heads.append(matched or [])
                lyrics.append(staff_lyrics_)
                boxes.append(tuple(p["kutu"]))
                measures.append((p["olcuBas"], p["olcuSon"]) if p["olcuBas"] is not None else (1, 0))
    _, record = add_lyrics(musicxml, measures, heads, lyrics, boxes)
    written = [r for r in record if r["olcu"] is not None]
    counts = {int(m.group(1)): m.group(2).count("<note") for m in _MEASURE.finditer(musicxml)}
    return {"soz": lyrics_summary(record, set(sources), None), "eslesmeyenPorte": unmatched,
            "heceler": [{"olcu": r["olcu"], "nota": r["nota"], "kita": r["kita"], "hece": r["hece"],
                         "guven": r["guven"]} for r in written],
            "olcuNotaSayisi": {str(m): counts[m] for m in sorted({r["olcu"] for r in written}) if m in counts}}


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True,
                              cwd=os.path.dirname(os.path.abspath(__file__)), check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def main() -> None:
    args = sys.argv[1:]
    part, parts, gpu = 0, 1, False
    if "--parca" in args:
        i = args.index("--parca")
        part, parts = map(int, args[i + 1].split("/"))
        del args[i:i + 2]
    if "--gpu" in args:
        gpu = True
        args.remove("--gpu")
    if "--dusuk" in args:
        args.remove("--dusuk")
        if os.name == "nt":
            import ctypes  # noqa: PLC0415

            ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
        else:
            os.nice(10)
    everything = "--hepsi" in args
    if everything:
        args.remove("--hepsi")
    out, folders = args[0], args[1:]
    os.makedirs(out, exist_ok=True)
    processing = ProcessingConfig(False, False, False, False, -1, gpu)
    works = sorted(f for folder in folders for f in glob.glob(os.path.join(folder, "okuma", "*.json")))
    works = works[part::parts]
    commit = _commit()
    done = 0
    start = time.perf_counter()
    for f in works:
        gid = os.path.basename(f)[:-5]
        target = os.path.join(out, gid + ".json")
        if os.path.exists(target):
            try:
                if "hata" not in json.load(open(target, encoding="utf-8")):
                    continue  # done; a work that failed (memory, a broken page) is tried again
            except ValueError:
                pass
        folder = os.path.dirname(os.path.dirname(f))
        xml_path, pdf = f[:-5] + ".musicxml", os.path.join(folder, "pdf", gid + ".pdf")
        if not (os.path.exists(xml_path) and os.path.exists(pdf)):
            continue
        wrapper = json.load(open(f, encoding="utf-8"))
        if not everything and wrapper.get("form") in INSTRUMENTAL:
            continue
        answer = wrapper.get("okuma", wrapper)
        if not answer or not answer.get("porteler"):
            continue
        raw = open(xml_path, "rb").read()
        t = time.perf_counter()
        try:
            result = layer(pdf, answer, raw.decode("utf-8"), processing)
        except Exception as e:  # noqa: BLE001
            result = {"hata": f"{type(e).__name__}: {e}"}
        result = {"id": gid, "okumaSha256": hashlib.sha256(raw).hexdigest(), "kod": commit,
                  "sureSn": round(time.perf_counter() - t, 1), **result}
        with open(target + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(result, fh, ensure_ascii=False)
        os.replace(target + ".tmp", target)
        done += 1
        if done % 25 == 0:
            rate = (time.perf_counter() - start) / done
            print(f"{done}/{len(works)} eser, {rate:.1f} sn/eser", flush=True)
    print(f"bitti: {done} eser, {time.perf_counter() - start:.0f} sn", flush=True)


if __name__ == "__main__":
    main()
