# Model settings

**Status: Current, October 6, 2026.** Implementation, gateway configuration,
and tests are authoritative.

## Production operator defaults

Open **Backoffice → Stage models** and connect with `CANARY_OPS_TOKEN` to set the
model used for each model-bearing stage. The same settings are available through
`GET` and `PATCH /api/ops/backoffice/models`. PATCH accepts a partial
`{"selections": {"adapt": "gpt-6-sol"}}` mapping. The API validates every
stage/model pair against the production catalog and rejects Codex choices.
Finish packages the book and has no separate model.

Operator defaults are stored atomically in
`<projects_dir>/.operator-model-settings.json`. New job configuration snapshots
for every account and project read them in development and production. A change
does not mutate a running job or existing page artwork. New Draw work advances
the edition revision to the configured profile when its saved profile is no
longer spendable, retaining frozen request provenance and lettering mode.
The operator token is never embedded in
the production browser bundle. Production backoffice settings require the same
operator connection used by its other views.

| Stage setting | Default | Work |
|---|---|---|
| Extract | GPT-6 Luna | Manuscript analysis |
| Brief | GPT-6 Luna | Creative direction |
| Style/Cast text | GPT-6 Luna | Visual briefs and asset instructions |
| Style/Cast images | Sunburst on FAL | Style, cast, and cover art |
| Adapt | GPT-6 Sol | Script and dialogue |
| Plan | GPT-6 Sol | Pages and panels |
| Draw | Sunburst on OpenAI, FAL backup | Complete page art |
| Lettering checks | GPT-6 Luna | OCR and canonical copy checks |
| Visual review | GPT-6 Luna | Visual consistency checks |

Text and vision choices are `gpt-6.1-sol`, `gpt-6-sol`, `gpt-6-luna`,
`claude-opus-5-5`, `claude-sonnet-5-5`, `mimo-v2.6-pro`,
`deepseek-v4.1-flash`, `gemini-3.8-flash`, `bedrock-claude-opus-5-5`, and
`bedrock-claude-sonnet-5-5`.
Image and Draw choices are `image-sunburst` and `image-nano-banana-2.1`. The gateway maps the text
choices to OpenAI, Anthropic, AWS Bedrock, OpenRouter/Xiaomi, Together AI, and Google Vertex AI.
Claude's direct Anthropic and Bedrock routes are independent selections; the
Bedrock labels include “· Bedrock” and the provider reads “AWS Bedrock”. Both
models support every text stage, OCR, and visual review. See [Bedrock setup](bedrock.md).
Gemini uses project-scoped Vertex REST requests with ADC credentials and Google
Cloud billing. See [Vertex setup](vertex-ai.md) for project/credit configuration.
`image-sunburst` runs on OpenAI first with one FAL attempt as backup, for
Style/Cast images and Draw pages alike; model pickers label it "OpenAI, FAL
backup". There is no route-priority setting.
Nano Banana 2.1 runs directly on Google Vertex AI, without fallback, using the
configured Vertex project and ADC at `global`. Both image settings offer
**Nano Banana 2.1** with provider **Google Vertex AI** in Backoffice and local
account/project model controls. Style/Cast freezes `quality=low` for native 1K;
Draw uses the native 1K portrait profile (848×1264) with at most 14 ordered image
inputs, including any correction parent, and preserves integrated or editable
lettering. Its streamed drafts use the same transient preview effect as OpenAI;
only the final image is saved. Pricing and reservations use its own configured
Vertex tariff, with actual provider usage authoritative for settlement.
The gateway loads its model routes at startup. Locally, run
`./scripts/gateway.sh` after updating its routes or preview middleware; it
decides whether to recreate or rebuild. See [gateway refresh](gateway-refresh.md).
A running gateway that has not loaded `image-nano-banana-2.1` rejects the
request before contacting Vertex; Canary classifies that as a configuration
error and records a gateway reload hint.
New Sunburst Draw editions render pages at medium quality; Sunburst Style/Cast
images use `image_quality` (default medium). Nano Banana uses native 1K for
new Style, Cast, and Draw requests. Set an Admin-scoped `FAL_ADMIN_KEY` on the
gateway so Sunburst images settle at FAL's billed charge; without it they settle
at a labelled request estimate (see [stage contracts](stage-contracts.md)).
`novel_to_comic/src/novel_to_comic/text_models.py` lists the selectable text aliases and the
request fields each accepts; every alias needs a gateway route and a pricing
alias. GPT, Claude, and Gemini text routes default to medium reasoning effort.
Backoffice offers a reasoning selector beside each text-stage model: Extract,
Brief, shared Style/Cast text, Adapt, Plan, lettering checks, and visual review.
GPT, Claude, and Gemini accept low, medium, or high. MiMo and DeepSeek accept Off or On
(`none` or `enabled`), using their routes' native reasoning toggles.
PATCH accepts a partial `reasoning_efforts` mapping, for example
`{"reasoning_efforts": {"adapt": "high", "plan": "low"}}`, or a model and
reasoning change together:
`{"selections": {"adapt": "mimo-v2.6-pro"}, "reasoning_efforts": {"adapt": "enabled"}}`.
Incompatible model/setting combinations are rejected before saving. Switching
models resets an incompatible saved reasoning choice to the new model's default:
medium for GPT/Claude/Gemini, Off for MiMo/DeepSeek. Image generation has no text
reasoning setting.

Settings are saved atomically with operator model defaults and snapshotted for
new jobs. Changes do not affect running jobs. GPT requests send
`reasoning_effort`; Gemini sends the same control, which the Vertex adapter maps
to `thinkingConfig.thinkingLevel`; Claude sends `output_config.effort`; open-model requests send
`extra_body.reasoning.enabled`. OpenRouter requests preserve
`provider.require_parameters`. Enabling reasoning on the open routes adds 16K
completion-token headroom and a 4K thinking-token allowance to the request's cost
estimate; actual usage remains provider-reported. The API's shared
`text_reasoning_effort` default remains available for GPT/Claude/Gemini; per-stage values
are what the backoffice edits. Provider request formats follow the
[OpenRouter reasoning API](https://openrouter.ai/docs/guides/best-practices/reasoning-tokens)
and [Together reasoning toggle](https://docs.together.ai/docs/deepseek-v4-quickstart#reducing-reasoning-overhead).
The OpenAI model pages publish the
standard text rates per million tokens: [Sol](https://developers.openai.com/api/docs/models/gpt-6-sol)
$2 input / $0.20 cached input / $10 output, and
[Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)
$0.10 input / $0.01 cached input / $0.50 output. Canary records these in its
pricing overrides; provider-reported cost remains authoritative for settlement.
Provider keys and Vertex credentials belong in the gateway environment.

## Project configuration

`pipeline init` writes `config.yaml` with project-owned choices such as language,
lettering mode, style template, generation concurrency, and pipeline limits. It
does not write provider routes, API credentials, or stage model defaults. The
server overlays operator defaults when it creates a job snapshot. Existing
project files may still contain former model/provider fields; `load_config`
ignores those fields, including legacy gateway credentials and billing policy,
so they cannot override the operator's production route. The next `save_config`
emits the compact project-owned format. Existing pages and frozen requests keep
their recorded profile; new Draw work follows the revision rules above.

## Local development controls

When the original server process has `CANARY_ENV=development` on a local runtime,
**Account → Models (dev)** and **Project settings → Models (dev)** expose
account preferences and project overrides. Those controls and their frontend
modules are excluded from production builds. The account API
`GET`/`PATCH /api/account/model-settings` and project model editing require
the same local development gate; project environment files cannot enable it.

Account preferences are stored in
`<projects_dir>/<user_id>/.model-settings.json`. Project overrides are stored
as `dev_model_selections` in the project `config.yaml`. In development, job
configuration resolves operator defaults, then account preferences, then
explicit project overrides. In production, only operator defaults apply.
Project settings remove an override by choosing **Account setting**.
Draw is selectable for existing projects; saving keeps the edition and artwork
unchanged until new Draw work selects its spendable profile. Saved choices do not start work.

When an older operator, account, or project setting names a retired API model,
reads ignore that choice and use the next active setting in the operator →
account → project order. The saved choice stays in its original file, so old
projects and their assets remain accessible. The development project selector
labels a retired choice and shows which account setting new work will use.
Editing another stage preserves the retired value; explicitly choosing a new
model replaces it. New selections still have to pass the current catalog.
Existing render bytes and frozen requests keep their recorded profile. New Draw
work follows the spendable-profile revision rules above.

The optional Codex adapter uses explicit `codex-dev/text/<model>` and
`codex-dev/image/<reasoning-model>` choices. The selector offers GPT-6 Luna and
GPT-6 Sol and GPT-6.1 Sol for text, and GPT-5.5 for images. It also requires
`CANARY_CODEX_DEV_ENABLED=1`, a local runtime, and a Codex login. Codex image
choices select the reasoning model driving the built-in image tool; they do not
select Sunburst. Codex usage is subscription-funded and does not settle API
credits. A disabled saved Codex choice fails before generation. The production
image omits the Codex execution modules and Labs router; the operator catalog
never lists Codex models.

The optional Claude Code adapter uses explicit `claude-dev/text/<model>`
choices (text only; default allowlist `claude-opus-5-5` and `claude-sonnet-5-5`, override with
`CANARY_CLAUDE_DEV_MODELS` as a JSON list). It requires
`CANARY_CLAUDE_DEV_ENABLED=1` (`./scripts/dev.sh --claude-code`), a local
runtime, the `claude` CLI, and a claude.ai login; `claude auth status` must
report a claude.ai first-party login before each prompt is sent. Each call runs
`claude --print` in an empty directory with no tools, MCP servers, user or
project settings, CLAUDE.md, or session persistence, and an environment that
never carries `ANTHROPIC_*` credentials. It sends the job's configured text effort and
output limit from `text_models.py`, and schemas through Claude Code's
`--json-schema`. Usage is `claude_subscription`-funded and does not settle
credits. Usage events record the served model's tokens (including cache reads
and writes), Claude Code's own cost estimate, and `api_equivalent_cost_usd`,
the same tokens priced as an API call, for comparing the two routes. Claude
Code's system prompt and structured-output mechanics differ from the API
route, so comparisons measure the model through Claude Code, not the raw API.

API and subscription routes can be mixed in a development job. API reservations cover
API work only. Request hashes identify input, not provider deduplication, and
ambiguous image submissions are not retried automatically. Automated tests use
mocked providers and do not establish account access or image quality.


## Labs image comparisons

**Labs → Image comparison** offers GPT Image 2.5 Sunburst and Flare on the
OpenAI API. New comparisons default to those two models with the production
prompt. Both use the same `OPENAI_API_KEY` and streaming gateway handler;
`image-flare` is a Labs route and is not added to account or operator choices.
Sunburst and Flare Style/Cast comparisons preserve the recorded size, quality
and references. Their page comparisons use medium quality at 1024×1536 and preserve the project's
lettering mode. Each cell submits once to its selected route, without fallback
or automatic retry, and is operator-funded. Source projects and editions are
not modified.

Flare's published token rates are configured separately. Its estimate uses a
conservative allowance until consumption is measured; Sunburst's measured
token counts are not attributed to Flare. Completed OpenAI calls report their
own token usage and cost. Automated checks do not establish image quality or
account access. See [OpenAI's Flare model](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare)
and [image generation guide](https://developers.openai.com/api/docs/guides/image-generation).

Page items include every planned part, labelled by part and page number. Each
selection compiles against that part workspace, so equal page numbers in two
parts remain distinct. A page does not need to have been drawn to appear.

Nano Banana 2.1 is also available through Vertex AI as `image-nano-banana-2.1`
(upstream `gemini-nano-banana-2.1`). Select **Nano Banana 2.1 · Vertex AI**
in Image comparison for recorded Style/Cast requests or planned Draw pages.
This operator-funded Labs route uses the configured Vertex project and ADC at
`global`; it allows at most 14 ordered reference images and makes one submission
per cell, without fallback. Asset comparisons freeze `quality=low` to select
native 1K, preserving the recorded prompt, aspect intent and reference bytes.
Page experiments use the versioned 1K portrait profile (848×1264) and preserve the
project's integrated or editable lettering mode. Estimates use the model's
configured allowance, while reported output modalities and reasoning are priced
at its own Vertex rates. The gateway must be rebuilt for its new handler and
Google Gen AI SDK, and the backend must reload the updated Labs target list.
Comparison fingerprints include effective quality; start a new run to compare
at 1K rather than retrying a cell from an older 2K run. Existing art and frozen
production requests retain their recorded inputs.
See [Google's model specifications](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/nano-banana-2-1)
and [native resolution table](https://ai.google.dev/gemini-api/docs/image-generation),
plus [Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing).

## Labs comparison reasoning

**Labs → Stage models** compares two to six arms and offers a model and a
reasoning selector for every arm and stage in the chosen phases. Extract/Brief
starts from the novel text and Adapt/Plan from the source's approved Brief, Style
and Cast; both hold other stages' inputs fixed. **End to end** (`full`) runs
Extract, Brief, Adapt and Plan on each arm's own outputs, keeping the approved
Style and Cast: Plan validates against the arm's own Story Bible, and Cast images
matter only to Draw, which Labs does not run. Its Extract and Brief stages see the
same inputs as the Extract/Brief phase, so that phase adds a repeat, not a new
comparison. A stage uses one model per arm in every phase that includes it.
When a phase continues past a checkpoint, Labs approves it as the author's
approve action would (the Brief as drafted) and marks that stage `auto_approved`. Select a model, then use **Duplicate arm** to add it again. Each
copy has its own settings; **Remove** deletes just that arm. Changing one stage's
model makes a mixed arm, such as one model's Adapt feeding another's Plan within
the same phase; that stage's reasoning resets to the new model's default. GPT and Claude API and
subscription routes, Gemini 3.8 Flash and Gemini 4 Hydrogen and Carbon on Vertex
offer Low, Medium and High. MiMo and DeepSeek offer Off and On. Labs defaults to
Low for Gemini 3.8 Flash and Gemini 4, Medium for GPT/Claude and Off for the
open-model routes. These are run-specific
settings, independent of backoffice defaults. Hydrogen and Carbon send native
thinking levels; see [Hydrogen](vertex-ai.md#gemini-4-hydrogen-default-gemini-4-route)
and [verified Vertex controls](vertex-ai.md#gemini-4-carbon-optional-text-route).

Create and estimate APIs accept `arms`, each with a unique `id`, a default
`model`, optional `stage_models` overrides and a `reasoning_efforts` mapping by
stage. Each stage's reasoning is validated against the model that stage runs on.
For example:

```json
{
  "kind": "stage_models",
  "project": "my-story",
  "phases": ["extract_brief"],
  "arms": [
    {"id": "low", "model": "gemini-4-hydrogen", "reasoning_efforts": {"extract": "low", "brief": "low"}},
    {"id": "high", "model": "gemini-4-hydrogen", "reasoning_efforts": {"extract": "high", "brief": "high"}},
    {"id": "mixed", "model": "gemini-4-hydrogen", "stage_models": {"brief": "gemini-3.8-flash"},
     "reasoning_efforts": {"extract": "low", "brief": "low"}}
  ]
}
```

The run spec stores resolved defaults and explicit choices per arm, including the
model every stage runs on. Each phase cell uses `phase.model.arm-id` (the arm's
default model) for its identity and independent workspace, and records
`stage_models`; a cell that spends any USD reports as API-funded;
reasoning is visible alongside results and in the stage table headings.
Estimates are keyed by arm ID and count every repeated selection. They price each
stage's source-project token log at that stage's model rates and cannot predict a new reasoning level's token
usage. Missing source usage leaves an unknown estimate rather than a free run.

Labs lists the project's current part (the first unfinished part, otherwise
its last), using that part's Brief and the series' shared Style/Cast status.
The create/estimate request pins its `part_id`; the run and retry preserve it.
Each arm snapshots the series authorities and prior parts, then runs the chosen
part under `parts/<part_id>/` inside that isolated copy. Shared Story Bible,
Style and Cast paths retain their series-root meaning. The source remains read-only.

Choices, IDs and model availability are validated before creation or dispatch.
Retries keep the selected arm's identity, reasoning, input fingerprint and
failed attempts; another arm of the same model is never overwritten. The
isolated config uses the normal text client. Claude Code receives the selected
effort; Codex pins `model_reasoning_effort` in its runtime configuration.
Source projects and operator defaults are not modified. Completed historical
runs remain readable; their recorded cells retain their own retry identity.
