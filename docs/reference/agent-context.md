# Canary agent context

**Status: Current, September 15, 2026.** Canary generates complete lettered comic
pages from novels through an eight-stage Python/FastAPI and React application.

| # | Stage | Checkpoint? |
|---|-------|-------------|
| 1 | `extract` | No |
| 2 | `brief` | Yes |
| 3 | `style` | Yes |
| 4 | `cast` | Yes |
| 5 | `adapt` | No |
| 6 | `plan` | No |
| 7 | `draw` | Yes |
| 8 | `finish` | No |

See [stage contracts](stage-contracts.md) for authority, recovery, and validation.
Use [documentation policy](../README.md) to resolve source status and
[the glossary](../../CONTEXT.md) for unfamiliar terms; read only relevant sections.
ADRs 0003–0016 record the full-page architecture; historical panel plans are not
implementation instructions.
The optional local [Codex adapter guide](codex-dev-capabilities.md) distinguishes
process routing/funding controls from scoped live evidence, including experimental Draw.

## Current user workflow

- Four stations group the eight stages: Story (Extract/Brief), Look
  (Style/Cast), Pages, Book. Upload/import creates a source-only project; explicit
  estimated Story analysis starts generation. The CLI still has only `init`
  and `serve`; generation, approval, review, and export use HTTP.
- Story saves the visible draft before approval. Revision/SHA-keyed local
  recovery preserves older drafts as separately labelled, selectable text
  with copy and confirmed discard, never silently merging them into a new Brief.
- Passive Cast entry spends nothing. Explicit estimated Start/Resume generates
  missing references; Style Continue can start Cast and a needed cover.
- Instructed Cast corrections enqueue before the text rewrite; the reserved job
  owns rewrite and image work. A queued receipt is not an applied correction.
  Pending/running work, durable failures/rejections, and instruction drafts remain
  visible across navigation; old artwork does not prove new-image completion.
- Pages reviews exceptions (`open`/`revised` issues), not mandatory per-page
  approvals. URL parameters preserve page, review, filter, and reading context;
  Book links directly to affected reviews. Drawn and text-checked counts are
  distinct; current artifacts/failure phase outrank historical job failure.
  OCR is optional evidence on base art, not an export prerequisite or redraw
  request. Hybrid lettering has a separate free Pages editor, independent
  revision/source/style/art checks, and a shared browser/server compositor. See
  [stage contracts](stage-contracts.md) for recovery and estimate contracts.
- Immediate estimates and temporary holds are distinct and rounded per job.
  Keep the full Draw-stage estimate for reruns, not remaining-page queues.
  Balance refresh after top-up never substitutes for explicit Resume.
- Book reads persisted preflight/package readiness, checking safe paths, size,
  and SHA-256. Check retry and package rebuild are provider-free; “ready to
  download” is not evidence that the browser completed a download. Do not
  promise model quality or invent generation ETAs.
- Paid project mutations require `Idempotency-Key`. Durable verified-account,
  method/path, and input-fingerprint replay survives restarts; an indeterminate
  receipt requires inspection and explicit recovery, never automatic paid retry.
  Browser receipts are account-scoped; account changes abort tracked requests,
  reject late results, replace query caches, and clear pipeline/style/resume state.
- `/api/projects/{project_id}/jobs` returns live and persisted job observations.
  Interrupted queued/running jobs appear failed/recoverable, never auto-requeued.
  Pipeline/style SSE is bounded broadcast, not durable history; refetch status/jobs.
- Cast (including instructed text rewrites), style work, and covers reserve before
  paid work. Owned one-hour holds renew every 30 seconds. Startup requires the
  canonical SQL migration; only expired never-started holds reclaim automatically.
  Started-expired, legacy unowned, and ambiguous settlement need reconciliation.
  Never globally release holds at startup or reset.
- Rejected reruns preserve state/artifacts; admitted non-Draw failure has no full
  rollback. Draw retains revisions plus pending/unfinished paid-result evidence,
  recovering the original frozen action until post-settlement acknowledgement.
  OCR retains complete provider response text with finalized usage before parsing,
  plus versioned raw observations; malformed JSON has no hidden paid repair retry.
  `GET /pages/checks/estimate` quotes readiness and OCR-only work.
  `POST /pages/checks/recover` defaults to `allow_paid: false`, replaying cached
  evidence under the shared page lock without a credit reservation. Explicit
  `allow_paid: true` plus a page-number/image-SHA `renders` map authorizes only
  missing OCR on saved pixels, with per-page outcomes, never a redraw.
  Cache presence does not promise parsability or successful recovery. OCR checks
  generated comic text in hybrid art (canonical wording in baked art), not
  visual correctness; uncertain order is nonblocking editorial
  evidence. Visual verification and paid artwork corrections remain separate.
- Deployment is one uvicorn worker on one Fly Machine with persistent `/projects`
  journals. Authenticated drain must precede the idle check; timeout stays drained.
  The first upgrade from a binary without drain needs controlled maintenance, not
  an idle-only fallback. Horizontal scaling requires distributed coordination.
  See [deployment runbook](../deploy.md); these are requirements, not evidence of
  production migration or deployment.
- Marketing must describe the actual workflow without quality/time guarantees.
  No finished-page showcase was added: the available asset was unsuitable.

Narrative length is advisory: Plan can finish below or above the Brief target
without changing its metadata. `narrative_review.py` owns source/page editorial
review and versioned content-bound evidence. Adapt/Plan publication and new Draw
spend require successful review; older unreviewed artifacts need rerunning their
owning stages. Silence and beat concentration trigger assessment, not automatic
word or page quotas. Review is metered text work and not a quality guarantee.

## Prompt and reference authority

- Extract classifies private character/scene evidence as `direct_action`,
  `staged_recollection`, or `background_only`, with source quotes compared using
  whitespace normalization only (words, punctuation, and case remain significant).
  Scene rosters contain staged visual participants, not mentioned people.
  Evidence is removed before canonical Story Bible persistence; the shared
  `visual_anchor` owns physical identity, including species/anatomy, without a
  separate species DTO.
- Style generates six base proofs (or a faithful author proof plus five neighbors).
  Twelve candidates are curated by role, `visual_logic`, `proportion_family` and
  concrete `character_design`. Defaults require four stylized/graphic directions,
  one realistic illustration, at most one optional photo, and four proportion
  families including three non-naturalistic ones. Author-quoted medium/rendering
  and proportion restrictions override only their own axes. Schema, role and
  diversity repair share two text attempts; mocked tests do not establish image quality.
- Style's generated shared brief, deterministic fallback, and compiler use the
  same bounded scene roster/location. Context mentions do not add subjects.
  Compiled canonical anchors stay exact; v6 brief caching keys selected evidence,
  model, and prompt rather than reusing an unrelated scene.
- Cast references use protected art-only style direction; full-page samples
  and Draw keep lettering/framing standards. Approved style imagery owns
  rendering, never subject identity, scene content, layout, or an implicit edit
  parent. Only explicit edit-parent selection authorizes an edit. Canonical text
  outranks wrong parent pixels, including restoration of species/anatomy.
  State anchors override changed facets; provider-safe framing must not reverse
  anatomy/state. Character calibration is a distinct text-free lineup of
  canonical subjects in anatomy-appropriate postures, not invented human adults
  or a page-style sample; it supplies rendering evidence only.
  Sunburst alone bypasses that shared lineup after observed identity copying;
  all its characters/states use the same approved proof, required before
  generation. Other models retain calibration against per-species style drift.
- Location state plates live at `plates/{location}/states/{state}.png`;
  instructions and lineage remain location-scoped. No old-artifact migration.
- Provider wire v3 and current profiles are a breaking cutover; local Codex uses
  runtime v6 execution identity. No old-wire shim or generated-artifact migration
  is provided. Re-extract/regenerate affected output, or use a new project for an
  incompatible existing edition. See the adapter guide for current selectors and
  scoped evidence; a requested image alias does not identify the actual backend.
- Plan draft continuity is folded into existing `ComicPage.layout_intent`,
  not a new `PageContent.continuity_intent` field. Corrections retain the exact
  original producing prompt and earlier instructions as subordinate,
  non-lettering history; current canonical copy, identity/state/style, author
  pins, and current changes win. No top-level `FrozenPageGenerationRequest.depiction`
  field or retroactive request rehash is introduced.

## Code navigation

- `state.py`, `stages/__init__.py`: stage order, gates, cleanup cascade.
- `target_artifacts.py`: canonical full-page artifact storage and validation.
- `artifacts.py`: Story Bible, style, Cast references, accepted addenda.
- `book_adaptation.py`, `page_planning.py`: creative text generation and validation.
- `editorial.py`, `server/routers/editorial.py`: revision-scoped decisions,
  story-change preview/apply; all routes under `/api/projects/{project_id}`.
- `generation_checkpoints.py`: input-keyed resumable structured responses.
- `stages/s1_extract.py`: private participation/source-quote validation.
- `style_briefing.py`, `style_contract.py`, `compiled_request.py`,
  `stages/s2_style.py`, `stages/s3_cast.py`: bounded shared proof selection,
  exact anchors, page/art-only projection, and canonical character calibration.
- `state_assets.py`, `artifacts.py`: explicit state conditioning, scoped state
  paths, and reference lineage.
- `page_drawing.py`: frozen page compilation, image submission, explicit corrections.
- `page_ocr.py`, `page_review.py`: raw response/observation persistence and
  provider-free revalidation, producing-intent retention, correction context,
  and issue lifecycle. `ai/client.py` owns the pre-parse response sink.
- `page_visual_review.py`: digest-keyed reference-aware review, saved-report validation.
- `page_finishing.py`, `models/finish.py`, `server/routers/export.py`: persisted
  preflight, package identity/byte validation, provider-free retry and export.
- `config.py`, `model_costs.py`, `usage.py`: configured aliases and cost evidence.
- `ai/client.py`: gateway calls and provider usage events.
- `server/credited_job.py`, `server/credits.py`: credit reservation and settlement.
- `server/admission.py`, `server/event_channel.py`, `server/generation_jobs.py`:
  durable action/job journal, process-local mutation/drain coordinator, bounded SSE.
  `server/deployment_status.py` and `scripts/check_deploy_safe.py`: authenticated
  drain/idle deployment guard and explicit operational recovery.
- `server/routers/pipeline.py`, `server/routers/pages.py`: pipeline plus page
  correction, saved-pixel OCR recovery, visual-review, and render-history APIs.
- `server/auth.py`, `server/deps.py`: authentication and project scoping.
- `server/routers/projects.py`: source-only upload/import creation.

Frontend: Pages room (`web/src/pages/rooms/PagesRoom.tsx`) exposes the page
gallery with per-page detail; `InspectDrawer.tsx` is read-only adaptation
and plan. Optional correction tools are `components/pages/RevisionDraft.tsx`
(with `AnnotationEditor.tsx`) and `VisualReviewPanel.tsx`. There is no
storyboard editing and no page story context UI. API ownership in
`web/src/api/pageRevisions.ts` (drafts, preview, submit, cached review,
render history) and `web/src/api/pages.ts` (including check recovery); shared types in
`web/src/types/api.ts`. Story-change preview/apply has no Pages UI and
remains a backend API contract (`editorial.py`,
`server/routers/editorial.py`); automatic correction context stays
backend-owned (`page_review.py`).
Story draft ownership is in `StoryRoom.tsx`; estimated starts use
`components/composites/StagePlaceholder.tsx`. `PagesRoom.tsx` owns review URL
and exception filters; `components/pages/PageCheckRecovery.tsx` owns cached/paid
OCR recovery selection; `BookRoom.tsx` owns package readiness and review links.
`components/InsufficientCreditsDialog.tsx` owns explicit post-top-up Resume.

## Local validation

Follow [AGENTS.md verification guidance](../../AGENTS.md#debugging-and-verification)
for targeted checks and when to broaden them. Model comparisons require
separately recorded provider costs and human visual review; mocked tests cannot
establish image quality.

### Hybrid lettering navigation

`models/lettering.py` and `lettering/service.py` own presentation authority;
`lettering/engine.mjs` is the single measured layout/SVG renderer imported by
React and executed by backend Chromium. `lettering/renderer.py` embeds bundled
fonts and raw pixels without network requests. Routes are in
`server/routers/lettering.py`; the Pages desk is in
`web/src/components/lettering/`. `TargetArtifacts` owns `lettering/` and derived
Finish caches. See [ADR 0021](../adr/0021-hybrid-page-lettering.md).
