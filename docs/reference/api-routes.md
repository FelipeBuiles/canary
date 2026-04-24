# API Routes Reference

**Manually maintained.** Sync changes with the actual router files in
`novel_to_comic/src/novel_to_comic/server/routers/`.

Base URL: `http://localhost:8000` (when running `pipeline serve`).
Replace `{project}` with the project directory name.

---

## Projects

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects` | `list_projects` | `projects.py` |
| `GET` | `/api/projects/{project}/status` | `project_status` | `projects.py` |

## Config

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/config` | `get_config` | `config.py` |
| `PATCH` | `/api/projects/{project}/config` | `update_config` | `config.py` |

## Pipeline

| Method | Path | Handler | File |
|--------|------|---------|------|
| `POST` | `/api/projects/{project}/run` | `run_pipeline` | `pipeline.py` |
| `POST` | `/api/projects/{project}/approve/{stage}` | `approve` | `pipeline.py` |
| `POST` | `/api/projects/{project}/reset/{stage}` | `reset_stage` | `pipeline.py` |
| `GET` | `/api/projects/{project}/events` | `event_stream` | `pipeline.py` |
| `GET` | `/api/projects/{project}/errors/{stage}` | `get_stage_error` | `pipeline.py` |

**Query parameters for `POST /run`:**
- `stage` (optional): run from a specific stage onward, clearing downstream outputs. Valid stages: `extract`, `cast`, `adapt`, `plan`, `storyboard`, `direct`, `draw`, `compose`.

**SSE:** `GET /api/projects/{project}/events` streams stage progress events. Connect before triggering a run to receive all events.

## Stages (Artifacts)

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/story-bible` | `get_story_bible` | `stages.py` |
| `PUT` | `/api/projects/{project}/story-bible` | `update_story_bible` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays` | `list_screenplays` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays/{scene_id}` | `get_screenplay` | `stages.py` |
| `GET` | `/api/projects/{project}/layout-plan` | `get_layout_plan` | `stages.py` |
| `GET` | `/api/projects/{project}/panels` | `list_panels` | `stages.py` |
| `GET` | `/api/projects/{project}/panels/{scene_id}` | `get_panels_for_scene` | `stages.py` |
| `PUT` | `/api/projects/{project}/panels/{scene_id}/{panel_number}` | `update_panel` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts` | `list_prompts` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts/{scene_id}` | `get_prompts_for_scene` | `stages.py` |
| `PUT` | `/api/projects/{project}/prompts/{scene_id}/{panel_number}` | `update_prompt` | `stages.py` |
| `GET` | `/api/projects/{project}/images` | `list_images` | `stages.py` |

## Pages (compose / Stage 8)

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/pages` | `list_pages` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}` | `get_page` | `pages.py` |
| `PUT` | `/api/projects/{project}/pages/{page_num}` | `update_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}/preview` | `page_preview` | `pages.py` |
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
```

`level`: `"info"` | `"warn"` | `"error"` | `"dim"` | `"bold"`
