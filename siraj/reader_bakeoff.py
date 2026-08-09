#!/usr/bin/env python3
"""Reader bakeoff on REAL newspaper gold: the 102 aligned adl0616 pages.

Every prior reader comparison on this project was run on proxies -- Bustan verse against
Ganjoor, MAKHZAN manuscript nastaliq, naskh print -- or was outright circular (2.5-teacher
gold scoring a 2.5-distilled student). This is the first time the models can be ranked on
the actual target: lithographed multi-column Kabul newspaper pages, scored against a human
typeset edition of the same articles.

Protocol, identical for every arm:
  - same page image (300dpi, the resolution the corpus run used)
  - same prompt, ONE call, no multi-draft, no adjudication -> a clean reader comparison.
    NB the production corpus number came from a 3-draft + adjudication pipeline, so the
    single-call 3.1-pro arm here is NOT that number and is not meant to be.
  - CER over the parallel span located per model against the SAME edition window, so no arm
    inherits another's span.

KNOWN BIAS, stated up front: these 102 pages were SELECTED because 3.1-pro's transcription
aligned well enough for the judge to confirm the pair. That selection favours 3.1-pro. A
different model winning here despite that bias would be strong evidence; 3.1-pro winning is
partly the bias talking. Treat this as a ranking on confirmed-parallel pages, not as an
unbiased estimate of reader accuracy on the whole corpus.
"""
import base64, io, json, os, re, subprocess, sys, threading, time, unicodedata, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from difflib import SequenceMatcher
import pypdfium2 as pdfium

GOLD = os.path.expanduser("~/siraj_gold/gold_pairs.jsonl")
ALIGN = os.path.expanduser("~/siraj_gold/alignment.jsonl")
OUTDIR = os.path.expanduser("~/bakeoff"); os.makedirs(OUTDIR, exist_ok=True)
OUT = os.path.join(OUTDIR, os.environ.get("BAKE_OUT","bakeoff.jsonl"))
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/"
PROJECT = os.environ.get("HTR_PROJECT", "")
DPI, MAXPX, WORKERS = 300, 3500, 10
MODELS = os.environ.get("BAKE_MODELS",
                        "gemini-3.1-pro-preview,gemini-3.6-flash,gemini-2.5-pro,gemini-2.5-flash").split(",")
LIMIT = int(os.environ.get("BAKE_LIMIT", "0"))

SYSTEM = ("You are an expert transcriber of early Afghan printed periodicals (1911-1918, the "
          "Afghanistan Digital Library). The text is Persian/Dari in Arabic script, lithographed "
          "nastaliq, often in multiple columns. Read right-to-left in correct reading order.")
TUNED_SYS = ("You are an expert transcriber of early Afghan print (1871-1930): Persian/Dari and "
             "Pashto in Arabic script (nastaliq/naskh), much of it lithographed from manuscript. "
             "Read right-to-left in correct reading order.")
TUNED_PROMPT = ("Transcribe this page faithfully. Preserve original spelling, capitalization, "
                "punctuation, and abbreviations; non-Latin text stays in its original script. "
                "Output ONLY the transcription.")
USE_TUNED_PROMPT = os.environ.get("BAKE_PROMPT", "generic") == "tuned"

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

try:
    from rapidfuzz.distance import Levenshtein as _RF
    lev = _RF.distance
except ImportError:
    raise SystemExit("rapidfuzz required")

def parallel_span(aw, bw):
    sm = SequenceMatcher(None, aw, bw, autojunk=False)
    bl = [b for b in sm.get_matching_blocks() if b.size >= 2]
    if not bl:
        return None
    return (min(b.a for b in bl), max(b.a + b.size for b in bl),
            min(b.b for b in bl), max(b.b + b.size for b in bl))

_tok = {"v": None, "e": 0.0}; _lk = threading.Lock(); _err = {}
def token():
    with _lk:
        if _tok["v"] and time.time() < _tok["e"]:
            return _tok["v"]
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        _tok["e"] = time.time() + 1500
        return _tok["v"]

AOAI_ENDPOINT = os.environ.get("AOAI_ENDPOINT", os.environ.get("HTR_AZURE_ENDPOINT", ""))
AOAI_API = os.environ.get("AOAI_API_VERSION", "2025-04-01-preview")

def read_azure(deployment, b64, sys_txt, usr_txt, retries=3):
    """Azure arm. Note the API differences that bit before: max_completion_tokens (NOT
    max_tokens), no temperature, and the image goes in as a data URI."""
    key = os.environ.get("AOAI_KEY", "")
    if not key:
        return "", "FAILED:no AOAI_KEY"
    url = f"{AOAI_ENDPOINT}/openai/deployments/{deployment}/chat/completions?api-version={AOAI_API}"
    body = {"messages": [{"role": "system", "content": sys_txt},
                         {"role": "user", "content": [
                             {"type": "text", "text": usr_txt},
                             {"type": "image_url",
                              "image_url": {"url": "data:image/jpeg;base64," + b64}}]}],
            "max_completion_tokens": 16384}
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "api-key": key, "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            txt = (d.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            if txt.strip():
                return txt.strip(), (d.get("choices") or [{}])[0].get("finish_reason", "")
        except Exception as e:
            _err["last"] = str(e)[:200]
            time.sleep(min(2 ** a, 20))
    return "", "FAILED:" + _err.get("last", "")[:120]

def read(model, b64, retries=3):
    if model.startswith("gpt-"):
        sys_txt, usr_txt = (TUNED_SYS, TUNED_PROMPT) if USE_TUNED_PROMPT else (SYSTEM, RULES)
        return read_azure(model, b64, sys_txt, usr_txt, retries)
    if model.startswith("projects/"):          # a tuned-model endpoint resource path
        url = f"https://us-central1-aiplatform.googleapis.com/v1/{model}:generateContent"
    else:
        glob = model.startswith("gemini-3")
        host = "aiplatform.googleapis.com" if glob else "us-central1-aiplatform.googleapis.com"
        loc = "global" if glob else "us-central1"
        url = f"https://{host}/v1/projects/{PROJECT}/locations/{loc}/publishers/google/models/{model}:generateContent"
    sys_txt, usr_txt = (TUNED_SYS, TUNED_PROMPT) if USE_TUNED_PROMPT else (SYSTEM, RULES)
    body = {"contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": b64}}, {"text": usr_txt}]}],
            "systemInstruction": {"parts": [{"text": sys_txt}]},
            "generationConfig": {"maxOutputTokens": 16384, "temperature": 0.1}}
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                d = json.loads(r.read())
            c = (d.get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in (c.get("content") or {}).get("parts") or []).strip()
            if txt:
                return txt, c.get("finishReason", "")
        except Exception as e:
            _err["last"] = str(e)[:200]
            time.sleep(min(2 ** a, 20))
    return "", "FAILED:" + _err.get("last", "")[:120]

def main():
    gold = [json.loads(l) for l in open(GOLD, encoding="utf-8")]
    windows = {}
    for l in open(ALIGN, encoding="utf-8"):
        a = json.loads(l)
        if a.get("edition_text"):
            windows[a["page"]] = a["edition_text"]
    pages = [g["page"] for g in gold if g["page"] in windows]
    # gold_pairs.jsonl is written sorted by cer_parallel_span ASCENDING, so a plain
    # head-of-file slice takes the EASIEST pages, not a sample. Measured on the 102 pairs:
    # first 40 have median gold CER 0.232 vs 0.462 for the remaining 62 -- twice as easy.
    # Every 40-page number produced before 2026-08-08 was scored on that easy head, so its
    # absolute CER is ~2x optimistic (within-run RANKINGS survive, because all arms shared
    # the same pages). Subsample deterministically across the whole difficulty range instead.
    if LIMIT and LIMIT < len(pages):
        step = len(pages) / LIMIT
        pages = [pages[int(i * step)] for i in range(LIMIT)]
        print(f"[bake] subsampled {LIMIT} of {len(gold)} gold pages evenly across the "
              f"difficulty-sorted file (NOT the easy head)", flush=True)
    print(f"[bake] {len(pages)} gold pages x {len(MODELS)} models", flush=True)

    pdf_path = os.path.expanduser("~/siraj/afghan/pdf/adl0616.pdf")
    if not os.path.exists(pdf_path):
        os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
        url = "https://afghanistandl.nyu.edu/pdf/adl0616_download.pdf"
        print("[bake] downloading adl0616 ...", flush=True)
        with urllib.request.urlopen(urllib.request.Request(
                url, headers={"User-Agent": "Mozilla/5.0 research"}), timeout=900) as r, open(pdf_path, "wb") as o:
            o.write(r.read())
    doc = pdfium.PdfDocument(pdf_path)

    imgs = {}
    for p in pages:                                   # pdfium is not thread-safe: render serially
        bmp = doc[p - 1].render(scale=DPI / 72)
        pil = bmp.to_pil().convert("L")
        w, h = pil.size
        if max(w, h) > MAXPX:
            s = MAXPX / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
        buf = io.BytesIO(); pil.save(buf, "JPEG", quality=92)
        imgs[p] = base64.b64encode(buf.getvalue()).decode()
    doc.close()
    print(f"[bake] rendered {len(imgs)} pages", flush=True)

    res, lk, done = [], threading.Lock(), {"n": 0}
    jobs = [(m, p) for m in MODELS for p in pages]

    def work(job):
        model, p = job
        txt, fin = read(model, imgs[p])
        rec = {"page": p, "model": model, "finish": fin, "chars": len(txt)}
        if txt:
            aw, bw = norm(txt), norm(windows[p])
            sp = parallel_span(aw, bw)
            if sp and min(sp[1] - sp[0], sp[3] - sp[2]) >= 60:
                A = " ".join(aw[sp[0]:sp[1]]); B = " ".join(bw[sp[2]:sp[3]])
                rec["cer"] = round(lev(A, B) / max(len(A), len(B)), 4)
                rec["span_tokens"] = sp[1] - sp[0]
                rec["span_coverage"] = round((sp[1] - sp[0]) / max(1, len(aw)), 3)
                # RECALL against the reference: what fraction of the edition window the model
                # actually recovered. CER over a span gives partial credit, so a model that
                # simply omits the hard half of a page can post a better CER while reading LESS.
                # ref_recall is the omission check that makes the CER ranking interpretable.
                rec["ref_recall"] = round((sp[3] - sp[2]) / max(1, len(bw)), 3)
                rec["out_tokens"] = len(aw)
                rec["ref_tokens"] = len(bw)
        with lk:
            res.append(rec); done["n"] += 1
            if done["n"] % 40 == 0:
                print(f"[bake] {done['n']}/{len(jobs)}", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, j) for j in jobs]))

    with open(OUT, "w", encoding="utf-8") as f:
        for r in sorted(res, key=lambda r: (r["model"], r["page"])):
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    import statistics as st
    summary = {}
    for m in MODELS:
        rs = [r for r in res if r["model"] == m]
        c = sorted(r["cer"] for r in rs if "cer" in r)
        summary[m] = {
            "pages": len(rs), "scored": len(c), "failed": sum(1 for r in rs if str(r["finish"]).startswith("FAILED")),
            "cer_median": round(st.median(c), 4) if c else None,
            "cer_p25": round(c[len(c) // 4], 4) if c else None,
            "cer_p75": round(c[3 * len(c) // 4], 4) if c else None,
            "span_coverage_median": round(st.median([r["span_coverage"] for r in rs if "span_coverage" in r]), 3) if c else None,
            "ref_recall_median": round(st.median([r["ref_recall"] for r in rs if "ref_recall" in r]), 3) if c else None,
            "out_tokens_median": round(st.median([r["out_tokens"] for r in rs if "out_tokens" in r]), 1) if c else None,
            "chars_median": round(st.median([r["chars"] for r in rs]), 1),
        }
    # head-to-head on pages BOTH models scored, which is what a ranking actually needs
    common = set.intersection(*[{r["page"] for r in res if r["model"] == m and "cer" in r} for m in MODELS]) if len(MODELS) > 1 else set()
    h2h = {}
    for m in MODELS:
        c = sorted(r["cer"] for r in res if r["model"] == m and r["page"] in common)
        h2h[m] = round(st.median(c), 4) if c else None
    out = {"summary": summary, "common_pages": len(common), "head_to_head_cer_median": h2h,
           "protocol": "single call, identical prompt, 300dpi; CER over per-model parallel span vs the same edition window",
           "bias": "pages were selected because 3.1-pro aligned well enough to be judge-confirmed; this favours 3.1-pro"}
    json.dump(out, open(os.path.join(OUTDIR, os.environ.get("BAKE_SUM","bakeoff_summary.json")), "w"), indent=2)
    print(json.dumps(out, indent=2), flush=True)
    subprocess.run(["gsutil", "-q", "cp", OUT, os.path.join(OUTDIR, os.environ.get("BAKE_SUM","bakeoff_summary.json")), GCS], check=False)

if __name__ == "__main__":
    main()
