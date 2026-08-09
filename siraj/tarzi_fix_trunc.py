#!/usr/bin/env python3
"""Re-read the Tarzi pages that hit MAX_TOKENS at a higher ceiling.

A truncated page is worse than a failed one for alignment: it looks like a clean read
but silently drops the tail, which would score as an omission against the lithograph.
"""
import base64, io, json, os, subprocess
import pypdfium2 as pdfium
import tarzi_ocr as T

OUT = T.OUT
recs = [json.loads(l) for l in open(OUT, encoding="utf-8")]
bad = sorted(r["page"] for r in recs if r.get("finish") == "MAX_TOKENS")
print("truncated pages:", bad, flush=True)
if not bad:
    raise SystemExit(0)

doc = pdfium.PdfDocument(T.PDF)
fixed = {}
for p in bad:
    bmp = doc[p].render(scale=T.DPI / 72)
    buf = io.BytesIO(); bmp.to_pil().convert("RGB").save(buf, "JPEG", quality=92)
    b64 = base64.b64encode(buf.getvalue()).decode()
    old = next(r for r in recs if r["page"] == p)
    try:
        raw, fr = T.gemini(b64, max_tokens=24576)
    except Exception as e:
        print(f"  p{p} FAILED {e}", flush=True); continue
    fixed[p] = {"page": p, "printed_page": p - 21, "model": T.MODEL, "finish": fr,
                "raw_chars": len(raw), "text": T.normalize(raw)}
    print(f"  p{p}: {old['raw_chars']} -> {len(raw)} chars, finish={fr}", flush=True)
doc.close()

with open(OUT, "w", encoding="utf-8") as f:
    for r in sorted(recs, key=lambda r: r["page"]):
        f.write(json.dumps(fixed.get(r["page"], r), ensure_ascii=False) + "\n")

recs = [json.loads(l) for l in open(OUT, encoding="utf-8")]
still = [r["page"] for r in recs if r.get("finish") == "MAX_TOKENS"]
ok = [r for r in recs if r.get("text") and r["text"] not in ("[BLANK PAGE]", "[PLATE]")]
full = "\n\n".join(r["text"] for r in sorted(ok, key=lambda r: r["page"]))
open(os.path.join(T.OUTDIR, "tarzi_full.txt"), "w", encoding="utf-8").write(full)
print(f"still truncated: {still} | chars {len(full):,}", flush=True)
subprocess.run(["gsutil", "-q", "cp", OUT,
                os.path.join(T.OUTDIR, "tarzi_full.txt"), T.GCS], check=False)
