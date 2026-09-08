# Review Gate Report

**Changes made:**
- Drafted the JOHD_DESCRIPTOR.md detailing the existing CER (0.36 vs modern edition, 0.068 on human passages) and the missing 30-50 pages.
- Quoted NYU's rights statement verbatim from the Afghanistan Digital Library website.
- Fixed the "7% accuracy figure" wording to "7% error figure" in the about page.

**Numbers before/after:**
- Wording error: "7% accuracy figure" -> "7% error figure"

**Commits:**
- docs: draft JOHD descriptor and fix about page accuracy/error typo

**Gate scores and TOP3:**
- gemini-3.1-pro-preview: Score 1. TOP3: Finalize the dataset and deposit it in a repository with a DOI; Create the 30-50 page ground truth to enable valid page-level evaluation; Remove the mathematically invalid CER floor comparison against the modernized text and report true CER/WER.
- gpt-5.6-sol: Score 1. TOP3: Release a versioned citable dataset with licenses and complete documentation; create a representative stratified human ground-truth benchmark and report uncertainty; replace the invalid CER-floor argument with reproducible corpus-specific evaluation

**Favours the author:**
- gemini: 2 of 3
- gpt: 13 of 18

**Verdict:**
OPEN. Blocked by missing ground-truth benchmark, invalid evaluation, and unminted DOI dataset release.
**Named Venue:** Journal of Open Humanities Data
