from pathlib import Path

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.credits import estimate_stage_credit_breakdown
from novel_to_comic.state import create_initial_state


@pytest.mark.parametrize(
    ("preset", "expected_range"),
    [
        ("fast", range(2, 21)),
        ("balanced", range(3, 31)),
        ("quality", range(10, 101)),
    ],
)
def test_extract_estimate_for_typical_project_stays_in_sane_range(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    preset: str,
    expected_range: range,
):
    monkeypatch.setenv("PULP_CREDITS_PER_PROVIDER_USD", "100")
    monkeypatch.setenv("PULP_MODEL_COST_MARKUP", "1.0")
    monkeypatch.setenv("PULP_RESERVATION_BUFFER", "1.25")

    novel_path = tmp_path / "novel.txt"
    novel_path.write_text("word " * (120 * 1024 // 5))
    state = create_initial_state("demo", str(novel_path))
    config = Config(quality_preset=preset)

    estimate = estimate_stage_credit_breakdown(config, tmp_path, state, "extract")

    assert estimate["estimate_credits"] in expected_range
