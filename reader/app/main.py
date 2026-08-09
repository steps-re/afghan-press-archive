"""Afghan Press Archive — search and reading API.  afghanpress.org

69,624 machine-read pages of Afghan periodicals (1870-1930s), the whole ADL collection.

Design constraints that come straight from the measurements (see ../../RESULTS.md):

  * The transcription is ~93% character-accurate against human gold, but exact search still
    fails: a scholar's remembered wording rarely matches the page character-for-character. So
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
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

DATA = os.environ.get("ADL_DATA", "/data")
DB_PATH = os.path.join(DATA, "corpus.db")
VEC_PATH = os.path.join(DATA, "corpus_vecs.npy")
IDS_PATH = os.path.join(DATA, "corpus_ids.json")
IMG_BASE = os.environ.get("ADL_IMG_BASE", "https://storage.googleapis.com/adl-page-images")
PROJECT = os.environ.get("ADL_PROJECT", os.environ.get("HTR_PROJECT", ""))
EMBED_MODEL = "text-multilingual-embedding-002"
EMBED_PROJECT = os.environ.get("ADL_EMBED_PROJECT", os.environ.get("HTR_PROJECT", ""))

app = FastAPI(title="Afghan Press Archive", docs_url="/api/docs")

# The design studies are a separate origin but drive this same API, so they can be judged as
# working interfaces rather than pictures. Read endpoints only — contributions still require a
# verified token, so a permissive read origin grants nothing a plain GET would not.
from fastapi.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https://(afghanpress\.org|www\.afghanpress\.org|afghan-press-[a-z]+-[0-9]+\.us-central1\.run\.app)|http://localhost(:[0-9]+)?",
    allow_methods=["GET", "POST"], allow_headers=["*"])

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
        # unseen trigrams are maximally selective — they exclude everything, so rank them first
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
    if mode in ("hybrid", "semantic"):
        qv = embed_query(q)
        if qv is not None:
            sem = search_semantic(qv, limit * 2, book)
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
            "semantic_available": bool(sem),
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
            "source": f"https://afghanistandl.nyu.edu/books/{book}/",
            "source_pdf": f"https://afghanistandl.nyu.edu/pdf/{book}_download.pdf",
            "provenance": "Machine-read, unverified. ~93% character accuracy measured against "
                          "human transcription (n=3). The page image is the primary source."}

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
    return {"apiKey": os.environ.get("ADL_FB_API_KEY", ""),
            "authDomain": os.environ.get("ADL_FB_AUTH_DOMAIN", ""),
            "projectId": os.environ.get("ADL_FIREBASE_PROJECT", PROJECT)}

@app.get("/api/healthz")
def api_health():
    n = db().execute("SELECT COUNT(*) c FROM pages").fetchone()["c"]
    return {"ok": n > 0, "pages": n}

@app.get("/api/stats")
def api_stats():
    r = db().execute("SELECT COUNT(*) n, COUNT(DISTINCT book) b, SUM(nchars) c FROM pages").fetchone()
    return {"pages": r["n"], "books": r["b"], "chars": r["c"],
            "accuracy_note": "~93% character accuracy vs human transcription (n=3); "
                             "search recall 81% top-20 on a long quote, 60% on a short one."}

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

@app.post("/api/contrib")
def api_contrib(payload: dict = Body(...), user: Optional[dict] = Depends(caller)):
    u = require(user)
    kind = payload.get("kind")
    if kind not in ("correction", "annotation", "feedback"):
        raise HTTPException(400, "kind must be correction, annotation or feedback")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "empty body")
    doc = {"kind": kind, "book": payload.get("book"), "page": payload.get("page"),
           "original": (payload.get("original") or "")[:4000], "body": body[:8000],
           "note": (payload.get("note") or "")[:2000],
           "uid": u["uid"], "email": u["email"],
           "created": time.time(),
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

app.mount("/", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static"),
                           html=True), name="static")
