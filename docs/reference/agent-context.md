# Canary agent context

**Status: Current, September 5, 2026.** Canary generates complete lettered comic
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

## Code navigation

All Python module paths below are under `novel_to_comic/src/novel_to_comic/`.

- `state.py`, `stages/__init__.py`: stage order, gates, cleanup cascade.
- `target_artifacts.py`: canonical full-page artifact storage and validation.
- `artifacts.py`: Story Bible, style, Cast references, accepted addenda.
- `book_adaptation.py`, `page_planning.py`: creative text generation and validation.
- `generation_checkpoints.py`: input-keyed resumable structured responses.
- `state_assets.py`: explicit state conditioning and reference lineage.
- `page_drawing.py`: frozen page compilation, image submission, corrections.
- `page_ocr.py`, `page_review.py`: blind OCR and issue lifecycle.
- `page_finishing.py`: deterministic preflight and export.
- `config.py`, `model_costs.py`, `usage.py`: configured aliases and cost evidence.
- `ai/client.py`: gateway calls and provider usage events.
- `server/credited_job.py`, `server/credits.py`: credit reservation and settlement.
- `server/routers/pipeline.py`, `server/routers/pages.py`: pipeline and page APIs.
- `server/auth.py`, `server/deps.py`: authentication and project scoping.

The gateway's complete-page serialization is in root
`litellm_handlers/vertex_multimodal.py`. Frontend rooms are in
`web/src/pages/rooms/`; shared API types in `web/src/types/api.ts`.

## Local validation

Use `novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests -q` for backend
checks and `npm test`, `npm run build`, `npm run lint` in `web/` for frontend
checks. Run `python3 scripts/check_docs_reliability.py` after documentation or
stage changes. Model comparisons require separately recorded provider costs
and human visual review; mocked tests cannot establish image quality.
