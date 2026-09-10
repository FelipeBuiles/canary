"""Whole-action funding is decided before money, mutations, or provider work."""
import asyncio
from types import MappingProxyType, SimpleNamespace
from unittest.mock import MagicMock

import pytest

from novel_to_comic import codex_dev
from novel_to_comic.config import Config
from novel_to_comic.server import credited_job, credits
from novel_to_comic.server.codex_admission import (
    action_operations,
    draw_operations,
    image_operations,
    prompt_image_operations,
    style_sample_operations,
)
from novel_to_comic.usage import ApiResult


@pytest.fixture
def select_routes(monkeypatch):
    process = dict.fromkeys(codex_dev._PROCESS)
    process.update(CANARY_CODEX_DEV_ENABLED="1", CANARY_ENV="development")
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(process))
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    monkeypatch.setattr(codex_dev, "_IMAGE_REASONING", "gpt-5.6-terra")

    def select(*, text=(), images=()):
        routes = text if isinstance(text, dict) else {alias: "gpt-5.6-terra" for alias in text}
        monkeypatch.setattr(codex_dev, "_TEXT", MappingProxyType(routes))
        monkeypatch.setattr(codex_dev, "_IMAGES", frozenset(images))

    select()
    return select


def app():
    return SimpleNamespace(state=SimpleNamespace(
        generation_jobs={}, generation_job_sequence=0, generation_queue=asyncio.Queue(),
    ))


def test_mixed_queue_refused_before_hold_or_publication(tmp_path, monkeypatch, select_routes):
    config = Config()
    select_routes(text=(config.effective_prompt_model(),))
    database = MagicMock(side_effect=AssertionError("admission must precede the database"))
    monkeypatch.setattr(credited_job, "get_db", database)
    queue = app()

    async def work():
        raise AssertionError("mixed work must never execute")

    with pytest.raises(codex_dev.CodexRoutingError):
        credited_job.enqueue_reserved_generation_job(
            queue, project_name="project", user_id="user", project_id="id",
            project_dir=tmp_path, stage="style", kind="style_suggest", label="Style",
            payload={}, work=work, debit_description="Style", reservation_credits=10,
            operations=prompt_image_operations(config),
        )
    database.assert_not_called()
    assert queue.state.generation_jobs == {}
    assert queue.state.generation_queue.empty()


def test_subscription_job_has_no_hold_and_pins_execution_funding(tmp_path, monkeypatch, select_routes):
    config = Config()
    alias = config.effective_image_model()
    select_routes(images=(alias,))
    database = MagicMock()
    monkeypatch.setattr(credited_job, "get_db", lambda: database)
    executed = []

    async def work():
        codex_dev.assert_request_funding("image", alias, require_admission=True)
        with pytest.raises(codex_dev.CodexRoutingError):
            codex_dev.assert_request_funding("text", "unselected-api-model")
        executed.append("subscription")
        return ApiResult(value="generated")

    queue = app()
    job, created = credited_job.enqueue_reserved_generation_job(
        queue, project_name="project", user_id="user", project_id="id",
        project_dir=tmp_path, stage="cast", kind="cast", label="Cast", payload={},
        work=work, debit_description="Cast", reservation_credits=99,
        operations=image_operations(config),
    )
    asyncio.run(job.runner())
    assert created and job.id in queue.state.generation_jobs
    assert executed == ["subscription"]
    database.rpc.assert_not_called()
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.assert_request_funding("image", alias, require_admission=True)


def test_subscription_quotes_bypass_tariffs_and_minimums(tmp_path, monkeypatch, select_routes):
    config = Config()
    select_routes(images=(config.effective_image_model(),), text=(config.effective_prompt_model(),))
    monkeypatch.setattr(credits, "estimate_image_cost", lambda *a, **k: pytest.fail("API tariff used"))
    monkeypatch.setattr(credits, "estimate_text_cost", lambda *a, **k: pytest.fail("API tariff used"))
    image = credits.UnifiedCostResolver.estimate_asset_regen_cost(config, tmp_path, "prop_ref_regen", "prop")
    instructed = credits.UnifiedCostResolver.estimate_instructed_regen_cost(config, image, "cast")
    for estimate in (image, instructed):
        assert estimate["funding"] == "codex_subscription"
        assert estimate["estimate_credits"] == estimate["reserved_credits"] == 0


def test_missing_style_brief_is_included_but_validation_is_image_only(select_routes):
    config = Config(style_sample_brief_enabled=True)
    select_routes(images=(config.effective_image_model(),))
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.classify_operations(style_sample_operations(config))
    assert codex_dev.classify_operations(style_sample_operations(config, validation=True)) == "codex_subscription"


def test_instructed_cast_refuses_before_rewrite_or_asset_mutation(tmp_path, monkeypatch, select_routes):
    from novel_to_comic import cast_instructions

    config = Config()
    select_routes(images=(config.effective_image_model(),))
    resolve = MagicMock(side_effect=AssertionError("mixed action reached asset handling"))
    monkeypatch.setattr(cast_instructions, "resolve_cast_asset", resolve)
    database = MagicMock()
    with pytest.raises(codex_dev.CodexRoutingError):
        asyncio.run(cast_instructions.apply_asset_instruction(
            config, tmp_path, database, "user", "project", "character", "ada", "Change the hat",
        ))
    resolve.assert_not_called()
    database.rpc.assert_not_called()


def test_adapt_autochain_refuses_before_start_and_approval_mutation(tmp_path, monkeypatch, select_routes):
    from novel_to_comic.server.routers import pipeline
    from novel_to_comic.state import StageStatus, create_initial_state

    config = Config(plan_model="gpt-5.6-luna")
    select_routes(text=(config.effective_adapt_model(),))
    state = create_initial_state("project", "novel.txt")
    state.stages["cast"].status = StageStatus.AWAITING_REVIEW
    project = (tmp_path, config, state)
    request = SimpleNamespace(app=app())
    save = MagicMock(side_effect=AssertionError("mixed chain mutated state"))
    monkeypatch.setattr(pipeline, "save_state", save)
    with pytest.raises(codex_dev.CodexRoutingError):
        asyncio.run(pipeline._start_stage(request, "id", "adapt", False, project, "user"))
    with pytest.raises(codex_dev.CodexRoutingError):
        asyncio.run(pipeline.approve("cast", "id", request, project, "user"))
    save.assert_not_called()
    assert state.stages["cast"].status == StageStatus.AWAITING_REVIEW


def test_adapt_admission_uses_only_explicit_adapt_and_plan_models(select_routes):
    config = Config(plan_model="gpt-5.6-luna")
    select_routes(text=(config.effective_adapt_model(), config.effective_plan_model()))
    assert action_operations(config, "adapt") == (
        ("text", config.effective_adapt_model()),
        ("text", config.effective_plan_model()),
    )


def test_dev_draw_requires_both_complete_page_and_ocr_selection(select_routes):
    config = Config()
    select_routes(images=("image-gemini-pro",), text=(config.effective_page_ocr_model(),))
    assert codex_dev.classify_operations(draw_operations(config)) == "codex_subscription"
    select_routes(images=("image-gemini-pro",))
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.classify_operations(draw_operations(config))
    select_routes(text=(config.effective_page_ocr_model(),))
    with pytest.raises(codex_dev.CodexRoutingError):
        codex_dev.classify_operations(draw_operations(config))
    select_routes(images=("image-gpt-2",))
    assert codex_dev.classify_operations(draw_operations(config)) == "api"


def test_cached_page_recovery_needs_neither_selected_route_nor_hold(tmp_path, monkeypatch, select_routes):
    database = MagicMock(side_effect=AssertionError("cache recovery needs no database"))
    monkeypatch.setattr(credited_job, "get_db", database)

    async def work():
        raise AssertionError("cache recovery called a provider")

    result = asyncio.run(credited_job.run_credited_page_check(
        user_id="user", project_id="id", project_dir=tmp_path, page_number=1,
        estimated_cost_usd=1, work=work, cached_work=lambda: {"recovered": True},
        operations=(("text", "codex-dev/unmapped"),),
    ))
    assert result == {"recovered": True}
    database.assert_not_called()
