"""Build a preservation and citation package for the corpus.

The question a librarian asks about a one-person website is what happens when the person stops
paying for it. The honest answer today is that the archive disappears, and that is a good
reason not to build on it. A checksummed BagIt package plus a deposit with a DOI changes the
answer: the text survives independently of the service, is citable by something more durable
than a hostname, and can be picked up by anyone.

Produces, into dist/:
  adl-corpus-<version>/            a BagIt bag (RFC 8493) of the text and metadata
  adl-corpus-<version>.zip         the same, packaged for deposit
  datacite.xml                     DataCite 4.4 metadata for minting the DOI
  CITATION.cff                     so GitHub and citation managers render it correctly

Depositing needs a human with an account, so this stops at the package. Nothing here talks to
Zenodo.
"""
import hashlib, json, os, sqlite3, sys, zipfile
from datetime import date

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "..", "data")
DIST = os.path.join(HERE, "..", "dist")
VERSION = os.environ.get("ADL_VERSION", "1.0.0")
AUTHOR = "German, Michael"
ORCID = os.environ.get("ADL_ORCID", "")
# Derived, not typed. The volume count was wrong (579) on every surface of this project until
# it was checked against the database, and a DOI is the one place a stale number cannot be
# quietly corrected later.
TITLE = None            # set in main() once provenance is imported


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def write_payload(bag: str, catalog: dict, prov) -> list:
    data = os.path.join(bag, "data")
    os.makedirs(data, exist_ok=True)
    db = sqlite3.connect(os.path.join(DATA, "corpus.db"))

    # One JSONL per volume rather than one giant file: a 126MB blob is hard to inspect, and
    # per-volume files let someone take the two periodicals they care about.
    texts = os.path.join(data, "text")
    os.makedirs(texts, exist_ok=True)
    books = [r[0] for r in db.execute("SELECT DISTINCT book FROM pages ORDER BY book")]
    for b in books:
        with open(os.path.join(texts, f"{b}.jsonl"), "w", encoding="utf-8") as f:
            for page, raw in db.execute(
                    "SELECT page, raw FROM pages WHERE book=? ORDER BY page", (b,)):
                f.write(json.dumps({"book": b, "page": page, "text": raw},
                                   ensure_ascii=False) + "\n")

    json.dump(catalog, open(os.path.join(data, "catalog.json"), "w"),
              ensure_ascii=False, indent=1)
    ent = os.path.join(DATA, "entities.json")
    if os.path.exists(ent):
        json.dump(json.load(open(ent)), open(os.path.join(data, "places.json"), "w"),
                  ensure_ascii=False, indent=1)
    json.dump({"corpus": prov.CORPUS, "method": prov.METHOD, "accuracy": prov.ACCURACY,
               "limits": prov.LIMITS},
              open(os.path.join(data, "provenance.json"), "w"), ensure_ascii=False, indent=1)

    readme = f"""{TITLE}
Version {VERSION}, {date.today().isoformat()}

WHAT THIS IS
{prov.CORPUS['pages']:,} pages from {prov.CORPUS['books']} volumes of Afghan books and
periodicals printed between 1871 and the 1930s, transcribed by machine in the original
Perso-Arabic script.

The page images are held by the Afghanistan Digital Library, New York University Libraries,
which states that the works it presents are in the public domain. This package contains only
the text layer and its metadata, not the images.

HOW IT WAS MADE
{prov.METHOD['model']} at thinkingLevel {prov.METHOD['thinking_level']}, one whole-page read
per page, on Google Vertex AI batch prediction. Read completed {prov.CORPUS['read_completed']}.

HOW GOOD IT IS
{prov.ACCURACY['headline']}

Measured: {prov.ACCURACY['primary_measurement']['cer_median']} median character error rate
against {prov.ACCURACY['primary_measurement']['reference']}, on
{prov.ACCURACY['primary_measurement']['sample']}.
{prov.ACCURACY['primary_measurement']['caveat']}

{prov.ACCURACY['no_human_gold']}

LIMITS
""" + "\n".join(f"- {l}" for l in prov.LIMITS) + f"""

CONTENTS
  text/<volume>.jsonl   one JSON object per page: book, page, text
  catalog.json          bibliographic record per volume, copied from the ADL catalogue
  places.json           place-name index built from GeoNames (CC-BY 4.0)
  provenance.json       the above, machine-readable

LICENCE
Text layer: CC0 1.0 Universal. No warranty of accuracy.
Bibliographic records are derived from the Afghanistan Digital Library's own catalogue.
Place data from GeoNames, CC-BY 4.0.
"""
    open(os.path.join(data, "README.txt"), "w", encoding="utf-8").write(readme)

    files = []
    for root, _, names in os.walk(data):
        for n in sorted(names):
            files.append(os.path.join(root, n))
    return files


def write_bag(bag: str, files: list):
    """BagIt 1.0 (RFC 8493). Tiny spec, and it is what a repository expects to receive."""
    payload_bytes = sum(os.path.getsize(f) for f in files)
    with open(os.path.join(bag, "manifest-sha256.txt"), "w") as m:
        for f in files:
            rel = os.path.relpath(f, bag).replace(os.sep, "/")
            m.write(f"{sha256(f)}  {rel}\n")
    open(os.path.join(bag, "bagit.txt"), "w").write(
        "BagIt-Version: 1.0\nTag-File-Character-Encoding: UTF-8\n")
    open(os.path.join(bag, "bag-info.txt"), "w", encoding="utf-8").write(
        f"Source-Organization: Steps Ventures\n"
        f"Bagging-Date: {date.today().isoformat()}\n"
        f"External-Description: {TITLE}\n"
        f"External-Identifier: afghanpress.org corpus {VERSION}\n"
        f"Payload-Oxum: {payload_bytes}.{len(files)}\n")
    # The tag manifest covers the tag files themselves, so a corrupted manifest is detectable.
    with open(os.path.join(bag, "tagmanifest-sha256.txt"), "w") as t:
        for name in ("bagit.txt", "bag-info.txt", "manifest-sha256.txt"):
            p = os.path.join(bag, name)
            t.write(f"{sha256(p)}  {name}\n")


def datacite(prov) -> str:
    orcid = (f'<nameIdentifier nameIdentifierScheme="ORCID" '
             f'schemeURI="https://orcid.org/">{ORCID}</nameIdentifier>') if ORCID else ""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<resource xmlns="http://datacite.org/schema/kernel-4"
          xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"
          xsi:schemaLocation="http://datacite.org/schema/kernel-4
          http://schema.datacite.org/meta/kernel-4.4/metadata.xsd">
  <identifier identifierType="DOI">10.0000/PENDING</identifier>
  <creators><creator><creatorName nameType="Personal">{AUTHOR}</creatorName>{orcid}
  </creator></creators>
  <titles><title xml:lang="en">{TITLE}</title></titles>
  <publisher>Zenodo</publisher>
  <publicationYear>{date.today().year}</publicationYear>
  <resourceType resourceTypeGeneral="Dataset">Machine-generated text corpus</resourceType>
  <subjects>
    <subject>Afghanistan</subject><subject>Persian</subject><subject>Pashto</subject>
    <subject>Handwritten text recognition</subject><subject>Nastaliq</subject>
    <subject>Lithography</subject><subject>Periodicals</subject>
    <subject>Digital humanities</subject>
  </subjects>
  <language>fas</language>
  <version>{VERSION}</version>
  <rightsList>
    <rights rightsURI="https://creativecommons.org/publicdomain/zero/1.0/"
            rightsIdentifier="cc0-1.0">Creative Commons Zero v1.0 Universal</rights>
  </rightsList>
  <descriptions>
    <description descriptionType="Abstract">{prov.CORPUS['pages']:,} pages from
      {prov.CORPUS['books']} volumes of Afghan print, 1871-1930s, machine-transcribed in the
      original Perso-Arabic script from page images held by the Afghanistan Digital Library,
      New York University Libraries. {prov.ACCURACY['headline']}</description>
    <description descriptionType="TechnicalInfo">{prov.METHOD['model']} at thinkingLevel
      {prov.METHOD['thinking_level']}, one whole-page read per page, Google Vertex AI batch
      prediction, completed {prov.CORPUS['read_completed']}. Measured median character error
      rate {prov.ACCURACY['primary_measurement']['cer_median']} against
      {prov.ACCURACY['primary_measurement']['reference']}.
      {prov.ACCURACY['primary_measurement']['caveat']}</description>
  </descriptions>
  <relatedIdentifiers>
    <relatedIdentifier relatedIdentifierType="URL" relationType="IsDerivedFrom"
      >https://afghanistandl.nyu.edu/</relatedIdentifier>
    <relatedIdentifier relatedIdentifierType="URL" relationType="IsDocumentedBy"
      >https://afghanpress.org/about.html</relatedIdentifier>
  </relatedIdentifiers>
</resource>
"""


def citation_cff(prov) -> str:
    return f"""cff-version: 1.2.0
message: If you use this corpus, please cite it.
title: >-
  {TITLE}
type: dataset
authors:
  - family-names: German
    given-names: Michael
{f"    orcid: https://orcid.org/{ORCID}" if ORCID else ""}
version: "{VERSION}"
date-released: "{date.today().isoformat()}"
license: CC0-1.0
url: "https://afghanpress.org"
abstract: >-
  {prov.CORPUS['pages']:,} pages from {prov.CORPUS['books']} volumes of Afghan print,
  1871-1930s, machine-transcribed in the original Perso-Arabic script. Page images are held
  by the Afghanistan Digital Library, New York University Libraries. The transcription is a
  finding aid, not an edition: {prov.ACCURACY['primary_measurement']['cer_median']} median
  character error rate against a modern printed edition of the same text.
keywords:
  - Afghanistan
  - Persian
  - Pashto
  - nastaliq
  - handwritten text recognition
  - digital humanities
"""


def main():
    global TITLE
    sys.path.insert(0, os.path.join(HERE, ".."))
    from app import provenance as prov
    TITLE = ("Machine-transcribed full text of the Afghanistan Digital Library: "
             f"{prov.CORPUS['books']} volumes of Afghan print, 1871-1930s")

    catalog = json.load(open(os.path.join(DATA, "catalog.json"), encoding="utf-8"))
    os.makedirs(DIST, exist_ok=True)
    bag = os.path.join(DIST, f"adl-corpus-{VERSION}")
    os.makedirs(bag, exist_ok=True)

    print("  writing payload", flush=True)
    files = write_payload(bag, catalog, prov)
    print(f"  {len(files)} files, hashing", flush=True)
    write_bag(bag, files)

    open(os.path.join(DIST, "datacite.xml"), "w", encoding="utf-8").write(datacite(prov))
    open(os.path.join(DIST, "CITATION.cff"), "w", encoding="utf-8").write(citation_cff(prov))

    zpath = os.path.join(DIST, f"adl-corpus-{VERSION}.zip")
    print("  zipping", flush=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for root, _, names in os.walk(bag):
            for n in sorted(names):
                p = os.path.join(root, n)
                z.write(p, os.path.relpath(p, DIST))
    mb = os.path.getsize(zpath) / 1e6
    print(f"done: {zpath} ({mb:.1f} MB), datacite.xml, CITATION.cff")
    print("Deposit needs a human: upload the zip to Zenodo with datacite.xml as the metadata.")


if __name__ == "__main__":
    main()
