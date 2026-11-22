"""Unpacks an archive of measurement inputs into the repository of the runtime.

    python -m training.olcum.ac /content/drive/MyDrive/homr_makam/tez_olcum/girdi/bakirkoy_exam.tar

Only regular files under datasets/ are taken: no absolute path, no "..", no link. A file just put on Drive shows
late in the runtime, so the archive is waited for (--bekle seconds, 900 by default).
"""

import argparse
import os
import sys
import tarfile
import time


def ac(arsiv: str, bekle: int) -> None:
    basla = time.time()
    while not os.path.exists(arsiv):
        if time.time() - basla > bekle:
            sys.exit(f"{arsiv} {bekle} saniyede gorunmedi")
        try:
            os.listdir(os.path.dirname(arsiv))  # makes Drive look again
        except OSError:
            pass
        time.sleep(15)
    boyut = -1
    while boyut != os.path.getsize(arsiv):  # still arriving
        boyut = os.path.getsize(arsiv)
        time.sleep(10)
    alinan = atlanan = 0
    with tarfile.open(arsiv) as t:
        for uye in t:
            ad = os.path.normpath(uye.name).replace("\\", "/")
            if not uye.isfile() or not ad.startswith("datasets/") or ".." in ad.split("/"):
                atlanan += 0 if uye.isdir() else 1
                continue
            uye.name = ad
            t.extract(uye, ".")
            alinan += 1
    print(f"{arsiv}: {boyut} bayt, {alinan} dosya acildi, {atlanan} atlandi ({round(time.time() - basla)} sn)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("arsiv", nargs="+")
    parser.add_argument("--bekle", type=int, default=900)
    options = parser.parse_args()
    for yol in options.arsiv:
        ac(yol, options.bekle)
