# htr-toolkit

A script-agnostic, layout-aware, multi-vendor HTR (handwritten/print text recognition)
platform. Built to generalize the one-off Afghan/Hyde/Euler transcription pipelines into a
reusable tool for **any** script or hand — Perso-Arabic lithographs, European cursive,
handwritten math, ledgers — where onboarding a new corpus is config + a small gold set, not
a new project.

Everything runs on **free credits**: Gemini (2.5 / 3.x) on Vertex/the credit grant, GPT-5.x on
Azure/Microsoft-for-Startups. No key is ever committed (Gemini uses the ambient gcloud/VM
identity; Azure key comes from `$AOAI_KEY` / `$AOAI_KEY_FILE`).


## Configuration

Nothing is hardcoded to any particular cloud account. Copy `.env.example`, set four values, and
every script and the web reader run against your own infrastructure:

```
export HTR_PROJECT=my-gcp-project      # serves the models
export HTR_BUCKET=gs://my-bucket       # artefacts in and out
export HTR_LOCATION=us-central1
export HTR_CONTACT=you@example.com     # sent in the User-Agent when fetching from a library
```

Optional: `HTR_TUNED_ENDPOINT` if you have tuned your own reader, and `HTR_AZURE_ENDPOINT`
plus `AOAI_KEY` for the cross-vendor comparison arm. Anything unset simply disables the
feature that needs it — `htr/config.py` raises with the exact variable to export rather than
letting a run fail halfway with someone else's project id in the URL.


## Layers

| Module | Role |
|---|---|
| `htr/pages.py` | Source I/O — fetch + render page images (ADL PDF today; add IIIF/local as adapters). |
| `htr/models.py` | **Model bank** — one interface over every reader (Gemini 2.5/3.x, GPT-5.x). 3.x auto-routes to the global endpoint. Add a backend = one line in `BACKENDS`. |
| `htr/layout.py` | **Layout-first** — detect reading-ordered regions, then transcribe each, then reassemble. Region-type-aware (see below). |
| `htr/metrics.py` | **Eval spine** — true Levenshtein CER/WER, script-aware normalization, degeneration/truncation flags. Not difflib. |
| `htr/gold.py` | **Benchmarks** — silver gold (cross-vendor agreement, zero cash) + human gold (same schema), and an eval runner. |

## Why these choices (all measured, 2026-07)

- **Multi-vendor, because the best reader is script-dependent.** On Afghan nastaliq, Gemini
  ≫ GPT-5.x (GPT fragments and spams illegibility markers); on Latin cursive the ranking may
  flip. Cross-vendor **disagreement is a free uncertainty signal** — where two vendors agree
  it's probably right; where they diverge, route to a human. Never use one model to grade
  itself (the old pipeline's circular Gemini-judges-Gemini trap).
- **Layout-first, because reading order is the #1 hidden error.** A page-level VLM reads
  fluently but mis-orders multi-column newspapers and interleaves headers/marginalia. Detect
  structure first so order is solved, not hoped.
- **Region-type-aware routing.** Cropping columns is right for **independent prose**
  (newspaper) but *wrong* for **paired verse** (masnavi — each row is one couplet across both
  columns; cropping scrambles it). `layout.transcribe_layout` crops **only** when the columns
  are independent prose; everything else reads whole-page. (Ambiguity defaults to whole-page:
  the harmful direction is cropping verse.)

## Status (prototype)

Proven live on credits (`demo_layout.py`):
- Model bank + 3.x global routing + metrics + gold harness all run end-to-end.
- Layout-first correctly **classifies and routes**: Anis newspaper → `independent_prose` →
  crops; Bustan masnavi → `paired_verse` → whole-page.
- Silver-gold correctly flags all Gemini-vs-GPT nastaliq pages for human review (they diverge
  too much to auto-certify) — the disagreement set *is* the annotation worklist.

**Layout-model finding (measured 2026-07):** off-the-shelf layout detectors do NOT transfer
to historical Perso-Arabic. DocLayout-YOLO labels a 1920s nastaliq newspaper's text block as
a `figure` (it was trained on modern English/Chinese docs); Surya's current build has a
llama.cpp grammar mismatch. So the toolkit keeps the **VLM as the layout engine** (it
understands the script) and stabilizes its run-to-run wobble with `layout.analyze_stable()`
(sample N times → majority-vote the verse/prose class → take a representative region set).
`htr/layout_model.py` is retained as the right tool for **modern** documents/hands.

Known next refinements (tune against the first gold set):
1. **A dedicated historical-layout model** would need fine-tuning on a small annotated set of
   historical pages (ties into the gold-set effort); until then, `analyze_stable` is the fix.
2. **Build the first human gold set** (~50 stratified pages, dual-typist + expert-adjudicate
   -disagreements) to certify accuracy and tune the crop/route thresholds.
3. Resolution bakeoff (200dpi vs 300–400dpi + crops) for dense pages.

## Run the demo

```bash
pip install -r requirements.txt
export GCLOUD_ACCOUNT=you@org           # or run on a VM with a default SA
export AOAI_KEY_FILE=/path/to/azure.key # optional, enables the GPT cross-vendor column
python3 demo_layout.py
```
