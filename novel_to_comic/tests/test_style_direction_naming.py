"""Custom direction proofs get distinct names without changing style identity."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from PIL import Image

from novel_to_comic.config import Config
from novel_to_comic.server.routers.styles import (
    _direction_credit_estimates,
    _direction_operations,
    create_style_direction,
    update_style_presentation,
)
from novel_to_comic.stages.s2_style import (
    CUSTOM_DIRECTION_PLACEHOLDERS,
    load_suggestions,
    normalize_suggestion,
    save_suggestions,
)
from novel_to_comic.style_contract import style_template_for_suggestion
from tests.test_style_routes import _project, _request, install_style_ledger, tmp_path as tmp_path


@pytest.fixture
def style_ledger(monkeypatch):
    return install_style_ledger(monkeypatch)


DESCRIPTION = {
    "label": "Claymation snowfall",
    "palette": "Chalky whites with brick-red accents",
    "line_rendering": "No outlines; sculpted clay edges",
    "lighting_value": "Soft overcast key with deep contact shadows",
    "sequential_art_strengths": "Chunky silhouettes read instantly at thumbnail size.",
    "story_fit": "The handmade texture suits a quiet winter fable.",
}


async def _write_proof(_config, _bible, sample_path, **_kwargs):
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (40, 50), "white").save(sample_path)


def _run_direction(tmp_path, *, label=None, naming=None):
    naming = naming or AsyncMock(return_value=SimpleNamespace(value=DESCRIPTION, usage=None))

    async def scenario():
        request = _request(tmp_path)
        with (
            patch("novel_to_comic.stages.s2_style.ensure_style_sample_brief", new=AsyncMock()),
            patch("novel_to_comic.stages.s2_style.generate_sample_image", side_effect=_write_proof),
            patch("novel_to_comic.stages.s2_style.text_client.generate_json", naming),
        ):
            response = await create_style_direction(
                request, "demo", direction_text="claymation, falling snow", label=label,
                with_neighbors=False, image=None, project=_project(tmp_path), user_id="user",
            )
            await request.app.state.generation_queue.get_nowait().runner()
        return response

    response = asyncio.run(scenario())
    return response, naming


def test_finished_direction_proof_is_named_from_the_image_and_author_words(tmp_path, style_ledger):
    response, naming = _run_direction(tmp_path)

    [stored] = load_suggestions(tmp_path)
    assert stored["id"] == response["suggestion"]["id"]
    assert stored["label"] == "Your direction"
    assert stored["display_label"] == "Claymation snowfall"
    assert stored["template"] == "claymation, falling snow"
    assert stored["origin"] == "user_text"
    for field in CUSTOM_DIRECTION_PLACEHOLDERS:
        assert stored[field] == DESCRIPTION[field]
    kwargs = naming.await_args.kwargs
    assert kwargs["model"] == Config().effective_visual_review_model()
    assert len(kwargs["image_attachments"]) == 1
    assert "claymation, falling snow" in kwargs["user_content"]
    assert not style_ledger.holds


def test_author_supplied_label_is_kept(tmp_path, style_ledger):
    _run_direction(tmp_path, label="Snow globe")

    [stored] = load_suggestions(tmp_path)
    assert stored["label"] == "Snow globe"
    assert "display_label" not in stored
    assert stored["palette"] == DESCRIPTION["palette"]


def test_naming_failure_keeps_the_proof_and_placeholder_text(tmp_path, style_ledger):
    _run_direction(tmp_path, naming=AsyncMock(side_effect=RuntimeError("provider down")))

    [stored] = load_suggestions(tmp_path)
    assert "display_label" not in stored
    assert stored["palette"] == CUSTOM_DIRECTION_PLACEHOLDERS["palette"]
    assert (tmp_path / "samples").exists()
    assert not style_ledger.holds


def test_direction_admission_prices_and_routes_the_naming_call(tmp_path):
    project_dir, config, _state = _project(tmp_path)
    assert _direction_operations(config)[-1] == ("text", config.effective_visual_review_model())
    assert _direction_operations(config, with_neighbors=True)[-1] == (
        "text", config.effective_visual_review_model(),
    )
    with patch(
        "novel_to_comic.server.routers.styles.estimate_custom_direction_naming_cost_usd",
        return_value=0.0,
    ):
        without = _direction_credit_estimates(config, project_dir)["faithful"]["estimate_credits"]
    with patch(
        "novel_to_comic.server.routers.styles.estimate_custom_direction_naming_cost_usd",
        return_value=1.0,
    ):
        priced = _direction_credit_estimates(config, project_dir)["faithful"]["estimate_credits"]
    assert priced > without


def _stored_pair(tmp_path):
    suggestions = [
        normalize_suggestion({"label": "Ink", "medium": "ink", "template": "Bold ink"}),
        normalize_suggestion({"label": "Paint", "medium": "paint", "template": "Wet paint"}),
    ]
    save_suggestions(tmp_path, suggestions, "Demo")
    return suggestions


def test_rename_and_hide_change_presentation_but_never_identity(tmp_path):
    project = _project(tmp_path)
    ink, paint = _stored_pair(tmp_path)

    renamed = update_style_presentation(ink["id"], {"display_label": "  Midnight ink  "}, project=project)
    assert renamed["suggestion"]["display_label"] == "Midnight ink"
    update_style_presentation(paint["id"], {"hidden": True}, project=project)

    stored = load_suggestions(tmp_path)
    assert [s["id"] for s in stored] == [ink["id"], paint["id"]]
    assert stored[0]["display_label"] == "Midnight ink"
    assert stored[1]["hidden"] is True

    update_style_presentation(ink["id"], {"display_label": ""}, project=project)
    update_style_presentation(paint["id"], {"hidden": False}, project=project)
    stored = load_suggestions(tmp_path)
    assert "display_label" not in stored[0]
    assert "hidden" not in stored[1]


@pytest.mark.parametrize("body", [{}, {"label": "x"}, {"hidden": "yes"}, {"display_label": 3}, {"display_label": "x" * 61}])
def test_presentation_update_rejects_invalid_bodies(tmp_path, body):
    ink, _paint = _stored_pair(tmp_path)
    with pytest.raises(HTTPException) as error:
        update_style_presentation(ink["id"], body, project=_project(tmp_path))
    assert error.value.status_code == 400


def test_selected_style_cannot_be_hidden(tmp_path):
    ink, _paint = _stored_pair(tmp_path)
    project_dir, _config, state = _project(tmp_path)
    selected = Config(image_model="image-gemini-pro", style_template=style_template_for_suggestion(ink))
    with pytest.raises(HTTPException) as error:
        update_style_presentation(ink["id"], {"hidden": True}, project=(project_dir, selected, state))
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        update_style_presentation("style_missing", {"hidden": True}, project=(project_dir, selected, state))
    assert missing.value.status_code == 404


def test_durable_direction_job_names_the_proof(tmp_path, monkeypatch):
    import json

    from novel_to_comic import artifacts
    from novel_to_comic.server import style_jobs
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.server.job_commands import command
    from novel_to_comic.stages.s2_style import custom_direction_candidate
    from tests.test_durable_queue import make_app
    from tests.test_style_stage import _bible

    direction = {"version": 1, "id": "direction_" + "a" * 16, "label": "Your direction",
                 "text": "claymation, falling snow", "origin": "user_text", "image_path": None}
    path = artifacts.style_direction_path(tmp_path, direction["id"])
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(direction))
    candidate = custom_direction_candidate(direction)
    save_suggestions(tmp_path, [candidate], "Demo")
    monkeypatch.setattr(style_jobs.style, "ensure_style_sample_brief", AsyncMock(return_value=None))
    monkeypatch.setattr(style_jobs.style, "generate_sample_image", _write_proof)
    monkeypatch.setattr(style_jobs.style.text_client, "generate_json",
                        AsyncMock(return_value=SimpleNamespace(value=DESCRIPTION, usage=None)))
    job = GenerationJob(
        id="direction", project_name="account:book", kind="style_sample", label="Direction",
        payload={}, sequence=1, runner=None,
        command=command("style_direction", tmp_path, Config(), bible=_bible().model_dump(mode="json"),
                        candidate=candidate, index=1, direction=direction, with_neighbors=False),
    )
    app = make_app(tmp_path)
    app.state.generation_jobs[job.id] = job

    asyncio.run(style_jobs.execute_style(app, job, tmp_path, Config()))

    [stored] = load_suggestions(tmp_path)
    assert stored["id"] == candidate["id"]
    assert stored["display_label"] == "Claymation snowfall"
    assert stored["story_fit"] == DESCRIPTION["story_fit"]


def test_back_to_back_directions_queue_as_independent_durable_jobs(tmp_path, style_ledger, monkeypatch):
    from novel_to_comic.server import credited_job
    from novel_to_comic.server.admission import mutation_conflicts
    from novel_to_comic.server.routers.styles import get_styles

    monkeypatch.setattr(credited_job, "assert_sufficient_credits", lambda *_args, **_kwargs: None)
    published = []
    request = _request(tmp_path)
    request.app.state.durable_queue_required = True
    request.app.state.durable_queue = SimpleNamespace(publish=published.append, healthy=True)
    project = _project(tmp_path)

    async def scenario():
        responses = []
        for text in ("claymation, falling snow", "woodcut with red ink", "soft pastel moths"):
            assert not mutation_conflicts(request.app, "user:demo", "/styles/direction")
            responses.append(await create_style_direction(
                request, "demo", direction_text=text, label=None,
                with_neighbors=False, image=None, project=project, user_id="user",
            ))
        return responses

    responses = asyncio.run(scenario())

    assert [r["suggestion"]["index"] for r in responses] == [1, 2, 3]
    assert len(published) == 3
    assert [job.command.arguments["index"] for job in published] == [1, 2, 3]
    assert not any(j.status == "running" for j in request.app.state.generation_jobs.values())
    stored = load_suggestions(tmp_path)
    assert [s["template"] for s in stored] == [
        "claymation, falling snow", "woodcut with red ink", "soft pastel moths",
    ]
    styles = get_styles("demo", project, request, "user")
    assert styles["is_generating"] is True
    assert styles["is_suggesting"] is False
    assert [s["generation_status"] for s in styles["suggestions"]] == ["queued", "queued", "queued"]
    # A presentation edit never waits for artwork; a portfolio batch still owns the list.
    assert not mutation_conflicts(request.app, "user:demo", f"/styles/{stored[0]['id']}")
    published[0].kind = "style_suggest"
    assert mutation_conflicts(request.app, "user:demo", "/styles/direction")
    assert mutation_conflicts(request.app, "user:demo", "/config")
