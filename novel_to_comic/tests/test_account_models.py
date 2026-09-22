"""Account model preferences must remain isolated and operator-gated."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import MappingProxyType

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from novel_to_comic import codex_dev
from novel_to_comic.config import Config, load_config, save_config
from novel_to_comic.server.account_models import account_config, read_selections, update_selections
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.routers.account_models import router


@pytest.fixture
def client(tmp_path, monkeypatch):
    original = dict(codex_dev._PROCESS)
    original.update(CANARY_ENV="development", ENV="development", FLY_APP_NAME=None,
                    FLY_MACHINE_ID=None, RENDER=None, RAILWAY_ENVIRONMENT=None,
                    K_SERVICE=None, VERCEL=None)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(original))
    monkeypatch.setattr(codex_dev, "_TEXT", {})
    monkeypatch.setattr(codex_dev, "_IMAGES", frozenset())
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    app = FastAPI()
    app.state.projects_dir = tmp_path
    app.include_router(router, prefix="/api/account")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    return TestClient(app)


def test_account_preferences_persist_and_do_not_leak(client, tmp_path):
    result = client.patch("/api/account/model-settings", json={"selections": {"adapt": "deepseek-v4.1-flash"}})
    assert result.status_code == 200
    assert read_selections(tmp_path, "alice")["adapt"] == "deepseek-v4.1-flash"
    assert read_selections(tmp_path, "bob")["adapt"] == "gpt-5.6-terra"
    assert client.get("/api/account/model-settings").json()["selections"]["adapt"] == "deepseek-v4.1-flash"


def test_model_change_does_not_change_existing_job_snapshot(client, tmp_path):
    snapshot = account_config(Config(), tmp_path, "alice")
    client.patch("/api/account/model-settings", json={"selections": {"plan": "gpt-5.6-luna"}})
    assert snapshot.plan_model == "gpt-5.6-terra"
    assert account_config(Config(), tmp_path, "alice").plan_model == "gpt-5.6-luna"


@pytest.mark.parametrize("changes", [
    {"draw": "deepseek-v4.1-flash"}, {"adapt": "deepseek-v4-flash"},
    {"unknown": "gpt-5.6-terra"}, {"image": "image-reve"},
    {"ocr": "https://untrusted.invalid/model"},
])
def test_rejects_unsupported_or_wrong_modality_models(client, changes):
    assert client.patch("/api/account/model-settings", json={"selections": changes}).status_code == 400


def test_muse_is_selectable_for_style_cast_and_draw(client):
    catalog = client.get("/api/account/model-settings").json()
    stages = {stage["id"]: stage["model_ids"] for stage in catalog["stages"]}
    assert "image-muse" in stages["image"]
    assert "image-muse" in stages["draw"]
    assert client.patch(
        "/api/account/model-settings", json={"selections": {"image": "image-muse", "draw": "image-muse"}},
    ).status_code == 200


@pytest.mark.parametrize("original", [{"CANARY_ENV": "production"}, {"FLY_APP_NAME": "hosted"}, {"ENV": "production"}])
def test_gate_uses_original_process_not_project_env(client, monkeypatch, original):
    values = dict(codex_dev._PROCESS)
    values.update(original)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(values))
    monkeypatch.setenv("CANARY_ENV", "development")
    assert client.get("/api/account/model-settings").status_code == 403
    assert client.patch("/api/account/model-settings", json={"selections": {}}).status_code == 403


def test_authentication_required(client):
    from fastapi import HTTPException
    def reject():
        raise HTTPException(401, "Sign in")
    client.app.dependency_overrides[get_current_user] = reject
    assert client.get("/api/account/model-settings").status_code == 401


def test_concurrent_partial_updates_preserve_both_fields(client, tmp_path):
    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(update_selections, tmp_path, "alice", change) for change in (
            {"adapt": "deepseek-v4.1-flash"}, {"prompt": "gemini-3.8-flash"},
        )]
        for result in futures:
            result.result()
    choices = read_selections(tmp_path, "alice")
    assert choices["adapt"] == "deepseek-v4.1-flash"
    assert choices["prompt"] == "gemini-3.8-flash"


def test_project_files_cannot_override_account_models(client, tmp_path):
    project = tmp_path / "alice" / "novel"
    project.mkdir(parents=True)
    (project / "config.yaml").write_text('adapt_model: arbitrary-endpoint\nquality_preset: quality\n')
    config, _ = load_config(project)
    assert config.adapt_model == "gpt-5.6-terra"
    save_config(config, project)
    assert "quality_preset:" not in (project / "config.yaml").read_text()
    assert "adapt_model:" not in (project / "config.yaml").read_text()


def test_api_choice_cannot_silently_use_subscription(client, monkeypatch):
    values = dict(codex_dev._PROCESS)
    values["CANARY_CODEX_DEV_ENABLED"] = "1"
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(values))
    monkeypatch.setattr(codex_dev, "_TEXT", {"gpt-5.6-terra": "gpt-5.6-terra"})
    result = client.patch("/api/account/model-settings", json={"selections": {"adapt": "gpt-5.6-terra"}})
    assert result.status_code == 400
    assert "Codex" in result.json()["detail"]


def test_catalog_matches_exact_gateway_and_pricing_routes(client):
    import yaml
    root = Path(__file__).resolve().parents[2]
    gateway = yaml.safe_load((root / "litellm/config.yaml").read_text())
    aliases = {item["model_name"]: item["litellm_params"]["model"] for item in gateway["model_list"]}
    assert aliases["deepseek-v4.1-flash"] == "openrouter/deepseek/deepseek-v4.1-flash"
    catalog = client.get("/api/account/model-settings").json()
    assert {model["id"] for model in catalog["models"] if model["funding"] == "api"} <= aliases.keys()
    assert [stage["id"] for stage in catalog["stages"]] == [
        "extract", "brief", "prompt", "image", "adapt", "plan", "draw", "ocr", "visual_review",
    ]
    for stage in catalog["stages"]:
        assert stage["description"]
        assert catalog["selections"][stage["id"]] in stage["model_ids"]


def test_project_language_patch_does_not_persist_account_models(client, tmp_path):
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.config import router as config_router
    project = tmp_path / "alice" / "novel"
    project.mkdir(parents=True)
    update_selections(tmp_path, "alice", {"adapt": "deepseek-v4.1-flash"})
    config = account_config(Config(), tmp_path, "alice")
    client.app.include_router(config_router, prefix="/api/projects/{project_id}/config")
    client.app.dependency_overrides[get_project] = lambda: (project, config, None)
    result = client.patch("/api/projects/novel/config/", json={"target_language": "es"})
    assert result.status_code == 200
    content = (project / "config.yaml").read_text()
    assert 'target_language: "es"' in content
    assert "deepseek" not in content
    assert "adapt_model:" not in content
    assert read_selections(tmp_path, "alice")["adapt"] == "deepseek-v4.1-flash"


def test_project_config_patch_rejects_model_override(client, tmp_path):
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.config import router as config_router
    client.app.include_router(config_router, prefix="/api/projects/{project_id}/config")
    client.app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    result = client.patch("/api/projects/novel/config/", json={"adapt_model": "gpt-5.6-luna"})
    assert result.status_code == 400
    assert not (tmp_path / "config.yaml").exists()


def enable_codex(monkeypatch):
    values = dict(codex_dev._PROCESS)
    values.update(CANARY_CODEX_DEV_ENABLED="1", CANARY_CODEX_DEV_MODELS=None)
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(values))


@pytest.mark.parametrize("reasoner", ("gpt-6-sol", "gpt-6-luna", "gpt-5.6-terra"))
def test_explicit_codex_models_route_without_shadowing_api(client, tmp_path, monkeypatch, reasoner):
    enable_codex(monkeypatch)
    selection = f"codex-dev/text/{reasoner}"
    response = client.patch("/api/account/model-settings", json={"selections": {"adapt": selection}})
    assert response.status_code == 200
    payload = response.json()
    assert payload["codex_enabled"] is True
    assert payload["funding"] == "mixed"
    assert payload["warnings"] == []
    assert "funding_groups" not in payload
    assert codex_dev.route_for("text", selection).reasoning_model == reasoner
    assert codex_dev.route_for("text", "gpt-5.6-terra") is None
    assert account_config(Config(), tmp_path, "alice").adapt_model == selection
    assert account_config(Config(), tmp_path, "bob").adapt_model == "gpt-5.6-terra"


def test_disabled_codex_choices_remain_visible_but_cannot_execute(client, tmp_path, monkeypatch):
    enable_codex(monkeypatch)
    selected = "codex-dev/text/gpt-5.5"
    assert client.patch("/api/account/model-settings", json={"selections": {"adapt": selected}}).status_code == 200
    values = dict(codex_dev._PROCESS)
    values["CANARY_CODEX_DEV_ENABLED"] = "0"
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType(values))
    monkeypatch.setenv("CANARY_CODEX_DEV_ENABLED", "1")
    result = client.get("/api/account/model-settings").json()
    assert not result["codex_enabled"]
    assert result["selections"]["adapt"] == selected
    assert not next(model for model in result["models"] if model["id"] == selected)["available"]
    assert client.patch("/api/account/model-settings", json={"selections": {"plan": selected}}).status_code == 400
    with pytest.raises(codex_dev.CodexRoutingError, match="ENABLED"):
        account_config(Config(), tmp_path, "alice")
    assert client.patch("/api/account/model-settings", json={"selections": {"adapt": "gpt-5.6-terra"}}).status_code == 200


@pytest.mark.parametrize("reasoner", ("gpt-6-sol", "gpt-6-luna", "gpt-5.6-luna"))
def test_codex_image_reasoner_and_text_only_constraints(client, monkeypatch, reasoner):
    enable_codex(monkeypatch)
    image = f"codex-dev/image/{reasoner}"
    assert client.patch("/api/account/model-settings", json={"selections": {"image": image, "draw": image}}).status_code == 200
    route = codex_dev.route_for("complete_page", image)
    assert (route.reasoning_model, route.image_model) == (reasoner, "gpt-image-2")
    for stage, model in (("draw", "codex-dev/text/gpt-5.5"), ("ocr", "codex-dev/text/gpt-5.3-codex-spark"), ("image", "codex-dev/image/gpt-5.3-codex-spark")):
        assert client.patch("/api/account/model-settings", json={"selections": {stage: model}}).status_code == 400


def test_model_allowlist_cannot_be_extended_by_project_environment(client, monkeypatch):
    enable_codex(monkeypatch)
    monkeypatch.setenv("CANARY_CODEX_DEV_MODELS", '["gpt-invented"]')
    assert client.patch("/api/account/model-settings", json={"selections": {"adapt": "codex-dev/text/gpt-invented"}}).status_code == 400


def test_explicit_codex_choices_allow_mixed_jobs(client, tmp_path, monkeypatch):
    from novel_to_comic.server.codex_admission import admit_stage_action
    enable_codex(monkeypatch)
    selected = "codex-dev/text/gpt-5.6-luna"
    update_selections(tmp_path, "alice", {"adapt": selected})
    assert admit_stage_action(account_config(Config(), tmp_path, "alice"), "adapt") == "api"
    update_selections(tmp_path, "alice", {"plan": selected})
    assert admit_stage_action(account_config(Config(), tmp_path, "alice"), "adapt") == "codex_subscription"


def test_project_choices_persist_and_only_override_selected_stages(client, tmp_path):
    from novel_to_comic.server.account_models import creation_config
    project = tmp_path / 'alice' / 'project'
    project.mkdir(parents=True)
    config = creation_config({'dev_model_selections': {'adapt': 'gpt-5.6-luna'}}, tmp_path, 'alice')
    save_config(config, project)
    loaded, _ = load_config(project)
    update_selections(tmp_path, 'alice', {'adapt': 'deepseek-v4.1-flash', 'plan': 'gpt-5.6-luna'})
    resolved = account_config(loaded, tmp_path, 'alice')
    assert resolved.adapt_model == 'gpt-5.6-luna'
    assert resolved.plan_model == 'gpt-5.6-luna'
    assert loaded.dev_model_selections == {'adapt': 'gpt-5.6-luna'}
    assert account_config(Config(), tmp_path, 'alice').adapt_model == 'deepseek-v4.1-flash'
    assert account_config(Config(), tmp_path, 'bob').adapt_model == 'gpt-5.6-terra'


@pytest.mark.parametrize('gate', [{'CANARY_ENV': 'production'}, {'FLY_APP_NAME': 'hosted'}])
def test_project_choices_are_rejected_and_inert_outside_dev(client, tmp_path, monkeypatch, gate):
    from novel_to_comic.server.account_models import creation_config
    values = {**codex_dev._PROCESS, **gate}
    monkeypatch.setattr(codex_dev, '_PROCESS', MappingProxyType(values))
    monkeypatch.setenv('CANARY_ENV', 'development')
    for selections in ({}, {'adapt': 'gpt-5.6-luna'}):
        with pytest.raises(ValueError, match='local development'):
            creation_config({'dev_model_selections': selections}, tmp_path, 'alice')
    resolved = account_config(Config(dev_model_selections={'adapt': 'codex-dev/text/gpt-5.5'}), tmp_path, 'alice')
    assert resolved.adapt_model == 'gpt-5.6-terra'


@pytest.mark.parametrize('selections', [None, [], {'invalid': 'gpt-5.6-luna'}, {'draw': 'gpt-5.6-luna'}, {'adapt': 'codex-dev/text/gpt-5.5'}])
def test_creation_validates_project_choices_and_routes(client, tmp_path, selections):
    from novel_to_comic.server.account_models import creation_config
    with pytest.raises((ValueError, codex_dev.CodexRoutingError)):
        creation_config({'dev_model_selections': selections}, tmp_path, 'alice')


def test_project_codex_overrides_allow_mixed_jobs(client, tmp_path, monkeypatch):
    from novel_to_comic.server.account_models import creation_config
    from novel_to_comic.server.codex_admission import admit_stage_action
    enable_codex(monkeypatch)
    model = 'codex-dev/text/gpt-5.5'
    config = creation_config({'dev_model_selections': {'adapt': model}}, tmp_path, 'alice')
    assert admit_stage_action(config, 'adapt') == 'api'
    config = creation_config({'dev_model_selections': {'adapt': model, 'plan': model}}, tmp_path, 'alice')
    assert admit_stage_action(config, 'adapt') == 'codex_subscription'


@pytest.mark.parametrize('method', ['upload', 'import'])
@pytest.mark.parametrize('development', [True, False])
def test_creation_endpoints_persist_dev_choices_or_reject(client, tmp_path, monkeypatch, method, development):
    import asyncio
    import io
    from unittest.mock import MagicMock
    from fastapi import HTTPException, UploadFile
    from novel_to_comic.server.routers import projects
    from unittest.mock import AsyncMock
    from starlette.requests import Request
    from novel_to_comic.server.ratelimit import limiter
    app = FastAPI()
    app.state.limiter = limiter
    request = Request({'type': 'http', 'method': 'POST', 'path': '/', 'headers': [], 'query_string': b'', 'client': ('127.0.0.1', 0), 'app': app})
    if not development:
        monkeypatch.setattr(codex_dev, '_PROCESS', MappingProxyType({**codex_dev._PROCESS, 'CANARY_ENV': 'production'}))
    db = MagicMock()
    db.table.return_value.insert.return_value.execute.return_value.data = [{'id': 'project-id'}]
    monkeypatch.setattr(projects, 'get_db', lambda: db)
    monkeypatch.setattr(projects, '_count_user_projects', lambda user: 0)
    response = MagicMock()
    response.content = b'Once upon a time, a traveler arrived.'
    response.text = response.content.decode()
    async def content():
        yield response.content
    response.aiter_bytes = content
    stream = MagicMock()
    stream.__aenter__ = AsyncMock(return_value=response)
    stream.__aexit__ = AsyncMock(return_value=False)
    http = MagicMock()
    http.stream.return_value = stream
    http_class = MagicMock()
    http_class.return_value.__aenter__ = AsyncMock(return_value=http)
    http_class.return_value.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(projects.httpx, 'AsyncClient', http_class)
    selections = {'adapt': 'gpt-5.6-luna'}
    overrides = json.dumps({'dev_model_selections': selections})
    if method == 'upload':
        call = projects.create_project(request=request, file=UploadFile(file=io.BytesIO(response.content), filename='novel.txt'), name='Novel', config_overrides=overrides, projects_dir=tmp_path, user_id='alice')
    else:
        call = projects.import_short_story(request=request, payload=projects.ImportStoryRequest(name='Novel', url_or_code='story', config_overrides=overrides), projects_dir=tmp_path, user_id='alice')
    if not development:
        with pytest.raises(HTTPException) as error:
            asyncio.run(call)
        assert error.value.status_code == 400
        assert not (tmp_path / 'alice' / 'novel').exists()
        return
    assert asyncio.run(call)['id'] == 'project-id'
    loaded, _ = load_config(tmp_path / 'alice' / 'novel')
    assert loaded.dev_model_selections == selections
    assert account_config(loaded, tmp_path, 'alice').adapt_model == 'gpt-5.6-luna'


@pytest.mark.parametrize("model,expected_cost", [
    ("gpt-6-astra", 0.06),
    ("claude-fable-5-1", 0.06),
    ("claude-opus-5", 0.03),
])
def test_premium_models_select_independently_with_known_pricing(client, tmp_path, model, expected_cost):
    from novel_to_comic.model_costs import PricingResolver
    from novel_to_comic.server.codex_admission import admit_stage_action

    response = client.patch("/api/account/model-settings", json={"selections": {"adapt": model}})
    assert response.status_code == 200
    config = account_config(Config(), tmp_path, "alice")
    assert config.adapt_model == model
    assert config.plan_model == "gpt-5.6-terra"
    assert admit_stage_action(config, "adapt") == "api"
    cost = PricingResolver().calculate(model_alias=model, operation="text", input_tokens=1000, output_tokens=1000)
    assert cost.cost_usd == pytest.approx(expected_cost)


def test_linked_subscription_stages_can_select_different_models(client, tmp_path, monkeypatch):
    from novel_to_comic.server.codex_admission import admit_stage_action

    enable_codex(monkeypatch)
    update_selections(tmp_path, "alice", {
        "adapt": "codex-dev/text/gpt-6-astra",
        "plan": "codex-dev/text/gpt-5.6-luna",
    })
    assert admit_stage_action(account_config(Config(), tmp_path, "alice"), "adapt") == "codex_subscription"


@pytest.fixture
def project_settings(client, tmp_path):
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.config import router as config_router

    project = tmp_path / "alice" / "novel"
    project.mkdir(parents=True)
    save_config(Config(dev_model_selections={"plan": "gpt-5.6-luna"}), project)
    client.app.include_router(config_router, prefix="/api/projects/{project_id}/config")
    client.app.dependency_overrides[get_project] = lambda: (
        project, account_config(load_config(project)[0], tmp_path, "alice"), None,
    )
    return project


def test_existing_project_models_update_and_reset_to_account(client, tmp_path, project_settings):
    update_selections(tmp_path, "alice", {"adapt": "deepseek-v4.1-flash"})
    snapshot = account_config(load_config(project_settings)[0], tmp_path, "alice")
    response = client.patch("/api/projects/novel/config/", json={
        "dev_model_selections": {"adapt": "claude-opus-5", "plan": "gpt-5.6-luna"},
    })
    assert response.status_code == 200
    assert response.json()["adapt_model"] == "claude-opus-5"
    assert load_config(project_settings)[0].dev_model_selections == {"adapt": "claude-opus-5", "plan": "gpt-5.6-luna"}
    assert snapshot.adapt_model == "deepseek-v4.1-flash"
    assert read_selections(tmp_path, "alice")["adapt"] == "deepseek-v4.1-flash"
    response = client.patch("/api/projects/novel/config/", json={"dev_model_selections": {}})
    assert response.status_code == 200
    assert response.json()["adapt_model"] == "deepseek-v4.1-flash"
    assert response.json()["plan_model"] == "gpt-5.6-terra"
    assert load_config(project_settings)[0].dev_model_selections == {}


@pytest.mark.parametrize("selections", [None, [], {"adapt": "unknown"}, {"draw": "gpt-6-astra"}])
def test_project_model_validation_is_atomic(client, project_settings, selections):
    before = (project_settings / "config.yaml").read_bytes()
    response = client.patch("/api/projects/novel/config/", json={"dev_model_selections": selections, "target_language": "fr"})
    assert response.status_code == 400
    assert (project_settings / "config.yaml").read_bytes() == before


def test_project_model_changes_require_dev_gate(client, project_settings, monkeypatch):
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({**codex_dev._PROCESS, "CANARY_ENV": "production"}))
    before = (project_settings / "config.yaml").read_bytes()
    response = client.patch("/api/projects/novel/config/", json={"dev_model_selections": {}})
    assert response.status_code == 403
    assert (project_settings / "config.yaml").read_bytes() == before


def test_existing_edition_allows_text_changes_but_not_draw_model_changes(client, project_settings):
    from novel_to_comic.target_artifacts import TargetArtifacts
    from novel_to_comic.models.draw import BookEdition
    from novel_to_comic.page_drawing import production_page_capability_profile

    TargetArtifacts(project_settings).write_book_edition(BookEdition(
        revision=1, id="edition-001", capability_profile=production_page_capability_profile(),
    ))
    response = client.patch("/api/projects/novel/config/", json={"dev_model_selections": {"adapt": "gpt-6-astra"}})
    assert response.status_code == 200
    before = (project_settings / "config.yaml").read_bytes()
    response = client.patch("/api/projects/novel/config/", json={"dev_model_selections": {"draw": "image-flare", "adapt": "claude-opus-5"}})
    assert response.status_code == 409
    assert "new edition" in response.json()["detail"]
    assert (project_settings / "config.yaml").read_bytes() == before
