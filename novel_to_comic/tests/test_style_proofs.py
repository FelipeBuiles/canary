"""One Style proof request must price, run and judge freshness identically."""
import asyncio
import hashlib
import json
from unittest.mock import patch

import pytest
from PIL import Image

from novel_to_comic import artifacts
from novel_to_comic.look_assets import LookAssetOutcome
from novel_to_comic.server.routers.styles import (
    generate_style_samples,
    generate_style_validation,
    get_styles,
)
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.stages.s2_style import normalize_suggestion, save_suggestions
from tests.test_style_routes import _project, _request, install_style_ledger


@pytest.fixture
def tmp_path(tmp_path):
    directory = tmp_path / "user" / "demo"
    directory.mkdir(parents=True)
    return directory


@pytest.fixture
def style_ledger(monkeypatch):
    return install_style_ledger(monkeypatch)


def _suggestion_with_reference(project_dir):
    direction_id = "direction_0123456789abcdef"
    image_path = artifacts.style_direction_image_path(project_dir, direction_id, ".png")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), "red").save(image_path)
    artifacts.style_direction_path(project_dir, direction_id).write_text(json.dumps({
        "id": direction_id, "text": "ink",
        "image_path": str(image_path.relative_to(project_dir)),
        "image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
    }))
    suggestion = normalize_suggestion({
        "label": "Ink", "medium": "ink", "template": "Bold ink",
        "direction_id": direction_id,
    })
    save_suggestions(project_dir, [suggestion], "Demo")
    return suggestion, image_path


def _run_proof_job(tmp_path, style_ledger, operation):
    """Admit one proof, execute it, and report what was priced and requested."""
    priced, requested, held = [], [], []
    suggestion, image_path = _suggestion_with_reference(tmp_path)

    def price(config, project_dir, bible, template, candidate_id, **kwargs):
        priced.append((template, candidate_id, kwargs))
        return 0.25

    async def produce(*, request, output_path, **_kwargs):
        requested.append((request, output_path))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "white").save(output_path)
        artifacts.write_asset_meta(output_path, {"provenance": {
            "execution_fingerprint": request.wire.execution_fingerprint,
        }})
        return LookAssetOutcome("reused")

    async def scenario():
        request, project = _request(tmp_path), _project(tmp_path)
        original = style_ledger.holds
        with patch("novel_to_comic.stages.s2_style.style_proof_image_cost_usd", side_effect=price), \
             patch("novel_to_comic.stages.s2_style.produce_look_asset", side_effect=produce):
            if operation == "validation":
                response = await generate_style_validation(
                    request, "demo", {"id": suggestion["id"]}, project=project, user_id="user",
                )
            else:
                response = await generate_style_samples(
                    request, "demo", {"indices": [1]}, project=project, user_id="user",
                )
            held.append(response)
            await request.app.state.generation_queue.get_nowait().runner()
        assert original == style_ledger.holds
        return get_styles("demo", project=project)

    styles = asyncio.run(scenario())
    return suggestion, image_path, priced, requested, styles


@pytest.mark.parametrize("operation", ["samples", "validation"])
def test_quote_execution_and_freshness_share_one_proof_request(tmp_path, style_ledger, operation):
    suggestion, image_path, priced, requested, styles = _run_proof_job(tmp_path, style_ledger, operation)
    candidate_id = suggestion["id"] + (":validation" if operation == "validation" else "")

    (template, priced_id, kwargs), = priced
    (request, output_path), = requested
    assert (template, priced_id) == (style_template_for_suggestion(suggestion), candidate_id)
    assert kwargs["style_reference"] == image_path.resolve()
    assert kwargs["style_reference_mode"] == suggestion["style_reference_mode"]
    assert request.input.asset_identity == f"style_sample:{candidate_id}"
    assert request.reference_plan.ref_count == 1

    proof = styles["suggestions"][0]
    assert proof["has_style_reference"] is True
    if operation == "validation":
        assert output_path == artifacts.style_validation_path(tmp_path, suggestion["id"])
        assert kwargs["subject_action"] and kwargs["composition"]
        assert proof["has_validation"] is True
    else:
        assert output_path == artifacts.style_sample_path(tmp_path, 1)
        assert "subject_action" not in kwargs or kwargs["subject_action"] is None


@pytest.mark.parametrize("operation", ["samples", "validation"])
def test_active_proof_is_not_requeued(tmp_path, style_ledger, operation):
    suggestion, _image = _suggestion_with_reference(tmp_path)

    async def scenario():
        request, project = _request(tmp_path), _project(tmp_path)
        call = (
            (lambda: generate_style_validation(
                request, "demo", {"id": suggestion["id"]}, project=project, user_id="user"))
            if operation == "validation" else
            (lambda: generate_style_samples(
                request, "demo", {"indices": [1]}, project=project, user_id="user"))
        )
        first, second = await call(), await call()
        jobs = first["jobs"] if operation == "samples" else [first["job"]]
        again = second["jobs"] if operation == "samples" else [second["job"]]
        assert [job["id"] for job in jobs] == [job["id"] for job in again]
        assert len(request.app.state.generation_jobs) == 1

    asyncio.run(scenario())


def test_proof_quotes_hold_the_priced_credits(tmp_path, style_ledger):
    suggestion, _image = _suggestion_with_reference(tmp_path)

    async def scenario():
        request, project = _request(tmp_path), _project(tmp_path)
        with patch("novel_to_comic.stages.s2_style.style_proof_image_cost_usd", return_value=0.5), \
             patch("novel_to_comic.stages.s2_style.style_proof_text_cost_usd", return_value=0.25):
            await generate_style_samples(
                request, "demo", {"indices": [1]}, project=project, user_id="user")
            await generate_style_validation(
                request, "demo", {"id": suggestion["id"]}, project=project, user_id="user")
        held = []

        def reserve(_db, _user, _project, _stage, required, **_kwargs):
            held.append(required)
            return "hold", "ledger"

        kinds = [job.kind for job in request.app.state.generation_queue._queue]
        with patch("novel_to_comic.server.credits.reserve_credits", side_effect=reserve):
            for _ in kinds:
                try:
                    await request.app.state.generation_queue.get_nowait().runner()
                except Exception:
                    pass
        return kinds, held

    kinds, held = asyncio.run(scenario())
    assert kinds == ["style_sample", "style_validation"]
    assert len(held) == 2 and held[0] == held[1] > 0
