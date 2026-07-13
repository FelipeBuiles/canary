# API Routes Reference

_Auto-generated from `server/routers/*.py`. Do not edit manually._

Base URL: `http://localhost:8000` (dev). Replace `{project}` with the project directory name.

## Routes

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/billing/packages` | `list_packages` | `billing.py` |
| `POST` | `/api/billing/checkout` | `create_checkout` | `billing.py` |
| `POST` | `/api/billing/webhook` | `stripe_webhook` | `billing.py` |
| `GET` | `/api/projects/{project}/config` | `get_config` | `config.py` |
| `PATCH` | `/api/projects/{project}/config` | `update_config` | `config.py` |
| `GET` | `/api/credits/pricing-reference` | `pricing_reference` | `credits.py` |
| `GET` | `/api/credits/balance` | `balance` | `credits.py` |
| `GET` | `/api/credits/history` | `history` | `credits.py` |
| `POST` | `/api/projects/{project}/export` | `trigger_export` | `export.py` |
| `GET` | `/api/projects/{project}/export/{fmt}` | `download_export` | `export.py` |
| `GET` | `/api/labs/models` | `list_models` | `labs.py` |
| `GET` | `/api/labs/fixtures/default` | `get_default_fixture` | `labs.py` |
| `GET` | `/api/labs/fixtures/default/refs/{filename}` | `get_default_fixture_ref` | `labs.py` |
| `GET` | `/api/labs/projects` | `list_importable_projects` | `labs.py` |
| `GET` | `/api/labs/projects/{project_id}/scenes` | `list_project_scenes` | `labs.py` |
| `POST` | `/api/labs/projects/{project_id}/import-scene` | `import_project_scene` | `labs.py` |
| `POST` | `/api/labs/runs` | `create_run` | `labs.py` |
| `GET` | `/api/labs/runs` | `list_runs_endpoint` | `labs.py` |
| `GET` | `/api/labs/runs/{run_id}` | `get_run_endpoint` | `labs.py` |
| `DELETE` | `/api/labs/runs/{run_id}` | `delete_run_endpoint` | `labs.py` |
| `GET` | `/api/labs/runs/{run_id}/cells/{panel_idx}/{variant}/{model_id}/image` | `get_cell_image` | `labs.py` |
| `GET` | `/api/projects/{project}/pages/` | `list_pages` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/bubble-presets` | `get_bubble_presets` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}` | `get_page` | `pages.py` |
| `PATCH` | `/api/projects/{project}/pages/{page_num}` | `update_page` | `pages.py` |
| `GET` | `/api/projects/{project}/lettering-style` | `get_lettering_style` | `pages.py` |
| `POST` | `/api/projects/{project}/lettering-style/generate` | `generate_lettering_style` | `pages.py` |
| `PUT` | `/api/projects/{project}/lettering-style` | `set_lettering_style` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/apply-bubble-preset` | `apply_bubble_preset` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/translate-bubbles` | `translate_page_bubbles` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_num}/translate-bubbles` | `translate_single_page_bubbles` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_num}/reflow` | `reflow_single_page` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/reflow` | `reflow_pages` | `pages.py` |
| `PUT` | `/api/projects/{project}/pages/{page_num}` | `replace_page` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/reorder` | `reorder_panels` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/structural` | `apply_structural_operation` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}/preview` | `page_preview` | `pages.py` |
| `GET` | `/api/projects/{project}/files/{file_path:path}` | `serve_file` | `pages.py` |
| `GET` | `/api/projects/{project}/estimate` | `estimate_stage_cost` | `pipeline.py` |
| `GET` | `/api/projects/{project}/regen-estimate` | `regen_panel_estimate` | `pipeline.py` |
| `POST` | `/api/projects/{project}/run` | `run_pipeline` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-extract` | `regen_extract` | `pipeline.py` |
| `GET` | `/api/projects/{project}/events` | `event_stream` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen` | `regen_panel` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-instructed` | `regen_panel_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-ref` | `regen_ref` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-plate` | `regen_plate` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-ref-instructed` | `regen_ref_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-plate-instructed` | `regen_plate_with_instruction` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-prop` | `regen_prop` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-prop-instructed` | `regen_prop_with_instruction` | `pipeline.py` |
| `GET` | `/api/projects/{project}/generation-jobs` | `get_generation_jobs` | `pipeline.py` |
| `POST` | `/api/projects/{project}/approve/{stage}` | `approve` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset/{stage}` | `reset_stage` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset-stale` | `reset_stale` | `pipeline.py` |
| `GET` | `/api/projects/{project}/stage-error/{stage}` | `get_stage_error` | `pipeline.py` |
| `POST` | `/api/projects` | `create_project` | `projects.py` |
| `GET` | `/api/projects` | `list_projects` | `projects.py` |
| `GET` | `/api/projects/{project_id}/status` | `project_status` | `projects.py` |
| `POST` | `/api/projects/{project_id}/cover` | `generate_cover` | `projects.py` |
| `DELETE` | `/api/projects/{project_id}` | `delete_project` | `projects.py` |
| `GET` | `/api/projects/short-stories` | `list_short_stories` | `projects.py` |
| `POST` | `/api/projects/import-story` | `import_short_story` | `projects.py` |
| `GET` | `/api/projects/{project}/story-bible` | `get_story_bible` | `stages.py` |
| `PUT` | `/api/projects/{project}/story-bible` | `update_story_bible` | `stages.py` |
| `GET` | `/api/projects/{project}/cast/primary-refs` | `get_primary_refs` | `stages.py` |
| `PUT` | `/api/projects/{project}/cast/{char_id}/primary-ref` | `set_primary_ref` | `stages.py` |
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
| `POST` | `/api/projects/{project}/images/{scene_id}/{panel_number}/flag` | `flag_image_panel` | `stages.py` |
| `DELETE` | `/api/projects/{project}/images/{scene_id}/{panel_number}/flag` | `unflag_image_panel` | `stages.py` |
| `GET` | `/api/projects/{project}/images/{scene_id}/{panel_number}/versions` | `get_image_panel_versions` | `stages.py` |
| `POST` | `/api/projects/{project}/images/{scene_id}/{panel_number}/versions/{version}/restore` | `restore_image_panel_version` | `stages.py` |
| `GET` | `/api/styles/styles` | `get_styles` | `styles.py` |
| `GET` | `/api/styles/styles/suggest-estimate` | `suggest_estimate` | `styles.py` |
| `POST` | `/api/styles/styles/suggest` | `suggest_styles` | `styles.py` |
| `POST` | `/api/styles/styles/generate-samples` | `generate_style_samples` | `styles.py` |
| `PATCH` | `/api/styles/styles/active` | `set_active_style` | `styles.py` |

## SSE Streaming

`GET /api/projects/{project}/events` — Server-sent events stream. Connect before `POST /run` to receive stage progress. Event schema: `{type, stage, done, total, message, level}`. See `events.py` for the full schema.
