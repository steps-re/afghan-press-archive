# Gold & benchmark sources for HTR (Afghan lithograph + general Perso-Arabic)

An archive sweep (2026-07-29) for HUMAN transcriptions/translations usable to measure our
AI reader. Bottom line up front:

**No page-level human transcription of the Afghanistan Digital Library's own lithographs
exists anywhere.** That is not surprising: our catalog scan shows the ADL is dominated by
*original* Afghan material (≥54% `Niẓāmnāmah` statutes, legal codes, Loya Jirga proceedings,
the Amir's edicts, administrative/military manuals) — obscure original print no scholar has
transcribed. Only a small minority are classical reprints with a prior canonical edition.

So gold comes in three forms, none of which is a drop-in ADL transcription:

## A. Reader benchmarks — real image + human transcription (measure the READER, script-level)
| Source | What | Size | Grabbed? | Match to our task |
|---|---|---|---|---|
| **OpenITI MAKHZAN** (Zenodo `10.5281/zenodo.19861912`, CC-BY-NC-SA) | Perso-Arabic manuscript pages + **line-level ALTO XML** transcriptions | **352 Persian pages, 201 of them NASTALIQ, 5,505 transcribed lines** (full set 1,497 pp / 6.1 GB) | metadata TSV grabbed (`makhzan_metadata.tsv`); pull the Persian subset from Zenodo (big → do on a VM) | **Best available.** Real human nastaliq gold. Manuscript, not lithograph, but by far the closest public match — benchmark the reader on this for free. |
| **OpenITI OCR_GS_Data/`fas`** (GitHub, CC-BY-NC-SA) | Persian line-crop images + `.gt.txt` | **~2,876 pairs** (Gulistan 835, Kalileh 1,017, Fihi 1,024) | **grabbed** (`OCR_GS_Data/`) | Real Persian ground truth, but clean *naskh typeset* (pixel-verified) — a baseline sanity benchmark, not nastaliq. |
| **UTRSet-Real** (GitHub UTRNet, Google-Drive) | 11,000+ real printed **Urdu nastaliq** line images + human labels | ~11k lines | not grabbed (Google Drive; adjacent script) | Urdu nastaliq ≈ Persian nastaliq visually — proxy / pretraining, not Persian gold. |

## B. Content cross-checks — human translations/related text (check MEANING, not CER)
| Source | What | Grabbed? | Use |
|---|---|---|---|
| **McChesney & Khorrami, *Siraj al-Tawārīkh* (Brill, EN translation)** | Scholarly English translation of the chronicle = **adl0009** (which we already transcribed, 1,269 pp) | **grabbed** (`siraj_al_tawarikh_EN_mcchesney.txt`, 8.8 MB) | Semantic cross-check: does our Persian transcription of adl0009 say what the translation says? |
| **Mahmud Tarzi collected articles** (archive.org, Persian) | 759 pp of Tarzi's prose (same author/register as Siraj al-Akhbar) | **grabbed** (`tarzi_articles_fa.txt`, 1.7 MB) | Vocabulary / content cross-check for the periodicals. |

## C. Canonical alignment gold — free, for the classical-reprint sliver of ADL
Our existing Ganjoor aligner (used for the Bustan gold) extends with ZERO new integration to
any ADL book reprinting a major poet. Confirmed live on `api.ganjoor.net`:
Hafez (Divan), Rumi (Masnavi, 25,636 vv; Divan-e Shams), Nizami (Khamsa), Jami (Haft Awrang),
Saadi (Bustan+Gulistan), Bidel (~33k vv, partial), Ferdowsi, Attar, Khayyam. Bulk SQLite dump
on SourceForge. Also clean bulk text: **Quran** = Tanzil.net (+ QuranEnc Dari); **Hadith** =
sunnah.com dump / `hadith-json`. **Gap:** Persian prose/fiqh/tafsir has no open API — Noor
Digital Library (noorlib.ir, 8k books) is login-gated; treat as a manual pull if needed.

## The gap that remains (and the honest ask)
For the ADL's *original* bulk (statutes, periodicals) there is no prior text, so certifying
accuracy there still needs either:
1. a small **home-built gold set** (~50 pages, dual-key + expert adjudication — the one cash item), or
2. **collaboration**: email `dlts@nyu.edu` — the ADL "about" page hints at a pilot
   "transliterated text search" layer; the OpenITI/AOCP team (Eshera/Shahid/Allen, already in
   contact) produce exactly this kind of ground truth and want this material.

_Downloaded data lives in `work/gold_sources/` (gitignored). This file is the map._
