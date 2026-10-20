import asyncio
import io
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, UploadFile
from PIL import Image
from starlette.datastructures import Headers
from starlette.requests import Request

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.server.routers.styles import (
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


@pytest.fixture
def tmp_path(tmp_path):
    directory = tmp_path / "user" / "demo"
    directory.mkdir(parents=True)
    return directory


def _request(root, headers=None) -> Request:
    from tests.queue_fixtures import create_app
    app = create_app(root.parent.parent)
    return Request({"type":"http","app":app,"headers":headers or []})


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
    from novel_to_comic.state import save_state
    save_state(state,tmp_path)
    return tmp_path, Config(image_model="image-gemini-pro"), state


def test_credit_failure_leaves_no_direction_artifacts(tmp_path):
    request = _request(tmp_path)
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








def test_direction_upload_cancellation_creates_no_command(tmp_path):
    class BlockingUpload:
        content_type, filename = "image/png", "blocked.png"
        async def read(self, _size):
            await asyncio.Event().wait()
    async def scenario():
        request = _request(tmp_path)
        task = asyncio.create_task(create_style_direction(request,"demo", direction_text="ink",
            label=None,with_neighbors=False,image=BlockingUpload(),project=_project(tmp_path),user_id="user"))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not request.app.state.generation_jobs
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
    request = _request(tmp_path)
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
    assert not request.app.state.generation_jobs
    assert not (tmp_path / "samples").exists()


def test_suggest_setup_failure_never_acquires_a_hold(tmp_path, style_ledger):
    request, project = _request(tmp_path), _project(tmp_path)
    with patch("novel_to_comic.stage_runtime.save_state", side_effect=RuntimeError("disk")):
        with pytest.raises(RuntimeError, match="disk"):
            asyncio.run(suggest_styles(request,"demo",project=project,user_id="user"))
    assert not request.app.state.generation_jobs
    assert not style_ledger.holds
    assert not style_ledger.released




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
    request = _request(tmp_path, [(b"content-length", str(12 * 1024 * 1024).encode())])
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(create_style_direction(
            request, "demo", direction_text="ink", label=None,
            with_neighbors=False, image=None, project=_project(tmp_path), user_id="user",
        ))
    assert exc_info.value.status_code == 413
    assert not any(j.status == "running" for j in request.app.state.generation_jobs.values())



def test_image_backed_direction_estimate_covers_references_and_retry(tmp_path):
    config = Config(image_model="image-sunburst")
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


def test_style_batch_estimates_structured_text_output_and_story_context(tmp_path):
    from novel_to_comic.stages.s2_style import (
        LLM_REQUEST_COUNT, _PRODUCTION_OUTPUT_CHARS, _SKETCH_OUTPUT_CHARS_PER_STYLE,
    )

    _project(tmp_path)
    with patch("novel_to_comic.usage.estimate_text_cost", return_value=.2) as text_cost:
        total = estimate_style_batch_cost_usd(Config(image_model="image-sunburst"), tmp_path, 6)
    sketch, production = text_cost.call_args_list[:2]
    assert sketch.kwargs["output_chars"] == LLM_REQUEST_COUNT * _SKETCH_OUTPUT_CHARS_PER_STYLE
    assert f"Generate {LLM_REQUEST_COUNT} style options" in sketch.args[1]
    assert production.kwargs["output_chars"] == _PRODUCTION_OUTPUT_CHARS
    # Two attempts of one sketch call plus six per-direction production calls.
    assert total >= 2 * (.2 + 6 * .2)


def test_generic_style_quote_uses_proof_geometry():
    from novel_to_comic.server.routers.styles import _style_sample_credit_estimate

    with patch("novel_to_comic.server.routers.styles.estimate_image_cost", return_value=.03) as estimate:
        _style_sample_credit_estimate(Config(image_model="image-sunburst"), has_style_reference=True)
    assert (estimate.call_args.kwargs["width"], estimate.call_args.kwargs["height"]) == (1024, 1280)
    assert estimate.call_args.kwargs["ref_count"] == 1




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
    return install_style_ledger(monkeypatch)


def install_style_ledger(monkeypatch):
    """A fake ledger; admission and execution retain their production implementations."""
    from novel_to_comic.server import credited_job, credits, db
    from novel_to_comic.server.routers import styles
    from novel_to_comic.stages import s2_style
    ledger=SimpleNamespace(balance=10000,holds={},released=[],expired=set())
    def sufficient(_db,_user,required,**kwargs):
        if required > ledger.balance - sum(ledger.holds.values()):
            raise HTTPException(402,"insufficient")
    def reserve(_db,_user,_project,_stage,required,**kwargs):
        sufficient(_db,_user,required)
        key=f"hold-{len(ledger.holds)+len(ledger.released)}"
        ledger.holds[key]=required
        return key,f"ledger-{key}"
    def release(_db,key):
        if key in ledger.holds:
            ledger.holds.pop(key)
            ledger.released.append(key)
    def active(_db,key):
        if key not in ledger.holds or key in ledger.expired:
            raise RuntimeError("Credit reservation expired or ownership was lost")
    for module in (styles,credited_job,db):
        monkeypatch.setattr(module,"get_db",lambda:ledger)
    for module in (styles,credited_job):
        monkeypatch.setattr(module,"assert_sufficient_credits",sufficient)
    monkeypatch.setattr(credits,"reserve_credits",reserve)
    monkeypatch.setattr(credits,"release_reservation",release)
    monkeypatch.setattr(credits,"assert_reservation_active",active)
    monkeypatch.setattr(s2_style,"ensure_style_sample_brief",AsyncMock(return_value=None))
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
def test_style_queue_cancellation_needs_no_hold_or_paid_work(tmp_path, style_ledger, operation):
    async def scenario():
        request, project = _request(tmp_path), _project(tmp_path)
        await _queue_style_operation(request,project,operation)
        job = request.app.state.generation_queue.get_nowait()
        assert not style_ledger.holds
        job.status = "cancelled"
        from novel_to_comic.server.generation_jobs import run_generation_job
        await run_generation_job(request.app,job)
        assert not job.started_at
        assert not style_ledger.holds and not style_ledger.released
    asyncio.run(scenario())


def test_queue_admission_leaves_credits_available_until_execution(tmp_path, style_ledger):
    async def scenario():
        request, project = _request(tmp_path), _project(tmp_path,StageStatus.AWAITING_REVIEW)
        with patch("novel_to_comic.server.routers.styles._style_sample_credit_estimate",
                   return_value={"reserved_credits":10,"estimate_credits":8}):
            style_ledger.balance = 10
            await _queue_style_operation(request,project,"samples")
            await _queue_style_operation(request,project,"validation")
        assert len(request.app.state.generation_jobs) == 2
        assert not style_ledger.holds
        # The worker rechecks available balance before any provider work.
        style_ledger.balance = 0
        with pytest.raises(HTTPException) as exc:
            await request.app.state.generation_queue.get_nowait().runner()
        assert exc.value.status_code == 402
        assert not style_ledger.holds
    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["direction", "suggest", "samples", "validation"])
def test_style_provider_work_runs_under_hold_and_releases_on_success(
    tmp_path, style_ledger, operation,
):
    async def scenario():
        request = _request(tmp_path)
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
            patch("novel_to_comic.stages.s2_style.ensure_style_sample_brief", side_effect=paid),
            patch("novel_to_comic.stages.s2_style.generate_sample_image", side_effect=paid),
            patch("novel_to_comic.stages.s2_style.describe_custom_direction", new=AsyncMock()),
            patch("novel_to_comic.stages.s2_style.generate_suggestions", side_effect=suggestions),
        ):
            await _queue_style_operation(request, project, operation)
            await request.app.state.generation_queue.get_nowait().runner()
        assert calls == [operation] * (1 if operation == "validation" else 3 if operation == "suggest" else 2)
        assert not style_ledger.holds
        assert not any(j.status == "running" for j in request.app.state.generation_jobs.values())
        if operation in ("direction", "suggest"):
            assert __import__("novel_to_comic.state",fromlist=["load_state"]).load_state(tmp_path).stages["style"].status == StageStatus.AWAITING_REVIEW

    asyncio.run(scenario())


def test_suggest_broadcasts_terminal_failure_to_each_subscriber(tmp_path, style_ledger):
    async def scenario():
        request = _request(tmp_path)
        project = _project(tmp_path)
        with patch(
            "novel_to_comic.stages.s2_style.generate_suggestions",
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
            assert events[0] == "stage_begin" and events[-1] == "stage_fail"
            channel.unsubscribe(subscriber)
        assert not style_ledger.holds

    asyncio.run(scenario())


@pytest.mark.parametrize("fail_neighbors", [False, True])
def test_direction_neighbors_keep_candidates_and_record_each_proof_outcome(tmp_path, style_ledger, fail_neighbors):
    async def scenario():
        request = _request(tmp_path)
        project = _project(tmp_path)
        neighbors = [normalize_suggestion({
            "label": f"N{i}", "medium": f"medium {i}", "template": f"style {i}",
            "role": role,
        }, origin="generated_neighbor") for i, role in enumerate(
            ("story_fit_primary", "story_fit_secondary", "adjacent", "contrast", "wildcard")
        )]
        images = 0
        async def proof(*args,**kwargs):
            nonlocal images
            images += 1
            if fail_neighbors and images > 1:
                raise RuntimeError("proof failed")
        with (
            patch("novel_to_comic.stages.s2_style.ensure_style_sample_brief", new=AsyncMock()),
            patch("novel_to_comic.stages.s2_style.generate_sample_image", new=proof),
            patch("novel_to_comic.stages.s2_style.describe_custom_direction", new=AsyncMock()),
            patch("novel_to_comic.stages.s2_style.generate_suggestions", new=AsyncMock(return_value=(neighbors, None))),
            patch(
                "novel_to_comic.stages.s2_style.generate_samples_for_indices",
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
            ["user_text"] + ["generated_neighbor"] * 5
        )
        assert __import__("novel_to_comic.state",fromlist=["load_state"]).load_state(tmp_path).stages["style"].status == (
            StageStatus.FAILED if fail_neighbors else StageStatus.AWAITING_REVIEW
        )
        assert not style_ledger.holds

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["direction", "suggest", "samples", "validation"])
def test_style_enqueue_failure_releases_hold(tmp_path, style_ledger, operation):
    async def scenario():
        request = _request(tmp_path)
        project = _project(tmp_path)
        with patch(
            "novel_to_comic.server.credited_job.enqueue_generation_job",
            side_effect=RuntimeError("queue unavailable"),
        ):
            with pytest.raises(RuntimeError, match="queue unavailable"):
                await _queue_style_operation(request, project, operation)
        assert not style_ledger.holds
        assert len(style_ledger.released) == 0
        assert not any(j.status == "running" for j in request.app.state.generation_jobs.values())
        if operation in ("direction", "suggest"):
            assert __import__("novel_to_comic.state",fromlist=["load_state"]).load_state(tmp_path).stages["style"].status == StageStatus.FAILED

    asyncio.run(scenario())


@pytest.mark.parametrize("operation", ["samples", "validation"])
def test_style_retry_reuses_queued_job_without_another_hold(tmp_path, style_ledger, operation):
    async def scenario():
        request = _request(tmp_path)
        project = _project(tmp_path, StageStatus.AWAITING_REVIEW)
        first = await _queue_style_operation(request, project, operation)
        style_ledger.balance = 0
        second = await _queue_style_operation(request, project, operation)
        assert first == second
        assert request.app.state.generation_queue.qsize() == 1
        request.app.state.generation_queue.get_nowait().status = "cancelled"
        assert not style_ledger.holds
        assert len(style_ledger.released) == 0

    asyncio.run(scenario())


def test_author_direction_queues_without_restarting_a_running_style_stage(tmp_path, style_ledger):
    async def scenario():
        request = _request(tmp_path)
        project = _project(tmp_path, StageStatus.RUNNING)
        stage = project[2].stages["style"]
        stage.items_total, stage.items_done = 6, 2
        result = await _queue_style_operation(request, project, "direction")
        assert result["status"] == "queued"
        assert (stage.items_total, stage.items_done, stage.status) == (6, 2, StageStatus.RUNNING)
        job = request.app.state.generation_queue.get_nowait()
        job.status = "cancelled"
        assert stage.status == StageStatus.RUNNING

    asyncio.run(scenario())


def test_default_and_directed_quotes_price_six_and_five_images(tmp_path):
    from novel_to_comic.server.routers.styles import (
        _direction_credit_estimates, _suggest_batch_credit_estimate,
    )
    from novel_to_comic.stages.s2_style import SAMPLE_COUNT, NEIGHBOR_COUNT

    project = _project(tmp_path)
    with (
        patch("novel_to_comic.server.routers.styles.estimate_style_batch_cost_usd", return_value=.5) as batch,
        patch("novel_to_comic.server.routers.styles.estimate_style_proof_cost_usd", return_value=.1),
    ):
        _suggest_batch_credit_estimate(project[1], tmp_path)
        assert batch.call_args.args[2] == SAMPLE_COUNT == 6
        batch.reset_mock()
        _direction_credit_estimates(project[1], tmp_path)
        assert batch.call_count == 2  # neighbors alone and faithful + neighbors
        assert all(call.args[2] == NEIGHBOR_COUNT == 5 for call in batch.call_args_list)


def test_six_proof_progress_is_monotonic_when_images_finish_out_of_order(tmp_path,style_ledger):
    from tests.test_style_stage import _batch
    from novel_to_comic.state import load_state
    from novel_to_comic.stages import s2_style
    async def scenario():
        request,project = _request(tmp_path),_project(tmp_path)
        candidates=[normalize_suggestion(item) for item in _batch(count=6)["styles"]]
        async def image(_config,_bible,path,**kwargs):
            await asyncio.sleep(0.001 * (sum(path.name.encode()) % 7))
        with patch.object(s2_style,"generate_suggestions",new=AsyncMock(return_value=(candidates,None))), \
             patch.object(s2_style,"generate_sample_image",new=image):
            await suggest_styles(request,"demo",None,project=project,user_id="user")
            await request.app.state.generation_queue.get_nowait().runner()
        progress=[e["done"] for e in request.app.state.event_queues["user:demo"].history if e["type"]=="stage_progress"]
        assert progress == sorted(progress) and progress[-1] == 6
        assert load_state(tmp_path).stages["style"].items_done == 6
        assert len(load_suggestions(tmp_path)) == 6
        assert not style_ledger.holds
    asyncio.run(scenario())
