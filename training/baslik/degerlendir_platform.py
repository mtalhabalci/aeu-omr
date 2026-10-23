"""The title-block reader on other publishers' pages (the platform notes: notaarsivleri, Üsküdar, şarkılar-notalar;
neyzen.com is printed for a look only). Every page goes the service's way: the PDF page rendered 1920 px wide, the
staffs found by homr's segmentation, the block read above the first staff.

Two kinds of labels:
- the file names, after the SymbTr counterpart (makam--form--usul--…): makam, form and usul; noisy here, since a
  publisher often prints another form or usul than SymbTr gives the same work (a "Hüzzâm Şarkı" that SymbTr files
  as an ağır semâî);
- training/baslik/sayfa_etiketleri_<folder name>.json, when there is one (the test notes have it): every field as
  the page prints it, labelled by eye from the header crops.

The OCR lines and the staff top of every page are kept in onbellek.json, so that a change in the rules is measured
again in seconds; --yeniden reads every page anew, --onbellek scores the cached pages only.

    python training/baslik/degerlendir_platform.py [klasör] [--yeniden | --onbellek] [--ters]
        klasör: default the test notes, 4_platform_notalari/notalar (output datasets/baslik/platform);
        another folder writes to datasets/baslik/platform_<folder name>
"""
import json
import os
import re
import sys
import time
from collections import Counter

import cv2
import pymupdf

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, root)
os.chdir(root)
from homr.autocrop import autocrop_box  # noqa: E402
from homr.baslik_okuyucu import Item, distance, fold, ocr_items, parse, _names  # noqa: E402
from homr.main import ProcessingConfig, detect_staffs_in_image  # noqa: E402

BASE = os.environ.get("PLATFORM_NOTALARI", r"G:\Drive'ım\homr_makam\4_platform_notalari")
PAGE_WIDTH = 1920
NAME_FIELDS = ("makam", "form", "usul")
TEXT_FIELDS = ("eser_adi", "bestekar", "gufte", "kaynak")


def first_staff_top(image_path: str) -> int | None:
    """The page y of the first staff's top, found as the service finds staffs."""
    import homr.main as reader_main  # noqa: PLC0415

    reader_main.detect_title = lambda *_: None  # the title is ours to read
    config = ProcessingConfig(False, False, False, False, -1, False)
    multi, preprocessed, _, _ = detect_staffs_in_image(image_path, config)
    page = cv2.imread(image_path)
    h, w = page.shape[:2]
    box = autocrop_box(page) or (0, 0, w, h)
    scale_y = box[3] / preprocessed.shape[0]
    staffs = [s for m in multi for s in m.staffs]
    if not staffs:
        return None
    return round(box[1] + min(s.min_y for s in staffs) * scale_y)


def name_key(kind: str, value: str, names) -> str:
    """A name folded, after the list's aliases; a form with the possessive ending ("Isfahan Peşrevi") as the
    form itself."""
    key = names.canonical(kind, fold(re.sub(r"\s+[IVX]+$", "", value)))
    if kind == "form" and key not in names.forms:
        for cut in (1, 2):
            if key[-cut:] in ("i", "si") and names.canonical(kind, key[:-cut]) in names.forms:
                return names.canonical(kind, key[:-cut])
    return key


def name_match(kind: str, got: str | None, want: str, names) -> bool:
    """Fold-equal after the list's aliases; a compound form ending in the wanted one counts ("Nakış Beste")."""
    if got is None:
        return False
    g, w = name_key(kind, got, names), name_key(kind, want, names)
    return g == w or (kind == "form" and g.endswith(w))


def text_close(got: str, want: str) -> bool:
    """A free-text field read with a few letters off: at most a fifth of the letters, two at least."""
    g, w = fold(got), fold(want)
    return distance(g, w) <= max(2, len(w) // 5)


def page_verdict(kind: str, got: str | None, want: str | None, names) -> str:
    if want is None:
        return "yok" if got is None else "fazla"
    if got is None:
        return "bulunamadı"
    if kind in NAME_FIELDS:
        return "doğru" if name_match(kind, got, want, names) else "yanlış"
    if fold(got) == fold(want):
        return "doğru"
    return "yakın" if text_close(got, want) else "yanlış"


def _save(cache: dict, path: str) -> None:
    with open(path + ".tmp", "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False)
    os.replace(path + ".tmp", path)


def read_pages(folder: str, scratch: str, fresh: bool, backwards: bool = False) -> dict:
    """Every PDF's first page: the staff top, the OCR lines above it and the seconds both took (cached). A second
    run going backwards (--ters, into onbellek_ters.json) shares a long folder; main() merges the two."""
    cache_path = os.path.join(scratch, "onbellek_ters.json" if backwards else "onbellek.json")
    cache = {} if fresh or not os.path.exists(cache_path) else json.load(open(cache_path, encoding="utf-8"))
    other_path = os.path.join(scratch, "onbellek.json" if backwards else "onbellek_ters.json")
    done_there: dict = {}
    changed = 0
    for dirpath, _, files in os.walk(folder):
        for number, name in enumerate(sorted((f for f in files if f.endswith(".pdf")), reverse=backwards)):
            site = os.path.basename(dirpath)
            key = f"{site}/{name[:-4]}"
            if number % 10 == 0 and os.path.exists(other_path):  # the other run's pages are not read twice
                try:
                    done_there = json.load(open(other_path, encoding="utf-8"))
                except ValueError:
                    pass
            if key in cache or key in done_there:
                continue
            page = pymupdf.open(os.path.join(dirpath, name))[0]
            zoom = PAGE_WIDTH / page.rect.width
            stem = os.path.join(scratch, f"{site}--{name[:-4]}")
            image = f"{stem}.{os.getpid()}.png"  # a run of its own: two runs on one folder do not share the file
            page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom)).save(image)
            start = time.perf_counter()
            try:
                top = first_staff_top(image)
            except Exception:  # noqa: BLE001
                top = None
            img = cv2.imread(image)
            entry = {"top": top, "width": img.shape[1], "seg_s": round(time.perf_counter() - start, 2)}
            if top is not None and top - 4 >= 20:
                crop = img[: top - 4]
                start = time.perf_counter()
                items = ocr_items(crop)
                entry["ocr_s"] = round(time.perf_counter() - start, 2)
                entry["items"] = [[i.text, [round(float(v), 1) for v in i.box], round(float(i.score), 4)]
                                  for i in items]
                cv2.imwrite(stem + "_baslik.png", crop)
            os.remove(image)  # the header crop is what is looked at
            cache[key] = entry
            changed += 1
            if changed % 20 == 0:
                _save(cache, cache_path)
                print(f"  {len(cache)} sayfa", flush=True)
    if changed:
        _save(cache, cache_path)
    return cache


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    folder = args[0] if args else os.path.join(BASE, "notalar")
    base = os.path.basename(folder.rstrip("\\/"))
    scratch = os.path.join(root, "datasets", "baslik", "platform" if base == "notalar" else f"platform_{base}")
    os.makedirs(scratch, exist_ok=True)
    if "--onbellek" not in sys.argv:  # --onbellek: only the pages read before
        read_pages(folder, scratch, "--yeniden" in sys.argv, "--ters" in sys.argv)
    cache = {}
    for part in ("onbellek.json", "onbellek_ters.json"):
        if os.path.exists(os.path.join(scratch, part)):
            cache.update(json.load(open(os.path.join(scratch, part), encoding="utf-8")))
    labels_path = os.path.join(here, f"sayfa_etiketleri_{base}.json")
    labels = json.load(open(labels_path, encoding="utf-8"))["etiketler"] if os.path.exists(labels_path) else {}
    names = _names()
    by_name: dict = {k: Counter() for k in NAME_FIELDS}
    by_page: dict = {k: Counter() for k in NAME_FIELDS + TEXT_FIELDS}
    report, readings, ocr_times = [], {}, []
    for key in sorted(cache):
        entry = cache[key]
        if "items" not in entry:
            report.append(f"{key}: porte yok ya da başlık alanı yok (üst {entry['top']})")
            for k in NAME_FIELDS:
                by_name[k]["bulunamadı"] += 1
            continue
        ocr_times.append(entry["ocr_s"])
        items = [Item(t, b, s) for t, b, s in entry["items"]]
        fields = parse(items, entry["width"], names).fields
        readings[key] = fields
        line = [key]
        parts = key.split("/", 1)[1].split("--")
        if len(parts) >= 3:
            for k, want in zip(NAME_FIELDS, parts[:3]):
                got = fields.get(k)
                ok = name_match(k, got, want, names)
                by_name[k]["doğru" if ok else "bulunamadı" if got is None else "yanlış"] += 1
                line.append(f"{k}={got!r}{'' if ok else ' ✗ ad:' + want}")
        label = labels.get(key)
        if label:
            unreadable = set(label.get("okunaksiz", []))
            wrong = []
            for k in NAME_FIELDS + TEXT_FIELDS:
                if k in unreadable:
                    continue
                verdict = page_verdict(k, fields.get(k), label.get(k), names)
                by_page[k][verdict] += 1
                if verdict not in ("doğru", "yok"):
                    wrong.append(f"{k}: {verdict} okunan={fields.get(k)!r} sayfa={label.get(k)!r}")
            line += ["SAYFA " + w for w in wrong]
        line.append(f"eser={fields.get('eser_adi')!r} beste={fields.get('bestekar')!r} güfte={fields.get('gufte')!r} "
                    f"kaynak={fields.get('kaynak')!r}")
        line.append("OCR: " + " | ".join(i.text for i in items))
        report.append("\n    ".join(line))
    out = os.path.join(scratch, f"rapor_{base}.txt")
    open(out, "w", encoding="utf-8").write("\n".join(report) + "\n")
    with open(out[:-4] + "_okunan.json", "w", encoding="utf-8") as handle:
        json.dump(readings, handle, ensure_ascii=False, indent=1)
    print(f"{len(cache)} sayfa; başlık okunan {len(readings)}; OCR ortalama "
          f"{sum(ocr_times) / max(len(ocr_times), 1):.2f} s, en çok {max(ocr_times, default=0):.2f} s")
    print("dosya adına göre:")
    for k, s in by_name.items():
        n = sum(s.values())
        print(f"  {k:9s} doğru {s['doğru']:3d}/{n:3d} ({100 * s['doğru'] / max(n, 1):5.1f}%)  yanlış {s['yanlış']:3d}"
              f"  bulunamadı {s['bulunamadı']:3d}")
    if labels:
        print("sayfa etiketlerine göre (yok = basılmamış, okunmamış; fazla = basılmamış ama okunmuş):")
        for k, s in by_page.items():
            printed = s["doğru"] + s["yakın"] + s["yanlış"] + s["bulunamadı"]
            print(f"  {k:9s} doğru {s['doğru']:3d}/{printed:3d} ({100 * s['doğru'] / max(printed, 1):5.1f}%)"
                  + (f"  yakın {s['yakın']:2d}" if k in TEXT_FIELDS else "")
                  + f"  yanlış {s['yanlış']:2d}  bulunamadı {s['bulunamadı']:2d}  | yok {s['yok']:2d}  fazla {s['fazla']:2d}")
    print("rapor:", out)


if __name__ == "__main__":
    main()
