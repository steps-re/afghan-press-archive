#!/usr/bin/env python3
"""Phase C: align adl0616 (Siraj al-Akhbar lithograph pages) against the modern
typeset Maqalat-e Tarzi edition, producing the first newspaper-layout gold pairs.

Method: anchor-and-extend. Both sides are normalized to a bare token stream, the Tarzi
side is indexed by token 4-gram, and each Siraj page votes for a start offset in Tarzi.
The winning window is scored with true character Levenshtein (NOT difflib -- difflib's
global ratio passes pages where every name and number is wrong).

What this is and is not:
  - IS content gold for the pages where Tarzi's own articles ran, which is a subset.
  - IS NOT orthographic gold. The 2008 Farhadi edition normalizes spelling and adds
    punctuation, so absolute CER carries an editorial floor. Rankings, omissions,
    reading-order breaks and garbled names/numbers are the trustworthy signals.
Unmatched pages are not failures: most of the paper is news, ads and other authors.
"""
import bisect, json, os, re, subprocess, unicodedata
from collections import Counter, defaultdict

TARZI = os.path.expanduser("~/tarzi_out/tarzi_pages.jsonl")
SIRAJ = os.path.expanduser("~/siraj/afghan/afghan_transcriptions.jsonl")
OUTDIR = os.path.expanduser(os.environ.get("ALIGN_OUT", "~/siraj_gold")); os.makedirs(OUTDIR, exist_ok=True)
GCS = os.environ.get("ALIGN_GCS", os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/")   # empty = skip upload (dry runs)
MIN_TOKENS = 40          # shorter pages cannot vote reliably
BUCKET = 32              # offset tolerance: the two texts drift, so exact offsets scatter votes
NSTOP = 150              # most-frequent tokens excluded from the content score
RARE_MAX = 25            # a token occurring more than this is not a distinctive anchor
RARE_MINLEN = 3
MIN_RARE = 12            # too few rare words on the page to decide either way
MIN_TYPES = int(os.environ.get("ALIGN_MIN_TYPES", "12"))   # distinct shared rare words
MIN_SPAN = float(os.environ.get("ALIGN_MIN_SPAN", "0.0"))  # see note: span mis-rejects true pairs
# NOTE ON GATES. This stage is a RECALL prefilter, not the decision. Precision comes from the
# model judge in adjudicate_align.py. Tight statistical gates were tried and abandoned: they
# rejected pairs that turned out to be genuinely the same article, because reference and target
# are the same author/era/topic and every distributional feature (rare-token overlap, content
# Jaccard, anchor span, distinct types, LIS) scores false and true pairs alike. LIS is actively
# useless here -- the offset bucket already forces monotonicity, so false positives scored
# HIGHER on it than true controls. Keep these wide and let the judge decide.
MIN_VOTE_RATIO = float(os.environ.get("ALIGN_MIN_VOTES", "0.20"))
MIN_CONTENT_JAC = float(os.environ.get("ALIGN_MIN_JAC", "0.15"))
REVIEW_VOTE_RATIO = float(os.environ.get("ALIGN_REVIEW_VOTES", "0.12"))
REVIEW_CONTENT_JAC = float(os.environ.get("ALIGN_REVIEW_JAC", "0.10"))

HARAKAT = dict.fromkeys(range(0x064B, 0x0653), None)
DROP = dict.fromkeys(map(ord, "«»؛،؟!?.,:;()[]{}\"'—–-*/\\|_=+<>#%&@~`^$"), " ")
MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه",
                     "ﻻ": "لا", "ـ": "", "‌": " ", "‏": "", "‎": ""})
TAG = re.compile(r"^\s*\[[^\]]{0,40}\]\s*")          # leading [Persian] / [Mixed: ...]
MARK = re.compile(r"\[(?:ILL|\?|BLANK PAGE|PLATE)\]")

def norm(t):
    t = TAG.sub("", t or "")
    t = MARK.sub(" ", t)
    t = re.sub(r"\[([^\]]*)\؟?\]", r"\1", t)          # [word?] -> word (keep the guess)
    t = unicodedata.normalize("NFKC", t).translate(MAP).translate(HARAKAT).translate(DROP)
    t = re.sub(r"[۰-۹٠-٩\d]+", " 0 ", t)   # digits -> placeholder
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

def main():
    tz = [json.loads(l) for l in open(TARZI, encoding="utf-8")]
    tz = [r for r in tz if r.get("text") and r["text"] not in ("[BLANK PAGE]", "[PLATE]")]
    tz.sort(key=lambda r: r["page"])
    toks, owner = [], []
    for r in tz:
        w = norm(r["text"])
        toks.extend(w); owner.extend([r["page"]] * len(w))
    print(f"[align] tarzi: {len(tz)} pages, {len(toks):,} tokens", flush=True)

    # Anchor on RARE SINGLE TOKENS, not n-grams. A 4-gram needs four consecutive words read
    # correctly; at the ~30-45% token noise a lithograph read plus a recension gap actually
    # produces, almost none survive, and measured vote_ratio for a TRUE match falls below the
    # false-positive ceiling. A rare word needs only itself to survive, so it degrades far more
    # gracefully. Calibrated against the noise sweep in the selftest.
    freq = Counter(toks)
    index = defaultdict(list)
    for i, t in enumerate(toks):
        if len(t) >= RARE_MINLEN and freq[t] <= RARE_MAX:
            index[t].append(i)
    stop = {w for w, _ in freq.most_common(NSTOP)}
    print(f"[align] index: {len(index):,} rare-token anchors | {len(stop)} stopwords excluded", flush=True)

    pages = [json.loads(l) for l in open(SIRAJ, encoding="utf-8")]
    pages = [p for p in pages if p.get("text")]
    pages.sort(key=lambda p: p["page"])
    print(f"[align] siraj: {len(pages)} transcribed pages", flush=True)

    if os.environ.get("ALIGN_SELFTEST"):
        # Positive control: feed back slices of the Tarzi text itself, lightly corrupted to
        # imitate a noisy read. Rejecting false positives is only half the proof -- the gates
        # also have to still FIRE on a genuine match.
        import random
        rnd = random.Random(0)
        noise = float(os.environ["ALIGN_SELFTEST"])   # word-drop AND ending-clip rate
        pages = []
        for k, s in enumerate((5000, 40000, 80000, 120000, 160000, 200000)):
            w = toks[s:s + 300]
            w = [t for t in w if rnd.random() > noise]
            w = [t if rnd.random() > noise else t[:-1] for t in w]
            pages.append({"book": "SELFTEST", "page": k, "text": " ".join(w)})
        print(f"[align] SELFTEST noise={noise}: {len(pages)} synthetic pages", flush=True)

    out, matched = [], 0
    for p in pages:
        w = norm(p["text"])
        if len(w) < MIN_TOKENS:
            continue
        # vote for the page's start offset, bucketed so near-misses reinforce instead of scatter
        votes, exact = Counter(), defaultdict(Counter)
        n_rare = 0
        for i, t in enumerate(w):
            hits = index.get(t)
            if not hits:
                continue
            n_rare += 1
            for pos in hits:
                off = pos - i
                votes[off // BUCKET] += 1
                exact[off // BUCKET][off] += 1
        if not votes or n_rare < MIN_RARE:
            continue
        bucket, nvotes = votes.most_common(1)[0]
        start = max(0, exact[bucket].most_common(1)[0][0])
        # fraction of THIS PAGE's rare words that landed in the winning offset bucket
        vote_ratio = nvotes / max(1, n_rare)

        # Two structural checks a genuine parallel page passes and a proper-noun cluster fails.
        # A masthead or a photo caption is dense in the same rare names (محمود طرزی, کابل,
        # دارالسلطنه) as the edition's front matter, so it wins on vote_ratio alone. A real
        # parallel page instead shares MANY DISTINCT rare words spread across the whole page.
        hit_at, hit_pos, types = [], [], set()
        for i, t in enumerate(w):
            for pos in index.get(t, ()):
                if (pos - i) // BUCKET == bucket:
                    types.add(t); hit_at.append(i); hit_pos.append(pos)
                    break
        span = ((max(hit_at) - min(hit_at)) / max(1, len(w))) if hit_at else 0.0
        n_types = len(types)

        # ORDER is the discriminator co-occurrence cannot give us. Reference and target are the
        # same author, era and subject matter, so shared vocabulary is high between ANY two
        # pages -- which is why rare-token overlap alone still produced confident garbage
        # (p123: 64 shared rare types, span 0.79, and simply not the same text). Genuine
        # parallel text puts its anchors in the SAME SEQUENCE, so the longest increasing run of
        # target positions separates real alignment from coincidental topical overlap.
        lis = []
        for pos in hit_pos:
            k = bisect.bisect_left(lis, pos)
            if k == len(lis):
                lis.append(pos)
            else:
                lis[k] = pos
        lis_len = len(lis)
        lis_ratio = lis_len / max(1, len(hit_pos))
        window = toks[start:start + len(w)]
        if not window:
            continue
        cw, cwin = [t for t in w if t not in stop], [t for t in window if t not in stop]
        inter = sum((Counter(cw) & Counter(cwin)).values())
        jac = inter / max(1, max(len(cw), len(cwin)))
        rec = {"book": p["book"], "page": p["page"], "anchor_votes": nvotes,
               "vote_ratio": round(vote_ratio, 4), "content_jaccard": round(jac, 4),
               "tarzi_start": start,
               "tarzi_pages": sorted(set(owner[start:start + len(w)])),
               "siraj_tokens": len(w), "rare_anchors": n_rare,
               "anchor_types": n_types, "anchor_span": round(span, 3),
               "lis_len": lis_len, "lis_ratio": round(lis_ratio, 3),
               "matched": (vote_ratio >= MIN_VOTE_RATIO and jac >= MIN_CONTENT_JAC
                           and n_types >= MIN_TYPES and span >= MIN_SPAN
                           )}
        rec["tier"] = ("gold" if rec["matched"] else
                       "review" if (vote_ratio >= REVIEW_VOTE_RATIO and jac >= REVIEW_CONTENT_JAC)
                       else "reject")
        if rec["tier"] in ("gold", "review"):   # review pairs must be inspectable, not opaque
            a, b = " ".join(w), " ".join(window)
            rec["cer_vs_edition"] = round(levenshtein(a, b) / max(len(a), len(b)), 4)
            rec["siraj_text"] = p["text"]
            rec["edition_text"] = b
            matched += rec["matched"]
        out.append(rec)

    out.sort(key=lambda r: -r["content_jaccard"])
    with open(os.path.join(OUTDIR, "alignment.jsonl"), "w", encoding="utf-8") as f:
        for r in out:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    good = [r for r in out if r["matched"]]
    cers = sorted(r["cer_vs_edition"] for r in good if "cer_vs_edition" in r)
    tiers = Counter(r["tier"] for r in out)
    summary = {"siraj_pages_scored": len(out), "matched_pages": matched,
               "match_rate": round(matched / max(1, len(out)), 4),
               "tiers": dict(tiers),
               "gates": {"gold": [MIN_VOTE_RATIO, MIN_CONTENT_JAC],
                         "review": [REVIEW_VOTE_RATIO, REVIEW_CONTENT_JAC],
                         "basis": "calibrated vs positive-control noise sweep and the observed "
                                  "false-positive ceiling; precision-biased, recall is partial"},
               "best_unmatched": [{"page": r["page"], "vote_ratio": r["vote_ratio"],
                                   "content_jaccard": r["content_jaccard"]}
                                  for r in out if not r["matched"]][:5],
               "cer_median": cers[len(cers) // 2] if cers else None,
               "cer_p25": cers[len(cers) // 4] if cers else None,
               "cer_p75": cers[3 * len(cers) // 4] if cers else None,
               "note": "CER carries a 2008-edition recension floor; use for ranking/omission, not absolute accuracy"}
    json.dump(summary, open(os.path.join(OUTDIR, "summary.json"), "w"), indent=2)
    print("[align]", json.dumps(summary, indent=2), flush=True)
    if GCS:
        subprocess.run(["gsutil", "-q", "cp", os.path.join(OUTDIR, "alignment.jsonl"),
                        os.path.join(OUTDIR, "summary.json"), GCS], check=False)

if __name__ == "__main__":
    main()
