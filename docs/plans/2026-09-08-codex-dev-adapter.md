# Development-only Codex SDK adapter

**Status: Proposed.** Implementation handoff, researched September 8, 2026.
No runtime changes or live model requests were made for this plan.

## Objective

Implement an opt-in local adapter that routes selected Canary text and image
requests through the supported Codex SDK, using the developer's existing
ChatGPT-backed Codex authentication and included usage. Preserve normal gateway
routing for explicitly unselected requests. Never fall back from a selected
Codex request to a paid API, another model, or another image tool automatically.

This is an adapter around agent runs, not an OpenAI-compatible subscription API.
Keep deployment, customer credentials, and production model defaults unchanged.
Work in the shared checkout and preserve unrelated edits. Read root AGENTS.md,
CONTEXT.md, docs/reference/agent-context.md, and docs/reference/stage-contracts.md
before implementation; implementation and tests outrank this proposal.

## Verified model availability and unresolved boundary

GPT Image 2.5 is released in the API under two exact model IDs:

- `gpt-image-2.5-sunburst`, snapshot `gpt-image-2.5-sunburst-2026-09-08`:
  the documented choice for editing precision.
- `gpt-image-2.5-flare`, snapshot `gpt-image-2.5-flare-2026-09-08`:
  the documented choice for fast everyday generation.

The API supports both generation and editing. The Images API selects these
models directly; the Responses API selects them in the image-generation tool's
`model` field, separately from the main reasoning model. Do not assume the bare
string `gpt-image-2.5` is a supported alias. Sunburst is the first evaluation
candidate for Canary's reference-heavy editing; this is a proposed experiment,
not evidence of superior comic quality.

**Subscription-backed 2.5 selection is not established.** The current Codex image
documentation still identifies `gpt-image-2` as the built-in model and says its
generations consume general Codex limits. API release does not establish that
the Codex image tool exposes either new model. Do not call the paid Images API
and label the result subscription-backed.

Local read-only inspection found `codex-cli 0.153.4`. Its generated app-server
schema includes `ImageGenerationThreadItem` with `result`, `savedPath`, `status`,
`failure`, and `revisedPrompt`; that item has no image-model identity field.
This supports an artifact-extraction investigation, not a claim of successful
generation or 2.5 selection. The desktop tool available in this conversation
also exposes no image-model selector. A reasoning-model selection or a prompt
saying “use Sunburst” does not prove which image model actually ran.

Sources fetched for this handoff:

- [API image generation guide](https://developers.openai.com/api/docs/guides/image-generation)
- [Sunburst model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst)
- [Flare model](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare)
- [Codex image generation and included usage](https://learn.chatgpt.com/docs/image-generation)
- [Codex SDK](https://developers.openai.com/codex/sdk)
- [Codex authentication](https://developers.openai.com/codex/auth)
- [Non-interactive execution](https://developers.openai.com/codex/noninteractive)
- [App-server protocol](https://learn.chatgpt.com/docs/app-server)

## Architecture and current integration points

Prefer the official Python SDK (`openai-codex`, async client) because Canary is
Python. The documented SDK controls local app-server and bundles a pinned runtime.
Pin the dependency after the capability spike. Keep it optional and lazily
loaded so normal installs and production startup do not require Codex. Use
TypeScript only if the Python SDK demonstrably lacks a required supported
capability; document that finding before adding a sidecar.

Add a narrow `ai/codex_runtime.py` wrapper for authentication/capability checks,
isolated runs, event collection, cancellation, and artifact extraction. Add
`ai/providers/codex_dev.py` for the image-provider implementation. Keep transport
mechanics out of stages. Do not build a general proxy or rewrite all providers.

Verified integration points, relative to `novel_to_comic/src/novel_to_comic/`:

| File / symbol | Required work |
| --- | --- |
| `ai/client.py`: `generate_text`, `generate_structured_object`, `_chat_completion` | Preserve public return types and shared event lifecycle; dispatch selected text requests before gateway transport. |
| `ai/providers/selector.py`: `pick` | Add explicit gated image routing; currently always selects LiteLLM. |
| `ai/providers/base.py`: `ImageProvider`, `ProviderRawResult` | Extend the actual protocol for immutable wire submission; retain bytes, request identity, and observed-model fields. |
| `ai/client.py`: `generate_wire_image` | Replace its LiteLLM-only `isinstance` branch with the coherent provider protocol. Adding a selector alone is insufficient. |
| `ai/finalisation.py` | Reuse image success/failure/cancellation accounting and persistence. |
| `provider_wire.py` and its compilation callers | Compile an honest Codex request identity; preserve references and execution fingerprint. |
| `config.py`, `image_models.py` | Add gated routing and capability descriptions without changing normal aliases. |
| `usage.py`, `model_costs.py`, `ai/client.py` finalization | Represent subscription funding without API-pricing fallback. |
| `server/credits.py`, `server/credited_job.py` | Respect funding during estimation, reservation, settlement, and credit history. |
| `page_drawing.py` | Conditional later phase: explicit development edition profile, never substitution inside a production edition. |

## Phase 0 — Prove capabilities before integration

Create an explicit developer diagnostic script outside the pipeline CLI. Its
default mode must be read-only and consume no generation allowance. Report SDK
and runtime versions, authentication mode, available reasoning models, and
supported image artifact events. Use supported account methods; do not print,
copy into project files, or manually exchange cached OAuth credentials.

Investigate whether the SDK exposes the built-in image tool in headless runs,
whether its model can be explicitly selected, and what metadata proves selection.
`model/list` is useful for reasoning models but is not proof of image-tool models.
Inspect supported schemas/configuration, not undocumented backend endpoints.

Provide a separately invoked live probe for one structured-text run, one small
image generation, and one reference-guided edit. Clearly label this as consuming
Codex allowance. Capture sanitized event evidence and validate returned image
bytes. Do not run it as part of tests or startup. This planning request did not
execute those probes or authorize an API-billed fallback.

Record capabilities separately: text, image input for text/OCR, image generation,
image editing, image-model selection, reference count/order, output dimensions,
and actual-model reporting. Distinguish hard API controls from prompt requests.

Decision gate:

1. Text passes: proceed with text even if images remain unavailable.
2. Built-in images pass but 2.5 selection is unproven: expose only an explicitly
   selected `codex-dev/builtin-image` capability with honest identity metadata.
3. Exact 2.5 selection is supported and independently evidenced: enable separate
   Sunburst/Flare aliases, keeping reasoning and image model fields separate.
4. Requested exact model cannot be selected or verified: fail before generation
   where possible; leave that alias disabled. Never silently substitute Image 2.

Do not infer actual model identity from the agent's final prose. If the only
available built-in backend is mutable/unidentifiable, keep it out of fixed-model
Draw editions and record that limitation.

## Phase 1 — Local routing and execution boundary

Use a process-level opt-in such as `CANARY_CODEX_DEV_ENABLED=1`, plus explicit
server-owned feature/model routing. These are proposed names, not existing config.
`Config.dev_mode` is a quality/performance preset and cannot serve as this gate.
Browser config mutation and imported project config must not enable local Codex
or alter its binary, credentials, permissions, or model mapping.

Require a local-development deployment context. Reject Codex selections when
the gate is absent; reject production activation. Preserve explicit paid routes
only for unselected operations, and identify them in developer diagnostics.
For the initial release, avoid mixed funding within a single admitted job: either
route every potentially invoked provider operation through Codex or reject that
job before spend. Add mixed-funded admission only with tested estimates and holds.

Verify ChatGPT authentication through the supported runtime. Scrub API-key and
alternative-provider overrides from the child environment and reject conflicting
effective configuration. Use Codex's supported login-method enforcement where
available. Do not expose this runner as a public service.

Use one fresh task workspace/thread per independent request, concurrency one by
default, bounded execution time, and explicit cancellation. Do not inherit broad
repository instructions, unrelated MCP tools, or arbitrary shell/network powers.
Configure minimum supported permissions: text should not execute tools; image
runs may use only the required image capability and designated artifact area.
Treat novel content and references as data, separate from adapter instructions.
If the runtime cannot enforce the required boundary, report it as a capability
failure rather than relying solely on prompt wording.

## Phase 2 — Text and structured output

Keep `ApiResult[str]` and `ApiResult[dict]` contracts. Map system/developer
instructions and user material through supported SDK inputs. Pass JSON Schema
when supported and retain local parsing/validation. Explicitly document unsupported
temperature/token controls; do not pretend a prompt hint enforces a hard limit.

Preserve `image_attachments` for OCR/vision or reject those operations before
submission. Preserve `response_sink`: exact raw text plus finalized usage must
be saved before parsing. Respect `retry_invalid_json=False`; do not add hidden
repair calls. Record each permitted repair as separate usage. Preserve existing
generation checkpoints and StageRuntime progress/events.

## Phase 3 — Image transport and recovery

Compile a Codex-specific immutable request before submission. The existing wire
fingerprint covers provider identity and controls: never relabel an already
compiled OpenAI/LiteLLM request or mutate it at transport time. Include requested
image model, reasoning model, materialized prompt, reference digests/order,
requested controls, and adapter/runtime identity as appropriate to the contract.

Preserve canonical reference roles/order from `order_refs_for_upload`, identity
and appearance-state authority, and exact lettering. Validate reference overflow
before spend; never drop authorities to fit. Preserve all prompt parts.

Extract artifacts from typed image events. Validate completion status, MIME,
decoded dimensions and size, and path containment before reading a saved path;
reject symlink/path escapes and unexpected multiple outputs. Treat output metadata
as untrusted. Return bytes through `ProviderRawResult` and existing finalization;
do not let the agent write canonical TargetArtifacts files directly. Preserve
revised prompts as provenance, not replacements for canonical instructions.

Map authentication, unsupported capability/model, quota, refusal, timeout,
cancellation, missing artifact, and malformed result to useful errors. Retain
thread/turn/tool identifiers and sanitized events. A timeout after submission
may have consumed allowance: preserve indeterminate evidence and recover an
already completed result where supported. Never automatically regenerate after
an ambiguous image submission. Audit runtime-level retries as well as application
retries; request hashes alone do not prove provider deduplication.

## Phase 4 — Subscription usage and Canary credits

Implement this before enabling any provider calls in normal jobs. Add an explicit
funding classification (proposed: `codex_subscription`) propagated through usage,
events, estimates, reservation, settlement, and history. Observed tokens and image
counts remain usage; unknown quota consumption remains unknown. Do not invent
remaining allowance, dollar conversion, or per-image credits.

Two current traps require regression tests:

- `UsageRecord.cost_usd=None` still allows API tariff estimation in the pricing
  resolver. It does not mean subscription-backed.
- `usage_to_credit_debit()` can impose a minimum charge for activity even when
  computed USD is zero. Setting cost to zero does not prevent a debit.

Subscription-only jobs must produce zero Canary credit reservation/debit and
still retain their job, usage, and failure evidence. Keep subscription funding
distinct from mock mode and from unknown API usage. Preserve existing paid-route
pricing, minimum charges, failed-request policy, and settlement idempotency.
Audit `debit_model_usage`/`p_billable` and every caller rather than patching only
displayed estimates. Any genuinely mixed job must reserve/settle only its paid
portion and disclose it before admission; otherwise keep it rejected in v1.

## Phase 5 — Conditional Draw support

Enable Style/Cast and verified text operations first. Draw is not simply another
alias: `production_page_capability_profile()`, `select_book_edition()`, and
`ensure_current_page_edition()` currently enforce a single production profile.

Only after reference-guided generation and model identity are proven, introduce
a distinct development capability profile and explicit new-edition selection.
Keep production defaults untouched. Freeze the selected model/profile for the
edition; fail on unsupported model drift or incompatible artifacts with a rerun
instruction. Do not weaken global profile validation to accept any image model.

Require evaluated complete lettered pages, reference ordering/count, dimensions,
prompt capacity, and correction modes. Read ADRs 0003, 0004, 0011, 0012, and 0013
before changing these contracts. OCR is lettering evidence only; visually review
identity, state, style, and layout separately. An unresolved mutable built-in
image model blocks this phase, not the earlier text implementation.

## Verification and deliverables

Add focused fake-runtime tests, with no paid calls, for:

- Opt-in and deployment gating; browser/imported config cannot activate Codex;
  missing SDK does not break normal startup; mock mode stays isolated.
- ChatGPT-auth requirement, inherited API overrides, selected-route failure
  without fallback, and exact requested model preservation.
- Structured success/failure, pre-parse response sink, vision attachments,
  cancellation, and no hidden repair when disabled.
- Image event decoding, quota failure, missing output, path escape, reference
  overflow/order, fingerprint mismatch, and ambiguous-submission recovery.
- Subscription usage never receives API tariff estimates or minimum Canary
  debits; paid routes remain correct; mixed jobs reject before spend in v1.
- Conditional Draw: no cross-model edition mixing and no implicit profile upgrade.

Extend existing `test_ai_client.py`, `test_image_models.py`, `test_usage.py`,
`test_credited_job.py`, `test_image_failure.py`, relevant provider-wire/Draw tests,
and credit settlement tests. Add a focused Codex runtime/provider test module.
Run targeted tests first, then the backend suite:

```sh
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests -q
python3 scripts/check_docs_reliability.py
```

If frontend code changes, also run `npm test`, `npm run build`, and `npm run lint`
in `web/`. Do not add a public provider selector merely to expose local settings.

Deliver the gated implementation, reproducible capability report, explicit live
probe script, configuration instructions, and test results. Clearly distinguish
API 2.5 availability, Codex 2.5 selectability, and successful account-level live
verification. If image selection remains blocked, complete the text adapter and
report the exact unsupported image capability; do not claim the whole image
objective is complete. Keep this plan marked Proposed until implementation facts
have moved into current reference documentation.
