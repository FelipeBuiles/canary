import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI, HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers
from starlette.requests import Request

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.server.routers.styles import (
    _assert_no_style_task,
    _prepare_style_direction,
    create_style_direction,
    generate_style_samples,
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
    app.state.generation_queue = asyncio.Queue()
    app.state.generation_semaphore = asyncio.Semaphore(1)
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
    return tmp_path, Config(image_model="image-gemini-pro"), state


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
            patch("novel_to_comic.server.routers.styles.enqueue_reserved_generation_job") as enqueue,
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




def test_decoded_image_dimensions_are_bounded(tmp_path):
    raw = io.BytesIO()
    Image.new("RGB", (10_001, 1), "red").save(raw, format="PNG")
    raw.seek(0)
    upload = UploadFile(
        file=raw, filename="wide.png", headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_prepare_style_direction(
            project_dir=tmp_path, config=Config(image_model="image-gemini-pro"),
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



def test_image_backed_direction_estimate_covers_references_and_retry(tmp_path):
    config = Config(image_model="image-gemini-pro")
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




def test_batch_estimator_prices_each_neighbor_reference_size(tmp_path):
    config = Config(image_model="image-gemini-pro")
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



@pytest.fixture
def style_ledger(monkeypatch):
    from novel_to_comic.server import credited_job
    from novel_to_comic.server.routers import styles

    ledger = SimpleNamespace(balance=10000, holds={}, released=[], expired=set())

    def reserve(_db, _user, _project, _stage, required):
        if required > ledger.balance - sum(ledger.holds.values()):
            raise HTTPException(402, "insufficient")
        key = f"hold-{len(ledger.holds) + len(ledger.released)}"
        ledger.holds[key] = required
        return key, f"ledger-{key}"

    def release(_db, key):
        if key in ledger.holds:
            ledger.holds.pop(key)
            ledger.released.append(key)

    def active(_db, key):
        if key not in ledger.holds or key in ledger.expired:
            raise RuntimeError("Credit reservation expired or ownership was lost")

    for module in (styles, credited_job):
        monkeypatch.setattr(module, "get_db", lambda: ledger)
        monkeypatch.setattr(module, "reserve_credits", reserve)
        monkeypatch.setattr(module, "release_reservation", release)
    monkeypatch.setattr(styles, "assert_sufficient_credits", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(credited_job, "assert_reservation_active", active)
    return ledger


async def _queue_style_operation(request, project, operation):
    suggestion = normalize_suggestion({
        "label": "Ink", "medium": "ink", "template": "Bold ink",
    })
    save_suggestions(project[0], [suggestion], "Demo")
    if operation == "direction":
        return await create_style_direction(
            request, "demo", direction_text="bold ink", image=None,
            label=None, with_neighbors=False, project=project, user_id="user",
        )
    if operation == "suggest":
        return await suggest_styles(request, "demo", project=project, user_id="user")
    if operation == "validation":
        return await generate_style_validation(
            request, "demo", {"id": suggestion["id"]}, project=project, user_id="user",
        )
    return await generate_style_samples(
        request, "demo", {"indices": [1]}, project=project, user_id="user",
    )


@pytest.mark.parametrize("operation", ["direction", "suggest", "samples", "validation"])
@pytest.mark.parametrize("terminal", ["cancel", "expired"])
def test_style_queue_releases_unstarted_hold_without_paid_work(
    tmp_path, style_ledger, operation, terminal,
):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with (
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock()) as brief,
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()) as image,
            patch("novel_to_comic.server.routers.styles.generate_suggestions", new=AsyncMock()) as suggestions,
        ):
            await _queue_style_operation(request, project, operation)
            job = request.app.state.generation_queue.get_nowait()
            assert len(style_ledger.holds) == 1
            if terminal == "expired":
                style_ledger.expired.update(style_ledger.holds)
                with pytest.raises(RuntimeError, match="expired"):
                    await job.runner()
            else:
                job.on_cancel()
            job.on_cancel()
            brief.assert_not_awaited()
            image.assert_not_awaited()
            suggestions.assert_not_awaited()
        assert not style_ledger.holds
        assert len(style_ledger.released) == 1
        assert not request.app.state.style_tasks
        if operation in ("direction", "suggest"):
            assert project[2].stages["style"].status == StageStatus.FAILED

    asyncio.run(scenario())


def test_competing_style_jobs_cannot_spend_another_queued_hold(tmp_path, style_ledger):
    async def scenario():
        first = _request()
        second = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        with patch(
            "novel_to_comic.server.routers.styles._style_sample_credit_estimate",
            return_value={"reserved_credits": 10, "estimate_credits": 8},
        ):
            style_ledger.balance = 10
            await _queue_style_operation(first, project, "samples")
            with pytest.raises(HTTPException) as error:
                await _queue_style_operation(second, project, "validation")
            assert error.value.status_code == 402
            assert second.app.state.generation_queue.empty()
            first.app.state.generation_queue.get_nowait().on_cancel()
            await _queue_style_operation(second, project, "validation")
            assert len(style_ledger.holds) == 1
            second.app.state.generation_queue.get_nowait().on_cancel()
        assert not style_ledger.holds

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["direction", "suggest", "samples", "validation"])
def test_style_provider_work_runs_under_hold_and_releases_on_success(
    tmp_path, style_ledger, operation,
):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        calls = []

        async def paid(*_args, **_kwargs):
            assert len(style_ledger.holds) == 1
            from novel_to_comic.ai.context import current_ai_request_context

            context = current_ai_request_context()
            assert context.job_id == f"ledger-{next(iter(style_ledger.holds))}"
            assert context.user_id == "user"
            calls.append(operation)

        async def suggestions(*args, **kwargs):
            await paid()
            return [normalize_suggestion({
                "label": "Paint", "medium": "paint", "template": "Paint",
            })], None

        with (
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", side_effect=paid),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", side_effect=paid),
            patch("novel_to_comic.server.routers.styles.generate_samples_for_indices", side_effect=paid),
            patch("novel_to_comic.server.routers.styles.generate_suggestions", side_effect=suggestions),
        ):
            await _queue_style_operation(request, project, operation)
            await request.app.state.generation_queue.get_nowait().runner()
        assert calls == [operation] * (1 if operation == "validation" else 2)
        assert not style_ledger.holds
        assert not request.app.state.style_tasks
        if operation in ("direction", "suggest"):
            assert project[2].stages["style"].status == StageStatus.AWAITING_REVIEW

    asyncio.run(scenario())


def test_suggest_broadcasts_terminal_failure_to_each_subscriber(tmp_path, style_ledger):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with patch(
            "novel_to_comic.server.routers.styles.generate_suggestions",
            new=AsyncMock(side_effect=RuntimeError("provider failed")),
        ):
            await _queue_style_operation(request, project, "suggest")
            channel = request.app.state.event_queues["user:demo"]
            subscribers = [channel.subscribe(), channel.subscribe()]
            with pytest.raises(RuntimeError, match="provider failed"):
                await request.app.state.generation_queue.get_nowait().runner()
        for subscriber in subscribers:
            events = []
            while not subscriber.empty():
                events.append(subscriber.get_nowait()["type"])
            assert events == ["stage_begin", "log", "stage_fail"]
            channel.unsubscribe(subscriber)
        assert not style_ledger.holds

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_neighbors", [False, True])
def test_direction_neighbors_commit_only_after_all_proofs(tmp_path, style_ledger, fail_neighbors):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        neighbors = [normalize_suggestion({
            "label": f"N{i}", "medium": f"medium {i}", "template": f"style {i}",
            "role": role,
        }, origin="generated_neighbor") for i, role in enumerate(
            ("story_fit_primary", "adjacent", "contrast", "wildcard")
        )]
        with (
            patch("novel_to_comic.server.routers.styles.ensure_style_sample_brief", new=AsyncMock()),
            patch("novel_to_comic.server.routers.styles.generate_sample_image", new=AsyncMock()),
            patch("novel_to_comic.server.routers.styles.generate_suggestions", new=AsyncMock(return_value=(neighbors, None))),
            patch(
                "novel_to_comic.server.routers.styles.generate_samples_for_indices",
                new=AsyncMock(side_effect=RuntimeError("proof failed") if fail_neighbors else None),
            ),
        ):
            await create_style_direction(
                request, "demo", direction_text="bold ink", label=None,
                with_neighbors=True, image=None, project=project, user_id="user",
            )
            job = request.app.state.generation_queue.get_nowait()
            if fail_neighbors:
                with pytest.raises(RuntimeError, match="proof failed"):
                    await job.runner()
            else:
                await job.runner()
        persisted = load_suggestions(tmp_path)
        assert [item["origin"] for item in persisted] == (
            ["user_text"] if fail_neighbors else ["user_text"] + ["generated_neighbor"] * 4
        )
        assert project[2].stages["style"].status == (
            StageStatus.FAILED if fail_neighbors else StageStatus.AWAITING_REVIEW
        )
        assert not style_ledger.holds

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["direction", "suggest", "samples", "validation"])
def test_style_enqueue_failure_releases_hold(tmp_path, style_ledger, operation):
    async def scenario():
        request = _request()
        project = _project(tmp_path)
        with patch(
            "novel_to_comic.server.credited_job.enqueue_generation_job",
            side_effect=RuntimeError("queue unavailable"),
        ):
            with pytest.raises(RuntimeError, match="queue unavailable"):
                await _queue_style_operation(request, project, operation)
        assert not style_ledger.holds
        assert len(style_ledger.released) == 1
        assert not request.app.state.style_tasks
        if operation in ("direction", "suggest"):
            assert project[2].stages["style"].status == StageStatus.FAILED

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["samples", "validation"])
def test_style_retry_reuses_queued_job_without_another_hold(tmp_path, style_ledger, operation):
    async def scenario():
        request = _request()
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        first = await _queue_style_operation(request, project, operation)
        style_ledger.balance = 0
        second = await _queue_style_operation(request, project, operation)
        assert first == second
        assert request.app.state.generation_queue.qsize() == 1
        request.app.state.generation_queue.get_nowait().on_cancel()
        assert not style_ledger.holds
        assert len(style_ledger.released) == 1

    asyncio.run(scenario())
