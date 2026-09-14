# Completed Cthulhu plan: quality and stale Draw badges

Status: Historical — snapshot of the completed artifacts inspected September 13, 2026 (Toronto).

Project: `the-call-of-cthulhu`, API ID `a16e7aae-0c91-40e7-9e88-e7afad8e2899`.

## Assessment

The adaptation preserves the investigation's causal chain and the nested-document
structure. The plan is coherent and drawable, but its language is much closer to
an illustrated abridgment than a visually economical comic. This is a creative
assessment of the saved script and staging, not a rendered-artwork assessment.
No new images were generated for this review.

The current artifacts contain 42 adapted beats, 227 lettering items, 44 pages,
and 195 planned panels. The page lettering contains 8,833 whitespace-delimited
words, compared with 11,865 in the supplied source: approximately 74% of the
source's word count. This ratio measures volume, not verbatim copying. Median
page lettering is 197.5 words. Six pages exceed 250 words.

Current Adapt and Plan review receipts pass admission. Independent deterministic
Plan validation reports no invariant failures, including exact lettering
allocation, order, adaptation authority, and approved entity/state references.
All selected reference files exist. The saved Draw edition allows 16 reference
images; its settings take precedence over the current default profile's limit
of eight. Page 44's nine references therefore do not block this edition.
All 44 pages compiled successfully against the saved edition in memory, without
saving requests or contacting an image provider.

## Strong passages

- Pages 3–5 establish the box, relief, manuscript, and shift into Angell's account
  with clear physical objects and document framing.
- Pages 16–18 give the ritual chant and the officers' reaction to the swamp
  spectacle space without needing graphic injury detail.
- Page 33 makes the date correlation an explicit deduction rather than a missing
  causal bridge.
- Pages 39–43 distinguish the opening door, emergence, deaths, pursuit, collision,
  and recombination. Page 40 has two panels and 94 words; page 42 ends before
  impact; page 43 lands the collision and ends with the quiet “That was all.”
  These are specific, useful page-turn and visual staging decisions.

## Remaining editorial concerns

| Location | Evidence | Assessment |
| --- | --- | --- |
| Page 44 | Eight panels, 429 words; three Johansen aftermath panels followed by five testament panels | The ending compresses rescue, return, secret writing, return to Thurston, and the final warning into the book's densest page. This is the highest-value revision. |
| Pages 21–22 | 322 and 308 words, six panels each | Castro's lore remains an extended exposition sequence despite the approved brief asking for economical compression. |
| Pages 9, 10, 13, 20 | Largest panel carries respectively 151, 122, 124, and 145 words | Individual balloons/captions may consume much of the panel's visual space. Actual readability still needs artwork inspection. |
| Pages 13 and 20 | Both explain the same translated chant | Legitimate motif recurrence, but the repeated explanation adds little escalation. |
| Page 7 | Angell speaks clinical observations while the framing identifies Dr. Tobey as intermediary | Small attribution ambiguity; the surrounding captions preserve comprehension. |
| Page 11 | Webb speaks before the following narration introduces him | Minor introduction-order awkwardness, not a broken story. |

A targeted option is to split current page 44 after its third panel: Johansen's
161-word aftermath on one page and Thurston's 268-word testament on the next.
The two groups need three and seven references respectively. This would create
45 pages, one above the advisory target, without changing Adapt's exact lettering.
The final page would still be text-heavy; the split improves space rather than
proving final layout quality. No project artifact was changed to implement it.

The process issue is selection before lettering locks: Adapt preserves a large
volume of source exposition, while Plan must retain every locked word. Plan's
prompts already permit exceeding the target, but this result finishes at 44
with a disproportionately dense coda. Looser narrative reviews remove polishing
loops; they do not themselves improve compression or page-space allocation.
This does not justify restarting the whole adaptation.

## Why undrawn pages showed failure badges

The request journal retains Draw jobs from September 12. The newest historical
failed job per page identifies pages **8, 10, 18, 21, 22, 23, 28, and 32**.
Seven stopped before starting; page 18 was interrupted by server shutdown.
Earlier jobs also include gateway failures, but those are not failures of the
new plan. At the beginning of this inspection the new Draw stage was pending,
with no start timestamp and no current page-failure files.

The Pages UI selected the latest `complete_page_draw` job by page number alone.
Adapt restart archived the old Draw artifacts, but the independent job journal
correctly retained its history. Reusing page numbers made those old failures
appear to belong to the new edition. Terminal-job reconciliation could also
copy these failures into local UI state.

The fix keeps historical jobs and adds `is_current_page` to the jobs API. It is
true only when the job's request hash matches a retained frozen request whose
page revision and content hash match the current page. Pages ignores false
entries both when building page status and when reconciling terminal jobs.
Current failures remain visible. No journal records were deleted, no failed job
was marked successful, and no image request was submitted by this review.

## Verification and limits

Provider-free regression tests cover matching current jobs, changed pages,
missing pages/requests, mismatched requests, preservation of other job types,
and stale failed/running jobs in the UI. Existing current-failure display tests
continue to pass. Frontend build, lint, and documentation reliability pass.
The inspection browser reached a sign-in screen, so live authenticated UI
verification was unavailable; the badge diagnosis is supported by the actual
journal, current artifacts, code path, and UI regression tests.
