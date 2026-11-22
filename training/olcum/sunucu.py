"""A queue of measurement jobs behind a small HTTP door, for a Colab runtime whose measurements are driven from
another machine.

    OLCUM_ANAHTAR=<key> python -m training.olcum.sunucu --cikti /content/olcum --drive <folder on Drive>

A job is one run of a measurement module of this repository (python -m <module> <arguments>), its output written to
<cikti>/<name>.txt; jobs run one at a time, in the order they came. Nothing else can be run through the door: the
module must be one of IZINLI or lie under training/olcum/, an argument that is a path must stay inside the
repository or one of --kok, and only HOMR_* and OMR_* variables are passed on. Every request must carry the key in
the X-Anahtar header; without it the answer is 404.

    GET  /durum               what runs, what waits, what is done, seconds since the last request or job
    POST /is                  {"isler": [{"ad", "modul", "args", "env"}]} -> queued, or refused with the reason
    GET  /cikti?ad=<file>     a file of the output folder (son=<bytes> its end only, gz=1 gzipped)
    GET  /dosyalar            the output folder
    POST /iptal               {"ad"}: stop the running job or take a waiting one out
    POST /guncelle            git fetch and reset to the head of the branch, when nothing runs
    POST /kapat               ask the notebook to end (it saves to Drive and gives the runtime back)
"""

import argparse
import gzip
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

IZINLI = {"training.evaluate_makam", "training.read_page", "training.read_work"}
AD = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,99}$")
DOSYA = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,139}$")
MODUL = re.compile(r"^training(\.[a-z_][a-z0-9_]*)+$")
ORTAM = re.compile(r"^(HOMR|OMR)_[A-Z0-9_]{1,60}$")
DEGER = re.compile(r"^[A-Za-z0-9_.,:/\-]{0,200}$")
EN_COK_GOVDE = 1 << 20


def modul_izinli(modul: object, repo: str) -> str | None:
    """The reason a module may not be run, or None."""
    if not isinstance(modul, str) or not MODUL.match(modul):
        return "modul adi gecersiz"
    if modul == "training.olcum.sunucu":
        return "sunucu kendini calistirmaz"
    if modul not in IZINLI and not modul.startswith("training.olcum."):
        return "modul izinli degil"
    if not os.path.isfile(os.path.join(repo, *modul.split(".")) + ".py"):
        return "modul depoda yok"
    return None


def yol_izinli(arg: str, kokler: list[str]) -> bool:
    """A path among the arguments stays inside the repository or an allowed root. `--key=value` is checked on the
    value; an argument without a slash is no path."""
    deger = arg.split("=", 1)[1] if arg.startswith("--") and "=" in arg else arg
    if "\\" in deger:
        return False
    if "/" not in deger and not deger.startswith("."):
        return True
    if deger.startswith("/"):
        tam = os.path.normpath(deger).replace("\\", "/")
        return any(tam == kok or tam.startswith(kok.rstrip("/") + "/") for kok in kokler)
    return not os.path.normpath(deger).startswith("..")


def is_denetle(is_: object, repo: str, kokler: list[str]) -> tuple[dict | None, str | None]:
    """(the job as it will run, None) or (None, the reason it is refused)."""
    if not isinstance(is_, dict):
        return None, "is bir nesne degil"
    ad, modul, args, env = is_.get("ad"), is_.get("modul"), is_.get("args", []), is_.get("env", {})
    if not isinstance(ad, str) or not AD.match(ad):
        return None, "ad gecersiz"
    neden = modul_izinli(modul, repo)
    if neden:
        return None, neden
    if not isinstance(args, list) or len(args) > 80:
        return None, "args bir liste degil ya da cok uzun"
    for arg in args:
        if not isinstance(arg, str) or len(arg) > 1000 or any(ord(c) < 32 for c in arg):
            return None, "arguman gecersiz"
        if not yol_izinli(arg, kokler):
            return None, f"yol izinli degil: {arg}"
    if not isinstance(env, dict) or len(env) > 20:
        return None, "env bir sozluk degil"
    for k, v in env.items():
        if not isinstance(k, str) or not ORTAM.match(k) or not isinstance(v, str) or not DEGER.match(v):
            return None, f"ortam degiskeni izinli degil: {k}"
    return {"ad": ad, "modul": modul, "args": list(args), "env": dict(env)}, None


class Kuyruk:
    def __init__(self, repo: str, cikti: str, drive: str | None, kokler: list[str], dal: str) -> None:
        self.repo, self.cikti, self.drive, self.kokler, self.dal = repo, cikti, drive, kokler, dal
        self.kilit = threading.Lock()
        self.bekleyen: list[dict] = []
        self.calisan: dict | None = None
        self.surec: subprocess.Popen | None = None
        self.biten: list[dict] = []
        self.son_hareket = time.time()
        os.makedirs(cikti, exist_ok=True)
        if drive:
            os.makedirs(drive, exist_ok=True)
        threading.Thread(target=self._calis, daemon=True).start()

    def kafa(self) -> str:
        r = subprocess.run(["git", "log", "--oneline", "-1"], cwd=self.repo, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", check=False)
        return r.stdout.strip()[:120]

    def ekle(self, isler: list) -> dict:
        kabul, ret = [], []
        with self.kilit:
            adlar = {i["ad"] for i in self.bekleyen} | {i["ad"] for i in self.biten}
            if self.calisan:
                adlar.add(self.calisan["ad"])
            for ham in isler:
                is_, neden = is_denetle(ham, self.repo, self.kokler)
                if is_ and is_["ad"] in adlar:
                    is_, neden = None, "bu adla bir is var"
                if not is_:
                    ret.append({"ad": ham.get("ad") if isinstance(ham, dict) else None, "neden": neden})
                    continue
                adlar.add(is_["ad"])
                self.bekleyen.append(is_)
                kabul.append(is_["ad"])
            self.son_hareket = time.time()
        return {"kabul": kabul, "ret": ret}

    def iptal(self, ad: str) -> str:
        with self.kilit:
            for i, is_ in enumerate(self.bekleyen):
                if is_["ad"] == ad:
                    del self.bekleyen[i]
                    return "kuyruktan cikarildi"
            if self.calisan and self.calisan["ad"] == ad and self.surec:
                self.surec.terminate()
                return "durduruluyor"
        return "boyle bir is yok"

    def durum(self) -> dict:
        with self.kilit:
            calisan = None
            if self.calisan:
                calisan = {"ad": self.calisan["ad"], "sure": round(time.time() - self.calisan["basla"]),
                           "son": self._son(self.calisan["ad"] + ".txt", 400)}
            mesgul = bool(self.calisan or self.bekleyen)
            return {
                "calisan": calisan,
                "bekleyen": [i["ad"] for i in self.bekleyen],
                "biten": [{"ad": i["ad"], "kod": i["kod"], "sure": i["sure"], "drive": i["drive"]}
                          for i in self.biten],
                "bosta_sn": 0 if mesgul else round(time.time() - self.son_hareket),
            }

    def _son(self, dosya: str, n: int) -> str:
        try:
            with open(os.path.join(self.cikti, dosya), "rb") as f:
                f.seek(0, os.SEEK_END)
                f.seek(max(0, f.tell() - n))
                return f.read().decode("utf-8", "replace")
        except OSError:
            return ""

    def _calis(self) -> None:
        while True:
            with self.kilit:
                is_ = self.bekleyen.pop(0) if self.bekleyen else None
                if is_:
                    is_["basla"] = time.time()
                    self.calisan = is_
            if not is_:
                time.sleep(1)
                continue
            yol = os.path.join(self.cikti, is_["ad"] + ".txt")
            ortam = dict(os.environ)
            ortam.pop("OLCUM_ANAHTAR", None)
            ortam.update(is_["env"])
            ortam["PYTHONUNBUFFERED"] = "1"
            ortam["PYTHONIOENCODING"] = "utf-8"
            kod = -1
            try:
                with open(yol, "wb") as f:
                    bas = (f"# is     : python -m {is_['modul']} {' '.join(is_['args'])}\n"
                           f"# ortam  : {json.dumps(is_['env'], sort_keys=True)}\n"
                           f"# depo   : {self.kafa()}\n"
                           f"# basladi: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write(bas.encode("utf-8"))
                    f.flush()
                    self.surec = subprocess.Popen([sys.executable, "-m", is_["modul"], *is_["args"]], cwd=self.repo,
                                                  env=ortam, stdout=f, stderr=subprocess.STDOUT)
                    kod = self.surec.wait()
            except Exception as hata:  # noqa: BLE001 - the queue must go on
                with open(yol, "ab") as f:
                    f.write(f"\n# sunucu hatasi: {type(hata).__name__}: {hata}\n".encode())
            is_["kod"], is_["sure"] = kod, round(time.time() - is_["basla"])
            is_["drive"] = self._drive_a(is_["ad"])
            with self.kilit:
                self.surec, self.calisan = None, None
                self.biten.append(is_)
                self.son_hareket = time.time()

    def _drive_a(self, ad: str) -> str:
        """A job's files (<ad>.txt and whatever else it wrote as <ad>.<something>) are copied to Drive."""
        if not self.drive:
            return "drive yok"
        try:
            for dosya in os.listdir(self.cikti):
                if dosya.startswith(ad + "."):
                    shutil.copy2(os.path.join(self.cikti, dosya), os.path.join(self.drive, dosya))
            return "tamam"
        except OSError as hata:
            return f"{type(hata).__name__}: {hata}"

    def guncelle(self) -> tuple[int, dict]:
        with self.kilit:
            if self.calisan:
                return 409, {"hata": "bir is calisiyor"}
            self.son_hareket = time.time()
            adimlar = (["git", "fetch", "-q", "--depth", "1", "origin", self.dal],
                       ["git", "reset", "-q", "--hard", "FETCH_HEAD"])
            for komut in adimlar:
                r = subprocess.run(komut, cwd=self.repo, capture_output=True, text=True, encoding="utf-8",
                                   errors="replace", check=False)
                if r.returncode != 0:
                    return 500, {"hata": (r.stdout + r.stderr)[-800:]}
        return 200, {"kafa": self.kafa()}


def isleyici(kuyruk: Kuyruk, anahtar: str) -> type[BaseHTTPRequestHandler]:
    class Isleyici(BaseHTTPRequestHandler):
        server_version = "olcum/1"

        def log_message(self, *args: object) -> None:
            pass

        def _yaz(self, kod: int, govde: bytes, tur: str = "application/json; charset=utf-8") -> None:
            self.send_response(kod)
            self.send_header("Content-Type", tur)
            self.send_header("Content-Length", str(len(govde)))
            self.end_headers()
            self.wfile.write(govde)

        def _json(self, kod: int, veri: object) -> None:
            self._yaz(kod, json.dumps(veri, ensure_ascii=False).encode("utf-8"))

        def _yetkili(self) -> bool:
            verilen = self.headers.get("X-Anahtar", "")
            if hmac.compare_digest(verilen.encode("utf-8"), anahtar.encode("utf-8")):
                return True
            self._yaz(404, b"", "text/plain")
            return False

        def _govde(self) -> object:
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > EN_COK_GOVDE:
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except ValueError:
                return None

        def do_GET(self) -> None:  # noqa: N802
            if not self._yetkili():
                return
            u = urlparse(self.path)
            q = parse_qs(u.query)
            if "sessiz" not in q:
                kuyruk.son_hareket = time.time()
            if u.path == "/durum":
                d = kuyruk.durum()
                d["kafa"] = kuyruk.kafa()
                self._json(200, d)
            elif u.path == "/dosyalar":
                liste = [{"ad": d, "boyut": os.path.getsize(os.path.join(kuyruk.cikti, d))}
                         for d in sorted(os.listdir(kuyruk.cikti)) if os.path.isfile(os.path.join(kuyruk.cikti, d))]
                self._json(200, liste)
            elif u.path == "/cikti":
                ad = (q.get("ad") or [""])[0]
                yol = os.path.join(kuyruk.cikti, ad)
                if not DOSYA.match(ad) or not os.path.isfile(yol):
                    self._json(404, {"hata": "dosya yok"})
                    return
                son = (q.get("son") or ["0"])[0]
                with open(yol, "rb") as f:
                    if son.isdigit() and int(son) > 0:
                        f.seek(0, os.SEEK_END)
                        f.seek(max(0, f.tell() - int(son)))
                    veri = f.read()
                if "gz" in q:
                    self._yaz(200, gzip.compress(veri), "application/gzip")
                else:
                    self._yaz(200, veri, "text/plain; charset=utf-8")
            else:
                self._json(404, {"hata": "yol yok"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._yetkili():
                return
            kuyruk.son_hareket = time.time()
            u = urlparse(self.path)
            govde = self._govde()
            if u.path == "/is":
                isler = govde.get("isler") if isinstance(govde, dict) else None
                if not isinstance(isler, list) or len(isler) > 500:
                    self._json(400, {"hata": "isler bir liste degil"})
                    return
                self._json(200, kuyruk.ekle(isler))
            elif u.path == "/iptal":
                ad = govde.get("ad") if isinstance(govde, dict) else None
                self._json(200, {"sonuc": kuyruk.iptal(ad) if isinstance(ad, str) else "ad yok"})
            elif u.path == "/guncelle":
                kod, veri = kuyruk.guncelle()
                self._json(kod, veri)
            elif u.path == "/kapat":
                open(os.path.join(kuyruk.cikti, "KAPAT"), "w").close()
                self._json(200, {"sonuc": "kapaniyor"})
            else:
                self._json(404, {"hata": "yol yok"})

    return Isleyici


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--cikti", required=True, help="Folder the outputs of the jobs are written to.")
    parser.add_argument("--drive", default=None, help="Folder on Drive the files of a finished job are copied to.")
    parser.add_argument("--kok", action="append", default=[], help="A folder outside the repository a job may name.")
    parser.add_argument("--dal", default="tez-olcum", help="Branch /guncelle resets to.")
    options = parser.parse_args()
    key = os.environ.get("OLCUM_ANAHTAR", "")
    if len(key) < 24:
        sys.exit("OLCUM_ANAHTAR yok ya da kisa")
    roots = [os.path.normpath(k).replace("\\", "/") for k in [options.cikti, *options.kok]]
    if options.drive:
        roots.append(os.path.normpath(options.drive).replace("\\", "/"))
    queue = Kuyruk(os.getcwd(), options.cikti, options.drive, roots, options.dal)
    print(f"olcum sunucusu: 127.0.0.1:{options.port} | depo {queue.kafa()}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", options.port), isleyici(queue, key)).serve_forever()
