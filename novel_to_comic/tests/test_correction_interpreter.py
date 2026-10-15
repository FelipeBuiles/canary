"""Change requests are read against the page before an image edit is drawn."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from novel_to_comic.config import Config
from novel_to_comic.correction_interpreter import (
    ChangeReading,
    CorrectionReadings,
    interpret_changes,
    interpretation_prompt,
)
from novel_to_comic.models.draw import CorrectionAnnotation, CorrectionChange
from novel_to_comic.models.page import ApprovedVisualReferenceInventory
from novel_to_comic.page_review import lettering_correction_instruction
from novel_to_comic.usage import ApiResult

from .test_page_corrections import _api_client, _setup, _write_empty_story_bible

PAGES = "/api/projects/test_project/parts/part_0001/pages/1"


def _changes() -> tuple[CorrectionChange, ...]:
    return (
        CorrectionChange(id="tail", instruction="the tail should point to the lady",
                         annotations=(CorrectionAnnotation(kind="pin", points=({"x": 0.36, "y": 0.1},)),)),
        CorrectionChange(id="move", instruction="this line should be in the first panel"),
    )


def test_prompt_carries_the_canonical_page_marks_and_lettering_mode(tmp_path: Path) -> None:
    _artifacts, page, _render = _setup(tmp_path)
    prompt = interpretation_prompt(page=page, inventory=ApprovedVisualReferenceInventory(),
                                   changes=_changes(), lettering_in_art=True)
    facts = json.loads(prompt[prompt.index("{"):])
    assert [panel["panel"] for panel in facts["panels"]] == sorted(c.order for c in page.content)
    assert facts["requests"][0] == {"change_id": "tail", "request": "the tail should point to the lady",
                                    "marked_locations": ["pin at 36-36% across, 10-10% down"]}
    assert "tail pointing at the wrong character" in prompt
    hybrid = interpretation_prompt(page=page, inventory=ApprovedVisualReferenceInventory(),
                                   changes=_changes(), lettering_in_art=False)
    assert "carries no comic lettering" in hybrid


def test_readings_come_back_in_draft_order_with_one_per_request(tmp_path: Path) -> None:
    _artifacts, page, _render = _setup(tmp_path)
    calls = []

    async def generate(**call):
        calls.append(call)
        return ApiResult(value={"changes": [
            {"change_id": "move", "route": "plan", "instruction": "Put the line in panel 1.", "reason": "Layout."},
            {"change_id": "tail", "route": "draw", "instruction": "Point the tail at Mrs. White.", "reason": "Art."},
        ]})

    result = asyncio.run(interpret_changes(config=Config(correction_model="gemini-4-argon"), page=page,
                                           inventory=ApprovedVisualReferenceInventory(), image=b"png",
                                           changes=_changes(), lettering_in_art=True, generate=generate))
    assert [reading.change_id for reading in result.value.changes] == ["tail", "move"]
    assert calls[0]["model"] == "gemini-4-argon"
    assert calls[0]["feature"] == "draw.correction_interpret"
    assert calls[0]["image_attachments"] == ((b"png", "image/png"),)

    async def incomplete(**_call):
        return ApiResult(value={"changes": [
            {"change_id": "tail", "route": "draw", "instruction": "Point the tail.", "reason": "Art."},
        ]})

    with pytest.raises(ValueError, match="one reading per request"):
        asyncio.run(interpret_changes(config=Config(), page=page, inventory=ApprovedVisualReferenceInventory(),
                                      image=b"png", changes=_changes(), lettering_in_art=True, generate=incomplete))


def test_check_route_prices_then_reads_without_touching_the_draft(tmp_path: Path, monkeypatch) -> None:
    from novel_to_comic import correction_interpreter
    from novel_to_comic.server import credited_job

    artifacts, page, render = _setup(tmp_path)
    project_dir = tmp_path / "project"
    _write_empty_story_bible(project_dir)
    client = _api_client(tmp_path, project_dir)
    issues_before = artifacts.read_issues(1) if artifacts.issues_path(1).exists() else ()
    body = {"comic_page_revision": page.revision, "parent_render_revision": render.revision,
            "changes": [{"id": "move", "instruction": "this line should be in the first panel"}]}

    estimate = client.post(f"{PAGES}/corrections/interpret/estimate", json=body)
    assert estimate.status_code == 200, estimate.text
    assert estimate.json()["estimate_credits"] >= 0

    async def fake_interpret(**kwargs):
        assert kwargs["image"] == artifacts.read_render(1, render.revision)
        return ApiResult(value=CorrectionReadings(changes=(ChangeReading(
            change_id="move", route="plan", instruction="Move the line to panel 1.", reason="Panel layout."),)))

    async def run_now(*, work, **_kwargs):
        return await work()

    monkeypatch.setattr(correction_interpreter, "interpret_changes", fake_interpret)
    monkeypatch.setattr(credited_job, "run_credited_page_check", run_now)
    response = client.post(f"{PAGES}/corrections/interpret", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["changes"] == [{"change_id": "move", "route": "plan",
                                           "instruction": "Move the line to panel 1.", "reason": "Panel layout."}]
    after = artifacts.read_issues(1) if artifacts.issues_path(1).exists() else ()
    assert after == issues_before

    stale = {**body, "parent_render_revision": render.revision + 1}
    assert client.post(f"{PAGES}/corrections/interpret/estimate", json=stale).status_code == 409
    assert client.post(f"{PAGES}/corrections/interpret/estimate", json={**body, "changes": []}).status_code == 422


@pytest.mark.parametrize("code, expected, observed, wanted", [
    ("misspelled_lettering", ["Might drop on his head."], ["Might drop on his heed."],
     'reads exactly: "Might drop on his head.". The page currently shows "Might drop on his heed." instead.'),
    ("missing_lettering", ["A", "Run!"], ["A"], 'worded exactly: "Run!"'),
    ("duplicated_lettering", ["Run!"], ["Run!", "Run!"], 'only once, in its assigned panel: "Run!"'),
    ("invented_lettering", ["Run!"], ["Run!", "Hey"], 'not in the script: "Hey"'),
])
def test_lettering_issues_ask_the_artwork_for_the_exact_fix(code, expected, observed, wanted) -> None:
    evidence = (f"expected_text={json.dumps(expected)}", f"recognized_text={json.dumps(observed)}")
    instruction = lettering_correction_instruction(code, evidence)
    assert wanted in instruction
    # Author guidance (the checker may have misread) never reaches the image model.
    assert "misread" not in instruction and "Compare the saved artwork" not in instruction


def test_generated_lettering_removal_names_what_was_seen() -> None:
    instruction = lettering_correction_instruction(
        "unexpected_generated_lettering", ("Blind base-art observation: HELP",))
    assert instruction.startswith('Remove the comic lettering drawn in the marked region ("HELP")')
    assert "dismiss" not in instruction
