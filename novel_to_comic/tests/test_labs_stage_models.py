"""Labs stage-model comparison: isolated workspaces, pinned models, honest accounting."""
import asyncio
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from novel_to_comic.ai.context import ai_request_context, current_ai_request_context
from novel_to_comic.labs import stage_models, storage
from novel_to_comic.stages import REGISTRY, Stage
from novel_to_comic.state import STAGE_NAMES, PipelineState, StageState, StageStatus, load_state, save_state
from novel_to_comic.usage import UsageRecord

OPUS, SONNET = stage_models.DEFAULT_MODELS


def _arms(models, reasoning=None):
    return [{"id": f"arm-{index + 1}", "model": model,
             "reasoning_efforts": (reasoning or {}).get(model, {})}
            for index, model in enumerate(models)]


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


def test_full_workspace_keeps_approved_style_and_cast_and_reruns_every_text_stage(root, tmp_path):
    source = root / "story"
    (source / "refs").mkdir()
    (source / "refs" / "cast_design.json").write_text("{}")
    (source / "lettering").mkdir()
    (source / "lettering" / "style.json").write_text("{}")
    (source / "lettering" / "page_001.json").write_text("{}")
    workspace = tmp_path / "ws"
    stage_models.prepare_workspace(source, workspace, "full")

    names = {path.name for path in workspace.iterdir()}
    assert {"samples", "refs", "input", "config.yaml"} <= names
    assert not names & {"brief", "adapt", "plan", "draw", "requests", ".jobs"}
    assert sorted(path.name for path in (workspace / "lettering").iterdir()) == ["style.json"]
    state = load_state(workspace)
    assert state.stages["style"].status is state.stages["cast"].status is StageStatus.COMPLETE
    assert all(state.stages[name].status is StageStatus.PENDING
               for name in ("extract", "brief", "adapt", "plan", "draw", "finish"))
    assert (source / "brief" / "adaptation_brief.json").exists(), "the source project is only read"


def test_full_phase_runs_each_stage_on_the_arms_model_in_order(root, monkeypatch):
    seen = _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})
    arms = stage_models.resolve_arms(["adapt_plan", "full"], [
        {"id": "mix", "model": OPUS, "stage_models": {"adapt": SONNET}},
        {"id": "pure", "model": SONNET},
    ])
    stage_models.validate_spec(root / "story", ["adapt_plan", "full"], stage_models.arm_models(arms))

    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan", "full"], arms))

    cells = {cell["cell_id"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}
    full = cells[f"{stage_models.arm_id('full', OPUS)}.mix"]
    assert [stage["stage"] for stage in full["stages"]] == ["extract", "brief", "adapt", "plan"]
    assert full["stage_models"] == {"extract": OPUS, "brief": OPUS, "adapt": SONNET, "plan": OPUS}
    mix_dirs = {call["dir"] for call in seen if call["stage"] == "extract"}
    assert len(mix_dirs) == 2, "each arm's full phase has its own workspace"
    assert [call["model"] for call in seen if call["dir"] == next(
        c["dir"] for c in seen if c["stage"] == "extract" and c["model"] == OPUS)] == [OPUS, OPUS, SONNET, OPUS]
    # A stage run in two phases is priced in both; extract/brief has no source usage here.
    assert stage_models.estimate_arms_usd(root / "story", ["adapt_plan"], arms)["mix"] == pytest.approx(6.0)
    assert stage_models.estimate_arms_usd(root / "story", ["adapt_plan", "full"], arms)["mix"] is None


def test_full_phase_approves_the_arms_draft_brief_before_adapt(root, monkeypatch):
    from novel_to_comic.models.adaptation import AdaptationBrief
    from novel_to_comic.target_artifacts import TargetArtifacts

    seen = _fake_stages(monkeypatch)
    brief_stage = REGISTRY["brief"]

    async def drafted(config, project_dir, ctx):
        await brief_stage.run(config, project_dir, ctx)
        TargetArtifacts(project_dir).write_brief(AdaptationBrief(
            status="draft", revision=1, story_promises=("A storm",), themes=("storm",),
            point_of_view="close third", narrator_treatment="captions", tone="dark",
            essential_events=("The storm",), character_turns=("They shelter",), desired_emphasis=("rain",),
            motifs=("rain",), transformation_level="faithful", target_page_min=2, target_page_max=4,
        ))
        ctx.state.stages["brief"].status = StageStatus.AWAITING_REVIEW
        save_state(ctx.state, project_dir)

    async def adapt(config, project_dir, ctx):
        assert TargetArtifacts(project_dir).read_brief().status == "approved"
        assert ctx.state.stages["brief"].status is StageStatus.COMPLETE
        seen.append({"stage": "adapt"})
        ctx.state.stages["adapt"].status = StageStatus.COMPLETE
        save_state(ctx.state, project_dir)

    monkeypatch.setitem(REGISTRY, "brief", Stage(name="brief", run=drafted, outputs=lambda _: [], clean_paths=lambda _: []))
    monkeypatch.setitem(REGISTRY, "adapt", Stage(name="adapt", run=adapt, outputs=lambda _: [], clean_paths=lambda _: []))
    monkeypatch.setattr(stage_models, "summarize_outputs", lambda workspace, stage: {})
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})

    asyncio.run(stage_models.run_arm(root, run["run_id"], "story", "full", OPUS))

    (cell,) = storage.read_run(root, run["run_id"])["cells"]
    assert cell["status"] == "ok", cell
    assert [stage.get("auto_approved", False) for stage in cell["stages"]] == [False, True, False, False]
    assert (root / "story" / "brief" / "adaptation_brief.json").read_text() == json.dumps({"themes": ["storm"]})


def test_full_phase_needs_an_approved_style_and_cast_but_not_a_brief(root):
    state = load_state(root / "story")
    state.stages["brief"] = StageState()
    save_state(state, root / "story")
    stage_models.validate_spec(root / "story", ["full"], [OPUS, SONNET])
    state.stages["style"] = StageState()
    save_state(state, root / "story")
    with pytest.raises(ValueError, match="style"):
        stage_models.validate_spec(root / "story", ["full"], [OPUS, SONNET])


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
            await stage_models.run(root, run["run_id"], "story", ["adapt_plan"], _arms([OPUS, SONNET]))

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


def test_a_mixed_arm_runs_each_stage_on_its_own_model(root, monkeypatch):
    _catalog(monkeypatch, available=True)
    seen = _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})
    arms = stage_models.resolve_arms(["adapt_plan"], [
        {"id": "pure", "model": OPUS},
        {"id": "mixed", "model": OPUS, "stage_models": {"plan": SUBSCRIPTION}},
    ])

    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan"], arms))

    cells = {cell["variant"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}
    mixed = cells["mixed"]
    assert mixed["status"] == "ok"
    assert mixed["stage_models"] == {"adapt": OPUS, "plan": SUBSCRIPTION}
    assert [stage["models"] for stage in mixed["stages"]] == [[OPUS], [SUBSCRIPTION]]
    assert mixed["funding"] == "api", "a cell that spends any USD reports as API"
    assert {(call["stage"], call["model"]) for call in seen} == {
        ("adapt", OPUS), ("plan", OPUS), ("plan", SUBSCRIPTION),
    }
    assert stage_models.estimate_arms_usd(root / "story", ["adapt_plan"], arms) == {
        "pure": pytest.approx(6.0), "mixed": 0.0,
    }


def test_mixed_arm_reasoning_is_validated_against_each_stages_model():
    arm = {"id": "mixed", "model": "gemini-4-argon", "stage_models": {"adapt": OPUS},
           "reasoning_efforts": {"plan": "low"}}
    resolved = stage_models.resolve_arms(["adapt_plan"], [arm, {"id": "b", "model": OPUS}])[0]
    assert resolved["stage_models"] == {"adapt": OPUS, "plan": "gemini-4-argon"}
    assert resolved["reasoning_efforts"]["plan"] == "low"

    for bad in ({"stage_models": {"draw": OPUS}}, {"stage_models": {"adapt": ""}},
                {"reasoning_efforts": {"adapt": "low", "plan": "low"}, "stage_models": {"adapt": "mimo-v2.6-pro"}}):
        with pytest.raises(ValueError):
            stage_models.resolve_arms(["adapt_plan"], [{"id": "a", "model": "gemini-4-argon"} | bad,
                                                       {"id": "b", "model": OPUS}])


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


def test_estimate_prices_the_source_projects_recorded_tokens_per_stage_model(root):
    estimate = lambda models: stage_models.estimate_stages_usd(root / "story", models)  # noqa: E731

    # Plan recorded 1M input and 100k output; each stage is priced at its own model's list price.
    assert estimate({"adapt": OPUS, "plan": OPUS}) == pytest.approx(6.0)
    assert estimate({"adapt": OPUS, "plan": SONNET}) == pytest.approx(3.0)
    assert estimate({"extract": OPUS, "brief": OPUS}) is None


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

    arms = stage_models.resolve_arms(["adapt_plan"], _arms([OPUS, SUBSCRIPTION]))
    estimates = stage_models.estimate_arms_usd(root / "story", ["adapt_plan"], arms)

    assert estimates == {"arm-1": pytest.approx(6.0), "arm-2": 0.0}


def test_a_subscription_model_this_server_has_not_enabled_is_rejected(root, monkeypatch):
    _catalog(monkeypatch, available=False)

    with pytest.raises(ValueError, match="Not enabled"):
        stage_models.validate_spec(root / "story", ["adapt_plan"], [OPUS, SUBSCRIPTION])


def test_arms_record_their_funding(root, monkeypatch):
    _catalog(monkeypatch, available=True)
    _fake_stages(monkeypatch)
    run = storage.create_run(root, kind=stage_models.KIND, label="t", spec={})

    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan"], _arms([OPUS, SUBSCRIPTION])))

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

        async def arm(user_root, run_id, source, phase, model, **kwargs):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0)
            calls.append((phase, model))
            active -= 1

        monkeypatch.setattr(stage_models, "_funding", lambda model: "codex_subscription")
        monkeypatch.setattr(stage_models, "run_arm", arm)
        await stage_models.run(root, "unused", "story", ["extract_brief", "adapt_plan"], _arms(["sol", "luna"]))
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
    choices = {OPUS: {"adapt": "high", "plan": "low"}, "mimo-v2.6-pro": {"adapt": "enabled"}}
    selected = {model: stage_models.resolve_stage_reasoning({"adapt": model, "plan": model}, choices[model])
                for model in choices}
    run = storage.create_run(root, kind=stage_models.KIND, label="reasoning", spec={"reasoning_efforts": selected})
    before = (root / "story/config.yaml").read_text()
    asyncio.run(stage_models.run(root, run["run_id"], "story", ["adapt_plan"], _arms([OPUS, "mimo-v2.6-pro"], selected)))
    cells = storage.read_run(root, run["run_id"])["cells"]
    assert all(cell["status"] == "ok" and cell["reasoning_efforts"] == selected[cell["model"]] for cell in cells)
    assert all(call["reasoning"] == selected[call["model"]] for call in seen)
    assert selected["mimo-v2.6-pro"]["plan"] == "none"
    assert (root / "story/config.yaml").read_text() == before


@pytest.mark.parametrize("model,choices", [
    (OPUS, {"draw": "high"}), (OPUS, {"adapt": "enabled"}),
    ("mimo-v2.6-pro", {"adapt": "medium"}), (OPUS, []),
])
def test_labs_rejects_invalid_reasoning_before_execution(model, choices):
    with pytest.raises(ValueError):
        stage_models.resolve_stage_reasoning({"adapt": model, "plan": model}, choices)


def test_text_comparison_accepts_six_arms_and_rejects_seven(root):
    models = [entry["id"] for entry in stage_models.selectable_models() if entry["funding"] == "api"]
    arms = stage_models.resolve_arms(["adapt_plan"], _arms(models[:6]))
    stage_models.validate_spec(root / "story", ["adapt_plan"], stage_models.arm_models(arms))
    for count in (1, 7):
        with pytest.raises(ValueError, match="two and six"):
            stage_models.resolve_arms(["adapt_plan"], _arms(models[:count]))


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


def test_repeated_model_arms_keep_independent_reasoning_workspaces_and_retry(root, monkeypatch):
    phases = ["extract_brief"]
    arms = stage_models.resolve_arms(phases, [
        {"id": "low", "model": SONNET, "reasoning_efforts": {"extract": "low", "brief": "low"}},
        {"id": "high", "model": SONNET, "reasoning_efforts": {"extract": "high", "brief": "high"}},
    ])
    stage_models.validate_spec(root / "story", phases, [arm["model"] for arm in arms])
    run = storage.create_run(root, kind=stage_models.KIND, label="repeats", spec={"project": "story", "arms": arms})
    seen = _fake_stages(monkeypatch, fail="extract")
    asyncio.run(stage_models.run(root, run["run_id"], "story", phases, arms))
    cells = storage.read_run(root, run["run_id"])["cells"]
    assert len(cells) == len({cell["cell_id"] for cell in cells}) == 2
    assert len({cell["workspace"] for cell in cells}) == 2
    assert {call["reasoning"]["extract"] for call in seen} == {"low", "high"}
    assert {cell["variant"] for cell in cells} == {"low", "high"}
    low = next(cell for cell in cells if cell["variant"] == "low")
    high = next(cell for cell in cells if cell["variant"] == "high")
    _fake_stages(monkeypatch)
    selected = stage_models.failed_cells(root, run["run_id"], [low["cell_id"]])
    asyncio.run(stage_models.retry(root, run["run_id"], selected))
    updated = {cell["variant"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}
    assert updated["low"]["status"] == "ok" and updated["low"]["reasoning_efforts"] == low["reasoning_efforts"]
    assert len(updated["low"]["attempts"]) == 1
    assert updated["high"] == high


def test_repeated_model_estimates_count_each_arm(root):
    arms = stage_models.resolve_arms(["adapt_plan"], _arms([OPUS, OPUS]))
    estimates = stage_models.estimate_arms_usd(root / "story", ["adapt_plan"], arms)
    assert estimates == {"arm-1": pytest.approx(6), "arm-2": pytest.approx(6)}
    assert sum(estimates.values()) == pytest.approx(12)


@pytest.mark.parametrize("arms", [
    [{"id": "same", "model": OPUS}, {"id": "same", "model": SONNET}],
    [{"id": "../escape", "model": OPUS}, {"id": "safe", "model": SONNET}],
    [{"id": "one", "model": OPUS}, {"id": "two", "model": OPUS, "reasoning_efforts": {"extract": "enabled"}}],
    [{"id": "one", "model": OPUS}],
    [{"id": "one", "model": OPUS}, "bad"],
])
def test_invalid_comparison_arms_are_rejected_before_spend(arms):
    with pytest.raises(ValueError):
        stage_models.resolve_arms(["extract_brief"], arms)


def test_argon_levels_are_independent_labs_arms(root):
    phases = ["adapt_plan"]
    arms = stage_models.resolve_arms(phases, [
        {"id": effort, "model": "gemini-4-argon", "reasoning_efforts": {"adapt": effort, "plan": effort}}
        for effort in ("low", "medium", "high")
    ])
    stage_models.validate_spec(root / "story", phases, stage_models.arm_models(arms))
    assert [arm["reasoning_efforts"]["plan"] for arm in arms] == ["low", "medium", "high"]
    assert stage_models.estimate_arms_usd(root / "story", phases, arms) == {
        "low": pytest.approx(3), "medium": pytest.approx(3), "high": pytest.approx(3),
    }


@pytest.fixture
def series_root_fixture(tmp_path):
    from novel_to_comic.series import append_parts, initialize_series
    from novel_to_comic.workspace import part_workspace

    user_root = tmp_path / 'series-user'
    root = user_root / 'book'
    (root / 'input').mkdir(parents=True)
    novel = root / 'input/novel.txt'
    novel.write_text('First story.')
    first = initialize_series(root, project_name='Series', novel_path=novel, text='First story.')
    append_parts(root, [('Second', 'Second source words.')], origin='paste')
    (root / 'config.yaml').write_text('litellm_base_url: "http://gateway"\n')
    (root / 'story_bible.json').write_text('{}')
    (root / 'samples/style.png').write_bytes(b'png')
    second = part_workspace(root, 'part_0002')
    for part in (first, second):
        for directory in ('brief', 'adapt', 'plan', 'draw', 'requests'):
            (part / directory).mkdir(exist_ok=True)
        (part / 'brief/adaptation_brief.json').write_text('{"themes":["storm"]}')
        (part / 'adapt/book.json').write_text('{}')
        (part / 'draw/art.png').write_bytes(b'art')
        (part / 'requests/private.json').write_text('{}')
        state = load_state(part)
        for name in STAGE_NAMES:
            state.stages[name].status = StageStatus.COMPLETE
        state.stages['adapt'].usage_log = [{'model': OPUS, 'input_tokens': 1000, 'output_tokens': 100}]
        save_state(state, part)
    series = load_state(root)
    for name in ('style', 'cast'):
        series.stages[name].status = StageStatus.COMPLETE
    save_state(series, root)
    return user_root, root, second


def test_series_listing_and_eligibility_use_part_brief_and_shared_look(series_root_fixture):
    from novel_to_comic.server.routers.labs import _projects
    user_root, root, part = series_root_fixture
    assert load_state(root).stages['brief'].status is StageStatus.PENDING
    (project,) = _projects(user_root)
    assert project['part_id'] == 'part_0002'
    assert project['statuses']['brief'] == project['statuses']['cast'] == project['statuses']['style'] == 'complete'
    assert project['words'] == 3
    stage_models.validate_spec(root, ['adapt_plan'], [OPUS, SONNET])
    assert stage_models.source_workspace(root) == part
    assert stage_models.estimate_stages_usd(root, {'adapt': OPUS, 'plan': OPUS}) == pytest.approx(0.006)


@pytest.mark.parametrize('phase', ['extract_brief', 'adapt_plan'])
def test_series_snapshot_keeps_shared_authorities_and_prior_parts(series_root_fixture, tmp_path, phase):
    from novel_to_comic.target_artifacts import TargetArtifacts
    from novel_to_comic.workspace import series_root
    user_root, root, part = series_root_fixture
    before = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}
    bundle = tmp_path / 'snapshot'
    workspace = stage_models.prepare_workspace(part, bundle, phase)
    assert workspace == bundle / 'parts/part_0002'
    assert series_root(workspace) == bundle
    assert TargetArtifacts(workspace).read_part_text('part_0002') == 'Second source words.'
    assert Path(load_state(workspace).novel_path).read_text() == 'Second source words.'
    assert (bundle / 'story_bible.json').exists() and (bundle / 'samples/style.png').exists()
    assert (bundle / 'parts/part_0001/adapt/book.json').exists()
    assert Path(load_state(bundle / 'parts/part_0001').novel_path).is_relative_to(bundle)
    assert not list(bundle.rglob('draw')) and not list(bundle.rglob('requests'))
    assert not (workspace / 'adapt').exists() and not (workspace / 'plan').exists()
    assert load_state(workspace).stages['style'].status is StageStatus.COMPLETE
    assert load_state(workspace).stages['adapt'].status is StageStatus.PENDING
    assert {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()} == before
    baseline = stage_models.input_fingerprint(workspace)
    (bundle / 'story_bible.json').write_text('{"changed":true}')
    assert stage_models.input_fingerprint(workspace) != baseline


def test_series_arm_and_retry_pin_the_part_even_when_current_part_changes(series_root_fixture, monkeypatch):
    from novel_to_comic.workspace import part_workspace
    user_root, root, part = series_root_fixture
    _fake_stages(monkeypatch, fail='adapt')
    run = storage.create_run(user_root, kind=stage_models.KIND, label='parts', spec={'project': 'book'})
    asyncio.run(stage_models.run(user_root, run['run_id'], 'book', ['adapt_plan'], _arms([OPUS, SONNET])))
    cells = storage.read_run(user_root, run['run_id'])['cells']
    assert all(cell['part_id'] == 'part_0002' and cell['workspace'].endswith('/parts/part_0002') for cell in cells)
    first = part_workspace(root, 'part_0001')
    state = load_state(first)
    state.stages['finish'] = StageState()
    save_state(state, first)
    assert stage_models.source_workspace(root) == first
    calls = _fake_stages(monkeypatch)
    asyncio.run(stage_models.retry(user_root, run['run_id'], [cells[0]]))
    retried = next(cell for cell in storage.read_run(user_root, run['run_id'])['cells'] if cell['cell_id'] == cells[0]['cell_id'])
    assert retried['status'] == 'ok' and retried['part_id'] == 'part_0002'
    assert all(call['dir'].name == 'part_0002' for call in calls)
    assert storage.run_file(user_root, run['run_id'], retried['attempts'][0]['workspace']).is_dir()


def test_series_labs_api_pins_part_and_rejects_unknown_part_before_dispatch(series_root_fixture, monkeypatch):
    from tests.test_labs_gate import _labs_client
    from novel_to_comic.server.auth import get_current_user
    from novel_to_comic.server.routers import labs
    user_root, root, part = series_root_fixture
    client = _labs_client(monkeypatch, user_root.parent)
    client.app.dependency_overrides[get_current_user] = lambda: user_root.name
    dispatched = []
    def start(request, root, run_id, coroutine):
        dispatched.append(run_id)
        coroutine.close()
    monkeypatch.setattr(labs, '_start', start)
    (listed,) = client.get('/api/labs/projects').json()['projects']
    assert listed['part_id'] == 'part_0002' and listed['statuses']['brief'] == 'complete'
    body = {'kind': 'stage_models', 'project': 'book', 'part_id': listed['part_id'],
            'phases': ['adapt_plan'], 'arms': _arms([OPUS, SONNET])}
    estimate = client.post('/api/labs/stage-models/estimate', json=body)
    assert estimate.status_code == 200
    result = client.post('/api/labs/runs', json=body)
    assert result.status_code == 200 and result.json()['spec']['part_id'] == 'part_0002'
    assert result.json()['spec']['estimated_cost_usd'] == estimate.json()['estimated_cost_usd']
    body['part_id'] = 'part_9999'
    assert client.post('/api/labs/runs', json=body).status_code == 400
    assert client.post('/api/labs/stage-models/estimate', json=body).status_code == 400
    assert len(dispatched) == 1
