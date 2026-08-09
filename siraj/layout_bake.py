#!/usr/bin/env python3
"""Does layout-first cropping fix the recall gap on real newspaper pages?

The pre-scale review named multi-column reading order the biggest hidden error, but it was
never measurable — there was no gold. Now there is: the 102 aligned adl0616 pages. The
whole-page baseline (gemini-3.1-pro, single call) scored CER 0.182 with ref_recall 0.797,
i.e. it reads accurately but recovers only ~80% of the reference. If reading order and
column interleaving are the cause, layout-first should move RECALL first and CER second.

Both arms run on the SAME pages, SAME 300dpi render, and are scored the SAME way (parallel
span vs the same edition window), so the only variable is whole-page vs layout-first.
"""
import base64, io, json, os, re, sys, threading, time, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
import pypdfium2 as pdfium
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, os.path.expanduser("~/htr-bench"))
from htr import layout

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "siraj_gold/gold_pairs.jsonl")
ALIGN = os.path.join(HOME, "siraj_gold/alignment.jsonl")
PDF = os.path.join(HOME, "siraj/afghan/pdf/adl0616.pdf")
OUTDIR = os.path.join(HOME, "layout_bake"); os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, "layout_bake.jsonl")
SUM = os.path.join(OUTDIR, "layout_bake_summary.json")
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/"
BACKEND = os.environ.get("LB_BACKEND", "gemini-3.1-pro")
LIMIT = int(os.environ.get("LB_LIMIT", "40"))
WORKERS = int(os.environ.get("LB_WORKERS", "6"))
DPI, MAXPX = 300, 3500

HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
TAG = re.compile(r"^\s*\[[^\]]{0,40}\]\s*")
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE)\]")

def norm(t):
    t = MARK.sub(" ", TAG.sub("", t or ""))
    t = re.sub(r"\[([^\]]*)\؟?\]", r"\1", t)
    t = unicodedata.normalize("NFKC", t).translate(MAP).translate(HARAKAT).translate(DROP)
    t = re.sub(r"[۰-۹٠-٩\d]+", " 0 ", t)
    return [w for w in t.split() if w]

def parallel_span(aw, bw):
    bl = [b for b in SequenceMatcher(None, aw, bw, autojunk=False).get_matching_blocks() if b.size >= 2]
    if not bl:
        return None
    return (min(b.a for b in bl), max(b.a + b.size for b in bl),
            min(b.b for b in bl), max(b.b + b.size for b in bl))

def score(txt, window):
    aw, bw = norm(txt), norm(window)
    sp = parallel_span(aw, bw)
    if not sp or min(sp[1] - sp[0], sp[3] - sp[2]) < 60:
        return None
    A = " ".join(aw[sp[0]:sp[1]]); B = " ".join(bw[sp[2]:sp[3]])
    return {"cer": round(Levenshtein.distance(A, B) / max(len(A), len(B)), 4),
            "ref_recall": round((sp[3] - sp[2]) / max(1, len(bw)), 3),
            "span_coverage": round((sp[1] - sp[0]) / max(1, len(aw)), 3),
            "out_tokens": len(aw)}

def main():
    gold = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
    windows = {}
    for l in open(ALIGN, encoding="utf-8"):
        a = json.loads(l)
        if a.get("edition_text"):
            windows[a["page"]] = a["edition_text"]
    pages = [g["page"] for g in gold if g["page"] in windows]
    # See reader_bakeoff.py: gold_pairs.jsonl is sorted EASIEST-first, so [:LIMIT] is the
    # easy head, not a sample. The paired whole-page-vs-layout-first conclusion still holds
    # (both arms shared the same pages), but its absolute CER/recall are optimistic.
    if LIMIT and LIMIT < len(pages):
        step = len(pages) / LIMIT
        pages = [pages[int(i * step)] for i in range(LIMIT)]
    print(f"[lb] {len(pages)} pages | backend={BACKEND}", flush=True)

    doc = pdfium.PdfDocument(PDF)
    imgs = {}
    for p in pages:                                   # pdfium is not thread-safe
        pil = doc[p - 1].render(scale=DPI / 72).to_pil().convert("L")
        w, h = pil.size
        if max(w, h) > MAXPX:
            s = MAXPX / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
        buf = io.BytesIO(); pil.save(buf, "JPEG", quality=92)
        imgs[p] = (pil, base64.b64encode(buf.getvalue()).decode())
    doc.close()
    print(f"[lb] rendered {len(imgs)} pages", flush=True)

    res, lk, done = [], threading.Lock(), {"n": 0}
    def work(p):
        pil, b64 = imgs[p]
        rec = {"page": p, "backend": BACKEND}
        try:
            whole = layout.whole_page(b64, BACKEND) or ""
            rec["whole"] = score(whole, windows[p])
        except Exception as e:
            rec["whole_err"] = str(e)[:160]
        try:
            lf, cls, nregs = layout.transcribe_layout(
                pil, b64, read_backend=BACKEND, layout_backend=BACKEND, stable=True)
            rec["columns_are"] = cls
            rec["n_regions"] = nregs
            rec["layout_first"] = score(lf or "", windows[p])
        except Exception as e:
            rec["lf_err"] = str(e)[:160]
        with lk:
            res.append(rec); done["n"] += 1
            if done["n"] % 5 == 0:
                print(f"[lb] {done['n']}/{len(pages)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, p) for p in pages]))

    with open(OUT, "w", encoding="utf-8") as f:
        for r in sorted(res, key=lambda r: r["page"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import statistics as st
    from collections import Counter
    def agg(key, field):
        v = [r[key][field] for r in res if r.get(key) and field in r[key]]
        return round(st.median(v), 4) if v else None
    # paired comparison: only pages where BOTH arms produced a score
    both = [r for r in res if r.get("whole") and r.get("layout_first")]
    d_cer = [r["layout_first"]["cer"] - r["whole"]["cer"] for r in both]
    d_rec = [r["layout_first"]["ref_recall"] - r["whole"]["ref_recall"] for r in both]
    summary = {
        "backend": BACKEND, "pages": len(res),
        "routing": dict(Counter(r.get("columns_are") for r in res)),
        "cropped_pages": sum(1 for r in res if r.get("columns_are") == "independent_prose"
                             and (r.get("n_regions") or 0) > 1),
        "whole_page": {"scored": sum(1 for r in res if r.get("whole")),
                       "cer_median": agg("whole", "cer"),
                       "ref_recall_median": agg("whole", "ref_recall"),
                       "out_tokens_median": agg("whole", "out_tokens")},
        "layout_first": {"scored": sum(1 for r in res if r.get("layout_first")),
                         "cer_median": agg("layout_first", "cer"),
                         "ref_recall_median": agg("layout_first", "ref_recall"),
                         "out_tokens_median": agg("layout_first", "out_tokens")},
        "paired_n": len(both),
        "delta_cer_median": round(st.median(d_cer), 4) if d_cer else None,
        "delta_recall_median": round(st.median(d_rec), 4) if d_rec else None,
        "layout_first_wins_recall": sum(1 for d in d_rec if d > 0),
        "layout_first_wins_cer": sum(1 for d in d_cer if d < 0),
        "note": "delta = layout_first - whole_page; negative CER delta and positive recall delta both favour layout-first",
    }
    json.dump(summary, open(SUM, "w"), indent=2)
    print(json.dumps(summary, indent=2), flush=True)
    import subprocess
    subprocess.run(["gsutil", "-q", "cp", OUT, SUM, GCS], check=False)

if __name__ == "__main__":
    main()
