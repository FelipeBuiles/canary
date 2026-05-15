from datetime import datetime, timedelta, timezone
from pathlib import Path

from novel_to_comic.config import Config
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.server.routers.projects import _reconcile_completed_draw_stage, _stage_payload
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


def test_stage_payload_not_stale_when_task_alive(tmp_path):
    """Long draw run: state.json shows started_at 10min ago, no recent
    heartbeat, but the asyncio task is still alive. Must NOT be stale —
    this is the bug the heartbeat-and-task-check fixes.
    """
    state = create_initial_state("demo", "novel.txt")
    state.stages["draw"].status = StageStatus.RUNNING
    state.stages["draw"].started_at = datetime.now(timezone.utc) - timedelta(minutes=10)
    state.stages["draw"].last_progress_at = None

    payload = _stage_payload(tmp_path, "draw", state, is_task_alive=True)
    assert payload["stale"] is False


def test_stage_payload_stale_when_task_gone_and_heartbeat_old(tmp_path):
    """Server-restart scenario: state.json says RUNNING but no live task.
    is_stale should fire so the UI can offer Reset.
    """
    state = create_initial_state("demo", "novel.txt")
    state.stages["draw"].status = StageStatus.RUNNING
    state.stages["draw"].started_at = datetime.now(timezone.utc) - timedelta(minutes=20)
    state.stages["draw"].last_progress_at = (
        datetime.now(timezone.utc) - timedelta(minutes=15)
    )

    payload = _stage_payload(tmp_path, "draw", state, is_task_alive=False)
    assert payload["stale"] is True


def test_stage_payload_in_flight_passthrough(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    in_flight = [{"scene_id": "s_1", "panel_number": 3, "started_at": "t"}]
    payload = _stage_payload(tmp_path, "draw", state, in_flight=in_flight)
    assert payload["in_flight"] == in_flight


def test_stage_payload_in_flight_defaults_to_empty(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    payload = _stage_payload(tmp_path, "draw", state)
    assert payload["in_flight"] == []


def test_stage_payload_includes_last_progress_at(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    moment = datetime.now(timezone.utc)
    state.stages["draw"].last_progress_at = moment
    payload = _stage_payload(tmp_path, "draw", state)
    assert payload["last_progress_at"] == moment.isoformat()
