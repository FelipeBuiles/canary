# API Routes Reference

_Auto-generated from `server/routers/*.py`. Do not edit manually._

Base URL: `http://localhost:8000` (dev). Replace `{project}` with the project directory name.

## Routes

| Method | Path | Handler | File |
|--------|------|---------|------|
| `GET` | `/api/projects/{project}/config` | `get_config` | `config.py` |
| `PATCH` | `/api/projects/{project}/config` | `update_config` | `config.py` |
| `POST` | `/api/projects/{project}/export` | `trigger_export` | `export.py` |
| `GET` | `/api/projects/{project}/export/{fmt}` | `download_export` | `export.py` |
| `GET` | `/api/projects/{project}/pages/` | `list_pages` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}` | `get_page` | `pages.py` |
| `PATCH` | `/api/projects/{project}/pages/{page_num}` | `update_page` | `pages.py` |
| `GET` | `/api/projects/{project}/pages/{page_num}/preview` | `page_preview` | `pages.py` |
| `GET` | `/api/projects/{project}/files/{file_path:path}` | `serve_file` | `pages.py` |
| `POST` | `/api/projects/{project}/run` | `run_pipeline` | `pipeline.py` |
| `GET` | `/api/projects/{project}/events` | `event_stream` | `pipeline.py` |
| `POST` | `/api/projects/{project}/approve/{stage}` | `approve` | `pipeline.py` |
| `GET` | `/api/projects` | `list_projects` | `projects.py` |
| `GET` | `/api/projects/{project_name}/status` | `project_status` | `projects.py` |
| `GET` | `/api/projects/{project}/story-bible` | `get_story_bible` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays` | `list_screenplays` | `stages.py` |
| `GET` | `/api/projects/{project}/screenplays/{scene_id}` | `get_screenplay` | `stages.py` |
| `GET` | `/api/projects/{project}/panels` | `list_panels` | `stages.py` |
| `GET` | `/api/projects/{project}/panels/{scene_id}` | `get_panels_for_scene` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts` | `list_prompts` | `stages.py` |
| `GET` | `/api/projects/{project}/prompts/{scene_id}` | `get_prompts_for_scene` | `stages.py` |
| `GET` | `/api/projects/{project}/images` | `list_images` | `stages.py` |

## SSE Streaming

`GET /api/projects/{project}/pipeline/events` — Server-sent events stream. Connect before `POST /pipeline/run` to receive stage progress. Event schema: `{type, stage, done, total, message, level}`. See `events.py` for the full schema.
