"""OAI-PMH 2.0 provider.

How libraries actually take a collection: they harvest it. A REST API with bespoke JSON means
somebody has to write an ingest script; an OAI-PMH endpoint means they point an existing
harvester at a URL and it appears alongside everything else they hold. It is also the route
into DPLA and other aggregators.

The record granularity is the VOLUME, not the page. A harvester wants 580 bibliographic
records it can shelve, not 69,624 fragments, and page-level access is what IIIF and the search
API are for.
"""
import re
from xml.sax.saxutils import escape

NS = 'xmlns="http://www.openarchives.org/OAI/2.0/" ' \
     'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' \
     'xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/ ' \
     'http://www.openarchives.org/OAI/2.0/OAI-PMH.xsd"'
DC_NS = 'xmlns:oai_dc="http://www.openarchives.org/OAI/2.0/oai_dc/" ' \
        'xmlns:dc="http://purl.org/dc/elements/1.1/" ' \
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" ' \
        'xsi:schemaLocation="http://www.openarchives.org/OAI/2.0/oai_dc/ ' \
        'http://www.openarchives.org/OAI/2.0/oai_dc.xsd"'
PREFIX = "oai:afghanpress.org:"
PAGE = 100                    # records per resumption chunk
DC_ELEMENTS = ["title", "creator", "subject", "description", "publisher", "contributor",
               "date", "type", "format", "identifier", "source", "language", "rights"]


def _env(base: str, verb_attr: str, body: str, stamp: str) -> str:
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<OAI-PMH {NS}>\n'
            f'<responseDate>{stamp}</responseDate>\n'
            f'<request {verb_attr}>{escape(base)}</request>\n{body}\n</OAI-PMH>')


def error(base: str, code: str, msg: str, stamp: str) -> str:
    return _env(base, "", f'<error code="{code}">{escape(msg)}</error>', stamp)


def _dc(bid: str, dc: dict) -> str:
    out = [f'<oai_dc:dc {DC_NS}>']
    for el in DC_ELEMENTS:
        for v in dc.get(el, []) or []:
            if v:
                out.append(f"  <dc:{el}>{escape(str(v))}</dc:{el}>")
    out.append("</oai_dc:dc>")
    return "\n".join(out)


def _header(bid: str, stamp: str, sets: list) -> str:
    """Identify declares YYYY-MM-DD granularity, so a record datestamp MUST be a bare date.
    Emitting a full timestamp here contradicts the repository's own declaration and a strict
    harvester is entitled to reject the record. responseDate keeps its full precision -- that
    one is a protocol timestamp, not a record datestamp."""
    s = "".join(f"<setSpec>{escape(x)}</setSpec>" for x in sets)
    return (f"<header><identifier>{PREFIX}{bid}</identifier>"
            f"<datestamp>{stamp[:10]}</datestamp>{s}</header>")


def sets_for(bid: str, cat_mod) -> list:
    out = []
    lo, _ = cat_mod.dates(bid)
    if lo:
        out.append(f"decade:{(lo // 10) * 10}")
    return out


def identify(base: str, stamp: str, earliest: str, admin: str) -> str:
    body = (f"<Identify><repositoryName>Afghan Press Archive</repositoryName>"
            f"<baseURL>{escape(base)}</baseURL><protocolVersion>2.0</protocolVersion>"
            f"<adminEmail>{escape(admin)}</adminEmail>"
            f"<earliestDatestamp>{earliest}</earliestDatestamp>"
            f"<deletedRecord>no</deletedRecord>"
            f"<granularity>YYYY-MM-DD</granularity>"
            f"<description><toolkit xmlns='http://afghanpress.org/oai'>"
            f"<title>Machine-transcribed text over the Afghanistan Digital Library</title>"
            f"</toolkit></description></Identify>")
    return _env(base, 'verb="Identify"', body, stamp)


def list_metadata_formats(base: str, stamp: str) -> str:
    body = ("<ListMetadataFormats><metadataFormat>"
            "<metadataPrefix>oai_dc</metadataPrefix>"
            "<schema>http://www.openarchives.org/OAI/2.0/oai_dc.xsd</schema>"
            "<metadataNamespace>http://www.openarchives.org/OAI/2.0/oai_dc/</metadataNamespace>"
            "</metadataFormat></ListMetadataFormats>")
    return _env(base, 'verb="ListMetadataFormats"', body, stamp)


def list_sets(base: str, stamp: str, decades: list) -> str:
    rows = "".join(
        f"<set><setSpec>decade:{d}</setSpec><setName>Published {d}s</setName></set>"
        for d in decades)
    return _env(base, 'verb="ListSets"', f"<ListSets>{rows}</ListSets>", stamp)


TOKEN = re.compile(r"^(\d+)(?::(.*))?$")


def list_records(base: str, stamp: str, books: list, counts: dict, cat_mod, verb: str,
                 token: str, setspec: str) -> str:
    """ListRecords / ListIdentifiers with a cursor resumption token.

    The token is just an offset because the corpus is static and ordered -- a finished
    historical artefact cannot shift under a harvester mid-walk, so nothing more elaborate
    (a snapshot id, a stable sort key) buys anything."""
    start = 0
    if token:
        m = TOKEN.match(token)
        if not m:
            return None                        # caller turns this into badResumptionToken
        start = int(m.group(1))
        setspec = m.group(2) or setspec
    if setspec:
        books = [b for b in books if setspec in sets_for(b, cat_mod)]
    chunk = books[start:start + PAGE]
    if not chunk:
        return None

    rows = []
    for b in chunk:
        hdr = _header(b, stamp, sets_for(b, cat_mod))
        if verb == "ListIdentifiers":
            rows.append(hdr)
        else:
            meta = _dc(b, cat_mod.dublin_core(b, counts.get(b, 0)))
            rows.append(f"<record>{hdr}<metadata>{meta}</metadata></record>")

    nxt = start + PAGE
    rt = ""
    if nxt < len(books):
        t = f"{nxt}:{setspec}" if setspec else str(nxt)
        rt = (f'<resumptionToken completeListSize="{len(books)}" cursor="{start}">'
              f"{escape(t)}</resumptionToken>")
    else:
        rt = f'<resumptionToken completeListSize="{len(books)}" cursor="{start}"/>'

    attr = f'verb="{verb}" metadataPrefix="oai_dc"'
    return _env(base, attr, f"<{verb}>{''.join(rows)}{rt}</{verb}>", stamp)


def get_record(base: str, stamp: str, bid: str, counts: dict, cat_mod) -> str:
    hdr = _header(bid, stamp, sets_for(bid, cat_mod))
    meta = _dc(bid, cat_mod.dublin_core(bid, counts.get(bid, 0)))
    body = f"<GetRecord><record>{hdr}<metadata>{meta}</metadata></record></GetRecord>"
    return _env(base, f'verb="GetRecord" identifier="{escape(PREFIX + bid)}" '
                      f'metadataPrefix="oai_dc"', body, stamp)
