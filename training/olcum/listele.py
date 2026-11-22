"""What a folder of the runtime holds, for the machine the measurements are driven from.

    python -m training.olcum.listele datasets datasets/bakirkoy-vector/index_exam.txt

A folder is listed entry by entry with sizes (a subfolder with the number of its entries); a text file is given with
its number of lines and its first two lines. Reads only.
"""

import os
import sys


def listele(yol: str, en_cok: int = 400) -> None:
    if os.path.isdir(yol):
        girdiler = sorted(os.listdir(yol))
        print(f"== {yol}: {len(girdiler)} girdi")
        for ad in girdiler[:en_cok]:
            tam = os.path.join(yol, ad)
            if os.path.isdir(tam):
                try:
                    print(f"   [klasor {len(os.listdir(tam)):>7}]  {ad}")
                except OSError as hata:
                    print(f"   [klasor okunamadi: {hata}]  {ad}")
            else:
                print(f"   {os.path.getsize(tam):>16}  {ad}")
        if len(girdiler) > en_cok:
            print(f"   ... {len(girdiler) - en_cok} girdi daha")
    elif os.path.isfile(yol):
        boyut = os.path.getsize(yol)
        print(f"== {yol}: {boyut} bayt")
        if yol.endswith((".txt", ".json", ".tsv", ".csv")) and boyut < 200_000_000:
            with open(yol, encoding="utf-8", errors="replace") as dosya:
                satirlar = dosya.readlines()
            print(f"   {len(satirlar)} satir")
            for satir in satirlar[:2]:
                print("   | " + satir.rstrip()[:300])
    else:
        print(f"== {yol}: YOK")


if __name__ == "__main__":
    for arguman in sys.argv[1:]:
        listele(arguman)
