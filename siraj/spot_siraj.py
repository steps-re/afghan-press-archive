#!/usr/bin/env python3
"""Spot-check scattered adl0616 pages. A run of [BLANK PAGE] near the front could be
genuine scan padding OR the reader bailing; only mid-book pages distinguish the two."""
import os, sys, json
sys.path.insert(0, os.path.expanduser("~/siraj"))
os.environ.setdefault("AFGHAN_DPI", "300")
os.environ.setdefault("AFGHAN_MAXPX", "3500")
os.environ.setdefault("AFGHAN_JPEGQ", "92")
import afghan_run as A
import pypdfium2 as pdfium

pdf_path = A.dl_pdf("adl0616")
pdf = pdfium.PdfDocument(pdf_path)
print("pages:", len(pdf))
for i in (40, 200, 700, 1200, 1700):
    img = A.render_page(pdf, i, "adl0616")
    px = os.path.getsize(img)
    txt = A.transcribe_page(img) or "<<NONE>>"
    print("=" * 70)
    print(f"page {i} | jpeg {px/1024:.0f}KB | chars {len(txt)}")
    print(txt[:600])
pdf.close()
