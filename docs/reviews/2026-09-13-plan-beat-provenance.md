# Plan detail: alternating beat ownership failures

Status: Historical — captured failure and provider-free replay on 2026-09-13.

The saved page-42 panel assigned both `lettering_0209` (owned by `beat_0038`)
and `lettering_0210` (owned by `beat_0039`) to panel 1. Initial response
`502b0eb56344` cited only beat 38. Compilation reported the missing beat 39
link, and correction `d030c065b35d` replaced the citation with beat 39. That
then failed for missing beat 38. Destinations and visual intentions were
unchanged. The reported `beat_allocation` label hid this bookkeeping loop.

The detail compiler now derives canonical caption-owner citations from the
author's explicit lettering destinations and combines them with the authored
visual citations. It does not move copy or rewrite visual/continuity intentions.
Foreign visual citations, backward visual sequences, and invalid destinations
remain errors; combined provenance still passes through page-map validation.
Request prompts and schemas were unchanged in this fix, so exact saved requests
remain reusable under current validators.

Read-only replay against the saved adaptation and approved visual inventory:

- Both failing responses pass detail compilation and map allocation checks.
- Latest six batches cover all 44 pages and 195 panels with consistent maps.
- Canonicalization and deterministic full-book validation report zero invariant
  failures. Eight editorial issues remain: five emphasis mismatches, one
  peak/release proportion concern, and two weak page turns.
- No provider requests or project artifact writes were performed. Narrative
  review was not run, so this does not establish narrative acceptance or final
  pipeline completion.

Latest batch response prefixes: `69171acaaa65`, `cb7ce3a35b1d`, `ae74075ab087`,
`82465a457e5f`, `d1ba6d6f8447`, `d030c065b35d`. Full responses remain in the
project's existing Plan response checkpoints. Regression tests cover either
initial visual citation, exact placement preservation, foreign citations, and
backward sequences; they do not claim to measure model quality.
