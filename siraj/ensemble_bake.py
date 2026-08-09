#!/usr/bin/env python3
"""Does adjudicating two COMPLEMENTARY drafts beat the best single reader?

Every result so far points at this config and none of them tested it. The two best readers
fail in opposite directions on real newspaper pages:

  gemini-3.1-pro    high precision, low recall  -- reads less, gets more of it right
  tuned-2.5-pro     high recall,   lower precision -- reads more, gets more of it wrong

That is textbook ensemble complementarity. Layout-first cropping is separately the biggest
single lever measured (+46% effective yield, paired). This runs both together.

THREE ARMS, same pages, same render, same scoring:
  pro_lf     layout-first, 3.1-pro reading every region
  tuned_lf   layout-first, tuned-2.5-pro reading every region
  ensemble   both drafts + the page image -> 3.1-pro adjudicates into one transcription

DESIGN NOTES
- Layout is computed ONCE per page (stable/majority-voted, 3.1-pro) and the SAME regions are
  handed to both readers. Layout is held fixed so the only variable is the reader; it also
  halves the cost.
- Each reader runs its OWN best prompt -- the rich rules for 3.1-pro, the tuned wording for
  the tuned model. Scoring a tuned model on a generic prompt measures prompt mismatch, not
  the model. So prompt co-varies with model by design: each arm is the best that model can
  actually do, which is what you would deploy.
- Scoring reports PAIRED per-page deltas and win counts, not a difference of two aggregate
  medians. On the last run the medians claimed a 0.05 CER gap where the paired median delta
  was 0.003. See feedback-head-slice-of-sorted-file-is-not-a-sample.
- Pages are subsampled EVENLY across the difficulty-sorted gold file, never [:N] off the head.
"""
import base64, io, json, os, re, statistics as st, subprocess, sys, threading, unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from math import comb
import pypdfium2 as pdfium
from rapidfuzz.distance import Levenshtein

sys.path.insert(0, os.path.expanduser("~/htr-bench"))
from htr import layout, models

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "siraj_gold/gold_pairs.jsonl")
ALIGN = os.path.join(HOME, "siraj_gold/alignment.jsonl")
PDF = os.path.join(HOME, "siraj/afghan/pdf/adl0616.pdf")
OUTDIR = os.path.join(HOME, "ensemble_bake"); os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, "ensemble_bake.jsonl")
SUM = os.path.join(OUTDIR, "ensemble_bake_summary.json")
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/"

PRO = os.environ.get("EB_PRO", "gemini-3.1-pro")
TUNED = os.environ.get("EB_TUNED", "tuned-2.5-pro")
JUDGE = os.environ.get("EB_JUDGE", "gemini-3.1-pro")
LIMIT = int(os.environ.get("EB_LIMIT", "0"))
WORKERS = int(os.environ.get("EB_WORKERS", "8"))
DPI, MAXPX = 300, 3500

SYS_RICH = ("You are an expert transcriber of early Afghan printed periodicals (1911-1918, the "
            "Afghanistan Digital Library). The text is Persian/Dari in Arabic script, lithographed "
            "nastaliq, often in multiple columns. Read right-to-left in correct reading order.")
PROMPT_RICH = """Transcribe this text region.
- Output the text in its ORIGINAL Arabic script, preserving orthography. Do NOT translate or romanize.
- Preserve reading order and structure; keep each verse on its own line; reflow hard-wrapped prose.
- Unclear word -> best guess as [word?]. Wholly illegible -> [ILL].
- If the region is blank or a plate with no text, output exactly [BLANK PAGE].
- Output ONLY the transcription. No commentary, no markdown, no code fences."""

SYS_TUNED = ("You are an expert transcriber of early Afghan print (1871-1930): Persian/Dari and "
             "Pashto in Arabic script (nastaliq/naskh), much of it lithographed from manuscript. "
             "Read right-to-left in correct reading order.")
PROMPT_TUNED = ("Transcribe this page faithfully. Preserve original spelling, capitalization, "
                "punctuation, and abbreviations; non-Latin text stays in its original script. "
                "Output ONLY the transcription.")

SYS_JUDGE = ("You are an expert editor of early Afghan lithographed periodicals. Two independent "
             "transcribers have read the same page. You have the page image. Produce the single "
             "best transcription.")
PROMPT_JUDGE = """Below are two independent transcriptions of the page image, by readers with
known and OPPOSITE failure modes:

- READER A is precise but OMITS material -- if a passage appears only in B, that is usually a
  real passage A skipped, not something B invented. Recover it.
- READER B reads more of the page but makes more character-level errors -- where both readers
  cover the same passage and disagree on wording, A is usually the more reliable one.

Use the IMAGE to settle every disagreement. Do not average the two texts and do not copy one
wholesale. Rules:
- Keep the original Arabic script and orthography. Do NOT translate or romanize.
- Correct reading order, right-to-left, right column fully before the left.
- Include every passage that is genuinely on the page, even if only one reader has it.
- Drop anything neither reader supports and the image does not show.
- Output ONLY the merged transcription. No commentary, no markdown, no code fences.

=== READER A ===
{a}

=== READER B ===
{b}
"""

HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
TAG = re.compile(r"^\s*\[[^\]]{0,40}\]\s*")
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE|TRUNCATED—MAX_TOKENS)\]")

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
    """CER over the genuinely parallel region + recall against the reference window.
    CER alone is not enough: a model that omits the hard half of a page posts a better CER
    while reading LESS, so effective yield = recall * (1 - CER) is the headline metric."""
    aw, bw = norm(txt), norm(window)
    sp = parallel_span(aw, bw)
    if not sp or min(sp[1] - sp[0], sp[3] - sp[2]) < 60:
        return None
    A = " ".join(aw[sp[0]:sp[1]]); B = " ".join(bw[sp[2]:sp[3]])
    cer = Levenshtein.distance(A, B) / max(len(A), len(B))
    rec = (sp[3] - sp[2]) / max(1, len(bw))
    return {"cer": round(cer, 4), "ref_recall": round(rec, 3),
            "yield": round(rec * (1 - cer), 4),
            "span_coverage": round((sp[1] - sp[0]) / max(1, len(aw)), 3),
            "out_tokens": len(aw)}

def read_regions(pil, b64, regs, columns_are, backend, sys_txt, prompt):
    """Same region set for every reader -- layout held fixed so the reader is the only variable."""
    if columns_are != "independent_prose" or len(regs) <= 1:
        return models.transcribe(backend, sys_txt, prompt, b64, max_tokens=16384) or ""
    parts = []
    for r in regs:
        cb = layout._crop_b64(pil, r["box"])
        if not cb:
            continue
        t = models.transcribe(backend, sys_txt, prompt, cb, max_tokens=8192)
        if t and t.strip() and t.strip() != "[BLANK PAGE]":
            parts.append(t.strip())
    return "\n\n".join(parts)

def sign_test(deltas, better=lambda d: d > 0):
    n = sum(1 for d in deltas if d != 0)
    w = sum(1 for d in deltas if better(d))
    if n == 0:
        return {"n": 0, "wins": 0, "p": None}
    p = 2 * sum(comb(n, k) for k in range(w, n + 1)) / 2 ** n
    return {"n": n, "wins": w, "p": round(min(1.0, p), 4)}

def main():
    gold = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
    windows = {}
    for l in open(ALIGN, encoding="utf-8"):
        a = json.loads(l)
        if a.get("edition_text"):
            windows[a["page"]] = a["edition_text"]
    pages = [g["page"] for g in gold if g["page"] in windows]
    if LIMIT and LIMIT < len(pages):
        step = len(pages) / LIMIT
        pages = [pages[int(i * step)] for i in range(LIMIT)]
        print(f"[eb] subsampled {LIMIT} evenly across the difficulty-sorted file", flush=True)
    print(f"[eb] {len(pages)} pages | pro={PRO} tuned={TUNED} judge={JUDGE}", flush=True)

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
    print(f"[eb] rendered {len(imgs)} pages", flush=True)

    res, lk, done = [], threading.Lock(), {"n": 0}

    def work(p):
        pil, b64 = imgs[p]
        rec = {"page": p}
        try:
            columns_are, regs = layout.analyze_stable(b64, JUDGE)
            rec["columns_are"], rec["n_regions"] = columns_are, len(regs)

            a_txt = read_regions(pil, b64, regs, columns_are, PRO, SYS_RICH, PROMPT_RICH)
            rec["pro_lf"] = score(a_txt, windows[p])

            b_txt = read_regions(pil, b64, regs, columns_are, TUNED, SYS_TUNED, PROMPT_TUNED)
            rec["tuned_lf"] = score(b_txt, windows[p])

            if a_txt.strip() and b_txt.strip():
                merged = models.transcribe(
                    JUDGE, SYS_JUDGE, PROMPT_JUDGE.format(a=a_txt, b=b_txt), b64,
                    max_tokens=16384) or ""
                rec["ensemble"] = score(merged, windows[p])
                rec["merged_chars"] = len(merged)
        except Exception as e:
            rec["err"] = f"{type(e).__name__}: {str(e)[:200]}"
        with lk:
            res.append(rec); done["n"] += 1
            if done["n"] % 5 == 0:
                print(f"[eb] {done['n']}/{len(pages)}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, p) for p in pages]))

    with open(OUT, "w", encoding="utf-8") as f:
        for r in sorted(res, key=lambda r: r["page"]):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ARMS = ["pro_lf", "tuned_lf", "ensemble"]
    summary = {"pages": len(res), "errors": sum(1 for r in res if "err" in r),
               "pro": PRO, "tuned": TUNED, "judge": JUDGE, "arms": {}}
    for a in ARMS:
        v = [r[a] for r in res if r.get(a)]
        summary["arms"][a] = {
            "scored": len(v),
            "cer_median": round(st.median([x["cer"] for x in v]), 4) if v else None,
            "recall_median": round(st.median([x["ref_recall"] for x in v]), 3) if v else None,
            "yield_median": round(st.median([x["yield"] for x in v]), 4) if v else None,
            "out_tokens_median": round(st.median([x["out_tokens"] for x in v]), 1) if v else None,
        }
    # PAIRED comparisons -- the only honest way to rank these
    summary["paired"] = {}
    for a, b in [("ensemble", "pro_lf"), ("ensemble", "tuned_lf"), ("tuned_lf", "pro_lf")]:
        both = [r for r in res if r.get(a) and r.get(b)]
        if not both:
            continue
        dy = [r[a]["yield"] - r[b]["yield"] for r in both]
        dc = [r[a]["cer"] - r[b]["cer"] for r in both]
        dr = [r[a]["ref_recall"] - r[b]["ref_recall"] for r in both]
        summary["paired"][f"{a}_vs_{b}"] = {
            "n": len(both),
            "delta_yield_median": round(st.median(dy), 4), "yield_sign_test": sign_test(dy),
            "delta_cer_median": round(st.median(dc), 4),
            "cer_wins": sum(1 for d in dc if d < 0),
            "delta_recall_median": round(st.median(dr), 4),
            "recall_wins": sum(1 for d in dr if d > 0),
        }
    summary["note"] = ("delta = first arm minus second. yield = ref_recall * (1 - CER), the share "
                       "of the reference recovered CORRECTLY, and the metric to rank on. Layout is "
                       "held FIXED across arms; each reader uses its own best prompt.")
    json.dump(summary, open(SUM, "w"), indent=2)
    print(json.dumps(summary, indent=2), flush=True)
    subprocess.run(["gsutil", "-q", "cp", OUT, SUM, GCS], check=False)

if __name__ == "__main__":
    main()
