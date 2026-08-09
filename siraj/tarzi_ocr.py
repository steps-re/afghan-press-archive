#!/usr/bin/env python3
"""Phase A: read the 757pp modern-typeset edition of Maqalat-e Mahmud Tarzi.

This book collects Tarzi's own articles as they ran in Siraj al-Akhbar (ADL adl0616,
Kabul 1911-1918, 1786 images). Clean letterpress naskh, so the 2.5 family wins here
(benchmarked naskh print CER: 2.5-pro 0.029 vs 3.1-pro 0.095 -- the ranking is the
INVERSE of the nastaliq lithograph case, which is why this run pins 2.5-pro).

Output is the reference side of the alignment: machine-read but near-clean, versus the
lithograph side which is the hard read. Resumable per page.
"""
import base64, io, json, os, re, subprocess, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import pypdfium2 as pdfium

PDF      = os.path.expanduser("~/tarzi/maqalat_tarzi.pdf")
OUTDIR   = os.path.expanduser("~/tarzi_out")
OUT      = os.path.join(OUTDIR, "tarzi_pages.jsonl")
GCS = os.environ.get("HTR_BUCKET", "").rstrip("/") + "/tarzi/"
MODEL    = os.environ.get("TARZI_MODEL", "gemini-2.5-pro")
PROJECT = os.environ.get("HTR_PROJECT", "")
DPI      = int(os.environ.get("TARZI_DPI", "300"))
WORKERS  = int(os.environ.get("TARZI_WORKERS", "8"))
LIMIT    = int(os.environ.get("TARZI_LIMIT", "0"))   # 0 = all pages

SYSTEM = (
    "You are transcribing a modern printed Persian book: the collected articles of "
    "Mahmud Tarzi, editor of the Kabul periodical Siraj al-Akhbar. The text is Persian/Dari "
    "in Arabic script, set in clean typeset naskh. Read right-to-left in correct reading order."
)
RULES = """Rules (follow exactly):
- Transcribe the page's BODY TEXT verbatim in the original Arabic script. Do NOT translate, do NOT romanize, do NOT summarize.
- OMIT the running header and the page number.
- Preserve structure: headings on their own lines; keep each verse/hemistich of poetry on its own line; blank line between paragraphs.
- REFLOW running prose: rejoin words hard-wrapped across a line break. Start a new line only at a real structural break.
- The typesetter stretches letters (kashida) to justify lines. Transcribe the WORD, never the stretching.
- Unclear word -> best guess as [word?]. Wholly illegible -> [ILL].
- A page that is a photograph/plate/facsimile with no body text -> output exactly [PLATE].
- A blank page -> output exactly [BLANK PAGE].
- Output ONLY the transcription. No commentary, no markdown, no code fences."""

_tok = {"v": None, "e": 0.0}; _lock = threading.Lock()
def token():
    with _lock:
        if _tok["v"] and time.time() < _tok["e"]:
            return _tok["v"]
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        _tok["e"] = time.time() + 1500
        return _tok["v"]

def gemini(img_b64, retries=4, max_tokens=8192):
    url = (f"https://us-central1-aiplatform.googleapis.com/v1/projects/{PROJECT}"
           f"/locations/us-central1/publishers/google/models/{MODEL}:generateContent")
    body = {"contents": [{"role": "user", "parts": [
                {"inlineData": {"mimeType": "image/jpeg", "data": img_b64}},
                {"text": RULES}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.1}}
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
            if txt:
                return txt, c.get("finishReason", "")
            last = f"empty (finishReason={c.get('finishReason')})"
        except Exception as e:
            last = str(e)[:200]
        time.sleep(min(2 ** a, 30))
    raise RuntimeError(f"gemini failed after retries: {last}")

# --- normalization: the alignment side must be orthographically canonical ---
TATWEEL = "ـ"
MAP = {"ي": "ی", "ى": "ی",   # arabic yeh / alef maqsura -> persian yeh
       "ك": "ک",                        # arabic kaf -> persian keheh
       "ۀ": "ه‌",                  # heh with yeh above -> heh + ZWNJ
       "​": "", "﻿": ""}
def normalize(t):
    t = t.replace(TATWEEL, "")
    for a, b in MAP.items():
        t = t.replace(a, b)
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return "\n".join(ln.strip() for ln in t.split("\n")).strip()

def main():
    os.makedirs(OUTDIR, exist_ok=True)
    if not os.path.exists(PDF):
        os.makedirs(os.path.dirname(PDF), exist_ok=True)
        subprocess.run(["gsutil", "-q", "cp", GCS + "maqalat_tarzi.pdf", PDF], check=True)

    doc = pdfium.PdfDocument(PDF)
    n = len(doc)
    pages = list(range(n))[: LIMIT or n]

    done = set()
    if os.path.exists(OUT):
        for ln in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(ln)["page"])
            except Exception:
                pass
    todo = [p for p in pages if p not in done]
    print(f"[tarzi] {n} pages | {len(done)} done | {len(todo)} to do | model={MODEL} dpi={DPI}", flush=True)

    wlock = threading.Lock()
    fh = open(OUT, "a", encoding="utf-8")
    counter = {"n": 0, "err": 0}

    def render(p):
        bmp = doc[p].render(scale=DPI / 72)
        buf = io.BytesIO()
        bmp.to_pil().convert("RGB").save(buf, "JPEG", quality=92)
        return base64.b64encode(buf.getvalue()).decode()

    def work(p):
        try:
            with wlock:                       # pdfium doc access is not thread-safe
                b64 = render(p)
            raw, fr = gemini(b64)
            rec = {"page": p, "printed_page": p - 21, "model": MODEL,
                   "finish": fr, "raw_chars": len(raw), "text": normalize(raw)}
        except Exception as e:
            rec = {"page": p, "error": str(e)[:300]}
        with wlock:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush()
            counter["n"] += 1
            if "error" in rec:
                counter["err"] += 1
            if counter["n"] % 25 == 0:
                print(f"[tarzi] {counter['n']}/{len(todo)} ({counter['err']} err)", flush=True)
                subprocess.run(["gsutil", "-q", "cp", OUT, GCS], check=False)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, p) for p in todo]))
    fh.close()

    recs = [json.loads(l) for l in open(OUT, encoding="utf-8")]
    ok = [r for r in recs if "text" in r]
    full = "\n\n".join(r["text"] for r in sorted(ok, key=lambda r: r["page"])
                       if r["text"] not in ("[PLATE]", "[BLANK PAGE]"))
    open(os.path.join(OUTDIR, "tarzi_full.txt"), "w", encoding="utf-8").write(full)
    print(f"[tarzi] DONE pages_ok={len(ok)} errors={len(recs)-len(ok)} chars={len(full):,}", flush=True)
    subprocess.run(["gsutil", "-q", "cp", OUT, GCS], check=False)
    subprocess.run(["gsutil", "-q", "cp", os.path.join(OUTDIR, "tarzi_full.txt"), GCS], check=False)

if __name__ == "__main__":
    main()
