import hashlib
import json

from fastapi.testclient import TestClient
from PIL import Image

from novel_to_comic.ai import client as ai_client
from novel_to_comic.config import Config, mock_mode_active
from novel_to_comic.mock_models import create_app
from novel_to_comic.server.credits import estimate_stage_credit_reservation, usage_to_credit_debit
from novel_to_comic.usage import UsageRecord


def _fixture_project(tmp_path):
    project = tmp_path / "the-call-of-cthulhu"
    (project / "samples").mkdir(parents=True)
    (project / "screenplays").mkdir()
    (project / "plan").mkdir()
    (project / "assembly").mkdir()
    (project / "draw" / "scene_001").mkdir(parents=True)
    (project / "story_bible.json").write_text(json.dumps({"title": "The Call of Cthulhu"}))
    (project / "samples" / "style_suggestions.json").write_text(json.dumps({
        "suggestions": [{"id": "style_1", "label": "Scratchboard"}],
    }))
    (project / "samples" / "style_sample_brief.json").write_text(json.dumps({
        "brief": "A quiet investigator studies an ancient clay idol beneath a shaded desk lamp.",
    }))
    (project / "screenplays" / "scene_001.json").write_text(json.dumps({
        "scene_id": "scene_001",
        "location_id": "loc_001",
        "characters": [],
        "beats": [{"type": "action", "content": "An investigator opens a file."}],
    }))
    (project / "plan" / "layout_plan.json").write_text(json.dumps({
        "planned_panels": [{
            "panel_id": "scene_001:panel_001",
            "scene_id": "scene_001",
            "beat_ids": ["scene_001:beat_001"],
            "lighting": "green desk lamp",
        }],
        "narration_decisions": [{
            "scene_id": "scene_001",
            "beat_index": 1,
            "decision": "rendered",
            "mode": "attached_caption",
            "panel_id": "scene_001:panel_001",
            "decision_reason": "Opening context.",
        }],
    }))
    (project / "assembly" / "lettering_style.json").write_text(json.dumps({
        "label": "Expressionist Woodcut",
        "rationale": "Heavy borders match the fixture art.",
        "theme": "noir",
        "font_pair": "horror",
        "vars": {"--panel-border": "#0A0A0A"},
    }))
    prompt = "Cthulhu fixture prompt"
    image_path = project / "draw" / "scene_001" / "panel_001.png"
    Image.new("RGB", (64, 64), "#123456").save(image_path)
    image_path.with_suffix(".png.meta.json").write_text(json.dumps({"prompt": prompt}))
    return project, prompt


def _chat_payload(feature, user=""):
    return {
        "model": "prompt-balanced",
        "messages": [{"role": "user", "content": user}],
        "metadata": {"metadata": {"feature": feature}},
    }


def test_mock_service_replays_text_and_zero_cost(tmp_path):
    project, _prompt = _fixture_project(tmp_path)
    client = TestClient(create_app(project))

    response = client.post("/v1/chat/completions", json=_chat_payload("extract.story_bible"))

    assert response.status_code == 200
    body = response.json()
    assert json.loads(body["choices"][0]["message"]["content"])["title"] == "The Call of Cthulhu"
    assert body["model"] == "canary-mock"
    assert body["_hidden_params"]["response_cost"] == 0.0


def test_mock_service_projects_recorded_plan_by_scene(tmp_path):
    project, _prompt = _fixture_project(tmp_path)
    client = TestClient(create_app(project))

    response = client.post(
        "/v1/chat/completions",
        json=_chat_payload("plan.scene_layout", "Scene: scene_001"),
    )

    plan = json.loads(response.json()["choices"][0]["message"]["content"])
    assert plan["panels"][0]["beat_indices"] == [1]
    assert plan["narration_decisions"][0]["panel_index"] == 1


def test_mock_service_replays_and_resizes_image(tmp_path):
    project, prompt = _fixture_project(tmp_path)
    client = TestClient(create_app(project))

    response = client.post("/v1/images/generations", json={
        "prompt": prompt,
        "canary_requested_width": 320,
        "canary_requested_height": 512,
    })

    assert response.status_code == 200
    import base64
    import io
    with Image.open(io.BytesIO(base64.b64decode(response.json()["data"][0]["b64_json"]))) as image:
        assert image.size == (320, 512)


def test_mock_service_supports_compose_text_callbacks(tmp_path):
    project, _prompt = _fixture_project(tmp_path)
    client = TestClient(create_app(project))

    lettering = client.post(
        "/v1/chat/completions",
        json=_chat_payload("compose.lettering_style"),
    ).json()
    lettering_value = json.loads(lettering["choices"][0]["message"]["content"])
    assert lettering_value["label"] == "Expressionist Woodcut"

    translated = client.post(
        "/v1/chat/completions",
        json=_chat_payload(
            "compose.translate_text",
            'Target language: French\n\nItems:\n[{"id":"p1:b1","text":"The stars are right."}]',
        ),
    ).json()
    translated_value = json.loads(translated["choices"][0]["message"]["content"])
    assert translated_value == {"items": [{"id": "p1:b1", "text": "The stars are right."}]}


def test_mock_mode_requires_operator_gate(monkeypatch):
    config = Config(mock_mode=True)
    monkeypatch.delenv("CANARY_MOCK_GENERATIONS_ENABLED", raising=False)
    assert not mock_mode_active(config)
    import pytest
    with pytest.raises(RuntimeError, match="refusing to fall back"):
        ai_client._base_url(config)

    monkeypatch.setenv("CANARY_MOCK_GENERATIONS_ENABLED", "true")
    assert mock_mode_active(config)
    assert ai_client._base_url(config) == config.mock_model_base_url


def test_mock_usage_and_stage_estimates_are_zero(monkeypatch, tmp_path):
    monkeypatch.setenv("CANARY_MOCK_GENERATIONS_ENABLED", "true")
    config = Config(mock_mode=True)
    usage = UsageRecord(
        provider="litellm",
        model="image-quality",
        provider_model="canary-mock",
        operation="image",
        image_count=1,
        cost_usd=0.0,
        cost_source="mock",
    )
    assert usage_to_credit_debit(usage) == (0, 0.0)

    assert estimate_stage_credit_reservation(config, tmp_path, object(), "draw") == 0


def test_mock_provider_usage_is_marked_mock():
    usage = ai_client._extract_usage(
        {"model": "canary-mock", "_hidden_params": {"response_cost": 0.0}},
        hashlib.sha256(b"call").hexdigest(),
        "image-quality",
        "image",
    )
    assert usage.cost_source == "mock"
    assert usage.cost_usd == 0.0
