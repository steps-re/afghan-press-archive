"""Harvest the ADL's own bibliographic record for every book in the corpus.

The transcription gives us text and nothing else: corpus.db knows a page belongs to
"adl0616" and not that adl0616 is Mahmud Tarzi's Siraj al-akhbar. Every librarian-facing
feature -- Dublin Core, IIIF manifest labels, faceted browse, a citation -- needs the
bibliographic layer, and NYU already holds an authoritative one on each book page.

So we harvest theirs rather than inventing our own. Nothing here is generated: each field is
copied from the ADL record and carries a source URL, and books whose record cannot be parsed
are recorded as failures rather than filled in with a guess.

The record is a two-column HTML table -- <td class="label">Field:</td> then a value cell
classed romanValue or arabicValue -- and this parses that structure directly. An earlier
version flattened the page to text and recovered fields with regexes anchored on the visible
labels, which cost real accuracy in the two places a scholar actually reads:

  * Subjects are separated by <br> and by nothing else once the tags are gone. Splitting the
    flattened run on a capitalisation heuristic shredded LCSH personal names, so NYU's
    "Amir of Afghanistan ʻAbd al-Raḥmān Khān" came back as "Amir of" plus a fragment.
  * "Abstract" was not in the label list, so the abstract was swallowed into the end of the
    publisher statement -- and from there into every generated citation.

Splitting on the markup removes the guesswork. A field is whatever NYU put in that cell.
"""
import json, os, re, sys, time, urllib.error, urllib.request

OUT = os.path.join(os.path.dirname(__file__), "..", "data", "catalog.json")
BASE = "https://afghanistandl.nyu.edu/books/{}/"
UA = "afghanpress.org catalog harvester (contact: mike@stepsventures.com)"
PACE = float(os.environ.get("HARVEST_PACE", "1.5"))   # seconds between requests

# ADL label -> our key. Anything NYU prints that is not in here is kept under a slugged key
# rather than dropped, so a new field on their side shows up as data instead of vanishing.
FIELDS = {
    "title": "title", "other titles": "other_titles", "author": "author",
    "contributors": "contributors", "publisher": "publisher", "abstract": "abstract",
    "subject(s)": "subjects", "description (physical)": "description_physical",
    "description (digital)": "description_digital", "object number": "object_number",
    "citation link": "handle", "downloadable pdf": "pdf",
}
# Fields NYU prints as a <br>-separated list rather than a single value.
MULTI = {"subjects", "other_titles", "contributors"}

HREF = re.compile(r'href\s*=\s*"([^"]*)"', re.I)

# The record table is nested inside a wrapper row that also holds the cover thumbnail, so
# walking <tr> elements catches the wrapper and loses the first field. Match label/value cell
# PAIRS instead, in document order: either a labelled field, or a continuation row whose label
# cell is empty because it carries the Arabic-script form of the field above it.
PAIR = re.compile(
    r'<td[^>]*class="label"[^>]*>(?P<lab>.*?)</td>\s*<td(?P<attrs>[^>]*)>(?P<val>.*?)</td>'
    r'|<td\s*>\s*</td>\s*<td(?P<cattrs>[^>]*)>(?P<cval>.*?)</td>',
    re.S | re.I)
CLASS = re.compile(r'class\s*=\s*"([^"]*)"', re.I)


def _text(html: str) -> str:
    """Cell text with <br> already consumed by the caller. Entities resolved, tags dropped."""
    import html as H
    t = re.sub(r"<[^>]+>", " ", html)
    t = H.unescape(t).replace(" ", " ")
    # Directional marks are invisible but survive into JSON, sort keys and citations.
    t = t.replace("‎", "").replace("‏", "")
    return re.sub(r"\s+", " ", t).strip()


def _parts(html: str) -> list:
    """A value cell split on <br>, which is the only separator NYU uses inside a cell."""
    return [p for p in (_text(x) for x in re.split(r"<br\s*/?>", html, flags=re.I)) if p]


def parse(html: str) -> dict:
    """Walk the record table. A row with an empty label cell continues the field above it,
    which is how the ADL prints the Arabic-script form of a title or publisher."""
    rec, last = {}, None
    for m in PAIR.finditer(html):
        labelled = m.group("lab") is not None
        attrs = m.group("attrs") if labelled else m.group("cattrs")
        val_html = m.group("val") if labelled else m.group("cval")
        m_cls = CLASS.search(attrs or "")
        cls = (m_cls.group(1) if m_cls else "").lower()
        if not labelled and "value" not in cls:
            continue
        label = _text(m.group("lab")).rstrip(":").strip().lower() if labelled else ""
        key = FIELDS.get(label) or (re.sub(r"[^a-z0-9]+", "_", label).strip("_") if label
                                    else last)
        if not key:
            continue
        # Citation Link and PDF carry the value in the anchor, not the anchor text.
        href = HREF.search(val_html)
        if key in ("handle", "pdf") and href:
            rec[key] = href.group(1)
            last = key
            continue
        parts = _parts(val_html)
        if not parts:
            continue
        if key in MULTI:
            rec.setdefault(key, []).extend(parts)
        elif key in rec:
            # A continuation row, or a second script for the same field. Keep it beside the
            # first rather than concatenating: "Kābul, 1310 , . ١٣١٠." is not a publisher.
            rec.setdefault(f"{key}_original" if "arabic" in cls else f"{key}_alt", []).extend(parts)
        else:
            rec[key] = " ".join(parts)
        last = key
    for k in list(rec):
        if k.endswith(("_original", "_alt")) and isinstance(rec[k], list):
            rec[k] = " ".join(rec[k])
    return rec


YEAR = re.compile(r"\b(\d{3,4})\b")
BRACKET = re.compile(r"\[([^\]]*)\]")
# A Gregorian imprint year for this collection sits in this range. Anything below it in an ADL
# publisher statement is the Hijri year, which the ADL prints first: "1310 [1892 or 1893]".
GREGORIAN = range(1600, 2030)


def years(rec: dict):
    """Split the publisher statement's dates into Gregorian and Hijri.

    Taking every 4-digit run as Gregorian filed 509 of 579 volumes under decades like 1290 and
    1310, so browse-by-date put an 1892 book eight centuries from an 1893 one. The ADL prints
    the Hijri year and then glosses it in brackets, so the Gregorian year is recoverable by
    range without converting anything: we are choosing which printed number is which calendar,
    not deriving a date. 9 volumes carry no Gregorian year at all and keep None rather than a
    guess -- they browse as undated."""
    pub = rec.get("publisher", "")
    inside = [int(y) for b in BRACKET.findall(pub) for y in YEAR.findall(b)]
    outside = [int(y) for y in YEAR.findall(BRACKET.sub(" ", pub))]
    greg = sorted({y for y in (inside or outside) if y in GREGORIAN})
    if not greg:                       # bracket held only a Hijri restatement
        greg = sorted({y for y in inside + outside if y in GREGORIAN})
    hijri = sorted({y for y in inside + outside if y not in GREGORIAN and y >= 1000})
    rec["year_hijri_start"] = hijri[0] if hijri else None
    rec["year_hijri_end"] = hijri[-1] if hijri else None
    return (greg[0], greg[-1]) if greg else (None, None)


def fetch(book: str) -> dict:
    req = urllib.request.Request(BASE.format(book), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        html = r.read().decode("utf-8", "replace")
    rec = parse(html)
    # A few ADL records leave Title empty and carry the actual title under Other Titles
    # (adl0957 is "new guide to Afghanistan" that way). Rejecting those left volumes rendering
    # as a bare identifier, which reads as a broken page rather than a thin record.
    if not rec.get("title") and rec.get("other_titles"):
        ot = rec["other_titles"]
        rec["title"] = ot[0] if isinstance(ot, list) else ot
        rec["title_source"] = "other_titles (ADL Title field is empty)"
    if not rec.get("title"):
        raise ValueError("no title parsed")
    # The romanised and Arabic-script titles arrive in separate cells, so record them apart
    # rather than leaving every caller to re-split one combined string by character range.
    rec["title_romanized"] = rec["title"]
    if rec.get("title_original"):
        rec["title"] = f"{rec['title']} {rec['title_original']}".strip()
    lo, hi = years(rec)
    rec["year_start"], rec["year_end"] = lo, hi
    rec["book"] = book
    rec["source_record"] = BASE.format(book)
    return rec


def main():
    books = sys.argv[1:]
    if not books:
        import sqlite3
        db = sqlite3.connect(os.path.join(os.path.dirname(__file__), "..", "data", "corpus.db"))
        books = [r[0] for r in db.execute("SELECT DISTINCT book FROM pages ORDER BY book")]

    out = {}
    if os.path.exists(OUT) and os.environ.get("HARVEST_RESUME"):
        out = json.load(open(OUT))          # resumable: a 580-request polite crawl is ~15 min
    failed = []
    for i, b in enumerate(books, 1):
        if b in out:
            continue
        try:
            out[b] = fetch(b)
        except Exception as e:
            failed.append({"book": b, "error": str(e)})
            print(f"  FAIL {b}: {e}", flush=True)
        if i % 25 == 0:
            print(f"  {i}/{len(books)} ({len(out)} held)", flush=True)
            json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
        time.sleep(PACE)

    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)
    print(f"done: {len(out)} records, {len(failed)} failures -> {OUT}")
    json.dump(failed, open(OUT.replace(".json", "_failures.json"), "w"), indent=1)


if __name__ == "__main__":
    main()
