#!/usr/bin/env python3
"""Production corpus reader: Vertex BATCH inference at thinkingLevel low.

Config is the one the measurements actually support (see RESULTS.md):
  - gemini-3.1-pro-preview, thinkingLevel "low"  -- 9x cheaper than default thinking with a
    paired yield delta of -0.0012 (p=0.53). "minimal" is NOT accepted by Pro (HTTP 400).
  - BATCH mode, global location -- flat 50% off input and output. Verified working with
    fileData gs:// URIs; batch is region-submitted and 3.x exists ONLY at `global`.
  - Do NOT substitute a cheaper model. flash / flash-lite lose on 75-80% of pages (p<1e-6)
    despite similar-looking median yields.
  - No blank-page prefilter: blank pages here are DARK scans, not white paper, and no pixel
    rule separates them safely (30% recall at best, worth ~$4). Let the model return
    [BLANK PAGE], which it does reliably.

~$500 for the remaining ~63,000 pages, versus $9,030 for the naive online default-thinking read.

Resumable by construction: every page already present in the output file is skipped, so a
killed run is restarted by re-running the same command.

INPUT: a catalog TSV with columns including `book` and `pages` (the ADL catalogue,
`adl_catalog_full.tsv`, 581 rows). Pass --catalog. Books listed in --done are skipped.
"""
import argparse, io, json, os, subprocess, sys, time, urllib.request, urllib.error
import pypdfium2 as pdfium

PROJECT = os.environ.get("HTR_PROJECT", "")
HOST = "aiplatform.googleapis.com"          # global has NO region prefix
LOCATION = "global"                          # 3.x publisher models exist only here
MODEL = "gemini-3.1-pro-preview"
THINKING = "low"
DPI, MAXPX, JPEGQ = 300, 3500, 92
CHUNK = 2000                                 # pages per batch job
PDF_URL = "https://afghanistandl.nyu.edu/pdf/{book}_download.pdf"

# published Vertex BATCH price, $/1M tokens (= 50% of standard), fetched 2026-08-08
PRICE_IN, PRICE_OUT = 1.00, 6.00

SYSTEM = ("You are an expert transcriber of early Afghan printed periodicals (1911-1918, the "
          "Afghanistan Digital Library). The text is Persian/Dari in Arabic script, lithographed "
          "nastaliq, often in multiple columns. Read right-to-left in correct reading order.")
RULES = """Transcribe this page.
- Output the text in its ORIGINAL Arabic script, preserving orthography. Do NOT translate or romanize.
- Preserve reading order and structure; keep each verse on its own line; reflow hard-wrapped prose.
- Unclear word -> best guess as [word?]. Wholly illegible -> [ILL].
- If the page is blank or a plate with no text, output exactly [BLANK PAGE].
- Output ONLY the transcription. No commentary, no markdown, no code fences."""

def sh(*a, **kw):
    return subprocess.run(a, capture_output=True, text=True, **kw)

def tok():
    return subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()

def api(method, url, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {tok()}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        return json.loads(r.read())

def fetch_pdf(book, pdf_dir):
    fp = os.path.join(pdf_dir, f"{book}.pdf")
    if os.path.exists(fp) and os.path.getsize(fp) > 10_000:
        return fp
    os.makedirs(pdf_dir, exist_ok=True)
    url = PDF_URL.format(book=book)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 research"})
    with urllib.request.urlopen(req, timeout=1800) as r, open(fp, "wb") as o:
        o.write(r.read())
    return fp

def render_and_upload(book, pdf_path, pages, gcs_img, workdir):
    """Render each page once and push to GCS. Images are referenced by URI in the batch
    request -- inlining base64 for 63k pages would mean ~30GB of JSONL."""
    doc = pdfium.PdfDocument(pdf_path)
    n = len(doc)
    local = os.path.join(workdir, book); os.makedirs(local, exist_ok=True)
    todo = [p for p in pages if 1 <= p <= n]
    made = []
    for p in todo:
        fp = os.path.join(local, f"{p:05d}.jpg")
        if not os.path.exists(fp):
            pil = doc[p - 1].render(scale=DPI / 72).to_pil().convert("L")
            w, h = pil.size
            if max(w, h) > MAXPX:
                s = MAXPX / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
            pil.save(fp, "JPEG", quality=JPEGQ)
        made.append((p, fp))
    doc.close()
    # one bulk copy beats 2,000 round trips
    r = sh("gcloud", "storage", "cp", "-r", local, gcs_img.rsplit("/", 1)[0] + "/",
           f"--project={PROJECT}")
    if r.returncode != 0:
        raise RuntimeError(f"image upload failed for {book}: {r.stderr[:300]}")
    return [(p, f"{gcs_img}/{p:05d}.jpg") for p, _ in made]

def submit_batch(in_uri, out_prefix, tag):
    body = {"displayName": f"htr-{tag}",
            "model": f"publishers/google/models/{MODEL}",
            "inputConfig": {"instancesFormat": "jsonl", "gcsSource": {"uris": [in_uri]}},
            "outputConfig": {"predictionsFormat": "jsonl",
                             "gcsDestination": {"outputUriPrefix": out_prefix}}}
    j = api("POST", f"https://{HOST}/v1/projects/{PROJECT}/locations/{LOCATION}"
                    f"/batchPredictionJobs", body)
    return j["name"]

def wait(name, poll=60):
    TERM = {"JOB_STATE_SUCCEEDED", "JOB_STATE_FAILED", "JOB_STATE_CANCELLED", "JOB_STATE_EXPIRED"}
    while True:
        j = api("GET", f"https://{HOST}/v1/{name}")
        s = j.get("state")
        if s in TERM:
            return s, j
        time.sleep(poll)

def collect(out_prefix, book_of):
    """Read predictions back. Batch output preserves request order per shard but NOT globally,
    so pages are recovered from the image URI in the echoed request, never from line order."""
    ls = sh("gcloud", "storage", "ls", "-r", out_prefix, f"--project={PROJECT}")
    rows, usage = [], {"in": 0, "out": 0}
    for uri in ls.stdout.split():
        if not uri.endswith(".jsonl"):
            continue
        c = sh("gcloud", "storage", "cat", uri, f"--project={PROJECT}")
        for line in c.stdout.splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            req, resp = d.get("request", {}), d.get("response", {})
            # The echoed request may come back in snake_case, and the key can be present but
            # null, so probe both spellings and tolerate None rather than indexing blind.
            img = ""
            for part in (req.get("contents") or [{}])[0].get("parts", []) or []:
                fd = part.get("fileData") or part.get("file_data") or {}
                img = fd.get("fileUri") or fd.get("file_uri") or img
            if not img:
                continue
            book = book_of.get(img, "")
            page = int(os.path.basename(img).split(".")[0])
            txt = ""
            try:
                txt = "".join(p.get("text", "") for p in
                              resp["candidates"][0]["content"]["parts"]).strip()
            except Exception:
                pass
            u = resp.get("usageMetadata", {}) or {}
            pin = u.get("promptTokenCount", 0) or 0
            pout = max((u.get("candidatesTokenCount", 0) or 0) + (u.get("thoughtsTokenCount", 0) or 0),
                       (u.get("totalTokenCount", 0) or 0) - pin)
            usage["in"] += pin; usage["out"] += pout
            rows.append({"book": book, "page": page, "text": txt,
                         "status": d.get("status", ""), "tok_in": pin, "tok_out": pout})
    return rows, usage

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--catalog", help="TSV with book + pages columns (adl_catalog_full.tsv)")
    ap.add_argument("--books", help="comma-separated book ids, overrides --catalog")
    ap.add_argument("--pages", help="explicit page range a-b, single book only (validation)")
    ap.add_argument("--done", default="", help="file of already-read book ids, one per line")
    ap.add_argument("--out", default=os.path.expanduser("~/corpus/transcriptions.jsonl"))
    ap.add_argument("--gcs", default=os.environ.get("HTR_BUCKET", "").rstrip("/") + "/corpus")
    ap.add_argument("--workdir", default=os.path.expanduser("~/corpus/work"))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    os.makedirs(a.workdir, exist_ok=True)

    done_books = set()
    if a.done and os.path.exists(a.done):
        done_books = {l.strip() for l in open(a.done) if l.strip()}

    # resume: anything already transcribed is never re-read
    have = set()
    if os.path.exists(a.out):
        for l in open(a.out, encoding="utf-8"):
            try:
                r = json.loads(l); have.add((r["book"], r["page"]))
            except Exception:
                pass
    print(f"[cb] resume: {len(have)} pages already in {a.out}", flush=True)

    work, est_pages = [], {}
    if a.books:
        for b in a.books.split(","):
            b = b.strip()
            if not b or b in done_books:
                continue
            if a.pages:
                lo, hi = (int(x) for x in a.pages.split("-"))
                work.append((b, list(range(lo, hi + 1))))
            else:
                work.append((b, None))
    elif a.catalog:
        import csv
        with open(a.catalog) as f:
            for row in csv.DictReader(f, delimiter="\t"):
                b = (row.get("book") or row.get("id") or "").strip()
                if not b or b in done_books:
                    continue
                try:
                    n = int(row.get("pages") or row.get("images") or 0)
                except ValueError:
                    n = 0
                # `est_pages` is a SIZE-DERIVED ESTIMATE and must never become the page list --
                # it is only good enough to cost a run. Real page counts come from the PDF.
                try:
                    est_pages[b] = int(row.get("est_pages") or 0)
                except ValueError:
                    pass
                work.append((b, list(range(1, n + 1)) if n else None))
    else:
        raise SystemExit("need --books or --catalog")

    print(f"[cb] {len(work)} books to read", flush=True)
    if a.dry_run:
        total = sum(len(p) if p else est_pages.get(b, 0) for b, p in work)
        est = total * (1271 * PRICE_IN / 1e6 + 1216 * PRICE_OUT / 1e6)   # measured per-page
        print(f"[cb] DRY RUN: {len(work)} books, ~{total:,} pages, est ${est:,.0f} at batch price")
        print(f"[cb] (page counts are size-derived estimates; the run uses the real PDF count)")
        return 0

    grand = {"in": 0, "out": 0, "pages": 0}
    skipped = []
    pending, book_of, chunk_no = [], {}, 0     # pages accumulated ACROSS books

    def flush_chunk(force=False):
        """Submit one batch job per CHUNK pages, pooled across books.

        Chunking per-book would mean ~580 jobs for a collection whose median volume is ~100
        pages, and each job carries fixed queue overhead -- the run would be mostly waiting.
        Pooling gives ~26 jobs for the whole corpus."""
        nonlocal pending, book_of, chunk_no
        if not pending or (len(pending) < CHUNK and not force):
            return
        batch, pending = pending[:CHUNK], pending[CHUNK:]
        tag = f"c{chunk_no:04d}"; chunk_no += 1
        lines = [json.dumps({"request": {
            "contents": [{"role": "user", "parts": [
                {"fileData": {"mimeType": "image/jpeg", "fileUri": u}},
                {"text": RULES}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 16384,
                                 "thinkingConfig": {"thinkingLevel": THINKING}},
        }}, ensure_ascii=False) for u in batch]
        lp = os.path.join(a.workdir, f"in-{tag}.jsonl")
        open(lp, "w", encoding="utf-8").write("\n".join(lines) + "\n")
        in_uri = f"{a.gcs}/batch/{tag}/in.jsonl"
        sh("gcloud", "storage", "cp", lp, in_uri, f"--project={PROJECT}")
        out_prefix = f"{a.gcs}/batch/{tag}/out/"
        # A retried chunk writes a SECOND predictions shard under the same prefix, and
        # collect() globs the prefix -- silently double-counting the earlier attempt.
        sh("gcloud", "storage", "rm", "-r", out_prefix.rstrip("/"), f"--project={PROJECT}")
        name = submit_batch(in_uri, out_prefix, tag)
        print(f"[cb] {tag}: submitted {len(batch)} pages -> {name}", flush=True)
        state, j = wait(name)
        if state != "JOB_STATE_SUCCEEDED":
            print(f"[cb] {tag}: {state} {json.dumps(j.get('error', {}))[:300]}", flush=True)
            return
        rows, usage = collect(out_prefix, book_of)
        seen, uniq = set(), []
        for r in rows:
            k = (r["book"], r["page"])
            if k in seen or k in have:
                continue
            seen.add(k); have.add(k); uniq.append(r)
        if len(uniq) != len(rows):
            print(f"[cb] {tag}: dropped {len(rows)-len(uniq)} duplicate rows", flush=True)
        rows = uniq
        empty = sum(1 for r in rows if not r["text"].strip())
        with open(a.out, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        grand["in"] += usage["in"]; grand["out"] += usage["out"]; grand["pages"] += len(rows)
        cost = usage["in"] * PRICE_IN / 1e6 + usage["out"] * PRICE_OUT / 1e6
        run = grand["in"] * PRICE_IN / 1e6 + grand["out"] * PRICE_OUT / 1e6
        print(f"[cb] {tag}: {len(rows)} pages, {empty} empty, ${cost:.2f}  "
              f"[running total {grand['pages']:,} pages / ${run:,.2f}]", flush=True)
        fb = {}
        for r in rows:
            if not r["text"].strip():
                fb.setdefault(r["book"], []).append(r["page"])
        if fb:
            with open(os.path.join(os.path.dirname(a.out), "fallback_todo.jsonl"), "a") as f:
                for b, ps in fb.items():
                    f.write(json.dumps({"book": b, "pages": ps}) + "\n")

    for book, pages in work:
        # 2 of 582 volumes (adl0109, adl0460) have no downloadable PDF. Skip loudly and keep
        # going rather than killing a multi-day run over a known-absent file.
        try:
            pdf = fetch_pdf(book, os.path.join(a.workdir, "pdf"))
        except Exception as e:
            print(f"[cb] {book}: SKIPPED, pdf unavailable ({str(e)[:100]})", flush=True)
            skipped.append(book)
            continue
        if pages is None:
            d = pdfium.PdfDocument(pdf); pages = list(range(1, len(d) + 1)); d.close()
        pages = [p for p in pages if (book, p) not in have]
        if not pages:
            print(f"[cb] {book}: nothing to do", flush=True); continue
        print(f"[cb] {book}: {len(pages)} pages", flush=True)
        uris = render_and_upload(book, pdf, pages, f"{a.gcs}/img/{book}", a.workdir)
        for _, u in uris:
            book_of[u] = book
            pending.append(u)
        # renders and the source PDF are reproducible; keep neither, or a 52k-page run
        # fills the disk (~1MB/page locally on top of 5.1GB of PDFs)
        subprocess.run(["rm", "-rf", os.path.join(a.workdir, book)], capture_output=True)
        os.remove(pdf) if os.path.exists(pdf) else None
        while len(pending) >= CHUNK:
            flush_chunk()
    flush_chunk(force=True)

    c = grand["in"] * PRICE_IN / 1e6 + grand["out"] * PRICE_OUT / 1e6
    print(f"\n[cb] TOTAL {grand['pages']:,} pages  {grand['in']:,} in / {grand['out']:,} out  "
          f"${c:,.2f} at batch price", flush=True)
    if skipped:
        print(f"[cb] SKIPPED {len(skipped)} books with no PDF: {', '.join(skipped)}", flush=True)
    return 0

if __name__ == "__main__":
    sys.exit(main())
