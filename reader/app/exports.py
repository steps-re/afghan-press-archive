"""Standard-format exports of the text layer.

JSONL is what we happen to store. ALTO, hOCR and TEI are what the receiving side already
speaks -- a digital-library pipeline ingests ALTO without anyone writing code, and a DH project
wants TEI. Offering only our own shape quietly pushes the integration cost onto them.

The coordinate problem is handled the same way everywhere: the reader produced page-level text
with no layout analysis, so no element carries a position derived from the image. ALTO and hOCR
require boxes on their structural elements, so the full print space is used and every export
says plainly, in a machine-readable processing note, that positions are not layout-derived and
must not be used to locate text on the page. Evenly divided line boxes would validate just as
well and would be fabricated data.
"""
from xml.sax.saxutils import escape

PAGE_W, PAGE_H = 2550, 3301
NOCOORD = ("Page-level transcription with no layout analysis. Element coordinates span the "
           "full print space and are NOT derived from the image. Do not use them to locate "
           "text on the page.")


def _lines(text: str):
    return [l for l in (text or "").split("\n") if l.strip()]


def alto(book: str, rows: list, cat_mod, prov_mod) -> str:
    """ALTO 4.2. `rows` is [(page, text), ...] in order."""
    m = prov_mod.METHOD
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<alto xmlns="http://www.loc.gov/standards/alto/ns-v4#" '
           'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
           'xsi:schemaLocation="http://www.loc.gov/standards/alto/ns-v4# '
           'http://www.loc.gov/standards/alto/v4/alto-4-2.xsd">',
           '<Description><MeasurementUnit>pixel</MeasurementUnit>',
           f'<sourceImageInformation><fileName>{escape(book)}</fileName>'
           f'</sourceImageInformation>',
           '<OCRProcessing ID="OCR_1"><ocrProcessingStep>',
           f'<processingDateTime>{prov_mod.CORPUS["read_completed"]}</processingDateTime>',
           '<processingStepDescription>Whole-page transcription by a vision language model'
           '</processingStepDescription>',
           f'<processingSoftware><softwareName>{escape(m["model"])}</softwareName>'
           f'<softwareVersion>thinkingLevel={escape(m["thinking_level"])}</softwareVersion>'
           f'</processingSoftware>',
           f'<processingStepSettings>{escape(NOCOORD)} '
           f'{escape(prov_mod.ACCURACY["headline"])}</processingStepSettings>',
           '</ocrProcessingStep></OCRProcessing></Description>',
           '<Layout>']
    for page, text in rows:
        out.append(f'<Page ID="P{page}" PHYSICAL_IMG_NR="{page}" WIDTH="{PAGE_W}" '
                   f'HEIGHT="{PAGE_H}">')
        out.append(f'<PrintSpace HPOS="0" VPOS="0" WIDTH="{PAGE_W}" HEIGHT="{PAGE_H}">')
        out.append(f'<TextBlock ID="P{page}_B1" HPOS="0" VPOS="0" WIDTH="{PAGE_W}" '
                   f'HEIGHT="{PAGE_H}">')
        for i, line in enumerate(_lines(text), 1):
            # One String per LINE, not per word. Word-level Strings would each need four
            # coordinate attributes, and with no layout analysis all four would be the same
            # invented box -- 11x the file size to assert nothing. A line-level String says
            # exactly what is known: this text, in this order, somewhere in this region.
            out.append(f'<TextLine ID="P{page}_L{i}" HPOS="0" VPOS="0" WIDTH="{PAGE_W}" '
                       f'HEIGHT="{PAGE_H}">'
                       f'<String ID="P{page}_L{i}_S1" '
                       f'CONTENT="{escape(line, {chr(34): "&quot;"})}" '
                       f'HPOS="0" VPOS="0" WIDTH="{PAGE_W}" HEIGHT="{PAGE_H}"/>'
                       f'</TextLine>')
        out.append('</TextBlock></PrintSpace></Page>')
    out.append('</Layout></alto>')
    return "\n".join(out)


def hocr(book: str, rows: list, cat_mod, prov_mod) -> str:
    m = prov_mod.METHOD
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<!DOCTYPE html>',
           '<html xmlns="http://www.w3.org/1999/xhtml" lang="fa" dir="rtl"><head>',
           '<meta charset="utf-8"/>',
           f'<title>{escape(cat_mod.label(book))}</title>',
           '<meta name="ocr-system" content="' + escape(m["model"]) + '"/>',
           '<meta name="ocr-capabilities" content="ocr_page ocr_carea ocr_line ocrx_word"/>',
           f'<meta name="ocr-note" content="{escape(NOCOORD)}"/>',
           '</head><body>']
    for page, text in rows:
        out.append(f'<div class="ocr_page" id="page_{page}" '
                   f'title="bbox 0 0 {PAGE_W} {PAGE_H}; ppageno {page}">')
        out.append(f'<div class="ocr_carea" id="block_{page}_1" '
                   f'title="bbox 0 0 {PAGE_W} {PAGE_H}">')
        for i, line in enumerate(_lines(text), 1):
            out.append(f'<span class="ocr_line" id="line_{page}_{i}">{escape(line)}</span>')
        out.append('</div></div>')
    out.append('</body></html>')
    return "\n".join(out)


def tei(book: str, rows: list, cat_mod, prov_mod, img_base: str) -> str:
    """TEI P5 with a <facsimile> graph, which is the export a digital-humanities project
    actually wants: every <pb/> points at the image it was read from, so a reader can always
    get back to the source."""
    rec = cat_mod.book(book)
    parts = cat_mod.title_parts(book)
    m = prov_mod.METHOD
    lo, hi = cat_mod.dates(book)
    date = f"{lo}–{hi}" if lo and hi and lo != hi else (str(lo) if lo else "")

    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<TEI xmlns="http://www.tei-c.org/ns/1.0">',
           '<teiHeader><fileDesc><titleStmt>',
           f'<title xml:lang="fa">{escape(parts["original"] or cat_mod.label(book))}</title>']
    if parts["romanized"]:
        out.append(f'<title type="romanized">{escape(parts["romanized"])}</title>')
    if rec.get("author"):
        out.append(f'<author>{escape(rec["author"])}</author>')
    out.append('</titleStmt><publicationStmt>')
    out.append('<publisher>afghanpress.org</publisher>')
    out.append(f'<availability status="free"><licence '
               f'target="{cat_mod.TEXT_RIGHTS["uri"]}">'
               f'{escape(cat_mod.TEXT_RIGHTS["statement"])}</licence></availability>')
    out.append('</publicationStmt><sourceDesc><bibl>')
    if rec.get("publisher"):
        out.append(f'<publisher>{escape(rec["publisher"])}</publisher>')
    if date:
        out.append(f'<date>{escape(date)}</date>')
    if rec.get("handle"):
        out.append(f'<idno type="handle">{escape(rec["handle"])}</idno>')
    out.append(f'<idno type="adl">{escape(book)}</idno>')
    out.append(f'<note>{escape(cat_mod.IMAGE_RIGHTS["statement"])}</note>')
    out.append('</bibl></sourceDesc></fileDesc>')
    out.append('<encodingDesc><appInfo><application version="1" '
               f'ident="{escape(m["model"])}">'
               f'<label>{escape(m["model"])} at thinkingLevel {escape(m["thinking_level"])}'
               f'</label><desc>{escape(prov_mod.ACCURACY["headline"])} {escape(NOCOORD)}</desc>'
               '</application></appInfo></encodingDesc>')
    out.append(f'<profileDesc><langUsage><language ident="fa">Persian</language>'
               f'<language ident="ps">Pashto</language></langUsage></profileDesc>')
    out.append('</teiHeader>')

    out.append('<facsimile>')
    for page, _ in rows:
        out.append(f'<surface xml:id="f{page}" ulx="0" uly="0" lrx="{PAGE_W}" lry="{PAGE_H}">'
                   f'<graphic url="{img_base}/{book}/{page:05d}.jpg" '
                   f'width="{PAGE_W}px" height="{PAGE_H}px"/></surface>')
    out.append('</facsimile>')

    out.append('<text><body><div>')
    for page, text in rows:
        out.append(f'<pb n="{page}" facs="#f{page}"/>')
        for line in _lines(text):
            out.append(f'<l>{escape(line)}</l>')
    out.append('</div></body></text></TEI>')
    return "\n".join(out)


def plain(book: str, rows: list, cat_mod, prov_mod) -> str:
    head = [f"# {cat_mod.label(book)}", f"# {book}"]
    rec = cat_mod.book(book)
    if rec.get("publisher"):
        head.append(f"# {rec['publisher']}")
    head += [f"# Transcribed by {prov_mod.METHOD['model']}, "
             f"{prov_mod.CORPUS['read_completed']}.",
             f"# {prov_mod.ACCURACY['headline']}",
             f"# Text: CC0. Images: {cat_mod.IMAGE_RIGHTS['holder']}, public domain.", ""]
    for page, text in rows:
        head.append(f"\n--- page {page} ---\n")
        head.append(text or "")
    return "\n".join(head)
