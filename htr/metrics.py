"""Honest HTR metrics — the eval spine.

The old pipeline scored quality with difflib's block ratio, which flatters and hides
single-char / name / number errors. Here we report true edit-distance CER/WER plus the
structural signals the cross-vendor review said matter most (omission, duplication,
degeneration), and a script-aware normalizer so orthographic noise doesn't dominate.
"""
import re, unicodedata
from collections import Counter

# Perso-Arabic normalization: unify letter variants, drop harakat/tatweel. For Latin/other
# scripts these substitutions are no-ops, so the same normalizer is safe cross-script.
_HARAKAT = "ًٌٍَُِّْـ"
def normalize(t, script="auto"):
    t = unicodedata.normalize("NFKC", t or "")
    for ch in _HARAKAT:
        t = t.replace(ch, "")
    t = (t.replace("ي", "ی").replace("ك", "ک").replace("ۀ", "ه")
           .replace("أ", "ا").replace("إ", "ا").replace("آ", "ا"))
    return re.sub(r"\s+", " ", t).strip()

def _lev(a, b):
    try:
        from rapidfuzz.distance import Levenshtein
        return Levenshtein.distance(a, b)
    except Exception:
        if a == b:
            return 0
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, 1):
            cur = [i]
            for j, cb in enumerate(b, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
            prev = cur
        return prev[-1]

def cer(pred, ref, script="auto"):
    """Character error rate = edit_distance(pred, ref) / len(ref). 0 = perfect."""
    p, r = normalize(pred, script), normalize(ref, script)
    if not r:
        return None
    return round(_lev(p[:8000], r[:8000]) / len(r[:8000]), 4)

def wer(pred, ref, script="auto"):
    p, r = normalize(pred, script).split(), normalize(ref, script).split()
    if not r:
        return None
    return round(_lev(p, r) / len(r), 4)

def similarity(a, b, script="auto"):
    """Symmetric normalized-edit similarity (1 - CER-style), for cross-model agreement."""
    p, r = normalize(a, script), normalize(b, script)
    if not p or not r:
        return None
    d = _lev(p[:8000], r[:8000])
    return round(1 - d / max(len(p[:8000]), len(r[:8000])), 4)

def degeneration(text, min_len=6):
    """Looping / illegibility-spam signal: any substantial line repeated 4+ times, or
    >30% duplicate lines. Mirrors the pipeline guard so the tool and the runner agree."""
    lines = [l.strip() for l in (text or "").splitlines() if len(l.strip()) >= min_len]
    if len(lines) < 4:
        return False
    c = Counter(lines)
    return max(c.values()) >= 4 or (len(lines) - len(c)) / len(lines) > 0.30

def line_stats(text):
    lines = [l for l in (text or "").splitlines() if l.strip()]
    return {"chars": len(text or ""), "lines": len(lines),
            "degenerate": degeneration(text),
            "truncated": "[TRUNCATED" in (text or "") or "[INCOMPLETE" in (text or "")}

def score(pred, ref, script="auto"):
    """Full per-page score dict against a reference."""
    return {"cer": cer(pred, ref, script), "wer": wer(pred, ref, script),
            **line_stats(pred)}
