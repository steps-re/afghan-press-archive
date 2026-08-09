#!/usr/bin/env python3
"""Detect blank pages locally, before spending a model call on them.

3.0% of adl0616 (53 of 1,787) is blank front/back matter. At corpus scale that is ~1,900 pages
of paid-for nothing, and worse, a blank page invites the model to hallucinate furniture into
the corpus. Detecting them from pixels costs zero API dollars.

Calibrated against ground truth we already own: the adl0616 transcription run marked blanks as
[BLANK PAGE], so we can measure precision/recall of a pixel rule instead of guessing a threshold.

The asymmetry that sets the threshold: skipping a real page LOSES CONTENT PERMANENTLY, while
sending a blank page to the model costs $0.008. So tune for ~100% precision on "blank" and
accept poor recall. Never trade content for pennies.
"""
import io, json, os, sys
import numpy as np
import pypdfium2 as pdfium

HOME = os.path.expanduser("~")
PDF = os.environ.get("BD_PDF", os.path.join(HOME, "siraj/afghan/pdf/adl0616.pdf"))
TRUTH = os.environ.get("BD_TRUTH", os.path.join(HOME, "adl0616_transcriptions.jsonl"))
DPI = int(os.environ.get("BD_DPI", "72"))          # low res is plenty and renders fast

def ink_fraction(pil, dark=200):
    """Share of pixels darker than `dark` after a light denoise. Scanner grain and page edges
    are the false-positive risk, so trim a 3% border before measuring."""
    a = np.asarray(pil.convert("L"), dtype=np.uint8)
    h, w = a.shape
    m = int(min(h, w) * 0.03)
    a = a[m:h - m, m:w - m]
    return float((a < dark).mean())

def page_inks(pdf_path, pages=None, dpi=DPI):
    doc = pdfium.PdfDocument(pdf_path)
    n = len(doc)
    idx = pages or range(1, n + 1)
    out = {}
    for p in idx:
        if p < 1 or p > n:
            continue
        pil = doc[p - 1].render(scale=dpi / 72).to_pil()
        out[p] = ink_fraction(pil)
    doc.close()
    return out

def main():
    # Fail loudly. An earlier version skipped a missing truth file and calibrated against an
    # EMPTY ground truth, which produces a confident-looking threshold built on nothing.
    if not os.path.exists(TRUTH):
        raise SystemExit(f"[bd] ground truth not found: {TRUTH} (set BD_TRUTH)")
    truth = {}
    for l in open(TRUTH, encoding="utf-8"):
        r = json.loads(l)
        t = (r.get("text") or r.get("transcription") or "").strip()
        truth[r.get("page")] = ("[BLANK PAGE]" in t) or (len(t) < 40)
    if not truth:
        raise SystemExit(f"[bd] ground truth file parsed to 0 pages: {TRUTH}")
    print(f"[bd] truth: {sum(truth.values())} blank / {len(truth)} pages", flush=True)

    inks = page_inks(PDF)
    print(f"[bd] measured ink on {len(inks)} pages", flush=True)

    both = [(p, inks[p], truth[p]) for p in inks if p in truth]
    blanks = [i for _, i, b in both if b]
    texts = [i for _, i, b in both if not b]
    import statistics as st
    if blanks:
        print(f"[bd] ink fraction — BLANK pages: median {st.median(blanks):.5f} max {max(blanks):.5f}")
    print(f"[bd] ink fraction — TEXT  pages: median {st.median(texts):.5f} min {min(texts):.5f}")

    # Choose the largest threshold that still misclassifies ZERO text pages as blank.
    # Precision on "blank" must be 1.0; recall is whatever we can get for free.
    safe = min(texts) if texts else 0.0
    best, best_rec = 0.0, 0
    for t in sorted(set(round(x, 5) for x in blanks + texts)):
        if t >= safe:
            break
        rec = sum(1 for i in blanks if i < t)
        if rec > best_rec:
            best, best_rec = t, rec
    print(f"\n[bd] safe threshold (0 text pages lost): ink < {best:.5f}")
    print(f"[bd] catches {best_rec}/{len(blanks)} blanks = {100*best_rec/max(1,len(blanks)):.0f}% recall, "
          f"100% precision")
    print(f"[bd] would skip {best_rec}/{len(both)} pages = {100*best_rec/len(both):.1f}% of the book")
    json.dump({"threshold": best, "dpi": DPI, "recall": best_rec / max(1, len(blanks)),
               "blank_pages_truth": len(blanks), "pages": len(both),
               "note": "precision on blank is 1.0 by construction; skipping a real page is "
                       "unrecoverable, sending a blank costs $0.008"},
              open(os.path.join(HOME, "blank_threshold.json"), "w"), indent=2)

if __name__ == "__main__":
    main()
