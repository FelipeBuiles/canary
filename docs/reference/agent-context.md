# Canary agent context

**Status: Current, September 7, 2026.** Canary generates complete lettered comic
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
Read [documentation policy](../README.md) and root `CONTEXT.md` for vocabulary.
ADRs 0003–0015 record the full-page architecture; historical panel plans are not
implementation instructions.

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
- Pages reviews exceptions (`open`/`revised` issues), not mandatory per-page
  approvals. URL parameters preserve page, review, filter, and reading context;
  Book links directly to affected reviews. See [stage contracts](stage-contracts.md)
  for parameter values and read-only page/remaining-page estimate endpoints.
- Immediate estimates and temporary holds are distinct and rounded per job.
  Keep the full Draw-stage estimate for reruns, not remaining-page queues.
  Balance refresh after top-up never substitutes for explicit Resume.
- Book reads persisted preflight/package readiness, checking safe paths, size,
  and SHA-256. Check retry and package rebuild are provider-free; “ready to
  download” is not evidence that the browser completed a download. Do not
  promise model quality or invent generation ETAs.

## Code navigation

- `state.py`, `stages/__init__.py`: stage order, gates, cleanup cascade.
- `target_artifacts.py`: canonical full-page artifact storage and validation.
- `artifacts.py`: Story Bible, style, Cast references, accepted addenda.
- `book_adaptation.py`, `page_planning.py`: creative text generation and validation.
- `editorial.py`, `server/routers/editorial.py`: revision-scoped decisions,
  story-change preview/apply; all routes under `/api/projects/{project_id}`.
- `generation_checkpoints.py`: input-keyed resumable structured responses.
- `state_assets.py`: explicit state conditioning and reference lineage.
- `page_drawing.py`: frozen page compilation, image submission, explicit corrections.
- `page_ocr.py`, `page_review.py`: blind OCR, correction context/lineage, issue lifecycle.
- `page_visual_review.py`: digest-keyed reference-aware review, saved-report validation.
- `page_finishing.py`, `models/finish.py`, `server/routers/export.py`: persisted
  preflight, package identity/byte validation, provider-free retry and export.
- `config.py`, `model_costs.py`, `usage.py`: configured aliases and cost evidence.
- `ai/client.py`: gateway calls and provider usage events.
- `server/credited_job.py`, `server/credits.py`: credit reservation and settlement.
- `server/routers/pipeline.py`, `server/routers/pages.py`: pipeline plus page
  correction, visual-review, and render-history APIs.
- `server/auth.py`, `server/deps.py`: authentication and project scoping.
- `server/routers/projects.py`: source-only upload/import creation.

Frontend: Pages room (`web/src/pages/rooms/PagesRoom.tsx`) exposes the page
gallery with per-page detail; `InspectDrawer.tsx` is read-only adaptation
and plan. Optional correction tools are `components/pages/RevisionDraft.tsx`
(with `AnnotationEditor.tsx`) and `VisualReviewPanel.tsx`. There is no
storyboard editing and no page story context UI. API ownership in
`web/src/api/pageRevisions.ts` (drafts, preview, submit, cached review,
render history) and `web/src/api/pages.ts`; shared types in
`web/src/types/api.ts`. Story-change preview/apply has no Pages UI and
remains a backend API contract (`editorial.py`,
`server/routers/editorial.py`); automatic correction context stays
backend-owned (`page_review.py`).
Story draft ownership is in `StoryRoom.tsx`; estimated starts use
`components/composites/StagePlaceholder.tsx`. `PagesRoom.tsx` owns review URL
and exception filters; `BookRoom.tsx` owns package readiness and review links.
`components/InsufficientCreditsDialog.tsx` owns explicit post-top-up Resume.

## Local validation

Use `novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests -q` for backend
checks and `npm test`, `npm run build`, `npm run lint` in `web/` for frontend
checks. Run `python3 scripts/check_docs_reliability.py` after documentation or
stage changes. Model comparisons require separately recorded provider costs
and human visual review; mocked tests cannot establish image quality.
