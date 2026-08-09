"""Page I/O — fetch and render source images. Currently supports the ADL static PDF
server (afghanistandl.nyu.edu); add other sources (IIIF, local dirs) here as one-function
adapters so the rest of the toolkit stays source-agnostic."""
import base64, io, os, urllib.request
import pypdfium2 as pdfium

UA = {"User-Agent": "Mozilla/5.0 research"}

def adl_pdf(book, work_dir):
    os.makedirs(work_dir, exist_ok=True)
    p = os.path.join(work_dir, f"{book}.pdf")
    if os.path.exists(p) and os.path.getsize(p) > 10000:
        return p
    url = f"https://afghanistandl.nyu.edu/pdf/{book}_download.pdf"
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=300) as r, open(p, "wb") as o:
        o.write(r.read())
    return p

def render(pdf_path, page, dpi=200, max_side=2500):
    """Return (PIL grayscale image, base64 jpeg). Higher dpi/max_side => more detail for
    dense pages (a lever the review flagged); defaults match the current pipeline."""
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        pil = pdf[page - 1].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        pdf.close()
    w, h = pil.size
    if max(w, h) > max_side:
        s = max_side / max(w, h)
        pil = pil.resize((int(w * s), int(h * s)))
    buf = io.BytesIO(); pil.save(buf, "JPEG", quality=90)
    return pil, base64.b64encode(buf.getvalue()).decode()
