"""Reads a folder of pdfs page by page (training.read_page) on the runtime and packs what was read into one file.

    python -m training.olcum.sayfa_oku --ad tez_sayfa_atkosar_sarki --folder datasets/atkosar-real/exam/pdf/sarki \
        --checkpoint /content/modeller/model.pth

read_page writes a picture of every staff beside each reading; a page exam is hundreds of megabytes of them. They
stay on the disk of the runtime (/content/sayfa/<ad>) and only the records the scorers read, one .json per pdf and
summary.json, go into /content/olcum/<ad>.okuma.json, which the queue copies to Drive with the job's output:

    {"folder": ..., "checkpoint": ..., "records": {"<pdf stem>.json": {...}, "summary.json": {...}}}

The scoring (datasets/<x>-real/exam/score_<x>.py --score-only, local_score.py) is done on the other machine, with
the records written back as files.
"""

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys

from homr.segmentation.config import segnet_path_onnx

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--ad", required=True, help="The job's name: the packed file is <cikti>/<ad>.okuma.json.")
    parser.add_argument("--folder", required=True, help="Folder of pdfs to read.")
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--cikti", default="/content/olcum")
    parser.add_argument("--calisma", default="/content/sayfa", help="Where the readings and staff pictures stay.")
    parser.add_argument("--segnet", default="/content/drive/MyDrive/homr_makam",
                        help="Folder that holds homr's segmentation model, copied in when the repository lacks it.")
    options = parser.parse_args()
    if not options.ad.replace("_", "").replace("-", "").isalnum():
        sys.exit("ad gecersiz")
    # read_page finds the staffs with homr's segmentation model, which is not in the repository; Drive has it.
    if not os.path.exists(segnet_path_onnx):
        kaynak = os.path.join(options.segnet, os.path.basename(segnet_path_onnx))
        if not os.path.exists(kaynak):
            sys.exit(f"porte bulma modeli yok: {kaynak}")
        shutil.copy(kaynak, segnet_path_onnx)
        print("porte bulma modeli Drive dan alindi", flush=True)
    pdfler = sorted(glob.glob(os.path.join(options.folder, "*.pdf")))
    print(f"{options.folder}: {len(pdfler)} pdf", flush=True)
    if not pdfler:
        sys.exit("okunacak pdf yok")
    out = os.path.join(options.calisma, options.ad)
    os.makedirs(out, exist_ok=True)
    # Through dongu_say, which leaves the reading as it is and prints how often each decoding rule acted in it.
    kod = subprocess.run([sys.executable, "-m", "training.olcum.dongu_say", "training.read_page", "--folder",
                          options.folder, "--checkpoint", options.checkpoint, "--out", out], check=False).returncode
    records = {}
    for yol in sorted(glob.glob(os.path.join(out, "*.json"))):
        with open(yol, encoding="utf-8") as dosya:
            records[os.path.basename(yol)] = json.load(dosya)
    okunan = len([ad for ad in records if ad != "summary.json"])
    paket = os.path.join(options.cikti, options.ad + ".okuma.json")
    with open(paket, "w", encoding="utf-8") as dosya:
        json.dump({"folder": options.folder, "checkpoint": os.path.basename(options.checkpoint), "records": records},
                  dosya, ensure_ascii=False)
    print(f"read_page cikis kodu {kod}; {okunan}/{len(pdfler)} pdf okundu; {paket} {os.path.getsize(paket)} bayt")
    if kod != 0 or okunan < len(pdfler):
        sys.exit(kod or 3)
