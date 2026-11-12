# Gemini through Vertex AI

**Status: Current, October 3, 2026.** The gateway route and provider-free
contracts are implemented. A local structured streaming smoke call succeeded
with fresh impersonated credentials for `canary-vertex` in
`project-b9574d1f-6b2c-4762-aff`, returning `{"ok":true}` with 51 input and 5 output
tokens (estimated USD $0.000057 before credits). This verifies that account's
Vertex access; deployed servers still require updated configuration and images.

Select `gemini-3.8-flash` in Account/Project Models (dev), Backoffice stage
models, or Labs. It supports text and vision stages, with Low/Medium/High
reasoning (default Medium). The gateway's built-in `vertex_ai` adapter calls
`aiplatform.googleapis.com` using the configured project and Application Default
Credentials (ADC). It does not use `GEMINI_API_KEY` or the Gemini Developer API.

The operator-funded Labs image route `image-nano-banana-2.1` uses the custom
`vertex-multimodal` handler and the Google Gen AI SDK from the gateway lock.
Its route passes `project` and `location` (fixed to `global`) to the handler.
LiteLLM reserves `vertex_project` and `vertex_location` for its built-in adapter
and removes them from custom image-generation requests. The text route keeps
those built-in adapter settings.

Gemini now uses the successful medium-reasoning Labs tuning behavior:
Extract, Brief, Adapt, and Plan receive their stage checklists after the source
context, and Plan always uses the reviewed global map plus local detail workflow.
Detail requests use one shared page/panel template and a list of lettering-ID
placements; local validators still enforce exact page count, beat ownership,
lettering ownership/order, and visual authorities. Repairs use the same format.
Every Gemini 3.8 Flash structured call compiles its schema with `gemini_output_schema`
and sends it as JSON-mode instructions (`schema_instructions`, both in
`ai/gemini_schema.py`, applied by `gemini_tuning.tuned_request`). No stage or
feature has its own Gemini transport rule. The compiled schema requires every
declared property (declared nullable unions stay nullable), drops defaults and
turns fixed integer enums into equal minimum/maximum bounds.
Other providers retain their existing prompts and workflows. This does not force High reasoning:
Medium remains the default and the selected Low/Medium/High setting is preserved.
Checkpoint and paid-request hashes include the effective tuned inputs, so an
older stock response cannot satisfy a tuned request. Historical Labs arms use
a request-local override to retain their original comparison behavior.

Vertex's native constrained decoding (`responseJsonSchema`, which the gateway
passes our schema through unchanged) is not used. Direct REST probes on
2026-10-03 found three failures:

- **Optional properties are often omitted.** Four of six identical Brief
  requests returned only the two required page-range fields, which validated
  as an empty brief.
- **Schemas have an unpredictable grammar budget.** Larger schemas are rejected
  before generation with `400 INVALID_ARGUMENT` and no detail (unbilled). Cost
  grows with properties after `$ref` expansion (one 150-property definition
  used three times fails; 250 flat properties pass, 300 fail), nesting depth
  (14 nested objects pass, 16 fail) and bounded arrays, which unroll their
  items. Property kinds weigh differently, so no count predicts acceptance.
  The whole-source Extract schema exceeds it.
- **Accepted schemas can loop.** The registry-backed Extract section schema was
  accepted, but Gemini repeated known entities until the output cap, with
  fields optional or required.

JSON mode with the compiled schema in the instructions returned complete Brief
responses (3/3) and finished registry-backed section and whole-source Extract
calls. JSON mode does not enforce the schema, so the typed validators and the
bounded structured correction path decide acceptance, as for every provider.
Plan detail keeps its Gemini page template (`generic_detail_schema`); it was
introduced for the budget and is not required by JSON mode.

The project in `VERTEXAI_PROJECT` determines the Google Cloud billing account
that receives usage. Trial credits offset eligible charges on that account;
they do not make provider usage free in Canary's cost records. Verify the
project's billing account and remaining credit in Cloud Console before generation.

## Gemini 4 Hydrogen (default Gemini 4 route)

As of November 12, 2026, `gemini-4-hydrogen` is the operator's default Gemini 4
text route, replacing Carbon in the Backoffice stage selections. It selects the
exact gateway target `vertex_ai/gemini-4-hydrogen`. Carbon remains selectable.
Hydrogen takes Carbon's settings and prompt tuning (`TextModel.tuning`): Low
default effort, native `thinkingConfig` levels, schema instructions with JSON
mode, no streaming, 48-page review windows and the same thinking allowances.

Verified in `global` for the `canary-vertex` project on November 12, 2026, with
no retries: one free `countTokens` (`gemini-4-hydrogen-preview` returned 404);
one plain `generateContent` with `thinkingLevel: low` (STOP, correct answer;
65 input, 5 output and 119 thinking tokens); and one JSON-mode call reading a
synthetic image (exact lettering and shape, 1,092 image tokens). Medium and High
levels, native schemas, caching and limits are unverified on Hydrogen.

Pricing uses Google's
[launch rates](https://blog.google/innovation-and-ai/models-and-research/gemini-models/introducing-gemini-4-hydrogen/):
$1.50/M input, $7.50/M output and $0.075/M cached input, flat across the
context window. The Vertex pricing page had no Hydrogen entry when checked.
The approved Runware 429 fallback covers Carbon only, so a rate-limited
Hydrogen call fails as other Vertex calls do.

## Gemini 4 Carbon (optional text route)

As of November 10, 2026, `gemini-4-carbon` replaces `gemini-4-argon` as the
Vertex Gemini 4 route and selects the exact gateway target
`vertex_ai/gemini-4-carbon`. It keeps Argon's settings, tuning and provisional
rates; the operator stated Carbon costs the same as Argon with slightly better
reasoning. Before the switch, one free `countTokens` and one plain-text
`generateContent` call (45 input, 9 output and 79 thinking tokens, no thinking
configuration) succeeded in `global` for the `canary-vertex` project. The public
publisher-model catalog did not list Carbon. Thinking levels, JSON mode,
schemas, vision, caching and limits are not yet verified on Carbon: the evidence
below was gathered on Argon and is kept as the basis for the inherited settings.
Runware does not offer Carbon, so its 429 fallback is `runware-gemini-4-argon`
(see [stage contracts](stage-contracts.md)).

### Argon evidence (October 2026)

As of October 13, 2026, `gemini-4-argon` selected the exact gateway target
`vertex_ai/gemini-4-argon`, using the same ADC credentials and
`VERTEXAI_PROJECT` / `VERTEXAI_LOCATION` settings. The operator reported HTTP 200
from direct `countTokens` and plain-text `generateContent` in `global`.
The integration initially made no live calls; the bounded schema comparison below
subsequently verified structured requests. Existing defaults are unchanged.

Argon is selectable in Labs and Extract, Brief, Style/Cast text, Adapt and Plan.
Finish has no model; image generation, OCR and visual review do not offer Argon.
Structured stage calls place the compiled schema in the prompt, send JSON mode,
and use the existing JSON parser and stage validators. Native constrained
decoding accepts small schemas but rejects full Extract, so stages keep the
same instruction-based contract as Gemini 3.8 Flash. Low, Medium and High
thinking levels are verified in direct Vertex calls on October 13, 2026. The
reasoning selector offers all three (route default Low), independently per Labs
arm and stage; an operator's saved shared or per-stage effort still applies. Streaming, vision, tools, cache creation and sampling controls
remain unverified and disabled. No Vertex input/output
limit is registered: Google's launch post announces a million-token **output**
limit, but it does not establish the configured Vertex endpoint's limits.
The output budget adds 16,384 tokens of thinking headroom, and pre-call holds
include a 4,096-token thinking allowance, following the existing Vertex
reservation policy. These are conservative application allowances, not verified
model limits or predicted thinking usage. Actual reported thinking is billed as
output by the existing usage accounting.

Argon sends `thinkingConfig: {thinkingLevel: <selected>, includeThoughts: true}`
as a native top-level gateway parameter. LiteLLM 1.101's Gemini version check
recognizes only `gemini-3`; its standard `reasoning_effort` would send an older
`thinkingBudget` for Argon and would not preserve Medium as a level. Sending
`thinkingConfig` in `extra_body` also drops it in this adapter. The app and route
default use the verified native parameter; provider-free contracts inspect the
actual Vertex request for all three levels and confirm billable thinking usage.

The first Low and High probes received 429 capacity errors. One further bounded
attempt at each succeeded; Medium succeeded initially. An invalid enum value
returned 400 at `generation_config.thinking_config.thinking_level`. All accepted
calls ended with STOP and answered the synthetic sock-count problem correctly.
High reported 427 thinking tokens and one thought part; Low and Medium reported
no thinking tokens. This supports configurable levels, not a quality or latency
benchmark. The probes had a 2,048-token output cap and no automatic retries.
Raw evidence is retained locally under
`work/argon-reasoning-comparison-20261013/` and its `-attempt2` directory.

The operator approved provisional USD rates of $2/M input, $10/M output and
$0.10/M cached input on October 13, 2026. These are the
[Google launch announcement](https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-argon/)
rates (95% cache discount), not independently confirmed Vertex tariffs.
The [Vertex pricing page](https://cloud.google.com/vertex-ai/generative-ai/pricing)
had no Argon entry when checked; the
[Google SKU catalog](https://cloud.google.com/skus/sku-groups/gen-ai-gemini-models)
lists Argon Cyber Permissive SKUs but does not establish rates for this exact
model ID. Cache storage charges, endpoint-specific rates and the introductory
expiry remain unconfirmed. The launch post says post-intro rates will be $4/M
input and $20/M output; review both checked-in pricing tables when Vertex
publishes applicable tariffs. Cache pricing registration does not enable caching. Bounded probes on October
13, 2026 (`work/argon-cache-probe*.py`, synthetic text) found that Vertex rejects
explicit `cachedContents` for Argon ("does not support explicit context
caching"), while Gemini 3.8 Flash accepts it. Argon's implicit cache did serve
repeated prefixes of about 9k tokens through the gateway (6,765–7,421 cached),
but only best-effort: a new prefix needed one or two earlier sends, the last
~2k tokens were never cached, and text appended inside the same content part
missed. Gemini requests therefore keep a stable system prompt and split shared
context from window-, shard- and repair-specific text with `ai/prompt_parts.py`
part breaks. Argon carries the output contract as the final user part; Gemini
3.8 Flash keeps it in the system prompt. In Labs run `20261013-171728-bf5a8d`
only 3 of 226 Gemini calls read any cached tokens, because each repair or
re-review re-sends its prefix once, and Flash's Plan rose to 11–19 calls after
the move, so Flash returned to its earlier placement.
Provider accounting uses these provisional rates; user-facing credit estimates
continue through the separate existing credit system.

Labs run `20261013-143611-7df22e` (one short story, October 13, 2026) set
three route-specific defaults. Low matched Medium from Extract through Plan.
Narrative review uses one window for up to 48 pages or 120,000 source
characters, instead of 12 pages or 24,000 characters, because every window
re-sends the story as reader context. Adapt lettering adds a show-don't-caption
checklist, because Argon lettered about twice Flash's words and captioned actions
that panels show. These are single-sample settings, not quality benchmarks.
Run `20261013-160909-c706ad` added Argon-only checklists: Extract gathers anchor
details stated anywhere in the source; Brief protects whole quotable lines,
including tone-setting opening and closing sentences, rather than fragments;
Plan mixes panel counts and reserves cliffhangers for withheld answers. Shared
Gemini checklists stay unchanged for Flash (`gemini_tuning.MODEL_ADDENDA`).
Run `20261013-171728-bf5a8d` settled the stage split: Argon for Extract, Brief
and Plan (Plan in 7–8 calls without repairs, against 11–19 for Flash), Flash for
Adapt. Flash Adapt adds a source-wording checklist: no invented cries, no
reported narration voiced as dialogue, no narration rewritten as a thought.
Stage selections are operator settings (see [model settings](account-model-settings.md)).

Provider-free tests cover the exact ADC REST route, plain-text/JSON serialization,
pricing registration, Labs availability, text-stage selections, local structured
parsing and disabled capabilities. They do not establish image understanding or context limits.
A [live schema comparison](../reviews/2026-10-13-argon-schemas.md) verified small
native schemas, compiled Brief and JSON mode with the full Extract schema in
instructions. Both models rejected the full native Extract schema. A running
backend and gateway require the updated catalog/configuration before selecting Argon;
the operator owns refreshes.

## Local credentials and project

Enable `aiplatform.googleapis.com` (shown as **Agent Platform API**, formerly
Vertex AI) in the credited project. Complete any Google Cloud terms/consent
required by the console. Create a dedicated `canary-vertex` service account in
that project with the **Vertex AI User** role (`roles/aiplatform.user`, displayed
as Agent Platform User). For keyless local credentials, enable the IAM Service
Account Credentials API, and give the credited account **Service Account Token
Creator** on this service account only. Then use an isolated, gitignored gcloud
directory to authenticate the credited account and impersonate `canary-vertex`:

```sh
CLOUDSDK_CONFIG="$PWD/.vertex-gcloud" gcloud auth application-default login \
  --project YOUR_CREDITED_PROJECT_ID \
  --impersonate-service-account canary-vertex@YOUR_CREDITED_PROJECT_ID.iam.gserviceaccount.com
```

Restrict the resulting ADC file to its owner (`chmod 600`). It contains a user
refresh credential which obtains short-lived service-account tokens. Do not
reuse credentials from a retired project or commit this file. This preserves
organization policies that disable service-account key creation. Where keys
are permitted, a new JSON key for this project's service account also works.

Set these values in the root `.env`:

```dotenv
VERTEXAI_PROJECT=YOUR_CREDITED_PROJECT_ID
VERTEXAI_LOCATION=global
CANARY_VERTEX_CREDENTIALS_FILE=/absolute/path/to/canary/.vertex-gcloud/application_default_credentials.json
```

`scripts/dev.sh` includes `docker-compose.vertex.yml` when the credential-file
setting is present. The override mounts only the ADC JSON file, read-only, and
sets its quota project explicitly. A missing file fails startup rather than
creating an empty credentials directory. Refresh the local gateway with:

```sh
./scripts/gateway.sh
```

The [refresh command](gateway-refresh.md) preserves the existing ADC mount,
detects changed routes and image inputs, and rebuilds only when needed. Use
`./scripts/gateway.sh --check` for a read-only check or
`./scripts/dev.sh --refresh-gateway` when launching the development stack.
The operator owns server restarts. A running gateway needs its updated image,
route configuration, environment and credential mount before the selection can
run; the backend needs the updated model catalog. For a native gateway, set
`GOOGLE_APPLICATION_CREDENTIALS` to the ADC file and
`GOOGLE_CLOUD_QUOTA_PROJECT` to the credited project instead of using the mount.
Credentials are never baked into either Docker image.

Nano Banana image previews use one native streaming request. Thought images
are transient previews; the final image and terminal usage metadata determine
the saved result. The gateway supplies an owned HTTPX client to the Google SDK
for this stream: its default aiohttp reader has an 8 MiB SSE-line limit, which
a final 2K PNG can exceed, and a separate connection-error retry path.
The HTTPX stream accepts large image frames with SDK retries disabled. A lost
stream remains an ambiguous submission and is never automatically repeated.

## Fly credentials

The production gateway runs inside `canary-web`. `fly.toml` maps the
base64-encoded `CANARY_VERTEX_ADC_B64` Fly secret to
`/run/credentials/google-adc.json` at Machine startup. The local Compose
`CANARY_VERTEX_CREDENTIALS_FILE` setting does not deliver credentials to Fly.

From the repository root, upload the ADC file through stdin and stage the
runtime settings. Replace the project ID, and adjust the file path if needed:

```sh
VERTEX_PROJECT_ID="YOUR_CREDITED_PROJECT_ID"
python3 - <<'PY' | fly secrets import --stage -a canary-web
import base64
from pathlib import Path

credentials = Path(".vertex-gcloud/application_default_credentials.json")
print("CANARY_VERTEX_ADC_B64=" + base64.b64encode(credentials.read_bytes()).decode())
PY
fly secrets set --stage -a canary-web \
  VERTEXAI_PROJECT="$VERTEX_PROJECT_ID" \
  VERTEXAI_LOCATION=global \
  GOOGLE_CLOUD_QUOTA_PROJECT="$VERTEX_PROJECT_ID" \
  GOOGLE_APPLICATION_CREDENTIALS=/run/credentials/google-adc.json
```

Staging does not restart the running app. Apply the file mapping and secrets
with the next deployment, following the drain and verification workflow in
[deployment](../deploy.md). A credential-only deployment can reuse the running
image with `fly deploy -a canary-web --image <current-image>`; this does not add
Vertex routes to an older gateway image. Verify credential loading and token
refresh separately from a paid model smoke call.

Fly recreates the credential file at startup with platform-default permissions.
Restrict it to its owner after deployment or a Machine restart:

```sh
fly ssh console -a canary-web -C 'chmod 600 /run/credentials/google-adc.json'
```

The impersonated ADC file relies on its source user's refresh credential and
service-account impersonation permission. Reauthenticate and restage the file
if that credential is revoked or expires. See
[Fly secrets as files](https://docs.fly.io/apps/secrets#mounting-secrets-as-files).

## Live probe

For a single live structured, streaming request without starting or restarting
servers, run the opt-in probe with the gateway's Python environment:

```sh
litellm/.venv/bin/python scripts/vertex_probe.py --call \
  --project YOUR_CREDITED_PROJECT_ID \
  --credentials /absolute/path/to/canary/.vertex-gcloud/application_default_credentials.json
```

The probe rejects credentials from another project, limits output to 2,048
tokens, uses Low reasoning, and never retries. It reports tokens and estimated
USD cost before trial credits; no pipeline artifacts are changed.

## Costs and verification

The request budget adds 16,384 tokens of thinking headroom and clamps the total
to 65,536 output tokens. Pre-call estimates include a 4,096-token thinking
allowance per call; actual output usage includes provider-reported thinking.
The gateway's cost includes cache reads; without a gateway cost, app fallback
pricing uses total input/output tokens. These allowances are estimates, not a
prediction of Gemini's output.

Global introductory prices are USD $0.75 per million input tokens, $0.075 cached
input, and $3.75 output including thinking, through December 31, 2026. Update the
gateway and app pricing overrides before the January 1, 2027 rate change.
The route defaults to `global`; the pinned prices describe that endpoint.
Sources: [model capabilities](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/gemini/3-8-flash),
[Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing),
[ADC setup](https://docs.cloud.google.com/docs/authentication/set-up-adc-local-dev-environment).

Gateway contracts verify project/endpoint routing, native JSON schema and image
inputs, all three reasoning levels, buffered/streaming responses, and billable
thinking. Backend tests verify catalog selection, output budgets and usage costs.
Those checks make no paid calls and do not establish live account access.
