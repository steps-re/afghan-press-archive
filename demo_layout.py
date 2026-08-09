#!/usr/bin/env python3
"""Phase-2 proof: does layout-first change/repair the read on pages where structure matters?

Runs, per page: whole-page (Gemini) vs layout-first (Gemini layout -> region crops -> Gemini
read -> reassemble), plus a whole-page GPT-5.x read for the cross-vendor signal. Reports region
count + structural stats. On a dense multi-column NEWSPAPER we expect layout-first to find
several regions and reorder the read; on single-column POETRY we expect ~1 region (no change),
which is the correct, safe behavior.

Runs on free credits. Small by design (2 pages) — pacing per the credit guardrails.
Env: AOAI_KEY_FILE (Azure key path) to enable the GPT column.
"""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from htr import pages, layout, models, metrics

WORK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "work")
CASES = [
    ("adl0789", 200, "newspaper (Anis — dense 2-column + header; layout-first should CROP)"),
    ("adl0294", 60, "poetry (Bustan — paired verse; layout-first should NO-OP to whole-page)"),
]

def main():
    have_gpt = bool(os.environ.get("AOAI_KEY") or os.environ.get("AOAI_KEY_FILE"))
    results = []
    for book, page, desc in CASES:
        print(f"\n=== {book} p{page} — {desc} ===", flush=True)
        pdf = pages.adl_pdf(book, WORK)
        pil, b64 = pages.render(pdf, page)
        lf, ptype, nreg = layout.transcribe_layout(pil, b64, "gemini-2.5-pro", "gemini-2.5-pro")
        # when layout routed to whole-page, reuse that read as the whole-page baseline so the
        # comparison reflects the LAYOUT decision, not two independent nondeterministic samples
        wp = lf if ptype != "independent_prose" else (layout.whole_page(b64, "gemini-2.5-pro") or "")
        rec = {"book": book, "page": page, "page_type": ptype, "regions": nreg,
               "whole_page": metrics.line_stats(wp),
               "layout_first": metrics.line_stats(lf),
               "wp_vs_lf_sim": metrics.similarity(wp, lf)}
        print(f"  page_type: {ptype} | regions: {nreg}")
        print(f"  whole-page : {rec['whole_page']}")
        print(f"  layout1st  : {rec['layout_first']}")
        print(f"  whole vs layout similarity: {rec['wp_vs_lf_sim']}  (low on newspaper => reading order changed)")
        if have_gpt:
            try:
                gp = models.transcribe("gpt-5.6-sol", layout.SYS_READ, layout.PROMPT_READ, b64) or ""
                rec["xvendor_gpt_vs_gemini_wp"] = metrics.similarity(gp, wp)
                print(f"  cross-vendor (gpt vs gemini whole-page) sim: {rec['xvendor_gpt_vs_gemini_wp']}")
            except Exception as e:
                print(f"  gpt skipped: {str(e)[:100]}")
        results.append(rec)
        # keep the actual texts for eyeballing
        open(os.path.join(WORK, f"{book}_{page}_wp.txt"), "w").write(wp)
        open(os.path.join(WORK, f"{book}_{page}_lf.txt"), "w").write(lf)
    json.dump(results, open(os.path.join(WORK, "demo_layout.json"), "w"), ensure_ascii=False, indent=1)
    print(f"\nsaved -> {WORK}/demo_layout.json (+ per-page _wp/_lf .txt for eyeballing)")

if __name__ == "__main__":
    main()
