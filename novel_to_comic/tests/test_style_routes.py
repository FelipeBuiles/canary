import asyncio
import io
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers
from starlette.requests import Request

from novel_to_comic import artifacts
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config
from novel_to_comic.server.routers.styles import (
    _assert_no_style_task,
    _direction_credit_estimates,
    _prepare_style_direction,
    _suggest_batch_credit_estimate,
    create_style_direction,
    generate_style_validation,
    get_styles,
    style_direction_estimate,
    suggest_styles,
)
from novel_to_comic.stages.s2_style import normalize_suggestion, save_suggestions
from novel_to_comic.stages.s2_style import estimate_style_batch_cost_usd, load_suggestions
from novel_to_comic.state import StageStatus, create_initial_state
from tests.test_style_stage import _bible


def _request(headers: list[tuple[bytes, bytes]] | None = None) -> Request:
    app = FastAPI()
    app.state.running_tasks = {}
    app.state.style_tasks = {}
    app.state.generation_jobs = {}
    app.state.event_queues = {}
    return Request({"type": "http", "app": app, "headers": headers or []})


def _png_upload() -> UploadFile:
    raw = io.BytesIO()
    Image.new("RGB", (8, 8), "red").save(raw, format="PNG")
    raw.seek(0)
    return UploadFile(
        file=raw, filename="reference.png",
        headers=Headers({"content-type": "image/png"}),
    )


def _project(tmp_path, status: StageStatus = StageStatus.PENDING):
    artifacts.story_bible_path(tmp_path).write_text(_bible().model_dump_json())
    state = create_initial_state("demo", "novel.txt")
    state.stages["style"].status = status
    return tmp_path, Config(image_model="image-balanced"), state


def test_credit_failure_leaves_no_direction_artifacts(tmp_path):
    request = _request()
    with patch(
        "novel_to_comic.server.routers.styles.assert_sufficient_credits",
        side_effect=HTTPException(402, "insufficient"),
    ), patch("novel_to_comic.server.routers.styles.get_db", return_value=object()):
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(create_style_direction(
                request, "demo", direction_text="bright ink", image=None,
                label=None, with_neighbors=False, project=_project(tmp_path), user_id="user",
            ))
    assert exc_info.value.status_code == 402
    assert not (tmp_path / "samples").exists()


def test_unsupported_image_only_rejects_before_write(tmp_path):
    request = _request()
    project_dir, _config, state = _project(tmp_path)
    with patch(
        "novel_to_comic.server.routers.styles.assert_sufficient_credits"
    ) as credit_check:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(create_style_direction(
                request, "demo", direction_text=None, image=_png_upload(),
                label=None, with_neighbors=False,
                project=(project_dir, Config(image_model="gpt-image-2"), state),
                user_id="user",
            ))
    assert exc_info.value.status_code == 400
    credit_check.assert_not_called()
    assert not (tmp_path / "samples").exists()


@pytest.mark.parametrize("initial", [StageStatus.PENDING, StageStatus.FAILED])
def test_custom_direction_repairs_canonical_style_lifecycle(tmp_path, initial):
    async def scenario():
        request = _request()
        project = _project(tmp_path, initial)
        captured = {}

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        with (
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("reservation", "job")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock(return_value=None)),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()),
        ):
            await create_style_direction(
                request, "demo", direction_text="bold ink", image=None,
                label=None, with_neighbors=False, project=project, user_id="user",
            )
            assert project[2].stages["style"].status == StageStatus.RUNNING
            assert "user:demo" in request.app.state.style_tasks
            await captured["runner"]()
        assert project[2].stages["style"].status == StageStatus.AWAITING_REVIEW
        assert "user:demo" not in request.app.state.style_tasks

    asyncio.run(scenario())


def test_style_task_guard_blocks_overlap():
    async def scenario():
        request = _request()
        request.app.state.style_tasks["user:demo"] = asyncio.get_running_loop().create_future()
        with pytest.raises(HTTPException) as exc_info:
            _assert_no_style_task(request, "user:demo")
        assert exc_info.value.status_code == 409

    asyncio.run(scenario())


def test_concurrent_direction_upload_is_owner_guarded(tmp_path):
    class BlockingUpload:
        content_type = "image/png"
        filename = "blocked.png"

        def __init__(self):
            self.started = asyncio.Event()
            self.release = asyncio.Event()

        async def read(self, _size):
            self.started.set()
            await self.release.wait()
            return _png_upload().file.read()

    async def scenario():
        request = _request()
        project = _project(tmp_path)
        upload = BlockingUpload()
        with (
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job") as enqueue,
        ):
            first = asyncio.create_task(create_style_direction(
                request, "demo", direction_text="ink", label=None,
                with_neighbors=False, image=upload, project=project, user_id="user",
            ))
            await upload.started.wait()
            with pytest.raises(HTTPException) as exc_info:
                await create_style_direction(
                    request, "demo", direction_text="ink", label=None,
                    with_neighbors=False, image=None, project=project, user_id="user",
                )
            assert exc_info.value.status_code == 409
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first
            assert enqueue.call_count == 0
            assert release.call_count == 0
            assert not (tmp_path / "samples").exists()

    asyncio.run(scenario())


def test_validation_reuses_identical_active_job_before_credit_check(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        suggestion = normalize_suggestion({
            "label": "Ink", "medium": "ink", "template": "Bold ink",
        })
        save_suggestions(tmp_path, [suggestion], "Demo")
        active = SimpleNamespace(id="existing", status="running")
        with (
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.find_active_generation_job", return_value=active),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "existing"}),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits") as credit,
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job") as enqueue,
        ):
            result = await generate_style_validation(
                request, "demo", {"id": suggestion["id"]},
                project=project, user_id="user",
            )
        assert result["job"] == {"id": "existing"}
        credit.assert_not_called()
        enqueue.assert_not_called()

    asyncio.run(scenario())


def test_validation_reservation_is_released_on_terminal_runner(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        suggestion = normalize_suggestion({
            "label": "Ink", "medium": "ink", "template": "Bold ink",
        })
        save_suggestions(tmp_path, [suggestion], "Demo")
        captured = {}

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        with (
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.find_active_generation_job", return_value=None),
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")) as reserve,
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()),
        ):
            await generate_style_validation(
                request, "demo", {"id": suggestion["id"]},
                project=project, user_id="user",
            )
            assert reserve.call_count == 1
            await captured["runner"]()
        assert release.call_count == 1

    asyncio.run(scenario())


def test_validation_estimate_is_reference_aware_before_reservation(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        suggestion = normalize_suggestion({
            "label": "Ink", "medium": "ink", "template": "Bold ink",
            "direction_id": "direction_0123456789abcdef",
        })
        save_suggestions(tmp_path, [suggestion], "Demo")
        captured = {}

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        reference = tmp_path / "reference.png"
        reference.write_bytes(b"reference")
        with (
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.find_active_generation_job", return_value=None),
            patch("novel_to_comic.server.routers.styles.load_style_direction", return_value={"id": suggestion["direction_id"]}),
            patch("novel_to_comic.server.routers.styles.style_direction_image", return_value=reference),
            patch(
                "novel_to_comic.server.routers.styles._style_sample_credit_estimate",
                return_value={"reserved_credits": 9, "estimate_credits": 8},
            ) as estimate,
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits") as credit,
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")) as reserve,
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
        ):
            await generate_style_validation(
                request, "demo", {"id": suggestion["id"]},
                project=project, user_id="user",
            )
        assert estimate.call_args.kwargs["has_style_reference"] is True
        assert estimate.call_args.kwargs["exact_cost_usd"] > 0
        assert credit.call_args.args[2] == 9
        assert reserve.call_args.args[-1] == 9

    asyncio.run(scenario())


def test_direction_estimate_discloses_reference_and_text_variants(tmp_path):
    result = style_direction_estimate(
        "demo", project=_project(tmp_path), user_id="user",
    )
    assert result["estimates"] == result["estimates_without_reference"]
    assert set(result["estimates_with_reference"]) == {
        "faithful", "neighbors", "faithful_with_neighbors",
    }
    assert result["image_reference_supported"] is True


def test_get_styles_discloses_usable_reference_per_suggestion(tmp_path):
    project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
    direction_id = "direction_0123456789abcdef"
    suggestions = [
        normalize_suggestion({
            "label": "Custom", "medium": "ink", "template": "Bold ink",
            "direction_id": direction_id,
        }),
        normalize_suggestion({
            "label": "Generated", "medium": "paint", "template": "Bright paint",
        }),
    ]
    save_suggestions(tmp_path, suggestions, "Demo")
    reference = tmp_path / "reference.png"
    reference.write_bytes(b"reference")
    with (
        patch(
            "novel_to_comic.server.routers.styles.load_style_direction",
            side_effect=lambda _project_dir, value: {"id": value} if value else None,
        ),
        patch(
            "novel_to_comic.server.routers.styles.style_direction_image",
            side_effect=lambda _project_dir, direction: reference if direction else None,
        ),
    ):
        result = get_styles("demo", project=project)
    assert [item["has_style_reference"] for item in result["suggestions"]] == [True, False]


def test_get_styles_keeps_stale_proof_visible_and_marks_it_for_refresh(tmp_path):
    project = _project(tmp_path, StageStatus.FAILED)
    suggestions = [normalize_suggestion({
        "label": "Old proof", "medium": "ink", "template": "Bold ink",
    })]
    save_suggestions(tmp_path, suggestions, "Demo")
    artifacts.style_sample_path(tmp_path, 1).write_bytes(b"existing proof")

    with patch(
        "novel_to_comic.server.routers.styles.missing_sample_indices",
        return_value=[1],
    ):
        result = get_styles("demo", project=project)

    proof = result["suggestions"][0]
    assert proof["has_sample"] is True
    assert proof["sample_stale"] is True


def test_get_styles_does_not_call_missing_proof_stale(tmp_path):
    project = _project(tmp_path, StageStatus.FAILED)
    suggestions = [normalize_suggestion({
        "label": "Missing proof", "medium": "ink", "template": "Bold ink",
    })]
    save_suggestions(tmp_path, suggestions, "Demo")

    with patch(
        "novel_to_comic.server.routers.styles.missing_sample_indices",
        return_value=[1],
    ):
        result = get_styles("demo", project=project)

    proof = result["suggestions"][0]
    assert proof["has_sample"] is False
    assert proof["sample_stale"] is False


@pytest.mark.parametrize("failure_point", ["estimate", "db"])
def test_direction_post_guard_failures_release_owner(tmp_path, failure_point):
    request = _request()
    patches = [
        patch(
            "novel_to_comic.server.routers.styles._direction_credit_estimates",
            side_effect=RuntimeError("estimate failed") if failure_point == "estimate" else None,
        ),
        patch(
            "novel_to_comic.server.routers.styles.get_db",
            side_effect=RuntimeError("db failed") if failure_point == "db" else None,
        ),
    ]
    if failure_point == "db":
        patches[0] = patch(
            "novel_to_comic.server.routers.styles._direction_credit_estimates",
            return_value={"faithful": {"reserved_credits": 2, "estimate_credits": 1}},
        )
    with patches[0], patches[1]:
        with pytest.raises(RuntimeError):
            asyncio.run(create_style_direction(
                request, "demo", direction_text="ink", label=None,
                with_neighbors=False, image=None, project=_project(tmp_path), user_id="user",
            ))
    assert "user:demo" not in request.app.state.style_tasks
    assert not (tmp_path / "samples").exists()


def test_suggest_setup_failure_releases_reservation_and_queue(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch("novel_to_comic.server.routers.styles.save_state", side_effect=RuntimeError("disk")),
        ):
            with pytest.raises(RuntimeError, match="disk"):
                await suggest_styles(
                    request, "demo", project=project, user_id="user",
                )
        assert release.call_count == 1
        assert "user:demo" not in request.app.state.style_tasks
        assert "user:demo" not in request.app.state.event_queues
        assert project[2].stages["style"].status == StageStatus.FAILED

    asyncio.run(scenario())


def test_suggest_worker_cancellation_releases_and_fails_lifecycle(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch(
                "novel_to_comic.server.routers.styles.generate_suggestions",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            await suggest_styles(request, "demo", project=project, user_id="user")
            task = request.app.state.style_tasks["user:demo"]
            with pytest.raises(asyncio.CancelledError):
                await task
        assert release.call_count == 1
        assert "user:demo" not in request.app.state.style_tasks
        assert project[2].stages["style"].status == StageStatus.FAILED

    asyncio.run(scenario())


def test_suggest_worker_reports_failure_without_unobserved_task_exception(
    tmp_path, caplog,
):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        error = AITransportError(
            "AI gateway request failed for style.suggestions "
            "(model=prompt-balanced, endpoint=/v1/chat/completions): "
            "transport ReadError after 4 attempts",
            phase="gateway_request",
        )
        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch(
                "novel_to_comic.server.routers.styles.generate_suggestions",
                new=AsyncMock(side_effect=error),
            ),
        ):
            await suggest_styles(request, "demo", project=project, user_id="user")
            task = request.app.state.style_tasks["user:demo"]
            assert await task is None

        failures = [
            event for event in request.app.state.event_queues["user:demo"]._queue
            if event["type"] == "stage_fail"
        ]
        assert failures == [{
            "type": "stage_fail",
            "stage": "style_suggest",
            "message": str(error),
        }]
        assert release.call_count == 1
        assert project[2].stages["style"].status == StageStatus.FAILED
        assert "project_id=demo" in caplog.text
        assert "feature=style.suggestions" in caplog.text
        assert "model=prompt-balanced" in caplog.text
        assert "transport ReadError after 4 attempts" in caplog.text
        assert "Traceback" not in caplog.text

    with caplog.at_level(logging.WARNING, logger="canary.styles"):
        asyncio.run(scenario())


def test_suggest_worker_labels_sample_image_failure_with_image_model(tmp_path, caplog):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        suggestion = normalize_suggestion({
            "label": "Ink", "medium": "ink", "template": "Bold ink",
        })
        error = AITransportError(
            "wire image transport failed (status_code=500)",
            phase="gateway_request",
        )
        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch(
                "novel_to_comic.server.routers.styles.generate_suggestions",
                new=AsyncMock(return_value=([suggestion], None)),
            ),
            patch(
                "novel_to_comic.server.routers.styles.generate_samples_for_indices",
                new=AsyncMock(side_effect=error),
            ),
        ):
            await suggest_styles(request, "demo", project=project, user_id="user")
            task = request.app.state.style_tasks["user:demo"]
            assert await task is None

        assert "feature=style.sample" in caplog.text
        assert "model=image-balanced" in caplog.text
        assert "feature=style.suggestions" not in caplog.text

    with caplog.at_level(logging.WARNING, logger="canary.styles"):
        asyncio.run(scenario())


def test_validation_runner_groups_usage_with_reservation_job_id(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        suggestion = normalize_suggestion({
            "label": "Ink", "medium": "ink", "template": "Bold ink",
        })
        save_suggestions(tmp_path, [suggestion], "Demo")
        captured = {}

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        class Context:
            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return False

        with (
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.find_active_generation_job", return_value=None),
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "ledger-job")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()),
            patch(
                "novel_to_comic.server.routers.styles.ai_request_context",
                side_effect=lambda **kwargs: captured.update(context=kwargs) or Context(),
            ),
        ):
            await generate_style_validation(
                request, "demo", {"id": suggestion["id"]},
                project=project, user_id="user",
            )
            await captured["runner"]()
        assert captured["context"]["job_id"] == "ledger-job"

    asyncio.run(scenario())


def test_decoded_image_dimensions_are_bounded(tmp_path):
    raw = io.BytesIO()
    Image.new("RGB", (10_001, 1), "red").save(raw, format="PNG")
    raw.seek(0)
    upload = UploadFile(
        file=raw, filename="wide.png", headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_prepare_style_direction(
            project_dir=tmp_path, config=Config(image_model="image-balanced"),
            bible=_bible(), text="ink", label=None, image=upload,
        ))
    assert exc_info.value.status_code == 400
    assert not (tmp_path / "samples").exists()


def test_direction_rejects_oversized_content_length_before_queue(tmp_path):
    request = _request([(b"content-length", str(12 * 1024 * 1024).encode())])
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_style_direction(
            request, "demo", direction_text="ink", label=None,
            with_neighbors=False, image=None, project=_project(tmp_path), user_id="user",
        ))
    assert exc_info.value.status_code == 413
    assert not request.app.state.style_tasks


def test_direction_with_neighbors_is_one_reserved_server_operation(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        captured = {}
        neighbors = [normalize_suggestion({
            "label": f"N{i}", "medium": f"medium {i}", "template": f"style {i}",
            "role": role,
        }, origin="generated_neighbor") for i, role in enumerate(
            ("story_fit_primary", "adjacent", "contrast", "wildcard")
        )]

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")) as reserve,
            patch("novel_to_comic.server.routers.styles.release_reservation") as release,
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue) as enqueue,
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock(return_value=None)),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()) as faithful,
            patch("novel_to_comic.server.routers.styles.generate_suggestions", new=AsyncMock(return_value=(neighbors, None))) as suggest,
            patch("novel_to_comic.server.routers.styles.generate_samples_for_indices", new=AsyncMock()) as samples,
        ):
            result = await create_style_direction(
                request, "demo", direction_text="bold ink", label=None,
                with_neighbors=True, image=None, project=project, user_id="user",
            )
            assert result["with_neighbors"] is True
            assert reserve.call_args.args[-1] == result["estimate"]["reserved_credits"]
            assert enqueue.call_count == 1
            await captured["runner"]()
        assert faithful.await_count == 1
        assert suggest.await_count == 1
        assert samples.await_args.args[-1] == [2, 3, 4, 5]
        assert release.call_count == 1
        assert project[2].stages["style"].status == StageStatus.AWAITING_REVIEW

    asyncio.run(scenario())


def test_image_backed_direction_estimate_covers_references_and_retry(tmp_path):
    config = Config(image_model="image-balanced")
    _project(tmp_path)
    without_image = estimate_style_batch_cost_usd(
        config, tmp_path, 4, has_style_reference=False,
    )
    with_image = estimate_style_batch_cost_usd(
        config, tmp_path, 4, has_style_reference=True,
    )
    one_attempt = estimate_style_batch_cost_usd(
        config, tmp_path, 4, suggestion_attempts=1,
    )
    two_attempts = estimate_style_batch_cost_usd(
        config, tmp_path, 4, suggestion_attempts=2,
    )
    assert with_image > without_image
    assert two_attempts > one_attempt


def test_combined_and_seeded_estimates_forward_arbitrary_reference_dimensions(tmp_path):
    config = Config(image_model="image-balanced")
    _project(tmp_path)
    size = (137, 911)
    with (
        patch(
            "novel_to_comic.server.routers.styles.estimate_style_proof_cost_usd",
            return_value=0.02,
        ),
        patch(
            "novel_to_comic.server.routers.styles.estimate_style_batch_cost_usd",
            return_value=0.08,
        ) as batch,
    ):
        _direction_credit_estimates(
            config, tmp_path, has_style_reference=True, reference_size=size,
        )
        assert batch.call_args.kwargs["reference_size"] == size
        _suggest_batch_credit_estimate(
            config, tmp_path, 4, has_style_reference=True, reference_size=size,
        )
        assert batch.call_args.kwargs["reference_size"] == size


def test_batch_estimator_prices_each_neighbor_reference_size(tmp_path):
    config = Config(image_model="image-balanced")
    _project(tmp_path)
    captured = []

    def fake_image_cost(_model, _count, **kwargs):
        captured.append(kwargs)
        return 0.02

    with patch("novel_to_comic.usage.estimate_image_cost", side_effect=fake_image_cost):
        estimate_style_batch_cost_usd(
            config, tmp_path, 4,
            has_style_reference=True, reference_size=(137, 911),
        )
    assert len(captured) == 4
    assert all(call["ref_count"] == 1 for call in captured)
    assert all(call["ref_image_sizes"] == [(137, 911)] for call in captured)


def test_direction_enqueue_failure_marks_owned_lifecycle_failed(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch(
                "novel_to_comic.server.routers.styles.enqueue_generation_job",
                side_effect=RuntimeError("queue unavailable"),
            ),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
        ):
            with pytest.raises(RuntimeError, match="queue unavailable"):
                await create_style_direction(
                    request, "demo", direction_text="bold ink", label=None,
                    with_neighbors=False, image=None, project=project, user_id="user",
                )
        assert project[2].stages["style"].status == StageStatus.FAILED
        assert "user:demo" not in request.app.state.style_tasks

    asyncio.run(scenario())


def test_direction_worker_cancellation_marks_owned_lifecycle_failed(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        captured = {}

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock(return_value=None)),
            patch(
                "novel_to_comic.server.routers.styles.generate_sample_image",
                new=AsyncMock(side_effect=asyncio.CancelledError()),
            ),
        ):
            await create_style_direction(
                request, "demo", direction_text="bold ink", label=None,
                with_neighbors=False, image=None, project=project, user_id="user",
            )
            with pytest.raises(asyncio.CancelledError):
                await captured["runner"]()
        assert project[2].stages["style"].status == StageStatus.FAILED
        assert "user:demo" not in request.app.state.style_tasks

    asyncio.run(scenario())


def test_failed_combined_neighbor_proofs_do_not_persist_duplicates(tmp_path):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        captured = {}
        neighbors = [normalize_suggestion({
            "label": f"N{i}", "medium": f"medium {i}", "template": f"style {i}",
            "role": role,
        }, origin="generated_neighbor") for i, role in enumerate(
            ("story_fit_primary", "adjacent", "contrast", "wildcard")
        )]

        def fake_enqueue(*args, **kwargs):
            captured["runner"] = kwargs["runner"]
            return SimpleNamespace(id="job", status="queued")

        with (
            patch("novel_to_comic.server.routers.styles.get_db", return_value=object()),
            patch("novel_to_comic.server.routers.styles.assert_sufficient_credits"),
            patch("novel_to_comic.server.routers.styles.reserve_credits", return_value=("r", "j")),
            patch("novel_to_comic.server.routers.styles.release_reservation"),
            patch("novel_to_comic.server.routers.styles.prune_finished_generation_jobs"),
            patch("novel_to_comic.server.routers.styles.enqueue_generation_job", side_effect=fake_enqueue),
            patch("novel_to_comic.server.routers.styles.generation_semaphore_for_config", return_value=None),
            patch("novel_to_comic.server.routers.styles.generation_job_payload", return_value={"id": "job"}),
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock(return_value=None)),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()),
            patch("novel_to_comic.server.routers.styles.generate_suggestions", new=AsyncMock(return_value=(neighbors, None))),
            patch(
                "novel_to_comic.server.routers.styles.generate_samples_for_indices",
                new=AsyncMock(side_effect=RuntimeError("proof failed")),
            ),
        ):
            await create_style_direction(
                request, "demo", direction_text="bold ink", label=None,
                with_neighbors=True, image=None, project=project, user_id="user",
            )
            with pytest.raises(RuntimeError, match="proof failed"):
                await captured["runner"]()
        persisted = load_suggestions(tmp_path)
        assert len(persisted) == 1
        assert persisted[0]["origin"] == "user_text"

    asyncio.run(scenario())
