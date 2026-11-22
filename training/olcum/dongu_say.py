"""Runs a measurement and counts how often each decoding rule acted in it.

    python -m training.olcum.dongu_say training.evaluate_makam --checkpoint ... --index ... --clean --generate
    python -m training.olcum.dongu_say training.read_page --folder ... --checkpoint ... --out ...

The measurement itself is untouched: the three rules of homr.transformer.vocabulary are called as before and their
answers passed on. The last line printed is the count,

    KURAL SAYIMI {"okuma": staffs read, "dongu": readings the loop breaker stopped,
                  "porte_basi_usul": 64th rests at the opening of a staff replaced by a time signature,
                  "olcu_duzeltme_porte": staffs the measure fix changed, "olcu_duzeltme_sembol": symbols it changed}

A rule turned off by its switch (HOMR_NO_METER_FIX, HOMR_MEASURE_FIX) counts nothing; the loop breaker has none.
"""

import json
import runpy
import sys

IZINLI = ("training.evaluate_makam", "training.read_page")

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in IZINLI:  # noqa: PLR2004
        sys.exit("kullanim: python -m training.olcum.dongu_say <" + " | ".join(IZINLI) + "> [its arguments]")
    import training.architecture.transformer.decoder as decoder

    sayim = {"okuma": 0, "dongu": 0, "porte_basi_usul": 0, "olcu_duzeltme_porte": 0, "olcu_duzeltme_sembol": 0}
    dongu, porte_basi, olcu = decoder.ends_in_loop, decoder.misread_opening_meter, decoder.fix_measure_sums

    def dongu_sayan(symbols):  # noqa: ANN001, ANN202
        sonuc = dongu(symbols)
        sayim["dongu"] += bool(sonuc)
        return sonuc

    def porte_basi_sayan(symbols, rhythm):  # noqa: ANN001, ANN202
        sonuc = porte_basi(symbols, rhythm)
        sayim["porte_basi_usul"] += bool(sonuc)
        return sonuc

    def olcu_sayan(symbols, alternatives, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        sonuc = olcu(symbols, alternatives, *args, **kwargs)
        sayim["okuma"] += 1
        sayim["olcu_duzeltme_porte"] += bool(sonuc)
        sayim["olcu_duzeltme_sembol"] += int(sonuc or 0)
        return sonuc

    decoder.ends_in_loop, decoder.misread_opening_meter, decoder.fix_measure_sums = dongu_sayan, porte_basi_sayan, olcu_sayan
    modul = sys.argv[1]
    sys.argv = [modul, *sys.argv[2:]]
    try:
        runpy.run_module(modul, run_name="__main__", alter_sys=True)
    finally:
        print("KURAL SAYIMI " + json.dumps(sayim), flush=True)
