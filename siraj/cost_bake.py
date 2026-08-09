#!/usr/bin/env python3
"""Cost/accuracy frontier: how cheaply can we read a page without losing quality?

Measured on the corpus runs: a page bills ~4,743 input and ~8,020 output tokens, but the
transcription itself is only ~2,100 tokens. **~73% of the output bill is REASONING**, which
Gemini charges at the output rate. For OCR that is plausibly wasted money -- but nobody has
checked whether turning thinking down costs accuracy. At 63,000 remaining pages the answer is
worth roughly $7,000 of credits, so it is worth an hour.

Every arm: ONE whole-page call, identical prompt, identical render, scored identically
(CER over the parallel span + ref_recall + yield). The only variables are the model and the
thinking level. Each response's usageMetadata is captured, so cost is MEASURED per arm and
not extrapolated from another run.

Reports the thing that actually decides this: $ per page, and $ per unit of effective yield.
"""
import base64, io, json, os, re, statistics as st, subprocess, sys, threading, time
import unicodedata, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
from math import comb
import pypdfium2 as pdfium
from rapidfuzz.distance import Levenshtein

HOME = os.path.expanduser("~")
GOLD = os.path.join(HOME, "siraj_gold/gold_pairs.jsonl")
ALIGN = os.path.join(HOME, "siraj_gold/alignment.jsonl")
PDF = os.path.join(HOME, "siraj/afghan/pdf/adl0616.pdf")
OUTDIR = os.path.join(HOME, "cost_bake"); os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, os.environ.get("CB_OUT", "cost_bake.jsonl"))
SUM = os.path.join(OUTDIR, os.environ.get("CB_SUM", "cost_bake_summary.json"))
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/"
PROJECT = os.environ.get("HTR_PROJECT", "")
DPI, MAXPX = 300, 3500
LIMIT = int(os.environ.get("CB_LIMIT", "0"))
WORKERS = int(os.environ.get("CB_WORKERS", "10"))

# Published Vertex list price, $ per 1M tokens (fetched 2026-08-08). Global endpoint rates,
# which is what 3.x uses. Keep this table honest -- every cost number below comes from it.
PRICE = {
    "gemini-3.1-pro-preview": (2.00, 12.00),
    "gemini-3.6-flash":       (1.50,  7.50),
    "gemini-3.1-flash-lite":  (0.25,  1.50),
    "gemini-2.5-pro":         (1.25, 10.00),
    "gemini-2.5-flash":       (0.30,  2.50),
}

# (label, model, thinking_level or None for the model default)
ARMS = json.loads(os.environ["CB_ARMS"]) if os.environ.get("CB_ARMS") else [
    ["pro-default",        "gemini-3.1-pro-preview", None],
    ["pro-low",            "gemini-3.1-pro-preview", "low"],
    ["flash-default",      "gemini-3.6-flash",       None],
    ["flash-low",          "gemini-3.6-flash",       "low"],
    ["lite-default",       "gemini-3.1-flash-lite",  None],
    ["lite-minimal",       "gemini-3.1-flash-lite",  "minimal"],
]

SYSTEM = ("You are an expert transcriber of early Afghan printed periodicals (1911-1918, the "
          "Afghanistan Digital Library). The text is Persian/Dari in Arabic script, lithographed "
          "nastaliq, often in multiple columns. Read right-to-left in correct reading order.")
RULES = """Transcribe this page.
- Output the text in its ORIGINAL Arabic script, preserving orthography. Do NOT translate or romanize.
- Preserve reading order and structure; keep each verse on its own line; reflow hard-wrapped prose.
- Unclear word -> best guess as [word?]. Wholly illegible -> [ILL].
- Output ONLY the transcription. No commentary, no markdown, no code fences."""

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

_tok = {"v": None, "e": 0.0}; _lk = threading.Lock()
def token():
    with _lk:
        if _tok["v"] and time.time() < _tok["e"]:
            return _tok["v"]
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        _tok["e"] = time.time() + 1500
        return _tok["v"]

def call(model, thinking, b64, retries=3):
    """Returns (text, finish, usageMetadata dict, error). 3.x is served ONLY on global."""
    host = "aiplatform.googleapis.com"
    url = (f"https://{host}/v1/projects/{PROJECT}/locations/global"
           f"/publishers/google/models/{model}:generateContent")
    gc = {"maxOutputTokens": 16384}
    if thinking:
        gc["thinkingConfig"] = {"thinkingLevel": thinking}
    body = {"contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": b64}}, {"text": RULES}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "generationConfig": gc}
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
            return txt, c.get("finishReason", ""), d.get("usageMetadata", {}) or {}, ""
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:300].decode(errors='replace')}"
            if e.code == 400:                      # bad thinking level -> do not retry
                return "", "BAD_REQUEST", {}, last
            if e.code in (401, 403):
                _tok["v"] = None
            time.sleep(3 * (a + 1))
        except Exception as e:
            last = f"{type(e).__name__}: {str(e)[:200]}"
            time.sleep(3 * (a + 1))
    return "", "FAILED", {}, last

def usd(model, u):
    """Cost of one call from its OWN usageMetadata. thoughtsTokenCount is billed as output;
    Vertex sometimes reports it separately and sometimes folds it into candidatesTokenCount,
    so take the max of (candidates+thoughts) and total-prompt to avoid undercounting."""
    pi, po = PRICE[model]
    pin = u.get("promptTokenCount", 0) or 0
    cand = u.get("candidatesTokenCount", 0) or 0
    thoughts = u.get("thoughtsTokenCount", 0) or 0
    total = u.get("totalTokenCount", 0) or 0
    out = max(cand + thoughts, total - pin, cand)
    return pin * pi / 1e6 + out * po / 1e6, pin, out

def sign_test(d, better=lambda x: x > 0):
    """Two-sided binomial sign test.

    NB an earlier version summed only the UPPER tail, so an arm that LOST most pages came back
    p=1.0 and read as 'no difference' when it was significantly WORSE. Take the smaller tail
    and double it. Always report `wins` alongside p so the direction is visible."""
    n = sum(1 for x in d if x != 0); w = sum(1 for x in d if better(x))
    if not n:
        return {"n": 0, "wins": 0, "p": None}
    k = min(w, n - w)
    p = 2 * sum(comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return {"n": n, "wins": w, "p": round(min(1.0, p), 6),
            "direction": "better" if w > n / 2 else ("worse" if w < n / 2 else "tie")}

def main():
    gold = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
    windows = {}
    for l in open(ALIGN, encoding="utf-8"):
        a = json.loads(l)
        if a.get("edition_text"):
            windows[a["page"]] = a["edition_text"]
    pages = [g["page"] for g in gold if g["page"] in windows]
    if LIMIT and LIMIT < len(pages):                # even subsample, never the easy head
        step = len(pages) / LIMIT
        pages = [pages[int(i * step)] for i in range(LIMIT)]
    print(f"[cb] {len(pages)} pages x {len(ARMS)} arms = {len(pages)*len(ARMS)} calls", flush=True)

    doc = pdfium.PdfDocument(PDF)
    imgs = {}
    for p in pages:                                # pdfium is not thread-safe
        pil = doc[p - 1].render(scale=DPI / 72).to_pil().convert("L")
        w, h = pil.size
        if max(w, h) > MAXPX:
            s = MAXPX / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
        buf = io.BytesIO(); pil.save(buf, "JPEG", quality=92)
        imgs[p] = base64.b64encode(buf.getvalue()).decode()
    doc.close()
    print(f"[cb] rendered {len(imgs)} pages", flush=True)

    res, lk, done = [], threading.Lock(), {"n": 0}
    jobs = [(a, p) for a in ARMS for p in pages]

    def work(job):
        (label, model, think), p = job
        txt, fin, u, err = call(model, think, imgs[p])
        cost, tin, tout = usd(model, u) if u else (0.0, 0, 0)
        rec = {"page": p, "arm": label, "model": model, "thinking": think,
               "finish": fin, "usd": round(cost, 6), "tok_in": tin, "tok_out": tout}
        if err:
            rec["err"] = err[:200]
        if txt:
            s = score(txt, windows[p])
            if s:
                rec.update(s)
        with lk:
            res.append(rec); done["n"] += 1
            if done["n"] % 50 == 0:
                print(f"[cb] {done['n']}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, j) for j in jobs]))

    with open(OUT, "w", encoding="utf-8") as f:
        for r in sorted(res, key=lambda r: (r["arm"], r["page"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    PAGES_LEFT = 63_000
    summary = {"pages": len(pages), "arms": {}, "corpus_pages_assumed": PAGES_LEFT}
    for label, model, think in ARMS:
        rs = [r for r in res if r["arm"] == label]
        sc = [r for r in rs if "cer" in r]
        bad = [r for r in rs if r.get("err")]
        cpp = st.mean([r["usd"] for r in rs]) if rs else None
        ym = st.median([r["yield"] for r in sc]) if sc else None
        summary["arms"][label] = {
            "model": model, "thinking": think,
            "calls": len(rs), "scored": len(sc), "errors": len(bad),
            "sample_error": (bad[0]["err"] if bad else None),
            "cer_median": round(st.median([r["cer"] for r in sc]), 4) if sc else None,
            "recall_median": round(st.median([r["ref_recall"] for r in sc]), 3) if sc else None,
            "yield_median": ym,
            "tok_in_mean": round(st.mean([r["tok_in"] for r in rs]), 0) if rs else None,
            "tok_out_mean": round(st.mean([r["tok_out"] for r in rs]), 0) if rs else None,
            "usd_per_page": round(cpp, 5) if cpp else None,
            "usd_63k_corpus": round(cpp * PAGES_LEFT, 0) if cpp else None,
            "usd_per_yield_point": round(cpp / ym, 5) if (cpp and ym) else None,
        }
    # paired accuracy vs the incumbent, so a cheap arm has to prove it is not worse
    base = ARMS[0][0]
    by = {}
    for r in res:
        if "yield" in r:
            by.setdefault(r["arm"], {})[r["page"]] = r
    summary["paired_vs_" + base] = {}
    for label, _, _ in ARMS[1:]:
        common = set(by.get(label, {})) & set(by.get(base, {}))
        if not common:
            continue
        d = [by[label][p]["yield"] - by[base][p]["yield"] for p in common]
        summary["paired_vs_" + base][label] = {
            "n": len(common), "delta_yield_median": round(st.median(d), 4),
            "sign_test": sign_test(d)}
    summary["note"] = ("usd is MEASURED from each response's usageMetadata at published Vertex "
                       "list price, not extrapolated. usd_per_yield_point = cost normalised by "
                       "quality, the number to actually choose on.")
    json.dump(summary, open(SUM, "w"), indent=2)
    print(json.dumps(summary, indent=2), flush=True)
    subprocess.run(["gsutil", "-q", "cp", OUT, SUM, GCS], check=False)

if __name__ == "__main__":
    main()
