# Afghan Press Archive

**[afghanpress.org](https://afghanpress.org)** — every page of the Afghanistan Digital Library,
read by machine and made searchable for the first time.

**69,624 pages · 580 volumes · Kabul and elsewhere, 1873–1960s · Persian, Dari, Pashto**

The scans belong to [New York University Libraries](https://afghanistandl.nyu.edu/) and are in
the public domain. The transcription, the index, the reader and the measurements are this
repository. The transcription is released on the same terms as the scans.

---

## Why this exists

These volumes have been available as images for years, and unsearchable for just as long. A
scholar wanting to know where a word first appears, or what a given issue said about a given
week, has had to read forward through thousands of pages to find out.

The collection is also hard to read by machine. Printing came to Afghanistan as **lithography**
rather than movable type, so these newspapers are manuscripts written out by a calligrapher and
transferred to stone. The script is nasta'liq — cursive, overlapping, context-dependent, and
still difficult for software.

## The part worth stealing

Ground truth for a historical corpus normally means transcribing by hand, which is why so
little exists for Perso-Arabic print.

**Where a modern printed edition of the same text exists, you can manufacture ground truth
instead.** Re-read the modern edition (clean type, easy for a model), align it against the
original page images, and have a model adjudicate every candidate pair — explicitly told that
shared author, topic and era are *not* evidence. What survives is verified image-to-text pairs,
for the cost of the compute.

That produced **102 aligned pairs for lithographed Kabul nasta'liq**, which as far as we know
did not previously exist. The method is in [`siraj/`](siraj/) and transfers to any corpus with a
modern reprint. Both the code and the gold set are yours on request.

## What the numbers actually are

| | |
|---|---|
| Reading accuracy vs a modern printed **edition**, representative sample | **0.36 median CER** (n=102) — ~0.19 of that is editorial recension, not misreading |
| Reading accuracy vs **human** transcription | ~93% of characters, but **n=3 passages of a 1940s newspaper** — easier printing than most of the corpus. An indication, not a measurement |
| Search: right page in top 20, long quote | **81%** |
| Search: right page in top 20, short phrase | **60%** |
| Cost to read the entire collection | **~$288** |

Good enough to find a page. Not good enough to quote — read the image.

## What did not work

[`RESULTS.md`](RESULTS.md) is the honest record, including the failures, because they were the
expensive part:

- **Layout-first region cropping** — the intervention most expected to help. Zero accuracy gain
  at ~11× the cost. It does rescue ~8% of pages that fail outright, so it belongs as a fallback,
  not a default.
- **A second fine-tuned reader** — tuning the best tunable base model produced a reader
  statistically indistinguishable from the frontier one it was meant to beat.
- **Ensemble adjudication** — real but tiny, and it worked by fixing wording rather than
  recovering omissions, which is the opposite of what was predicted.
- **Post-hoc linguistic correction** — improved the score while rewriting 3–5% of
  already-correct text. For a primary source that is damage, not improvement.

Two measurement bugs are also documented. One scored models on the 40 *easiest* pages because
the gold file was sorted by difficulty; another used a one-tailed significance test, so arms
that were significantly *worse* reported as "no difference." Both made results look better than
they were, and both were caught only by scaling the sample.

The through-line: nearly every intervention that sounded like it should help did not, and the
two that mattered — turning the model's reasoning budget down, and batch inference — were worth
a **31× cost reduction** between them.

## Layout

```
htr/       model bank, layout-first transcription, evaluation spine
siraj/     the pipeline — catalogue, batch reading, alignment, benchmarks
reader/    the search API and the site, plus twelve design studies
```

## Running it

Nothing is hardcoded to any cloud account. Copy `.env.example` and set four values:

```sh
export HTR_PROJECT=my-gcp-project      # serves the models
export HTR_BUCKET=gs://my-bucket       # artefacts in and out
export HTR_LOCATION=us-central1
export HTR_CONTACT=you@example.com     # sent in the User-Agent when fetching from a library
```

Anything unset disables the feature that needs it and says which variable to export.

## Data

The full corpus is one JSON Lines record per page — volume, page, text — from
[afghanpress.org/api/download/corpus.jsonl](https://afghanpress.org/api/download/corpus.jsonl).
No account, no rate limit, no attribution requirement beyond crediting NYU for the scans.

## Citing

> Afghan Press Archive, `adl0616`, p. 575. Digitised by New York University Libraries.
> Transcription machine-generated and unverified, retrieved YYYY-MM-DD.

If a passage matters to your argument, cite the image and transcribe it yourself.

## Please be careful with this

The text is a finding aid. Reading order on dense multi-column pages is unverified, 72 pages
returned nothing at all, nobody has checked any of it by hand, and the accuracy figure rests on
three passages of one newspaper. [The method page](https://afghanpress.org/about.html) says all
of this in more detail, on purpose.
