"""Brings the repository of the runtime to the head of the measurement branch, as a job of the queue.

    python -m training.olcum.guncelle

Jobs run one at a time, so nothing else reads the code while it changes; the next job runs the new code. The
datasets are untracked and stay as they are.
"""

import subprocess
import sys

DAL = "tez-olcum"

if __name__ == "__main__":
    for komut in (["git", "fetch", "-q", "--depth", "1", "origin", DAL],
                  ["git", "reset", "-q", "--hard", "FETCH_HEAD"],
                  ["git", "log", "--oneline", "-1"]):
        sonuc = subprocess.run(komut, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        print(" ".join(komut), "->", sonuc.returncode, (sonuc.stdout + sonuc.stderr).strip()[:300], flush=True)
        if sonuc.returncode != 0:
            sys.exit(sonuc.returncode)
