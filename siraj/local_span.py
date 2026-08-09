#!/usr/bin/env python3
"""Phase C3: measure CER only over the genuinely parallel span of a confirmed pair.

A Siraj page carries material the edition never reprints: masthead, subscription prices,
the issue's table of contents, adverts, and the other columns that ran beside Tarzi's
article. Scoring the whole page against the whole window therefore charges the reader for
text that has no counterpart, which is why confirmed-correct pairs still showed CER ~0.50.

So: locate the parallel region first (SequenceMatcher over TOKENS, used only to FIND the
region), then score that region with true character Levenshtein. difflib never produces the
reported number -- it only proposes where to measure.
"""
import json, os, re, subprocess, unicodedata
from difflib import SequenceMatcher

IN = os.path.expanduser(os.environ.get("SPAN_IN", "~/siraj_gold/adjudicated.jsonl"))
OUT = os.path.expanduser(os.environ.get("SPAN_OUT", "~/siraj_gold/gold_pairs.jsonl"))
GCS = os.environ.get("SPAN_GCS", os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/")
MIN_CONF = float(os.environ.get("SPAN_MIN_CONF", "0.7"))
MIN_SPAN_TOKENS = int(os.environ.get("SPAN_MIN_TOKENS", "60"))

HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
TAG = re.compile(r"^\s*\[[^\]]{0,40}\]\s*")
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE)\]")

def norm(t):
    t = MARK.sub(" ", TAG.sub("", t or ""))
    t = re.sub(r"\[([^\]]*)\؟?\]", r"\1", t)
    t = unicodedata.normalize("NFKC", t).translate(MAP).translate(HARAKAT).translate(DROP)
    t = re.sub(r"[۰-۹٠-٩\d]+", " 0 ", t)
    return [w for w in t.split() if w]

def _lev_py(a, b):
    if a == b: return 0
    if not a: return len(b)
    if not b: return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]

try:
    from rapidfuzz.distance import Levenshtein as _RF
    levenshtein = _RF.distance          # same metric, C speed
except ImportError:
    levenshtein = _lev_py

def parallel_span(aw, bw):
    """Token indices (a0,a1,b0,b1) of the region the two texts actually share."""
    sm = SequenceMatcher(None, aw, bw, autojunk=False)
    blocks = [bl for bl in sm.get_matching_blocks() if bl.size >= 2]
    if not blocks:
        return None
    a0 = min(bl.a for bl in blocks); a1 = max(bl.a + bl.size for bl in blocks)
    b0 = min(bl.b for bl in blocks); b1 = max(bl.b + bl.size for bl in blocks)
    return a0, a1, b0, b1

def main():
    rows = [json.loads(l) for l in open(IN, encoding="utf-8")]
    # the adjudicated records carry verdicts and metadata only, so rejoin the texts by page
    src = os.path.expanduser(os.environ.get("SPAN_TEXTS", "~/siraj_gold/alignment.jsonl"))
    texts = {}
    if os.path.exists(src):
        for l in open(src, encoding="utf-8"):
            a = json.loads(l)
            if a.get("siraj_text"):
                texts[a["page"]] = (a["siraj_text"], a["edition_text"])
    for r in rows:
        if not r.get("siraj_text") and r["page"] in texts:
            r["siraj_text"], r["edition_text"] = texts[r["page"]]
    keep = [r for r in rows if r["judge"].get("verdict") == "same"
            and r["judge"].get("confidence", 0) >= MIN_CONF and r.get("siraj_text")]
    print(f"[span] {len(keep)} judge-confirmed pairs of {len(rows)}", flush=True)

    out = []
    for r in keep:
        aw, bw = norm(r.get("siraj_text", "")), norm(r.get("edition_text", ""))
        sp = parallel_span(aw, bw)
        if not sp:
            continue
        a0, a1, b0, b1 = sp
        sa, sb = aw[a0:a1], bw[b0:b1]
        if min(len(sa), len(sb)) < MIN_SPAN_TOKENS:
            continue
        A, B = " ".join(sa), " ".join(sb)
        cer = levenshtein(A, B) / max(len(A), len(B))
        out.append({**{k: r[k] for k in ("book", "page", "tarzi_pages") if k in r},
                    "judge_conf": r["judge"].get("confidence"),
                    "cer_wholepage": r.get("cer_vs_edition"),
                    "cer_parallel_span": round(cer, 4),
                    "span_tokens": len(sa), "page_tokens": len(aw),
                    "span_coverage": round(len(sa) / max(1, len(aw)), 3),
                    "siraj_span": A, "edition_span": B})

    out.sort(key=lambda r: r["cer_parallel_span"])
    with open(OUT, "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    cers = sorted(r["cer_parallel_span"] for r in out)
    whole = sorted(r["cer_wholepage"] for r in out if r.get("cer_wholepage") is not None)
    print(json.dumps({
        "gold_pairs": len(out),
        "cer_parallel_median": cers[len(cers) // 2] if cers else None,
        "cer_parallel_p25": cers[len(cers) // 4] if cers else None,
        "cer_parallel_p75": cers[3 * len(cers) // 4] if cers else None,
        "cer_wholepage_median_for_contrast": whole[len(whole) // 2] if whole else None,
        "note": "CER retains a 2008-edition recension floor (normalized orthography/punctuation); "
                "use for ranking, omission and reading-order, not as absolute reader accuracy",
    }, indent=2), flush=True)
    if GCS:
        subprocess.run(["gsutil", "-q", "cp", OUT, GCS], check=False)

if __name__ == "__main__":
    main()
