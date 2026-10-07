"""Labs stage-model comparison: isolated workspaces, pinned models, honest accounting."""
import asyncio
import json
import os
from datetime import UTC, datetime

import pytest

from novel_to_comic.ai.context import ai_request_context, current_ai_request_context
from novel_to_comic.labs import stage_models, storage
from novel_to_comic.stages import REGISTRY, Stage
from novel_to_comic.state import STAGE_NAMES, PipelineState, StageState, StageStatus, load_state, save_state
from novel_to_comic.usage import UsageRecord

OPUS, SONNET = stage_models.DEFAULT_MODELS


@pytest.fixture
def root(tmp_path):
    """A user root holding one project approved through Cast and already planned."""
    user_root = tmp_path / "user"
    project = user_root / "story"
    for directory in ("input", "brief", "samples", "adapt", "plan", "draw", "requests", ".jobs"):
        (project / directory).mkdir(parents=True)
    (project / "config.yaml").write_text('litellm_base_url: "http://gateway"\n')
    (project / "input" / "story.txt").write_text("It was a dark and stormy night.")
    (project / "brief" / "adaptation_brief.json").write_text(json.dumps({"themes": ["storm"]}))
    (project / "samples" / "style_1.png").write_bytes(b"png")
    (project / "adapt" / "book.json").write_text("{}")
    (project / "plan" / "book.json").write_text("{}")
    state = PipelineState(
        project_name="Story", novel_path=str(project / "input" / "story.txt"), created_at=datetime.now(UTC),
        stages={name: StageState(status=StageStatus.COMPLETE) for name in STAGE_NAMES},
    )
    state.stages["plan"].usage_log = [
        {"model": OPUS, "input_tokens": 1_000_000, "output_tokens": 100_000, "cost_usd": 6.0},
    ]
    state.stages["adapt"].usage_log = [{"model": OPUS, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0}]
    save_state(state, project)
    return user_root


def test_extract_brief_workspace_holds_only_the_novel_and_config(root, tmp_path):
    workspace = tmp_path / "ws"
    stage_models.prepare_workspace(root / "story", workspace, "extract_brief")

    assert sorted(path.name for path in workspace.iterdir()) == ["config.yaml", "input", "state.json"]
    state = load_state(workspace)
    assert all(stage.status is StageStatus.PENDING and not stage.usage_log for stage in state.stages.values())
    assert state.novel_path == str(workspace / "input" / "story.txt")


def test_adapt_plan_workspace_keeps_approved_inputs_and_clears_the_rest(root, tmp_path):
    source = root / "story"
    workspace = tmp_path / "ws"
    stage_models.prepare_workspace(source, workspace, "adapt_plan")

    names = {path.name for path in workspace.iterdir()}
    assert {"brief", "samples", "input", "config.yaml"} <= names
    assert not names & {"adapt", "plan", "draw", "requests", ".jobs"}
    assert os.stat(workspace / "samples" / "style_1.png").st_ino == os.stat(source / "samples" / "style_1.png").st_ino
    state = load_state(workspace)
    assert state.stages["cast"].status is StageStatus.COMPLETE
    assert all(state.stages[name].status is StageStatus.PENDING for name in ("adapt", "plan", "draw", "finish"))
    assert (source / "adapt" / "book.json").exists(), "the source project is only read"


def _fake_stages(monkeypatch, *, fail: str | None = None):
    seen: list[dict] = []

    def fake(name):
        async def run(config, project_dir, ctx):
            model = getattr(config, stage_models.STAGE_MODEL_FIELDS[name])
            seen.append({"stage": name, "model": model, "user": current_ai_request_context().user_id,
                         "dir": project_dir, "reasoning": dict(config.text_reasoning_efforts)})
            if name == fail:
                raise RuntimeError(f"{name} broke")
            state = ctx.state
            state.stages[name].status = StageStatus.COMPLETE
            state.stages[name].usage_log.append(UsageRecord(
                provider="anthropic", model=model, operation="text", input_tokens=1000, output_tokens=200,
            ).model_dump())
            state.stages[name].cost_usd += 0.01
            save_state(state, project_dir)
        return Stage(name=name, run=run, outputs=lambda _: [], clean_paths=lambda _: [])

    for name in stage_models.STAGE_MODEL_FIELDS:
        monkeypatch.setitem(REGISTRY, name, fake(name))
    return seen


def test_each_arm_runs_its_phase_with_its_own_model_and_no_user(root, monkeypatch):
    seen = _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})

    async def as_a_signed_in_request():
        with ai_request_context(user_id="user-1"):
            await stage_models.run(root, run["run_id"], "story", ["adapt_plan"], [OPUS, SONNET])

    asyncio.run(as_a_signed_in_request())

    cells = {cell["model"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}
    assert {(call["stage"], call["model"]) for call in seen} == {
        ("adapt", OPUS), ("plan", OPUS), ("adapt", SONNET), ("plan", SONNET),
    }
    assert all(call["user"] is None for call in seen)
    assert len({call["dir"] for call in seen}) == 2, "arms never share a workspace"
    for model, cell in cells.items():
        assert cell["status"] == "ok" and [stage["stage"] for stage in cell["stages"]] == ["adapt", "plan"]
        assert cell["stages"][0]["calls"] == 1 and cell["stages"][0]["output_tokens"] == 200
        assert cell["cost_usd"] == pytest.approx(0.02)
        assert cell["stages"][0]["models"] == [model]


def test_a_failed_stage_stops_its_arm(root, monkeypatch):
    seen = _fake_stages(monkeypatch, fail="adapt")
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})

    asyncio.run(stage_models.run_arm(root, run["run_id"], "story", "adapt_plan", SONNET))

    (cell,) = storage.read_run(root, run["run_id"])["cells"]
    assert [call["stage"] for call in seen] == ["adapt"]
    assert cell["status"] == "failed" and cell["stages"][0]["error"] == "adapt broke"


def _failed_extract_arm(root, monkeypatch, **kwargs):
    _fake_stages(monkeypatch, fail="extract")
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={"project": "story"})
    asyncio.run(stage_models.run_arm(root, run["run_id"], "story", "extract_brief", SONNET, **kwargs))
    return run["run_id"]


def _retry(root, run_id, cell_ids=None):
    cells = stage_models.failed_cells(root, run_id, cell_ids)
    asyncio.run(stage_models.retry(root, run_id, cells))
    (cell,) = storage.read_run(root, run_id)["cells"]
    return cell


def test_retrying_a_failed_arm_reruns_its_phase_and_keeps_the_failed_attempt(root, monkeypatch):
    run_id = _failed_extract_arm(root, monkeypatch, reasoning_efforts={"extract": "high"}, variant="repeat")
    (failed,) = storage.read_run(root, run_id)["cells"]
    seen = _fake_stages(monkeypatch)

    cell = _retry(root, run_id)

    assert [(call["stage"], call["model"], call["reasoning"]["extract"]) for call in seen] == [
        ("extract", SONNET, "high"), ("brief", SONNET, "high")]
    assert cell["status"] == "ok" and cell["variant"] == "repeat"
    assert cell["input_sha256"] == failed["input_sha256"]
    (attempt,) = cell["attempts"]
    assert attempt["error"] == "extract broke" and attempt["stages"] == failed["stages"]
    assert attempt["cost_usd"] == failed["cost_usd"]
    kept = storage.run_file(root, run_id, attempt["workspace"])
    assert kept.is_dir() and (kept / "input" / "story.txt").exists()
    assert storage.read_run(root, run_id)["total_cost_usd"] == pytest.approx(cell["cost_usd"] + failed["cost_usd"])


def test_a_retry_refuses_to_run_when_the_source_inputs_changed(root, monkeypatch):
    run_id = _failed_extract_arm(root, monkeypatch)
    (root / "story" / "input" / "story.txt").write_text("A different novel.")
    seen = _fake_stages(monkeypatch)

    cell = _retry(root, run_id)

    assert not seen
    assert cell["status"] == "failed" and "changed since the run" in cell["error"]
    assert len(cell["attempts"]) == 1


def test_arms_recorded_before_fingerprints_retry_against_their_kept_novel_and_config(root, monkeypatch):
    run_id = _failed_extract_arm(root, monkeypatch)
    (failed,) = storage.read_run(root, run_id)["cells"]
    storage.write_cell(root, run_id, failed["cell_id"], {k: v for k, v in failed.items() if k != "input_sha256"})
    seen = _fake_stages(monkeypatch)

    assert _retry(root, run_id)["status"] == "ok" and seen


def test_only_failed_arms_can_be_retried(root, monkeypatch):
    _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={"project": "story"})
    asyncio.run(stage_models.run_arm(root, run["run_id"], "story", "extract_brief", SONNET))
    (cell,) = storage.read_run(root, run["run_id"])["cells"]
    assert stage_models.failed_cells(root, run["run_id"], None) == []
    with pytest.raises(ValueError, match="Only failed"):
        stage_models.failed_cells(root, run["run_id"], [cell["cell_id"]])


@pytest.mark.parametrize("phases,models,message", [
    (["adapt_plan"], [OPUS], "two and six"),
    (["adapt_plan"], [OPUS, OPUS], "two and six"),
    (["adapt_plan"], [OPUS, "codex-dev/text/gpt-6-luna"], "Unknown text model"),
    (["draw"], [OPUS, SONNET], "Choose phases"),
])
def test_invalid_specs_are_rejected_before_spend(root, phases, models, message):
    with pytest.raises(ValueError, match=message):
        stage_models.validate_spec(root / "story", phases, models)


def test_adapt_plan_needs_an_approved_cast(root):
    state = load_state(root / "story")
    state.stages["cast"] = StageState()
    save_state(state, root / "story")

    with pytest.raises(ValueError, match="cast"):
        stage_models.validate_spec(root / "story", ["adapt_plan"], [OPUS, SONNET])


def test_estimate_prices_the_source_projects_recorded_tokens_per_model(root):
    estimates = stage_models.estimate_usd(root / "story", ["adapt_plan"], [OPUS, SONNET])

    # 1M input and 100k output at each model's list price.
    assert estimates == {OPUS: pytest.approx(6.0), SONNET: pytest.approx(3.0)}
    assert stage_models.estimate_usd(root / "story", ["extract_brief"], [OPUS, SONNET]) == {OPUS: None, SONNET: None}


SUBSCRIPTION = "claude-dev/text/claude-sonnet-5-5"


def _catalog(monkeypatch, *, available: bool):
    real = stage_models.selectable_models()
    monkeypatch.setattr(stage_models, "selectable_models", lambda: [*real, {
        "id": SUBSCRIPTION, "label": "Claude Code · claude-sonnet-5-5", "provider": "Claude subscription",
        "funding": "claude_subscription", "available": available,
    }])


def test_subscription_models_compare_against_api_models_without_usd(root, monkeypatch):
    _catalog(monkeypatch, available=True)
    stage_models.validate_spec(root / "story", ["adapt_plan"], [OPUS, SUBSCRIPTION])

    estimates = stage_models.estimate_usd(root / "story", ["adapt_plan"], [OPUS, SUBSCRIPTION])

    assert estimates == {OPUS: pytest.approx(6.0), SUBSCRIPTION: 0.0}


def test_a_subscription_model_this_server_has_not_enabled_is_rejected(root, monkeypatch):
    _catalog(monkeypatch, available=False)

    with pytest.raises(ValueError, match="Not enabled"):
        stage_models.validate_spec(root / "story", ["adapt_plan"], [OPUS, SUBSCRIPTION])


def test_arms_record_their_funding(root, monkeypatch):
    _catalog(monkeypatch, available=True)
    _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})

    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan"], [OPUS, SUBSCRIPTION]))

    funding = {cell["model"]: cell["funding"] for cell in storage.read_run(root, run["run_id"])["cells"]}
    assert funding == {OPUS: "api", SUBSCRIPTION: "claude_subscription"}


def test_api_equivalent_prices_recorded_subscription_tokens_at_api_rates():
    from novel_to_comic.labs.stage_models import api_equivalent_usd

    claude = {"model": "claude-dev/text/claude-sonnet-5-5", "provider_model": "claude-sonnet-5-5",
              "input_tokens": 1_000_000, "cached_text_tokens": 900_000, "output_tokens": 100_000}
    gpt = {"model": "codex-dev/text/gpt-6-sol", "provider_model": "gpt-6-sol",
           "input_tokens": 1_000_000, "cached_text_tokens": 900_000, "output_tokens": 100_000}

    # Canary sends Claude no cache_control: all input at $2/M, output at $10/M.
    assert api_equivalent_usd([claude]) == 2.0 + 1.0
    # This request exceeds 272k: 100k at $4/M, 900k at $0.40/M, output at $15/M.
    assert api_equivalent_usd([gpt]) == 0.4 + 0.36 + 1.5
    assert api_equivalent_usd([{**gpt, "provider_model": "unpriced-model"}]) is None


def test_codex_arms_do_not_time_each_others_runtime_queue(root, monkeypatch):
    async def scenario():
        active = 0
        peak = 0
        calls = []

        async def arm(user_root, run_id, source, phase, model):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            calls.append((phase, model))
            active -= 1

        monkeypatch.setattr(stage_models, "_funding", lambda model: "codex_subscription")
        monkeypatch.setattr(stage_models, "run_arm", arm)
        await stage_models.run(root, "unused", "story", list(stage_models.PHASES), ["sol", "luna"])
        assert peak == 1
        assert len(calls) == 4

    asyncio.run(scenario())


@pytest.mark.parametrize("provider_model", [None, "gpt-6.1-sol", "openai/gpt-6.1-sol"])
@pytest.mark.parametrize("input_tokens,expected", [(200_000, 0.4), (300_000, 1.105)])
def test_sol_61_api_equivalent_uses_its_own_cache_and_long_context_rates(provider_model, input_tokens, expected):
    entry = {"model": "codex-dev/text/gpt-6.1-sol", "provider_model": provider_model,
             "input_tokens": input_tokens, "cached_text_tokens": 100_000, "output_tokens": 19_000}
    assert stage_models.api_equivalent_usd([entry]) == pytest.approx(expected)


def test_labs_snapshots_reasoning_for_each_model_and_stage(root, monkeypatch):
    seen = _fake_stages(monkeypatch)
    selected = stage_models.resolve_reasoning(["adapt_plan"], [OPUS, "mimo-v2.6-pro"], {
        OPUS: {"adapt": "high", "plan": "low"}, "mimo-v2.6-pro": {"adapt": "enabled"},
    })
    run = storage.create_run(root, kind=stage_models.KIND, label="reasoning", spec={"reasoning_efforts": selected})
    before = (root / "story/config.yaml").read_text()
    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan"], [OPUS, "mimo-v2.6-pro"], selected))
    cells = storage.read_run(root, run["run_id"])["cells"]
    assert all(cell["status"] == "ok" and cell["reasoning_efforts"] == selected[cell["model"]] for cell in cells)
    assert all(call["reasoning"] == selected[call["model"]] for call in seen)
    assert selected["mimo-v2.6-pro"]["plan"] == "none"
    assert (root / "story/config.yaml").read_text() == before


@pytest.mark.parametrize("choices", [
    {OPUS: {"draw": "high"}}, {OPUS: {"adapt": "enabled"}},
    {"mimo-v2.6-pro": {"adapt": "medium"}}, {"other": {"adapt": "high"}},
    [], {OPUS: []},
])
def test_labs_rejects_invalid_reasoning_before_execution(choices):
    with pytest.raises(ValueError):
        stage_models.resolve_reasoning(["adapt_plan"], [OPUS, "mimo-v2.6-pro"], choices)


def test_text_comparison_accepts_six_models_and_rejects_seven(root):
    models = [entry["id"] for entry in stage_models.selectable_models() if entry["funding"] == "api"]
    stage_models.validate_spec(root / "story", ["adapt_plan"], models[:6])
    with pytest.raises(ValueError, match="two and six"):
        stage_models.validate_spec(root / "story", ["adapt_plan"], models[:7])


@pytest.mark.parametrize("model", ["claude-haiku-5-5", "bedrock-claude-haiku-5-5"])
@pytest.mark.parametrize("input_tokens,input_rate,output_rate", [
    (100_000, 1e-7, 5e-7), (100_001, 5e-7, 2.5e-6), (300_000, 5e-7, 2.5e-6),
])
def test_haiku_catalog_and_prompt_pricing(model, input_tokens, input_rate, output_rate):
    from novel_to_comic.model_costs import PricingResolver

    choices = {entry["id"]: entry for entry in stage_models.selectable_models()}
    assert choices[model]["default_reasoning"] == "medium"
    assert choices[model]["reasoning_options"] == ["low", "medium", "high"]
    expected = input_tokens * input_rate + 1000 * output_rate
    cost = PricingResolver().estimate_text_cost(model, input_tokens, 1000)
    assert cost.cost_usd == pytest.approx(expected)
    assert stage_models.api_equivalent_usd([{
        "provider_model": "claude-haiku-5-5", "input_tokens": input_tokens,
        "output_tokens": 1000,
    }]) == pytest.approx(expected, abs=1e-6)


def test_haiku_gateway_routes_match_catalog():
    from pathlib import Path

    import yaml

    from novel_to_comic import codex_dev
    from novel_to_comic.text_models import text_wire

    config = yaml.safe_load((Path(__file__).resolve().parents[2] / "litellm/config.yaml").read_text())
    routes = {entry["model_name"]: entry for entry in config["model_list"]}
    for alias, provider_model in [
        ("claude-haiku-5-5", "anthropic/claude-haiku-5-5"),
        ("bedrock-claude-haiku-5-5", "bedrock/converse/global.anthropic.claude-haiku-5-5"),
    ]:
        route = routes[alias]
        assert route["litellm_params"]["model"] == provider_model
        assert route["litellm_params"]["thinking"] == {"type": "adaptive", "display": "summarized"}
        assert route["model_info"]["supports_native_structured_output"] is True
        assert route["model_info"]["max_output_tokens"] == text_wire(alias).max_output_tokens
        assert route["model_info"]["input_cost_per_token_above_100k_tokens"] == 5e-7
    assert "claude-haiku-5-5" in codex_dev._DEFAULT_CLAUDE_MODELS
