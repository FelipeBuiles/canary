"""Stage data API — reads JSON artifacts from the project directory."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic import artifacts

from novel_to_comic.models.panel import PanelBreakdown
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.panel_store import save_breakdown, save_prompt
from novel_to_comic.panel_versions import archived_panel_version_count, list_panel_versions, restore_panel_version
from novel_to_comic.models.story_bible import StoryBible

from ..auth import get_current_user
from ..narration_editor import apply_patch as apply_narration_patch, estimate_patch_impact
from ..deps import get_project, project_key
from ..generation_jobs import find_active_generation_job
from ..panel_acceptance import accept_panel, clear_panel_acceptance, is_panel_accepted

router = APIRouter()


def _image_revision(path: Path) -> str | None:
    if not path.exists():
        return None
    stat = path.stat()
    return f"{stat.st_mtime_ns}-{stat.st_size}"


# ── Story Bible (EXTRACT) ─────────────────────────────────────────────────────


@router.get("/story-bible")
def get_story_bible(project=Depends(get_project)):
    project_dir, config, state = project
    if not artifacts.story_bible_path(project_dir).exists():
        raise HTTPException(404, "Story bible not found")
    return artifacts.read_story_bible(project_dir).model_dump()


@router.put("/story-bible")
def update_story_bible(body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    if not artifacts.story_bible_path(project_dir).exists():
        raise HTTPException(404, "Story bible not found")
    try:
        updated_bible = StoryBible.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"Invalid story bible data: {e}")
    artifacts.write_story_bible(project_dir, updated_bible)
    return updated_bible.model_dump()


# ── Screenplays (ADAPT) ───────────────────────────────────────────────────────


@router.get("/screenplays")
def list_screenplays(project=Depends(get_project)):
    project_dir, config, state = project
    return [
        {"scene_id": sp.scene_id, "title": sp.scene_id.replace("_", " ").title(), "beat_count": len(sp.beats)}
        for sp in artifacts.list_screenplays(project_dir)
    ]


@router.get("/screenplays/{scene_id}")
def get_screenplay(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    if not artifacts.screenplay_path(project_dir, scene_id).exists():
        raise HTTPException(404, f"Screenplay for {scene_id} not found")
    return artifacts.read_screenplay(project_dir, scene_id).model_dump()


# ── Panel Breakdowns (STORYBOARD) ─────────────────────────────────────────────


@router.get("/layout-plan")
def get_layout_plan(project=Depends(get_project)):
    project_dir, config, state = project
    if not artifacts.layout_plan_path(project_dir).exists():
        raise HTTPException(404, "Layout plan not found")
    return artifacts.read_layout_plan(project_dir).model_dump()


@router.post("/layout-plan/narration-decisions/{beat_id}/impact")
def estimate_narration_decision_impact(beat_id: str, body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    try:
        return estimate_patch_impact(project_dir, beat_id, body, config, state)
    except FileNotFoundError:
        raise HTTPException(404, "Layout plan not found")
    except KeyError:
        raise HTTPException(404, f"Narration decision {beat_id} not found")


@router.put("/layout-plan/narration-decisions/{beat_id}")
def update_narration_decision(beat_id: str, body: dict, project=Depends(get_project)):
    project_dir, _config, _state = project
    try:
        decision, impact = apply_narration_patch(project_dir, beat_id, body)
    except FileNotFoundError:
        raise HTTPException(404, "Layout plan not found")
    except KeyError:
        raise HTTPException(404, f"Narration decision {beat_id} not found")
    except Exception as e:
        raise HTTPException(400, f"Invalid narration decision update: {e}")
    return {"decision": decision.model_dump(), "impact": impact}


# ── Panel Breakdowns (STORYBOARD) ─────────────────────────────────────────────


@router.get("/panels")
def list_panels(project=Depends(get_project)):
    project_dir, config, state = project
    storyboard_dir = project_dir / "storyboard"
    if not storyboard_dir.exists():
        return []
    return [
        {"scene_id": d.name, "panel_count": len(list(d.glob("panel_*.json")))}
        for d in sorted(storyboard_dir.iterdir())
        if d.is_dir() and list(d.glob("panel_*.json"))
    ]


@router.get("/panels/{scene_id}")
def get_panels_for_scene(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    scene_dir = project_dir / "storyboard" / scene_id
    if not scene_dir.is_dir():
        raise HTTPException(404, f"Panels for {scene_id} not found")
    results = []
    for f in sorted(scene_dir.glob("panel_*.json")):
        try:
            results.append(PanelBreakdown.model_validate_json(f.read_text()).model_dump())
        except Exception:
            pass
    return results


@router.put("/panels/{scene_id}/{panel_number}")
def update_panel(scene_id: str, panel_number: int, body: dict, project=Depends(get_project)):
    project_dir, _config, _state = project
    if not artifacts.panel_breakdown_path(project_dir, scene_id, panel_number).exists():
        raise HTTPException(404, f"Panel {scene_id}/{panel_number} not found")
    try:
        updated = save_breakdown(project_dir, scene_id, panel_number, body)
    except Exception as e:
        raise HTTPException(400, f"Invalid panel data: {e}")
    return updated.model_dump()


# ── Image Prompts (DIRECT) ────────────────────────────────────────────────────


@router.get("/prompts")
def list_prompts(project=Depends(get_project)):
    project_dir, config, state = project
    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return []
    return [
        {"scene_id": d.name, "prompt_count": len(list(d.glob("panel_*.json")))}
        for d in sorted(prompts_dir.iterdir())
        if d.is_dir() and list(d.glob("panel_*.json"))
    ]


@router.get("/prompts/{scene_id}")
def get_prompts_for_scene(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    scene_dir = project_dir / "direct" / scene_id
    if not scene_dir.is_dir():
        raise HTTPException(404, f"Prompts for {scene_id} not found")
    return [p.model_dump() for p in artifacts.list_panel_prompts(project_dir, scene_id)]


@router.put("/prompts/{scene_id}/{panel_number}")
async def update_prompt(scene_id: str, panel_number: int, body: dict, project=Depends(get_project)):
    project_dir, _config, _state = project
    if not artifacts.panel_prompt_path(project_dir, scene_id, panel_number).exists():
        raise HTTPException(404, f"Prompt {scene_id}/{panel_number} not found")
    try:
        updated = save_prompt(project_dir, scene_id, panel_number, body)
    except Exception as e:
        raise HTTPException(400, f"Invalid prompt data: {e}")
    return updated.model_dump()


# ── Generated Images (DRAW) ───────────────────────────────────────────────────


@router.get("/images")
def list_images(
    request: Request,
    project_id: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_id)
    images_dir = project_dir / "draw"
    if not images_dir.exists():
        return []

    generate_state = state.stages.get("draw")
    failed_items = set(generate_state.items_failed) if generate_state else set()

    def failure_summary(scene_id: str, panel_num: int) -> tuple[str | None, str | None, str | None]:
        failure_path = artifacts.panel_image_failure_path(project_dir, scene_id, panel_num)
        if not failure_path.exists():
            return None, None, None
        try:
            data = json.loads(failure_path.read_text())
            classification = data.get("classification")
            user_message = data.get("user_message")
            error = data.get("error") if isinstance(data.get("error"), dict) else None
            raw_message = error.get("message") if error else None
            raw_type = error.get("type") if error else None
            if not isinstance(user_message, str) or not user_message.strip():
                if isinstance(raw_message, str):
                    user_message = raw_message
            if isinstance(user_message, str) and len(user_message) > 180:
                user_message = f"{user_message[:177].rstrip()}..."
            detail: str | None = None
            if isinstance(raw_message, str) and raw_message.strip():
                prefix = f"{raw_type}: " if isinstance(raw_type, str) and raw_type else ""
                detail = (prefix + raw_message).strip()
                if len(detail) > 2000:
                    detail = f"{detail[:1997].rstrip()}..."
            return (
                classification if isinstance(classification, str) else None,
                user_message.strip() if isinstance(user_message, str) else None,
                detail,
            )
        except Exception:
            return None, None, None

    results = []
    seen: set[tuple[str, int]] = set()
    for scene_dir in sorted(images_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        for img_file in sorted(scene_dir.glob("panel_*.png")):
            stem = img_file.stem
            panel_num = int(stem.replace("panel_", ""))
            item_key = f"{scene_dir.name}/{stem}"
            is_failed = item_key in failed_items

            prompt_path = artifacts.panel_prompt_path(project_dir, scene_dir.name, panel_num)
            planned_panel_id = None
            if prompt_path.exists():
                try:
                    planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
                except Exception:
                    planned_panel_id = None
            failure_classification, failure_message, failure_detail = failure_summary(scene_dir.name, panel_num)
            active_job = find_active_generation_job(
                request.app,
                pkey,
                "panel_regen",
                {"scene_id": scene_dir.name, "panel_number": panel_num},
            )
            if active_job:
                status: str = active_job.status
            elif is_failed or failure_classification:
                status = "failed"
            else:
                status = "done"

            results.append({
                "scene_id": scene_dir.name,
                "panel_number": panel_num,
                "planned_panel_id": planned_panel_id,
                "status": status,
                "image_available": True,
                "image_revision": _image_revision(img_file),
                "accepted": is_panel_accepted(project_dir, scene_dir.name, panel_num),
                "version_count": archived_panel_version_count(project_dir, scene_dir.name, panel_num),
                "failure_classification": failure_classification,
                "failure_message": failure_message,
                "failure_detail": failure_detail,
            })
            seen.add((scene_dir.name, panel_num))

        for failure_file in sorted(scene_dir.glob("panel_*.png.failure.json")):
            match = re.search(r"panel_(\d+)\.png\.failure\.json$", failure_file.name)
            if not match:
                continue
            panel_num = int(match.group(1))
            if (scene_dir.name, panel_num) in seen:
                continue
            prompt_path = artifacts.panel_prompt_path(project_dir, scene_dir.name, panel_num)
            planned_panel_id = None
            if prompt_path.exists():
                try:
                    planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
                except Exception:
                    planned_panel_id = None
            failure_classification, failure_message, failure_detail = failure_summary(scene_dir.name, panel_num)
            results.append({
                "scene_id": scene_dir.name,
                "panel_number": panel_num,
                "planned_panel_id": planned_panel_id,
                "status": "failed",
                "image_available": False,
                "image_revision": None,
                "accepted": False,
                "version_count": archived_panel_version_count(project_dir, scene_dir.name, panel_num),
                "failure_classification": failure_classification,
                "failure_message": failure_message,
                "failure_detail": failure_detail,
            })
            seen.add((scene_dir.name, panel_num))

    for failed_item in sorted(failed_items):
        parts = failed_item.split("/")
        scene_idx = next((idx for idx in range(len(parts) - 1, -1, -1) if parts[idx].startswith("scene_")), -1)
        scene_id = parts[scene_idx] if scene_idx >= 0 else (parts[0] if parts else "")
        panel_part = parts[scene_idx + 1] if scene_idx >= 0 and scene_idx + 1 < len(parts) else (parts[1] if len(parts) > 1 else "")
        match = re.search(r"panel_(\d+)", panel_part)
        if not scene_id or not match:
            continue
        panel_num = int(match.group(1))
        if (scene_id, panel_num) in seen:
            continue

        prompt_path = artifacts.panel_prompt_path(project_dir, scene_id, panel_num)
        planned_panel_id = None
        if prompt_path.exists():
            try:
                planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
            except Exception:
                planned_panel_id = None
        failure_classification, failure_message, failure_detail = failure_summary(scene_id, panel_num)
        results.append({
            "scene_id": scene_id,
            "panel_number": panel_num,
            "planned_panel_id": planned_panel_id,
            "status": "failed",
            "image_available": False,
            "image_revision": None,
            "accepted": False,
            "version_count": archived_panel_version_count(project_dir, scene_id, panel_num),
            "failure_classification": failure_classification,
            "failure_message": failure_message,
            "failure_detail": failure_detail,
        })
        seen.add((scene_id, panel_num))

    return results


@router.post("/images/{scene_id}/{panel_number}/accept")
def accept_image_panel(scene_id: str, panel_number: int, project=Depends(get_project)):
    project_dir, config, state = project
    try:
        entry = accept_panel(project_dir, scene_id, panel_number)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "accepted": True,
        "accepted_at": entry["accepted_at"],
    }


@router.delete("/images/{scene_id}/{panel_number}/accept")
def unaccept_image_panel(scene_id: str, panel_number: int, project=Depends(get_project)):
    project_dir, config, state = project
    clear_panel_acceptance(project_dir, scene_id, panel_number)
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "accepted": False,
    }


@router.get("/images/{scene_id}/{panel_number}/versions")
def get_image_panel_versions(scene_id: str, panel_number: int, project=Depends(get_project)):
    project_dir, config, state = project
    versions = list_panel_versions(project_dir, scene_id, panel_number)
    archived_count = len([version for version in versions if not version.get("current")])
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "has_history": archived_count > 0,
        "versions": versions,
    }


@router.post("/images/{scene_id}/{panel_number}/versions/{version}/restore")
def restore_image_panel_version(scene_id: str, panel_number: int, version: int, project=Depends(get_project)):
    project_dir, config, state = project
    try:
        restored = restore_panel_version(project_dir, scene_id, panel_number, version)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    clear_panel_acceptance(project_dir, scene_id, panel_number)
    return {
        "scene_id": scene_id,
        "panel_number": panel_number,
        "restored": restored,
        "versions": list_panel_versions(project_dir, scene_id, panel_number),
    }
