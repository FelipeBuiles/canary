# Panel Regeneration Model Alias Override Design

Date: 2026-05-16

## Goal

Allow a user to regenerate a difficult or blocked draw-stage panel with a
specific image model alias for that one regeneration only. The project-wide
`config.yaml` image model must not change, and the Draw UI must not expose raw
provider or model names outside Labs.

## Success Criteria

- A panel regeneration can be requested with an explicit image model alias.
- The alias applies only to that queued regeneration job.
- The project default remains unchanged for later panel generation.
- Credit estimates use the same alias that the regeneration request will use.
- Draw UI surfaces aliases such as `image-fast`, `image-balanced`, and
  `image-quality`, not raw provider names such as OpenAI, Gemini, Seedream, or
  GPT Image 2.
- Generation metadata continues to record the resolved `image_model` used for
  the panel image.

## Non-Goals

- No per-panel persistent model preference.
- No mutation of project `config.yaml`.
- No Labs-style model comparison UI in Draw.
- No provider/model-name picker outside Labs.
- No fallback chain or automatic retry model selection.

## Backend Design

Add an optional `image_model_alias` parameter to panel regeneration flows:

- `GET /regen-estimate`
- `POST /regen`
- `POST /regen-instructed`

For plain query endpoints, the alias is a query parameter. For instructed
regeneration, the alias is an optional request-body field.

The server validates the alias against a backend-owned allowlist of production
image aliases. The initial allowlist should include:

- `image-fast`
- `image-balanced`
- `image-quality`

If the alias is omitted or blank, the backend uses the current project default.
If the alias is present and invalid, the backend returns `400` with a concise
message.

After validation, the backend creates a one-shot config copy:

```python
regen_config = config.model_copy(update={"image_model": image_model_alias})
```

That copied config is passed to:

- `estimate_panel_image_cost_usd(...)`
- `s7_draw.regenerate_panel_image(...)`
- the generation semaphore selection, if model choice affects concurrency

The copied config is captured in the queued job closure so later config edits do
not change an already queued regeneration. The original `config` object and
project `config.yaml` remain untouched.

## Frontend Design

Add a compact alias selector in `PanelDetailModal`, available to all panel
regeneration actions:

- Quick Re-Do
- Apply & Regen
- Generate from Edits

The selector defaults to `project default`. The explicit choices are aliases,
not raw model names:

- `image-fast`
- `image-balanced`
- `image-quality`

When the selected alias changes, the regen estimate query key includes that
alias and refetches cost. All regeneration mutations include the selected alias.

The UI copy should stay deterministic and direct. For example:

- Label: `IMAGE MODEL`
- Default option: `Project default`
- Alias options: `image-fast`, `image-balanced`, `image-quality`

No provider names or Labs model labels are shown in Draw.

## Data Flow

1. User opens a panel in Draw.
2. User selects an alias or leaves `Project default`.
3. Frontend requests `/regen-estimate` with the alias, if selected.
4. User starts one of the regeneration actions.
5. Frontend sends the alias with the mutation.
6. Backend validates the alias.
7. Backend builds a temporary config copy for the job.
8. The job regenerates the panel with that config copy.
9. Existing generation metadata records the effective model used.

## Error Handling

- Invalid alias: return `400`.
- Missing prompt: preserve current `404` behavior.
- Active project stage or active panel regen: preserve current `409` behavior.
- Insufficient credits: use the estimate for the selected alias.
- Provider blocked or generation failed: preserve current failure metadata and
  UI handling.

## Testing

Backend tests should cover:

- Omitted alias uses project default.
- Valid alias creates a copied config and does not mutate original config.
- Invalid alias returns `400`.
- `regen-estimate` and `regen` use the same alias for cost calculation.
- Instructed regeneration passes the alias through after prompt rewrite.

Frontend tests should cover:

- Selector defaults to `Project default`.
- Changing alias refetches the regen estimate.
- Quick Re-Do sends the selected alias.
- Apply & Regen sends the selected alias.
- Generate from Edits sends the selected alias after saving prompt edits.

## Implementation Notes

- Keep the alias allowlist close to image configuration code, or expose it from a
  small shared helper used by the pipeline router and frontend config endpoint.
- Do not reuse Labs labels in Draw. Labs can continue to expose raw model
  details because its purpose is experimentation.
- The draw-stage generation metadata already writes
  `config.effective_image_model()` into the panel image metadata, so the
  one-shot alias should be auditable without adding new metadata fields.
