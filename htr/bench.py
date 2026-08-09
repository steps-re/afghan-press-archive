"""Benchmark harness: score the reader bank against human gold, resumably.

Gold row: {"key","image_path" or "image_b64","ref"}. For each (row, backend[, config]) it
runs the reader, computes CER/WER vs the human ref, and checkpoints to a JSONL so a flaky/
interrupted run resumes. Aggregates a per-backend table. Everything runs on free credits.
"""
import base64, json, os, threading, time, statistics as st
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import models, metrics

SYS_READ = ("You are an expert transcriber of historical Perso-Arabic text (Persian/Dari, "
            "Arabic, Urdu) in naskh/nastaliq. Transcribe faithfully in the original script, "
            "right-to-left. Output ONLY the transcription.")
PROMPT_READ = ("Transcribe this image faithfully in the original script. Preserve spelling. "
               "Output ONLY the transcription, no commentary.")

def _b64(row):
    if row.get("image_b64"):
        return row["image_b64"]
    with open(row["image_path"], "rb") as f:
        return base64.b64encode(f.read()).decode()

def run(gold_rows, backends, out_jsonl, workers=2, pace=0.0, limit=None):
    """Score each backend on each gold row. Resumable via out_jsonl. workers small + pace
    to respect the shared-credit pacing preference (no bursting)."""
    rows = gold_rows[:limit] if limit else gold_rows
    done = set()
    if os.path.exists(out_jsonl):
        for ln in open(out_jsonl):
            try:
                r = json.loads(ln); done.add((r["key"], r["backend"]))
            except Exception:
                pass
    lock = threading.Lock()
    ck = open(out_jsonl, "a")
    tasks = [(row, b) for row in rows for b in backends if (row["key"], b) not in done]
    print(f"bench: {len(rows)} rows x {len(backends)} backends = {len(rows)*len(backends)} "
          f"({len(done)} done, {len(tasks)} to run)", flush=True)

    def one(row, backend):
        try:
            b64 = _b64(row)
            pred = models.transcribe(backend, SYS_READ, PROMPT_READ, b64,
                                     **({} if backend.startswith("gpt") else {"temperature": 0.1}))
            rec = {"key": row["key"], "backend": backend, "cer": metrics.cer(pred, row["ref"]),
                   "wer": metrics.wer(pred, row["ref"]), "pred_len": len(pred or ""),
                   "ref_len": len(row["ref"]), "degenerate": metrics.degeneration(pred)}
        except Exception as e:
            rec = {"key": row["key"], "backend": backend, "error": str(e)[:160]}
        if pace:
            time.sleep(pace)
        return rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one, row, b) for row, b in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            rec = f.result()
            with lock:
                ck.write(json.dumps(rec, ensure_ascii=False) + "\n"); ck.flush()
            if i % 20 == 0:
                print(f"  {i}/{len(tasks)}", flush=True)
    ck.close()
    return summarize(out_jsonl)

def summarize(out_jsonl):
    by = {}
    for ln in open(out_jsonl):
        try:
            r = json.loads(ln)
        except Exception:
            continue
        by.setdefault(r["backend"], []).append(r)
    table = {}
    for b, rs in by.items():
        cers = [r["cer"] for r in rs if isinstance(r.get("cer"), float)]
        wers = [r["wer"] for r in rs if isinstance(r.get("wer"), float)]
        table[b] = {"n": len(cers), "errors": sum(1 for r in rs if r.get("error")),
                    "cer_mean": round(st.mean(cers), 4) if cers else None,
                    "cer_median": round(st.median(cers), 4) if cers else None,
                    "wer_mean": round(st.mean(wers), 4) if wers else None,
                    "degenerate": sum(1 for r in rs if r.get("degenerate"))}
    return table
