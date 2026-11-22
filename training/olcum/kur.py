"""Installs what the page pipeline needs beyond the training cell's packages, on the runtime.

    python -m training.olcum.kur

homr.main imports rapidocr (the title reader), which the staff measurements never needed. The packages are the fixed
list below; the versions of the libraries the measurements run on (torch, numpy, opencv, onnxruntime, ...) are
pinned to what is installed, so that pip cannot move them in the middle of a run. Ends by importing homr.main.
"""

import importlib.metadata
import subprocess
import sys

PAKETLER = ["rapidocr>=3.7,<4"]
SABIT = ["torch", "torchvision", "torchaudio", "numpy", "transformers", "tokenizers", "safetensors", "onnxruntime",
         "opencv-python", "opencv-python-headless", "opencv-contrib-python", "pillow", "albumentations", "pymupdf",
         "x-transformers", "scipy"]

if __name__ == "__main__":
    kisit = "/tmp/olcum_kisit.txt"
    with open(kisit, "w", encoding="utf-8") as dosya:
        for paket in SABIT:
            try:
                dosya.write(f"{paket}=={importlib.metadata.version(paket)}\n")
            except importlib.metadata.PackageNotFoundError:
                pass
    print(open(kisit, encoding="utf-8").read(), flush=True)
    kod = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-c", kisit, *PAKETLER], check=False).returncode
    print("pip cikis kodu", kod, flush=True)
    for paket in ["rapidocr", *SABIT]:
        try:
            print(f"  {paket} {importlib.metadata.version(paket)}")
        except importlib.metadata.PackageNotFoundError:
            pass
    dene = subprocess.run([sys.executable, "-c", "import homr.main, training.read_page; print('homr.main ve read_page yuklendi')"],
                          check=False).returncode
    sys.exit(kod or dene)
