"""Afghan Press Archive: search and reading API.  afghanpress.org

69,624 machine-read pages of Afghan periodicals (1873-1960s), the whole ADL collection.

Design constraints that come straight from the measurements (see ../../RESULTS.md):

  * The transcription is a finding aid, not an edition -- roughly two thirds of characters
    agree with a modern printed edition of the same text, and a measured part of that gap is
    editorial recension rather than misreading (see app/provenance.py for the full record and
    what it is and is not measured against). Exact search would fail even on perfect text: a
    scholar's remembered wording rarely matches the page character-for-character. So
    the lexical index is over character TRIGRAMS, which degrade gracefully under both OCR error
    and paraphrase, and every query is normalised the same way the text was.
  * Measured over the full 69,624-page index, LEXICAL WINS and fusion hurts: trigram reaches
    the right page in the top 20 for 81.4% of long quotes and 59.8% of short ones; semantic
    manages 54.9% / 23.5%, and reciprocal-rank fusion drags short queries down to 54.9%. So the
    default is trigram alone. Semantic is kept as an explicit mode because it is the only thing
    that can answer a TOPICAL query ("pages about land reform"), which the gold set cannot
    measure and lexical search structurally cannot do.
  * The raw read is the citable layer and is never silently rewritten. AI "cleanup" measurably
    rewrites 3-5% of already-correct text, so it is opt-in, per page, and clearly labelled.
  * The page IMAGE is the primary source; the text is an index into it. Every result carries
    its image so a reader can verify rather than trust.
"""
import json, os, re, sqlite3, threading, time, unicodedata
from typing import Optional

import numpy as np
from fastapi import Body, Depends, FastAPI, HTTPException, Header, Query
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, RedirectResponse,
                               Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles

from . import catalog, exports, iiif, oai, pages as render, provenance

DATA = os.environ.get("ADL_DATA", "/data")
BASE_URL = os.environ.get("ADL_BASE_URL", "https://afghanpress.org")
ADMIN_EMAIL = os.environ.get("ADL_CONTACT", "mike@stepsventures.com")
DB_PATH = os.path.join(DATA, "corpus.db")
VEC_PATH = os.path.join(DATA, "corpus_vecs.npy")
IDS_PATH = os.path.join(DATA, "corpus_ids.json")
IMG_BASE = os.environ.get("ADL_IMG_BASE", "https://storage.googleapis.com/adl-page-images")
PROJECT = os.environ.get("ADL_PROJECT", os.environ.get("HTR_PROJECT", ""))
EMBED_MODEL = "text-multilingual-embedding-002"
EMBED_PROJECT = os.environ.get("ADL_EMBED_PROJECT", os.environ.get("HTR_PROJECT", ""))

app = FastAPI(title="Afghan Press Archive", docs_url="/api/docs")

# The design studies are a separate origin but drive this same API, so they can be judged as
# working interfaces rather than pictures. Read endpoints only: contributions still require a
# verified token, so a permissive read origin grants nothing a plain GET would not.
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://(afghanpress\.org|www\.afghanpress\.org|afghan-press-[a-z]+-[0-9]+\.us-central1\.run\.app)|http://localhost(:[0-9]+)?",
    allow_methods=["GET", "POST"], allow_headers=["*"])



@app.middleware("http")
async def cache_headers(request, call_next):
    """Without an explicit Cache-Control, browsers apply HEURISTIC caching to static files and
    can serve a stale page for hours after a deploy: which looks exactly like the deploy not
    having worked. HTML must always revalidate; fonts and images never change and can be held
    forever.

    The bibliographic surfaces are the exception in the other direction: manifests, OAI records
    and the rendered page views describe a finished historical artefact, and a harvester or
    crawler walking 69,624 of them should be served from cache rather than waking this
    container 69,624 times."""
    t0 = time.time()
    r = await call_next(request)
    path = request.url.path
    if path.startswith(("/iiif/", "/oai", "/book/", "/browse", "/places", "/sitemap")):
        r.headers["Cache-Control"] = "public, max-age=3600"
    elif path.startswith("/api/"):
        r.headers["Cache-Control"] = "no-store"
    elif path.endswith((".woff2", ".jpg", ".png")):
        r.headers["Cache-Control"] = "public, max-age=31536000, immutable"
    else:
        r.headers["Cache-Control"] = "no-cache, must-revalidate"

    # Baseline security headers. Nothing here is exotic, and their absence is the kind of thing
    # an institutional review flags before it looks at anything else. The CSP is deliberately
    # loose about images (page scans come from a GCS bucket) and about the Firebase SDK, which
    # is imported from gstatic only when a reader chooses to sign in.
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    r.headers["X-Frame-Options"] = "SAMEORIGIN"
    r.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    r.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' https://storage.googleapis.com data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self' 'unsafe-inline' https://www.gstatic.com; "
        "connect-src 'self' https://identitytoolkit.googleapis.com "
        "https://securetoken.googleapis.com; "
        "font-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'")

    ms = int((time.time() - t0) * 1000)
    if not path.startswith(("/fonts/", "/static/")):
        print(json.dumps({"severity": "INFO", "path": path, "method": request.method,
                          "status": r.status_code, "ms": ms}), flush=True)
    return r


@app.exception_handler(HTTPException)
async def html_errors(request, exc: HTTPException):
    """A reader who mistypes a page number should not be shown {"detail":"page not found"}.
    API paths still get JSON, because that is what a client is parsing."""
    p = request.url.path
    if p.startswith(("/api/", "/oai", "/iiif/")) or "text/html" not in \
            request.headers.get("accept", ""):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    return HTMLResponse(render.error_page(exc.status_code, exc.detail),
                        status_code=exc.status_code)


# Contributions are the only unauthenticated-ish write path (a verified sign-in is required,
# but a signed-in reader could still loop). A token bucket per uid keeps a scripted client from
# filling Firestore, without adding a dependency or a shared cache -- one container's worth of
# memory is the right granularity for something this cheap to get wrong.
_buckets = {}
CONTRIB_PER_HOUR = int(os.environ.get("ADL_CONTRIB_PER_HOUR", "60"))


def rate_limit(key: str, per_hour: int = None) -> bool:
    per_hour = per_hour or CONTRIB_PER_HOUR
    now = time.time()
    with _lock:
        hits = [t for t in _buckets.get(key, []) if now - t < 3600]
        if len(hits) >= per_hour:
            _buckets[key] = hits
            return False
        hits.append(now)
        _buckets[key] = hits
        if len(_buckets) > 5000:            # bound the map; oldest keys are cheapest to drop
            for k in [k for k, v in _buckets.items() if not v or now - max(v) > 3600][:1000]:
                _buckets.pop(k, None)
    return True

# ---------------------------------------------------------------- text handling
HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'’‘—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE)\]")

def norm(t: str) -> str:
    """Fold the orthographic variation that would otherwise break search on its own.

    A Kabul lithograph and a modern scholar's keyboard disagree about yeh/kaf forms, tatweel,
    diacritics and digit shapes. That gap is nearly as large as our OCR error, and folding both
    sides at index AND query time fixes them together."""
    t = MARK.sub(" ", t or "")
    t = re.sub(r"\[([^\]]*)\؟?\]", r"\1", t)
    t = unicodedata.normalize("NFKC", t).translate(MAP).translate(HARAKAT).translate(DROP)
    t = re.sub(r"[۰-۹٠-٩\d]+", " 0 ", t)
    return " ".join(w for w in t.split() if w)

def trigrams(s: str) -> str:
    s = s.replace(" ", "_")
    return " ".join(s[i:i + 3] for i in range(len(s) - 2)) if len(s) >= 3 else s

# ---------------------------------------------------------------- lazy resources
_res = {"db": None, "vecs": None, "ids": None, "pos": None}
_lock = threading.Lock()

def db() -> sqlite3.Connection:
    # one connection per thread; sqlite objects are not shareable across threads
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn

_local = threading.local()

def vectors():
    with _lock:
        if _res["vecs"] is None:
            _res["vecs"] = np.load(VEC_PATH, mmap_mode="r")
            _res["ids"] = [tuple(x) for x in json.load(open(IDS_PATH))]
            _res["pos"] = {bp: i for i, bp in enumerate(_res["ids"])}
    return _res["vecs"], _res["ids"]

# ---------------------------------------------------------------- query embedding
_tok = {"v": None, "e": 0.0}

def _token() -> str:
    """Cloud Run metadata server token. No key material anywhere."""
    import urllib.request
    if _tok["v"] and time.time() < _tok["e"]:
        return _tok["v"]
    req = urllib.request.Request(
        "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token",
        headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(req, timeout=10) as r:
        d = json.loads(r.read())
    _tok["v"] = d["access_token"]; _tok["e"] = time.time() + d.get("expires_in", 3600) - 120
    return _tok["v"]

def embed_query(q: str) -> Optional[np.ndarray]:
    import urllib.request, urllib.error
    url = (f"https://us-central1-aiplatform.googleapis.com/v1/projects/{EMBED_PROJECT}"
           f"/locations/us-central1/publishers/google/models/{EMBED_MODEL}:predict")
    body = {"instances": [{"task_type": "RETRIEVAL_QUERY", "content": q[:4000]}]}
    try:
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={
            "Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as r:
            v = json.loads(r.read())["predictions"][0]["embeddings"]["values"]
        a = np.asarray(v, dtype=np.float32); n = np.linalg.norm(a)
        return a / n if n else None
    except Exception:
        # Semantic is an ENHANCEMENT. If Vertex is unreachable the lexical index still answers,
        # so degrade to trigram-only rather than failing the request.
        return None

# ---------------------------------------------------------------- retrieval
def search_trigram(q: str, k: int, book: Optional[str]):
    # Keep the MOST SELECTIVE trigrams, not the first ones. A trigram like "_و_" occurs on
    # 59,207 of 69,624 pages and costs a huge posting-list merge while telling us nothing; a
    # rare one nearly identifies the page by itself. Ranking the query's trigrams by document
    # frequency and keeping the rarest cuts the longest query from 2.5s to 1.3s. NB it does NOT
    # improve accuracy -- measured recall moved 62.7%->59.8% (short) and 82.4%->81.4% (long),
    # i.e. unchanged within noise on n=102. This is a latency optimisation, nothing more.
    tg = trigrams(norm(q)).split()
    if not tg:
        return []
    if len(tg) > 40:
        uniq = list(dict.fromkeys(tg))
        marks = ",".join("?" * len(uniq))
        freq = {r["term"]: r["doc"] for r in
                db().execute(f"SELECT term, doc FROM ftv WHERE term IN ({marks})", uniq)}
        # unseen trigrams are maximally selective: they exclude everything, so rank them first
        tg = sorted(uniq, key=lambda t: freq.get(t, 0))[:40]
    m = " OR ".join('"' + t.replace('"', "") + '"' for t in tg)
    sql = ("SELECT p.book, p.page, p.raw, p.txt, bm25(ft) AS s FROM ft JOIN pages p ON p.id=ft.rowid "
           "WHERE ft MATCH ?")
    args = [m]
    if book:
        sql += " AND p.book = ?"; args.append(book)
    sql += " ORDER BY bm25(ft) LIMIT ?"; args.append(k * 3)
    rows = list(db().execute(sql, args))

    # FTS MATCH is an OR over trigrams, so a single incidental match surfaces a page: searching
    # nonsense returned 20 confident-looking results. Require a real share of the query's
    # trigrams to actually be present. Showing nothing is the honest answer when nothing matches;
    # a research tool that always returns something teaches users to distrust it.
    need = 0.34 if len(tg) >= 12 else 0.55      # short queries must match proportionally more
    out = []
    for r in rows:
        txt = r["txt"] or ""
        hit = sum(1 for t in tg if t in txt)
        if hit / max(1, len(tg)) >= need:
            out.append((r["book"], r["page"], r["raw"]))
        if len(out) >= k:
            break
    return out

def search_semantic(qv, k: int, book: Optional[str]):
    vecs, ids = vectors()
    s = np.asarray(vecs @ qv)
    take = min(len(s) - 1, max(k * 5, 200))
    top = np.argpartition(-s, take)[:take]
    top = top[np.argsort(-s[top])]
    out = []
    for i in top:
        b, p = ids[i]
        if book and b != book:
            continue
        out.append((b, p, None))
        if len(out) >= k:
            break
    return out

def rrf(lists, k):
    """Reciprocal rank fusion. Rank-based rather than score-based, because BM25 scores and
    cosine similarities are not on comparable scales and normalising them invents a tradeoff
    we have not measured."""
    sc = {}
    for lst in lists:
        for i, (b, p, _) in enumerate(lst):
            sc[(b, p)] = sc.get((b, p), 0.0) + 1.0 / (60 + i + 1)
    return [bp for bp, _ in sorted(sc.items(), key=lambda kv: -kv[1])][:k]

def snippet(raw: str, q: str, width: int = 260) -> str:
    """Locate the best-matching window by normalised tokens, then return the RAW text there --
    users must see what is actually printed, not our normalised form."""
    if not raw:
        return ""
    nq = set(norm(q).split())
    words = raw.split()
    if not nq or not words:
        return raw[:width]
    # Normalise each word ONCE, then slide a window with a rolling count. The obvious version
    # -- re-normalising a 30-word window at every position -- is O(n*w) calls into the regex
    # machinery and measured 2-3 SECONDS per request on a long page. This is O(n).
    nw = [norm(w) for w in words]
    W = 30
    cur = sum(1 for t in nw[:W] if t in nq)
    best, bi = cur, 0
    for i in range(1, max(1, len(words) - W + 1)):
        if nw[i - 1] in nq:
            cur -= 1
        if i + W - 1 < len(nw) and nw[i + W - 1] in nq:
            cur += 1
        if cur > best:
            best, bi = cur, i
    return " ".join(words[bi:bi + 40])[:width * 2]

@app.get("/api/search")
def api_search(q: str = Query(..., min_length=2), limit: int = Query(20, le=100),
               mode: str = Query("trigram"), book: Optional[str] = None):
    t0 = time.time()
    tri = search_trigram(q, limit * 2, book) if mode in ("hybrid", "trigram") else []
    sem = []
    # Only a query that actually reached for semantic search can say anything about whether it
    # is available. Reporting bool(sem) meant every default lexical search returned False and
    # the reader was told "subject search unavailable" on a search that never asked for it.
    sem_ok = True
    if mode in ("hybrid", "semantic"):
        qv = embed_query(q)
        if qv is not None:
            sem = search_semantic(qv, limit * 2, book)
        sem_ok = bool(sem)
    if mode == "semantic" and not sem:
        # Vertex unreachable. Returning an empty page would read as "nothing in the archive
        # matches", which is false and is the worst possible failure for a research tool.
        # Fall back to the lexical index and say so.
        tri = tri or search_trigram(q, limit * 2, book)
        mode = "trigram (subject search unavailable)"
    if mode.startswith("trigram"):
        order = [(b, p) for b, p, _ in tri][:limit]
    elif mode == "semantic":
        order = [(b, p) for b, p, _ in sem][:limit]
    else:
        order = rrf([tri, sem], limit) if sem else [(b, p) for b, p, _ in tri][:limit]

    raws = {}
    if order:
        qs = ",".join("(?,?)" for _ in order)
        flat = [x for bp in order for x in bp]
        for r in db().execute(
                f"SELECT book, page, raw FROM pages WHERE (book,page) IN (VALUES {qs})", flat):
            raws[(r["book"], r["page"])] = r["raw"]
    return {"query": q, "mode": mode, "ms": int((time.time() - t0) * 1000),
            "semantic_available": sem_ok,
            "results": [{"book": b, "page": p,
                         "snippet": snippet(raws.get((b, p), ""), q),
                         "image": f"{IMG_BASE}/{b}/{p:05d}.jpg"} for b, p in order]}

@app.get("/api/page/{book}/{page}")
def api_page(book: str, page: int):
    r = db().execute("SELECT book,page,raw,nchars FROM pages WHERE book=? AND page=?",
                     (book, page)).fetchone()
    if not r:
        raise HTTPException(404, "page not found")
    nb = db().execute("SELECT MIN(page) lo, MAX(page) hi FROM pages WHERE book=?",
                      (book,)).fetchone()
    return {"book": book, "page": page, "text": r["raw"], "chars": r["nchars"],
            "image": f"{IMG_BASE}/{book}/{page:05d}.jpg",
            "first_page": nb["lo"], "last_page": nb["hi"],
            "title": catalog.label(book),
            "permalink": f"{BASE_URL}/book/{book}/{page}",
            "canvas": iiif.canvas_id(book, page),
            "source": f"https://afghanistandl.nyu.edu/books/{book}/",
            "source_pdf": f"https://afghanistandl.nyu.edu/pdf/{book}_download.pdf",
            "rights": {"image": catalog.IMAGE_RIGHTS, "text": catalog.TEXT_RIGHTS},
            # Carried on the page payload so the reader shows the same citation the API
            # serves. The two used to be written separately and the visible one named only
            # the object number, which is not a citation anybody could follow.
            "citation": _citation(book, page),
            "provenance": provenance.page_record(book, page)}

@app.get("/api/books")
def api_books():
    rows = db().execute("SELECT book, COUNT(*) n, SUM(nchars) c FROM pages "
                        "GROUP BY book ORDER BY book").fetchall()
    return {"count": len(rows),
            "books": [{"book": r["book"], "pages": r["n"], "chars": r["c"]} for r in rows]}

@app.get("/api/download/book/{book}.jsonl")
def api_dl_book(book: str):
    rows = db().execute("SELECT book,page,raw FROM pages WHERE book=? ORDER BY page",
                        (book,)).fetchall()
    if not rows:
        raise HTTPException(404, "unknown book")
    def gen():
        for r in rows:
            yield json.dumps({"book": r["book"], "page": r["page"], "text": r["raw"]},
                             ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={
        "Content-Disposition": f'attachment; filename="{book}.jsonl"'})

@app.get("/api/download/corpus.jsonl")
def api_dl_all():
    def gen():
        cur = db().execute("SELECT book,page,raw FROM pages ORDER BY book,page")
        for r in cur:
            yield json.dumps({"book": r["book"], "page": r["page"], "text": r["raw"]},
                             ensure_ascii=False) + "\n"
    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={
        "Content-Disposition": 'attachment; filename="adl_corpus.jsonl"'})

@app.get("/api/authconfig")
def api_authconfig():
    """Firebase web config. These values are public by design -- a Firebase apiKey identifies
    the project, it does not authorise anything. Access is governed by token verification
    server-side and by Firestore rules, never by hiding this."""
    key = os.environ.get("ADL_FB_API_KEY", "")
    dom = os.environ.get("ADL_FB_AUTH_DOMAIN", "")
    # `configured` exists so the interface can tell the difference between "sign-in is off" and
    # "sign-in is broken". Without it the front end offered a sign-in button that called Firebase
    # with an empty apiKey and failed with an SDK error, which reads to a visitor as a broken
    # site rather than a feature that is not open yet.
    return {"apiKey": key, "authDomain": dom,
            "projectId": os.environ.get("ADL_FIREBASE_PROJECT", PROJECT),
            "configured": bool(key and dom),
            "contact": ADMIN_EMAIL}

@app.get("/designs")
def designs_redirect():
    """The design studies are internal working material -- five rejected interfaces beside the
    one that shipped. Useful to us, confusing to a scholar who lands on them from a research
    guide, so the route stays for our own use but is off by default rather than public."""
    from fastapi.responses import RedirectResponse
    url = os.environ.get("ADL_DESIGNS_URL")
    if not url:
        raise HTTPException(404, "not found")
    return RedirectResponse(url, status_code=302)

@app.get("/api/healthz")
def api_health():
    n = db().execute("SELECT COUNT(*) c FROM pages").fetchone()["c"]
    return {"ok": n > 0, "pages": n}

@app.get("/api/stats")
def api_stats():
    r = db().execute("SELECT COUNT(*) n, COUNT(DISTINCT book) b, SUM(nchars) c FROM pages").fetchone()
    return {"pages": r["n"], "books": r["b"], "chars": r["c"],
            "blank_pages": provenance.CORPUS["blank_pages"],
            "accuracy_note": provenance.ACCURACY["headline"],
            "search_recall": provenance.ACCURACY["search_recall"],
            "full_provenance": f"{BASE_URL}/api/provenance"}

# ---------------------------------------------------------------- contributions
# Firestore holds everything a reader creates. Three kinds, deliberately different in visibility:
#   correction  -- a proposed better reading. PUBLIC once approved, so it is moderated.
#   annotation  -- a private research note. Visible ONLY to its author, never moderated,
#                  never shown to anyone else. Researchers will not take notes in public.
#   feedback    -- free text to us. Never public.
# The raw transcription is never mutated by any of this; corrections are an overlay.
_fs = {"c": None}

def fs():
    with _lock:
        if _fs["c"] is None:
            from google.cloud import firestore
            _fs["c"] = firestore.Client(project=PROJECT)
    return _fs["c"]

def caller(authorization: Optional[str] = Header(None)) -> Optional[dict]:
    """Verify a Firebase ID token. Returns None for anonymous readers -- reading is open."""
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    try:
        from google.auth.transport import requests as grequests
        from google.oauth2 import id_token
        info = id_token.verify_firebase_token(
            authorization.split(None, 1)[1], grequests.Request(),
            audience=os.environ.get("ADL_FIREBASE_PROJECT", PROJECT))
        if not info:
            return None
        return {"uid": info.get("user_id") or info.get("sub"), "email": info.get("email", "")}
    except Exception:
        return None

def require(user: Optional[dict]) -> dict:
    if not user:
        raise HTTPException(401, "sign in to contribute")
    return user

MODERATORS = set(filter(None, os.environ.get("ADL_MODERATORS", "").split(",")))

CONTRIB_LICENCE = {
    "version": "2026-08-12",
    "uri": "https://creativecommons.org/publicdomain/zero/1.0/",
    "terms": "By submitting a correction you release it under CC0 1.0, waiving copyright in it "
             "so it can be redistributed with the corpus by anyone, including libraries. You "
             "will be credited by name unless you ask otherwise. Private annotations are not "
             "covered: they are never published or redistributed.",
}


@app.get("/api/contrib/terms")
def api_contrib_terms():
    return CONTRIB_LICENCE

@app.post("/api/contrib")
def api_contrib(payload: dict = Body(...), user: Optional[dict] = Depends(caller)):
    u = require(user)
    if not rate_limit(f"contrib:{u['uid']}"):
        raise HTTPException(429, f"more than {CONTRIB_PER_HOUR} contributions in an hour; "
                                 f"slow down or write to us")
    kind = payload.get("kind")
    if kind not in ("correction", "annotation", "feedback"):
        raise HTTPException(400, "kind must be correction, annotation or feedback")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "empty body")
    # A correction is a creative act and its author holds copyright in it. Publishing the corpus
    # as CC0 while silently absorbing reader corrections would put an unlicensed contribution
    # inside a dataset that promises institutions there is nothing to clear. So a public
    # contribution requires an explicit licence agreement, recorded per contribution with the
    # terms version, rather than assumed. Annotations are private and never republished, so they
    # need no grant.
    if kind == "correction" and not payload.get("agree_cc0"):
        raise HTTPException(400, "a correction must be accompanied by agree_cc0: true, "
                                 "releasing it under CC0 1.0 so it can travel with the corpus")
    doc = {"kind": kind, "book": payload.get("book"), "page": payload.get("page"),
           "original": (payload.get("original") or "")[:4000], "body": body[:8000],
           "note": (payload.get("note") or "")[:2000],
           "uid": u["uid"], "email": u["email"],
           "created": time.time(),
           "licence": CONTRIB_LICENCE if kind == "correction" else None,
           "licence_agreed": bool(payload.get("agree_cc0")) if kind == "correction" else None,
           # annotations are private by definition and skip moderation entirely
           "status": "private" if kind == "annotation" else "pending"}
    ref = fs().collection("adl_contributions").document()
    ref.set(doc)
    return {"id": ref.id, "status": doc["status"]}

@app.get("/api/contrib/page/{book}/{page}")
def api_contrib_page(book: str, page: int, user: Optional[dict] = Depends(caller)):
    col = fs().collection("adl_contributions")
    approved = [d.to_dict() | {"id": d.id} for d in
                col.where("book", "==", book).where("page", "==", page)
                   .where("status", "==", "approved").stream()]
    mine = []
    if user:
        mine = [d.to_dict() | {"id": d.id} for d in
                col.where("book", "==", book).where("page", "==", page)
                   .where("uid", "==", user["uid"]).stream()]
    # never leak another reader's private notes or unapproved suggestions
    return {"corrections": [a for a in approved if a["kind"] == "correction"],
            "mine": mine}

@app.get("/api/contrib/export")
def api_contrib_export(user: Optional[dict] = Depends(caller)):
    """Every note and correction a reader has made, as JSONL, on demand.

    A library's objection to a one-person site is not that it might vanish, it is that a
    scholar's notes vanish with it. Private annotations live in Firestore, which is ours and
    could be switched off tomorrow, so the only honest answer is that the reader can take their
    work out whenever they like without asking us. This deliberately returns the caller's own
    records only, including unapproved and private ones, and nobody else's."""
    u = require(user)
    if not PROJECT:
        raise HTTPException(503, "contributions store unavailable")
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        q = (fs().collection("adl_contributions")
             .where(filter=FieldFilter("uid", "==", u["uid"])))
        rows = [d.to_dict() | {"id": d.id} for d in q.stream(timeout=30)]
    except Exception as e:
        raise HTTPException(503, f"could not read your contributions: {str(e)[:120]}")

    def gen():
        for r in rows:
            r.pop("email", None)          # they know their own address; do not echo it back
            yield json.dumps(r, ensure_ascii=False, default=str) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson", headers={
        "Content-Disposition": 'attachment; filename="my-afghanpress-contributions.jsonl"'})


@app.get("/api/admin/queue")
def api_queue(user: Optional[dict] = Depends(caller), limit: int = 100):
    u = require(user)
    if u["email"] not in MODERATORS:
        raise HTTPException(403, "not a moderator")
    q = (fs().collection("adl_contributions").where("status", "==", "pending")
         .limit(limit).stream())
    return {"pending": [d.to_dict() | {"id": d.id} for d in q]}

@app.post("/api/admin/moderate")
def api_moderate(payload: dict = Body(...), user: Optional[dict] = Depends(caller)):
    u = require(user)
    if u["email"] not in MODERATORS:
        raise HTTPException(403, "not a moderator")
    status = payload.get("status")
    if status not in ("approved", "rejected"):
        raise HTTPException(400, "status must be approved or rejected")
    fs().collection("adl_contributions").document(payload["id"]).update(
        {"status": status, "moderated_by": u["email"], "moderated": time.time()})
    return {"ok": True}

# ---------------------------------------------------------------- bibliographic surfaces
# Everything below exists so an institution can take this corpus without taking our files:
# a manifest their viewer can load, a search service they can point at, records their
# harvester already understands, and formats their pipeline already ingests.

_counts = {"v": None}


def page_counts() -> dict:
    """book -> page count. Computed once; the corpus is static."""
    with _lock:
        if _counts["v"] is None:
            _counts["v"] = {r["book"]: r["n"] for r in db().execute(
                "SELECT book, COUNT(*) n FROM pages GROUP BY book")}
    return _counts["v"]


def book_pages(book: str) -> list:
    return [r["page"] for r in db().execute(
        "SELECT page FROM pages WHERE book=? ORDER BY page", (book,))]


def book_rows(book: str) -> list:
    return [(r["page"], r["raw"]) for r in db().execute(
        "SELECT page, raw FROM pages WHERE book=? ORDER BY page", (book,))]


_ents = {"v": None}


def entities() -> dict:
    with _lock:
        if _ents["v"] is None:
            try:
                _ents["v"] = json.load(open(os.path.join(DATA, "entities.json"),
                                            encoding="utf-8"))
            except (OSError, ValueError):
                _ents["v"] = {"places": []}
    return _ents["v"]


# Corrections enrich a rendered page; they are never a precondition for showing it. Firestore
# with no reachable credentials does not fail fast -- it retries with backoff and blocks the
# request for 30s+, which turns an overlay outage into an outage of the archive. So: a hard
# per-call timeout, and a breaker that stops calling at all after repeated failures rather than
# paying the timeout on every page view.
_fs_break = {"fails": 0, "until": 0.0}
FS_TIMEOUT = float(os.environ.get("ADL_FS_TIMEOUT", "2.0"))


def approved_corrections(book: str, page: int) -> list:
    if not PROJECT or time.time() < _fs_break["until"]:
        return []
    try:
        from google.cloud.firestore_v1.base_query import FieldFilter
        q = (fs().collection("adl_contributions")
             .where(filter=FieldFilter("book", "==", book))
             .where(filter=FieldFilter("page", "==", page))
             .where(filter=FieldFilter("status", "==", "approved")))
        out = [d.to_dict() for d in q.stream(timeout=FS_TIMEOUT)]
        _fs_break["fails"] = 0
        return [c for c in out if c.get("kind") == "correction"]
    except Exception as e:
        _fs_break["fails"] += 1
        if _fs_break["fails"] >= 3:
            _fs_break["until"] = time.time() + 300
            print(json.dumps({"severity": "ERROR", "msg": "firestore breaker open for 300s",
                              "error": str(e)[:200]}), flush=True)
        return []


@app.get("/api/provenance")
def api_provenance():
    """The full method and accuracy record, in one place, machine-readable.

    Published because the alternative -- a number in a footer with no sourcing -- is what
    makes a specialist stop trusting the whole thing."""
    return {"corpus": provenance.CORPUS, "method": provenance.METHOD,
            "accuracy": provenance.ACCURACY, "limits": provenance.LIMITS,
            "rights": {"images": catalog.IMAGE_RIGHTS, "text": catalog.TEXT_RIGHTS}}


@app.get("/api/facets")
def api_facets():
    return catalog.facets(page_counts())


@app.get("/api/places")
def api_places(limit: int = Query(500, le=5000)):
    e = entities()
    return {"method": e.get("method"), "selection": e.get("selection"),
            "limitation": e.get("known_limitation"),
            "source": e.get("generated_from"),
            "count": len(e["places"]),
            "places": [{k: v for k, v in p.items() if k != "sample"}
                       for p in e["places"][:limit]]}


@app.get("/api/place/{pid}")
def api_place(pid: str):
    for p in entities()["places"]:
        if p["id"] == pid:
            return p
    raise HTTPException(404, "unknown place")


# ---------------------------------------------------------------- IIIF
@app.get("/iiif/collection")
def iiif_collection():
    return JSONResponse(iiif.collection(sorted(page_counts()), catalog),
                        media_type="application/ld+json")


@app.get("/iiif/{book}/manifest")
def iiif_manifest(book: str):
    pgs = book_pages(book)
    if not pgs:
        raise HTTPException(404, "unknown book")
    return JSONResponse(iiif.manifest(book, pgs, catalog, provenance),
                        media_type="application/ld+json")


@app.get("/iiif/{book}/canvas/{page}")
def iiif_canvas(book: str, page: int):
    """A canvas URI has to resolve to something -- a viewer following a search hit will
    dereference it. Redirect to the page it names rather than 404."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"/book/{book}/{page}", status_code=302)


def _content_search(q: str, book: Optional[str]):
    hits = search_trigram(q, 100, book)
    snips = {}
    order = []
    for b, p, raw in hits:
        order.append((b, p))
        snips[(b, p)] = snippet(raw or "", q, width=200)
    return iiif.search_response(q, order, book, snips)


@app.get("/iiif/{book}/canvas/{page}/text")
def iiif_canvas_text(book: str, page: int):
    """Every canvas in every manifest references this. Without it a IIIF viewer asks for the
    transcription and gets a 404, which reads as "this project has no text layer"."""
    r = db().execute("SELECT raw FROM pages WHERE book=? AND page=?", (book, page)).fetchone()
    if not r:
        raise HTTPException(404, "page not found")
    return JSONResponse(iiif.text_annotation_page(book, page, r["raw"]),
                        media_type="application/ld+json")


@app.get("/iiif/{book}/search")
def iiif_search_book(book: str, q: str = Query("")):
    if not q:
        return JSONResponse(iiif.search_response("", [], book), media_type="application/ld+json")
    return JSONResponse(_content_search(q, book), media_type="application/ld+json")


@app.get("/iiif/search")
def iiif_search_all(q: str = Query("")):
    if not q:
        return JSONResponse(iiif.search_response("", []), media_type="application/ld+json")
    return JSONResponse(_content_search(q, None), media_type="application/ld+json")


# ---------------------------------------------------------------- OAI-PMH
@app.get("/oai")
def oai_endpoint(verb: str = Query(""), identifier: str = Query(""),
                 metadataPrefix: str = Query(""), resumptionToken: str = Query(""),
                 set: str = Query("")):
    stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    base = f"{BASE_URL}/oai"
    earliest = provenance.CORPUS["read_completed"]
    counts = page_counts()
    books = sorted(counts)
    xml = "application/xml"

    def err(code, msg):
        return Response(oai.error(base, code, msg, stamp), media_type=xml, status_code=200)

    if verb == "Identify":
        return Response(oai.identify(base, stamp, earliest, ADMIN_EMAIL), media_type=xml)
    if verb == "ListMetadataFormats":
        return Response(oai.list_metadata_formats(base, stamp), media_type=xml)
    if verb == "ListSets":
        decades = sorted({(catalog.dates(b)[0] // 10) * 10 for b in books
                          if catalog.dates(b)[0]})
        return Response(oai.list_sets(base, stamp, decades), media_type=xml)
    if verb in ("ListRecords", "ListIdentifiers"):
        if not resumptionToken and metadataPrefix != "oai_dc":
            return err("cannotDisseminateFormat", "only oai_dc is supported")
        out = oai.list_records(base, stamp, books, counts, catalog, verb, resumptionToken, set)
        if out is None:
            return err("badResumptionToken" if resumptionToken else "noRecordsMatch",
                       "no records for that token or set")
        return Response(out, media_type=xml)
    if verb == "GetRecord":
        if metadataPrefix != "oai_dc":
            return err("cannotDisseminateFormat", "only oai_dc is supported")
        bid = identifier.replace(oai.PREFIX, "")
        if bid not in counts:
            return err("idDoesNotExist", f"no such identifier: {identifier}")
        return Response(oai.get_record(base, stamp, bid, counts, catalog), media_type=xml)
    return err("badVerb", f"unsupported verb: {verb or '(none)'}")


# ---------------------------------------------------------------- exports
EXPORTS = {
    "alto": ("text/xml", "xml", exports.alto),
    "hocr": ("text/html", "hocr.html", exports.hocr),
    "tei": ("text/xml", "tei.xml", None),
    "txt": ("text/plain; charset=utf-8", "txt", exports.plain),
}


@app.get("/api/export/{book}")
def api_export(book: str, format: str = Query("alto")):
    if format not in EXPORTS:
        raise HTTPException(400, f"format must be one of {', '.join(EXPORTS)}")
    rows = book_rows(book)
    if not rows:
        raise HTTPException(404, "unknown book")
    media, ext, fn = EXPORTS[format]
    body = (exports.tei(book, rows, catalog, provenance, IMG_BASE) if format == "tei"
            else fn(book, rows, catalog, provenance))
    return Response(body, media_type=media, headers={
        "Content-Disposition": f'attachment; filename="{book}.{ext}"'})


# ---------------------------------------------------------------- addressable HTML
@app.get("/book/{book}")
def html_book(book: str):
    pgs = book_pages(book)
    if not pgs:
        raise HTTPException(404, "unknown book")
    return HTMLResponse(render.book_page(book, pgs, catalog, provenance, BASE_URL, IMG_BASE))


@app.get("/book/{book}/{page}")
def html_page(book: str, page: int):
    r = db().execute("SELECT raw FROM pages WHERE book=? AND page=?", (book, page)).fetchone()
    if not r:
        raise HTTPException(404, "page not found")
    nb = db().execute("SELECT MIN(page) lo, MAX(page) hi FROM pages WHERE book=?",
                      (book,)).fetchone()
    prv = db().execute("SELECT MAX(page) p FROM pages WHERE book=? AND page<?",
                       (book, page)).fetchone()["p"]
    nxt = db().execute("SELECT MIN(page) p FROM pages WHERE book=? AND page>?",
                       (book, page)).fetchone()["p"]
    return HTMLResponse(render.reader_page(book, page, r["raw"], nb["lo"], nb["hi"], prv, nxt,
                                           catalog, provenance, BASE_URL, IMG_BASE,
                                           approved_corrections(book, page)))


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def _facet_view(decade=None, subject=None):
    f = catalog.facets(page_counts())
    if decade:
        f = dict(f, titles=[t for t in f["titles"]
                            if t["year_start"] and (t["year_start"] // 10) * 10 == decade])
    if subject:
        f = dict(f, titles=[t for t in f["titles"]
                            if any(_slug(s.split("--")[0]) == subject
                                   for s in catalog.subjects(t["book"]))])
    return f


@app.get("/browse")
def html_browse(decade: Optional[int] = None, subject: Optional[str] = None):
    # Query-string facets are a dead end for discovery: crawlers treat ?decade=1910 as a
    # parameter on one page rather than as a page, so the whole browse tree collapses to a
    # single URL. The real paths below are what gets indexed; these redirect into them so old
    # links and the in-page controls keep working.
    if decade:
        return RedirectResponse(f"/browse/decade/{decade}", status_code=301)
    if subject:
        return RedirectResponse(f"/browse/subject/{_slug(subject)}", status_code=301)
    return HTMLResponse(render.browse_page(_facet_view(), BASE_URL))


@app.get("/browse/decade/{decade}")
def html_browse_decade(decade: int):
    f = _facet_view(decade=decade)
    if not f["titles"]:
        raise HTTPException(404, f"no volumes published in the {decade}s")
    return HTMLResponse(render.browse_page(f, BASE_URL, heading=f"Published in the {decade}s",
                                           crumb=f"{decade}s"))


@app.get("/browse/subject/{subject}")
def html_browse_subject(subject: str):
    f = _facet_view(subject=subject)
    if not f["titles"]:
        raise HTTPException(404, "no volumes under that subject")
    name = next((s["subject"] for s in f["subjects"] if _slug(s["subject"]) == subject), subject)
    return HTMLResponse(render.browse_page(f, BASE_URL, heading=name, crumb=name))


@app.get("/places")
def html_places():
    e = entities()
    return HTMLResponse(render.places_page(e["places"], e, BASE_URL))


@app.get("/places/{pid}")
def html_place(pid: str):
    for p in entities()["places"]:
        if p["id"] == pid:
            return HTMLResponse(render.place_page(p, catalog, BASE_URL))
    raise HTTPException(404, "unknown place")


# ---------------------------------------------------------------- discovery
# Answer engines are how a scholar finds an obscure archive now, so the crawlers that READ in
# order to cite are welcomed by name. The ones that exist to vacuum text into a training set are
# not: the transcription is CC0 and free to take deliberately, but a bulk scrape returns nothing
# to the collection and costs us the egress. The split is imperfect -- some operators run one
# agent for both jobs -- so this is a stated preference, not a security control.
CITE_BOTS = ["OAI-SearchBot", "PerplexityBot", "ClaudeBot", "Claude-SearchBot",
             "Google-Extended", "Applebot-Extended"]
TRAIN_BOTS = ["GPTBot", "CCBot", "Bytespider", "meta-externalagent", "Amazonbot",
              "Diffbot", "Omgilibot"]


@app.get("/robots.txt")
def robots():
    lines = ["User-agent: *", "Allow: /", ""]
    lines.append("# Answer engines may read and cite this archive.")
    for b in CITE_BOTS:
        lines += [f"User-agent: {b}", "Allow: /", ""]
    lines.append("# Bulk training crawlers: the corpus is CC0, take it from the deposit instead.")
    for b in TRAIN_BOTS:
        lines += [f"User-agent: {b}", "Disallow: /", ""]
    lines.append(f"Sitemap: {BASE_URL}/sitemap.xml")
    return Response("\n".join(lines) + "\n", media_type="text/plain")


# IndexNow: Bing, Yandex and others accept URL submissions from anyone who can prove they
# control the domain, and serving this file at the root IS the proof. It is the only submission
# channel that does not need somebody to log into a webmaster console, which matters when the
# sitemap holds 69,624 URLs that have never been crawled.
#
# Registered as a literal path rather than /{key}.txt, because a path parameter there would
# shadow /robots.txt and /llms.txt depending on declaration order and return 404 for both.
INDEXNOW_KEY = os.environ.get("ADL_INDEXNOW_KEY", "a7f3c19e84b24d6fa0e5b3c8d1729f46")

app.add_api_route(f"/{INDEXNOW_KEY}.txt",
                  lambda: Response(INDEXNOW_KEY, media_type="text/plain"),
                  methods=["GET"], include_in_schema=False)


@app.get("/llms.txt")
def llms_txt():
    """A plain-language map of the archive for a model that is trying to answer a question
    about it. Everything here is a fact the site already publishes; this file exists so an
    answer engine does not have to infer the shape of the collection from HTML."""
    c, a = provenance.CORPUS, provenance.ACCURACY
    return Response(f"""# Afghan Press Archive

> Full-text search over {c['pages']:,} machine-transcribed pages from {c['books']} volumes of
> Afghan books and periodicals printed between 1873 and the 1960s, in the original Perso-Arabic
> script. Page images are held by the Afghanistan Digital Library, New York University
> Libraries, and are public domain. The transcription is CC0.

## What this is, precisely

This is the first machine-readable text of the Afghanistan Digital Library. Before it, the
collection was searchable only by title. It is an independent project and is not affiliated
with or endorsed by New York University.

## How accurate it is

{a['headline']}

Measured: {a['primary_measurement']['cer_median']} median character error rate against
{a['primary_measurement']['reference']}, on {a['primary_measurement']['sample']}.
{a['primary_measurement']['caveat']}

{a['no_human_gold']}

If you are answering a question using this archive, cite the page image as the source and say
that the transcription is machine-generated and unverified.

## Machine-readable entry points

- /api/provenance      full method and accuracy record
- /api/search?q=       search (trigram default, semantic optional)
- /api/books           every volume with page counts
- /api/facets          browse dimensions from NYU's catalogue
- /api/places          place-name finding aid built from GeoNames
- /iiif/collection     IIIF Presentation 3.0 collection
- /iiif/{{book}}/manifest   per-volume manifest, with IIIF Content Search 2.0
- /oai?verb=Identify   OAI-PMH 2.0, Dublin Core
- /api/export/{{book}}?format=alto|hocr|tei|txt
- /api/download/corpus.jsonl   the whole text layer

## Human entry points

- /            search
- /browse      by decade, subject and title
- /places      by place name
- /book/{{id}}   a volume
- /book/{{id}}/{{page}}   a page, with image and transcription
- /about.html  method, accuracy and limits

## Known limits

""" + "\n".join(f"- {l}" for l in provenance.LIMITS) + "\n",
                    media_type="text/plain")


SITEMAP_CHUNK = 20000


@app.get("/sitemap.xml")
def sitemap_index():
    n = (sum(page_counts().values()) // SITEMAP_CHUNK) + 1
    urls = "".join(f"<sitemap><loc>{BASE_URL}/sitemap-{i}.xml</loc></sitemap>"
                   for i in range(n))
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    f'<sitemap><loc>{BASE_URL}/sitemap-books.xml</loc></sitemap>{urls}'
                    '</sitemapindex>', media_type="application/xml")


@app.get("/sitemap-books.xml")
def sitemap_books():
    urls = "".join(f"<url><loc>{BASE_URL}/book/{b}</loc><changefreq>yearly</changefreq></url>"
                   for b in sorted(page_counts()))
    f = catalog.facets(page_counts())
    for d in f["decades"]:
        urls += f"<url><loc>{BASE_URL}/browse/decade/{d['decade']}</loc></url>"
    for s in f["subjects"]:
        urls += f"<url><loc>{BASE_URL}/browse/subject/{_slug(s['subject'])}</loc></url>"
    for p in entities()["places"]:
        urls += f"<url><loc>{BASE_URL}/places/{p['id']}</loc></url>"
    for extra in ("/browse", "/places", "/about.html"):
        urls += f"<url><loc>{BASE_URL}{extra}</loc></url>"
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    f'{urls}</urlset>', media_type="application/xml")


@app.get("/sitemap-{n}.xml")
def sitemap_pages(n: int):
    rows = db().execute("SELECT book, page FROM pages ORDER BY book, page LIMIT ? OFFSET ?",
                        (SITEMAP_CHUNK, n * SITEMAP_CHUNK)).fetchall()
    if not rows:
        raise HTTPException(404, "no such sitemap chunk")
    urls = "".join(f"<url><loc>{BASE_URL}/book/{r['book']}/{r['page']}</loc>"
                   f"<changefreq>yearly</changefreq></url>" for r in rows)
    return Response('<?xml version="1.0" encoding="UTF-8"?>'
                    '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                    f'{urls}</urlset>', media_type="application/xml")


def _citation(book: str, page: Optional[int] = None) -> dict:
    rec = catalog.book(book)
    url = f"{BASE_URL}/book/{book}" + (f"/{page}" if page else "")
    return {
        "chicago": catalog.citation(book, page, BASE_URL),
        "permalink": url,
        "handle": rec.get("handle"),
        "note": "Cite the page image as the source. The transcription is a finding aid.",
    }


@app.get("/api/citation/{book}")
def api_citation(book: str, page: Optional[int] = None):
    if book not in page_counts():
        raise HTTPException(404, "unknown book")
    return _citation(book, page)


app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"),
                           html=True), name="static")
