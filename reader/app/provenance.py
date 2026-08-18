"""What produced the text, how well it was measured, and under what terms it can be reused.

A library cannot ingest an unlabelled machine text layer. It needs to know which model read
the page, against what the reading was scored, and what the score actually means -- and it
needs those to be the real numbers, because the first person to check will be a subject
specialist with the page open beside them.

Every figure below is traceable to ../../RESULTS.md and ../../GOLD_SOURCES.md. Two rules were
applied while writing it:

  1. A benchmark on a DIFFERENT corpus is never reported as this corpus's accuracy. The model
     reads human-transcribed Persian nastaliq MANUSCRIPTS at ~93% of characters; that is a
     ceiling indication, not a measurement of these lithographs, and it is labelled as such.
  2. The headline number is the one measured on the configuration actually deployed
     (gemini-3.1-pro-preview at thinkingLevel "low"), on a difficulty-representative sample --
     not the easiest pages. RESULTS.md records that every pre-2026-08-08 40-page figure was
     scored on a sorted head and is roughly 2x optimistic.
"""

CORPUS = {
    "pages": 69624,
    "books": 580,
    "blank_pages": 4033,          # pages the reader returned as [BLANK PAGE]
    "read_completed": "2026-08-09",
}

METHOD = {
    "model": "gemini-3.1-pro-preview",
    "thinking_level": "low",
    "platform": "Google Vertex AI batch prediction, locations/global",
    "pass_structure": "single whole-page read per page",
    "prompt": "generic Perso-Arabic transcription prompt; transcribe in the original script, "
              "no translation, no normalisation",
    "why_this_model": "Measured against independent gold, model choice is script-dependent and "
                      "the ranking flips between clean naskh type and the nastaliq these "
                      "lithographs use. On nastaliq, Gemini 3.x wins decisively and "
                      "gemini-2.5-flash is the worst reader tested. thinkingLevel low was "
                      "chosen because it is statistically indistinguishable from default "
                      "thinking (paired delta -0.0012, p=0.53) at one ninth the cost.",
}

# ---------------------------------------------------------------------------------------------
# Accuracy. The honest version is uncomfortable and is published anyway.
#
# There is NO page-level human transcription of the ADL's own lithographs -- we looked, and
# GOLD_SOURCES.md records the search. So this corpus cannot be scored the way an OCR project
# normally is. The nearest available reference is a modern printed edition of the same text:
# Tarzi's own articles, reset in 2008, aligned page to page against the Siraj al-akhbar
# lithograph. That reference disagrees with the Kabul printing for reasons that have nothing to
# do with misreading -- normalised spelling, added punctuation, different line breaks.
#
# TWO GOLD SETS EXIST AND MUST NOT BE CONFLATED. The 102 aligned pairs that produce the headline
# number are adl0616 against the Farhadi edition. The ~0.19 recension floor was measured on a
# different pairing entirely (adl0294, Sa'di's Bustan, against the Ganjoor canonical text).
# Carrying the floor from one to the other is an analogy and is labelled as such below; an
# earlier version of this file silently welded the Bustan reference onto the adl0616 sample.
#
# So the number below is a LOWER BOUND on reading quality, and the true figure sits somewhere
# between it and the manuscript benchmark. We do not know where, and we say so.
ACCURACY = {
    "headline": "Roughly two thirds of characters agree with a modern printed edition of the "
                "same text. Much of the disagreement is editorial, not misreading. Treat the "
                "transcription as a finding aid and read the page image before quoting.",
    "primary_measurement": {
        "what": "Character error rate against a modern printed edition, aligned page to page",
        "reference": "Maqalat-e Tarzi, 2008 Farhadi typeset edition, aligned against ADL "
                     "adl0616 (Siraj al-akhbar) -- the same author and text in modern type",
        "sample": "102 aligned gold pages, sampled evenly across the difficulty distribution",
        "config": "gemini-3.1-pro-preview, thinkingLevel low (the deployed configuration)",
        "cer_median": 0.361,
        "reference_recall_median": 0.786,
        # 1-CER is deliberately not published as "characters correct". CER counts
        # substitutions, deletions AND insertions over the reference length, so it can exceed 1
        # and its complement is not a proportion of correctly classified characters. This is
        # also a median over sampled pages, not a character-weighted rate over the corpus.
        "cer_note": "Report this as a character error rate, not as an accuracy percentage. "
                    "1 - CER is not a literal proportion of characters read correctly, and "
                    "this is a per-page median rather than a corpus-wide rate.",
        "caveat": "The 2008 edition normalises spelling and adds punctuation, so part of this "
                  "error is editorial distance rather than misreading. A floor of about 0.19 "
                  "CER was measured for that effect -- but on a DIFFERENT pairing (Sa'di's "
                  "Bustan, ADL adl0294, against the Ganjoor canonical text), so applying it "
                  "here is an analogy, not a measurement. Subtracting it entirely would imply "
                  "about 83% character accuracy. Nobody has verified that.",
    },
    "secondary_gold_set": {
        "what": "An earlier, separate gold set, listed so the two are not confused",
        "reference": "Sa'di, Bustan, Ganjoor canonical text, aligned to ADL adl0294",
        "sample": "331 aligned pages, 92% page-align rate",
        "note": "This is where the ~0.19 recension floor was measured. Classical verse against "
                "an Iranian canonical text, not journalism against its own author's reprint.",
    },
    # Two secondary figures. Both are real, both are on easier material than the corpus average,
    # and neither is this corpus's accuracy. They are published because the primary number above
    # is a lower bound and it would be equally dishonest to let it stand alone.
    "against_human_transcription": {
        "what": "Character error rate against passages a scholar transcribed directly from the "
                "page -- the only true page-level human gold this project has",
        "sample": "3 passages of Anis",
        "cer": 0.07,
        "caveat": "THREE PASSAGES, from a newspaper of the 1940s. That is later letterpress, "
                  "not the 1871-1930 lithography that makes up most of this collection, and it "
                  "is the easiest material in the corpus. n=3 is an indication, not a "
                  "measurement, and this figure was previously published as though it were the "
                  "accuracy of the whole archive. It is not.",
    },
    "model_ceiling_on_nastaliq": {
        "what": "The same model family on human-transcribed Persian nastaliq, to show what the "
                "reader is capable of where real ground truth exists",
        "reference": "OpenITI MAKHZAN, line-level ALTO human transcription "
                     "(doi:10.5281/zenodo.19861912, CC-BY-NC-SA)",
        "sample": "40 nastaliq pages",
        "cer_median": 0.074,
        "caveat": "MANUSCRIPT pages, not these lithographs. What the model can do on nastaliq "
                  "when gold exists. NOT this corpus's accuracy.",
    },
    "no_human_gold": "No page-level human transcription of the Afghanistan Digital Library's "
                     "lithographs is known to exist. If your institution holds one, even a few "
                     "pages, it would let this corpus be scored properly for the first time.",
    "search_recall": {"long_quote_top20": 0.814, "long_quote_rank1": 0.57,
                      "short_phrase_top20": 0.598, "short_phrase_rank1": 0.21,
                      "note": "Whether the right page appears in the first 20 results, over the "
                              "full 69,624-page index. The query was a VERBATIM sentence lifted "
                              "from a printed edition, which is an easier condition than a "
                              "scholar's remembered wording. Subject (semantic) search has "
                              "never been evaluated for thematic relevance at all."},
    "source": "https://afghanpress.org/about.html",
}

LIMITS = [
    "The transcription is a finding aid, not an edition. Do not quote from it without checking "
    "the page image.",
    "Accuracy varies sharply by page. Dense newspaper type reads far worse than clean literary "
    "type, and no per-page confidence was recorded during the corpus run.",
    "4,033 of 69,624 pages were returned as blank by the reader. Some of those are genuinely "
    "blank; a false blank has not been separately measured.",
    "Marginalia, tables, running heads and figure captions are read in whatever order the model "
    "emitted them. There is no layout model behind this text and no word coordinates.",
    "Persian and Pashto are not distinguished per page.",
]


def page_record(book: str, page: int, has_correction: bool = False) -> dict:
    """Provenance as it attaches to one page.

    Deliberately does not invent a per-page confidence. The corpus run recorded token counts,
    not a calibrated score, and a made-up number here would be worse than none: it would be
    trusted."""
    return {
        "text_produced_by": METHOD["model"],
        "thinking_level": METHOD["thinking_level"],
        "read_completed": CORPUS["read_completed"],
        "per_page_confidence": None,
        "per_page_confidence_note": "Not recorded during the corpus run. No calibrated "
                                    "per-page score exists, and none is estimated here.",
        "human_reviewed": bool(has_correction),
        "accuracy_context": ACCURACY["headline"],
        "primary_source": "The page image. The text is an index into it.",
    }
