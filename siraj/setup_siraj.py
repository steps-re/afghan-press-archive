#!/usr/bin/env python3
"""Set up an ISOLATED adl0616 (Siraj al-Akhbar) run at ~/siraj.

Isolated because afghan_run.py roots its state at dirname(__file__)/afghan, so a
private copy keeps this run's manifest, cache and JSONL away from the main corpus run.

Two deltas vs the stock pipeline:
  - manifest pinned to adl0616 only
  - render resolution made env-controlled, DEFAULTS UNCHANGED (200dpi/2500px/q85), so
    the stock behaviour is byte-identical unless the env vars are set. Siraj is a dense
    multi-column newspaper and 200dpi/2500px is the known-suspect setting for exactly
    that case, so this run overrides to 300/3500/q92.
"""
import json, os, re, shutil

SRC = os.path.expanduser("~/mss301work")
DST = os.path.expanduser("~/siraj")
os.makedirs(os.path.join(DST, "afghan"), exist_ok=True)

for f in ("afghan_run.py", "hyde_transcribe.py"):
    shutil.copy2(os.path.join(SRC, f), os.path.join(DST, f))

json.dump(["adl0616"], open(os.path.join(DST, "afghan", "afghan_manifest.json"), "w"))

p = os.path.join(DST, "afghan_run.py")
s = open(p, encoding="utf-8").read()

anchor = 'WORKERS = int(os.environ.get("AFGHAN_WORKERS", "12"))'
assert anchor in s, "worker anchor missing -- pipeline changed, re-check before patching"
s = s.replace(anchor, anchor + "\n" + "\n".join([
    'DPI = int(os.environ.get("AFGHAN_DPI", "200"))',
    'MAXPX = int(os.environ.get("AFGHAN_MAXPX", "2500"))',
    'JPEGQ = int(os.environ.get("AFGHAN_JPEGQ", "85"))',
]), 1)

subs = [("bmp = page.render(scale=200 / 72)", "bmp = page.render(scale=DPI / 72)"),
        ("if max(w, hgt) > 2500:", "if max(w, hgt) > MAXPX:"),
        ("s = 2500 / max(w, hgt)", "s = MAXPX / max(w, hgt)"),
        ('pil.save(out, format="JPEG", quality=85)', 'pil.save(out, format="JPEG", quality=JPEGQ)')]
for a, b in subs:
    assert a in s, f"render anchor missing: {a}"
    s = s.replace(a, b, 1)

# cache key must carry the resolution, else a 200dpi jpeg from an earlier run gets
# silently reused at 300dpi and the resolution change becomes a no-op
old_out = 'out = os.path.join(IMG_DIR, f"{book}_{i:04d}.jpg")'
assert old_out in s
s = s.replace(old_out, 'out = os.path.join(IMG_DIR, f"{book}_{i:04d}_d{DPI}.jpg")', 1)

open(p, "w", encoding="utf-8").write(s)
print("patched:", p)
print("manifest:", json.load(open(os.path.join(DST, "afghan", "afghan_manifest.json"))))
