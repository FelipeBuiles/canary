# API Routes Reference

**Manually maintained.** Sync changes with the actual router files in
`novel_to_comic/src/novel_to_comic/server/routers/`.

Base URL: `http://localhost:8000` (when running `pipeline serve`).
Replace `{project}` with the project directory name.

---

## Meta

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/health` | `health` | `app.py` |

## Credits

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/credits/pricing-reference` | `pricing_reference` | `credits.py` |
| `GET` | `/api/credits/balance` | `balance` | `credits.py` |
| `GET` | `/api/credits/history` | `history` | `credits.py` |

## Billing

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/billing/packages` | `list_packages` | `billing.py` |
| `POST` | `/api/billing/checkout` | `create_checkout` | `billing.py` |
| `POST` | `/api/billing/webhook` | `stripe_webhook` | `billing.py` |

---

## Projects

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects` | `list_projects` | `projects.py` |
| `POST` | `/api/projects` | `create_project` | `projects.py` |
| `GET` | `/api/projects/{project}/status` | `project_status` | `projects.py` |
| `POST` | `/api/projects/{project}/cover` | `generate_cover` | `projects.py` |
| `DELETE` | `/api/projects/{project}` | `delete_project` | `projects.py` |

## Config

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/config` | `get_config` | `config.py` |
| `PATCH` | `/api/projects/{project}/config` | `update_config` | `config.py` |

## Pipeline

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/estimate` | `estimate_stage_cost` | `pipeline.py` |
| `GET` | `/api/projects/{project}/regen-estimate` | `regen_panel_estimate` | `pipeline.py` |
| `POST` | `/api/projects/{project}/run` | `run_pipeline` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-extract` | `regen_extract` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen` | `regen_panel` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-instructed` | `regen_panel_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-ref` | `regen_ref` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-plate` | `regen_plate` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-prop` | `regen_prop` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-ref-instructed` | `regen_ref_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-plate-instructed` | `regen_plate_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-prop-instructed` | `regen_prop_with_instruction` | `pipeline.py` |
| `GET` | `/api/projects/{project}/generation-jobs` | `get_generation_jobs` | `pipeline.py` |
| `POST` | `/api/projects/{project}/approve/{stage}` | `approve` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset/{stage}` | `reset_stage` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset-stale` | `reset_stale` | `pipeline.py` |
| `GET` | `/api/projects/{project}/events` | `event_stream` | `pipeline.py` |
| `GET` | `/api/projects/{project}/stage-error/{stage}` | `get_stage_error` | `pipeline.py` |

**Query parameters for `POST /run`:**
- `stage` (required): stage to run. Valid stages: `extract`, `style`, `cast`, `adapt`, `plan`, `storyboard`, `direct`, `draw`, `compose`.
- `rerun` (optional bool): when true, resets the selected stage and downstream
  state and clears their registered output paths before running.
- `retry_failed` (optional bool): only valid with `stage=draw`; regenerates
  panels that have failure metadata or failed item state without clearing the
  whole draw/compose/export downstream path. Mutually exclusive with `rerun`.

**SSE:** `GET /api/projects/{project}/events` streams stage progress events.
Connect before triggering a run to receive all events. The frontend applies
stage events directly to the cached project status, then invalidates status and
project lists when `pipeline_done` arrives.

## Stages (Artifacts)

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/story-bible` | `get_story_bible` | `stages.py` |
| `PUT` | `/api/projects/{project}/story-bible` | `update_story_bible` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays` | `list_screenplays` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays/{scene_id}` | `get_screenplay` | `stages.py` |
| `GET` | `/api/projects/{project}/layout-plan` | `get_layout_plan` | `stages.py` |
| `POST` | `/api/projects/{project}/layout-plan/narration-decisions/{beat_id}/impact` | `estimate_narration_decision_impact` | `stages.py` |
| `PUT` | `/api/projects/{project}/layout-plan/narration-decisions/{beat_id}` | `update_narration_decision` | `stages.py` |
| `GET` | `/api/projects/{project}/panels` | `list_panels` | `stages.py` |
| `GET` | `/api/projects/{project}/panels/{scene_id}` | `get_panels_for_scene` | `stages.py` |
| `PUT` | `/api/projects/{project}/panels/{scene_id}/{panel_number}` | `update_panel` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts` | `list_prompts` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts/{scene_id}` | `get_prompts_for_scene` | `stages.py` |
| `PUT` | `/api/projects/{project}/prompts/{scene_id}/{panel_number}` | `update_prompt` | `stages.py` |
| `GET` | `/api/projects/{project}/images` | `list_images` | `stages.py` |
| `POST` | `/api/projects/{project}/images/{scene_id}/{panel_number}/accept` | `accept_image_panel` | `stages.py` |
| `DELETE` | `/api/projects/{project}/images/{scene_id}/{panel_number}/accept` | `unaccept_image_panel` | `stages.py` |
| `GET` | `/api/projects/{project}/images/{scene_id}/{panel_number}/versions` | `get_image_panel_versions` | `stages.py` |
| `POST` | `/api/projects/{project}/images/{scene_id}/{panel_number}/versions/{version}/restore` | `restore_image_panel_version` | `stages.py` |

`GET /images` includes failed placeholders synthesized from
`draw/scene_NNN/panel_NNN.png.failure.json` and `state.json.items_failed`.
Each image status can include `failure_classification`, short
`failure_message`, and longer `failure_detail` for provider diagnostics.

## Pages (compose / Stage 9)

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/pages` | `list_pages` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}` | `get_page` | `pages.py` |
| `PATCH` | `/api/projects/{project}/pages/{page_num}` | `update_page` | `pages.py` |
| `PUT` | `/api/projects/{project}/pages/{page_num}` | `replace_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}/preview` | `page_preview` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_num}/translate-bubbles` | `translate_single_page_bubbles` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_num}/reflow` | `reflow_single_page` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/style-vars/generate` | `generate_page_style_vars` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/set-theme` | `set_theme` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/bubble-presets` | `get_bubble_presets` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/apply-bubble-preset` | `apply_bubble_preset` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/translate-bubbles` | `translate_page_bubbles` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/reflow` | `reflow_pages` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/reorder` | `reorder_panels` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/structural` | `apply_structural_operation` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/character-voices` | `get_character_voices` | `pages.py` |
| `PUT` | `/api/projects/{project}/pages/character-voices/{character_id}` | `put_character_voice` | `pages.py` |
| `DELETE` | `/api/projects/{project}/pages/character-voices/{character_id}` | `delete_character_voice` | `pages.py` |
| `GET` | `/api/projects/{project}/files/{file_path:path}` | `serve_file` | `pages.py` |

## Export

| Method | Path | Handler | File |
|--------|------|---------|------|
| `POST` | `/api/projects/{project}/export` | `trigger_export` | `export.py` |
| `GET` | `/api/projects/{project}/export/{fmt}` | `download_export` | `export.py` |

**`{fmt}`**: `pdf` or `cbz`.

## Styles

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/styles` | `get_styles` | `styles.py` |
| `GET` | `/api/projects/{project}/styles/suggest-estimate` | `suggest_estimate` | `styles.py` |
| `POST` | `/api/projects/{project}/styles/suggest` | `suggest_styles` | `styles.py` |
| `POST` | `/api/projects/{project}/styles/generate-samples` | `generate_style_samples` | `styles.py` |
| `PATCH` | `/api/projects/{project}/styles/active` | `set_active_style` | `styles.py` |

---

## SSE Event Schema

Connect to `GET /api/projects/{project}/events` before triggering a run.

```json
{"type": "stage_begin",    "stage": str, "total": int}
{"type": "stage_progress", "stage": str, "done": int, "total": int}
{"type": "stage_complete", "stage": str, "done": int, "total": int}
{"type": "stage_fail",     "stage": str, "message": str}
{"type": "log",            "stage": str, "level": str, "message": str}
{"type": "pipeline_done"}
```

`level`: `"info"` | `"warn"` | `"error"` | `"dim"` | `"bold"`

`stage_fail` may also include `error_code: "insufficient_credits"` plus
`balance_credits`, `required_credits`, and `shortfall_credits` when a running
or chained stage cannot reserve enough credits.
