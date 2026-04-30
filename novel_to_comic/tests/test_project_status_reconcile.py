from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.server.routers.projects import _reconcile_completed_draw_stage
from novel_to_comic.state import StageStatus, begin_stage, create_initial_state


def _write_prompt(project_dir: Path, scene_id: str, panel_number: int) -> None:
    prompt_dir = project_dir / "direct" / scene_id
    prompt_dir.mkdir(parents=True, exist_ok=True)
    (prompt_dir / f"panel_{panel_number:03d}.json").write_text(
        ImagePrompt(
            scene_id=scene_id,
            panel_number=panel_number,
            full_prompt="A panel.",
            width=768,
            height=1024,
            steps=28,
        ).model_dump_json()
    )


def _write_image(project_dir: Path, scene_id: str, panel_number: int) -> None:
    image_dir = project_dir / "draw" / scene_id
    image_dir.mkdir(parents=True, exist_ok=True)
    (image_dir / f"panel_{panel_number:03d}.png").write_bytes(b"image")


def test_reconcile_completed_draw_stage_recovers_running_state(tmp_path):
    for panel_number in range(1, 4):
        _write_prompt(tmp_path, "scene_001", panel_number)
        _write_image(tmp_path, "scene_001", panel_number)

    state = create_initial_state("demo", "novel.txt")
    begin_stage(state, "draw", total=3)

    changed = _reconcile_completed_draw_stage(tmp_path, Config(), state, is_running=False)

    assert changed is True
    assert state.stages["draw"].status == StageStatus.AWAITING_REVIEW
    assert state.stages["draw"].items_done == 3
    assert state.stages["draw"].items_total == 3
    assert state.stages["draw"].items_failed == []
    assert state.stages["draw"].finished_at is not None


def test_reconcile_completed_draw_stage_ignores_active_task(tmp_path):
    _write_prompt(tmp_path, "scene_001", 1)
    _write_image(tmp_path, "scene_001", 1)
    state = create_initial_state("demo", "novel.txt")
    begin_stage(state, "draw", total=1)

    changed = _reconcile_completed_draw_stage(tmp_path, Config(), state, is_running=True)

    assert changed is False
    assert state.stages["draw"].status == StageStatus.RUNNING
