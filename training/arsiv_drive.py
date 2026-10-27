"""Pack the downloaded score archives (C:/projects/yl/siteler/<site>) onto Drive, one tar per site, so they can leave
the local disk and come back unchanged whenever a dataset is built again.

    python -m training.arsiv_drive [--site omarsiv ...]

For every site: <site>.tar (uncompressed: the content is PDFs and images) under homr_makam/siteler_arsiv/ on Drive,
written as <site>.tar.part and renamed when complete, with <site>.liste.tsv beside it (path, size, sha256 of every
file). The tar is read back from Drive and its members checked against the local tree, then the script waits until
Drive for desktop has uploaded it (no pending operation, the item known to the cloud with the tar's size) before the
next site, so its cache never holds more than one site. Nothing local is changed or removed. A site already packed
and checked (its .tar and liste.tsv there, the same files locally) is skipped."""

import argparse
import glob
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import tarfile
import tempfile
import time
from datetime import datetime

SITES = r"C:\projects\yl\siteler"
DRIVEFS = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Google", "DriveFS")
ORDER = ["bakirkoy", "sahaney", "atkosar", "erdincbal", "trt", "repertukul", "omarsiv"]
SUMMARY = "siteler_arsiv_ozet.json"
README_NAME = "OKU_BENI_siteler_arsiv.md"
README = r"""# İndirilen nota arşivleri (siteler)

Yerelde `C:\projects\yl\siteler\<site>` olan arşivlerin kopyası, site başına bir tar (sıkıştırmasız). Tar içindeki
yollar `<site>/...` ile başlar: açılınca yerel düzen birebir geri gelir ve `homr/datasets/*/_build` betikleri (sabit
yol `C:\projects\yl\siteler\<site>`) değişmeden çalışır.

- `<site>.tar`: arşivin kendisi
- `<site>.liste.tsv`: her dosyanın yolu, boyutu ve sha256'sı
- `siteler_arsiv_ozet.json`: site başına dosya sayısı, toplam bayt, tar boyutu ve sha256'sı, tarih

Geri açmak (yerel; Windows 10+ tar, Git Bash ya da PowerShell):

    tar -xf "G:\Drive'ım\homr_makam\siteler_arsiv\omarsiv.tar" -C C:\projects\yl\siteler

Colab:

    !mkdir -p /content/siteler && tar -xf /content/drive/MyDrive/homr_makam/siteler_arsiv/omarsiv.tar -C /content/siteler

Eğitim bu arşivleri doğrudan okumaz: eğitim paketleri (Drive'da hazır) bunlardan `homr/datasets` altında kurulur;
arşiv yalnız bir veri seti yeniden kurulacaksa gerekir. Paketleyen: `homr/training/arsiv_drive.py`.
Not: `homr_makam/siteler` (28.09) arşivlerin eski, eksik bir kopyasıdır; tam kopya burasıdır.
"""


def log(*args: object) -> None:
    print(datetime.now().strftime("%H:%M:%S"), *args, flush=True)


def drive_root() -> str:
    return [d for d in glob.glob("G:/Drive*") if os.path.isdir(d)][0]


def local_files(site: str) -> list[tuple[str, int]]:
    root = os.path.join(SITES, site)
    out = []
    for d, dirs, names in os.walk(root):
        dirs.sort()
        for n in sorted(names):
            p = os.path.join(d, n)
            out.append((os.path.relpath(p, SITES).replace(os.sep, "/"), os.path.getsize(p)))
    return out


class Hashing:
    """A file wrapper that hashes what passes through it."""

    def __init__(self, f):
        self.f, self.h = f, hashlib.sha256()

    def read(self, n=-1):
        b = self.f.read(n)
        self.h.update(b)
        return b

    def write(self, b):
        self.h.update(b)
        return self.f.write(b)


def pack(files: list[tuple[str, int]], target: str) -> tuple[str, list[str]]:
    part = target + ".part"
    lines = []
    with open(part, "wb") as raw:
        out = Hashing(raw)
        with tarfile.open(fileobj=out, mode="w|", format=tarfile.PAX_FORMAT) as tar:
            for rel, size in files:
                path = os.path.join(SITES, rel)
                info = tar.gettarinfo(path, arcname=rel)
                if info.size != size:
                    raise SystemExit(f"{rel}: size changed while packing")
                with open(path, "rb") as f:
                    src = Hashing(f)
                    tar.addfile(info, src)
                lines.append(f"{rel}\t{size}\t{src.h.hexdigest()}\n")
    os.replace(part, target)
    return out.h.hexdigest(), lines


def check_tar(target: str, files: list[tuple[str, int]]) -> None:
    want = dict(files)
    seen = {}
    with tarfile.open(target, mode="r:") as tar:
        for m in tar:
            if m.isfile():
                seen[m.name] = m.size
    if seen != want:
        missing = sorted(set(want) - set(seen))[:5]
        extra = sorted(set(seen) - set(want))[:5]
        diff = [k for k in want if k in seen and seen[k] != want[k]][:5]
        raise SystemExit(f"{target}: members differ (missing {missing}, extra {extra}, size {diff})")


def drive_state(title: str) -> tuple[int, list[tuple[str, int]]]:
    """Pending operations of Drive for desktop and the items titled so, from a copy of its metadata database."""
    db = glob.glob(os.path.join(DRIVEFS, "*", "metadata_sqlite_db"))[0]
    with tempfile.TemporaryDirectory() as tmp:
        for suffix in ("", "-wal"):
            if os.path.exists(db + suffix):
                shutil.copyfile(db + suffix, os.path.join(tmp, "m.db" + suffix))
        con = sqlite3.connect(os.path.join(tmp, "m.db"))
        ops = con.execute("select count(*) from operations").fetchone()[0]
        items = con.execute("select id, file_size from items where local_title = ? and trashed = 0",
                            (title,)).fetchall()
        con.close()
    return ops, items


def wait_uploaded(title: str, size: int, limit_h: float = 8.0) -> None:
    start = time.time()
    while True:
        ops, items = drive_state(title)
        done = [i for i, s in items if s == size and not i.startswith("local")]
        if ops == 0 and done:
            log(f"  Drive'a yüklendi: {title} ({size / 1e9:.2f} GB, kimlik {done[0]})")
            return
        if time.time() - start > limit_h * 3600:
            raise SystemExit(f"{title}: {limit_h} saatte yüklenmedi (bekleyen işlem {ops}, kayıt {items})")
        time.sleep(60)


def write_json(path: str, doc: dict) -> None:
    with open(path + ".part", "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=1)
    os.replace(path + ".part", path)


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--site", nargs="*", default=ORDER)
    a = ap.parse_args()
    dest = os.path.join(drive_root(), "homr_makam", "siteler_arsiv")
    os.makedirs(dest, exist_ok=True)
    summary_path = os.path.join(dest, SUMMARY)
    summary = json.load(open(summary_path, encoding="utf-8")) if os.path.exists(summary_path) else {}
    for site in a.site:
        files = local_files(site)
        target = os.path.join(dest, f"{site}.tar")
        listing = os.path.join(dest, f"{site}.liste.tsv")
        total = sum(s for _, s in files)
        prev = summary.get(site)
        if prev and os.path.exists(target) and os.path.exists(listing) and prev["dosya"] == len(files) \
                and prev["bayt"] == total:
            log(f"{site}: önceden paketlenmiş, atlandı")
            wait_uploaded(f"{site}.tar", os.path.getsize(target))
            continue
        log(f"{site}: {len(files)} dosya, {total / 1e9:.2f} GB paketleniyor")
        tar_sha, lines = pack(files, target)
        with open(listing + ".part", "w", encoding="utf-8", newline="\n") as f:
            f.write("yol\tbayt\tsha256\n")
            f.writelines(lines)
        os.replace(listing + ".part", listing)
        check_tar(target, files)
        size = os.path.getsize(target)
        log(f"  paket tamam ve denetlendi: {size / 1e9:.2f} GB, sha256 {tar_sha[:16]}...")
        summary[site] = {"dosya": len(files), "bayt": total, "tar_bayt": size, "tar_sha256": tar_sha,
                         "tarih": datetime.now().isoformat(timespec="seconds")}
        write_json(summary_path, summary)
        wait_uploaded(f"{site}.tar", size)
        wait_uploaded(f"{site}.liste.tsv", os.path.getsize(listing))
    readme = os.path.join(dest, README_NAME)
    with open(readme, "w", encoding="utf-8", newline="\n") as f:
        f.write(README)
    wait_uploaded(SUMMARY, os.path.getsize(summary_path))
    wait_uploaded(README_NAME, os.path.getsize(readme))
    log("bitti:", ", ".join(a.site))


if __name__ == "__main__":
    main()
