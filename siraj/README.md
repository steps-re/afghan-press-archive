# siraj — building real newspaper gold for Siraj al-Akhbar

These scripts produced the project's first **aligned image↔text gold set for the actual
newspaper target** (`adl0616`, Sirāj al-akhbār, Kabul 1911–1918, 1,787 pp), with $0 cash.

The trick: ADL holds the lithographed run, and a modern typeset edition —
*Maqālāt-e Maḥmūd Ṭarzī* (Farhadi, 2008, 757 pp) — reprints Tarzi's own articles from the
same paper, same years. Re-OCR the clean typeset edition, align it to the lithograph pages,
and you get free gold without hand transcription. Same move as the Ganjoor/Bustan trick,
applied to the newspaper.

Run on the `eel-compute` VM off donated cloud credits. **Stop the VM when idle.**

## Pipeline order

| Script | Does |
|---|---|
| `tarzi_ocr.py` | Re-OCR all 757 pp of the Tarzi edition at 300dpi with `gemini-2.5-pro` (naskh **print** — 2.5 beats 3.x here; the 3.x-wins result is nastaliq-only). Normalizes: strips tatweel/kashida, unifies Arabic→Persian yeh/kaf. |
| `tarzi_fix_trunc.py` | Re-reads pages that hit MAX_TOKENS. These look like clean reads but drop the tail, so they score as false omissions. 8/757 hit it; all recovered at 24,576 tokens. |
| `setup_siraj.py` / `spot_siraj.py` | Stand up the isolated pipeline copy at `~/siraj` (manifest pinned to `adl0616` so it can't touch the main corpus run) and spot-check pages. |
| `align_siraj.py` | Distributional prefilter for **recall**: normalize both sides to bare token streams, each Siraj page votes for a start offset, **bucketed by 32** (exact-offset voting scatters a true match's evidence). |
| `adjudicate_align.py` | `gemini-3.1-pro` judge for **precision** — same / different / uncertain, explicitly told that shared author, topic, era and proper nouns are *not* evidence. |
| `local_span.py` | CER over only the genuinely parallel region. SequenceMatcher over tokens **locates** the region; true character Levenshtein **scores** it. difflib never produces the reported number. |
| `reader_bakeoff.py` | Head-to-head reader ranking on the gold pairs. Any arm can be a publisher model, an Azure GPT deployment, or a tuned-endpoint resource path. |
| `layout_bake.py` | Whole-page vs layout-first cropping on the same pages, same render, same scoring. |

## Rules learned the hard way

- **Never judge an alignment from unaligned prefixes.** A newspaper page opens with
  masthead/price/TOC furniture the edition never reprints, so the shared region starts
  further down. Judging by first-300-chars nearly threw the working method away; every
  statistic agreed with the wrong call and only the model judge caught it.
- **Always report CER over the parallel span**, never whole-page — the page has columns,
  ads and TOC with no counterpart, so whole-page CER is inflated by construction.
- **Always pair CER with `ref_recall`.** CER over a span gives partial credit, so a model
  that omits the hard half of a page posts a better CER while reading *less*. Reading CER
  alone would have rejected layout-first, which is the winning method.
- **Absolute CER is not orthographic truth.** A modern editorial recension (normalized
  spelling, added punctuation) inflates it, same as the ~0.19 Iranian-canon-vs-Kabul floor.
  The **ranking** is the decision-relevant signal.
- Keep the positive control (`ALIGN_SELFTEST=<noise>` feeds corrupted slices of the Tarzi
  text back through). It is what made the tuning falsifiable.
- The judge occasionally returns a JSON **array** despite an object schema. Coerce
  list→first dict, and never let one malformed record kill the write of the rest — that bug
  lost 168 already-paid-for calls.
- `gemini-3.x` 404s on the regional host. Use the **global** endpoint.
- Launch background jobs with `setsid nohup … < /dev/null & disown` and `python3 -u`.
  `pkill -f <script>` matches the SSH wrapper and kills your own session.

## Artifacts

`$HTR_BUCKET/tarzi/` — `maqalat_tarzi.pdf`, `tarzi_pages.jsonl`, `tarzi_full.txt`
`$HTR_BUCKET/siraj_gold/` — `adl0616_transcriptions.jsonl` (full 1,787-page corpus),
`alignment.jsonl`, `adjudicated.jsonl`, `gold_pairs.jsonl` (**the 102 gold pairs**),
plus the bakeoff outputs.

The 43 "uncertain" and 22 "different" judgements are not waste — they are the human worklist.
