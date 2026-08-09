"""The eval spine: build benchmarks and score models against them.

Two gold tiers:
  - SILVER (zero cash, available now): run 2+ independent-vendor backends on a page; where
    they AGREE above a threshold, the agreed text is a probable-correct label; where they
    DISAGREE, flag the page for a human. Cheap, and the disagreement set is exactly the
    human-annotation worklist. Caveat: agreement can be shared error, so silver is a weaker
    yardstick than human gold — use it to triage and to A/B changes, not to certify accuracy.
  - GOLD (small cash): human dual-draft + expert-adjudicate-disagreements. Same row schema
    as silver, so every downstream tool is tier-agnostic.

A gold/silver row: {"key","ref","tier","confidence"?,"sources"?}.
"""
import json
from . import metrics

def silver_gold(page_reads, agree=0.80):
    """page_reads: {key: {backend_name: text, ...}}. Returns (silver_rows, flagged).
    A page becomes silver if the two most-similar backends agree >= `agree`."""
    silver, flagged = [], []
    for key, reads in page_reads.items():
        items = [(b, t) for b, t in reads.items() if t and t.strip()]
        if len(items) < 2:
            flagged.append({"key": key, "reason": "insufficient_reads"}); continue
        best = None
        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                s = metrics.similarity(items[i][1], items[j][1])
                if s is not None and (best is None or s > best[0]):
                    best = (s, items[i], items[j])
        if best and best[0] >= agree:
            # label = the longer of the two agreeing reads (both are near-identical)
            label = max(best[1][1], best[2][1], key=len)
            silver.append({"key": key, "ref": label, "tier": "silver",
                           "confidence": best[0], "sources": [best[1][0], best[2][0]]})
        else:
            flagged.append({"key": key, "reason": "vendor_disagreement",
                            "max_sim": round(best[0], 3) if best else None})
    return silver, flagged

def evaluate(predictions, gold_rows, script="auto"):
    """predictions: {key: text}. gold_rows: list of {key, ref}. Returns per-key scores +
    aggregate CER/WER (mean & median)."""
    gold = {r["key"]: r["ref"] for r in gold_rows if r.get("ref")}
    rows, cers, wers = [], [], []
    for key, ref in gold.items():
        pred = predictions.get(key, "")
        sc = metrics.score(pred, ref, script)
        sc["key"] = key
        rows.append(sc)
        if isinstance(sc["cer"], float): cers.append(sc["cer"])
        if isinstance(sc["wer"], float): wers.append(sc["wer"])
    import statistics as st
    agg = {"n": len(rows),
           "cer_mean": round(st.mean(cers), 4) if cers else None,
           "cer_median": round(st.median(cers), 4) if cers else None,
           "wer_mean": round(st.mean(wers), 4) if wers else None,
           "degenerate": sum(1 for r in rows if r["degenerate"]),
           "truncated": sum(1 for r in rows if r["truncated"])}
    return {"aggregate": agg, "rows": rows}

def load_rows(path):
    return [json.loads(l) for l in open(path) if l.strip()]

def save_rows(rows, path):
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
