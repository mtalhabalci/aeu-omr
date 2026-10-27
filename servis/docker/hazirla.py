"""Assemble the Docker build folder of the reading service: the Dockerfile and pinned requirements from this
folder, the Python code the service imports, the weights it reads (which git does not hold) and the OCR models of
the title-block reader (ocr_modelleri/, from this machine's RapidOCR; the Dockerfile puts them where RapidOCR looks).

    python servis/docker/hazirla.py [out]        out defaults to C:\\projects\\yl\\nota-okuma-imaj

The weights are taken from this checkout, or, for one that has none (a git worktree), from the checkout named by
OMR_AGIRLIK_KOKU. The folder is meant to be copied to the server as it is and built there
(docker build -t nota-okuma:v24 .).
At the end it lists which of its files carry the upstream project's name, which the app's repository must not.
"""
import os
import shutil
import sys

import rapidocr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = sys.argv[1] if len(sys.argv) > 1 else r"C:\projects\yl\nota-okuma-imaj"
NAME = "ho" + "mr"  # spelled so that this file does not list itself
# where the weights are when this checkout has none (git holds no weights)
WEIGHTS_ROOT = os.environ.get("OMR_AGIRLIK_KOKU", ROOT)

# Python packages copied whole (code only), and the data files the service opens
PACKAGES = [NAME, "servis", os.path.join("training", "architecture"), os.path.join("training", "transformer")]
SINGLE = [os.path.join("training", "__init__.py")]
DATA = [
    os.path.join(NAME, "transformer", "tokenizer_lift.json"),
    os.path.join(NAME, "transformer", "tokenizer_note.json"),
    os.path.join(NAME, "transformer", "tokenizer_pitch.json"),
    os.path.join(NAME, "transformer", "tokenizer_rhythm.json"),
    # staff finding on the CPU (the fp16 file is the GPU's)
    os.path.join(NAME, "segmentation", "segnet_308-3296ccd40960f90ca6ab9c035cca945675d30a0f.onnx"),
    # v24, the reader the app uses (the thesis keeps v20)
    os.path.join("training", "architecture", "transformer",
                 "pytorch_model_1-819bee2ae062dff09fd97af4dfae98dd1709ceb3.pth"),
    # the model v24 was fine-tuned from (run 331): it reads the staffs of systems of several staffs, for chords,
    # second voices and the clefs other than the treble clef
    os.path.join("training", "architecture", "transformer",
                 "pytorch_model_331-e10346542968cc71fbcce0c0696f3ac963f11ae1.pth"),
    # the tempo readers that vote, and the one for ranges
    *(os.path.join("training", "architecture", "tempo", f"tempo_okuyucu_{k}.pt") for k in ("1", "2", "3", "aralik")),
    # the makam, form and usul names the title-block reader looks for
    os.path.join(NAME, "baslik_isimleri.json"),
]
# RapidOCR's default models, as the title-block reader loads them (PP-OCRv6 small detector and recogniser, the
# angle classifier); RapidOCR downloads them on first use, so they are taken from this machine's installation
OCR_MODELS = ["PP-OCRv6_det_small.onnx", "PP-OCRv6_rec_small.onnx", "ch_ppocr_mobile_v2.0_cls_mobile.onnx"]
SKIP_DIRS = {"__pycache__", "ornekler"}


def copy(rel: str) -> int:
    src, dst = os.path.join(ROOT, rel), os.path.join(OUT, "kod", rel)
    if not os.path.exists(src):
        src = os.path.join(WEIGHTS_ROOT, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(src, dst)
    return os.path.getsize(dst)


if os.path.exists(OUT):
    shutil.rmtree(OUT)
os.makedirs(OUT)
for name in ("Dockerfile", "requirements-cpu.txt", "OKU_BENI.md", ".dockerignore"):
    shutil.copy2(os.path.join(HERE, name), os.path.join(OUT, name))

code = 0
for package in PACKAGES:
    for folder, dirs, files in os.walk(os.path.join(ROOT, package)):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            if f.endswith(".py"):
                code += copy(os.path.relpath(os.path.join(folder, f), ROOT))
for rel in SINGLE:
    code += copy(rel)
weights = {rel: copy(rel) for rel in DATA}
ocr_dir = os.path.join(os.path.dirname(rapidocr.__file__), "models")
os.makedirs(os.path.join(OUT, "ocr_modelleri"))
for model in OCR_MODELS:
    src = os.path.join(ocr_dir, model)
    if not os.path.exists(src):  # the image build downloads what is missing
        print("OCR modeli yok, imaj kurulurken indirilecek:", model)
        continue
    shutil.copy2(src, os.path.join(OUT, "ocr_modelleri", model))
    weights[os.path.join("ocr_modelleri", model)] = os.path.getsize(src)

named = []
for folder, _, files in os.walk(OUT):
    for f in files:
        path = os.path.join(folder, f)
        rel = os.path.relpath(path, OUT)
        in_path = NAME in rel.lower()
        in_text = False
        if not f.endswith((".pth", ".pt", ".onnx")):
            in_text = NAME in open(path, encoding="utf-8", errors="ignore").read().lower()
        if in_path or in_text:
            named.append(rel)

mb = lambda n: f"{n / 1e6:.1f} MB"  # noqa: E731
print(OUT)
print("kod", mb(code))
for rel, size in weights.items():
    print(" ", mb(size), rel)
print("agirlik toplam", mb(sum(weights.values())))
outside = [r for r in named if not r.startswith("kod" + os.sep)]
print("adi gecen dosya:", len(named), "| kod/ disinda:", outside or "yok")
