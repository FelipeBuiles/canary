# Slice 00 — Route Truth and Characterization

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, and the
files listed below. Do not begin Slice 01.

## Goal

Establish truthful model-route and request-shape contracts before changing
prompt or reference behavior. User-facing labels, route predicates, one-shot
model overrides, tests, and LiteLLM configuration must agree.

## Current problem

- `image-fast` and `image-balanced` currently route to the same Gemini Flash
  Lite image model.
- `image-quality` and `image-reve` currently route to Reve.
- Some CLI, Labs, comments, and tests still describe balanced as Gemini Pro or
  quality as GPT Image 2.
- A one-shot image alias override can be superseded by `quality_preset`, making
  an explicit rerender choice ineffective.

## Required reading

- `novel_to_comic/src/novel_to_comic/config.py`
- `novel_to_comic/src/novel_to_comic/cli.py`
- `litellm/config.yaml`
- `novel_to_comic/src/novel_to_comic/labs/labs_models.yaml`
- `novel_to_comic/src/novel_to_comic/ai/providers/selector.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/litellm_http.py`
- `novel_to_comic/tests/test_config.py`

## Deliverables

1. Introduce one application-level route-description seam, preferably a small
   `image_models.py` module, that maps an effective model string to a stable
   route enum and truthful display metadata. Keep it small; reference limits,
   prompt limits, and native aspect support are added in later slices.
2. Make `is_reve_model()` and `is_gpt_image_2()` delegate to or agree with that
   seam. Do not infer GPT behavior from stale alias labels.
3. Correct CLI, Labs, docs/comments directly adjacent to edited code, and any
   exposed API labels so they describe the configured routes truthfully.
4. Make an explicit one-shot alias from `config_for_image_model_alias()` win
   over `quality_preset` and dev-mode defaults for that request only. Do not
   mutate the persisted project configuration.
5. Add characterization tests for:
   - every production alias;
   - literal Reve and GPT model strings;
   - explicit alias overrides under every quality preset and dev mode;
   - `/images/generations` with no refs and `/images/edits` with refs;
   - selector behavior for Reve layout versus flat generation.
6. Do not change prompt text, reference selection, or provider payload fields.

## Likely files

- New: `novel_to_comic/src/novel_to_comic/image_models.py`
- Edit: `config.py`, `cli.py`, `labs/labs_models.yaml`
- Tests: `test_config.py` and narrowly scoped provider-selector/request tests

## Exit criteria

- Python route classification and `litellm/config.yaml` agree for every exposed
  alias.
- An explicit per-request alias remains effective with `quality_preset` and
  dev mode enabled.
- No user-facing surface calls Reve “GPT Image 2” or the current Gemini Lite
  route “Gemini Pro.”
- Existing image request behavior is otherwise unchanged.
- Focused tests, full backend tests, and Ruff pass.

## Handoff to Slice 01

Write `handoffs/00.md` using the durable handoff template before replying.

Report the new route-description API and the exact precedence rule for one-shot
overrides. Slice 01 may consume route truth but must not expand it.
