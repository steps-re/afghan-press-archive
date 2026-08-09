#!/usr/bin/env python3
"""Phase C2: decide candidate pairs with a model judge instead of a distributional threshold.

Why this stage exists. Every purely distributional discriminator tried on this pair failed:
4-gram anchors, rare-token anchors, content-word Jaccard, anchor span, distinct-type counts,
and longest-increasing-subsequence. They fail for a structural reason, not a tuning reason --
the reference (Tarzi's collected articles) and the target (the newspaper he edited) are the
same author, same decade, same subject matter, so ANY two pages share heavy vocabulary. The
measured false positives (a masthead vs photo captions; a trade item vs a press notice) scored
AT OR ABOVE genuine controls on every feature, including LIS, where the offset bucket already
forces monotonicity so the statistic carries no extra information.

So the architecture changes: the cheap distributional pass is kept ONLY as a high-recall
prefilter, and the accept/reject call is made by a reader that can tell "same text" from
"same topic". That is a judgment, not a statistic.

Output is deliberately three-way: same / different / uncertain. Uncertain stays out of the
gold set and becomes a human worklist, the same discipline used for the cross-vendor
disagreement set.
"""
import base64, json, os, subprocess, sys, threading, time, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

ALIGN = os.path.expanduser(os.environ.get("ADJ_IN", "~/siraj_gold/alignment.jsonl"))
OUT = os.path.expanduser(os.environ.get("ADJ_OUT", "~/siraj_gold/adjudicated.jsonl"))
GCS = os.environ.get("ADJ_GCS", os.environ.get("HTR_BUCKET", "").rstrip("/") + "/siraj_gold/")
MODEL = os.environ.get("ADJ_MODEL", "gemini-3.1-pro-preview")
PROJECT = os.environ.get("HTR_PROJECT", "")
WORKERS = int(os.environ.get("ADJ_WORKERS", "8"))
# Prefilter is for RECALL now, so it runs wide open; precision comes from the judge.
MIN_VOTE = float(os.environ.get("ADJ_MIN_VOTE", "0.20"))

SYSTEM = (
    "You compare two Persian texts. One is a machine transcription of a page of the Kabul "
    "newspaper Siraj al-Akhbar (1911-1918), lithographed nastaliq, so it contains reading "
    "errors. The other is a passage from a 2008 typeset edition of Mahmud Tarzi's collected "
    "articles, which were originally published in that same newspaper. The edition normalizes "
    "spelling and punctuation.\n"
    "Decide whether they are THE SAME UNDERLYING TEXT (the edition's version of what is on "
    "that newspaper page), or merely two different texts that share subject matter, era and "
    "vocabulary.\n"
    "Be strict. Same author, same topic, same period and shared proper nouns are NOT evidence "
    "of sameness. Sameness requires the same propositions in the same order: matching sentence "
    "openings, matching clause sequence, the same specific claims and names in the same places. "
    "Newspaper mastheads, subscription prices, advertisements and photo captions are NEVER the "
    "same text as an article, even when they share names.\n"
    'Answer as JSON only: {"verdict":"same"|"different"|"uncertain","confidence":0.0-1.0,'
    '"evidence":"<one sentence citing the specific overlap or mismatch>"}'
)

_tok = {"v": None, "e": 0.0}; _lock = threading.Lock()
def token():
    with _lock:
        if _tok["v"] and time.time() < _tok["e"]:
            return _tok["v"]
        _tok["v"] = subprocess.check_output(["gcloud", "auth", "print-access-token"]).decode().strip()
        _tok["e"] = time.time() + 1500
        return _tok["v"]

def judge(siraj, edition, retries=3):
    host = "aiplatform.googleapis.com" if MODEL.startswith("gemini-3") else "us-central1-aiplatform.googleapis.com"
    loc = "global" if MODEL.startswith("gemini-3") else "us-central1"
    url = f"https://{host}/v1/projects/{PROJECT}/locations/{loc}/publishers/google/models/{MODEL}:generateContent"
    prompt = (f"TEXT A (newspaper page, machine-read):\n{siraj[:3500]}\n\n"
              f"TEXT B (2008 edition passage):\n{edition[:3500]}\n\nAnswer as JSON only.")
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": SYSTEM}]},
            "generationConfig": {"maxOutputTokens": 1024, "responseMimeType": "application/json"}}
    data = json.dumps(body).encode()
    for a in range(retries + 1):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "Authorization": f"Bearer {token()}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                d = json.loads(r.read())
            c = (d.get("candidates") or [{}])[0]
            txt = "".join(x.get("text", "") for x in (c.get("content") or {}).get("parts") or []).strip()
            if txt:
                v = json.loads(txt)
                # the model occasionally wraps the object in an array despite the schema
                if isinstance(v, list):
                    v = next((x for x in v if isinstance(x, dict)), None)
                if isinstance(v, dict) and "verdict" in v:
                    return v
                return {"verdict": "uncertain", "confidence": 0.0,
                        "evidence": f"unparseable judge reply: {str(txt)[:120]}"}
        except Exception:
            time.sleep(min(2 ** a, 20))
    return {"verdict": "uncertain", "confidence": 0.0, "evidence": "judge failed"}

def main():
    cands = [json.loads(l) for l in open(ALIGN, encoding="utf-8")]
    cands = [c for c in cands if c.get("siraj_text") and c.get("edition_text")
             and c.get("vote_ratio", 0) >= MIN_VOTE]
    print(f"[adj] {len(cands)} candidate pairs to judge with {MODEL}", flush=True)

    res, lk = [], threading.Lock()
    def work(c):
        v = judge(c["siraj_text"], c["edition_text"])
        rec = {**{k: c[k] for k in ("book", "page", "vote_ratio", "content_jaccard",
                                    "anchor_types", "anchor_span", "tarzi_pages")
                  if k in c},
               "prefilter_tier": c.get("tier"), "judge": v,
               "cer_vs_edition": c.get("cer_vs_edition")}
        with lk:
            res.append(rec)
            if len(res) % 20 == 0:
                print(f"[adj] {len(res)}/{len(cands)}", flush=True)
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        list(as_completed([ex.submit(work, c) for c in cands]))

    for r in res:
        if not isinstance(r.get("judge"), dict):
            r["judge"] = {"verdict": "uncertain", "confidence": 0.0, "evidence": "malformed"}
    res.sort(key=lambda r: -(r["judge"].get("confidence") or 0))
    with open(OUT, "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    from collections import Counter
    tally = Counter(r["judge"].get("verdict") for r in res)
    gold = [r for r in res if r["judge"].get("verdict") == "same" and r["judge"].get("confidence", 0) >= 0.7]
    cers = sorted(r["cer_vs_edition"] for r in gold if r.get("cer_vs_edition") is not None)
    print(json.dumps({"judged": len(res), "verdicts": dict(tally), "gold_pairs": len(gold),
                      "cer_median": cers[len(cers) // 2] if cers else None}, indent=2), flush=True)
    if GCS:
        subprocess.run(["gsutil", "-q", "cp", OUT, GCS], check=False)

if __name__ == "__main__":
    main()
