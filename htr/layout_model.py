"""Dedicated layout model (DocLayout-YOLO) — deterministic region detection for MODERN
documents and hands.

IMPORTANT measured caveat (2026-07): this off-the-shelf model does NOT transfer to historical
Perso-Arabic lithographs. On a 1920s Anis newspaper page it labels the dense nastaliq text
block as 'figure' (conf 0.41) and only finds 'plain text' at 0.05-0.07 (noise) — it was
trained on modern English/Chinese docs and doesn't recognize the historical script as text.
For those corpora use the VLM layout with layout.analyze_stable() (the VLM understands the
script); to get a reliable dedicated detector for historical pages, fine-tune one on a small
annotated set (ties into the gold-set effort). Kept here as the right tool for modern material
(the "other scripts / handwriting" corpora), deterministic and free on CPU/VM.

Returns regions in the toolkit convention: {order, type, box:[ymin,xmin,ymax,xmax]} 0-1000.
"""
_model = {"m": None}
_REPO = "juliozhao/DocLayout-YOLO-DocStructBench"
_WEIGHTS = "doclayout_yolo_docstructbench_imgsz1024.pt"
# DocStructBench classes we treat as transcribable text (skip figure/table/abandon).
_TEXT_CLASSES = {"title", "plain text", "figure_caption", "table_caption",
                 "table_footnote", "formula_caption"}

def _get_model():
    if _model["m"] is None:
        from doclayout_yolo import YOLOv10
        from huggingface_hub import hf_hub_download
        _model["m"] = YOLOv10(hf_hub_download(_REPO, _WEIGHTS))
    return _model["m"]

def _reading_order(boxes, rtl=True, col_tol=0.12):
    """Sort boxes into human reading order. Cluster into columns by x-center (columns are
    the dominant structure in newspapers/journals), order columns right->left for RTL, then
    top->bottom within each column. boxes: list of (xc, yc, region_dict)."""
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda b: b[0])  # by x-center
    cols, cur, anchor = [], [], boxes[0][0]
    for xc, yc, r in boxes:
        if abs(xc - anchor) <= col_tol:
            cur.append((xc, yc, r))
        else:
            cols.append(cur); cur = [(xc, yc, r)]; anchor = xc
    if cur:
        cols.append(cur)
    if rtl:
        cols = cols[::-1]  # rightmost column first
    ordered = []
    for col in cols:
        for _, _, r in sorted(col, key=lambda b: b[1]):  # top->bottom
            ordered.append(r)
    return ordered

def detect_regions(pil, rtl=True, conf=0.2, device="cpu"):
    """Deterministic reading-ordered text regions for a PIL image."""
    model = _get_model()
    res = model.predict(pil.convert("RGB"), imgsz=1024, conf=conf, device=device, verbose=False)[0]
    W, H = pil.size
    names = res.names
    cand = []
    for b in res.boxes:
        cls = names[int(b.cls[0])]
        if cls not in _TEXT_CLASSES:
            continue
        x1, y1, x2, y2 = [float(v) for v in b.xyxy[0]]
        box = [int(y1 / H * 1000), int(x1 / W * 1000), int(y2 / H * 1000), int(x2 / W * 1000)]
        cand.append(((x1 + x2) / 2 / W, (y1 + y2) / 2 / H, {"type": cls, "box": box}))
    ordered = _reading_order(cand, rtl=rtl)
    for i, r in enumerate(ordered, 1):
        r["order"] = i
    return ordered
