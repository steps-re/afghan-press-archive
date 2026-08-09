#!/usr/bin/env python3
"""Text-only linguistic post-correction: does knowing Persian fix OCR errors, and what does it break?

Never tested before. The adjudication pass we ran was IMAGE-grounded arbitration between two
drafts; this is different -- one transcription, no image, corrected purely from knowledge of
the language. There is concrete reason to expect gains: our best gold pair differed from the
edition almost entirely by «اورویا»/«اروپا» (a پ misread) and «میماند»/«می ماند» (word
boundary). Both are fixable with no image at all, and both are the signature nasta'liq failure
modes -- dot count/placement and boundary splits in connected script.

THE TRAP THIS SCRIPT EXISTS TO CATCH
We score against a MODERN TYPESET EDITION whose orthography is already normalised. A corrector
that quietly modernises 1911 Kabul spelling will IMPROVE measured CER while moving AWAY from
what is printed on the page. CER alone would reward exactly the behaviour that corrupts a
primary source. So every level is scored on TWO axes:

  cer            -- did it get closer to the edition?
  false_corr     -- of the tokens the raw read got RIGHT, what fraction did it CHANGE?

false_corr is the number that decides this. A level that gains 0.03 CER while rewriting 5% of
already-correct tokens is a bad trade for a historical corpus.

LEVELS are deliberately a risk ladder, so the search UI can expose them as a toggle with a
measured cost attached to each rung rather than a vague "AI cleanup" switch.
"""
import base64, io, json, os, re, statistics as st, subprocess, sys, threading, time
import unicodedata, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
import pypdfium2 as pdfium
from rapidfuzz.distance import Levenshtein

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "siraj_gold/gold_pairs.jsonl")
ALIGN = os.path.join(HOME, "siraj_gold/alignment.jsonl")
PDF = os.path.join(HOME, "siraj/afghan/pdf/adl0616.pdf")
OUTDIR = os.path.join(HOME, "correct_bake"); os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, "correct_bake.jsonl")
SUM = os.path.join(OUTDIR, "correct_bake_summary.json")
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/"
PROJECT = os.environ.get("HTR_PROJECT", "")
READER = "gemini-3.1-pro-preview"          # same config the corpus run uses
DPI, MAXPX = 300, 3500
LIMIT = int(os.environ.get("CR_LIMIT", "0"))
WORKERS = int(os.environ.get("CR_WORKERS", "8"))

SYS_READ = ("You are an expert transcriber of early Afghan printed periodicals (1911-1918, the "
            "Afghanistan Digital Library). The text is Persian/Dari in Arabic script, lithographed "
            "nastaliq, often in multiple columns. Read right-to-left in correct reading order.")
RULES = """Transcribe this page.
- Output the text in its ORIGINAL Arabic script, preserving orthography. Do NOT translate or romanize.
- Preserve reading order and structure; keep each verse on its own line; reflow hard-wrapped prose.
- Unclear word -> best guess as [word?]. Wholly illegible -> [ILL].
- If the page is blank or a plate with no text, output exactly [BLANK PAGE].
- Output ONLY the transcription. No commentary, no markdown, no code fences."""

SYS_FIX = ("You are an editor of early 20th-century Afghan Persian (Dari) periodical prose, "
           "working from an OCR transcription of a lithographed nasta'liq page. You know the "
           "language, its grammar, and the period's orthography.")

COMMON = """The transcription came from an image; you do NOT have the image. Typical errors in
this script are: wrong number or placement of dots (ب/پ/ت/ث, ج/چ/ح/خ, ر/ز, س/ش, ک/گ), ی vs ے,
and incorrect word boundaries in connected script (e.g. «میماند» for «می ماند»).

Output ONLY the corrected text. No commentary, no markdown, no code fences, no explanation."""

LEVELS = {
    # L1: touch only what the reader itself flagged. Lowest possible risk.
    "L1-flagged": """Correct ONLY the words the transcriber marked as uncertain, which appear as
[word?] or [ILL]. Replace each such marker with your best reading given the surrounding context,
and remove the brackets.

DO NOT alter any other character anywhere in the text. Preserve all archaic, non-standard and
period spellings exactly as they are. If you cannot confidently resolve a marker, leave the word
without brackets as the transcriber guessed it.
""" + COMMON,

    # L2: fix real errors, explicitly forbidden from modernising. The intended production setting.
    "L2-conservative": """Correct clear transcription errors: sequences that are not Persian words,
or that are ungrammatical, where the intended word is obvious from context and is a plausible
misreading of the script.

CRITICAL: this is a 1911-1918 text. PRESERVE its period orthography. Do NOT modernise spelling,
do NOT standardise archaic forms, do NOT add or remove ezafe, and do NOT change punctuation or
paragraphing. If a word is unusual but is a genuine period form, LEAVE IT. When in doubt, leave
the text unchanged -- an uncorrected error is far better than a plausible invention.
""" + COMMON,

    # L3: full fluency pass. Deliberately the high-impact rung, expected to score well on CER and
    # badly on false_corr -- which is the point: it quantifies what "aggressive" costs.
    "L3-fluent": """Produce the most fluent and readable Persian text consistent with this
transcription. Fix misreadings, normalise spelling and word boundaries, and repair grammar so the
passage reads naturally.
""" + COMMON,
}
# Emit ONLY the edits instead of the whole page. Measured waste in the full-text arms: the
# correction re-emits ~1,000 tokens of unchanged text to alter ~20 words. NB this alone is only
# ~26% off, because THINKING is billed as output too and dominates (2,260 tok vs the read's 192)
# -- so the thinking level is the bigger lever and these arms vary both.
DIFF_INSTRUCTION = """
Return ONLY a JSON array of the corrections you are making, and nothing else:
[{"old": "<the exact wrong word, copied verbatim from the transcription>", "new": "<corrected word>"}]

Include an entry ONLY for words you are actually changing. If nothing needs changing, return [].
Copy `old` exactly as it appears so it can be located. No commentary, no markdown, no code fences.
"""

def apply_edits(raw, payload):
    """Apply an edit list to the raw text. Replaces every exact occurrence of `old`, which can
    over-apply when a word repeats -- that risk is deliberately left in and measured, since it
    shows up directly in false_corr_rate rather than being hidden by a cleverer matcher."""
    s = payload.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-z]*\s*|\s*```$", "", s)
    i, j = s.find("["), s.rfind("]")
    if i < 0 or j <= i:
        return raw, 0
    try:
        edits = json.loads(s[i:j + 1])
    except Exception:
        return raw, 0
    out, n = raw, 0
    for e in edits if isinstance(edits, list) else []:
        if not isinstance(e, dict):
            continue
        o, w = str(e.get("old", "")), str(e.get("new", ""))
        if o and w and o != w and o in out:
            out = out.replace(o, w); n += 1
    return out, n

# [label, model, thinkingLevel, mode]
ARMS = json.loads(os.environ["CR_ARMS"]) if os.environ.get("CR_ARMS") else [
    ["L1-flagged",      READER,                  "low", "full"],
    ["L2-conservative", READER,                  "low", "full"],
    ["L3-fluent",       READER,                  "low", "full"],
    # Correction is a TEXT task, not the visual specialist task the reader ranking was measured
    # on -- so a cheap model may be fine here. Do not inherit the "never use lite" conclusion.
    ["L2-conservative", "gemini-3.1-flash-lite", "low", "full"],
]

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
    cer = Levenshtein.distance(A, B) / max(len(A), len(B))
    rec = (sp[3] - sp[2]) / max(1, len(bw))
    return {"cer": round(cer, 4), "ref_recall": round(rec, 3),
            "yield": round(rec * (1 - cer), 4), "out_tokens": len(aw)}

def damage(raw, corrected, window):
    """The number that decides this.

    Of the raw tokens that ALREADY AGREED with the edition, what fraction did the corrector
    change? Computed inside the parallel span only, since the edition covers just Tarzi's own
    articles and the rest of the page has no counterpart to be right or wrong about.
    """
    R, C, G = norm(raw), norm(corrected), norm(window)
    sp = parallel_span(R, G)
    if not sp:
        return None
    Rs, Gs = R[sp[0]:sp[1]], G[sp[2]:sp[3]]
    # which raw tokens were already correct?
    correct = set()
    for b in SequenceMatcher(None, Rs, Gs, autojunk=False).get_matching_blocks():
        for i in range(b.size):
            correct.add(sp[0] + b.a + i)
    if not correct:
        return None
    # which raw tokens survived into the corrected text unchanged?
    kept = set()
    for b in SequenceMatcher(None, R, C, autojunk=False).get_matching_blocks():
        for i in range(b.size):
            kept.add(b.a + i)
    changed_correct = len(correct - kept)
    # and of the tokens raw got WRONG, how many did it touch at all?
    wrong = set(range(sp[0], sp[1])) - correct
    touched_wrong = len(wrong - kept)
    return {"correct_tokens": len(correct),
            "false_corrections": changed_correct,
            "false_corr_rate": round(changed_correct / len(correct), 4),
            "wrong_tokens": len(wrong),
            "touched_wrong_rate": round(touched_wrong / max(1, len(wrong)), 4)}

_tok = {"v": None, "e": 0.0}; _lk = threading.Lock()
def token():
    with _lk:
        if _tok["v"] and time.time() < _tok["e"]:
            return _tok["v"]
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        _tok["e"] = time.time() + 1500
        return _tok["v"]

def call(model, system, user, b64=None, retries=3, thinking="low"):
    url = (f"https://aiplatform.googleapis.com/v1/projects/{PROJECT}/locations/global"
           f"/publishers/google/models/{model}:generateContent")
    parts = []
    if b64:
        parts.append({"inlineData": {"mimeType": "image/jpeg", "data": b64}})
    parts.append({"text": user})
    body = {"contents": [{"role": "user", "parts": parts}],
            "systemInstruction": {"parts": [{"text": system}]},
            "generationConfig": {"maxOutputTokens": 16384,
                                 "thinkingConfig": {"thinkingLevel": thinking}}}
    data = json.dumps(body).encode()
    last = ""
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            c = (d.get("candidates") or [{}])[0]
            txt = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts") or []).strip()
            u = d.get("usageMetadata", {}) or {}
            if txt:
                return txt, u, ""
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
            if e.code == 400:
                return "", {}, last
            time.sleep(3 * (a + 1))
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:150]}"
            time.sleep(3 * (a + 1))
    return "", {}, last

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
    print(f"[cr] {len(pages)} pages x ({len(ARMS)} correction arms + 1 raw read)", flush=True)

    doc = pdfium.PdfDocument(PDF)
    imgs = {}
    for p in pages:
        pil = doc[p - 1].render(scale=DPI / 72).to_pil().convert("L")
        w, h = pil.size
        if max(w, h) > MAXPX:
            s = MAXPX / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
        buf = io.BytesIO(); pil.save(buf, "JPEG", quality=92)
        imgs[p] = base64.b64encode(buf.getvalue()).decode()
    doc.close()
    print(f"[cr] rendered {len(imgs)} pages", flush=True)

    # Stage 1: the raw read, exactly the config the corpus run uses.
    raw, lk, done = {}, threading.Lock(), {"n": 0}
    def read_one(p):
        txt, u, err = call(READER, SYS_READ, RULES, imgs[p])
        with lk:
            raw[p] = {"text": txt, "usage": u, "err": err}
            done["n"] += 1
            if done["n"] % 25 == 0:
                print(f"[cr] raw {done['n']}/{len(pages)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(read_one, p) for p in pages]))
    ok = [p for p in pages if raw[p]["text"]]
    print(f"[cr] raw reads: {len(ok)}/{len(pages)}", flush=True)

    # Stage 2: text-only correction, no image.
    res, done["n"] = [], 0
    jobs = [(lab, model, think, mode, p) for lab, model, think, mode in ARMS for p in ok]
    def fix_one(job):
        lab, model, think, mode, p = job
        arm = f"{lab}@{model.split('-')[-1]}/{think}/{mode}"
        body = LEVELS[lab] + (DIFF_INSTRUCTION if mode == "diff" else "")
        prompt = body + "\n\n=== TRANSCRIPTION ===\n" + raw[p]["text"]
        out, u, err = call(model, SYS_FIX, prompt, thinking=think)
        rec = {"page": p, "arm": arm, "level": lab, "model": model,
               "thinking": think, "mode": mode}
        if err:
            rec["err"] = err[:200]
        if mode == "diff" and out:
            txt, n_applied = apply_edits(raw[p]["text"], out)
            rec["edits_applied"] = n_applied
        else:
            txt = out
        if txt:
            s = score(txt, windows[p])
            if s: rec.update(s)
            d = damage(raw[p]["text"], txt, windows[p])
            if d: rec.update(d)
            pin = u.get("promptTokenCount", 0) or 0
            tot = u.get("totalTokenCount", 0) or 0
            rec["tok_in"], rec["tok_out"] = pin, max(tot - pin, u.get("candidatesTokenCount", 0) or 0)
        with lk:
            res.append(rec); done["n"] += 1
            if done["n"] % 50 == 0:
                print(f"[cr] fix {done['n']}/{len(jobs)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(fix_one, j) for j in jobs]))

    # baseline: the uncorrected read
    base = {}
    for p in ok:
        s = score(raw[p]["text"], windows[p])
        if s: base[p] = s
    with open(OUT, "w", encoding="utf-8") as f:
        for p in ok:
            f.write(json.dumps({"page": p, "arm": "L0-raw", "level": "L0-raw",
                                "text": raw[p]["text"], **(base.get(p) or {})},
                               ensure_ascii=False) + "\n")
        for r in sorted(res, key=lambda r: (r["arm"], r["page"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    summary = {"pages": len(ok), "arms": {}}
    bl = [base[p] for p in base]
    summary["arms"]["L0-raw"] = {
        "scored": len(bl),
        "cer_median": round(st.median([x["cer"] for x in bl]), 4) if bl else None,
        "recall_median": round(st.median([x["ref_recall"] for x in bl]), 3) if bl else None,
        "yield_median": round(st.median([x["yield"] for x in bl]), 4) if bl else None,
        "false_corr_rate": 0.0}
    for lab, model, think, mode in ARMS:
        arm = f"{lab}@{model.split('-')[-1]}/{think}/{mode}"
        rs = [r for r in res if r["arm"] == arm]
        sc = [r for r in rs if "cer" in r]
        dm = [r for r in rs if "false_corr_rate" in r]
        common = [r for r in sc if r["page"] in base]
        dcer = [r["cer"] - base[r["page"]]["cer"] for r in common]
        dy = [r["yield"] - base[r["page"]]["yield"] for r in common]
        summary["arms"][arm] = {
            "scored": len(sc), "errors": sum(1 for r in rs if r.get("err")),
            "sample_error": next((r["err"] for r in rs if r.get("err")), None),
            "cer_median": round(st.median([r["cer"] for r in sc]), 4) if sc else None,
            "recall_median": round(st.median([r["ref_recall"] for r in sc]), 3) if sc else None,
            "yield_median": round(st.median([r["yield"] for r in sc]), 4) if sc else None,
            "paired_delta_cer": round(st.median(dcer), 4) if dcer else None,
            "cer_improved_on": sum(1 for d in dcer if d < 0), "paired_n": len(dcer),
            "paired_delta_yield": round(st.median(dy), 4) if dy else None,
            "FALSE_CORR_RATE_median": round(st.median([r["false_corr_rate"] for r in dm]), 4) if dm else None,
            "false_corr_total": sum(r["false_corrections"] for r in dm),
            "correct_tokens_total": sum(r["correct_tokens"] for r in dm),
            "touched_wrong_rate_median": round(st.median([r["touched_wrong_rate"] for r in dm]), 4) if dm else None,
            "tok_in_mean": round(st.mean([r.get("tok_in", 0) for r in rs]), 0) if rs else None,
            "tok_out_mean": round(st.mean([r.get("tok_out", 0) for r in rs]), 0) if rs else None,
            "usd_per_page": round(st.mean([r.get("tok_in", 0) for r in rs]) / 1e6 * 1.0
                                  + st.mean([r.get("tok_out", 0) for r in rs]) / 1e6 * 6.0, 5) if rs else None,
            "edits_applied_median": round(st.median([r["edits_applied"] for r in rs
                                                     if "edits_applied" in r]), 1)
                                    if any("edits_applied" in r for r in rs) else None,
        }
    summary["note"] = ("FALSE_CORR_RATE is the deciding number: of tokens the raw read got RIGHT, "
                       "the share the corrector CHANGED. CER can improve purely by modernising "
                       "1911 orthography toward the modern edition, which moves the text AWAY "
                       "from the page. Read both columns together, never CER alone.")
    json.dump(summary, open(SUM, "w"), indent=2)
    print(json.dumps(summary, indent=2), flush=True)
    subprocess.run(["gsutil", "-q", "cp", OUT, SUM, GCS], check=False)

if __name__ == "__main__":
    main()
