from novel_to_comic.config import Config, load_config
from novel_to_comic.server.routers.projects import _stage_payload
from novel_to_comic.server.routers.styles import (
    clear_style_failures_after_selection,
    is_style_selected,
    set_active_style,
)
from novel_to_comic.stages.s2_style import save_suggestions
from novel_to_comic.state import StageStatus, create_initial_state, load_state


def test_set_active_style_clears_completed_style_failures(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["style"].items_failed = ["style_3"]
    save_suggestions(
        tmp_path,
        [{"label": "Ink", "template": "bold ink wash"}],
        "Demo",
    )

    result = set_active_style(
        "demo",
        {"index": 1},
        project=(tmp_path, Config(style_template="old"), state),
    )

    assert result == {
        "status": "updated",
        "index": 1,
        "style_template": "bold ink wash",
    }
    assert state.stages["style"].items_failed == []
    assert load_state(tmp_path).stages["style"].items_failed == []
    loaded_config, _env_file = load_config(tmp_path)
    assert loaded_config.style_template.strip() == "bold ink wash"


def test_selected_style_reconciliation_removes_failure_from_status_payload(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["style"].items_failed = ["style_3"]
    save_suggestions(
        tmp_path,
        [{"label": "Ink", "template": "bold ink wash"}],
        "Demo",
    )
    config = Config(style_template="bold ink wash")

    assert is_style_selected(tmp_path, config) is True
    assert clear_style_failures_after_selection(state) is True

    payload = _stage_payload(tmp_path, "style", state)
    assert payload["status"] == "complete"
    assert payload["items_failed"] == []


def test_unselected_style_does_not_clear_failures(tmp_path):
    state = create_initial_state("demo", "novel.txt")
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["style"].items_failed = ["style_3"]
    save_suggestions(
        tmp_path,
        [{"label": "Ink", "template": "bold ink wash"}],
        "Demo",
    )
    config = Config(style_template="different style")

    assert is_style_selected(tmp_path, config) is False
    assert state.stages["style"].items_failed == ["style_3"]

