"""Layout-first transcription — the biggest quality lever for complex pages.

A page-level VLM read can be linguistically fluent while being STRUCTURALLY wrong: it
reads multi-column newspapers in the wrong order, interleaves columns, or folds headers
and marginalia into the body. The review + the live probe both flagged this as the top
hidden error. Fix: detect reading-ordered regions FIRST, transcribe each region alone,
then reassemble deterministically — so reading order is a solved sub-problem, not a hope.

Stage 1 (layout) and Stage 2 (recognition) can use different backends from the model bank.
For simple single-column pages this collapses to a whole-page read (1 region), so it's
safe to run everywhere; it only changes behavior where structure actually exists.
"""
import base64, io, json, re
from . import models

SYS_LAYOUT = ("You are a document-layout analyst for historical printed and manuscript pages "
              "(often multi-column, right-to-left Perso-Arabic, with headers/marginalia).")
PROMPT_LAYOUT = """Analyze this page's LAYOUT ONLY. Do NOT transcribe the text.

CRITICAL BINARY — look at the LINES inside any columns:
- "paired_verse": the columns hold SHORT, regular half-lines that pair ACROSS the columns
  (classical masnavi/ghazal poetry — each row = one couplet: right half + left half). These
  MUST be read row-by-row; splitting the columns would scramble the poem. Short centered
  text block, lots of white space, every line roughly the same short length.
- "independent_prose": the columns hold LONG prose lines that fill each column's width and
  continue down one full column before the next (newspaper/journal article). Read column by
  column, right column fully before the left (RTL).
- "none": no side-by-side columns (single block).

Then list the text regions in correct HUMAN READING ORDER (RTL: right before left; headers
and boxed titles before the body they head).
Reply ONLY compact JSON:
{"columns_are":"paired_verse|independent_prose|none","regions":[{"order":1,"type":"column|header|body|marginalia|footnote","box":[ymin,xmin,ymax,xmax]}]}
box coords are integers 0-1000 (top-left origin). At most 20 regions."""

SYS_READ = ("You are an expert transcriber of historical text. Transcribe faithfully in the "
            "original script, right-to-left where applicable. Output ONLY the transcription.")
PROMPT_READ = ("Transcribe this text region faithfully. Preserve original spelling and script. "
               "If the region is blank or a plate with no text, output exactly [BLANK PAGE]. "
               "Output ONLY the transcription, no commentary.")

def analyze(image_b64, backend="gemini-2.5-pro"):
    """Return (columns_are, regions). columns_are drives whether we crop or read whole-page:
    'independent_prose' -> crop; 'paired_verse'/'none' -> whole-page (cropping would scramble)."""
    out = models.transcribe(backend, SYS_LAYOUT, PROMPT_LAYOUT, image_b64, max_tokens=4096) or ""
    m = re.search(r"\{.*\}", out, re.S)
    if not m:
        return "none", []
    try:
        d = json.loads(m.group(0))
    except Exception:
        return "none", []
    regs = [r for r in d.get("regions", []) if isinstance(r.get("box"), list) and len(r["box"]) == 4]
    return d.get("columns_are", "none"), sorted(regs, key=lambda r: r.get("order", 999))[:20]

def analyze_stable(image_b64, backend="gemini-2.5-pro", n=3):
    """Wobble-resistant layout via the VLM. Measured finding (2026-07): off-the-shelf layout
    CNNs do NOT transfer to historical Perso-Arabic — DocLayout-YOLO reads a 1920s nastaliq
    newspaper as a 'figure', and Surya's current build has a llama.cpp grammar mismatch. The
    VLM understands the script, so it's the right layout engine here; its only weakness is that
    box counts vary run-to-run. Fix: sample analyze() n times, MAJORITY-VOTE the verse/prose
    class (the routing-critical decision), and take the median-region-count set of that class."""
    from collections import Counter
    runs = [analyze(image_b64, backend) for _ in range(n)]
    cls = Counter(c for c, _ in runs).most_common(1)[0][0]
    same = sorted((regs for c, regs in runs if c == cls), key=len)
    return cls, same[len(same) // 2]

def _crop_b64(pil, box, pad=0.015):
    """box = [ymin,xmin,ymax,xmax] in 0-1000. Generous padding: nastaliq dots/ascenders
    cross nominal region edges, so tight crops lose strokes."""
    W, H = pil.size
    ymin, xmin, ymax, xmax = box
    x0 = max(0, int((min(xmin, xmax) / 1000 - pad) * W))
    y0 = max(0, int((min(ymin, ymax) / 1000 - pad) * H))
    x1 = min(W, int((max(xmin, xmax) / 1000 + pad) * W))
    y1 = min(H, int((max(ymin, ymax) / 1000 + pad) * H))
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    crop = pil.crop((x0, y0, x1, y1))
    buf = io.BytesIO(); crop.convert("L").save(buf, "JPEG", quality=90)
    return base64.b64encode(buf.getvalue()).decode()

def transcribe_layout(pil, image_b64, read_backend="gemini-2.5-pro",
                      layout_backend="gemini-2.5-pro", region_source="vlm", stable=True):
    """Region-type-aware layout-first pass. Returns (text, columns_are, n_regions).
    Crops regions ONLY when the columns are INDEPENDENT PROSE; paired-verse and single-block
    pages are read whole-page (cropping paired verse scrambles couplets — measured on Bustan
    p60). This whitelist ('crop only if we're sure it's prose columns') is deliberately safe:
    the harmful direction is cropping verse, so ambiguity defaults to whole-page.

    region_source: 'vlm' uses the (variable) VLM boxes; 'model' uses the dedicated layout
    model (DocLayout-YOLO) for STABLE, deterministic region geometry — the VLM still makes
    the verse/prose call."""
    columns_are, regs = (analyze_stable(image_b64, layout_backend) if stable
                         else analyze(image_b64, layout_backend))
    if columns_are == "independent_prose" and region_source == "model":
        # NB DocLayout-YOLO does not transfer to historical Perso-Arabic (reads it as figures);
        # only use region_source='model' on modern documents / hands, not lithographs.
        from . import layout_model
        regs = layout_model.detect_regions(pil) or regs
    if columns_are != "independent_prose" or len(regs) <= 1:
        return whole_page(image_b64, read_backend), columns_are, len(regs)
    parts = []
    for r in regs:
        cb = _crop_b64(pil, r["box"])
        if not cb:
            continue
        txt = models.transcribe(read_backend, SYS_READ, PROMPT_READ, cb, max_tokens=8192)
        if txt and txt.strip() and txt.strip() != "[BLANK PAGE]":
            parts.append(txt.strip())
    return "\n\n".join(parts), columns_are, len(regs)

def whole_page(image_b64, backend="gemini-2.5-pro"):
    return models.transcribe(backend, SYS_READ, PROMPT_READ, image_b64, max_tokens=16384)
