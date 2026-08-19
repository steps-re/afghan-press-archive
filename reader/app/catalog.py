"""Bibliographic layer over the corpus.

corpus.db knows text and page numbers. It does not know that adl0616 is Mahmud Tarzi's
Siraj al-akhbar, printed in Kabul 1911-1918. Everything a library wants from this archive --
Dublin Core, a IIIF manifest label, a citation, browse-by-date -- is a question about the
BOOK, not the page, so the catalogue is loaded once and held in memory (580 records is
nothing) rather than joined out of SQLite on every request.

Every field here was copied from NYU's own record for that book. Nothing is inferred, and a
book whose record failed to parse is absent rather than approximated -- callers must handle
a missing entry instead of being handed a plausible blank.
"""
import json, os, re, threading
from typing import Optional

DATA = os.environ.get("ADL_DATA", "/data")
CATALOG_PATH = os.path.join(DATA, "catalog.json")

# NYU's own statement, verified on afghanistandl.nyu.edu/about.html 2026-08-12:
# "All works presented on this website are, unless otherwise indicated, in the public domain."
IMAGE_RIGHTS = {
    "statement": "Public domain. NYU states: \"All works presented on this website are, unless "
                 "otherwise indicated, in the public domain. The images available on this "
                 "website may be freely reproduced, distributed and transmitted by anyone for "
                 "any purpose, commercial or non-commercial.\"",
    "uri": "http://rightsstatements.org/vocab/NoC-US/1.0/",
    "holder": "New York University Libraries",
    "source": "https://afghanistandl.nyu.edu/about.html",
    # Said plainly because a manifest that credits NYU while serving bytes from our bucket
    # invites the reader to assume an institutional relationship that does not exist.
    "delivery": "Images are served from a copy mirrored by this project, not from NYU's "
                "servers, under the reproduction terms above.",
    "endorsement": "This is an independent project. It is not affiliated with, endorsed by, "
                   "or reviewed by New York University.",
}
# The text layer is our contribution and is machine-generated from public-domain originals.
# CC0 is the only licence that lets a library ingest it without a rights review.
TEXT_RIGHTS = {
    "statement": "Machine-generated transcription, dedicated to the public domain under CC0 1.0. "
                 "No warranty of accuracy: see the provenance block on every page.",
    "uri": "https://creativecommons.org/publicdomain/zero/1.0/",
    "holder": "Steps Ventures",
}

_lock = threading.Lock()
_cat: Optional[dict] = None


def catalog() -> dict:
    global _cat
    with _lock:
        if _cat is None:
            try:
                _cat = json.load(open(CATALOG_PATH, encoding="utf-8"))
            except (OSError, ValueError):
                # A missing catalogue must not take the archive down. Search and reading do not
                # depend on it; only the bibliographic surfaces degrade, and they degrade to
                # "unknown" rather than to a wrong answer.
                _cat = {}
    return _cat


def book(bid: str) -> dict:
    return catalog().get(bid, {})


def label(bid: str) -> str:
    """A human title for a book id, for manifest labels and result headers."""
    return (book(bid).get("title") or "").strip() or bid


LATIN = re.compile(r"[A-Za-zĀ-ſʻʿ]")


def title_parts(bid: str):
    """The ADL prints romanised and Arabic-script titles in one string ("Sirāj al-akhbār
    سراج الاخبار"). Interfaces need them apart: the romanised form for a Latin-script label
    and sort, the original script for display in the reading direction of the text."""
    b = book(bid)
    # The harvester now reads the romanised and Arabic-script titles from the separate cells
    # NYU prints them in, so prefer those exact values and keep the split below only for
    # records harvested before that change.
    if b.get("title_romanized") or b.get("title_original"):
        return {"romanized": (b.get("title_romanized") or "").strip(),
                "original": (b.get("title_original") or "").strip()}
    t = (b.get("title") or "").strip()
    if not t:
        return {"romanized": "", "original": ""}
    words = t.split()
    rom = [w for w in words if LATIN.search(w)]
    orig = [w for w in words if not LATIN.search(w)]
    return {"romanized": " ".join(rom).strip(), "original": " ".join(orig).strip()}


def dates(bid: str):
    b = book(bid)
    return b.get("year_start"), b.get("year_end")


def subjects(bid: str) -> list:
    s = book(bid).get("subjects") or []
    return s if isinstance(s, list) else [s]


def dublin_core(bid: str, pages: int = 0) -> dict:
    """Map a record to unqualified Dublin Core, the format OAI-PMH harvesters expect.

    Repeated elements are lists because oai_dc allows repetition and collapsing them to a
    single string would lose the distinction between an author and a contributor."""
    b = book(bid)
    parts = title_parts(bid)
    lo, hi = dates(bid)
    date = f"{lo}-{hi}" if lo and hi and lo != hi else (str(lo) if lo else "")
    titles = [t for t in (parts["romanized"], parts["original"]) if t] or [bid]
    ot = b.get("other_titles")
    titles.extend(ot if isinstance(ot, list) else [ot] if ot else [])
    creators = []
    for c in (b.get("author"), b.get("author_original"), b.get("contributors")):
        creators.extend(c if isinstance(c, list) else [c] if c else [])
    # The abstract is NYU's own summary of the volume and is the single most useful field for
    # a harvester deciding whether a record is relevant. It was being swallowed into the
    # publisher statement until the catalogue was re-harvested.
    desc = [d for d in (b.get("abstract"), b.get("description_physical"),
                        b.get("description_digital")) if d]
    if pages:
        desc.append(f"{pages} pages machine-transcribed at afghanpress.org")
    return {
        "title": titles,
        "creator": creators,
        "subject": subjects(bid),
        "description": desc,
        "publisher": [b["publisher"]] if b.get("publisher") else [],
        "date": [date] if date else [],
        "type": ["Text"],
        "format": ["text/plain"],
        "identifier": [i for i in (b.get("handle"), f"https://afghanpress.org/book/{bid}",
                                   b.get("source_record")) if i],
        # The originals are Persian and Pashto. The ADL record does not carry a language code
        # per book, so we assert only what the collection scope guarantees.
        "language": ["fas", "pus"],
        "rights": [IMAGE_RIGHTS["statement"], TEXT_RIGHTS["statement"]],
        "source": [b["source_record"]] if b.get("source_record") else [],
    }


def facets(counts: dict) -> dict:
    """Browse dimensions over the whole corpus. `counts` maps book id -> page count.

    Decade rather than year: these are periodicals running over several years, and a
    year-granular facet would scatter one publication across a dozen buckets."""
    decades, subj, by_title = {}, {}, []
    for bid, n in counts.items():
        lo, _ = dates(bid)
        if lo:
            d = (lo // 10) * 10
            e = decades.setdefault(d, {"decade": d, "books": 0, "pages": 0})
            e["books"] += 1
            e["pages"] += n
        for s in subjects(bid):
            head = s.split("--")[0].strip()          # LCSH heading, not the full subdivision
            if head:
                e = subj.setdefault(head, {"subject": head, "books": 0, "pages": 0})
                e["books"] += 1
                e["pages"] += n
        parts = title_parts(bid)
        by_title.append({"book": bid, "title": label(bid), "romanized": parts["romanized"],
                         "original": parts["original"], "pages": n,
                         "year_start": dates(bid)[0], "year_end": dates(bid)[1]})
    by_title.sort(key=lambda r: (r["romanized"] or "￿").lower())
    return {
        "decades": sorted(decades.values(), key=lambda r: r["decade"]),
        "subjects": sorted(subj.values(), key=lambda r: -r["pages"]),
        "titles": by_title,
    }


def citation(bid: str, page=None, base: str = "https://afghanpress.org") -> str:
    """One citation string for the whole site.

    There were three of these: the API built one, the server-rendered page built another, and
    the reader printed a third that named only the object number. A reader who cited from the
    page and one who cited from the API produced different references to the same thing.

    Assembled from the parts that exist rather than one format string, so a volume with no
    author or no publisher does not leave ". ." stranded mid-citation."""
    rec = book(bid)
    t = title_parts(bid)["romanized"] or label(bid)
    url = f"{base}/book/{bid}" + (f"/{page}" if page else "")
    bits = [b for b in (
        (rec.get("author") or "").rstrip("."),
        f"{t}, page {page}" if page else t,
        (rec.get("publisher") or "").rstrip("."),
        "Afghanistan Digital Library, New York University Libraries",
        rec.get("handle"),
        f"Machine-transcribed text, Afghan Press Archive, {url}",
    ) if b]
    return ". ".join(bits) + "."
