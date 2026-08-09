# Afghan Press Archive — afghanpress.org

Search and reading interface over 69,624 machine-read pages of the Afghanistan Digital
Library (579 volumes, 1871–1930s). Scans are NYU's; the transcription and index are ours.

## Why it is built this way

Every design choice traces to a measurement in [`../RESULTS.md`](../RESULTS.md):

| Decision | Because |
|---|---|
| Character **trigram** index, not words | OCR error and remembered wording both break exact match; a misread word still shares most trigrams |
| Normalise text **and** query identically | Kabul lithograph vs modern keyboard disagree on ی/ي, ک/ك, tatweel, diacritics, digits — nearly as large a gap as our OCR error |
| **Lexical is the default**, not hybrid | Measured: trigram 81.4%/59.8% top-20 (long/short); semantic 54.9%/23.5%; RRF fusion *hurts* short queries |
| Semantic kept as an explicit mode | It is the only thing that can answer a topical query; the gold set cannot measure that, so it is offered, not defaulted |
| Query keeps the **40 rarest** trigrams | `_و_` matches 59,207 of 69,624 pages. Latency 2.5s → 1.3s, accuracy unchanged |
| Raw text is never rewritten | AI "cleanup" measurably alters 3–5% of already-correct text |
| Page image beside every result | Transcription is a finding aid at ~93% character accuracy; the image is the source of record |

## Layout

    app/main.py            search, reader, downloads, contributions API
    app/static/            index.html (search + reader), about.html (method & limits)
    app/static/fonts/      Amiri, self-hosted (SIL OFL) — no third-party request
    data/                  corpus.db (518MB) + corpus_vecs.npy (214MB), baked into the image

## Data

Rebuild from `$HTR_BUCKET/corpus/transcriptions_full.jsonl` with
`../siraj/build_full_index.py`. The index ships inside the container: the corpus is a finished
historical artefact, so a redeploy-on-change model costs nothing and removes a database.

## Contributions

Firestore + Firebase Auth (email link). **Corrections** are public after moderation and
credited. **Annotations** are private to their author, never moderated, never shown to anyone
else — researchers will not take notes in a public field. Neither ever mutates the
transcription; corrections are an overlay.

Set `ADL_MODERATORS` to a comma-separated list of moderator emails.

## Local

    ADL_DATA=$PWD/data python3 -m uvicorn app.main:app --port 8099
