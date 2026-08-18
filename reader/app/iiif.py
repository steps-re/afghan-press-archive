"""IIIF Presentation 3.0 and Content Search 2.0 over the corpus.

The reason this exists: a library that already has the page images does not want our files.
NYU serves these scans itself and plans to run its own OCR. What it cannot cheaply build is a
search index over 69,624 pages of nastaliq, and what IIIF lets us do is offer exactly that and
nothing else -- their viewer, their images, their branding, our search service behind it. A
Content Search endpoint is a pointer they can add in an afternoon and remove in a minute,
which is a far smaller ask than ingesting a third party's text layer.

Honest limitation, stated in the manifest itself rather than buried: the reader produced
page-level text with no word coordinates, so a search hit targets the whole canvas and cannot
highlight the word. That is a real reduction in what a viewer can show. Getting boxes needs a
layout pass aligned to the existing transcription, which has not been run.
"""
import os

BASE = os.environ.get("ADL_BASE_URL", "https://afghanpress.org")
IMG_BASE = os.environ.get("ADL_IMG_BASE", "https://storage.googleapis.com/adl-page-images")

# Verified uniform across a 25-page random sample spanning the corpus (2026-08-12). The scans
# are a single digitisation run at one setting, so a constant is honest here; if that ever
# stops being true the canvas dimensions are the thing that breaks.
PAGE_W, PAGE_H = 2550, 3301


def _img(book: str, page: int) -> str:
    return f"{IMG_BASE}/{book}/{page:05d}.jpg"


def canvas_id(book: str, page: int) -> str:
    return f"{BASE}/iiif/{book}/canvas/{page}"


def _lang_label(cat) -> dict:
    """IIIF labels are language maps. Giving the Persian title a `fa` key rather than dumping
    both scripts into one string is what lets a viewer pick the right font and direction."""
    out = {}
    if cat.get("romanized"):
        out["en"] = [cat["romanized"]]
    if cat.get("original"):
        out["fa"] = [cat["original"]]
    return out or {"none": ["Untitled"]}


def manifest(book: str, pages: list, cat_mod, prov_mod) -> dict:
    """One manifest per volume. `pages` is an ordered list of page numbers."""
    parts = cat_mod.title_parts(book)
    rec = cat_mod.book(book)
    lo, hi = cat_mod.dates(book)

    md = []
    import re as _re
    _arabic = _re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")

    def add(label, value):
        """IIIF language maps are not decoration: a viewer picks font and text direction from
        the tag, so labelling Persian as `none` renders Perso-Arabic in a Latin font, left to
        right, and hides it from assistive technology. `none` means "language does not apply"
        (an identifier, a number), not "we did not look".

        The ADL prints romanised and original script in one field ("Sirāj al-akhbār
        سراج الاخبار"), so tagging per VALUE is not enough -- a mixed string tagged `fa` sets
        the whole line right-to-left in an Arabic face. Split each value by script and let each
        run carry its own tag."""
        if not value:
            return
        vals = [str(v) for v in ([value] if isinstance(value, str) else list(value)) if v]
        en, fa = [], []
        for v in vals:
            if not _arabic.search(v):
                en.append(v)
                continue
            toks = v.split()
            a = " ".join(t for t in toks if _arabic.search(t)).strip()
            l = " ".join(t for t in toks if not _arabic.search(t)).strip()
            if a:
                fa.append(a)
            if l:
                en.append(l)
        lang = {}
        if en:
            lang["en"] = en
        if fa:
            lang["fa"] = fa
        md.append({"label": {"en": [label]}, "value": lang or {"none": vals}})

    add("Title", rec.get("title"))
    add("Other titles", rec.get("other_titles"))
    add("Author", rec.get("author"))
    add("Contributors", rec.get("contributors"))
    add("Published", rec.get("publisher"))
    add("Date", f"{lo}–{hi}" if lo and hi and lo != hi else (str(lo) if lo else None))
    add("Subjects", cat_mod.subjects(book))
    add("Physical description", rec.get("description_physical"))
    add("Identifier", rec.get("object_number") or book)
    add("Transcription", f"{prov_mod.METHOD['model']} at thinkingLevel "
                         f"{prov_mod.METHOD['thinking_level']}, completed "
                         f"{prov_mod.CORPUS['read_completed']}. "
                         f"{prov_mod.ACCURACY['headline']}")
    add("Text layer limitation", "Page-level text with no word coordinates. A search hit "
                                 "identifies the page, it cannot highlight the word.")

    items = []
    for p in pages:
        cid = canvas_id(book, p)
        items.append({
            "id": cid, "type": "Canvas", "height": PAGE_H, "width": PAGE_W,
            "label": {"none": [str(p)]},
            "items": [{
                "id": f"{cid}/page", "type": "AnnotationPage",
                "items": [{
                    "id": f"{cid}/page/image", "type": "Annotation", "motivation": "painting",
                    "body": {"id": _img(book, p), "type": "Image", "format": "image/jpeg",
                             "height": PAGE_H, "width": PAGE_W},
                    "target": cid,
                }],
            }],
            # The transcription rides along as a supplementing annotation page, which is how a
            # viewer offers "show transcript" without treating our text as the image itself.
            "annotations": [{
                "id": f"{cid}/text", "type": "AnnotationPage",
                # Referenced, not embedded: embedding 69,624 page texts would make some
                # manifests tens of megabytes and unusable in a browser.
            }],
        })

    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{BASE}/iiif/{book}/manifest",
        "type": "Manifest",
        "label": _lang_label(parts),
        "metadata": md,
        "summary": {"en": [f"{len(pages)} pages, machine-transcribed. Images from the "
                           f"Afghanistan Digital Library, New York University Libraries."]},
        "rights": cat_mod.IMAGE_RIGHTS["uri"],
        "requiredStatement": {
            "label": {"en": ["Attribution"]},
            "value": {"en": [
                "Page images: Afghanistan Digital Library, New York University Libraries "
                "(public domain), served here from a mirrored copy rather than from NYU. "
                "Transcription and search index: afghanpress.org, CC0. This is an independent "
                "project, not affiliated with or endorsed by New York University."]},
        },
        "provider": [{
            "id": "https://afghanpress.org",
            "type": "Agent",
            "label": {"en": ["Afghan Press Archive"]},
            "homepage": [{"id": BASE, "type": "Text", "label": {"en": ["afghanpress.org"]},
                          "format": "text/html"}],
        }],
        "homepage": [{"id": f"{BASE}/book/{book}", "type": "Text",
                      "label": {"en": [cat_mod.label(book)]}, "format": "text/html"}],
        "seeAlso": [
            {"id": f"{BASE}/api/download/book/{book}.jsonl", "type": "Dataset",
             "label": {"en": ["Transcription as JSONL"]}, "format": "application/x-ndjson"},
            {"id": f"{BASE}/api/export/{book}?format=alto", "type": "Dataset",
             "label": {"en": ["Transcription as ALTO XML"]}, "format": "text/xml"},
            {"id": f"{BASE}/oai?verb=GetRecord&metadataPrefix=oai_dc&identifier="
                   f"oai:afghanpress.org:{book}", "type": "Dataset",
             "label": {"en": ["Dublin Core record via OAI-PMH"]}, "format": "text/xml"},
        ] + ([{"id": rec["source_record"], "type": "Text",
               "label": {"en": ["Catalogue record at the Afghanistan Digital Library"]},
               "format": "text/html"}] if rec.get("source_record") else []),
        "service": [{
            "id": f"{BASE}/iiif/{book}/search",
            "type": "SearchService2",
            "profile": "http://iiif.io/api/search/2/level1.json",
        }],
        "partOf": [{"id": f"{BASE}/iiif/collection", "type": "Collection",
                    "label": {"en": ["Afghan Press Archive"]}}],
        "items": items,
    }


def collection(books: list, cat_mod) -> dict:
    """Top-level collection so a harvester can walk every volume from one URL."""
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{BASE}/iiif/collection",
        "type": "Collection",
        "label": {"en": ["Afghan Press Archive"]},
        "summary": {"en": ["Machine-transcribed text and search over the Afghanistan Digital "
                           "Library: Afghan books and periodicals printed 1873-1960s."]},
        "rights": cat_mod.IMAGE_RIGHTS["uri"],
        "requiredStatement": {
            "label": {"en": ["Attribution"]},
            "value": {"en": ["Page images: Afghanistan Digital Library, New York University "
                             "Libraries. Transcription: afghanpress.org, CC0."]},
        },
        "service": [{
            "id": f"{BASE}/iiif/search",
            "type": "SearchService2",
            "profile": "http://iiif.io/api/search/2/level1.json",
        }],
        "items": [{
            "id": f"{BASE}/iiif/{b}/manifest", "type": "Manifest",
            "label": _lang_label(cat_mod.title_parts(b)) ,
        } for b in books],
    }


def text_annotation_page(book: str, page: int, text: str) -> dict:
    """The AnnotationPage each canvas references for its transcription.

    The manifest points at this rather than embedding the text, so it has to resolve or the
    viewer's "show transcript" silently shows nothing. Page-level text with no coordinates, so
    the annotation targets the whole canvas, same as a search hit."""
    cid = canvas_id(book, page)
    return {
        "@context": "http://iiif.io/api/presentation/3/context.json",
        "id": f"{cid}/text",
        "type": "AnnotationPage",
        "items": [{
            "id": f"{cid}/text/anno",
            "type": "Annotation",
            "motivation": "supplementing",
            "body": {"type": "TextualBody", "format": "text/plain", "language": "fa",
                     "value": text or ""},
            "target": cid,
        }],
    }


def search_response(query: str, hits: list, book: str = None, snippets: dict = None) -> dict:
    """IIIF Content Search 2.0 response.

    `hits` is a list of (book, page). Each becomes an Annotation whose target is the canvas.
    Without word coordinates there is no fragment selector to add -- the honest target is the
    whole page, and `ignored` tells the client which of its parameters we could not honour."""
    snippets = snippets or {}
    base_search = f"{BASE}/iiif/{book}/search" if book else f"{BASE}/iiif/search"
    items = []
    for i, (b, p) in enumerate(hits):
        items.append({
            "id": f"{base_search}/anno/{b}/{p}",
            "type": "Annotation",
            "motivation": "supplementing",
            "body": {"type": "TextualBody", "format": "text/plain", "language": "fa",
                     "value": snippets.get((b, p), "")},
            "target": canvas_id(b, p),
        })
    return {
        "@context": "http://iiif.io/api/search/2/context.json",
        "id": f"{base_search}?q={query}",
        "type": "AnnotationPage",
        "ignored": ["motivation", "date", "user"],
        "partOf": {"id": base_search, "type": "AnnotationCollection",
                   "total": len(items)},
        "items": items,
    }
