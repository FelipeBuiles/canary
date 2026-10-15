# Codex subscription image runtime review

Status: Historical review of the shared checkout on 2026-10-13. Recommendations
below are proposed; no runtime or configuration changes were made.

Canary can improve batch throughput and visibility into drawing delays. Selecting
GPT Image 2.5 through the existing subscription adapter is not a Python setting:
the native Codex extension owns the image request. No live image generation or
allowance-consuming probe was performed for this review.

## Model selection

Both installed distributions, `openai-codex` and `openai-codex-cli-bin`, are
0.159.0, matching [the dependency pin](../../scripts/requirements-codex-dev.txt).
The adapter launches that bundled binary, not the desktop application's runtime.
Updating the desktop app therefore does not update Canary's transport.

The inspected [0.159.0 image extension][pinned-tool] and [upstream main][main-tool]
hardcode `IMAGE_MODEL = "gpt-image-2"`. The native tool arguments contain prompt,
background and references, with no model, quality or size selector. Both generation
and editing requests use automatic size and quality. Upgrading to the inspected
main implementation would not add model selection. Image results do not establish
the resolved backend model; Canary correctly leaves that identity unknown.

In Canary, `run_image()` validates `requested_model` but does not send it as a
native image-tool argument. Changing its constant would only change validation
and provenance. Additional assumptions exist in `codex_dev.route_for()` and
`page_drawing`'s profile selection/native-dimension checks. Changing the reasoning
model also does not select the image backend.

The documented API model names are `gpt-image-2.5-sunburst` and
`gpt-image-2.5-flare`. OpenAI positions Sunburst for precise editing and Flare for
fast everyday generation. These API capabilities do not establish Codex subscription
entitlement or comic quality. See the [official image guide][image-guide].

There are two distinct paths:

- **Established API path:** Canary already has a Sunburst Draw route and image
  profiles for both 2.5 variants. This uses API funding. Flare is not currently a
  normal Draw choice in `model_catalog.DRAW_MODELS`; exposing it requires the
  corresponding selection and profile plumbing.
- **Experimental subscription path:** a separately pinned Codex source build could
  make the native request model configurable while retaining runtime-managed
  authentication and the existing service's access checks. Service acceptance of
  either 2.5 selector is unknown. This needs an isolated experiment before any
  product integration; a changed request string is not proof of resolved model
  identity. Do not relabel normal results or silently fall back after rejection.

Any adopted runtime/model change must update request provenance and use an
explicit compatible Draw profile transition. Preserve existing page provenance
and lettering mode; do not rename or reinterpret frozen editions.

## Prioritized experience improvements

### 1. Measure the actual phases before optimizing

The runtime records aggregate execution time and last-notification time, but
successful Draw results pass through `codex_complete_page._runtime_metadata()`,
which drops both. It also lacks dedicated startup, pre-tool reasoning, image-tool
execution and teardown measurements. Parent-side waiting for `_LOCK` occurs
before child execution timing begins. The aggregate page latency cannot distinguish
these causes.

Add monotonic durations for queue wait, runtime startup/preflight, turn-to-image
start, image start-to-completion, and completion-to-publication. Preserve numeric
durations through both the Draw projection and `ai/usage_payloads.py`. Report
medians and tail latency separately for generation and correction, grouped by
reasoner, runtime fingerprint and reference count. This is the first recommended
implementation because it makes subsequent speed claims testable.

### 2. Allow a small number of independent pages concurrently

There are three independent serialization points:

- `server/generation_jobs.py:PARALLEL_PAGE_PROVIDERS` excludes `codex-dev`, so its
  page jobs use the exclusive account lane.
- `ai/codex_runtime.py:_LOCK` serializes text and images within the backend.
- `_child()` takes one per-OS-user nonblocking file lock; a second process fails
  with `runtime_busy` rather than joining a shared queue.

Changing `PARALLEL_CALLS` alone does not remove these controls. A coherent change
must cover scheduling, in-process capacity and cross-process admission. Start an
experiment at two independent pages, with separate fresh threads/workspaces,
bounded capacity, cancellation cleanup and explicit quota/capacity reporting.
Keep dependent corrections ordered and prohibit automatic ambiguous resubmission.
Do not reuse the API's twelve-page limit for Codex without evidence.

This can improve book completion time; it does not inherently make one image
render faster. No throughput multiplier has been measured. Subscription service
capacity may limit or erase the gain.

### 3. Amortize repeated runtime startup

`_execute()` starts one app-server to inspect effective configuration/MCP servers,
closes it, then starts another with those servers disabled. Every page repeats
account/model/capability reads and thread setup. `_run()` also creates a fresh
Python subprocess each time.

A worker that reuses a validated app-server across requests could reduce fixed
overhead. Keep a fresh ephemeral thread and isolated attachments per request;
never reuse conversation history across pages. Define configuration/authentication
invalidation, worker recycling, parent-death cleanup and per-request cancellation
before adopting it. The scout launch currently enforces isolation; simply deleting
it is not an equivalent optimization. Benchmark startup first to justify the
larger lifecycle change.

### 4. Surface progress and publish promptly after image completion

The parent currently waits for process exit. The child checkpoints validated image
bytes before interrupting the reasoning turn, but normal delivery still waits for
SDK teardown. Surface phases such as waiting, preparing, drawing and saving from
bounded child events. If teardown proves material, publish the validated checkpoint
earlier while retaining worker ownership until cleanup finishes. Preserve usage
accounting, cancellation semantics and request-bound checkpoint validation.

The current integration handles image start/completion rather than partial-image
previews. Phase progress is implementable without claiming support for intermediate
pixels. Canary's API preview transport is separate.

## Existing optimizations and limits

Fast mode (`service_tier=priority`), low image reasoning effort, first-image
checkpointing and immediate best-effort turn interruption already exist. The
native image request does not expose a priority/quality control in the inspected
request path, so Fast mode is not evidence of faster image rendering itself.

The image reasoner offered by the current model catalog is `gpt-5.5`. The recorded
September 29 `gpt-6.1-sol` image probe completed without an image, despite passing
capability checks. A newer/faster reasoner needs actual image-tool validation
before being offered; image input support alone is insufficient. See the
[existing capability evidence](../reference/codex-dev-capabilities.md).

The image deadline is 300 seconds and includes startup/preflight. Increasing it
could rescue slow completions but would not improve speed. Keep zero image
transport retries and checkpoint recovery; retrying an ambiguous submission can
consume allowance twice.

## Verification

Read the adapter, subscription routing, page provider/profile, job scheduling,
metadata projection and installed SDK image-result schema. Compared native image
selection against the pinned source and upstream main retrieved on this date.

Focused provider-free verification:

```sh
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_codex_runtime.py novel_to_comic/tests/test_codex_complete_page.py novel_to_comic/tests/test_codex_image_transport.py -q
```

Result: **178 passed in 2.98 seconds**. These tests establish transport contracts,
not current account eligibility, image quality, provider speed or 2.5 subscription
access. No servers were started/restarted and no existing source edits were changed.

[pinned-tool]: https://github.com/openai/codex/blob/rust-v0.159.0/codex-rs/ext/image-generation/src/tool.rs
[main-tool]: https://github.com/openai/codex/blob/main/codex-rs/ext/image-generation/src/tool.rs
[image-guide]: https://developers.openai.com/api/docs/guides/image-generation
