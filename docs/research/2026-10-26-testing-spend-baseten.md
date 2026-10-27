# Scenewright testing usage for Baseten

**Status: Observed database evidence, October 26, 2026.** Internal application usage audit for a draft reply to Baseten. These figures describe recorded inference usage costs, not reconciled vendor invoices or cash payments. No email was sent.

## Recommended figures

Use October 1–26, 2026, in America/Toronto. This is a month-to-date window and captures intermittent testing more fairly than presenting the last seven days as a steady run rate.

| Metric | Recorded value |
|---|---:|
| API usage costs with a recorded value | US$114.165431 |
| Days with any recorded testing activity | 18 |
| Average recorded API cost per active testing day | US$6.342524 |
| Days with positive recorded API cost | 17 |
| Average per positive-cost day | US$6.715614 |
| Average per calendar day, including idle days | US$4.390978 |
| Highest recorded API-cost day | US$38.270643 on October 13 |
| Successful calls across API and subscription routes | 3,855 |
| Images recorded across API and subscription routes | 1,259 |
| API-funded image outputs | 588 |
| Codex-subscription image outputs | 671 |
| API calls, including failed and unfinished attempts | 2,823 |
| Codex/Claude subscription calls, including failed and unfinished attempts | 1,227 |
| Successful subscription calls | 1,131 |
| API records with unknown cost | 98 |

All 98 unknown-cost API records are failed (88), cancelled (3), or still marked started (7). There are no successful API records with missing cost in this window. This does not establish that unsuccessful attempts were free.

## Recorded October costs by route

| Route | Recorded cost, USD |
|---|---:|
| Google, including Vertex/Gemini labels | 90.706658 |
| Runware | 6.687697 |
| OpenAI-labelled routes | 10.963049 |
| Other LiteLLM-labelled routes | 4.857006 |
| Anthropic API | 0.554721 |
| FAL-labelled routes | 0.375300 |
| Textract | 0.021000 |
| **Total** | **114.165431** |

The Google and Runware groups represent about 85% of the recorded total. Normalize Runware by the explicit provider, a Runware provider-model prefix, or `cost_source=runware_cost`; many Runware records otherwise retain the generic `litellm` provider label. Do not add gateway spend to these same calls without deduplicating it.

## Cost confidence and subscription treatment

October cost-source totals are:

| Source | Records | Recorded cost, USD |
|---|---:|---:|
| `litellm_usage_cost` | 1,502 | 48.994711 |
| `litellm_response_header` | 635 | 42.655551 |
| `runware_cost` | 210 | 6.687697 |
| `fal_billing_event` | 8 | 0.451200 |
| `litellm_cost_map+canary_pricing_override` | 354 | 15.302972 |
| `request_estimate` | 2 | 0.052300 |
| `configured_document_pages` | 14 | 0.021000 |
| No cost source / unknown cost | 98 | Unknown |

The total mixes gateway/provider cost records and locally calculated estimates. Gateway cost reporting is not an invoice reconciliation. Some provider use may be funded by credits; the application records do not establish cash paid, credit funding, subscription fees, or all Google Cloud infrastructure charges.

Codex and Claude subscription calls are included in workload counts, but excluded from API dollars. Their per-call `cost_usd` values are null, not measured zero. An API-equivalent estimate exists for only 181 subscription calls in October, totalling US$24.6824. It is partial hypothetical pricing, not additional spend, and is not used in the email.

## Wider context

| Period | Recorded API cost, USD | Successful calls, all funding | Images, all funding |
|---|---:|---:|---:|
| July 6–October 26, first recorded use through audit | 280.376188 | 8,792 | 3,532 |
| September 1–October 26 | 183.932960 | 7,037 | 2,716 |
| September 27–October 26, 30 calendar days | 119.381956 | 4,462 | 1,484 |
| October 1–26 | 114.165431 | 3,855 | 1,259 |

The complete query returned 9,557 distinct usage IDs. Of these, 6,263 were API-funded and 3,294 subscription-funded. Cumulative API cost includes US$2.920250 tagged `request_estimate`. The API cost total is a known recorded amount; missing costs and untracked experiments may increase the overall testing cost.

## Earlier named-model experiments

The same snapshot records experiments with GLM, DeepSeek, and MiMo during September. These calls already contribute to the cumulative totals above; do not add them again.

| Recorded model | Attempts | Successful calls | Recorded API cost, USD |
|---|---:|---:|---:|
| `glm-5.3-flash` | 417 | 399 | 2.516609 |
| `deepseek-v4.1-flash` | 108 | 103 | 1.140329 |
| `mimo-v2.6-pro` | 93 | 92 | 1.093813 |
| **Total** | **618** | **594** | **4.750751** |

Those records contain 12,722,378 input tokens and 3,309,706 output tokens. Features include story extraction, adaptation briefs, narrative treatment, adaptation writing and review, page planning and review, character-reference instructions, and translation. This supports describing practical model comparison on Scenewright tasks. It does not establish 594 independent experiments, measured superiority, custom training, or self-hosted deployment.

Across all successful rows in the full snapshot, there are 5,246 text calls, 3,532 image calls, and 14 OCR calls. Model families are named from recorded provider-model values; generic aliases such as `adapt-balanced` are not counted as separate model architectures. No Mammoth-1 calls were found in this application snapshot; its promising evaluation remains founder-reported and is not added to these totals.

The useful framing is cumulative workload and concrete experiments, with the actual recorded cost given alongside them. Subscription calls demonstrate usage, but cannot be revalued as money spent. Current monthly traffic or projected GPU demand cannot be inferred from cumulative testing.

## Method

Read the configured Supabase `public.ai_usage_events` table with read-only, paginated requests. Retrieved usage metadata only: IDs, timestamps, model/provider/funding, status, token and image counts, cost fields, numeric usage details, and an API-equivalent estimate field. No manuscript, prompt, image, credential, or customer-profile content was needed. The snapshot's newest event was `2026-10-26T23:01:37.667174+00:00`.

For each period, convert `created_at` to America/Toronto before selecting dates. Sum non-null `cost_usd` only where `funding=api`, while counting null values separately. All funding sources contribute to activity days. Count calls as successful only where `status=succeeded`; the 1,259 October image outputs all occur on successful rows. Deduplicate by usage-event ID. Do not sum `estimated_cost_usd` into `cost_usd`, treat null subscription costs as cash, or turn API-equivalent estimates into spend.

The Supabase records were sufficient for this reply, so no PostHog fallback was needed. The application database covers instrumented Scenewright calls, not every coding-assistant session or ad hoc experiment run outside the app.

## Suggested reply

Hi Mae,

I pulled the full testing history, including our earlier GLM, DeepSeek, and MiMo experiments. From July 6 through October 26, Scenewright logged roughly 8,800 successful model calls and 3,500 generated images. That includes about 600 successful calls using those three model families for adaptation, page planning, and review.

Recorded API usage costs total about US$280 over that period, including US$115 in October. Some of the testing runs through Codex and Claude subscriptions; their fees aren't included in those figures.

Our recent Mammoth-1 results were very promising, and integrating it into the review pipeline is the next concrete step I'd like to take with Baseten. The program would also help me explore hosting and adapting open models for these workloads as I prepare the product for users.

Best,
Juan
