"""Server-rendered, addressable pages for every volume and every page.

The search interface is a single-page app, which means that until now nothing in this archive
had a URL. A scholar could not cite a page, a sitemap had nothing to list, a search engine saw
one document where there are 69,624, and a IIIF manifest's `homepage` had nowhere to point.
Rendering these server-side fixes all four at once, and has the useful side effect that the
archive is fully readable with JavaScript switched off -- which is also the accessible path.

These are deliberately plain: metadata, the page image, the transcription, the provenance, and
links to the machine-readable forms of all of it. The rich interface lives at /.
"""
from html import escape
from urllib.parse import quote

CSS = """
:root{--paper:#faf5e8;--ink:#221d14;--soft:#6f6757;--rule:#ddd4be;--lapis:#1f3a6e;
--gold:#b08d3f;--madder:#7c3b2e;--sans:"Helvetica Neue",Helvetica,Arial,sans-serif;
--arabic:Amiri,"Noto Naskh Arabic","Scheherazade New",serif;color-scheme:light}
@font-face{font-family:Amiri;src:url(/fonts/amiri-arabic.woff2) format('woff2');
unicode-range:U+0600-06FF,U+0750-077F,U+08A0-08FF,U+200C-200E,U+FB50-FDFF,U+FE70-FEFC;
font-display:swap}
*{box-sizing:border-box}
body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.62 var(--sans)}
.wrap{max-width:1060px;margin:0 auto;padding:0 30px 70px}
a{color:var(--lapis)}
a:focus-visible,button:focus-visible{outline:3px solid var(--madder);outline-offset:2px}
.khatam{height:22px;margin:0 -30px;background:
repeating-conic-gradient(from 45deg,var(--madder) 0 25%,transparent 0 50%) 0 0/22px 22px,
repeating-conic-gradient(from 45deg,var(--gold) 0 25%,transparent 0 50%) 11px 11px/22px 22px;
opacity:.42}
header.top{padding:22px 0 0}
.crumb{font-size:13px;color:var(--soft);letter-spacing:.04em}
h1{font-size:30px;line-height:1.25;margin:14px 0 2px;color:var(--lapis);font-weight:700}
h1.ar{font-family:var(--arabic);direction:rtl;font-size:44px;font-weight:400}
.sub{color:var(--soft);font-size:14.5px;margin:0 0 22px}
.rule{border:0;border-top:3px solid var(--ink);margin:26px 0 0}
.rule.thin{border-top:1px solid var(--rule)}
dl.meta{display:grid;grid-template-columns:190px 1fr;gap:7px 22px;font-size:15px;margin:22px 0}
dl.meta dt{color:var(--madder);font-weight:700;font-size:12px;letter-spacing:.09em;
text-transform:uppercase;padding-top:3px}
dl.meta dd{margin:0}
.cols{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:34px;margin:26px 0}
@media(max-width:820px){.cols{grid-template-columns:1fr}dl.meta{grid-template-columns:1fr}}
.scan{width:100%;height:auto;border:1px solid var(--rule);background:#fff}
.txt{font-family:var(--arabic);direction:rtl;text-align:right;font-size:22px;line-height:2.05;
white-space:pre-wrap;word-wrap:break-word}
.lbl{font-size:12px;letter-spacing:.09em;text-transform:uppercase;color:var(--madder);
font-weight:700;margin:0 0 10px}
.note{font-size:13.5px;color:var(--soft);border-left:3px solid var(--gold);padding:2px 0 2px 14px;
margin:20px 0}
.pager{display:flex;gap:18px;align-items:center;flex-wrap:wrap;margin:26px 0;font-size:15px}
.pager .sp{flex:1}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(158px,1fr));gap:16px;margin:22px 0}
.grid a{display:block;border-bottom:0;font-size:13px;color:var(--soft)}
.grid img{width:100%;height:auto;border:1px solid var(--rule);background:#fff;display:block}
ul.plain{list-style:none;padding:0;margin:16px 0}
ul.plain li{padding:7px 0;border-bottom:1px solid var(--rule);font-size:15px}
.tag{display:inline-block;font-size:12px;color:var(--soft);border:1px solid var(--rule);
padding:2px 8px;margin:0 6px 6px 0;border-radius:2px}
footer{margin-top:44px;padding-top:18px;border-top:1px solid var(--rule);font-size:13px;
color:var(--soft)}
.skip{position:absolute;left:-9999px}
.skip:focus{left:8px;top:8px;position:fixed;background:var(--paper);padding:10px 14px;z-index:9}
"""


def dublin_core_meta(rec: dict, title: str, date: str, url: str, page=None) -> str:
    """Dublin Core as <meta>, plus a canonical URL.

    schema.org JSON-LD is what search engines read. It is not what a scholar's tools read:
    Zotero, and most library-side harvesters, look for Dublin Core meta tags or a COinS span.
    Without either, capturing a page meant retyping the citation by hand, which for the audience
    this archive is built for is the difference between usable and not."""
    def m(name, value):
        return f'<meta name="{name}" content="{escape(str(value))}">' if value else ""
    subj = rec.get("subjects") or []
    # DC.date wants ISO 8601. An en dash is display punctuation and a harvester will not parse
    # it; "1911/1918" is the ISO interval form.
    iso_date = date.replace("\u2013", "/") if date else ""
    rows = [
        f'<link rel="canonical" href="{escape(url)}">',
        m("DC.title", title if page is None else f"{title}, page {page}"),
        m("DC.creator", rec.get("author")),
        m("DC.publisher", rec.get("publisher")),
        m("DC.date", iso_date),
        m("DC.type", "Text"),
        m("DC.format", "text/html"),
        m("DC.identifier", url),
        m("DC.source", rec.get("source_record")),
        m("DC.rights", "https://creativecommons.org/publicdomain/zero/1.0/"),
    ]
    rows += [m("DC.language", l) for l in ("fa", "ps")]
    rows += [m("DC.subject", s) for s in subj[:8]]
    if rec.get("handle"):
        rows.append(m("DC.relation", rec["handle"]))
    return "\n".join(r for r in rows if r)


def coins(rec: dict, title: str, date: str, url: str, page=None) -> str:
    """A COinS span: an OpenURL ContextObject that Zotero picks up with no translator of ours.

    It is invisible, it is the most widely supported one-click capture there is, and it costs a
    span. `bookitem` for a page, `book` for a volume, which is how a periodical issue in a bound
    run is normally described to a reference manager."""
    f = [("ctx_ver", "Z39.88-2004"),
         ("rft_val_fmt", "info:ofi/fmt:kev:mtx:book"),
         ("rft.genre", "book" if page is None else "bookitem"),
         ("rft.btitle", title), ("rft.title", title),
         ("rft.au", rec.get("author") or ""), ("rft.pub", rec.get("publisher") or ""),
         # OpenURL rft.date is a single date; give the first year of the run.
         ("rft.date", (date or "").split("\u2013")[0]), ("rft.language", "fas"),
         ("rft_id", url)]
    if page is not None:
        f += [("rft.spage", str(page)), ("rft.pages", str(page))]
    if rec.get("handle"):
        f.append(("rft_id", rec["handle"]))
    q = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in f if v)
    return f'<span class="Z3988" title="{escape(q)}"></span>'


def shell(title: str, body: str, desc: str = "", jsonld: str = "", lang: str = "en",
          head_extra: str = "") -> str:
    return f"""<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<meta name="description" content="{escape(desc)}">
{head_extra}
<style>{CSS}</style>
{jsonld}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<div class="wrap">
<div class="khatam" role="presentation"></div>
{body}
<footer>
<p><a href="/">Afghan Press Archive</a> · <a href="/about.html">Method and limits</a> ·
<a href="/browse">Browse</a> · <a href="/places">Places</a> ·
<a href="/iiif/collection">IIIF</a> · <a href="/oai?verb=Identify">OAI-PMH</a></p>
<p>Page images: Afghanistan Digital Library, New York University Libraries, public domain.
Transcription: machine-generated, CC0. The image is the source of record.</p>
</footer>
</div>
</body>
</html>"""


def _meta_rows(rec, cat_mod, book):
    rows = []

    def add(k, v):
        if v:
            rows.append(f"<dt>{escape(k)}</dt><dd>{v}</dd>")

    def esc(v):
        """NYU prints several fields as a <br>-separated list and the catalogue keeps them as
        one, so a value here is a string or a list of them. escape() takes only strings."""
        if isinstance(v, (list, tuple)):
            return "<br>".join(escape(str(x)) for x in v if x)
        return escape(str(v)) if v else ""

    add("Title", esc(rec.get("title")))
    add("Other titles", esc(rec.get("other_titles")))
    add("Author", esc(rec.get("author")))
    add("Contributors", esc(rec.get("contributors")))
    add("Published", esc(rec.get("publisher")))
    subs = cat_mod.subjects(book)
    if subs:
        add("Subjects", "".join(f'<span class="tag">{escape(s)}</span>' for s in subs))
    add("Physical description", escape(rec.get("description_physical", "")))
    add("Identifier", escape(rec.get("object_number") or book))
    if rec.get("handle"):
        h = escape(rec["handle"])
        add("Persistent link", f'<a href="{h}">{h}</a>')
    if rec.get("source_record"):
        s = escape(rec["source_record"])
        add("Catalogue record", f'<a href="{s}">Afghanistan Digital Library</a>')
    return "".join(rows)


def book_page(book: str, pages: list, cat_mod, prov_mod, base: str, img_base: str) -> str:
    rec = cat_mod.book(book)
    parts = cat_mod.title_parts(book)
    lo, hi = cat_mod.dates(book)
    date = f"{lo}–{hi}" if lo and hi and lo != hi else (str(lo) if lo else "")
    n = len(pages)
    title = parts["romanized"] or cat_mod.label(book)

    jsonld = f"""<script type="application/ld+json">{{
"@context":"https://schema.org","@type":"Book","name":{_j(title)},
"alternateName":{_j(parts['original'])},"identifier":{_j(book)},
"inLanguage":["fa","ps"],"datePublished":{_j(date)},
"author":{_j(rec.get('author',''))},"publisher":{_j(rec.get('publisher',''))},
"numberOfPages":{n},"isAccessibleForFree":true,
"license":"https://creativecommons.org/publicdomain/zero/1.0/",
"url":{_j(base + '/book/' + book)},
"provider":{{"@type":"Organization","name":"Afghan Press Archive"}},
"sourceOrganization":{{"@type":"Organization","name":"New York University Libraries"}}
}}</script>"""

    thumbs = "".join(
        f'<a href="/book/{book}/{p}"><img loading="lazy" src="{img_base}/{book}/{p:05d}.jpg" '
        f'alt="Page {p} of {escape(title)}"><span>{p}</span></a>'
        for p in pages[:60])
    more = (f'<p class="note">Showing the first 60 of {n} pages. '
            f'<a href="/book/{book}/{pages[0]}">Start reading</a>.</p>' if n > 60 else "")

    # A volume with no bibliographic record still has to read as a real thing rather than a
    # bare identifier. adl0277 is the live case: the ADL serves an empty page for its record,
    # so there is nothing to copy and saying so is better than showing a blank.
    norec = "" if rec else (
        '<p class="note">The Afghanistan Digital Library does not currently serve a catalogue '
        f'record for this volume, so no title, author or date is available. The scanned pages '
        f'and the <a href="https://afghanistandl.nyu.edu/pdf/{book}_download.pdf">source PDF</a> '
        'exist. We have reported this to NYU.</p>')

    body = f"""
<header class="top">
<p class="crumb"><a href="/browse">Browse</a> → {escape(book)}</p>
<h1>{escape(title)}</h1>
{f'<h1 class="ar" lang="fa" dir="rtl">{escape(parts["original"])}</h1>' if parts["original"] else ''}
<p class="sub">{n} pages{' · ' + escape(date) if date else ''}</p>
<hr class="rule">
</header>
<main id="main">
{norec}
<dl class="meta">{_meta_rows(rec, cat_mod, book)}
<dt>Transcription</dt><dd>{escape(prov_mod.METHOD['model'])}, completed
{escape(prov_mod.CORPUS['read_completed'])}.
<a href="/api/provenance">Method and measured accuracy</a></dd>
<dt>Machine-readable</dt><dd>
<a href="/iiif/{book}/manifest">IIIF manifest</a> ·
<a href="/api/export/{book}?format=alto">ALTO</a> ·
<a href="/api/export/{book}?format=hocr">hOCR</a> ·
<a href="/api/export/{book}?format=tei">TEI</a> ·
<a href="/api/export/{book}?format=txt">Plain text</a> ·
<a href="/api/download/book/{book}.jsonl">JSONL</a> ·
<a href="/oai?verb=GetRecord&amp;metadataPrefix=oai_dc&amp;identifier=oai:afghanpress.org:{book}">Dublin Core</a>
</dd>
</dl>
<p class="note">{escape(prov_mod.ACCURACY['headline'])}</p>
{more}
<div class="grid">{thumbs}</div>
</main>"""
    url = f"{base}/book/{book}"
    head = dublin_core_meta(rec, title, date, url) + f"""
<link rel="alternate" type="application/ld+json" title="IIIF Presentation 3.0 manifest" href="{base}/iiif/{book}/manifest">
<link rel="alternate" type="text/xml" title="ALTO XML" href="{base}/api/export/{book}?format=alto">
<link rel="alternate" type="text/xml" title="TEI XML" href="{base}/api/export/{book}?format=tei">
<link rel="alternate" type="application/x-ndjson" title="Transcription as JSONL" href="{base}/api/download/book/{book}.jsonl">
<link rel="alternate" type="text/xml" title="Dublin Core via OAI-PMH" href="{base}/oai?verb=GetRecord&amp;metadataPrefix=oai_dc&amp;identifier=oai:afghanpress.org:{book}">"""
    body += coins(rec, title, date, url)
    return shell(f"{title} — Afghan Press Archive", body,
                 desc=f"{title}. {n} pages, machine-transcribed. {date}", jsonld=jsonld,
                 head_extra=head)


def reader_page(book: str, page: int, text: str, first: int, last: int, prev: int, nxt: int,
                cat_mod, prov_mod, base: str, img_base: str, corrections: list) -> str:
    parts = cat_mod.title_parts(book)
    rec = cat_mod.book(book)
    title = parts["romanized"] or cat_mod.label(book)
    lo, hi = cat_mod.dates(book)
    date = f"{lo}\u2013{hi}" if lo and hi and lo != hi else (str(lo) if lo else "")
    img = f"{img_base}/{book}/{page:05d}.jpg"
    cite = cat_mod.citation(book, page, base)

    jsonld = f"""<script type="application/ld+json">{{
"@context":"https://schema.org","@type":"DigitalDocument","name":{_j(title + ', page ' + str(page))},
"isPartOf":{{"@type":"Book","name":{_j(title)},"url":{_j(base + '/book/' + book)}}},
"inLanguage":"fa","isAccessibleForFree":true,
"license":"https://creativecommons.org/publicdomain/zero/1.0/",
"url":{_j(f'{base}/book/{book}/{page}')},"image":{_j(img)},
"text":{_j((text or '')[:1200])}
}}</script>"""

    corr = ""
    if corrections:
        items = "".join(
            f'<li lang="fa" dir="rtl" class="txt" style="font-size:18px">{escape(c.get("body",""))}'
            f'<br><span style="font-family:var(--sans);direction:ltr;font-size:12px;'
            f'color:var(--soft)">— {escape(c.get("email","") .split("@")[0])}</span></li>'
            for c in corrections)
        corr = f'<hr class="rule thin"><p class="lbl">Reader corrections</p><ul class="plain">{items}</ul>'

    body = f"""
<header class="top">
<p class="crumb"><a href="/browse">Browse</a> →
<a href="/book/{book}">{escape(title)}</a> → page {page}</p>
<h1>Page {page}</h1>
<p class="sub"><a href="/book/{book}">{escape(title)}</a> · pages {first}–{last}</p>
<hr class="rule">
</header>
<main id="main">
<nav class="pager" aria-label="Page navigation">
{f'<a href="/book/{book}/{prev}" rel="prev">← Previous</a>' if prev else '<span></span>'}
<span class="sp"></span>
<a href="/?book={book}&amp;page={page}">Open in the search interface</a>
<span class="sp"></span>
{f'<a href="/book/{book}/{nxt}" rel="next">Next →</a>' if nxt else '<span></span>'}
</nav>
<div class="cols">
<div>
<p class="lbl">Page image — the source of record</p>
<a href="{img}"><img class="scan" src="{img}" alt="Scanned page {page} of {escape(title)}"
width="2550" height="3301"></a>
</div>
<div>
<p class="lbl">Machine transcription</p>
<div class="txt" lang="fa" dir="rtl">{escape(text or '')}</div>
{corr}
</div>
</div>
<p class="note">{escape(prov_mod.ACCURACY['headline'])}
<a href="/api/provenance">How this was measured</a>.</p>
<hr class="rule thin">
<dl class="meta">
<dt>Cite this page</dt><dd>{escape(cite)}</dd>
<dt>Permalink</dt><dd><a href="{base}/book/{book}/{page}">{base}/book/{book}/{page}</a></dd>
<dt>Machine-readable</dt><dd>
<a href="/api/page/{book}/{page}">JSON</a> ·
<a href="/iiif/{book}/manifest">IIIF manifest</a> ·
<a href="/iiif/{book}/canvas/{page}">Canvas</a></dd>
<dt>Source</dt><dd><a href="https://afghanistandl.nyu.edu/books/{book}/">Afghanistan Digital
Library record</a></dd>
</dl>
</main>"""
    purl = f"{base}/book/{book}/{page}"
    head = dublin_core_meta(rec, title, date, purl, page=page) + f"""
<link rel="alternate" type="application/ld+json" title="IIIF Presentation 3.0 manifest" href="{base}/iiif/{book}/manifest">
<link rel="alternate" type="application/ld+json" title="Transcription as a IIIF annotation" href="{base}/iiif/{book}/canvas/{page}/text">
<link rel="alternate" type="text/plain" title="Volume as plain text" href="{base}/api/export/{book}?format=txt">
<link rel="up" href="{base}/book/{book}">"""
    body += coins(rec, title, date, purl, page=page)
    return shell(f"{title}, page {page} — Afghan Press Archive", body,
                 desc=f"Page {page} of {title}, with page image and machine transcription.",
                 jsonld=jsonld, head_extra=head)


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def browse_page(facets: dict, base: str, heading: str = "", crumb: str = "") -> str:
    dec = "".join(
        f'<li><a href="/browse/decade/{d["decade"]}">{d["decade"]}s</a> — '
        f'{d["books"]} volumes, {d["pages"]:,} pages</li>' for d in facets["decades"])
    subj = "".join(
        f'<li><a href="/browse/subject/{_slug(s["subject"])}">{escape(s["subject"])}</a> — '
        f'{s["books"]} volumes, {s["pages"]:,} pages</li>' for s in facets["subjects"][:40])
    titles = "".join(
        f'<li><a href="/book/{t["book"]}">{escape(t["romanized"] or t["book"])}</a> '
        f'<span lang="fa" dir="rtl" style="font-family:var(--arabic)">{escape(t["original"])}</span> — '
        f'{t["pages"]:,} pages{" · " + str(t["year_start"]) if t["year_start"] else ""}</li>'
        for t in facets["titles"])
    crumbs = ('<a href="/">Afghan Press Archive</a> → <a href="/browse">Browse</a> → '
              + escape(crumb)) if crumb else '<a href="/">Afghan Press Archive</a> → Browse'
    n = len(facets["titles"])
    npages = sum(t["pages"] for t in facets["titles"])
    body = f"""
<header class="top">
<p class="crumb">{crumbs}</p>
<h1>{escape(heading) if heading else 'Browse the collection'}</h1>
<p class="sub">{n} volume{'s' if n != 1 else ''}, {npages:,} pages. Bibliographic data from the
Afghanistan Digital Library's own catalogue.</p>
<hr class="rule">
</header>
<main id="main">
<h2>By decade</h2><ul class="plain">{dec}</ul>
<h2>By subject</h2><ul class="plain">{subj}</ul>
<h2>{'Volumes' if heading else 'All volumes'}</h2><ul class="plain">{titles}</ul>
</main>"""
    t = f"{heading} — Afghan Press Archive" if heading else "Browse — Afghan Press Archive"
    d = (f"{heading}: {n} volumes, {npages:,} pages of Afghan print, machine-transcribed and "
         f"searchable." if heading else
         "Browse 580 volumes of Afghan periodicals by decade, subject and title.")
    return shell(t, body, desc=d)


def places_page(places: list, meta: dict, base: str) -> str:
    rows = "".join(
        f'<li><a href="/places/{p["id"]}">{escape(p["name"])}</a> — {p["pages"]:,} pages in '
        f'{p["books"]} volumes <span class="tag">{escape(p["country"])}</span></li>'
        for p in places[:400])
    body = f"""
<header class="top">
<p class="crumb"><a href="/">Afghan Press Archive</a> → Places</p>
<h1>Places named in the corpus</h1>
<p class="sub">{len(places):,} place names from GeoNames found by exact match in the
transcribed text.</p>
<hr class="rule">
</header>
<main id="main">
<p class="note">{escape(meta.get('method', ''))} A match means those characters appear on that
page. It is a pointer into the text, not a claim about what the page is about. Names that
occur on more than 2% of pages are dropped as ordinary Persian words rather than places.</p>
<ul class="plain">{rows}</ul>
</main>"""
    return shell("Places — Afghan Press Archive", body,
                 desc="Browse Afghan and regional place names found in the corpus.")


def place_page(place: dict, cat_mod, base: str) -> str:
    hits = "".join(
        f'<li><a href="/book/{h["book"]}/{h["page"]}">{escape(cat_mod.label(h["book"]))}, '
        f'page {h["page"]}</a></li>' for h in place["sample"])
    var = "".join(f'<span class="tag" lang="fa" dir="rtl">{escape(v)}</span>'
                  for v in place["variants"])
    body = f"""
<header class="top">
<p class="crumb"><a href="/places">Places</a> → {escape(place['name'])}</p>
<h1>{escape(place['name'])}</h1>
<p class="sub">{place['pages']:,} pages in {place['books']} volumes ·
{place['lat']:.3f}, {place['lon']:.3f} ·
<a href="{escape(place['source'])}">GeoNames</a></p>
<hr class="rule">
</header>
<main id="main">
<p>{var}</p>
<h2>Pages</h2>
<ul class="plain">{hits}</ul>
</main>"""
    return shell(f"{place['name']} — Afghan Press Archive", body,
                 desc=f"Pages naming {place['name']} in the Afghan press corpus.")


def error_page(code: int, detail: str) -> str:
    body = f"""
<header class="top">
<p class="crumb"><a href="/">Afghan Press Archive</a></p>
<h1>{code}</h1>
<p class="sub">{escape(str(detail))}</p>
<hr class="rule">
</header>
<main id="main">
<p>The address you asked for is not in this archive. That is usually a page number past the end
of a volume, or a volume identifier that does not exist.</p>
<ul class="plain">
<li><a href="/">Search the collection</a></li>
<li><a href="/browse">Browse 580 volumes by decade, subject or title</a></li>
<li><a href="/places">Browse by place name</a></li>
<li><a href="/about.html">How the text was made, and how far to trust it</a></li>
</ul>
</main>"""
    return shell(f"{code} — Afghan Press Archive", body,
                 desc="Page not found in the Afghan Press Archive.")


def _j(s) -> str:
    import json
    return json.dumps(s or "", ensure_ascii=False)
