"""Mixed local transports preserve API holds without billing Codex calls."""
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


@pytest.mark.parametrize("cancel", [False, True])
def test_mixed_queue_reserves_api_spend_and_releases_hold(tmp_path, monkeypatch, select_routes, cancel):
    from novel_to_comic.ai.context import current_ai_request_context
    from novel_to_comic.usage import UsageRecord

    config = Config()
    select_routes(text=(config.effective_prompt_model(),))
    database = MagicMock()
    monkeypatch.setattr(credited_job, "get_db", lambda: database)
    reserve = MagicMock(return_value=("hold", "job"))
    release = MagicMock()
    monkeypatch.setattr(credited_job, "reserve_credits", reserve)
    monkeypatch.setattr(credited_job, "release_reservation", release)
    monkeypatch.setattr(credited_job, "assert_reservation_active", lambda *args: None)
    executed = []

    async def work():
        assert current_ai_request_context().job_id == "job"
        executed.append("mixed")
        if cancel:
            raise asyncio.CancelledError()
        return ApiResult(value="generated", usage=UsageRecord(
            provider="codex", model=config.effective_prompt_model(), operation="text",
            funding="codex_subscription", input_tokens=100,
        ), additional_usage=(UsageRecord(
            provider="openai", model="gpt-6-astra", operation="text",
            input_tokens=1000, output_tokens=1000,
        ),))

    queue = app()
    job, created = credited_job.enqueue_reserved_generation_job(
        queue, project_name="project", user_id="user", project_id="id",
        project_dir=tmp_path, stage="style", kind="style", label="Style", payload={},
        work=work, debit_description="Style", reservation_credits=10,
        operations=prompt_image_operations(config),
    )
    assert created
    assert reserve.call_args.args[-1] == 10
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(job.runner())
        database.rpc.assert_not_called()
    else:
        asyncio.run(job.runner())
        database.rpc.assert_called_once()
        name, params = database.rpc.call_args.args
        assert name == "settle_model_usage_credits"
        assert params["p_funding"] == "api"
        assert params["p_cost_usd"] == pytest.approx(0.06)
    assert executed == ["mixed"]
    release.assert_called_once_with(database, "hold")


def test_subscription_job_needs_no_credit_hold_or_ledger_entry(tmp_path, monkeypatch, select_routes):
    from novel_to_comic.usage import UsageRecord

    config = Config()
    select_routes(images=(config.effective_image_model(),))
    database = MagicMock()
    monkeypatch.setattr(credited_job, "get_db", lambda: database)

    async def work():
        return ApiResult(value="generated", usage=UsageRecord(
            provider="codex", model=config.effective_image_model(), operation="image",
            funding="codex_subscription", image_count=1,
        ))

    queue = app()
    job, created = credited_job.enqueue_reserved_generation_job(
        queue, project_name="project", user_id="user", project_id="id",
        project_dir=tmp_path, stage="cast", kind="cast", label="Cast", payload={},
        work=work, debit_description="Cast", reservation_credits=99,
        operations=image_operations(config),
    )
    asyncio.run(job.runner())
    assert created
    database.rpc.assert_not_called()


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
    assert codex_dev.classify_operations(style_sample_operations(config)) == "api"
    assert codex_dev.classify_operations(style_sample_operations(config, validation=True)) == "codex_subscription"


@pytest.mark.parametrize("stage", ["extract", "adapt"])
def test_autochain_allows_either_mixed_transport_order(select_routes, stage):
    from novel_to_comic.server.codex_admission import admit_stage_action

    config = Config(extraction_model="gpt-5.6-terra", brief_model="gpt-5.6-luna",
                    adapt_model="gpt-5.6-terra", plan_model="gpt-5.6-luna")
    for alias in ("gpt-5.6-terra", "gpt-5.6-luna"):
        select_routes(text=(alias,))
        assert admit_stage_action(config, stage) == "api"


def test_adapt_admission_uses_only_explicit_adapt_and_plan_models(select_routes):
    config = Config(plan_model="gpt-5.6-luna")
    select_routes(text=(config.effective_adapt_model(), config.effective_plan_model()))
    assert action_operations(config, "adapt") == (
        ("text", config.effective_adapt_model()),
        ("text", config.effective_plan_model()),
    )


def test_dev_draw_allows_either_or_both_codex_selections(select_routes):
    config = Config(draw_model="codex-dev/image/gpt-5.5")
    select_routes(text=(config.effective_page_ocr_model(), config.effective_visual_review_model()))
    assert codex_dev.classify_operations(draw_operations(config)) == "codex_subscription"
    select_routes()
    assert codex_dev.classify_operations(draw_operations(config, checks=False)) == "codex_subscription"
    # Every draw checks its page, so API checks make the draw API-funded.
    assert codex_dev.classify_operations(draw_operations(config)) == "api"
    api_draw = Config()
    select_routes(text=(api_draw.effective_page_ocr_model(), api_draw.effective_visual_review_model()))
    assert codex_dev.classify_operations(draw_operations(api_draw)) == "api"


def test_complete_page_alias_routes_cannot_price_a_codex_page(select_routes):
    config = Config()
    select_routes(images=(config.draw_model,))
    with pytest.raises(codex_dev.CodexRoutingError, match="explicit codex-dev/image"):
        codex_dev.classify_operations(draw_operations(config))


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


@pytest.mark.parametrize("codex_image,codex_checks,expected", [
    (False, False, 0.55), (True, False, 0.05),
    (False, True, 0.50), (True, True, 0.0),
])
def test_draw_estimates_include_only_api_operations(select_routes, monkeypatch, codex_image, codex_checks, expected):
    from novel_to_comic import page_drawing

    config = Config(draw_model="codex-dev/image/gpt-5.5") if codex_image else Config()
    select_routes(text=(config.effective_page_ocr_model(), config.effective_visual_review_model())
                  if codex_checks else ())
    monkeypatch.setattr(page_drawing, "PAGE_OCR_ESTIMATED_COST_USD", 0.02)
    monkeypatch.setattr(page_drawing, "PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD", 0.03)
    monkeypatch.setattr(page_drawing, "estimate_page_request_cost_usd", lambda compiled: 0.50)
    compiled = object()
    # The page read and the visual review are included by default.
    assert page_drawing.estimate_draw_api_cost(config, compiled) == pytest.approx(expected)
    assert page_drawing.estimate_draw_api_cost(config, compiled, checks=False) == (0 if codex_image else 0.50)


@pytest.mark.parametrize("codex_text", [False, True])
def test_instructed_cast_mixed_estimate_excludes_codex_portion(select_routes, tmp_path, codex_text):
    from novel_to_comic.usage import estimate_text_cost, estimate_image_cost

    config = Config()
    select_routes(text=(config.effective_prompt_model(),) if codex_text else (),
                  images=() if codex_text else (config.effective_image_model(),))
    image = credits.UnifiedCostResolver.estimate_asset_regen_cost(config, tmp_path, "prop_ref_regen", "prop")
    combined = credits.UnifiedCostResolver.estimate_instructed_regen_cost(config, image, "cast")
    assert combined["funding"] == "api"
    if codex_text:
        assert estimate_text_cost(config.effective_prompt_model(), 1000, 1000) == 0
        assert combined["estimate_credits"] == image["estimate_credits"] > 0
    else:
        assert estimate_image_cost(config.effective_image_model(), 1) == 0
        assert image["estimate_credits"] == 0
        assert combined["estimate_credits"] > 0


def test_mixed_route_still_rejects_disabled_codex_before_queue(tmp_path, monkeypatch, select_routes):
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({**codex_dev._PROCESS, "CANARY_CODEX_DEV_ENABLED": "0"}))
    database = MagicMock(side_effect=AssertionError("invalid route reached database"))
    monkeypatch.setattr(credited_job, "get_db", database)
    queue = app()
    with pytest.raises(codex_dev.CodexRoutingError, match="ENABLED"):
        credited_job.enqueue_reserved_generation_job(
            queue, project_name="project", user_id="user", project_id="id",
            project_dir=tmp_path, stage="style", kind="style", label="Style", payload={},
            work=MagicMock(), debit_description="Style", reservation_credits=10,
            operations=(("image", "image-gemini-pro"), ("text", "codex-dev/text/gpt-6-sol")),
        )
    database.assert_not_called()
    assert queue.state.generation_queue.empty()


def test_codex_draw_credit_estimate_charges_only_separately_selected_api_checks(select_routes, monkeypatch):
    from novel_to_comic import page_drawing

    config = Config(draw_model="codex-dev/image/gpt-5.5")
    select_routes()
    monkeypatch.setenv("PULP_CREDITS_PER_PROVIDER_USD", "100")
    monkeypatch.setenv("PULP_MODEL_COST_MARKUP", "1.0")
    monkeypatch.setenv("PULP_RESERVATION_BUFFER", "1.25")
    def unexpected_image_price(compiled):
        raise AssertionError("Codex subscription images must not be priced")
    monkeypatch.setattr(page_drawing, "estimate_page_request_cost_usd", unexpected_image_price)
    estimate = page_drawing.correction_credit_estimate(object(), config=config, reserve=True)
    assert estimate["funding"] == "api"
    assert estimate["estimate_credits"] == 3
    assert estimate["reserved_credits"] == 4
    select_routes(text=(config.effective_page_ocr_model(), config.effective_visual_review_model()))
    estimate = page_drawing.correction_credit_estimate(object(), config=config, reserve=True)
    assert estimate["funding"] == "codex_subscription"
    assert estimate["estimate_credits"] == estimate["reserved_credits"] == 0
