"""Stage data API — reads JSON artifacts from the project directory."""

import json
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic.models.comic_page import ComicPage
from novel_to_comic.models.layout_plan import LayoutPlan
from novel_to_comic.models.panel import PanelBreakdown, Screenplay
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.panel_versions import archived_panel_version_count, list_panel_versions, restore_panel_version
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import render_panel_prompt_body
from novel_to_comic.state import load_state

from ..auth import get_current_user
from ..deps import get_project, project_key
from ..generation_jobs import find_active_generation_job
from ..panel_acceptance import accept_panel, clear_panel_acceptance, is_panel_accepted

router = APIRouter()


# ── Story Bible (EXTRACT) ─────────────────────────────────────────────────────


@router.get("/story-bible")
def get_story_bible(project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "story_bible.json"
    if not path.exists():
        raise HTTPException(404, "Story bible not found")
    return StoryBible.model_validate_json(path.read_text()).model_dump()


@router.put("/story-bible")
def update_story_bible(body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "story_bible.json"
    if not path.exists():
        raise HTTPException(404, "Story bible not found")
    
    try:
        # Validate the incoming body against the StoryBible schema
        updated_bible = StoryBible.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"Invalid story bible data: {e}")
        
    path.write_text(updated_bible.model_dump_json(indent=2))
    return updated_bible.model_dump()


# ── Screenplays (ADAPT) ───────────────────────────────────────────────────────


@router.get("/screenplays")
def list_screenplays(project=Depends(get_project)):
    project_dir, config, state = project
    sp_dir = project_dir / "screenplays"
    if not sp_dir.exists():
        return []
    results = []
    for f in sorted(sp_dir.glob("*.json")):
        try:
            sp = Screenplay.model_validate_json(f.read_text())
            results.append({
                "scene_id": sp.scene_id,
                "title": sp.scene_id.replace("_", " ").title(),
                "beat_count": len(sp.beats),
            })
        except Exception:
            pass
    return results


@router.get("/screenplays/{scene_id}")
def get_screenplay(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "screenplays" / f"{scene_id}.json"
    if not path.exists():
        raise HTTPException(404, f"Screenplay for {scene_id} not found")
    return Screenplay.model_validate_json(path.read_text()).model_dump()


# ── Panel Breakdowns (STORYBOARD) ─────────────────────────────────────────────


@router.get("/layout-plan")
def get_layout_plan(project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "plan" / "layout_plan.json"
    if not path.exists():
        raise HTTPException(404, "Layout plan not found")
    return LayoutPlan.model_validate_json(path.read_text()).model_dump()


# ── Panel Breakdowns (STORYBOARD) ─────────────────────────────────────────────


@router.get("/panels")
def list_panels(project=Depends(get_project)):
    project_dir, config, state = project
    panels_dir = project_dir / "storyboard"
    if not panels_dir.exists():
        return []
    results = []
    for scene_dir in sorted(panels_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        count = len(list(scene_dir.glob("panel_*.json")))
        if count > 0:
            results.append({
                "scene_id": scene_dir.name,
                "panel_count": count,
            })
    return results


@router.get("/panels/{scene_id}")
def get_panels_for_scene(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    scene_dir = project_dir / "storyboard" / scene_id
    if not scene_dir.is_dir():
        raise HTTPException(404, f"Panels for {scene_id} not found")
    results = []
    for f in sorted(scene_dir.glob("panel_*.json")):
        try:
            pb = PanelBreakdown.model_validate_json(f.read_text())
            results.append(pb.model_dump())
        except Exception:
            pass
    return results


@router.put("/panels/{scene_id}/{panel_number}")
def update_panel(scene_id: str, panel_number: int, body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "storyboard" / scene_id / f"panel_{panel_number:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Panel {scene_id}/{panel_number} not found")
    try:
        updated = PanelBreakdown.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"Invalid panel data: {e}")
    path.write_text(updated.model_dump_json(indent=2))
    return updated.model_dump()


# ── Image Prompts (DIRECT) ────────────────────────────────────────────────────


@router.get("/prompts")
def list_prompts(project=Depends(get_project)):
    project_dir, config, state = project
    prompts_dir = project_dir / "direct"
    if not prompts_dir.exists():
        return []
    results = []
    for scene_dir in sorted(prompts_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        count = len(list(scene_dir.glob("panel_*.json")))
        if count > 0:
            results.append({
                "scene_id": scene_dir.name,
                "prompt_count": count,
            })
    return results


@router.get("/prompts/{scene_id}")
def get_prompts_for_scene(scene_id: str, project=Depends(get_project)):
    project_dir, config, state = project
    scene_dir = project_dir / "direct" / scene_id
    if not scene_dir.is_dir():
        raise HTTPException(404, f"Prompts for {scene_id} not found")
    results = []
    for f in sorted(scene_dir.glob("panel_*.json")):
        try:
            ip = ImagePrompt.model_validate_json(f.read_text())
            results.append(ip.model_dump())
        except Exception:
            pass
    return results


@router.put("/prompts/{scene_id}/{panel_number}")
def update_prompt(scene_id: str, panel_number: int, body: dict, project=Depends(get_project)):
    project_dir, config, state = project
    path = project_dir / "direct" / scene_id / f"panel_{panel_number:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Prompt {scene_id}/{panel_number} not found")
    try:
        updated = ImagePrompt.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"Invalid prompt data: {e}")
    updated.full_prompt = render_panel_prompt_body(updated)
    path.write_text(updated.model_dump_json(indent=2))
    return updated.model_dump()


# ── Generated Images (DRAW) ───────────────────────────────────────────────────


@router.get("/images")
def list_images(
    request: Request,
    project_name: str,
    project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    project_dir, config, state = project
    pkey = project_key(user_id, project_name)
    images_dir = project_dir / "draw"
    if not images_dir.exists():
        return []

    generate_state = state.stages.get("draw")
    failed_items = set(generate_state.items_failed) if generate_state else set()

    def failure_summary(scene_id: str, stem: str) -> tuple[str | None, str | None]:
        failure_path = images_dir / scene_id / f"{stem}.png.failure.json"
        if not failure_path.exists():
            return None, None
        try:
            data = json.loads(failure_path.read_text())
            classification = data.get("classification")
            user_message = data.get("user_message")
            if not isinstance(user_message, str) or not user_message.strip():
                error = data.get("error")
                if isinstance(error, dict):
                    message = error.get("message")
                    if isinstance(message, str):
                        user_message = message
            if isinstance(user_message, str) and len(user_message) > 180:
                user_message = f"{user_message[:177].rstrip()}..."
            return (
                classification if isinstance(classification, str) else None,
                user_message.strip() if isinstance(user_message, str) else None,
            )
        except Exception:
            return None, None

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

            prompt_path = project_dir / "direct" / scene_dir.name / f"{stem}.json"
            planned_panel_id = None
            if prompt_path.exists():
                try:
                    planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
                except Exception:
                    planned_panel_id = None
            failure_classification, failure_message = failure_summary(scene_dir.name, stem)
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
                "accepted": is_panel_accepted(project_dir, scene_dir.name, panel_num),
                "version_count": archived_panel_version_count(project_dir, scene_dir.name, panel_num),
                "failure_classification": failure_classification,
                "failure_message": failure_message,
            })
            seen.add((scene_dir.name, panel_num))

        for failure_file in sorted(scene_dir.glob("panel_*.png.failure.json")):
            match = re.search(r"panel_(\d+)\.png\.failure\.json$", failure_file.name)
            if not match:
                continue
            panel_num = int(match.group(1))
            if (scene_dir.name, panel_num) in seen:
                continue
            stem = f"panel_{panel_num:03d}"
            prompt_path = project_dir / "direct" / scene_dir.name / f"{stem}.json"
            planned_panel_id = None
            if prompt_path.exists():
                try:
                    planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
                except Exception:
                    planned_panel_id = None
            failure_classification, failure_message = failure_summary(scene_dir.name, stem)
            results.append({
                "scene_id": scene_dir.name,
                "panel_number": panel_num,
                "planned_panel_id": planned_panel_id,
                "status": "failed",
                "image_available": False,
                "accepted": False,
                "version_count": archived_panel_version_count(project_dir, scene_dir.name, panel_num),
                "failure_classification": failure_classification,
                "failure_message": failure_message,
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

        prompt_path = project_dir / "direct" / scene_id / f"panel_{panel_num:03d}.json"
        planned_panel_id = None
        if prompt_path.exists():
            try:
                planned_panel_id = ImagePrompt.model_validate_json(prompt_path.read_text()).planned_panel_id
            except Exception:
                planned_panel_id = None
        failure_classification, failure_message = failure_summary(scene_id, f"panel_{panel_num:03d}")
        results.append({
            "scene_id": scene_id,
            "panel_number": panel_num,
            "planned_panel_id": planned_panel_id,
            "status": "failed",
            "image_available": False,
            "accepted": False,
            "version_count": archived_panel_version_count(project_dir, scene_id, panel_num),
            "failure_classification": failure_classification,
            "failure_message": failure_message,
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
