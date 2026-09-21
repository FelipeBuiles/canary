# API Routes Reference

_Auto-generated from `server/routers/*.py`. Do not edit manually._

Base URL: `http://localhost:8000` (dev). Replace `{project}` with the project directory name.

## Routes

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/account/model-settings` | `get_model_settings` | `account_models.py` |
| `PATCH` | `/api/account/model-settings` | `patch_model_settings` | `account_models.py` |
| `GET` | `/api/backoffice` | `backoffice_snapshot` | `backoffice.py` |
| `POST` | `/api/backoffice/users/{user_id}/credits` | `grant_credits` | `backoffice.py` |
| `GET` | `/api/billing/packages` | `list_packages` | `billing.py` |
| `POST` | `/api/billing/checkout` | `create_checkout` | `billing.py` |
| `POST` | `/api/billing/webhook` | `stripe_webhook` | `billing.py` |
| `GET` | `/api/cast_assets/cast/review` | `cast_review` | `cast_assets.py` |
| `GET` | `/api/cast_assets/asset-regen-estimate` | `asset_regen_estimate` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-ref` | `regen_ref` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-state-ref` | `regen_state_ref` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-plate` | `regen_plate` | `cast_assets.py` |
| `POST` | `/api/cast_assets/locations/{loc_id}/states/{state_id}/regenerate` | `regenerate_location_state` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-prop` | `regen_prop` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-ref-instructed` | `regen_ref_with_instruction` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-plate-instructed` | `regen_plate_with_instruction` | `cast_assets.py` |
| `POST` | `/api/cast_assets/regen-prop-instructed` | `regen_prop_with_instruction` | `cast_assets.py` |
| `POST` | `/api/cast_assets/characters/{char_id}/states/{state_id}/regenerate-instructed` | `regenerate_character_state_instructed` | `cast_assets.py` |
| `POST` | `/api/cast_assets/locations/{loc_id}/states/{state_id}/regenerate-instructed` | `regenerate_location_state_instructed` | `cast_assets.py` |
| `GET` | `/api/cast_assets/character-ref-versions` | `get_character_ref_versions` | `cast_assets.py` |
| `POST` | `/api/cast_assets/character-ref-versions/restore` | `restore_character_ref_version` | `cast_assets.py` |
| `GET` | `/api/cast_assets/location-plate-versions` | `get_location_plate_versions` | `cast_assets.py` |
| `POST` | `/api/cast_assets/location-plate-versions/restore` | `restore_location_plate_version` | `cast_assets.py` |
| `GET` | `/api/projects/{project}/config` | `get_config` | `config.py` |
| `PATCH` | `/api/projects/{project}/config` | `update_config` | `config.py` |
| `GET` | `/api/credits/pricing-reference` | `pricing_reference` | `credits.py` |
| `GET` | `/api/credits/balance` | `balance` | `credits.py` |
| `GET` | `/api/credits/history` | `history` | `credits.py` |
| `GET` | `/api/editorial/editorial` | `get_editorial` | `editorial.py` |
| `GET` | `/api/editorial/editorial/source` | `get_editorial_source` | `editorial.py` |
| `POST` | `/api/editorial/editorial/decisions` | `post_editorial_decisions` | `editorial.py` |
| `POST` | `/api/editorial/story-changes/preview` | `preview_story_change` | `editorial.py` |
| `POST` | `/api/editorial/story-changes/{proposal_id}/apply` | `apply_story_change` | `editorial.py` |
| `POST` | `/api/events` | `ingest_web_event` | `events.py` |
| `GET` | `/api/projects/{project}/export/preflight` | `get_preflight` | `export.py` |
| `POST` | `/api/projects/{project}/export/preflight` | `run_preflight` | `export.py` |
| `POST` | `/api/projects/{project}/export` | `trigger_export` | `export.py` |
| `GET` | `/api/projects/{project}/export/{fmt}` | `download_export` | `export.py` |
| `GET` | `/api/files/files/{file_path:path}` | `serve_project_file` | `files.py` |
| `GET` | `/api/labs/models` | `list_models` | `labs.py` |
| `GET` | `/api/labs/fixtures/default` | `get_default_fixture` | `labs.py` |
| `GET` | `/api/labs/fixtures/default/refs/{filename}` | `get_default_fixture_ref` | `labs.py` |
| `POST` | `/api/labs/runs` | `create_run` | `labs.py` |
| `GET` | `/api/labs/runs` | `list_runs` | `labs.py` |
| `GET` | `/api/labs/runs/{run_id}` | `get_run` | `labs.py` |
| `DELETE` | `/api/labs/runs/{run_id}` | `delete_run` | `labs.py` |
| `GET` | `/api/labs/runs/{run_id}/cells/{image_idx}/{variant}/{model_id}/image` | `get_cell_image` | `labs.py` |
| `GET` | `/api/lettering/pages/{page_number}/lettering` | `get_lettering` | `lettering.py` |
| `PUT` | `/api/lettering/pages/{page_number}/lettering` | `put_lettering` | `lettering.py` |
| `POST` | `/api/lettering/pages/{page_number}/lettering/reset` | `reset_page_lettering` | `lettering.py` |
| `GET` | `/api/lettering/lettering/style` | `get_lettering_style` | `lettering.py` |
| `PUT` | `/api/lettering/lettering/style` | `put_lettering_style` | `lettering.py` |
| `GET` | `/api/lettering/pages/{page_number}/composite/{rendition}` | `get_page_composite` | `lettering.py` |
| `GET` | `/api/lettering/lettering/translation-estimate` | `get_translation_estimate` | `lettering.py` |
| `POST` | `/api/lettering/lettering/translate` | `post_translation` | `lettering.py` |
| `POST` | `/api/operator_billing/refunds` | `refund_unused_credit_grant` | `operator_billing.py` |
| `GET` | `/api/projects/{project}/pages` | `list_pages` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}` | `get_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/renders/{revision}` | `get_page_render` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/renders/{revision}/correction` | `read_render_correction` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/renders/{revision}/preview/{rendition}` | `get_page_render_preview` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/generate/estimate` | `estimate_remaining_page_generation` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/generate/estimate` | `estimate_page_generation` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/analyze/estimate` | `estimate_page_analysis` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/generate` | `generate_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/checks/estimate` | `estimate_missing_page_checks` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/checks/recover` | `recover_missing_page_checks` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/analyze` | `analyze_page` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/issues` | `create_page_issue` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/issues/{issue_id}/accept` | `accept_page_issue` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/issues/{issue_id}/dismiss` | `dismiss_automated_page_issue` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/corrections/preview` | `preview_page_correction` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/corrections` | `submit_page_correction` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/visual-review/estimate` | `visual_review_estimate` | `pages.py` |
| `POST` | `/api/projects/{project}/pages/{page_number}/visual-review` | `visual_review_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_number}/visual-review` | `read_saved_visual_review` | `pages.py` |
| `GET` | `/api/projects/{project}/estimate` | `estimate_stage_cost` | `pipeline.py` |
| `POST` | `/api/projects/{project}/run` | `run_pipeline` | `pipeline.py` |
| `POST` | `/api/projects/{project}/regen-extract` | `regen_extract` | `pipeline.py` |
| `GET` | `/api/projects/{project}/events` | `event_stream` | `pipeline.py` |
| `GET` | `/api/projects/{project}/generation-jobs` | `get_generation_jobs` | `pipeline.py` |
| `POST` | `/api/projects/{project}/approve/{stage}` | `approve` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset/{stage}` | `reset_stage` | `pipeline.py` |
| `GET` | `/api/projects/{project}/stage-error/{stage}` | `get_stage_error` | `pipeline.py` |
| `POST` | `/api/projects` | `create_project` | `projects.py` |
| `GET` | `/api/projects` | `list_projects` | `projects.py` |
| `PATCH` | `/api/projects/{project_id}` | `rename_project` | `projects.py` |
| `GET` | `/api/projects/{project_id}/status` | `project_status` | `projects.py` |
| `GET` | `/api/projects/{project_id}/cover-estimate` | `project_cover_estimate` | `projects.py` |
| `POST` | `/api/projects/{project_id}/cover` | `generate_cover` | `projects.py` |
| `DELETE` | `/api/projects/{project_id}` | `delete_project` | `projects.py` |
| `GET` | `/api/projects/short-stories` | `list_short_stories` | `projects.py` |
| `POST` | `/api/projects/import-story` | `import_short_story` | `projects.py` |
| `GET` | `/api/projects/{project}/story` | `get_story` | `stages.py` |
| `GET` | `/api/projects/{project}/story-bible` | `get_story_bible` | `stages.py` |
| `PUT` | `/api/projects/{project}/story-bible` | `update_story_bible` | `stages.py` |
| `GET` | `/api/projects/{project}/brief` | `get_brief` | `stages.py` |
| `PUT` | `/api/projects/{project}/brief` | `update_brief` | `stages.py` |
| `GET` | `/api/projects/{project}/validation/{stage}` | `get_stage_validation` | `stages.py` |
| `GET` | `/api/projects/{project}/plan/review-draft` | `get_plan_review_draft` | `stages.py` |
| `GET` | `/api/projects/{project}/adaptation` | `get_book_adaptation` | `stages.py` |
| `GET` | `/api/projects/{project}/book-plan` | `get_book_plan` | `stages.py` |
| `GET` | `/api/projects/{project}/comic-pages` | `list_comic_pages` | `stages.py` |
| `GET` | `/api/projects/{project}/comic-pages/{page_number}` | `get_comic_page` | `stages.py` |
| `GET` | `/api/projects/{project}/cast/primary-refs` | `get_primary_refs` | `stages.py` |
| `PUT` | `/api/projects/{project}/cast/{char_id}/primary-ref` | `set_primary_ref` | `stages.py` |
| `GET` | `/api/styles/styles` | `get_styles` | `styles.py` |
| `GET` | `/api/styles/styles/{suggestion_id}/proof/{kind}` | `get_style_lettering_proof` | `styles.py` |
| `GET` | `/api/styles/styles/suggest-estimate` | `suggest_estimate` | `styles.py` |
| `GET` | `/api/styles/styles/sample-estimate` | `style_sample_estimate` | `styles.py` |
| `GET` | `/api/styles/styles/direction-estimate` | `style_direction_estimate` | `styles.py` |
| `POST` | `/api/styles/styles/direction` | `create_style_direction` | `styles.py` |
| `POST` | `/api/styles/styles/suggest` | `suggest_styles` | `styles.py` |
| `POST` | `/api/styles/styles/generate-samples` | `generate_style_samples` | `styles.py` |
| `POST` | `/api/styles/styles/validation` | `generate_style_validation` | `styles.py` |
| `PATCH` | `/api/styles/styles/active` | `set_active_style` | `styles.py` |

## SSE Streaming

`GET /api/projects/{project}/events` — Server-sent events stream. Connect before `POST /run` to receive stage progress. Event schema: `{type, stage, done, total, message, level}`. See `events.py` for the full schema.
