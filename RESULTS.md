# Benchmark results — reader vs human gold

First real, independent accuracy numbers for the reader bank, scored against **human**
ground truth (not Gemini-judging-Gemini). Metric: character error rate (Levenshtein / ref
length), **lower is better**. Runs on the the credit grant VM off the default SA (free credits), paced.

## The result: model choice is SCRIPT-DEPENDENT, and 3.x wins on the corpus

| Reader | naskh print (OCR_GS, n=60) | nastaliq manuscript (MAKHZAN, n=40) | **nastaliq LITHOGRAPH — real ADL (Bustan, n=40)** |
|---|---|---|---|
| gemini-3.1-pro | 0.095 | **0.074** | **0.263** ← best |
| gemini-3.6-flash | 0.074 | 0.089 | 0.326 |
| gemini-2.5-pro | **0.029** | 0.114 | 0.485 |
| gemini-2.5-flash | **0.029** | 0.153 | **0.668** ← worst |

*(CER median. naskh = OpenITI OCR_GS_Data/fas typeset; nastaliq manuscript = OpenITI MAKHZAN
ALTO gold; lithograph = ADL Bustan adl0294 pages vs the Ganjoor canonical text.)*

- On **clean naskh print**, Gemini **2.5 wins ~3×** (2.5-flash ties 2.5-pro at Flash cost).
- On **nastaliq** — the script the **Afghan lithographs actually use** — the ranking **flips
  and stays flipped** from manuscript to real lithograph: **Gemini 3.x wins decisively.**
  `3.1-pro` best, `3.6-flash` a close second at Flash cost. `2.5-flash` is the **worst**.

## Two decisions this forces

1. **Read the ADL corpus with `gemini-3.1-pro` (best) or `gemini-3.6-flash` (near-best at
   Flash cost)** — not the 2.5 default. The model bank auto-routes 3.x to the global endpoint,
   so it's a config change (done: toolkit + pipeline defaults now 3.x).
2. **The distillation-to-2.5-flash strategy is undercut.** The pipeline distilled its cheap
   "student" into `gemini-2.5-flash` — which independent gold shows is the *worst* reader on
   lithograph nastaliq (0.668). The old "tuned-flash ≈ Pro parity" claim was circular (measured
   against a 2.5 teacher). If a cheap student is still wanted, distill from a 3.x teacher into
   a *tunable* 3.x flash (note: `gemini-3.6-flash` is not yet tunable on Vertex — so near-term
   the cheap-and-good option is just running `gemini-3.6-flash` directly, no tuning needed).

## 2026-08-08 — tuned gemini-2.5-pro, and a sampling bug that inflated every 40-page number

**Tuning the best *tunable* base was worth doing, but it is not the unlock the first run
suggested.** `htr-afghan-pro-v1` (supervised tune of `gemini-2.5-pro` on `afghan_v2`,
6 epochs, adapter 4 — deliberately identical to the flash v2 job so base model is the only
variable) scored against the 102 aligned adl0616 gold pairs. `adl0616` is confirmed absent
from both train (2,741 lines) and val (250) sets.

On **40 pages** the epoch-6 checkpoint looked like a clear win: CER 0.225 vs 3.1-pro's 0.281,
*and* recall 0.865 vs 0.767 — better on both axes at once.

On the **full 102** it mostly evaporated. Paired over the 96 pages both models scored:

| | 3.1-pro | tuned-2.5-pro e6 | paired delta | tuned wins |
|---|---|---|---|---|
| CER ↓ | 0.334 | 0.388 | +0.003 | 46/96 |
| ref_recall ↑ | 0.694 | 0.786 | +0.000 | 42/96 |
| **effective yield** ↑ | 0.420 | 0.452 | **+0.006** | **60/96** (sign test p=0.018) |

So: **real but small.** The tuned model edges 3.1-pro on effective yield — statistically
detectable, practically marginal. It is *not* better on CER, and its recall advantage comes
from a minority of pages with large gains, not a consistent shift.

### Why the 40-page run lied — and what else it contaminates

`gold_pairs.jsonl` is written **sorted by `cer_parallel_span` ascending**. So `[:40]` is not
a sample, it is **the 40 easiest pages**: median gold CER 0.232, capped at 0.297, versus
0.462 for the other 62. Both models degrade on the full set; the tuned model degrades more,
which is exactly the profile of a model whose edge is on clean pages.

**Every 40-page number this project produced before 2026-08-08 was scored on that easy head**
— the tuned-student bakeoff, the `ref_recall` subset, the Azure/GPT-5.x comparison, the
layout-first run. **Absolute CERs from those runs are roughly 2× optimistic.** Within-run
**rankings survive**, because all arms shared the same pages and were compared paired — which
is why the layout-first conclusion (+46% effective yield) still stands as a direction even
though its absolute numbers do not generalize.

Both harnesses now subsample **evenly across the difficulty-sorted file** instead of slicing
the head (verified: median gold CER 0.363 vs the full set's 0.364, spanning 0.070–0.710).

### What to do with it

Keep the tuned pro, but for **throughput, not accuracy**: it matches 3.1-pro's effective
yield while running on 2.5-pro quota, and the corpus run was quota-limited on the 3.1-pro
*preview* endpoint (24 workers bought almost nothing over 12). It also stays
ensemble-complementary — higher recall, more tokens emitted — which is the right second
draft to pair with 3.1-pro's precision. Checkpoints improved monotonically through epoch 6
(0.285 → 0.266 → 0.225 on the easy subset) with no upturn, so more epochs is still live.

## 2026-08-08 — the ensemble works; layout-first's headline does not survive

Three arms over all 102 gold pairs, 0 errors, layout held fixed across arms (computed once
per page, same regions to both readers), each reader on its own best prompt.

| Arm | CER ↓ | recall ↑ | **yield** ↑ |
|---|---|---|---|
| 3.1-pro layout-first | 0.406 | 0.715 | 0.415 |
| tuned-2.5-pro layout-first | 0.403 | 0.793 | 0.443 |
| **ensemble (both + adjudication)** | **0.310** | 0.737 | **0.448** |

Paired, which is the only honest read:

| Comparison | Δyield | sign test | Δ CER | Δ recall |
|---|---|---|---|---|
| ensemble vs 3.1-pro | **+0.013** | 65/94, **p=0.0003** | −0.023 (wins 67) | 0.000 (wins 22) |
| ensemble vs tuned-pro | **+0.011** | 63/99, **p=0.0086** | −0.029 (wins 76) | 0.000 (wins 19) |
| tuned-pro vs 3.1-pro | +0.002 | 53/100, p=0.62 | +0.005 | 0.000 |

**1. Adjudication is real, and it works the opposite way to the hypothesis.** The bet was that
the judge would recover passages only the high-recall reader found. It does not: recall barely
moves (median Δ 0.000, ensemble recall 0.737 is *below* tuned-pro's 0.793). What it does is
**fix wording** — CER drops 0.023–0.029 and the ensemble wins CER on 67–76% of pages. The judge
is conservative: it arbitrates disagreements rather than unioning content. Statistically solid,
practically small (~3% relative yield). The gain is concentrated where there is something to
adjudicate: **+0.021 on the 92 cropped pages (wins 61/91), +0.000 on the 10 uncropped ones.**

**2. Under layout-first, the tuned model's edge over 3.1-pro disappears** (p=0.62, 53/100).
Its only real advantage was recall, and cropping supplies recall structurally — so the two are
**substitutes, not complements**. Keep tuned-2.5-pro for quota/throughput, not accuracy.

**3. ⚠️ Layout-first itself does not beat whole-page on representative pages.** Paired against
the whole-page 3.1-pro numbers on the same 97 pages: **median yield delta −0.0035, layout-first
wins only 43/97** — a coin flip, arguably a slight loss. The earlier **+46% effective yield**
claim was measured on the easy 40-page head (see the sampling entry above). *Caveat: this
particular comparison is cross-run and the two arms used different prompts, so it is suggestive,
not decisive — but it is more than enough to retire the +46% number.*

**Settled below — the clean test ran and layout-first is not an accuracy lever.**

**The honest summary of the whole sweep:** measured on difficulty-representative pages, every
headline gain shrinks to 1–3%. The corpus method is roughly where it was; adjudication is the
one lever that survives contact with a fair sample.

## 2026-08-08 (settled) — layout-first is a ROBUSTNESS lever, not an accuracy one

The clean test: all 102 gold pages, whole-page vs layout-first, **same prompt, same backend
(3.1-pro), same pages** — the only variable is cropping. No confound left.

**Paired on the 94 pages both arms scored: median yield delta −0.0035, layout-first wins
41/91, sign test p=1.0.** A dead coin flip. The **+46% claim is definitively retired** — it
was an artifact of the easy 40-page head.

**But layout-first never loses, and it rescues outright failures.** Whole-page produced no
scoreable output at all on **8 of 102 pages** (129, 553, 668, 831, 851, 1330, 1344, 1578);
layout-first scored **all 102**, and those 8 came in at a respectable 0.342 median yield.
Layout-first failed on **zero** pages where whole-page succeeded. Counting failures as yield 0
— the deployment-relevant view — median yield goes 0.376 → 0.406, still p=1.0 on the median
but with ~8% of the corpus moving from nothing to a usable read.

**Cost: 91/102 pages get cropped at a median of 8 regions, so layout-first spends ~11 calls
per page (3 layout votes + 8 region reads) against whole-page's 1.**

### Production shape this implies

**Do not make layout-first the default, and do not re-run the corpus for it** — that is ~11×
the calls for zero median accuracy gain.

**Use it as a FALLBACK:** read whole-page (1 call); if the output is empty, short, or fails
its sanity check, re-read that page layout-first. That buys the entire 8% rescue at roughly 8%
of the cost instead of 11× on every page. Adjudication stays an optional accuracy top-up
(+3% yield, and it only pays on multi-region pages).

## 2026-08-08 — thinking tokens were 90% of the bill, and buying them changed nothing

Six configurations over all 102 gold pages, one whole-page call each, identical prompt and
render. Cost is **measured from each response's `usageMetadata`** at published Vertex list
price, not extrapolated. Only the model and `thinkingConfig.thinkingLevel` vary.

| Arm | CER ↓ | recall ↑ | yield ↑ | out tok | $/page | **63k pages** | vs pro-default |
|---|---|---|---|---|---|---|---|
| pro-default | 0.302 | 0.768 | 0.468 | 11,736 | $0.1433 | **$9,030** | — |
| **pro-low** | 0.361 | 0.786 | 0.460 | **1,130** | **$0.0161** | **$1,012** | **indistinguishable (p=0.53)** |
| flash-low | 0.357 | 0.781 | 0.461 | 1,471 | $0.0129 | $813 | worse (p=7e-7) |
| flash-default | 0.429 | 0.736 | 0.421 | 5,651 | $0.0443 | $2,788 | worse (p=1e-8) |
| lite-minimal | 0.418 | 0.789 | 0.436 | 1,064 | $0.0019 | $120 | worse (p=6e-7) |
| lite-default | 0.430 | 0.775 | 0.435 | 1,066 | $0.0019 | $120 | worse (p=8e-9) |

**`thinking_level: "low"` on 3.1-pro cuts output tokens 10× (11,736 → 1,130) and cost 9×,
and the paired yield difference is −0.0012 on 93 pages, 43 wins, p=0.53. Statistically
indistinguishable.** Recall is unchanged (p=0.68); CER is marginally worse (better on 37/94,
p=0.049), but the composite is a wash because recall holds. **~90% of what this project was
paying for was reasoning that did not improve the read.**

**Cheaper models are NOT a wash — they are significantly worse**, despite median yields that
look close. flash-low's median yield (0.461) even edges pro-low's (0.460), yet head to head
**pro-low beats flash-low on 73/94 pages, p=7e-8.** Comparing medians of separate
distributions would have picked the wrong model; only the paired test shows it.

**Recommended production config: `gemini-3.1-pro-preview` at `thinkingLevel: "low"`.**
$1,012 for the remaining 63,000 pages, or **~$1,900 with the layout-first fallback on the 8%
that fail** — against $9,030 at default thinking for no measurable quality gain.

⚠️ **Harness bug found and fixed while reading these results:** the sign test summed only the
upper tail, so arms that *lost* most pages returned p=1.0 and read as "no difference". Every
cheap arm above was initially mis-reported as indistinguishable. Fixed to a proper two-sided
test that also reports direction. **Any earlier p-value from this harness that claimed "no
difference" should be re-derived from the win counts, which were always recorded.**

## 2026-08-08 — routing to cheap models is dead; batch mode is the last real lever

**Question asked: is there a subset of pages where a cheap model is good enough, so we can
route?** Tested against the 102-page results. **No, on three independent counts:**

1. **The subset is small.** `flash-lite` matches or beats `pro-low` on only **20/96 pages
   (21%)**; `flash-low` on 21/96. There is no large easy-page population to harvest.
2. **The ceiling is trivial.** An **oracle router with perfect foresight** — pick the cheapest
   arm that ties pro-low on every page — costs $804 for 63k against $1,012. **It saves $209.**
   Allowing a 0.02 yield give-back gets it to $624, saving $388. That is the unbuildable upper
   bound; a real router captures a fraction of it.
3. **There is no signal to route on.** Pages where cheap was enough vs where it wasn't are
   indistinguishable on every runtime-observable feature: cheap-model output 1,118 vs 1,198
   tokens, 633 vs 651 normalised words. Nothing separates them *before* you know the answer.

A cascade is worse than the oracle, not better: you pay the cheap call on all 63k pages and
still escalate ~79% of them, netting ~$95. **Rejected.**

### What does work

| Lever | Saving | Note |
|---|---|---|
| **Batch/flex mode** | **$506 (50%)** | Flat 50% off input *and* output. This is an offline bulk job — exactly the workload batch exists for. Biggest remaining lever, and it is a runner change, not a quality change. |
| Blank-page skip | $15 | 3.0% of pages measured blank on adl0616 (53/1,787). Detectable locally from image statistics at **zero API cost**. Money is trivial; the point is keeping junk out of the corpus. |
| Skip already-read pages | — | ~8,587 pages are already transcribed. Don't re-read them. |
| `thinkingLevel: "minimal"` on pro | ~$250 if it works | **UNTESTED.** Docs suggest `minimal` may be Flash-only. Worth a ~$5 probe, not an assumption. |

**Stacked (batch + blank-skip + layout fallback on the 8%): ~$923 all-in**, of which $432 is
the fallback, against **$9,030** for the naive online default-thinking read.

**Then stop.** The whole job is now ~$500–900. Further optimisation is worth a few hundred
dollars against engineering time and the risk of breaking something that measures correctly.

### Built and verified 2026-08-08 (`siraj/corpus_batch.py`)

**Batch works.** `gemini-3.1-pro-preview` at `thinkingLevel: low`, submitted to
`locations/global` — 3.x publisher models exist nowhere else, and a regional submit 404s with
*"The PublisherModel gemini-3.1-pro-preview does not exist."* Images go in as `fileData`
`gs://` URIs, not inline base64; at 63k pages inlining would mean ~30GB of JSONL.

Validated end to end on a real 60-page slice: **60 unique rows, 0 empty, median 3,458 chars
against the original multi-draft pipeline's 3,428, $0.51 = $0.0085/page → ~$536 for 63k.**

Runner is resumable, chunks into 2,000-page jobs, and recovers page numbers from the echoed
image URI rather than output line order (batch does not preserve global ordering).

**Two negative results, recorded so nobody retries them:**
- **`thinkingLevel: "minimal"` is rejected by Pro** — HTTP 400 on all 102 pages,
  *"thinking_level MINIMAL is not supported by this model."* `low` is the floor. 4xx is not
  billed, so the probe cost nothing.
- **Blank-page prefiltering does not work here.** These blanks are *dark scans*, not white
  paper: blank pages carry **more** ink than text pages (median 0.510 vs 0.309), so the obvious
  darkness rule is backwards. The best structural feature (Laplacian edge energy) catches only
  **30% of blanks** at zero risk of dropping a real page — worth about **$4**. Not built. The
  model returns `[BLANK PAGE]` reliably; pay the $15.

**Prerequisite still open:** the runner needs the ADL catalogue (`adl_catalog_full.tsv`, 581
rows) to enumerate books. It is not on this VM or in the local repos — it lives with the
original `bd-agent/hyde-transcription/afghan-htr` work. Source it before a full-corpus run.

## 2026-08-08 — text-only linguistic correction: works, but must run on demand, not over the corpus

Never tested before. Prior adjudication was IMAGE-grounded arbitration between two drafts; this
is one transcription, no image, corrected purely from knowledge of Persian. Four arms over the
102 gold pages, scored on two axes because CER alone would reward the failure mode: a corrector
that modernises 1911 orthography moves *toward* the modern edition and *away* from the page.

| Level | Δyield | wins | p | ΔCER | **false-corr** | notes |
|---|---|---|---|---|---|---|
| L1 flagged-only | +0.0000 | 2/3 | 1.0 | 0.0000 | **0.00%** | no-op: the reader emits `[word?]` so rarely there is nothing to fix |
| **L2 conservative** | +0.0011 | 73/93 | **2.9e-08** | −0.0013 | **0.29%** | real and near damage-free, but tiny |
| **L3 fluent** | **+0.0099** | 82/97 | **2.4e-12** | −0.0080 | **3.07%** | 9× the gain, 10× the damage |
| L2 on flash-lite | +0.0000 | 43/88 | 0.92 | 0.0000 | 0.52% | coin flip, and *more* damage than Pro |

**1. It works.** Both Pro levels beat raw on a large majority of pages at overwhelming
significance. The gains are small in absolute terms but they are unambiguously real.

**2. The cheap model fails here too — my hypothesis was wrong.** I expected text-only correction
to be an easier task than reading images, so that flash-lite might suffice. It does not: a coin
flip on quality (43/88, p=0.92) while causing nearly twice Pro's false corrections. The
"don't substitute a cheap model" finding survives a change of task.

**3. The economics decide the architecture.** A correction pass costs **more than double the
read it corrects** — $0.021/page (L2) or $0.018/page (L3) against $0.0086 for the read itself,
because output tokens dominate and correction regenerates the whole page. Over 59.5k pages that
is **$1,093–1,249 to buy ~+0.01 yield**, on top of a corpus read projected at ~$510 total.
(That $510 is the projection at the online rate used throughout this comparison. The read was
actually run as a batch job at roughly half that rate and came in at **$288** — see the site's
methods page. Both numbers are right; they are on different bases.)

**Never batch-correct the corpus. Correct on demand, per page, when a reader asks for it.**
$0.02 is nothing for one person viewing one page and ruinous across 59,500.

### How this maps to the search UI

- **"As printed" (raw) — default, and the citable layer.** Free, already computed. This is the
  transcription of record; nothing silently rewrites it.
- **L2 in the search INDEX, not the UI.** Damage-free (0.29%) and significant, so fold it into
  indexed text where a hallucinated character costs nothing. Not worth a user-facing switch.
- **"AI reading" (L3) — opt-in, per page, generated on demand, labelled with its 3% figure.**
  This is the rung worth exposing. It also lifts recall most (0.802 vs 0.776), which is what
  makes a page findable.

⚠️ **Limit of the false-correction metric:** "correct" means "agreed with the modern edition", so
some of L3's 3% may be fixing genuine OCR errors on pages where the edition itself diverges from
the lithograph (the recension gap). It measures divergence from the edition-agreeing baseline,
not ground truth about the page. Separating the two needs image-grounded verification.

## Caveats (honest)
- Absolute lithograph CER (0.26–0.67) is inflated by the **Iranian-canon vs Kabul-lithograph
  recension gap** (~0.19 floor measured earlier) plus a generic prompt — the **cross-model
  RANKING**, consistent across all three benchmarks, is the decision-relevant signal, not the
  absolute numbers.
- Samples n=40–60; CER on whitespace-normalized text. Raw per-page results in `work/bench_*.jsonl`.
- Cost: ~$20 of donated cloud credits total, $0 cash. Benchmarks ran on VM `eel-compute` (stop when idle).
