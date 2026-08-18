#!/usr/bin/env python3
"""Driver: benchmark the reader bank against human gold. Runs on the the credit grant VM (survives laptop
sleep); Gemini uses the VM default SA (bills donated cloud credits), GPT-5.x needs $AOAI_KEY.

Usage:
  python3 run_bench.py ocrgs   [N_per_text]   # OpenITI OCR_GS_Data/fas (Persian naskh lines)
  python3 run_bench.py makhzan [N_pages]      # OpenITI MAKHZAN Persian NASTALIQ pages
Env: HTR_BACKENDS (comma list), BENCH_WORKERS (default 2), BENCH_PACE (sec, default 0.5)
"""
import os, sys, glob, json, csv, base64, zipfile, urllib.request, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htr import bench

HERE = os.path.dirname(os.path.abspath(__file__))
GS = os.path.join(HERE, "work", "gold_sources")
DEFAULT_BACKENDS = ["gemini-2.5-pro", "gemini-3.7-flash", "gemini-3.1-pro", "gemini-3.7-flash", "gpt-5.6-sol"]
BACKENDS = os.environ.get("HTR_BACKENDS", "").split(",") if os.environ.get("HTR_BACKENDS") else DEFAULT_BACKENDS
BACKENDS = [b for b in BACKENDS if b]

def load_ocrgs(n_per_text=20, min_ref=15):
    rows = []
    for text_dir in sorted(glob.glob(os.path.join(GS, "OCR_GS_Data", "fas", "*"))):
        got = 0
        for gt in sorted(glob.glob(os.path.join(text_dir, "*.gt.txt"))):
            ref = open(gt, encoding="utf-8").read().strip()
            img = gt[:-7] + ".png"
            if len(ref) >= min_ref and os.path.exists(img):
                rows.append({"key": os.path.basename(gt)[:-7], "image_path": img, "ref": ref})
                got += 1
            if got >= n_per_text:
                break
    return rows

def load_makhzan(n_pages=40, min_ref=60):
    """MAKHZAN (downloaded+extracted as per-doc Doc<ID>.zip, each holding <DocID>_<PartID>.png
    + .xml ALTO). Keep Persian NASTALIQ pages; ref = concatenated ALTO CONTENT tokens; image
    read straight from the nested zip as base64."""
    base = os.path.join(GS, "makhzan")
    os.makedirs(base, exist_ok=True)
    root = os.path.join(base, "extracted")
    zpath = os.path.join(base, "makhzan.zip")
    if not glob.glob(os.path.join(root, "Doc*.zip")):   # first run: fetch + extract
        if not os.path.exists(zpath) or os.path.getsize(zpath) < 1_000_000:
            rec = json.load(urllib.request.urlopen("https://zenodo.org/api/records/19861912", timeout=60))
            zf = next(f for f in rec["files"] if f["key"].lower().endswith(".zip"))
            print(f"downloading MAKHZAN {zf['key']} ({zf['size']/1e9:.1f} GB)...", flush=True)
            urllib.request.urlretrieve(zf["links"]["self"], zpath)
        print("extracting...", flush=True)
        with zipfile.ZipFile(zpath) as z:
            z.extractall(root)
    meta = list(csv.DictReader(open(os.path.join(GS, "makhzan_metadata.tsv"), encoding="utf-8"), delimiter="\t"))
    want = [r for r in meta if "Persian" in r.get("Language", "") and r.get("Script") == "nastaliq"
            and r.get("Transcribed Lines Count", "0").isdigit() and int(r["Transcribed Lines Count"]) > 0]
    rows = []
    for r in want:
        doc = (r.get("Doc ID") or "").strip(); part = (r.get("Doc Part ID") or "").strip()
        zp = os.path.join(root, f"Doc{doc}.zip")
        if not (doc and part and os.path.exists(zp)):
            continue
        try:
            zf = zipfile.ZipFile(zp)
            names = zf.namelist()
            xml_name = (f"{doc}_{part}.xml" if f"{doc}_{part}.xml" in names
                        else next((n for n in names if part in n and n.endswith(".xml")), None))
            img_name = next((n for n in (f"{doc}_{part}.png", f"{doc}_{part}.jpg") if n in names),
                            next((n for n in names if part in n and n.lower().endswith((".png", ".jpg"))), None))
            if not xml_name or not img_name:
                continue
            alto = zf.read(xml_name).decode("utf-8", "ignore")
            ref = " ".join(re.findall(r'CONTENT="([^"]*)"', alto)).strip()
            if len(ref) < min_ref:
                continue
            rows.append({"key": f"{doc}_{part}", "ref": ref,
                         "image_b64": base64.b64encode(zf.read(img_name)).decode()})
        except Exception:
            continue
        if len(rows) >= n_pages:
            break
    return rows

def load_bustan(n_pages=40, min_ref=80):
    """The REAL target: actual ADL LITHOGRAPH nastaliq. Bustan (adl0294) pages aligned to the
    Ganjoor canon by the existing pipeline (gold_pages.jsonl). Renders each page from the ADL
    PDF and scores against the canonical human text. Closest thing to lithograph gold we have."""
    from htr import pages as P
    gp = os.environ.get("BUSTAN_GOLD", os.path.expanduser("~/mss301work/afghan/gold_pages.jsonl"))
    seen, out = set(), []
    for ln in open(gp):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        key = (r.get("book"), r.get("page"))
        if not r.get("gold") or key in seen or len(r["gold"]) < min_ref:
            continue
        seen.add(key)
        try:
            pdf = P.adl_pdf(r["book"], os.path.join(GS, "bustan_pdf"))
            _, b64 = P.render(pdf, r["page"])
        except Exception:
            continue
        out.append({"key": f"{r['book']}_{r['page']}", "image_b64": b64, "ref": r["gold"]})
        if len(out) >= n_pages:
            break
    return out

def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "ocrgs"
    n = int(sys.argv[2]) if len(sys.argv) > 2 else (20 if which == "ocrgs" else 40)
    rows = {"ocrgs": load_ocrgs, "makhzan": load_makhzan, "bustan": load_bustan}[which](n)
    print(f"[{which}] gold rows: {len(rows)} | backends: {BACKENDS}", flush=True)
    out = os.path.join(HERE, "work", f"bench_{which}.jsonl")
    table = bench.run(rows, BACKENDS, out,
                      workers=int(os.environ.get("BENCH_WORKERS", "2")),
                      pace=float(os.environ.get("BENCH_PACE", "0.5")))
    summary = {"gold": which, "n_rows": len(rows), "backends": BACKENDS, "table": table}
    json.dump(summary, open(os.path.join(HERE, "work", f"bench_{which}_summary.json"), "w"),
              ensure_ascii=False, indent=1)
    print("\n=== RESULT (" + which + ", CER lower=better) ===", flush=True)
    for b, s in sorted(table.items(), key=lambda kv: (kv[1]["cer_mean"] is None, kv[1]["cer_mean"] or 9)):
        print(f"  {b:18s} n={s['n']:3d} cer_mean={s['cer_mean']} cer_med={s['cer_median']} "
              f"wer={s['wer_mean']} degen={s['degenerate']} err={s['errors']}", flush=True)

if __name__ == "__main__":
    main()
