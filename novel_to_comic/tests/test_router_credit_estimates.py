"""Focused API coverage for per-image regeneration credit estimates."""

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic.config import Config
from novel_to_comic.server import credits
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.deps import get_project
from novel_to_comic.server.routers import pipeline, projects, styles


@pytest.fixture
def estimate_client(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(pipeline.router, prefix="/api/projects/{project_id}")
    app.include_router(styles.router, prefix="/api/projects/{project_id}")
    app.include_router(projects.router, prefix="/api/projects")
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    app.dependency_overrides[get_current_user] = lambda: "user_001"

    calls = []

    def fake_asset_estimate(config, project_dir, asset_type, asset_id):
        calls.append((config, project_dir, asset_type, asset_id))
        return {
            "estimate_credits": 4,
            "reserved_credits": None,
            "reservation_multiplier": 1.0,
            "confidence": "high",
        }

    monkeypatch.setattr(
        pipeline.UnifiedCostResolver,
        "estimate_asset_regen_cost",
        fake_asset_estimate,
    )
    monkeypatch.setattr(
        pipeline.UnifiedCostResolver,
        "estimate_instructed_regen_cost",
        lambda config, image_estimate, stage: {
            "estimate_credits": image_estimate["estimate_credits"] + 2,
            "reserved_credits": None,
            "reservation_multiplier": 1.0,
            "confidence": "variable",
        },
    )
    monkeypatch.setattr(
        projects,
        "_project_cover_credit_estimate",
        lambda config: {
            "estimate_credits": 3,
            "reserved_credits": None,
            "reservation_multiplier": 1.0,
            "confidence": "low_variance",
        },
    )
    return TestClient(app), calls


def test_project_cover_estimate_uses_the_generation_precheck_estimate(estimate_client):
    client, _calls = estimate_client

    response = client.get("/api/projects/demo/cover-estimate")

    assert response.status_code == 200
    assert response.json() == {
        "estimate_credits": 3,
        "reserved_credits": None,
        "reservation_multiplier": 1.0,
        "confidence": "low_variance",
    }


@pytest.mark.parametrize(
    ("asset_type", "asset_id", "resolver_kind"),
    [
        ("character", "char_001", "character_ref_regen"),
        ("location", "loc_001", "location_plate_regen"),
        ("prop", "prop_001", "prop_ref_regen"),
    ],
)
def test_asset_regen_estimate_maps_allowlisted_asset_types(
    estimate_client,
    asset_type,
    asset_id,
    resolver_kind,
):
    client, calls = estimate_client

    response = client.get(
        "/api/projects/demo/asset-regen-estimate",
        params={"asset_type": asset_type, "asset_id": asset_id},
    )

    assert response.status_code == 200
    assert response.json() == {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "state_id": None,
        "estimate_credits": 4,
        "reserved_credits": None,
        "reservation_multiplier": 1.0,
        "confidence": "high",
        "instruction_estimate": {
            "estimate_credits": 6,
            "reserved_credits": None,
            "reservation_multiplier": 1.0,
            "confidence": "variable",
        },
    }
    assert calls[-1][2:] == (resolver_kind, asset_id)


def test_asset_regen_estimate_passes_appearance_state_to_resolver(estimate_client):
    client, calls = estimate_client

    response = client.get(
        "/api/projects/demo/asset-regen-estimate",
        params={
            "asset_type": "character",
            "asset_id": "char_001",
            "state_id": "silver-hands",
        },
    )

    assert response.status_code == 200
    assert response.json()["state_id"] == "silver-hands"
    assert calls[-1][2:] == ("character_ref_regen", "char_001:silver-hands")


@pytest.mark.parametrize(
    "params",
    [
        {"asset_type": "panel", "asset_id": "panel_001"},
        {"asset_type": "character", "asset_id": "../char_001"},
        {"asset_type": "location", "asset_id": "loc_001", "state_id": "../night"},
        {"asset_type": "prop", "asset_id": "prop_001", "state_id": "broken"},
    ],
)
def test_asset_regen_estimate_rejects_unallowlisted_or_unsafe_input(
    estimate_client,
    params,
):
    client, calls = estimate_client

    response = client.get(
        "/api/projects/demo/asset-regen-estimate",
        params=params,
    )

    assert response.status_code == 400
    assert calls == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/projects/demo/asset-regen-estimate?asset_type=prop&asset_id=prop_001",
        "/api/projects/demo/styles/sample-estimate",
        "/api/projects/demo/cover-estimate",
    ],
)
def test_regen_estimate_endpoints_require_authentication(tmp_path, path):
    app = FastAPI()
    app.include_router(pipeline.router, prefix="/api/projects/{project_id}")
    app.include_router(styles.router, prefix="/api/projects/{project_id}")
    app.include_router(projects.router, prefix="/api/projects")
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)

    response = TestClient(app).get(path)

    assert response.status_code == 401


def test_panel_regen_estimate_includes_combined_instruction_estimate(
    tmp_path, monkeypatch,
):
    image_estimate = {
        "estimate_credits": 5,
        "reserved_credits": None,
        "reservation_multiplier": 1.25,
        "confidence": "variable",
    }
    combined_estimate = {**image_estimate, "estimate_credits": 8}
    monkeypatch.setattr(
        pipeline.UnifiedCostResolver,
        "estimate_panel_regen_cost",
        lambda *args: image_estimate,
    )
    monkeypatch.setattr(
        pipeline.UnifiedCostResolver,
        "estimate_instructed_regen_cost",
        lambda *args: combined_estimate,
    )

    response = asyncio.run(pipeline.regen_panel_estimate(
        "demo",
        scene_id="scene_001",
        panel_number=1,
        image_model_alias=None,
        project=(tmp_path, Config(), None),
        user_id="user_001",
    ))

    assert response == {
        "scene_id": "scene_001",
        "panel_number": 1,
        **image_estimate,
        "instruction_estimate": combined_estimate,
    }


def test_instructed_estimate_adds_conservative_prompt_rewrite_cost(monkeypatch):
    captured = {}

    def fake_text_cost(model, input_text, output_chars=0):
        captured.update(
            model=model,
            input_chars=input_text,
            output_chars=output_chars,
        )
        return 0.02

    monkeypatch.setattr(credits, "estimate_text_cost", fake_text_cost)
    image_estimate = credits.CreditEstimate(
        estimate_credits=4,
        reserved_credits=None,
        reservation_multiplier=1.25,
        confidence="variable",
    )

    combined = credits.UnifiedCostResolver.estimate_instructed_regen_cost(
        Config(), image_estimate, "cast"
    )

    assert combined["estimate_credits"] > image_estimate["estimate_credits"]
    assert combined["confidence"] == "variable"
    assert captured == {
        "model": Config().effective_prompt_model(),
        "input_chars": credits.INSTRUCTION_REWRITE_INPUT_CHARS,
        "output_chars": credits.INSTRUCTION_REWRITE_OUTPUT_CHARS,
    }


def test_panel_instruction_estimate_covers_the_explicit_rewrite(monkeypatch):
    calls = []
    monkeypatch.setattr(
        credits,
        "estimate_text_cost",
        lambda *args, **kwargs: calls.append((args, kwargs)) or 0.01,
    )
    image_estimate = credits.CreditEstimate(
        estimate_credits=4,
        reserved_credits=None,
        reservation_multiplier=1.25,
        confidence="variable",
    )

    combined = credits.UnifiedCostResolver.estimate_instructed_regen_cost(
        Config(), image_estimate, "draw"
    )

    assert len(calls) == credits.INSTRUCTION_TEXT_CALLS_BY_STAGE["draw"] == 1
    assert combined["estimate_credits"] >= image_estimate["estimate_credits"] + 1


def test_style_sample_estimate_uses_shared_one_sample_calculation(
    estimate_client,
    monkeypatch,
):
    client, _calls = estimate_client
    captured = {}

    def fake_image_cost(model, count, *, quality=None):
        captured.update(model=model, count=count, quality=quality)
        return 0.025

    monkeypatch.setattr(styles, "estimate_image_cost", fake_image_cost)

    response = client.get("/api/projects/demo/styles/sample-estimate")

    assert response.status_code == 200
    assert response.json() == styles._style_sample_credit_estimate(Config())
    assert captured == {
        "model": Config().effective_image_model(),
        "count": 1,
        "quality": Config().image_quality,
    }


def test_generate_samples_uses_same_style_sample_estimate(
    tmp_path,
    monkeypatch,
):
    class CreditCheckReached(Exception):
        pass

    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(running_tasks={}, style_tasks={}),
        ),
    )
    monkeypatch.setattr(
        styles,
        "load_suggestions",
        lambda _project_dir: [
            {"template": "ink"},
            {"template": "watercolor"},
        ],
    )
    monkeypatch.setattr(styles, "_get_bible", lambda _project_dir: object())
    monkeypatch.setattr(
        styles,
        "_style_sample_credit_estimate",
        lambda _config: {"estimate_credits": 6},
    )
    monkeypatch.setattr(styles, "get_db", lambda: object())

    def assert_credits(_db, user_id, required, *, action):
        assert user_id == "user_001"
        assert required == 12
        assert action == "style_sample_regen"
        raise CreditCheckReached

    monkeypatch.setattr(styles, "assert_sufficient_credits", assert_credits)

    with pytest.raises(CreditCheckReached):
        asyncio.run(
            styles.generate_style_samples(
                request,
                "demo",
                {"indices": [1, 2]},
                project=(tmp_path, Config(), None),
                user_id="user_001",
            )
        )
