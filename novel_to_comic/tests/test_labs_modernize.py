"""Labs source modernization: excerpts, controls, alignment checks and the provider-free run path."""

import asyncio
from datetime import UTC, datetime

import pytest

from novel_to_comic.ai.context import current_ai_request_context
from novel_to_comic.labs import modernize, storage
from novel_to_comic.state import STAGE_NAMES, PipelineState, StageState, StageStatus, save_state
from novel_to_comic.usage import ApiResult, UsageRecord

OPUS = "claude-opus-5-5"
NOVEL = """CHAPTER I

"Thou art late," said the old man, looking up from the heavy
book that lay open upon his knees.

She curtsied. "Forgive me, sir; 'twas the rain."

The fire crackled whilst they spoke.
"""


@pytest.fixture
def root(tmp_path):
    user_root = tmp_path / "user"
    project = user_root / "story"
    (project / "input").mkdir(parents=True)
    (project / "config.yaml").write_text('litellm_base_url: "http://gateway"\n')
    (project / "input" / "story.txt").write_text(NOVEL)
    save_state(PipelineState(
        project_name="Story", novel_path=str(project / "input" / "story.txt"), created_at=datetime.now(UTC),
        stages={name: StageState(status=StageStatus.PENDING) for name in STAGE_NAMES},
    ), project)
    return user_root


def test_paragraphs_rejoin_hard_wrapped_lines():
    assert modernize.paragraphs(NOVEL) == [
        "CHAPTER I",
        '"Thou art late," said the old man, looking up from the heavy book that lay open upon his knees.',
        "She curtsied. \"Forgive me, sir; 'twas the rain.\"",
        "The fire crackled whilst they spoke.",
    ]


def test_unwrapped_lines_stay_separate_paragraphs_between_part_breaks():
    long = "The fire burned brightly in the small parlour while the wind howled outside the villa."
    assert modernize.paragraphs(f"Part I\n“Check.”\n{long}\n“Mate.”\n\nPart II\n{long}") == [
        "Part I", "“Check.”", long, "“Mate.”", "Part II", long,
    ]


def test_excerpt_takes_whole_paragraphs_within_the_word_budget(root):
    paragraphs = modernize.manuscript(root / "story")
    found = modernize.excerpt(paragraphs, 1, 27)
    assert (found["start"], found["end"]) == (1, 3)
    assert found["words"] == 27 and found["total_paragraphs"] == 4
    # A single paragraph larger than the budget is still returned, never an empty passage.
    assert modernize.excerpt(paragraphs, 1, 1)["end"] == 2
    with pytest.raises(ValueError):
        modernize.excerpt(paragraphs, 4, 100)
    with pytest.raises(ValueError):
        modernize.excerpt(paragraphs, 0, modernize.MAX_WORDS + 1)


def test_controls_and_arms_are_validated_before_spend():
    assert modernize.validate_controls({}) == {
        "intensity": "moderate", "scope": "both", "sensitive": "soften", "keep_setting": True,
        "comic_ready": True, "notes": "",
    }
    for bad in ({"intensity": "max"}, {"scope": "all"}, {"sensitive": "erase"}, {"notes": "x" * 1001}):
        with pytest.raises(ValueError):
            modernize.validate_controls(bad)
    with pytest.raises(ValueError):
        modernize.validate_arms([])
    with pytest.raises(ValueError):
        modernize.validate_arms([{"id": "a", "model": "not-a-model"}])
    with pytest.raises(ValueError):
        modernize.validate_arms([{"id": "a", "model": OPUS}, {"id": "a", "model": OPUS}])
    with pytest.raises(ValueError):
        modernize.validate_arms([{"id": "a", "model": OPUS, "reasoning": "extreme"}])


def test_system_prompt_carries_every_control():
    prompt = modernize.system_prompt(modernize.validate_controls({
        "intensity": "light", "scope": "dialogue", "sensitive": "keep", "keep_setting": False, "notes": "Keep Holmes formal.",
    }))
    assert modernize.INTENSITIES["light"] in prompt
    assert modernize.SCOPES["dialogue"] in prompt
    assert modernize.SENSITIVE["keep"] in prompt
    assert "present-day idiom" in prompt
    assert "Author direction for this passage: Keep Holmes formal." in prompt
    assert modernize.COMIC[0] in prompt


def test_prompt_targets_the_weak_spots_of_the_first_comparison():
    prompt = modernize.system_prompt(modernize.validate_controls({"intensity": "contemporary"}))
    # Narrator asides count as offensive, and every instance is flagged whatever the setting.
    assert "as patiently as her sex would permit" in prompt
    assert "whatever you do with it" in prompt
    # Regional English stays consistent, nuance survives, and accidental-looking grammar is standardized.
    assert "never mixes in American ones" in prompt
    assert "'stealthy' knock stays furtive" in prompt
    assert '"he don\'t"' in prompt
    # Contemporary must restructure, and the changes list is for review, not routine rewording.
    assert "10-20% shorter" in prompt and "is not a cut" in prompt
    assert "Do not list routine rewording" in prompt


def test_prompt_keeps_drawing_cues_and_emphasis_and_labels_every_addition_and_cut():
    prompt = modernize.system_prompt(modernize.validate_controls({"intensity": "contemporary"}))
    # Tone adverbs tell the artist what face to draw.
    assert "'solemnly'" in prompt and "is a drawing cue: keep it" in prompt
    # Capitals survive for lettering, comic-ready or not.
    assert '"THE PAW!" stays in capitals' in prompt
    assert '"THE PAW!" stays in capitals' in modernize.system_prompt(modernize.validate_controls({"comic_ready": False}))
    # Anything added is inferred, never clarity; every dropped clause is tightened.
    assert "Use 'inferred', never 'clarity', for these" in prompt
    assert "Fewer words for the same content is routine rewording, not tightened" in prompt


def test_prompt_pushes_punch_with_subject_first_tags_and_a_sentence_target():
    prompt = modernize.system_prompt(modernize.validate_controls({"intensity": "contemporary"}))
    assert "subject first ('his father said'" in prompt
    assert "about 9-10 words on average" in prompt
    plain = modernize.system_prompt(modernize.validate_controls({"comic_ready": False}))
    assert "about 9-10 words on average" not in plain and "subject first" in plain
    assert modernize.COMIC[0] not in modernize.system_prompt(modernize.validate_controls({"comic_ready": False}))


def test_comic_metrics_measure_sentence_and_speech_load():
    long_speech = "“" + " ".join(["word"] * 30) + ".”"
    metrics = modernize.comic_metrics(["“Check.” He moved. The board was set.", long_speech])
    assert metrics == {"avg_sentence_words": 9.2, "longest_speech_words": 30, "long_speeches": 1}


def test_estimates_use_earlier_runs_of_the_same_model_and_reasoning(monkeypatch, root):
    monkeypatch.setattr(modernize.stage_models, "_funding", lambda model: "api")
    source = {"paragraphs": ["word " * 100], "words": 1000}
    arms = [{"id": "a", "model": OPUS, "reasoning": "medium"}, {"id": "b", "model": OPUS, "reasoning": "high"}]
    before = modernize.estimate_usd(root, source, arms, modernize.validate_controls({}))
    assert before["a"]["basis"] == "heuristic" and before["b"]["basis"] == "heuristic"
    # High reasoning is allowed more thinking output than medium.
    assert before["b"]["usd"] > before["a"]["usd"]
    run = storage.create_run(root, kind=modernize.KIND, label="t", spec={})
    storage.write_cell(root, run["run_id"], "x", {
        "status": "ok", "model": OPUS, "reasoning": "medium",
        "checks": {"words_before": 1000}, "usage": {"output_tokens": 10_000},
    })
    after = modernize.estimate_usd(root, source, arms, modernize.validate_controls({}))
    assert after["a"]["basis"] == "history" and after["a"]["runs"] == 1
    assert after["a"]["usd"] > before["a"]["usd"]
    assert after["b"]["basis"] == "heuristic"


def test_align_keeps_dropped_paragraphs_and_flags_edits_outside_scope():
    source = ['"Thou art late," said the old man.', "The fire crackled whilst they spoke.", "Unchanged."]
    revised, checks = modernize.align(source, {"paragraphs": [
        {"index": 0, "text": '"You\'re late," said the old man.'},
        {"index": 1, "text": "The fire crackled while they spoke."},
        {"index": 7, "text": "Invented."},
    ]})
    assert revised == ['"You\'re late," said the old man.', "The fire crackled while they spoke.", "Unchanged."]
    assert checks["changed_paragraphs"] == 2
    assert checks["missing_paragraphs"] == [2]
    assert checks["extra_paragraphs"] == [7]
    assert checks["dialogue_edits"] == [0]
    assert checks["narration_edits"] == [1]
    assert modernize.scope_violations("dialogue", checks) == [1]
    assert modernize.scope_violations("narration", checks) == [0]
    assert modernize.scope_violations("both", checks) == []


def test_run_freezes_the_passage_and_records_each_arm(monkeypatch, root):
    from novel_to_comic.clients import text

    calls = []

    async def generate_json(config, model, system_prompt, user_content, **kwargs):
        calls.append({"model": model, "effort": config.text_reasoning_effort, "user": user_content,
                      "stage": current_ai_request_context().stage, "feature": kwargs["feature"]})
        if model == "broken":
            raise RuntimeError("provider down")
        return ApiResult(
            value={"paragraphs": [{"index": 0, "text": "CHAPTER I"},
                                  {"index": 1, "text": '"You\'re late," said the old man, looking up from the heavy book that lay open upon his knees.'}],
                   "changes": [{"paragraph": 1, "original": "Thou art", "revised": "You're",
                                "category": "archaic", "note": "obsolete pronoun"}]},
            usage=UsageRecord(provider="anthropic", model=model, operation="text",
                              input_tokens=100, output_tokens=50, cost_usd=0.01),
        )

    monkeypatch.setattr(text, "generate_json", generate_json)
    monkeypatch.setattr(modernize.stage_models, "_funding", lambda model: "api")
    source = modernize.validate_source({"start": 0, "max_words": 21}, root / "story")
    assert len(source["paragraphs"]) == 2
    run = storage.create_run(root, kind=modernize.KIND, label="t", spec={"project": "story"})
    modernize.write_source(root, run["run_id"], source)
    controls = modernize.validate_controls({"scope": "dialogue"})
    arms = [{"id": "arm-1", "model": OPUS, "reasoning": "low"}, {"id": "arm-2", "model": "broken", "reasoning": "high"}]

    asyncio.run(modernize.run(root, run["run_id"], "story", arms, controls))

    cells = {cell["cell_id"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}
    ok, failed = cells["arm-1"], cells["arm-2"]
    assert ok["status"] == "ok" and ok["reasoning"] == "low"
    assert ok["paragraphs"][1].startswith('"You\'re late,"')
    assert ok["checks"]["changed_paragraphs"] == 1 and ok["checks"]["scope_violations"] == []
    assert ok["changes"][0]["category"] == "archaic"
    assert ok["cost_usd"] == 0.01 and ok["usage"]["input_tokens"] == 100
    assert failed["status"] == "failed" and "provider down" in failed["error"]
    assert {call["effort"] for call in calls} == {"low", "high"}
    assert {call["stage"] for call in calls} == {"modernize"}
    assert all(call["user"] == modernize.user_content(source["paragraphs"]) for call in calls)

    # A retry resends the frozen passage and keeps the failed attempt on the cell.
    storage.update_run(root, run["run_id"], spec={"project": "story", "controls": controls,
                                                  "arms": [arms[0], {**arms[1], "model": OPUS}]})
    retry_cells = modernize.failed_cells(root, run["run_id"], None)
    assert [cell["cell_id"] for cell in retry_cells] == ["arm-2"]
    asyncio.run(modernize.retry(root, run["run_id"], retry_cells))
    retried = {cell["cell_id"]: cell for cell in storage.read_run(root, run["run_id"])["cells"]}["arm-2"]
    assert retried["status"] == "ok"
    assert retried["attempts"][0]["error"] == failed["error"]


def test_router_creates_a_modernize_run_from_pasted_text(monkeypatch, root):
    from tests.test_labs_gate import _labs_client
    from novel_to_comic.server.auth import get_current_user
    from novel_to_comic.server.routers import labs

    client = _labs_client(monkeypatch, root.parent)
    monkeypatch.setattr(modernize, "estimate_usd",
                        lambda user_root, source, arms, controls: {"arm-1": {"usd": 0.02, "basis": "heuristic", "runs": 0}})
    dispatched = []

    def start(request, user_root, run_id, coroutine, cells=None):
        dispatched.append(run_id)
        coroutine.close()

    monkeypatch.setattr(labs, "_start", start)
    # The fixture's user root is "user"; the Labs client signs in as "owner".
    client.app.dependency_overrides[get_current_user] = lambda: "user"

    body = {"kind": "modernize", "project": "story", "text": "Ere long.\n\nHe hath gone.",
            "controls": {"intensity": "light"}, "arms": [{"id": "arm-1", "model": OPUS}]}
    assert client.post("/api/labs/runs", json=body | {"controls": {"intensity": "wild"}}).status_code == 400
    assert client.post("/api/labs/runs", json=body | {"text": "word " * (modernize.MAX_WORDS + 1)}).status_code == 400
    assert not dispatched
    result = client.post("/api/labs/runs", json=body)
    assert result.status_code == 200, result.text
    run_id = result.json()["run_id"]
    spec = result.json()["spec"]
    assert spec["source"]["origin"] == "pasted" and spec["source"]["paragraphs"] == 2
    assert spec["estimated_cost_usd"] == {"arm-1": 0.02}
    assert dispatched == [run_id]
    assert client.get(f"/api/labs/runs/{run_id}/files/source.json").json()["paragraphs"] == ["Ere long.", "He hath gone."]

    excerpt = client.get("/api/labs/modernize/projects/story/excerpt", params={"start": 1, "max_words": 27})
    assert excerpt.status_code == 200 and excerpt.json()["end"] == 3
    estimate = client.post("/api/labs/modernize/estimate", json=body).json()
    assert estimate["estimated_cost_usd"] == {"arm-1": 0.02}
    assert estimate["estimate_basis"] == {"arm-1": {"basis": "heuristic", "runs": 0}}
