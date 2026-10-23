"""Measure the title-block reader on the SymbTr test works (the thesis's test split, never used for the name lists).

Each work's first page is rendered as the service renders a PDF (1920 px wide) and read above its first staff; the
fields are compared with the labels of etiket_mus2.py after folding (Bûselikaşîrân = buselikasiran). Works whose PDF
fonts are coded have makam, form and usul labels from their file names only. The OCR lines of every page are kept
(datasets/baslik/mus2_onbellek[_bozuk].json), so that a change in the rules is measured again in seconds.

    python training/baslik/degerlendir.py [--bozuk] [--yeniden]
        --bozuk: blur, noise and JPEG, as a photo or scan would; --yeniden: OCR every page anew
"""
import json
import os
import re
import sys
import time
from collections import Counter

import cv2
import numpy as np
import pymupdf

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, root)
sys.path.insert(0, here)
from etiket_mus2 import OUT, PDFS, fold  # noqa: E402

from homr.baslik_okuyucu import Item, _names, ocr_items, parse  # noqa: E402

FIELDS = ("eser_adi", "makam", "form", "usul", "bestekar", "gufte")


def degrade(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.6, 1.4))
    img = np.clip(img.astype(np.float32) + rng.normal(0, 8, img.shape), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(35, 70))])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def main() -> None:
    bad = "--bozuk" in sys.argv
    rng = np.random.default_rng(0)
    rows = [json.loads(l) for l in open(os.path.join(OUT, "mus2_etiketler.jsonl"), encoding="utf-8")]
    test = [r for r in rows if r["kume"] == "sinav"]
    stats = {k: Counter() for k in FIELDS}
    errors = []
    cache_path = os.path.join(OUT, "mus2_onbellek_bozuk.json" if bad else "mus2_onbellek.json")
    cache = json.load(open(cache_path, encoding="utf-8")) \
        if os.path.exists(cache_path) and "--yeniden" not in sys.argv else {}
    seconds = []
    for r in test:
        if r["eser"] not in cache:
            page = pymupdf.open(os.path.join(PDFS, r["eser"] + ".pdf"))[0]
            zoom = 1920 / page.rect.width
            pix = page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom))
            img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)[:, :, :3].copy()
            img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            if bad:
                img = degrade(img, rng)
            crop = img[: max(int((r["header_bottom"] + 4) * zoom) - 4, 0)]  # as read_header crops
            start = time.perf_counter()
            items = ocr_items(crop) if crop.shape[0] >= 20 else []
            cache[r["eser"]] = {"width": crop.shape[1], "ocr_s": round(time.perf_counter() - start, 2),
                                "items": [[i.text, [round(float(v), 1) for v in i.box], round(float(i.score), 4)]
                                          for i in items]}
        entry = cache[r["eser"]]
        seconds.append(entry["ocr_s"])
        got = parse([Item(t, b, sc) for t, b, sc in entry["items"]], entry["width"], _names()).fields
        want = dict(r["fields"])
        if r["kodlu"]:  # only what the file name says
            want = {k: r["dosya_adi"][k] for k in ("makam", "form", "usul")}
        for k in FIELDS:
            if k not in want and not (r["kodlu"] and k in ("eser_adi", "bestekar", "gufte")):
                stats[k]["etiket yok, okunan" if k in got else "etiket yok"] += 1
                continue
            if k not in want:
                continue
            w = re.sub(r"\s+[IVX]+$", "", str(want[k])) if k == "usul" else str(want[k])
            g = got.get(k)
            if g is None:
                stats[k]["bulunamadı"] += 1
                errors.append((r["eser"], k, w, None))
            elif fold(g) == fold(w) or (k == "usul" and fold(re.sub(r"\s+[IVX]+$", "", g)) == fold(w)):
                stats[k]["doğru"] += 1
            else:
                stats[k]["yanlış"] += 1
                errors.append((r["eser"], k, w, g))
    with open(cache_path, "w", encoding="utf-8") as handle:
        json.dump(cache, handle, ensure_ascii=False)
    print(("BOZUK " if bad else "TEMİZ ") + f"{len(test)} sınav eseri; OCR ortalama "
          f"{sum(seconds) / max(len(seconds), 1):.2f} s, en çok {max(seconds, default=0):.2f} s")
    for k in FIELDS:
        s = stats[k]
        n = s["doğru"] + s["yanlış"] + s["bulunamadı"]
        print(f"  {k:9s} doğru {s['doğru']:3d}/{n:3d} ({100 * s['doğru'] / max(n, 1):5.1f}%)  yanlış {s['yanlış']:2d}  "
              f"bulunamadı {s['bulunamadı']:2d}  | etiketi olmayan: {s['etiket yok']} (okunan {s['etiket yok, okunan']})")
    name = "hatalar_bozuk.txt" if bad else "hatalar.txt"
    with open(os.path.join(OUT, name), "w", encoding="utf-8") as f:
        for e in errors:
            f.write(" | ".join(str(x) for x in e) + "\n")
    print("hatalar:", os.path.join(OUT, name))


if __name__ == "__main__":
    main()
