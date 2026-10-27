"""Cold Open planning: provider-free scene, look and cost choices."""

from unittest.mock import patch

import pytest

from novel_to_comic.cold_open import HouseLook, choose_looks, house_looks, plan_cold_open
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.style_contract import COLOR_MARKER, style_template_for_suggestion


def _bible(summary: str = "Mara crosses the square.", mood: str = "calm") -> StoryBible:
    return StoryBible(
        title="Opening",
        author="A. Writer",
        total_scenes=1,
        characters=[
            Character(
                id="char_001", name="Mara", visual_anchor="1woman, adult, short grey hair",
                age_range="40s", gender="female", distinguishing_features=[],
                default_outfit="", relationships=[], first_appearance_scene="scene_001",
            )
        ],
        locations=[Location(id="loc_001", name="Square", visual_anchor="cobbled square", mood=mood)],
        scenes=[
            Scene(
                id="scene_001", chapter=1, title="Arrival", location_id="loc_001",
                character_ids=["char_001"], summary=summary, scene_type="action",
                narrative_beat="inciting_incident", source_start_quote="Mara arrived",
            )
        ],
        sequences=[],
        props=[],
    )


def test_house_looks_keep_their_color_and_medium_authority():
    looks = house_looks()
    assert len({look.id for look in looks}) == len(looks)
    for look in looks:
        assert look.suggestion["origin"] == "cold_open"
        assert look.suggestion["medium_family"] and look.suggestion["color_strategy"]
        assert COLOR_MARKER in style_template_for_suggestion(look.suggestion)


def test_three_distinct_looks_include_a_comic():
    looks = choose_looks(_bible())
    assert len(looks) == 3
    assert len({look.suggestion["medium_family"] for look in looks}) == 3
    assert len({look.suggestion["color_strategy"] for look in looks}) == 3
    assert any(look.suggestion["medium_family"] == "comic_production" for look in looks)
    assert choose_looks(_bible()) == looks


def test_the_best_story_match_leads():
    horror = _bible("A ghost curse haunts the dark house; fear and blood.", mood="dread")
    assert choose_looks(horror)[0].label == "Scratchboard Dread"


def test_a_comic_takes_the_last_place_when_matches_have_none():
    def look(label, family, color, signals=()):
        return HouseLook({"id": label, "label": label, "medium_family": family,
                          "color_strategy": color}, frozenset(signals))

    looks = (
        look("Paint", "painted", "muted", {"mara"}),
        look("Pencil", "drawn", "monochrome", {"mara"}),
        look("Print", "printmaking", "spot_color", {"mara"}),
        look("Comic", "comic_production", "saturated"),
    )
    assert [chosen.label for chosen in choose_looks(_bible(), looks)] == ["Paint", "Pencil", "Comic"]


def test_plan_prices_three_images_and_the_shared_text_once(tmp_path):
    images = []

    def image_cost(_model, _count, **kwargs):
        images.append(kwargs["prompt_text"])
        return 0.03

    with (
        patch("novel_to_comic.usage.estimate_text_cost", return_value=0.002) as text_cost,
        patch("novel_to_comic.usage.estimate_image_cost", side_effect=image_cost),
    ):
        plan = plan_cold_open(Config(), tmp_path, _bible())

    # One proof brief and one story-copy call, shared by all three proofs.
    assert text_cost.call_count == 2
    assert plan.text_cost_usd == pytest.approx(0.004)
    assert plan.cost_usd == pytest.approx(0.094)
    assert len(images) == len(set(images)) == 3
    assert plan.scene_id == "scene_001"
    assert plan.subjects == ("Mara",)
    assert [proof.look_id for proof in plan.proofs] == [look.id for look in choose_looks(_bible())]


# --- Integration: snapshot, funding, admission, the job, adoption ------------

import asyncio  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402
from types import SimpleNamespace  # noqa: E402

from novel_to_comic import artifacts, cold_open  # noqa: E402
from novel_to_comic.ai import client  # noqa: E402
from novel_to_comic.ai.context import ai_request_context  # noqa: E402
from novel_to_comic.extraction_sections import publish_opening  # noqa: E402
from novel_to_comic.models.cold_open import ColdOpenLook, OpeningSnapshot  # noqa: E402
from novel_to_comic.server import cold_open_jobs  # noqa: E402
from novel_to_comic.server.job_commands import JobCommand, command  # noqa: E402
from novel_to_comic.target_artifacts import TargetArtifacts  # noqa: E402
from novel_to_comic.usage import ApiResult, UsageRecord  # noqa: E402
from novel_to_comic.workspace import create_part_workspace  # noqa: E402

OPENING = "Mara arrived at dusk. The square was empty.\n\nThen the bell rang and nobody came."


def _opening_bible() -> StoryBible:
    bible = _bible()
    second = bible.scenes[0].model_copy(update={
        "id": "scene_002", "title": "The bell", "source_start_quote": "Then the bell rang",
        "scene_type": "dialogue", "narrative_beat": "rising_action"})
    bible.scenes[0].source_start_offset = 0
    second.source_start_offset = OPENING.index("Then the bell")
    bible.scenes.append(second)
    bible.total_scenes = 2
    return bible


def _series(tmp_path):
    root = tmp_path / "series"
    part = create_part_workspace(root, "part_0001")
    (root / "state.json").write_text("{}")
    return root, part


def test_choose_looks_follows_a_model_ranking_but_keeps_contrast():
    looks = house_looks()
    noir = next(look for look in looks if "Noir" in look.label)
    order = (noir.id, *(look.id for look in looks if look is not noir))
    chosen = choose_looks(_bible(), order=order)
    assert chosen[0] is noir
    assert len({look.suggestion["medium_family"] for look in chosen}) == 3
    assert any(look.suggestion["medium_family"] == "comic_production" for look in chosen)


def test_opening_passage_is_the_scene_own_text_until_the_next_scene():
    bible = _opening_bible()
    snapshot = OpeningSnapshot(bible=bible, text=OPENING, whole_source=False)
    assert cold_open.opening_passage(snapshot, bible.scenes[0]) == "Mara arrived at dusk. The square was empty."
    assert cold_open.opening_passage(snapshot, bible.scenes[1]) == "Then the bell rang and nobody came."
    # A short book's source document is published before the Cold Open runs.
    whole = snapshot.model_copy(update={"whole_source": True})
    assert cold_open.opening_passage(whole, bible.scenes[0]) is None


def test_extract_publishes_the_opening_and_announces_it(tmp_path):
    _root, part = _series(tmp_path)
    ctx = SimpleNamespace(snapshot=lambda data: announced.append(data))
    announced = []
    publish_opening(ctx, part, _opening_bible(), text=OPENING, whole_source=False)
    snapshot = TargetArtifacts(part).read_opening_snapshot()
    assert snapshot.text == OPENING and len(snapshot.bible.scenes) == 2
    assert announced == [{"opening": {"scenes": 2, "characters": 1}}]


def test_sponsored_calls_are_never_authorized_or_debited(monkeypatch):
    monkeypatch.setattr("novel_to_comic.server.credits.authorize_model_call",
                        lambda *a, **k: pytest.fail("Cold Open calls hold no user credits"))
    monkeypatch.setattr(client, "_settle_event_usage",
                        lambda *a, **k: pytest.fail("Cold Open calls are never debited"))
    monkeypatch.setattr(client, "mock_mode_active", lambda _config: False)
    usage = UsageRecord(provider="openai", model="gpt-image-2", call_id="call-1", operation="image",
                        image_count=1, cost_usd=0.02)
    with ai_request_context(user_id="00000000-0000-0000-0000-000000000001", job_id="job", sponsor="cold_open"):
        asyncio.run(client._authorize_model_submission(
            event_id="call-1", estimated_cost_usd=0.03, funding="api", config=Config()))
        client._finalize_event(event_id="call-1", status="succeeded", feature="style.sample",
                               model_alias="gpt-image-2", latency_ms=10, usage=usage, operation="image")


def test_only_the_cold_open_is_canary_paid():
    spec = command("cold_open", Path("/tmp/x"), Config(), part_dir="/tmp/x/parts/part_0001")
    for update in ({"operation": "cover", "arguments": {}}, {"reservation_credits": 3}):
        with pytest.raises(ValueError, match="Only the Cold Open"):
            JobCommand.model_validate({**spec.model_dump(), "sponsor": "cold_open", **update})


def test_each_account_gets_one_cold_open(tmp_path, monkeypatch):
    monkeypatch.delenv("CANARY_COLD_OPEN_PER_ACCOUNT", raising=False)
    monkeypatch.setenv("CANARY_ENV", "production")
    assert cold_open_jobs.claim_grant(tmp_path, "project-a")
    assert cold_open_jobs.claim_grant(tmp_path, "project-a")  # the same project again
    assert not cold_open_jobs.claim_grant(tmp_path, "project-b")
    monkeypatch.setenv("CANARY_COLD_OPEN_PER_ACCOUNT", "0")
    assert not cold_open_jobs.claim_grant(tmp_path / "other", "project-c")


def test_outside_production_every_project_gets_a_cold_open(tmp_path, monkeypatch):
    monkeypatch.delenv("CANARY_COLD_OPEN_PER_ACCOUNT", raising=False)
    monkeypatch.setenv("CANARY_ENV", "development")
    assert cold_open_jobs.claim_grant(tmp_path, "project-a")
    assert cold_open_jobs.claim_grant(tmp_path, "project-b")
    monkeypatch.setenv("CANARY_COLD_OPEN_PER_ACCOUNT", "0")
    assert not cold_open_jobs.claim_grant(tmp_path, "project-c")


def test_admission_enqueues_canary_paid_work_once(tmp_path, monkeypatch):
    root, part = _series(tmp_path)
    queued = []
    monkeypatch.setattr(cold_open_jobs, "enqueue_generation_job", lambda app, **kw: queued.append(kw) or kw)
    monkeypatch.setattr(cold_open_jobs, "generation_semaphore_for_config", lambda app, config: None)
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={}))
    start = lambda **kw: cold_open_jobs.start_cold_open(  # noqa: E731
        app, user_id="user", config=Config(), **{"project_id": "project", "part_dir": part, **kw})

    assert start() is None  # Extract has not read the opening yet
    TargetArtifacts(part).write_opening_snapshot(OpeningSnapshot(bible=_opening_bible(), text=OPENING, whole_source=False))
    assert start(project_id=None) is None
    assert start()["kind"] == "cold_open"
    spec = queued[0]["command"]
    assert spec.sponsor == "cold_open" and spec.reservation_credits == 0 and spec.operation == "cold_open"
    assert cold_open.read_record(root).scene_id == "scene_001"
    assert start() is None  # one per project, ever
    assert len(queued) == 1


def _job(root, part):
    spec = command("cold_open", root, Config(), part_dir=str(part.resolve()))
    spec = JobCommand.model_validate({**spec.model_dump(), "sponsor": "cold_open", "user_id": "u", "project_id": "p"})
    return SimpleNamespace(command=spec, payload={})


def test_the_job_prints_three_pages_and_isolates_a_failure(tmp_path, monkeypatch):
    from novel_to_comic.stages import s2_style as style

    root, part = _series(tmp_path)
    bible = _opening_bible()
    TargetArtifacts(part).write_opening_snapshot(OpeningSnapshot(bible=bible, text=OPENING, whole_source=False))
    cold_open.begin_record(root, "part_0001", bible)
    looks = choose_looks(bible)
    passages = []

    async def brief(config, story_bible, project_dir, *, passage=None):
        passages.append(passage)
        return "a brief"

    async def rank(config, story_bible, record_usage):
        record_usage(UsageRecord(provider="vertex_ai", model="gemini-4-argon", call_id="rank", operation="text", cost_usd=0.001))
        return tuple(look.id for look in reversed(looks))

    async def draw(config, story_bible, path, *, candidate_id, **kwargs):
        if candidate_id == looks[1].id:
            raise RuntimeError("provider said no")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"png")
        return ApiResult(path, usage=UsageRecord(provider="openai", model="gpt-image-2", call_id=candidate_id,
                                                 operation="image", image_count=1, cost_usd=0.02))

    monkeypatch.setattr(style, "ensure_style_sample_brief", brief)
    monkeypatch.setattr(style, "generate_sample_image", draw)
    monkeypatch.setattr(cold_open, "rank_looks", rank)
    monkeypatch.setattr(cold_open_jobs, "persist_generation_job", lambda app, job: None)
    monkeypatch.setattr("novel_to_comic.usage.calculate_cost_breakdown",
                        lambda usage: SimpleNamespace(cost_usd=usage.cost_usd, source="reported"))
    asyncio.run(cold_open_jobs.execute_cold_open(None, _job(root, part), root, Config()))

    record = cold_open.read_record(root)
    assert passages == ["Mara arrived at dusk. The square was empty."]
    assert record.status == "ready" and record.ranking == "model"
    assert [entry.status for entry in record.looks].count("ready") == 2
    assert next(entry for entry in record.looks if entry.id == looks[1].id).status == "failed"
    assert record.provider_cost_usd == pytest.approx(0.041)
    assert not cold_open.style_has_suggestions(root)  # nothing reached Style


def test_style_adopts_only_proofs_it_would_draw_identically(tmp_path):
    root, _part = _series(tmp_path)
    config = Config()
    bible = _opening_bible()
    record = cold_open.begin_record(root, "part_0001", bible)
    looks = choose_looks(bible)
    record.looks = [ColdOpenLook(id=look.id, label=look.label, medium="m", status="ready") for look in looks]
    record.favorite_look_id = looks[2].id
    cold_open.write_record(root, record)
    for look in looks:
        request = cold_open._proof_request(config, root, bible, look.suggestion, None)
        path = cold_open.proof_path(root, look.id)
        path.write_bytes(look.id.encode())
        artifacts.write_asset_meta(path, {"provenance": {"execution_fingerprint": request.wire.execution_fingerprint}})

    # The final read drew a different proof (here, a richer anchor): nothing is adopted.
    changed = bible.model_copy(deep=True)
    changed.characters[0].visual_anchor += ", round glasses"
    assert cold_open.adoptable_looks(config, root, changed) == []

    adopted = cold_open.adoptable_looks(config, root, bible)
    assert [suggestion["id"] for suggestion in adopted][0] == looks[2].id  # the favorite leads
    cold_open.adopt_into_style(root, adopted, 1)
    assert artifacts.style_sample_path(root, 1).read_bytes() == looks[2].id.encode()
    assert json.loads(artifacts.asset_meta_path(artifacts.style_sample_path(root, 1)).read_text())
    assert cold_open.adoptable_looks(config, root, bible) == []  # never twice


def test_the_cold_open_never_holds_the_author_s_work_back():
    from novel_to_comic.server.admission import mutation_conflicts, project_busy

    printing = SimpleNamespace(project_name="u:p", kind="cold_open", status="running", payload={},
                               command=SimpleNamespace(project_dir="/x/series"))
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={"j": printing}))
    assert not project_busy(app, "u:p")
    assert not project_busy(app, "u:p", "part_0001")
    assert not mutation_conflicts(app, "u:p", "/approve/brief", "part_0001")
    assert not mutation_conflicts(app, "u:p", "/styles/suggest")
    # Deleting the project still waits: the job writes into it.
    assert project_busy(app, "u:p", ambient=True)
