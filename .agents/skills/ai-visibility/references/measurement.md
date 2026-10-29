# Visibility measurement rules

Migration layout: the skill is at Canary root in `.agents/skills/`; run its commands from `<Canary root>/marketing`. Treat that directory as `ROOT`, and paths below as relative to it unless explicitly marked Canary-root-relative. Canary is its parent directory and is read-only to marketing workflows.


Formula provenance is Falbor's `/Users/jbuiles/Code/falbor/apps/falbor/app/lib/workspace-build/calculations.ts:65-91`, read directly. Adapted from Falbor, copyright (c) 2026 Falbor, under its default AGPL-3.0 source license. Trademarks are excluded. This local private-use adaptation does not imply a permissive license or endorsement.

The following rules deliberately replace Falbor's zero-denominator defaults and permissive understanding calculation. No executable scoring helper is required. Preserve the extraction table and calculate these transparent counts with a calculator or a small read-only code invocation.

## Define the sample

One observation is one successful, full answer to a fixed question from one actual engine in one declared mode. Retries that replace a failed attempt are not extra observations. Keep failures in the attempt log but out of response denominators. A refusal with no substantive answer is a failure for these metrics. A substantive answer that mentions no brands is a valid answer with zero brand mentions.

For each engine, mode, and question cohort, define:

- `N` as successful answers.
- `M` as successful answers whose answer body explicitly mentions Scenewright, at most once per answer.
- `R` as successful answers that explicitly recommend Scenewright.
- `B` as the sum of distinct named software-product brands per successful answer, including Scenewright when present. Count a repeated brand once within one answer. Count it again in another answer. Exclude source-only brands, publishers, and engine branding unless the answer actually discusses them as buyer options.

Use verified alias identity. Record the brand set beside each answer so another reader can reproduce `B`. A mention is not necessarily praise or recommendation. A negative mention still counts in `M` and must retain its context.

## Calculate observable rates

- Mention rate, also called visibility, is `100 * M / N` percent.
- Recommendation rate is `100 * R / N` percent.
- Share of voice is `100 * M / B` percent using the per-answer distinct-brand counting rule above.
- Average explicit recommendation position is the sum of observed numeric ranks divided by the number of answers with an explicit Scenewright rank. Report that ranked-answer count.

If `N` is zero, mention and recommendation rates are unknown. If `B` is zero, share of voice is unknown. If no explicit ranks exist, average position is unknown. Do not silently convert a zero denominator into a zero percentage.

For an optional understanding diagnostic, count only answers that mention the product and make at least one ground-truth-checkable claim. Report `correct checked answers / answers with checkable claims`, along with excluded mention-only answers. All checkable claims in a counted-correct answer must agree with marketable ledger facts. Unknown accuracy flags do not prove understanding. Do not call this metric brand awareness.

## Check the arithmetic

This example is synthetic arithmetic only, never probe evidence. Suppose three successful answers contain the distinct brand sets `{Scenewright, A}`, `{A}`, and `{}`. Suppose one failed request is also logged.

`N = 3`, `M = 1`, and `B = 3`. Mention rate is `1 / 3 = 33.3%`. Share of voice is `1 / 3 = 33.3%`. The failed request contributes to neither denominator. If the successful answers had no brands, `B = 0` and share of voice would be unknown, even though mention rate would be an observed `0 / 3 = 0%`.

## Report limits without fake trends

Always show the raw fraction and successful response count. State requested pairs, successful answers, failures, excluded refusals, exact prompt ids, date, engine, and mode. Separate unbranded discovery from branded understanding and comparison. Separate each engine before any combined summary. Label a combined result as a pooled convenience sample, with its engine weights made visible.

Do not infer customer behavior, market share, search volume, acquisition, or a trend from these rates. Do not use Falbor's question criticality or priority scores as measured demand. Real trend claims require at least two saved dates with comparable question sets, engine versions if known, modes, repetitions, and counting rules. Missing version metadata is a comparability limitation, not permission to invent it.
