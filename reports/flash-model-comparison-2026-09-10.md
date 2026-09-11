# The Flowers: Flash text-model comparison

Scope: recorded Extract, Brief, Style text, Adapt and Plan calls for GLM project 7269c145-b736-438e-bf7d-c31d7c7bdb28 and DeepSeek project bcf06c0e-420e-4dc4-ac28-094df1276d9c. Image generation and OCR excluded. No new generations were run. Based on ai_usage_events and saved project artifacts, retrieved September 10, 2026 local time.

## Result

GLM is the stronger candidate for a controlled follow-up: lower recorded text cost, faster typical calls, and a more restrained final adaptation. DeepSeek had fewer repeated blueprint calls but slower typical completions and some questionable editorial additions. Neither run proves production reliability. Both required repairs during integration, and this was one story with changing prompts/settings.

## Recorded measurements

| Metric | GLM 5.3 Flash | DeepSeek V4.1 Flash |
|---|---:|---:|
| Recorded text cost estimate, USD | $0.056153 | $0.101704 |
| Application call records | 20 | 15 |
| Successful response records | 17 | 13 |
| Failed records | 3 (15%) | 1 (6.7%) |
| Cancelled records | 0 | 1 (6.7%) |
| Failed or cancelled | 15% | 13.3% |
| Median successful-call latency | 22.9 seconds | 90.7 seconds |
| Sum of recorded call latencies, all outcomes | 59.94 minutes | 35.73 minutes |
| Latest successful call per each of 8 features, summed latency | 2.82 minutes | 15.64 minutes |
| Latest successful call per feature, summed estimated cost | $0.015160 | $0.058401 |
| Final planned pages / panels | 6 / 17 | 12 / 30 |
| Approved page target | 4–6 | 12–16 |
| Adaptation beats | 16 | 8 |
| Lettering items / whitespace-separated words | 36 / 518 | 29 / 511 |

Costs are recorded application estimates, not reconciled provider invoices. Null-cost failures/cancellation are excluded from dollar sums, not proven free. DeepSeek's configured rate was higher than some time-dependent provider rates. The latest-success-per-feature calculation is a diagnostic subset, not a measured clean run: it omits earlier attempts and manual recovery, and some selected calls are correction calls. Latencies include application/provider waiting and retries; summed latencies are not wall-clock elapsed project time or pure inference speed.

GLM's failed calls include two setup/routing errors (unknown model alias and no compatible endpoint) and one empty response. Excluding those two setup errors gives 1/18 failed records, 5.6%. DeepSeek has one transport failure (the application reported four underlying attempts) and one cancelled Style call. These are application-call rates, not individual HTTP-attempt rates or validated-output failure rates. Neither Flash run records a text refusal.

Successful API responses can still fail downstream validation. GLM made 7 blueprint calls (6 successful responses, 1 empty response); DeepSeek made 3 blueprint and 3 lettering calls. These counts do not establish exact quality-failure rates: full rejection histories were not retained in the final validation artifacts. Both final Adapt and Plan artifacts have zero blocking invariant failures after repairs. Both Adapt artifacts have one nonblocking omission warning concerning front matter. DeepSeek's protected title was recovered by code, so final validity cannot be credited solely to its raw output.

## Speed interpretation

GLM's typical successful call was about four times faster, but its long tail dominated the experiment: one blueprint took 15.0 minutes, another 13.6 minutes, Style suggestions 11.3 minutes, and a treatment 7.9 minutes. DeepSeek's cancelled Style call consumed 12.3 minutes; its completed Plan call took 5.0 minutes. Both had reasoning configuration changes during the experiment; GLM remained reasoning-enabled and DeepSeek was later disabled. Queueing, gateway changes, restarts, and prompt repairs confound raw speed rankings.

The latest Plan calls were 12.9 seconds GLM versus 299.7 seconds DeepSeek, but DeepSeek planned twice as many pages, so this is not a matched-work benchmark.

## Editorial review of saved artifacts

Both preserve the movement from pastoral innocence to the discovery of remains and the noose, and both retain the original closing line. Both remain heavily caption-driven: approximately 500 words of lettering on a short source. They are closer to illustrated prose than aggressively visual adaptations.

GLM's 16 beats separate the discovery and reveal into finer steps, and its final beat explicitly avoids an explanatory reaction beyond laying down the flowers. It gives the discovery a page-turn role and avoids invented internal dialogue. One weak choice: it uses the full phrase “the tat-de-ta-ta-ta of accompaniment” as an SFX and repeats the motif in narration, making the lettering less natural.

DeepSeek introduces “I wonder who he was.” as a thought, adding explicit interior narration absent from the source and in tension with its own treatment's restraint. It also labels the song as a thought and includes both “YELP!” and narration describing the yelp. Its page 3 overview proposes an autumn memory with Myop's mother, while the canonical staging describes Myop alone in the present woods. The Story Bible has only Myop as a character, so the mother has no canonical character reference. This is a concrete staging/continuity concern even though validation passes.

DeepSeek gives the ending much more room, but pages 9–11 repeat noose, stillness, and flowers before the final gesture. That may create an elegiac pause or feel padded. Its approved 12–16 page target encouraged expansion; it should not be penalized as if asked for GLM's 4–6 pages.

GLM extracted two characters (Myop and the dead man) and two locations; DeepSeek extracted one character and four locations. These choices affect downstream reference and image work, so text-call cost alone is not the total economic comparison. Twelve planned pages imply roughly twice as many initial page renders as six, if using the same image model/settings; actual costs and retries can differ.

## Next comparison

Use identical source, approved brief, protected language, page range, prompts and code revision. Freeze documented reasoning settings, record queue time separately from provider latency, and run each model at least three times. Track provider success, JSON parsing, schema validation, editorial rejection and manual intervention separately. Evaluate blinded text outputs for fidelity, visual storytelling, pacing, continuity and unnecessary narration. Compare total cost per accepted page plan, then downstream image costs separately. Do not count successful HTTP responses as usable-output successes.

Source artifacts: each project's story_bible.json, brief/adaptation_brief.json, adapt/book.json, adapt/validation.json, plan/validation.json and plan/pages/page_*.json under projects/947150d4-7d2f-4726-a018-5539f933ea56/.
