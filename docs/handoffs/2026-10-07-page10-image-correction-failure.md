# Page 10: ineffective image corrections and accumulating artifacts

Status: Historical handoff snapshot — 2026-10-07. The image problem remains unresolved.

## Objective and latest user report

Fix the actual image revision workflow: requested visual changes must take, and repeated corrections must not progressively damage the rest of the page. The latest user report is: “the eye is still open and the image keeps getting worse artifacting on each new revision.” Do not treat passing mocked tests, another generated revision, or stronger prompt wording as evidence that this is fixed.

The concrete failure is Page 10, panel 2: Professor Rook has three eyes. All three should be squeezed tightly shut, including the upper forehead eye against the gun barrel. The generated image keeps an open-looking upper socket around the barrel. The author reported it was still wrong after revision 4; the latest saved render inspected in this session was revision 6. The author also reports increasing artifacts with every revision. That degradation has not yet been measured or isolated.

Related original UX failures:

- “Not an issue” suggestions remained preselected when fixing other suggestions.
- Review changes failed with `page issue 'visual-review-e9269a425d01316347544f15105a105e1e12fb93757cca387caec3f971d44c98-1' is already dismissed`.
- Dismissed/“Looks fixed” suggestions returned on later renders, requiring repeated dismissal.
- “Still wrong” and “Looks fixed” remained visible during generation, inviting decisions about stale artwork.

Original error identifiers: Request `4c779604-230f-449e-b0ad-5a85f638d6a3`; Trace `805be7c68216449bb0556e45be815ccb`.

## Reproduction and evidence locations

Workspace: `/Users/jbuiles/Code/canary`.

Browser URL:
`http://localhost:5173/project/ba18ae37-8647-4f12-b8fd-72833d070c50~part_0001/pages?filter=all&page=10&review=page`

The UI project ID differs from the filesystem container ID. Actual series directory:
`projects/947150d4-7d2f-4726-a018-5539f933ea56/astronomical/`

Part workspace:
`projects/947150d4-7d2f-4726-a018-5539f933ea56/astronomical/parts/part_0001/`

Under the part:

- Canonical page: `plan/pages/page_010.json`.
- Full evidence directory: `draw/pages/page_010/`.
- Original PNGs: `render_001.png` through `render_006.png`.
- Inspection derivatives: matching `.reader.webp` and `.thumbnail.webp` files. Inspect original PNGs when distinguishing model degradation from derivative compression.
- Frozen requests: `request_001.json` through `request_012.json`. Request numbering is independent of render numbering; resolve through `TargetArtifacts.producing_request(render)`.
- Provenance: `provenance_001.json` through `provenance_006.json`.
- Issues: `issues.json`; saved visual evidence: `visual_<revision>_<digest>.json`; OCR/analysis files are alongside them.

Author screenshot:
`/Users/jbuiles/Library/Application Support/CleanShot/media/media_Ac5asfqDIw/CleanShot 2026-10-07 at 7.40.14 PM@2x.png`

Tracked manual concern:
`page-issue-manual-10-3-551d3325-b9b3-4787-bc5a-5f8690fb279a`.

The submitted correction was:

> Draw the eyelids of Rook's upper forehead eye completely closed and squeezed shut against the barrel.
>
> Panel 2: Rook's upper forehead eye is partially open around the gun barrel.
> Expected: All three of Professor Rook's eyes, including the upper forehead eye, squeezed tightly shut.

Canonical page revision is 1; SHA-256 is `4a3ef98fe097117745c1ff2810c5eae64643d00d5e6f390422e0339cadf9a6a0`.

Panel 2's canonical visual intent already requires all eyes shut, but its acting gesture says `pressing gun barrel firmly into upper eye`. Whether that contact wording contributes to the open socket is a hypothesis, not a demonstrated root cause.

## What the artifacts establish

All six renders have different image hashes. This is not byte-identical output returned from a cache. Differences do not establish that the requested feature changed correctly.

| Render | Parent | Producing prompt characters | Image SHA-256 |
| --- | --- | ---: | --- |
| 1 | none | 13,845 | `fa710b3d3249a8d4535877f97a77d5593eda9629aea97325c137b812b662c392` |
| 2 | 1 | 26,633 | `1b1a35554b1dd5e29e310f01798c385b7574c8f3e573700f5b3c748845a6d22f` |
| 3 | 2 | 26,922 | `a121fa541714d065ed1ff2770abaeb3ed779d4bb0958397764ba20e2cd47c048` |
| 4 | 3 | 27,591 | `b7a75e457111c15fbd7abdee7d52136f335506ae69e86e9ff0625f411c5819ae` |
| 5 | 4 | 27,878 | `512095db7f8ad18d7c325c7c6deea0eefc384da6be71bc808e0a17ebff2af9ab` |
| 6 | 5 | 27,878 | `2a3d2c89b2965220050761459a8db59b822ce987eaa5c93e6683f51e8d943724` |

Frozen/provenance profile is `openai-fal`, model `gpt-image-2.5-sunburst`, medium quality. Earlier route inspection found OpenAI actually serving the requests; inspect current provenance rather than assuming a FAL attempt. Model aliases, routes and pricing belong to configuration.

The chain repeatedly edits the preceding generated full page. This makes cumulative repainting a plausible degradation mechanism, but the current investigation has not distinguished provider repainting, input preprocessing, reference conditioning, output quality, and reader-image compression.

## Changes already made in this shared checkout

These are uncommitted source changes, not a deployed fix. Inspect the diff before continuing.

### UI and recurring issue handling

- `web/src/components/pages/RevisionDraft.tsx`: prune linked draft changes/seeds whose issues are no longer actionable. Preserve manual requests, edits and in-flight submission state.
- `web/src/components/pages/PageChecks.tsx`: hide suggestion decisions/fix buttons and second-look actions during drawing; remove the “Redrawn — does it look fixed?” label while waiting.
- `novel_to_comic/src/novel_to_comic/page_visual_review.py`: optional existing issue linkage on findings; provide eligible ancestor concerns to the reviewer; validate linked panel/category/branch; retain author dispositions rather than recreating dismissed/accepted/resolved concerns. Mutable issue status is excluded from the visual-review cache digest.
- `novel_to_comic/src/novel_to_comic/page_review.py`: an old tracked concern can target a current render when saved exact-render visual evidence reobserves it. Human confirmation records the current inspected revision.
- Tests: `web/src/__tests__/pageRevisionDraftIsolation.test.tsx`, `web/src/__tests__/pagesRoom.test.tsx`, `novel_to_comic/tests/test_page_corrections.py`.

The UI hiding behavior was observed live during revision 6: “Redrawing this page” was visible, with no “Still wrong” or “Looks fixed” buttons. Recurring visual issue matching still depends on model linkage; unit tests do not establish its accuracy on every real recurrence.

### Image prompt changes

`novel_to_comic/src/novel_to_comic/page_drawing.py`:

1. An earlier change moved correction instructions ahead of the original page-generation brief and removed the hybrid prompt's “immutable art” wording. Revision 4/5 evidence showed priority wording alone was insufficient.
2. The latest change adds `_edit_prompt_payload` and a dedicated edit prompt. It identifies Image 1 as the parent page and subsequent numbered uploads as identity/state/style authorities. This addresses reliance on asset labels not explicitly interleaved by the OpenAI image upload.
3. Original canonical acting, visual intent, camera and staging directions are omitted from revisions. Subject/state assignments, physical anchors, continuity guards, pinned geometry and canonical lettering remain. Reference images constrain identity/style, not the edited pose or expression.
4. Provider grounding always uses page/neighboring beats, rather than including every book beat merely because it fits under the prompt limit. Full correction context remains in provenance; explicitly selected source prose remains available.
5. Identical current/prior instruction strings are deduplicated. Historical producing prompts remain unchanged in provenance.

Offline recompilation of Page 10's revision-5 request produced approximately 15,648 characters instead of 27,878, with the same four references and the original disputed acting gesture absent. This is input validation only, not a successful image edit.

**Critical live-verification limitation:** the running backend did not load this latest dedicated edit builder. The agent mistakenly submitted one live revision before confirming server freshness. That became revision 6/request 12. Its saved prompt has neither `Edit Image 1` nor `"input_images"`; it still uses the old 27,878-character brief. Therefore revision 6 does not test the latest source change. No backend restart was performed. The previous final asked permission to restart; the user instead requested this handoff. Do not infer restart authorization from that exchange.

Documentation changes: `docs/reference/stage-contracts.md`, `docs/reference/agent-context.md`.

## Verification already completed

- Focused backend: `novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_page_corrections.py novel_to_comic/tests/test_complete_page_draw.py -q`: **110 passed**. Covers integrated/editable edit prompts, retained references/anchors, parent bytes, context projection and issue disposition behavior.
- Full provider-free backend gate: `UV_CACHE_DIR=/private/tmp/canary-uv-cache python3 scripts/check_release.py backend`: **3,670 passed, 63 skipped**, Ruff passed. Chromium portions required approved sandbox escalation.
- After the full gate, a small prompt wording change explicitly preserved deliberate depiction/earlier author intent, and a regression assertion was added. The 110 focused tests, Ruff, docs reliability and `git diff --check` passed afterward; the full gate was not repeated for that wording-only edit.
- Earlier focused frontend verification: **100 tests** across the two affected files, lint and build passed.
- `python3 scripts/update_docs.py` and `python3 scripts/check_docs_reliability.py` passed.

No check above proves image fidelity. The user explicitly reports the visual failure remains.

## Recommended next investigation

1. Inspect the original PNG sequence and the tiny forehead-eye region at matched scale. Compare untouched regions as well. Establish whether artifacting is in originals or reader derivatives, and which parent offers the cleanest useful starting point.
2. Trace the actual edit submission end to end: parent file/bytes, reference order, resizing/reencoding, model quality/size parameters, route serialization and provider response. Relevant owners: `page_drawing.py` (`prepare_page_correction`, `compile_page_generation_request`, `GoogleVertexCompletePageTransport.generate`, `OpenAICompletePageAdapter`, `_PageRouteTransport`); `server/routers/pages.py`; `image_route_fallback.py`; root `litellm_handlers/vertex_multimodal.py`. Use `TargetArtifacts` for typed artifact access.
3. Confirm the running server/gateway uses current code before any live validation. A saved request containing the dedicated edit opening and numbered image bindings is the concrete check; browser hot reload does not establish backend freshness.
4. Assess whether prompt-only full-page editing is suitable for a tiny anatomical change. Investigate existing region/annotation support and provider capabilities for stronger localization or protecting unchanged art. Consider a deliberate cleaner-parent strategy to avoid degrading a revision chain. These are hypotheses/design options, not implemented solutions; preserve complete-page generation and provenance contracts.
5. Build provider-free contract tests for any actual transport/localization change. Then perform a bounded, authorized live validation and inspect the exact feature and unrelated art. Do not just increase emphasis and declare success.
6. Leave visual concerns unverified until human confirmation. Do not mark this issue “Looks fixed” on the user's behalf.

## Working constraints and unrelated edits

Follow the current `AGENTS.md`. Work in this shared checkout; no routine worktree. Do not start/restart development servers unless explicitly asked. Use HTTP APIs for run/correction/revision operations; no pipeline CLI commands. Preserve identity refs and all anchors/guards, canonical lettering mode and frozen historical provenance. No automatic retries after ambiguous paid submission except the existing approved OpenAI→FAL behavior. Keep reproduction loops provider-free; never hide failed attempt costs. Do not rewrite saved project requests/renders to make the new implementation appear previously active.

Unrelated changes already present before this work and to preserve:

- `novel_to_comic/src/novel_to_comic/server/admission.py`
- `novel_to_comic/tests/test_server_admission.py`
- `docs/startup-application-package.md` (untracked)

The optional temporary offline request is `/private/tmp/canary-page10-focused-edit.json`; it may disappear between sessions. Recreate it by compiling the saved revision-5 correction with current canonical page/edition, approved inventory/files, `build_correction_context`, the exact revision-4 parent bytes and selected style proof. Do not submit the temporary request as a hidden replacement for normal revision/issue lineage.

## Follow-up findings (2026-10-07, offline, no provider calls)

- **Revision 7 / request 13 did use the dedicated edit builder** (prompt 15,743 chars, contains `Edit Image 1`; 3,186 input text tokens vs 5,627 for revision 6). Original PNG crops show revisions 1–6 keep an open almond socket with visible eyeball around the muzzle; revision 7 is the first with a lid fold over the socket, but a raw reddish ring remains at the muzzle. Partial improvement, not fixed; author confirmation still required.
- **Degradation is in the original PNGs, not derivatives, and it is cumulative across the whole page.** Panel 1 was never targeted, yet its mean absolute difference from revision 1 grows monotonically (red channel 8.2 → 10.3 → 12.1 → 14.2 → 15.4 → 17.3 for revisions 2–7). Skin, wallpaper and bedspread acquire a maze/“circuit-board” high-frequency texture that compounds each generation.
- **Transport is faithful:** parent PNG bytes go unmodified as the first `image[]` part to `/v1/images/edits` (`page_drawing.py` OpenAI path → `litellm_handlers/openai_image_stream.py`), quality medium, no mask; GPT Image 2.5 rejects `input_fidelity`. The cause is generation loss: every revision is a full medium-quality repaint of the previous AI output.
- **No pixel protection exists anywhere.** `region_targeted` polygons and annotations are only serialized into prompt text; the provider's whole-canvas output always replaces the page.
- **Offline composite proof of concept:** feathered ellipse of revision 7's eye region pasted onto revision 1 keeps all other pixels identical to revision 1 and shows the closed lid; seam visible because revision 7 has drifted (texture, barrel position). Suggests: composite onto the edited parent outside an author/derived region, and edit from the cleanest ancestor rather than chaining.
