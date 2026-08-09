#!/usr/bin/env python3
"""Rebuild the ADL catalogue from NYU, authoritatively.

The original `adl_catalog_full.tsv` (581 rows) was lost with the machine it lived on. Rather
than hunt for a copy, regenerate it from the source of truth: NYU serves an open Apache
directory index at /books/ that lists every volume.

Politeness / permission notes:
  - robots.txt disallows only /files/nyupress/pdfs/*.pdf. Neither /books/ nor /pdf/ is
    disallowed, and we only ever issue HEAD against the PDFs here.
  - Requests are paced and carry a contact address in the User-Agent.

Page counts are deliberately NOT scraped. The site's search is a JS-rendered Solr front end
with no JSON output, and the corpus runner opens each PDF anyway, so the authoritative page
count is `len(PdfDocument(pdf))` at render time. What this file provides is the BOOK LIST plus
a size-based page ESTIMATE, which is all that is needed to plan and cost a run.
"""
import json, os, sys, time, urllib.request, re

BASE = "https://afghanistandl.nyu.edu"
UA = "Mozilla/5.0 (research; " + os.environ.get("HTR_CONTACT", "set HTR_CONTACT") + ")"
# anchor: adl0616 is 148,590,177 bytes for 1,787 pages -> ~83 KB/page. Density varies by
# volume, so treat the derived page count as an ESTIMATE for planning, never as truth.
BYTES_PER_PAGE = 148_590_177 / 1787

def get(url, method="GET", timeout=60):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=timeout)

def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "adl_catalog.tsv"
    with get(f"{BASE}/books/") as r:
        html = r.read().decode("utf-8", errors="replace")
    books = sorted(set(re.findall(r'href="(adl\d+)/"', html)))
    print(f"[cat] {len(books)} volumes listed at {BASE}/books/", flush=True)

    rows, missing = [], []
    for i, b in enumerate(books):
        try:
            with get(f"{BASE}/pdf/{b}_download.pdf", method="HEAD", timeout=30) as r:
                rows.append((b, int(r.headers.get("Content-Length") or 0)))
        except Exception as e:
            missing.append((b, str(e)[:80]))
        if i % 100 == 99:
            print(f"[cat] {i+1}/{len(books)}", flush=True)
        time.sleep(0.12)

    total = sum(n for _, n in rows)
    print(f"[cat] reachable {len(rows)}/{len(books)}, missing {len(missing)}")
    for b, e in missing:
        print(f"[cat]   MISSING {b}: {e}")
    print(f"[cat] {total/1e9:.1f} GB of PDFs, ~{total/BYTES_PER_PAGE:,.0f} pages estimated")

    with open(out, "w") as f:
        f.write("book\tpdf_bytes\test_pages\n")
        for b, n in rows:
            f.write(f"{b}\t{n}\t{round(n/BYTES_PER_PAGE)}\n")
    json.dump({"books": len(books), "reachable": len(rows),
               "missing": [b for b, _ in missing], "pdf_bytes": total,
               "est_pages": round(total / BYTES_PER_PAGE)},
              open(os.path.splitext(out)[0] + "_summary.json", "w"), indent=2)
    print(f"[cat] wrote {out}")

if __name__ == "__main__":
    main()
