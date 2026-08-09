#!/usr/bin/env python3
"""First REAL newspaper benchmark. Aman-i Afghan issue 1 (rahparcham1.org, human-RETYPED,
not OCR): PDF has 8 scanned newspaper pages + one fully retyped page (newspaper p12). We
transcribe the scans with each backend, concatenate, and score via best-window CER against
the human-typed page — measuring how accurately the reader got the content a human transcribed
(robust to not knowing which scan == the retyped page). Dense multi-column nastaliq newspaper:
the hardest layout, finally on real human gold."""
import os, sys, base64, io
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htr import models, metrics
import pypdfium2 as pdfium

PDF = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "work/gold_sources/aman_afghan_i1_retyped.pdf")
BACKENDS = os.environ.get("HTR_BACKENDS", "gemini-2.5-pro,gemini-2.5-flash,gemini-3.1-pro,gemini-3.6-flash").split(",")
SYS = ("You are an expert transcriber of early Afghan newspaper print (Dari/Persian in "
       "nastaliq/naskh). Read right-to-left in correct reading order. Output ONLY the transcription.")
USER = "Transcribe this newspaper page faithfully in the original script. Output ONLY the transcription."

def best_window_cer(pred, ref):
    p, r = metrics.normalize(pred), metrics.normalize(ref)
    if len(r) < 40 or len(p) < 40:
        return None
    L = len(r)
    best, step = 9.0, max(1, L // 8)
    for i in range(0, max(1, len(p) - L), step):
        c = metrics._lev(p[i:i + int(L * 1.3)], r) / L
        best = min(best, c)
    return round(best, 4)

def main():
    pdf = pdfium.PdfDocument(PDF)
    ref = pdf[9].get_textpage().get_text_range()          # PDF page 10 = retyped newspaper page
    scans = []
    for p in range(1, 9):                                  # PDF pages 2-9 = scanned newspaper pages
        pil = pdf[p].render(scale=220 / 72).to_pil().convert("L")
        w, h = pil.size
        if max(w, h) > 2600:
            s = 2600 / max(w, h); pil = pil.resize((int(w * s), int(h * s)))
        buf = io.BytesIO(); pil.save(buf, "JPEG", quality=88)
        scans.append(base64.b64encode(buf.getvalue()).decode())
    pdf.close()
    print(f"Aman-i Afghan issue 1: {len(scans)} scan pages, human ref {len(ref)} chars", flush=True)
    print("=== newspaper reader CER (best-window vs human-typed page, lower=better) ===", flush=True)
    rows = []
    for b in BACKENDS:
        outs = []
        for b64 in scans:
            try:
                outs.append(models.transcribe(b, SYS, USER, b64,
                            **({} if b.startswith("gpt") else {"temperature": 0.1})) or "")
            except Exception as e:
                outs.append(""); print(f"  {b} page err: {str(e)[:80]}", flush=True)
        concat = "\n".join(outs)
        cer = best_window_cer(concat, ref)
        rows.append((b, cer, len(concat)))
        print(f"  {b:18s} CER={cer}  (transcribed {len(concat)} chars across {len(scans)} pages)", flush=True)
    rows.sort(key=lambda r: (r[1] is None, r[1] or 9))
    print("\nRANK:", " > ".join(f"{b}({c})" for b, c, _ in rows), flush=True)

if __name__ == "__main__":
    main()
