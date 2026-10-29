# Transparent opportunity ranking

Migration layout: the skill is at Canary root in `.agents/skills/`; run its commands from `<Canary root>/marketing`. Treat that directory as `ROOT`, and paths below as relative to it unless explicitly marked Canary-root-relative. Canary is its parent directory and is read-only to marketing workflows.


The weights and recency steps come from `/Users/jbuiles/Code/falbor/apps/falbor/app/lib/automation/prompts.ts:4-12,47-71`, read directly. Adapted from Falbor, copyright (c) 2026 Falbor, under its default AGPL-3.0 source license. Trademarks are excluded. This local private-use adaptation does not imply a permissive license or endorsement. These are prioritization heuristics, not measured conversion probabilities. The anchors below are this workspace's explicit judgment rubric.

Choose 0, 25, 50, 75, or 100 for each judgment factor. Cite the actual thread or rules excerpt that supports it. Interpolate only with an explicit explanation. Unknown evidence is an uncertainty flag, not a zero score. Do not fabricate a factor to force a total. Keep an unscorable candidate in the run report until evidence is available rather than inventing `Opportunity.relevance`.

| Factor | Weight | 0 | 50 | 100 |
| --- | --- | --- | --- | --- |
| problemRelevance | .25 | Unrelated problem | Adjacent visual-story problem | Explicit novel-to-comic adaptation problem |
| audienceRelevance | .15 | Audience is unrelated | Mixed audience with some writers | Author, indie novelist, or small comics studio asking directly |
| productFit | .20 | Requires unsupported capability | Partly supported with material limitations | Current marketable ledger entries directly address the stated task |
| intentSignal | .15 | No question or need | Exploring approaches | Explicit request for a workflow or tool recommendation |
| communityFit | .10 | Rules bar the reply | Helpful reply allowed, product promotion restricted | Rules allow the proposed disclosed reply and its exact content |
| participationValue | .05 | Repeats existing answers | Adds a concrete useful step | Resolves an unanswered question with specific actionable guidance |

Use 25 between the 0 and 50 descriptions, and 75 between 50 and 100. A rules ban still requires skipping, even if other factors are high.

Recency contributes .10. Compute exact elapsed days in UTC, without rounding before bucket selection.

| Age in days | Score |
| --- | --- |
| Up to 3 | 100 |
| More than 3, up to 7 | 85 |
| More than 7, up to 14 | 70 |
| More than 14, up to 30 | 55 |
| More than 30, up to 60 | 35 |
| More than 60, up to 90 | 20 |
| More than 90 | 5 |
| Unknown | 40, a disclosed fallback only |

`relevance = round(.25*problemRelevance + .15*audienceRelevance + .20*productFit + .15*intentSignal + .10*recency + .10*communityFit + .05*participationValue)`.

The weights sum to 1. The scorer rejects future dates and invalid factors. For date-only values, it uses UTC midnight. Rank descending, break ties by participation value, then newer verified date, then URL alphabetically. The threshold of 55 is a shortlist rule, not an expected success rate.

## Verify the scorer

`score.ts` reads one JSON argument and writes `{ageDays, recency, relevance}`. The input has `postedAt`, an ISO date or offset timestamp or null, optional ISO date `today`, and the six integer factors. A missing `today` uses the actual current time. Bad input exits nonzero without a score. Unknown age is emitted as `"unknown"`.

Run the bundled CLI tests from any working directory after setting `ROOT` and `SKILL` to absolute paths:

```sh
CANARY_ROOT=/absolute/path/to/canary
ROOT="$CANARY_ROOT/marketing"
SKILL="$CANARY_ROOT/.agents/skills/community-scan"
node "$SKILL/verify-score.mjs" "$ROOT"
```

For an isolated staging tree, point `SKILL` to that staged community-scan directory while keeping `ROOT` pointed to the installed workspace. The test runner sets `NODE_PATH` to `ROOT/node_modules` so the staged CLI can resolve Zod. It does not install packages or write to `ROOT`.
