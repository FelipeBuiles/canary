# Codex development capability report

**Status: local development adapter (the dev launcher defaults to Codex); scoped
live text, image, reference and correction evidence observed on macOS,
September 8–9, 2026.** September 8's complete-page proof and September 9's
extraction proof required manual recovery of captured output; neither was an
uninterrupted whole job. The original
[adapter handoff](../plans/2026-09-08-codex-dev-adapter.md) remains **Proposed**:
a historical design, not the current configuration contract. Its all-tools-off
requirement was explicitly relaxed for built-in tools, live probes and
`gpt-image-2`; the restricted runtime below supersedes its blocked finding.

## Local developer configuration

The optional SDK is lazy-loaded; API-only startup does not require it.
Before using the default development launcher, explicitly install the optional
SDK and bundled CLI into the existing backend environment, both pinned to 0.147.0:

```sh
uv pip install --python novel_to_comic/.venv/bin/python -r scripts/requirements-codex-dev.txt
```

[SDK metadata][pypi-sdk] requires Python >=3.10; Canary requires >=3.12.
The [bundled runtime][pypi-runtime], not the separately installed CLI 0.153.4,
is used by the adapter. Use existing local ChatGPT Codex authentication; do not
copy credentials or supply API keys to this adapter.

From the repository root, start the local stack with:

```sh
./scripts/dev.sh          # Same as --codex: selected routes use Codex allowance
./scripts/dev.sh --api    # Escape hatch: normal live paid API routing
./scripts/dev.sh --mock   # Zero-cost local fixture replay
./scripts/dev.sh --check  # Read-only health and installed-SDK metadata check
```

The three mode flags are mutually exclusive. Codex startup requires both pinned
SDK distributions already installed; it never installs them, probes authentication
or generates. Both Codex and API modes retain LiteLLM/Postgres Docker dependencies:
unselected API routes still exist. `--no-docker` prevents automatic Docker startup.
`--help` and `--check` do not start services or install dependencies.

The launcher authorizes Codex **only in the backend child process**, before imports,
and defaults `CANARY_ENV` to `development` only when unset. Explicit nondevelopment
values remain intact and fail the existing runtime guards. API and mock children
explicitly disable Codex; API and Codex children explicitly disable mock generation.
`--dev` uses the separate Vite frontend; it is not the authorization switch.

Default text routes cover `extract`, `adapt`, `plan`, `prompt` and `ocr` at all three
`fast`, `balanced` and `quality` presets, targeting the exact `gpt-5.6-terra` selector.
This includes `adapt-quality` at the **same exact** target as `adapt-balanced`,
because planned quality escalation participates in whole-job admission. Default
image routes are `image-fast`, `image-balanced` and `image-quality`; image reasoning
uses `gpt-5.5`. Neither reasoning selector identifies the image backend.
There is no automatic model substitution. **Experimental Codex Draw is enabled**
for a first edition when `image-balanced` and its OCR route are selected together.

To override routing, set `CANARY_CODEX_DEV_TEXT_ROUTES` (a JSON alias-to-model map),
`CANARY_CODEX_DEV_IMAGE_ROUTES` (a JSON alias list), or
`CANARY_CODEX_DEV_IMAGE_REASONING_MODEL` in the launching environment. Explicit
values replace the corresponding defaults, not merge with them. Match **every
alias used by the intended action**, including adapt escalation; partial selection
can reject mixed jobs. Project `config.yaml`, project `.env`, browser input and
`Config.dev_mode` cannot authorize routing.

**Stop an existing backend manually before switching modes or changing route
overrides.** The launcher reuses a backend only when readiness reports the exact
requested `model_mode`, the current pipeline contract and the expected dependency
marker. A stale backend missing `model_mode` is incompatible even if otherwise
healthy; the launcher never kills or restarts it automatically. Same-mode reuse
does not compare route overrides. Flags do not re-route saved artifacts, alter
frozen model identities, or upgrade existing editions.

Settings are captured before dotenv loading. Production `ENV`, hosted-platform
markers, non-development `CANARY_ENV`, non-loopback serving and trusted proxy-header
serving reject enabled routing. Restart with `--api` to restore normal API routing.
Selected failures never fall back to a paid API.
Production dependencies, service configuration, global Codex config and
credentials/authentication remain unchanged.

### Admission, funding and Draw

Whole-job manifests classify **all planned operations in every job**: all selected
and eligible means `codex_subscription`; wholly unselected retains normal API
behavior. **Mixed API/subscription jobs reject before generation or credit holds.**
Selecting only images is insufficient when the job also plans text.

Subscription usage has zero credit holds/debits and explicit zero-debit history,
not mock usage, a tariff fallback or free API inference. Provider cost remains
unknown (`cost_usd=null`); consumed Codex allowance is not converted to USD or
assumed unlimited. **Apply [the canonical schema SQL](../supabase-schema.sql)
before starting the updated backend**, including funding-aware events, ledger and
RPC signatures. Fresh-schema installation and upgrade from the preceding schema
passed against isolated local PostgreSQL 18; no production database was changed.

Draw uses a **separate local-only experimental profile**, not a relaxed production
profile. With the default launcher routes, open a project with an approved Plan
and no existing Draw edition, then use the normal Draw estimate and **Queue all**
action. There is no public provider selector. The first edition binds the requested
`gpt-image-2` source selector, image reasoning selector and restricted runtime
execution fingerprint; changing those controls cannot mix models into that edition.
An existing edition requires its original execution profile, including its runtime
fingerprint: runtime v6 does not silently upgrade an edition frozen under an older
runtime. An existing production edition rejects Codex selection without rewriting
it. This change provides no edition reset or migration action.

All required approved authorities remain verbatim and ordered; none are dropped
to fit. The limit is **five total image inputs**, including the preceding render
for an explicit correction (so at most four authority images with a parent).
Every page in a Queue all batch is prepared before any credit hold or submission;
an over-capacity later page rejects the batch rather than partially enqueuing it.
Authored Plan lettering remains exact and OCR checks are still required.

The 1696×2528 request is composition intent only for this experimental profile.
The native PNG bytes and actual dimensions are preserved through Draw and Finish:
PDF page boxes and CBZ images follow each page's native canvas, without resizing
or cropping. An incompatible fixed/custom trim rejects. Production retains its
fixed Vertex `gemini-3-pro-image`, eight-reference, 1696×2528 geometry contract.

Subscription Draw estimates, holds and debits are zero; provider cost and actual
per-result image-model identity remain unknown (`null`), not inferred from the
source selector or reasoner. Attempts are limited to one; failures do not fall
back to API/model alternatives or automatically resubmit ambiguous work.
One complete-page probe matched both canonical captions in blind OCR; this is
not a guarantee of lettering fidelity, reference fidelity or full-book quality.
Review generated pages and OCR findings before Finish. See the scoped
[complete-page evidence](#complete-page-draw-proof) below and [stage contracts](stage-contracts.md).

## Restricted runtime

The [adapter runtime](../../novel_to_comic/src/novel_to_comic/ai/codex_runtime.py)
uses the official [0.147.0 async client][client147] and supported config/account/
models/thread/turn APIs. The child receives an exact replacement environment from
an allowlisted original-process snapshot, not an environment merged with backend
secrets. Temporary image attachments are read-only; HOME retains intended local
authentication. Canary does not read auth-cache contents.

**Execution is macOS-only.** Supported `launch_args_override` launches the child
app-server under `/usr/bin/sandbox-exec` with actual OS-level read denial for global
Codex `AGENTS` instruction files. Inspected 0.147/0.153 runtimes otherwise load
these despite instruction overrides. No global files are modified, tokens copied,
or sandbox widened. Deprecated `sandbox-exec` is a platform/version-specific
boundary, not a portable guarantee; unsupported OS or unavailable sandbox fails
closed. Successful probes passed the required empty thread `instruction_sources`.

Merged effective configuration is checked for provider, endpoint and profile
conflicts. MCP servers are inventoried, disabled on a second launch and checked
again. Shell, web, MCP, apps, plugins, inherited project/skill instructions and
escalation are disabled. Thread model/provider, read-only sandbox and disabled
sandbox network are checked; utility tools remain allowed. Remote inference still
needs network access. The built-in image extension writes its source-fixed
`~/.codex/generated_images` subtree: workspace read-only policy does **not** mean
no filesystem writes anywhere.

Runtime v6 supplies explicit `image_tool_arguments`, separate from Canary's
internal `image_specification`. Only the native tool arguments are instructions
for the built-in image call; internal specification fields must not be copied
into that call as unsupported parameters. This is a clean runtime/provider-wire
v3 cutover, not an old-wire compatibility shim.

Canonical references use `reference_mode=fresh-thread-user-images`: only the
supplied ordered image attachments enter a fresh thread. With references,
`image_tool_arguments` requests `num_last_images_to_include=N` in the native
range **1–5**, with `referenced_image_paths` empty/omitted. With no references,
omit the recent-image count entirely, rather than passing zero. Ordered reference
roles and edit-parent indices remain attached to the request; an edit parent is
not reclassified as style or discarded. The [native source][image147] gathers
recent user images and restores their order. An earlier direct-path edit failed
because the nested image sandbox could not read those paths; native attachments
succeeded without widening it. Ordered attachment transport is controlled; the
reasoning model's tool arguments and semantic use of references remain
prompt-directed, not a hard fidelity guarantee.

Request/stream retries are zero. Validated completed image bytes are checkpointed
before best-effort interrupt/SDK teardown. Timeout recovery can return that same
validated, request-bound completed checkpoint; it does not submit another turn or
regenerate. A missing/invalid checkpoint or ambiguous submission remains a failure
or indeterminate outcome, not proof that nothing happened. First-image interrupt
and a one-call prompt do not guarantee provider deduplication or a hard single
image-tool invocation.

Structured text schemas are normalized **only at the Codex request boundary**:
all declared object properties become required, objects are closed, and nested
objects, arrays, nullable unions and local `$ref` definitions are handled.
Existing nullability is preserved; defaulted non-nullable fields do not become
nullable. Domain schemas, canonical local validation, saved artifacts and API
routing are unchanged.

**Arbitrary-map schemas remain unsupported.** The strict converter rejects these
explicitly rather than silently discarding map data or replacing it with an empty
object. Plan's private `_BookPlanDraft` now uses the same ordered
`appearance_states` list for all providers in both `plan.book` and `plan.detail`:
each binding is `{"entity_id":"character_1","state_id":"injured"}`, with nonempty
IDs and no extra fields. Each content item permits at most one binding per entity,
even when a repeated binding names the same state; different entities may share a
state ID. Base appearances are omitted from the list; no explicit bindings is `[]`.
Plan rejects duplicate entities before converting the list to the unchanged
canonical `ComicPage` content map. Approved entity-state authority, Adapt-owned
activation timing, exact lettering and visual anchors retain their existing
contracts. This private boundary change is not whole-pipeline compatibility.

Typed provider failures retain a bounded, redacted reason (at most 512 characters)
in error metadata and exception text, not raw provider details. Missing-image
failures now retain a sanitized assistant diagnostic by default, also bounded to
512 characters. That text is an **assistant report, not an authoritative provider
error**. In the older missing-image path, the diagnostic was lost with the
ephemeral thread. Native parameter rejection can precede an image event, so an
absent image event proves neither that no tool call was attempted nor that no
allowance was consumed.

## Capabilities: hard controls, prompt requests, observed evidence

| Capability | Hard implementation/source control | Prompt-only request or limit | Live observation |
| --- | --- | --- | --- |
| Structured text + vision | JSON-schema final output and local parsing; ordered attachments | Schema does not constrain preceding utility tools | `gpt-5.6-terra` returned exact `{"text":"CANARY"}` from the synthetic PNG |
| Image generation | Typed image-item bytes; MIME/dimensions/digest validation; source selector `gpt-image-2`; no prose-path fallback | Prompt fidelity | `gpt-5.5` generated a red mug PNG |
| Reference edit | Fresh thread contains only canonical supplied attachments; native recent-image control available | Tool argument compliance, edit fidelity, identity and lettering | Native one-reference red-to-blue probe and blue-to-green client smoke; Main visually confirmed shape, composition and background retained |
| Reference count/order | Adapter/source maximum five; ordered roles, edit parents and attachments; native source restores recent-image order | Actual tool selection/use/order is not hard-enforced | Single-reference edits and scoped multi-input location state evidence below; five-reference boundary is source/test evidence, **not live five-reference proof** |
| Output size/quality | Source uses `size=auto`, quality `Auto`; actual dimensions recorded | Requested dimensions and quality are not guaranteed | Probe and successful client-smoke PNGs were natively 1254×1254; not a fixed-size promise |
| Image-model identity | Source hardcodes `gpt-image-2`, with no image-model tool argument | Reasoning model cannot select Sunburst/Flare | Actual per-result image backend **unknown** |
| Invocation/retries | Transport retries zero; validated checkpoint recovery without another turn | One image-tool call requested; interrupt best-effort | Successful generation/edit observed; no hard invocation-count/deduplication proof |
| Execution boundary | macOS OS read denial plus config/account/models/thread/tool checks | Utility tools and source-fixed image-store writes remain allowed | Successful text, image and edit passed the restricted runtime |

Both inspected image sources, [0.147.0][image147] and [0.153.4][image153], hardcode
`IMAGE_MODEL = "gpt-image-2"`. That is source selection, not actual result identity.
[Sunburst][sunburst] and [Flare][flare] public API documentation describes API Image
2.5, not Codex selectability, subscription access or comic quality. Do not assume a
bare `gpt-image-2.5` alias or silently substitute. The [API image guide][api-guide]
is separate from the built-in Codex tool.

## Metadata diagnostic and explicit probes

The default diagnostic is **metadata-only**, read-only and missing-SDK-safe:

```sh
novel_to_comic/.venv/bin/python scripts/codex_dev_diagnostic.py
```

A valid report exits 0 with `schema_version=1`, `generation_attempted=false` and
`execution_enabled=false`; these describe the diagnostic, not the live adapter.
It never starts a thread/turn, generates, logs in or explicitly refreshes auth.
Bounded children inspect versions/schema and `account(refresh_token=False)`;
only typed ChatGPT identity permits model-list metadata. Missing SDK permits weaker
supported-CLI login-status evidence; SDK errors do not trigger CLI fallback.
Credentials, emails, raw errors and auth-cache contents are excluded. Metadata
requests are not guaranteed offline and cannot set `live_verified=true`.
There is no diagnostic `--probe` option.

The separate [probe script](../../scripts/codex_dev_probe.py) uses the real runtime.
Preflight performs isolated image capability checks **without starting a turn**;
the other commands explicitly consume allowance, with output outside the repo and
pipeline projects. These are opt-in instructions, not startup/test behavior:

```sh
novel_to_comic/.venv/bin/python scripts/codex_dev_probe.py --probe image --preflight-only --output-dir "$HOME/canary-codex-probes"
novel_to_comic/.venv/bin/python scripts/codex_dev_probe.py --probe structured-text --reasoning-model gpt-5.6-terra --output-dir "$HOME/canary-codex-probes"
novel_to_comic/.venv/bin/python scripts/codex_dev_probe.py --probe image --reasoning-model gpt-5.5 --output-dir "$HOME/canary-codex-probes"
novel_to_comic/.venv/bin/python scripts/codex_dev_probe.py --probe edit --reasoning-model gpt-5.5 --source-image "$HOME/canary-codex-probes/previous-result.png" --output-dir "$HOME/canary-codex-probes"
```

Replace `previous-result.png` with the real preceding successful result. Defaults
are `gpt-5.6-terra` for text and `gpt-5.5` for image/edit. No `--probe` prints help
and submits nothing. Reports distinguish completed validation, failure and ambiguous
submission; images require visual review.

### September 8 recorded evidence

All following probes were explicitly authorized, used SDK/bundle 0.147.0 and local
ChatGPT Codex allowance, with no paid API/fallback. Reports and artifacts are local
under `/tmp/canary-codex-probes/` (not committed):

| Probe/report stem | Result |
| --- | --- |
| `structured-text-5b911d5c524e46188c7382b06c6a3ef7` | Exact schema-valid CANARY OCR JSON using `gpt-5.6-terra` |
| `image-9471c9b1a9574e9bb2a56591d27dbdcb` | Red mug, PNG 1254×1254; SHA-256 `2afa88cf3333301cfde169182aa668381cdea649793e16ed092606ce52d282fd` |
| `edit-892485d3fb0f44a1ac79246b05ad4904` | Native one-reference blue-mug edit, PNG 1254×1254; SHA-256 `d2cc16993bec2ea3529257949c8ed829bf8ca31057bde7349adedda0ee8b4134` |
| `adapt-schema-compatibility.json` | Synthetic request using the actual `NarrativeTreatment` schema: original rejected because `required` omitted `character_arcs`; normalized schema passed with the same request and `gpt-5.6-terra` (2,080 input / 78 output tokens), then passed canonical `NarrativeTreatment.model_validate_json` |
| `plan-state-binding-compatibility.json` | Synthetic request using the actual `_BookPlanDraft` schema: normalized schema accepted by `gpt-5.6-terra` (2,660 input / 195 output tokens), output passed `_BookPlanDraft.model_validate_json`, and `_derived_state_citations` preserved `{"entity_a":"injured","entity_b":"injured"}` as a canonical map |

Main visually reviewed the generation/edit pair. Two earlier `gpt-5.6-terra` image
experiments produced no image-tool result; the successful image/edit reasoning
selector was explicitly `gpt-5.5`, not an automatic fallback. The earlier direct-path
edit failure is superseded only by the native-reference success described above.

The Adapt schema red/green report is
`/tmp/canary-codex-probes/adapt-schema-compatibility.json`. The separate Plan
schema report is `/tmp/canary-codex-probes/plan-state-binding-compatibility.json`.
The Plan probe establishes acceptance of the actual private draft schema and
lossless conversion of two entity-scoped bindings sharing a state ID to the
canonical map. These are synthetic schema/boundary probes only;
**no full project stage or pipeline was rerun**.

Metadata previously verified typed ChatGPT account and seven reasoning selectors:
hidden `gpt-reserve`, visible `gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`,
`gpt-5.5`, `gpt-5.3-codex-spark`, and hidden `codex-auto-review`. All advertised image
input except Spark. No next cursor was present; future non-null cursor means a
partial catalog. Catalog metadata alone proves neither image generation nor vision.

### Integrated client and historical backend verification

The actual client smoke recorded structured text through the raw-response sink and
real PostgreSQL zero-credit settlement in
`integrated-f312911390bf4c2c8c50339634f85dc4/report.json`. Its image generation
completed, but the unchanged safe writer rejected the runner's symlinked `/tmp`
output path. An **explicit image-only rerun**, using canonical `/private/tmp`,
succeeded; this was not automatic regeneration, retry or fallback.

The successful report is
`/private/tmp/canary-codex-probes/integrated-533b9b4af90b4aa8b5af052210862ef8/report.json`.
It records a native 1254×1254 PNG, 1,254,609 bytes, SHA-256
`ec88edbf0b79524dce34a43e1ace7958bccd7ccd27d5a234f060a5166db369c2`.
Main visually compared its blue source and green result: mug color changed while
shape, composition and background remained. The real database recorded one
succeeded subscription event and a zero-credit ledger entry, with `cost_usd=null`,
`provider_model=null`, `image_count=1`, retained thread/turn/tool/reference-digest/
execution-fingerprint provenance, and `gateway_attempts=0`. The isolated user was
deleted after the smoke.

**Historical backend suite (integrated-client milestone):** 1177 passed, 4 skipped
in 17.58 seconds, including real PostgreSQL tests. The documentation checker passed
before that milestone's evidence addition; these counts predate the strict-schema
and provider-error fixes. These are client/database and backend proofs, **not an
HTTP server launch, whole-comic run or Draw qualification**.

**Historical backend suite (Plan list-binding fix, prior Adapt strict-schema/provider-error
fixes and launcher fixtures):** 1202 passed, 12 skipped in 16.60 seconds. Eight skips
were PostgreSQL tests because
the isolated database was not running; the historical PostgreSQL proof above is
separate. Documentation reliability checks passed before this count addition.
No full project stage or pipeline was rerun.

### Complete-page Draw proof

Read-only preflight compiled and prepared all ten actual `undiadeestos-codex`
pages, with one to four required references per page. The actual batch estimate
reported `funding=codex_subscription`, zero estimated/reserved credits, and wrote
no edition. **Only one image was generated**, not the ten-page book.

That one authorized `gpt-5.5` image-reasoning call produced a native 1024×1536 PNG,
2,879,963 bytes, SHA-256
`cc9662390bb5e9c8ae360acac1f56eb0ac620d874639e1a14c397c275f8fe014`.
The isolated proof SQL bridge then failed on ambiguous `RETURNING id`, after
image completion. The exact terminal event was recovered from the PostgreSQL
log and bound to the native image hash. After an offline bridge fix, the captured
completed image was **manually replayed through the TargetArtifacts journal**:
no second image call, automatic retry or paid API fallback occurred. This proves
captured-output publication and settlement, not fresh uninterrupted whole-job
execution or automatic recovery of that bridge failure.

A subsequent real blind OCR call using `gpt-5.6-terra` consumed 4,218 input and
446 output tokens. Persisted `analysis_001.json` matches both canonical Spanish
captions exactly, records `reading_order_proven=true`, and contains zero invariant
failures or editorial issues. Main visually reviewed the four-panel native page.
These observations cover one page, not bookwide visual quality, five-reference
fidelity, correction quality, or a live Finish export.

The isolated real PostgreSQL database recorded two terminal successful
subscription events and two zero-credit ledger rows. Both costs remain `null`;
the actual image backend remains `null` rather than the source selector or
reasoner. The isolated user was deleted after saving evidence. Report and native
artifacts remain local, outside the project:
`/private/tmp/canary-codex-probes/complete-page-cd938110-f6d8-4eaf-ad9e-da83340db731/report.json`.
The canonical OCR evidence is under `draw/pages/page_001/analysis_001.json`
within that proof directory; `review.json` separately records Main's visual
inspection and the two exact OCR matches. The original script report's
conservative `lettering_verified=false` and not-independently-reviewed summary
remain unmodified; the analysis and supplementary review are the evidence for
the later findings. The visual inspection is not comprehensive art, style or
continuity approval.

**Historical backend suite (complete-page profile and native Finish):** 1221 passed,
4 skipped in 17.55 seconds, including real PostgreSQL tests, with no warnings.
Documentation checking remained pending after this evidence update. This suite
result and the scoped probe above do not claim an HTTP/UI launch, a full-book
generation, or production-quality equivalence.

## September 9 scoped live proof

This later proof used isolated copies and real local PostgreSQL subscription
settlement. It did **not mutate** the original
`projects/947150d4-7d2f-4726-a018-5539f933ea56/dcc1` project. Existing bad pixels
there were not repaired. Retained evidence lives outside the repository:

- `/private/tmp/canary-dcc1-live-proof/`: proof projects, manifests, captured
  responses, step jobs/events/ledger records, native images and reviews.
- `/private/tmp/canary-dcc1-location-proof/`: location proof project, per-step
  artifacts, `summary.json` and `main-review.json`; the summary records identical
  before/after original inventories.

These are evidence directories, not supported executable harnesses. Text used
`gpt-5.6-terra`, image reasoning used `gpt-5.5`, and the built-in source selector
remained `gpt-image-2`; the actual image backend is still unknown. There were no
automatic retries, model substitutions or paid API fallbacks. Later authorized
submissions are recorded separately from failures, not presented as uninterrupted
success.

### Recovery and failed attempts remain part of the evidence

The real extraction response failed local source-quote validation because of
source line wrapping. The same captured response was manually recovered after
the private evidence comparison was corrected to collapse whitespace only.
`recovery/extract/recovered.json` and `recovery/extract/review.json` bind that
recovery to source, response and published Bible evidence; there was no second
generation or duplicate settlement. The original failed job remains failed.
This is not a canonical-data migration or proof of automatic job recovery.
The review retained Carl, Persian cat Donut, Mrs. Parsons and rat-like Mordecai,
and excluded background-only Beatrice. The shared canonical `visual_anchor`
remains the authority, not a new species DTO.

The Style sample had **two submitted text turns without an image result** before
the explicit native-argument fix: the original `steps/sample/` failure and
`steps/sample/attempts/diagnostics-only/`. Their evidence is retained. The latter
assistant diagnostic informed the native-parameter fix, but is not authoritative
provider telemetry; absence of an image event does not establish absence of an
attempted tool call. The successful new submission is
`steps/sample/attempts/native-arguments/`, bound by `steps/sample/review.json`.
Separately, the harness's route-admission failure under
`preflight-failures/sample-route-admission/` and Mordecai's earlier `runtime_busy`
failure occurred **before submission**. `steps/mordecai/review.json` binds the
first actual Mordecai submission to `steps/mordecai/attempts/serialized/`.
Those harness/admission failures are not additional generated images.

### Seven successful image outputs, with scoped visual review

The retained reviews account for **four main-proof images plus three location
images**, not seven pages or a book. Main opened the actual images:

| Output | Observed result and evidence |
| --- | --- |
| Style sample | Human Carl and quadrupedal Persian cat Donut, not pastry; no additional character. `steps/sample/review.json` binds the successful native-arguments attempt. `steps/brief/review.json` separately records the fresh two-subject brief. |
| Cast calibration | Mixed lineup: human Carl, Persian cat Donut, elderly Mrs. Parsons and bearded rat-like humanoid Mordecai, not a generic human lineup. `steps/calibration/review.json`. |
| Initial Mordecai reference | Portrait and full-body rat-like anatomy, muzzle, ears, whiskers and tail. `steps/mordecai/review.json`. |
| Accepted Mordecai correction | The real rewrite accepted “Restore the canonical rat-like depiction.” A durable `character_ref_regen` job produced a corrected rat-like reference from a separate clone of the original bad human sheet, **not** from the new correct initial reference. The canonical anchor stayed unchanged; rewrite and image events each uniquely settled zero credits. `steps/correction/review.json`. |
| Dungeon staircase | Distinct descending staircase with iron rails and fish/demon carvings. Location `summary.json` step `loc002`; image `project/plates/loc_002.png`. |
| Locked guild doorway | Distinct wooden doorway in red brick with chain and padlocks, not the staircase or copied Seattle subject from the original scene-rich Style reference. Location `summary.json` step `loc004`; image `project/plates/loc_004.png`. |
| Alternate location state | Generated at `project/plates/loc_001/states/loc_001_crushed.png`, with canonical parent conditioning and scoped lineage. Foreground building facade, cars and streetlamp removed; tree, rack and sign retained. Location `summary.json` step `crushed` and `main-review.json`. |

The alternate state is **not comprehensive state-art approval**: distant skyline
and Space Needle survive, the booted moped and car-shaped indentations are not
clearly visible, and churned/heaped ground leaves flattened, rubble-free terrain
fidelity uncertain. The successful scoped path, distinct location identities and
individual character depictions do not establish general reference fidelity,
full-book continuity, production-quality equivalence or repaired original pixels.

### UI scope and final validation

`/private/tmp/canary-dcc1-live-proof/ui-review.json` records the actual CastRoom
surface at desktop 1365×768 and mobile 390×844 using controlled placeholder images
and job responses. Pending → queued → running → failed transitions, persistent
card status after closing the modal, retained failure after remount, readable
canonical anchor/error guidance and scoped state-image paths were checked. The
mobile view had no horizontal overflow and no premature success was shown.
This fixture made no provider calls or backend requests: it is **not live
authenticated HTTP proof or image-quality evidence**.

Final backend validation recorded **1278 passed, 4 skipped in 17.83 seconds**,
with real isolated PostgreSQL; frontend validation recorded **331 passed**, with
build and lint passing. The UI review's embedded earlier backend count is a
historical snapshot, not this final count. These results and the scoped live
images do not claim a full-book run or uninterrupted extraction-to-Finish proof.

[api-guide]: https://developers.openai.com/api/docs/guides/image-generation
[sunburst]: https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst
[flare]: https://developers.openai.com/api/docs/models/gpt-image-2.5-flare
[pypi-sdk]: https://pypi.org/pypi/openai-codex/0.147.0/json
[pypi-runtime]: https://pypi.org/pypi/openai-codex-cli-bin/0.147.0/json
[client147]: https://github.com/openai/codex/blob/rust-v0.147.0/sdk/python/src/openai_codex/client.py
[image147]: https://github.com/openai/codex/blob/rust-v0.147.0/codex-rs/ext/image-generation/src/tool.rs
[image153]: https://github.com/openai/codex/blob/rust-v0.153.4/codex-rs/ext/image-generation/src/tool.rs
