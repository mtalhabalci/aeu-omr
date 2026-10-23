"""Labels for the title block of a score page, read from the Mus2 PDFs of SymbTr.

A Mus2 page prints its title block as text: the work's name (largest, centred), the makam and form line under it,
"Beste:" and "Güfte:" on the right, "Usul:" and the tempo (a note glyph, the beats per minute and the duration of the
piece) on the left. The PDF's text layer gives every field's words and box, so the labels need no hand work. The
SymbTr file name (makam--form--usul--name--composer) is a second source for makam, form and usul and is used to check
the fields read from the page.

Some PDFs set a few Turkish letters through another code (Ş as "ù", ş as "ú", ğ as "÷", İ as "ø"); those are mapped
back here. About a third of the PDFs embed their text fonts as re-indexed CID subsets with no Unicode table: their text
reads as control characters. Their lines keep their boxes, makam, form and usul come from the file name, and the row
is marked "kodlu" (decoding them, by matching the glyphs against the system fonts, is left for later).

    python training/baslik/etiket_mus2.py   ->  datasets/baslik/mus2_etiketler.jsonl and a summary
"""
import json
import os
import re
import unicodedata
import sys
from collections import Counter

import pymupdf

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, root)
from training.datasets.convert_symbtr import _staff_lines  # noqa: E402

DATA = os.environ.get("SYMBTR_ROOT", r"C:\projects\yl\homr\datasets")
PDFS = os.path.join(DATA, "SymbTr-2.0.0", "pdf")
TEST_INDEX = os.path.join(DATA, "SymbTr-2.0.0", "index_test_SymbTr-work-v4.txt")
OUT = os.path.join(root, "datasets", "baslik")

FIX = str.maketrans({"ù": "Ş", "ú": "ş", "÷": "ğ", "ø": "İ", "´": "'", "": "", "": " "})
FOLD = str.maketrans("çğıöşüâîûÇĞİIÖŞÜÂÎÛ", "cgiosuaiucgiiosuaiu")
LABELS = {"beste": "bestekar", "güfte": "gufte", "usul": "usul", "usûl": "usul", "usûlü": "usul", "usulü": "usul"}


def fold(text: str) -> str:
    """ASCII form of a Turkish name, as the SymbTr file names spell it: Bûselikaşîrân -> buselikasiran. Accents and
    the comma letters OCR sometimes reads for ş (ș) are dropped by Unicode decomposition."""
    text = unicodedata.normalize("NFKD", text.replace("ı", "i").replace("İ", "I"))
    return re.sub(r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c)).lower())


def lines_of(spans: list[dict]) -> list[dict]:
    """Spans on one baseline and close together become a line: its words, box and largest size."""
    lines: list[dict] = []
    for s in sorted(spans, key=lambda s: (round(s["origin"][1]), s["bbox"][0])):
        for line in lines:
            near = abs(line["base"] - s["origin"][1]) < 4 and -2 < s["bbox"][0] - line["bbox"][2] < 30
            if near:
                line["parts"].append(s)
                line["bbox"] = [min(line["bbox"][0], s["bbox"][0]), min(line["bbox"][1], s["bbox"][1]),
                                max(line["bbox"][2], s["bbox"][2]), max(line["bbox"][3], s["bbox"][3])]
                line["size"] = max(line["size"], s["size"])
                break
        else:
            lines.append({"base": s["origin"][1], "parts": [s], "bbox": list(s["bbox"]), "size": s["size"]})
    for line in lines:
        line["text"] = re.sub(r"\s+", " ", "".join(p["text"] for p in line["parts"]).translate(FIX)).strip()
    return [line for line in lines if line["text"]]


def read_header(path: str, makam_slug: str | None = None) -> dict:
    page = pymupdf.open(path)[0]
    staffs = _staff_lines(page)
    spans = [s for b in page.get_text("dict")["blocks"] for l in b.get("lines", []) for s in l["spans"]
             if s["text"].strip()]
    music = [s for s in spans if s["font"].startswith("Mus2")]
    # the title block ends at the first staff; without vector staff lines, at the first big music glyph below it
    if staffs:
        bottom = staffs[0][0] - 4
    else:
        tops = sorted(s["bbox"][1] for s in music if s["bbox"][1] > 80)
        bottom = tops[0] - 4 if tops else page.rect.height * 0.2
    head = [s for s in spans if s["bbox"][3] <= bottom]
    fields: dict = {}
    boxes: dict = {}
    centre = page.rect.width / 2
    free = []
    for line in lines_of(head):
        text = line["text"]
        label = re.match(r"^(\w+)\s*:\s*(.*)$", text)
        if label and label.group(1).lower() in LABELS:
            name = LABELS[label.group(1).lower()]
            value = label.group(2).strip()
            if name in ("bestekar", "gufte"):
                dates = re.search(r"\(([^()]*\d[^()]*)\)\s*$", value)
                if dates:
                    fields["yasam" if name == "bestekar" else "gufte_yasam"] = dates.group(1).strip()
                    value = value[:dates.start()].strip()
            if value and value not in ('"', "?", "-"):
                fields[name] = value
                boxes[name] = [round(v, 1) for v in line["bbox"]]
            continue
        if any(p["font"].startswith("Mus2") for p in line["parts"]) or re.search(r"\d+\s*(Dk|Sn)\b", text):
            bpm = re.search(r"(?<![\d/])(\d{2,3})(?![\d/])", text)
            length = re.search(r"((\d+\s*Dk\s*)?\d+\s*Sn|\d+\s*Dk)", text)
            if bpm:
                fields["tempo"] = int(bpm.group(1))
                boxes["tempo"] = [round(v, 1) for v in line["bbox"]]
            if length:
                fields["sure"] = re.sub(r"\s+", " ", length.group(1)).strip()
            continue
        free.append(line)
    # the centred lines: the largest is the work's name; the makam and form line is found by the makam's name
    # (an instrumental work's name is that line itself: "Rast Peşrev", "Eviç Aranağme (Sofyan)")
    centred = sorted((l for l in free if abs((l["bbox"][0] + l["bbox"][2]) / 2 - centre) < page.rect.width * 0.2),
                     key=lambda l: (-l["size"], l["bbox"][1]))
    if centred:
        fields["eser_adi"] = centred[0]["text"]
        boxes["eser_adi"] = [round(v, 1) for v in centred[0]["bbox"]]
    used = centred[:1]
    if makam_slug is not None:
        for line in sorted(centred, key=lambda l: l["bbox"][1]):
            if fold(line["text"]).startswith(fold(makam_slug)):
                fields["makam_form"] = line["text"]
                boxes["makam_form"] = [round(v, 1) for v in line["bbox"]]
                used.append(line)
                break
    rest = [l["text"] for l in free if l not in used]
    coded = any(sum(ord(c) < 32 for c in t) > len(t) * 0.3
                for t in [l["text"] for l in free] + [str(v) for v in fields.values()] if t)
    row = {"fields": fields, "boxes": boxes, "rest": rest, "page": [round(page.rect.width, 1),
                                                                    round(page.rect.height, 1)],
           "header_bottom": round(bottom, 1), "staff_lines": bool(staffs), "kodlu": coded}
    if coded:  # the words cannot be read; keep where the lines are
        row["fields"], row["boxes"] = {}, {}
        row["lines"] = [{"bbox": [round(v, 1) for v in l["bbox"]], "size": round(l["size"], 1)}
                        for l in lines_of(head)]
        row["rest"] = []
    return row


def split_makam_form(line: str, makam_slug: str, form_slug: str) -> tuple[str | None, str | None]:
    """'Bûselikaşîrân Küpe' -> ('Bûselikaşîrân', 'Küpe'), using the file name's slugs to find the cut."""
    line = re.sub(r"\s*\([^()]*\)\s*$", "", line).strip()  # "Eviç Aranağme (Sofyan)": the usul in brackets
    words = line.split()
    makam_slug = fold(makam_slug)
    for cut in range(1, len(words)):
        if fold(" ".join(words[:cut])) == makam_slug:
            return " ".join(words[:cut]), " ".join(words[cut:]) or None
    if fold(line) == makam_slug:
        return line, None
    return None, None


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    test_works = {os.path.basename(l.split(",")[0]).rsplit("-", 1)[0] for l in open(TEST_INDEX, encoding="utf-8")}
    stats: Counter = Counter()
    with open(os.path.join(OUT, "mus2_etiketler.jsonl"), "w", encoding="utf-8") as out:
        for name in sorted(os.listdir(PDFS)):
            work = name[:-4]
            parts = work.split("--")
            makam_slug, form_slug, usul_slug = parts[0], parts[1], parts[2]
            try:
                header = read_header(os.path.join(PDFS, name), makam_slug)
            except Exception as error:  # noqa: BLE001
                stats["okunamadı"] += 1
                print("okunamadı:", name, error)
                continue
            f = header["fields"]
            if "usul" in f:  # "Devrikebîr (28/4)": the time signature in brackets is kept apart
                meter = re.search(r"\((\d+/\d+)\)", f["usul"])
                if meter:
                    f["usul_olcu"] = meter.group(1)
                    f["usul"] = re.sub(r"\s*\(\d+/\d+\)", "", f["usul"]).strip()
            if "makam_form" in f:
                makam, form = split_makam_form(f["makam_form"], makam_slug, form_slug)
                if makam:
                    f["makam"], f["form"] = makam, form
            row = {"eser": work, "kume": "sinav" if work in test_works else "egitim",
                   "dosya_adi": {"makam": makam_slug, "form": form_slug, "usul": usul_slug}, **header}
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
            stats["eser"] += 1
            stats["sinav" if row["kume"] == "sinav" else "egitim"] += 1
            for key in ("eser_adi", "makam", "form", "usul", "bestekar", "gufte", "tempo", "sure"):
                stats["alan:" + key] += key in f
            stats["kodlu"] += header["kodlu"]
            stats["makam=ad"] += fold(f.get("makam", "")) == fold(makam_slug)
            stats["form=ad"] += fold(f.get("form") or "") == fold(form_slug)
            stats["usul=ad"] += fold(re.sub(r"\s+[IVX]+$", "", f.get("usul", ""))) == fold(usul_slug)
            stats["cizgisiz"] += not header["staff_lines"]
    for k, v in sorted(stats.items()):
        print(f"{k:14s} {v}")


if __name__ == "__main__":
    main()
