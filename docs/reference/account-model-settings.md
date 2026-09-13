# Account model settings

**Status: Current, September 11, 2026.** Implementation and tests are authoritative.

In local development, open **Account → Models (dev)** to choose a specific model
for extraction, brief, adaptation, planning, style/cast text, style/cast images,
Draw, lettering checks, and visual review. Quality presets have been removed.
Controls follow pipeline order: Extract, Brief, shared Style/Cast text and images,
Adapt, Plan, then Draw artwork, lettering checks and visual review. Each numbered
label names its stage and each description explains the model’s responsibility.
Finish is noted as having no separate model. Adaptation and planning default to
GPT-5.6 Terra. Saving choices starts no work.

Preferences apply across the authenticated account's projects. New jobs receive
a configuration snapshot; changing preferences does not mutate running jobs.
Preferences are stored atomically in `<projects_dir>/<user_id>/.model-settings.json`.
During local project creation, **Models for this project (dev)** can override
individual stages. Omitted stages continue to inherit account settings. Explicit
choices are saved in the project's `dev_model_selections` mapping and apply to
new work for that project; they never change the account's defaults. The same
controls work for uploaded manuscripts and imported stories.

After creation, **Project settings → Models (dev)** edits the same overrides.
Each selection saves immediately; choose **Account setting** to remove an
override. `PATCH /api/projects/{project_id}/config/` accepts the complete
`dev_model_selections` map, with omitted stages returning to account inheritance.
Validation happens before any settings are persisted, and running configuration
snapshots remain unchanged. Changing Draw after an edition exists is rejected;
other model choices can still be changed. Model edits are gated to local
development on the server, just like creation.

Creation accepts
this mapping only under the original local-development process gate, and saved
overrides are inert outside that gate. Existing edition/profile protections
still apply. Old flat project model and preset fields are discarded on load.

The panel is excluded from production frontend builds. Its authenticated
`GET`/`PATCH /api/account/model-settings` API independently requires the original
server process to have `CANARY_ENV=development`, with hosted runtimes rejected.
Project environment files cannot enable it. PATCH accepts a partial `selections`
object whose stage/model pairs must belong to the configured catalog.

## Providers and local startup

`scripts/dev.sh` defaults to API mode and enables local development controls.
Configure `OPENROUTER_API_KEY` for OpenRouter models and `OPENAI_API_KEY` for
OpenAI models, and `ANTHROPIC_API_KEY` for Claude models. Restart the local gateway and backend after updating routes or
environment variables. Model aliases and pricing remain in configuration.

| Account choice | Gateway alias | Provider model |
|---|---|---|
| GPT-6 Astra | `gpt-6-astra` | `openai/gpt-6-astra` |
| Claude Fable 5.1 | `claude-fable-5-1` | `anthropic/claude-fable-5-1` |
| Claude Opus 5 | `claude-opus-5` | `anthropic/claude-opus-5` |
| DeepSeek V4.1 Flash | `deepseek-v4.1-flash` | `openrouter/deepseek/deepseek-v4.1-flash` |
| GLM 5.3 Flash | `glm-5.3-flash` | `openrouter/z-ai/glm-5.3-flash` |
| GPT Image 2.5 Sunburst | `image-sunburst` | `openai/gpt-image-2.5-sunburst` |
| GPT Image 2.5 Flare | `image-flare` | `openai/gpt-image-2.5-flare` |
| Muse Image | `image-muse` | `openrouter/meta/muse-image` |

GLM 5.3 Flash uses the same `OPENROUTER_API_KEY`. The standard paid model supports
text, image input, and structured outputs, so it is available for text stages and
visual checks, not image generation. Its configured rates are $0.15/M input and
$0.50/M output tokens, verified against the public OpenRouter model catalog on
September 10, 2026; provider-reported charges still take precedence. The route
requires parameter-compatible providers and does not select free or batch
variants. [OpenRouter model details](https://openrouter.ai/z-ai/glm-5.3-flash).

Start `scripts/dev.sh --codex` to enable the local Codex adaptor. The account
panel offers explicit `codex-dev/text/<model>` choices and
`codex-dev/image/<reasoning-model>` choices without any route-map setup.
API mode displays Codex choices as unavailable; it cannot enable the adaptor.
The original-process `CANARY_CODEX_DEV_ENABLED=1` gate, local-only runtime,
authenticated account boundary, and Codex login requirements still apply.

Codex choices include GPT-6 Astra, GPT-5.6 Sol/Terra/Luna, GPT-5.5, and GPT-5.3
Codex Spark. Spark is text-only and excluded from visual checks and image work.
Operators can replace the exact-model allowlist with an original-process
`CANARY_CODEX_DEV_MODELS` JSON list of supported `gpt-*` reasoning model names;
restart the backend after changing it. This list is a selection allowlist,
not a guarantee that a subscription has access to every model. There is no
silent fallback when a selected model is unavailable.

Codex image choices select the **reasoning model** driving the existing built-in
image tool. Its source selector remains GPT Image 2; these choices do not select
GPT Image 2.5, and the actual image backend may be unknown. API GPT Image 2.5
choices remain separate. Codex work uses subscription funding, not API credits.

The premium API text choices also accept images for lettering and visual checks.
Astra uses configured low reasoning effort; Claude uses native adaptive thinking
with the provider default effort. New Claude schema requests use native
`output_config.format` because the pinned gateway otherwise translates them into
legacy forced tool calls. Schema-less JSON requests use a JSON instruction and
local parsing. No automatic model fallback is enabled.

Linked text stages can use different models, including different Codex reasoning
models. There is no active same-model requirement between Extract/Brief or
Adapt/Plan. Style and Cast currently share one text setting and one image setting;
this is configuration granularity, not a provider restriction.

API and Codex choices can be mixed within any job or auto-chain, including
extract/brief, adapt/plan, style text/images, and Draw/lettering checks. Routes
are validated before work, but there is no job-wide funding lock. Estimates and
reservations include only API operations. Codex usage remains diagnostic AI
usage evidence and never writes a credit-ledger row; API calls retain normal
reservation, settlement, cancellation and ambiguous-submission handling. A mixed
job's estimate is labeled `api` because it contains API spend, not because every
call uses the API. Pure Codex work needs no credit hold. Disabled saved Codex
choices stay visible; replace them or enable the adaptor before generating.

Legacy explicit route maps remain available for diagnostics. Account API choices reject conflicting Codex
route overrides, so an API selection cannot silently use subscription funding.
Reve's provider, Labs integration, layout request formatting, and configuration
have been removed.

## Draw and billing

In local development, failed extraction (including provider refusal) exposes the
project's extraction model choice directly in Story. Saving preserves other
stage overrides and refreshes the estimate before enabling an explicit retry.
A failed save keeps retry disabled. Saving a choice never starts generation.

Project routes, including settings, return to the library when project status
returns 404, including after revalidating a previously open tab on focus.
Artifact 404s and temporary server errors do not imply project deletion.

GPT Image 2.5 Draw uses an immutable 1024×1536, high-quality profile. It preserves
required identity/style references and correction parents, rejecting more than
16 references before submission. A Draw edition has one fixed profile. Changing
the account's Draw model requires a new edition or project; mismatched existing
editions are rejected rather than silently switched.

Ambiguous image submissions are not automatically retried. Saved pixels survive
accounting failures. Charges use provider-reported cost or complete modality-aware
token usage. Unknown usage remains unknown and retains its reservation for
reconciliation. The configured $0.25/image and $0.01/reference allowances are
reservation estimates, not provider tariffs or measured charges.

This integration uses immediate API requests. Deferred Batch execution is not
implemented. Automated tests use mocked providers; they do not establish paid
account access, live latency, or comparative image quality.
