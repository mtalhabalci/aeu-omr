"""The makam, form and usul names the title-block reader looks for (homr/baslik_isimleri.json): the SymbTr file-name
slugs of the training works, plus the printed spelling the Mus2 headers give each slug. Test works are left out, so
that the reader is measured on names it was not handed.

    python training/baslik/isimler.py   (after etiket_mus2.py)
"""
import json
import os
import re
import sys
from collections import Counter, defaultdict

here = os.path.dirname(os.path.abspath(__file__))
root = os.path.dirname(os.path.dirname(here))
sys.path.insert(0, here)
from etiket_mus2 import OUT, fold  # noqa: E402

rows = [json.loads(line) for line in open(os.path.join(OUT, "mus2_etiketler.jsonl"), encoding="utf-8")]
train = [r for r in rows if r["kume"] == "egitim"]
lists: dict = {}
printed: dict = {}
for kind in ("makam", "form", "usul"):
    spellings: dict = defaultdict(Counter)
    for r in train:
        spellings[fold(r["dosya_adi"][kind])]  # a slug counts even when the header could not be read
        value = r["fields"].get(kind)
        if value:
            value = re.sub(r"\s+[IVX]+$", "", value)
            spellings[fold(value)][value] += 1
    # a slug with no letters is no name (one türkü's file gives its usul as "3334", the beats of its measure)
    slugs = sorted(s for s in spellings if re.search(r"[a-z]", s))
    lists[kind] = slugs
    printed[kind] = {s: spellings[s].most_common(1)[0][0] for s in slugs if spellings[s]}
out = os.path.join(root, "homr", "baslik_isimleri.json")
# spellings of the same name that SymbTr writes otherwise (Evç is SymbTr's eviç; "Ağırca Aksak" is ağır aksak)
ALIASES = {"makam": {"evc": "evic"}, "form": {"sazsemai": "sazsemaisi"}, "usul": {"agircaaksak": "agiraksak"}}
json.dump({**lists, "yazilis": printed, "takma": ALIASES}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
test = [r for r in rows if r["kume"] == "sinav"]
for kind in ("makam", "form", "usul"):
    known = sum(fold(r["dosya_adi"][kind]) in set(lists[kind]) for r in test)
    print(f"{kind}: {len(lists[kind])} ad; sınav eserlerinin {known}/{len(test)}'i listede")
print(out)
