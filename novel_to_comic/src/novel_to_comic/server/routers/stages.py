"""Stage data API — reads JSON artifacts from the project directory."""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from novel_to_comic.models.comic_page import ComicPage
from novel_to_comic.models.panel import PanelBreakdown, Screenplay
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import load_state

from ..deps import get_project

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


@router.get("/panels")
def list_panels(project=Depends(get_project)):
    project_dir, config, state = project
    panels_dir = project_dir / "panels"
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
    scene_dir = project_dir / "panels" / scene_id
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
    path = project_dir / "panels" / scene_id / f"panel_{panel_number:03d}.json"
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
    prompts_dir = project_dir / "prompts"
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
    scene_dir = project_dir / "prompts" / scene_id
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
    path = project_dir / "prompts" / scene_id / f"panel_{panel_number:03d}.json"
    if not path.exists():
        raise HTTPException(404, f"Prompt {scene_id}/{panel_number} not found")
    try:
        updated = ImagePrompt.model_validate(body)
    except Exception as e:
        raise HTTPException(400, f"Invalid prompt data: {e}")
    path.write_text(updated.model_dump_json(indent=2))
    return updated.model_dump()


# ── Generated Images (DRAW) ───────────────────────────────────────────────────


@router.get("/images")
def list_images(project=Depends(get_project)):
    project_dir, config, state = project
    images_dir = project_dir / "images"
    if not images_dir.exists():
        return []

    # Gather failed items from state
    generate_state = state.stages.get("generate")
    failed_items = set(generate_state.items_failed) if generate_state else set()

    # Gather done items from state
    items_done = generate_state.items_done if generate_state else 0

    results = []
    for scene_dir in sorted(images_dir.iterdir()):
        if not scene_dir.is_dir():
            continue
        for img_file in sorted(scene_dir.glob("panel_*.png")):
            stem = img_file.stem  # e.g. "panel_001"
            panel_num = int(stem.replace("panel_", ""))
            item_key = f"{scene_dir.name}/{stem}"
            is_failed = item_key in failed_items
            results.append({
                "scene_id": scene_dir.name,
                "panel_number": panel_num,
                "status": "failed" if is_failed else "done",
            })

    return results
