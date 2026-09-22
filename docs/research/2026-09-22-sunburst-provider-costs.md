# Sunburst provider cost comparison

Status: Historical investigation snapshot, checked 2026-09-22. Published rates,
local artifacts, and authenticated dashboard evidence are distinguished below.

## Actual recent costs

The authenticated FAL dashboard shows four recent Sunburst edit charges
totaling **$0.2161**, averaging **$0.054025 per page**:

| Sep 22 local time | FAL request ID | Actual USD | Local fallback estimate USD |
| --- | --- | ---: | ---: |
| 10:22 | 01a0c97e-92a9-7522-97dc-1ba0198f090e | 0.0396 | 0.27 |
| 10:23 | 01a0c97f-8fe1-7f30-9c7c-5c7ebf315154 | 0.0672 | 0.30 |
| 10:24 | 01a0c980-9a42-7b61-855f-8fde53fc8435 | 0.0500 | 0.28 |
| 10:25 | 01a0c981-9ef5-73c1-be3a-fbfa5cf610ef | 0.0593 | 0.29 |

These are a chronology-based match to Dungeon Crawler Carl page 1–4 provenance
timestamps 14:22:15, 14:23:33, 14:24:46, and 14:25:44 UTC, not a request-ID
join: local artifacts have no provider request IDs. They record respectively
2, 5, 3, and 4 references, 1024×1536 dimensions, configured medium quality,
zero token usage, and `cost_source=capability_profile`. Their $1.14 combined
local estimate is about 5.3 times the matched dashboard charges.

An earlier 10:19 request, `01a0c97b-6cf9-7490-be9d-aec486ef512e`, cost $0.0820
and chronologically aligns with the failed generation. The dashboard showed
21 edit billing results. Current-cycle totals were $0.7744 for edit and
$0.1420 for text-to-image, totaling $0.9164 (displayed rounded as $0.92).
The displayed $1 unit price is per abstract billing unit, not per image.
The latest request detail confirmed $0.0593 but its input panel showed `{}`,
so it did not independently establish the delivered quality parameter.
[Authenticated FAL edit billing dashboard](https://fal.ai/dashboard/usage-billing/usage/openai/gpt-image-2.5/sunburst/edit?dateRange=current_month)

The available configured FAL key returned HTTP 403 for the read-only usage
API because it lacked billing permission. Authenticated browser access supplied
the evidence above; no API billing records were downloaded.

## Comparison with earlier direct OpenAI pages

Local direct-OpenAI artifacts recorded token counts but null monetary costs.
Reconstructing costs from their tokens and the published rates gives:

| Book | Pages | Mean USD/page | Range USD/page | Total USD |
| --- | ---: | ---: | ---: | ---: |
| The Egg | 22 | 0.07032909 | 0.064201–0.076918 | 1.547240 |
| Cthulhu | 44 | 0.077271 | 0.056327–0.137877 | 3.399924 |

These are token-based reconstructions, not retrieved OpenAI invoices. The old
direct Draw path forced high quality even when configuration said medium;
the recorded output was 1,372 tokens per page. The four matched recent FAL
charges average less than either earlier book. Whole-book startup also includes
style/reference assets and cover work, and the failed request adds spend
without a usable page. Comparing an account total with an individual page
therefore obscures the cost of the page itself.

Dungeon Crawler Carl's local completed medium-quality manifests include six
style samples, seven character references, six location plates, two prop
references, and one cover. The remaining cycle charges total $0.6183 after
subtracting the four matched pages and likely failed attempt, but there is no
exact request-ID attribution proving those charges map to those assets.
Visual inspection of page 2 found legible integrated captions and detailed
pixel art; it was not a controlled comparison between low and medium quality,
and no quality/review state was changed.

## Published rates

Direct OpenAI `gpt-image-2.5-sunburst` and FAL
`openai/gpt-image-2.5/sunburst` publish matching token rates:

| Token category | USD per million |
| --- | ---: |
| Text input | 5.00 |
| Cached text input | 1.25 |
| Image input | 8.00 |
| Cached image input | 2.00 |
| Image output | 30.00 |

There is no published FAL premium in these rates. OpenAI says text output is
not billed. FAL's endpoint page lists a text-output rate, while its model
overview says there is no text-output charge; actual usage must resolve any
material discrepancy. Sources: [OpenAI model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst),
[FAL endpoint](https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image),
[FAL overview](https://fal.ai/gpt-image-2.5).

## Quality is the largest output-cost control

FAL's published 1024×1536 portrait output table:

| Quality | USD image output |
| --- | ---: |
| low | 0.00474 |
| medium | 0.01029 |
| high | 0.04116 |
| xhigh | 0.07377 |
| max | 0.16464 |

Medium reduces output cost 75% versus high. Low saves a further $0.00555.
These are output costs; prompts and references are additional. FAL rounds
the request total upward to $0.0001. [FAL endpoint pricing](https://fal.ai/models/openai/gpt-image-2.5/sunburst/text-to-image)

FAL's edit schema defaults to `quality=high`, `num_images=1`, and
`image_size=auto`; custom dimensions use a width/height object. It accepts
up to 16 reference images. Explicit settings avoid relying on those defaults.
[FAL edit API](https://fal.ai/models/openai/gpt-image-2.5/sunburst/edit/api)

OpenAI recommends low for drafts and evaluating higher levels for final
assets. Actual token consumption depends on the model, size, and quality;
`auto` cannot provide a fixed estimate. Responses API calls also incur the
main model's tokens. [OpenAI generation guide](https://developers.openai.com/api/docs/guides/image-generation)

## Inputs and practical recommendation

FAL reports about $0.008 additional input cost for one 1024×1024 reference,
about $0.012 for a 3840×2160 reference, with more references adding more
cost. Its example table uses a short prompt and one reference; it is not a
full comic-page workload estimate. Flare and Sunburst have identical published
prices; choosing Flare mainly targets speed, not guaranteed savings.
[FAL overview](https://fal.ai/gpt-image-2.5)

Recommendation (inference): evaluate explicit medium at the existing portrait
dimensions as the first cost-focused candidate. Retain required identity and
continuity references. Measure prompt and image-input usage before prioritizing
further output reductions: 10,000 uncached text tokens cost $0.05, and several
references can exceed medium's entire output cost. Avoid max/xhigh unless a
visual comparison shows a material benefit.

The dashboard evidence does not show an increase in comparable recent page
costs. It does not establish the delivered quality or fully attribute every
cycle charge. Published prices alone do not demonstrate comic quality or prove
that a lower setting preserves lettering and identity. Keep explicit medium
and 1024×1536 as the cost-focused baseline, preserving required references.
Moving to low would save only about $0.56 in output costs per 100 pages.

Recommended accounting repair: persist FAL request IDs and real usage/charges
when available, and label fallback estimates separately. Do not present the
local $1.14 estimate as the actual charge. This is a recommendation only;
no code/configuration changes or paid generations were made in this investigation.

## Recovering actual FAL charges

The documented Sunburst edit response contains `images`; it does not promise
an inline `usage` field. The separate read-only billing API provides request
charges: `GET https://api.fal.ai/v1/models/billing-events`, authenticated with
an Admin-scoped key in `Authorization: Key ...`. Filter by `request_id`,
`endpoint_id`, and `start`/`end` (at most 90 days). Each billing event has
`cost_subtotal`, `cost_discount`, and `cost_total` in USD;
`cost_estimate_nano_usd` carries that same total in nano-USD. Follow
`next_cursor` while `has_more` is true. These records are the appropriate
comparison with local estimates. [FAL billing API](https://fal.ai/docs/platform-apis/v1/models/billing-events)
