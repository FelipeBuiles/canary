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
        record_usage(UsageRecord(provider="vertex_ai", model="gemini-4-carbon", call_id="rank", operation="text", cost_usd=0.001))
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


def test_look_opens_on_the_first_pages_without_generation(tmp_path):
    from novel_to_comic.stages.s2_style import load_suggestions, save_suggestions
    from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state

    root, _part = _series(tmp_path)
    save_state(create_initial_state("demo", "novel.txt"), root)
    config = Config()
    bible = _opening_bible()
    artifacts.story_bible_path(root).write_text(bible.model_dump_json())
    record = cold_open.begin_record(root, "part_0001", bible)
    looks = choose_looks(bible)
    record.looks = [ColdOpenLook(id=look.id, label=look.label, medium="m", status="ready") for look in looks]
    record.looks[1].status = "failed"
    record.favorite_look_id = looks[2].id
    cold_open.write_record(root, record)
    for look in (looks[0], looks[2]):
        request = cold_open._proof_request(config, root, bible, look.suggestion, None)
        path = cold_open.proof_path(root, look.id)
        path.write_bytes(look.id.encode())
        artifacts.write_asset_meta(path, {"provenance": {"execution_fingerprint": request.wire.execution_fingerprint}})

    assert cold_open_jobs.adopt_first_pages(root, config) == [looks[2].id, looks[0].id]  # the favorite leads
    assert [suggestion["id"] for suggestion in load_suggestions(root)] == [looks[2].id, looks[0].id]
    assert artifacts.style_sample_path(root, 1).read_bytes() == looks[2].id.encode()
    # Reviewable, so choosing a proof approves Style; nothing is selected for the author.
    style_state = load_state(root).stages["style"]
    assert style_state.status == StageStatus.AWAITING_REVIEW and style_state.items_done == 2
    assert Config().style_template == config.style_template
    assert cold_open_jobs.adopt_first_pages(root, config) == []  # never twice

    # Look's own proofs are never joined uninvited.
    other, _part = _series(tmp_path / "other")
    save_state(create_initial_state("demo", "novel.txt"), other)
    artifacts.story_bible_path(other).write_text(bible.model_dump_json())
    cold_open.write_record(other, record.model_copy(update={"adopted_look_ids": []}))
    save_suggestions(other, [looks[1].suggestion], bible.title)
    assert cold_open_jobs.adopt_first_pages(other, config) == []


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


# --- Canary-paid first Extract, the daily ceiling, and grant routes only ---

from novel_to_comic import image_route_fallback, sponsored_budget  # noqa: E402
from novel_to_comic.server import free_opening_guard  # noqa: E402
from novel_to_comic.server.free_opening_guard import Applicant  # noqa: E402
from novel_to_comic.state import StageStatus  # noqa: E402


def _applicant(email="mara@example.com", ip="203.0.113.7", verified=True):
    return Applicant(email, verified, ip)


def _extract_state(status=StageStatus.PENDING):
    return SimpleNamespace(stages={"extract": SimpleNamespace(status=status)})


def _free_opening(tmp_path, monkeypatch, *, length=9000, env="production"):
    monkeypatch.setenv("CANARY_ENV", env)
    monkeypatch.delenv("CANARY_COLD_OPEN_PER_ACCOUNT", raising=False)
    monkeypatch.delenv("CANARY_SPONSORED_DAILY_USD", raising=False)
    monkeypatch.setenv("CANARY_FREE_OPENING_MAX_CHARS", "20000")
    monkeypatch.delenv("CANARY_FREE_OPENING_PER_IP_DAILY", raising=False)
    monkeypatch.delenv("CANARY_DISPOSABLE_EMAIL_DOMAINS", raising=False)
    monkeypatch.setattr("novel_to_comic.stages.s1_extract.source_text",
                        lambda *_: ("Mara crossed the square. " * length)[:length])
    volume = tmp_path / "volume"
    part = create_part_workspace(volume / "account" / "series", "part_0001")
    return volume, part


def test_the_first_extract_is_free_only_when_enabled(tmp_path, monkeypatch):
    _, part = _free_opening(tmp_path, monkeypatch)
    sponsor = lambda **kw: cold_open_jobs.free_opening_sponsor(  # noqa: E731
        **{"part_dir": part, "state": _extract_state(), "project_id": "project", "stage": "extract",
           "applicant": _applicant(), **kw})
    monkeypatch.delenv("CANARY_FREE_OPENING_MAX_CHARS")
    assert sponsor() is None  # off unless the operator sets a length
    monkeypatch.setenv("CANARY_FREE_OPENING_MAX_CHARS", "20000")
    assert sponsor() == "cold_open"
    assert not (part.parent.parent.parent / cold_open_jobs.GRANTS_FILE).exists()  # asking claims nothing
    assert not (part.parents[3] / free_opening_guard.CLAIMS_FILE).exists()
    assert sponsor(stage="brief") is None
    assert sponsor(rerun=True) is None
    assert sponsor(project_id=None) is None
    assert sponsor(state=_extract_state(StageStatus.COMPLETE)) is None
    later = create_part_workspace(part.parent.parent, "part_0002")
    assert sponsor(part_dir=later) is None


def test_a_long_upload_pays_for_its_own_extract(tmp_path, monkeypatch):
    _, part = _free_opening(tmp_path, monkeypatch, length=20001)
    assert cold_open_jobs.free_opening_sponsor(
        part, _extract_state(), "project", "extract", applicant=_applicant()) is None


def test_the_free_extract_spends_the_account_s_one_grant(tmp_path, monkeypatch):
    _, part = _free_opening(tmp_path, monkeypatch)
    claim = lambda project: cold_open_jobs.free_opening_sponsor(  # noqa: E731
        part, _extract_state(), project, "extract", claim=True, applicant=_applicant())
    assert claim("project-a") == "cold_open"
    assert claim("project-a") == "cold_open"  # a failed run retries free
    # The job has no request to judge; it honors what the run request admitted.
    assert cold_open_jobs.free_opening_sponsor(part, _extract_state(), "project-a", "extract", claim=True) == "cold_open"
    assert claim("project-b") is None
    # The Cold Open that follows uses the same grant, not a second one.
    assert cold_open_jobs.claim_grant(part.parent.parent.parent, "project-a")
    monkeypatch.setenv("CANARY_COLD_OPEN_PER_ACCOUNT", "0")
    assert claim("project-a") is None  # the kill switch covers the free Extract too


def test_the_daily_ceiling_stops_new_sponsored_work(tmp_path, monkeypatch):
    volume, part = _free_opening(tmp_path, monkeypatch)
    assert sponsored_budget.daily_ceiling_usd() == 10.0
    sponsored_budget.record_spend(volume, 6.0)
    assert sponsored_budget.has_room(volume)
    sponsored_budget.record_spend(volume, 4.5)
    sponsored_budget.record_spend(volume, None)
    assert sponsored_budget.spent_today_usd(volume) == 10.5
    assert not sponsored_budget.has_room(volume)
    assert cold_open_jobs.free_opening_sponsor(
        part, _extract_state(), "project", "extract", claim=True, applicant=_applicant()) is None
    assert not (volume / "account" / cold_open_jobs.GRANTS_FILE).exists()  # a refused day keeps the grant
    # A new day starts from zero.
    monkeypatch.setattr(sponsored_budget, "_today", lambda: "2999-01-01")
    assert sponsored_budget.spent_today_usd(volume) == 0.0 and sponsored_budget.has_room(volume)
    monkeypatch.setenv("CANARY_ENV", "development")
    assert sponsored_budget.daily_ceiling_usd() is None  # local work is never refused


def test_the_ceiling_refuses_a_cold_open_without_spending_the_grant(tmp_path, monkeypatch):
    volume, part = _free_opening(tmp_path, monkeypatch)
    (part.parent.parent / "state.json").write_text("{}")
    TargetArtifacts(part).write_opening_snapshot(
        OpeningSnapshot(bible=_opening_bible(), text=OPENING, whole_source=False))
    monkeypatch.setattr(cold_open_jobs, "enqueue_generation_job", lambda app, **kw: pytest.fail("admitted"))
    sponsored_budget.record_spend(volume, 10.0)
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={}))
    assert cold_open_jobs.start_cold_open(
        app, user_id="user", project_id="project", part_dir=part, config=Config()) is None
    assert not (volume / "account" / cold_open_jobs.GRANTS_FILE).exists()


def test_sponsored_calls_count_toward_the_ceiling_from_either_workspace(tmp_path):
    volume = tmp_path / "volume"
    assert sponsored_budget.volume_for_workspace(volume / "account") == volume
    assert sponsored_budget.volume_for_workspace(volume / "account" / "series" / "parts") == volume
    usage = UsageRecord(provider="vertex", model="gemini", call_id="call-2", operation="text", cost_usd=0.02)
    with ai_request_context(user_id="u", job_id="job", sponsor="cold_open",
                            workspace_id=str(volume / "account" / "series" / "parts")):
        client._finalize_event(event_id="call-2", status="succeeded", feature="extract",
                               model_alias="gemini", latency_ms=10, usage=usage, operation="text")
    assert sponsored_budget.spent_today_usd(volume) > 0
    before = sponsored_budget.spent_today_usd(volume)
    with ai_request_context(user_id="u", job_id="job", workspace_id=str(volume / "account")):
        client._finalize_event(event_id="call-3", status="succeeded", feature="extract",
                               model_alias="gemini", latency_ms=10, usage=usage, operation="text")
    assert sponsored_budget.spent_today_usd(volume) == before  # the author's own calls are not sponsored spend


def test_sponsored_images_never_reach_a_cash_route(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "production")
    monkeypatch.delenv("CANARY_SPONSORED_GRANT_ROUTES_ONLY", raising=False)

    async def forbidden():
        pytest.fail("a cash route was submitted")

    async def openai_chain():
        return await image_route_fallback._run_openai_first(
            primary=forbidden, backup=forbidden, surface="asset", request_key="k",
            estimate_openai_usd=lambda: 0.05)

    async def runware_down():
        raise __import__("httpx").ConnectError("down")

    image_route_fallback.RUNWARE_CIRCUIT.reset()
    with ai_request_context(user_id="u", sponsor="cold_open"):
        with pytest.raises(sponsored_budget.SponsoredRouteUnavailable):
            asyncio.run(openai_chain())
        # Runware first: its failure stops the job instead of moving to OpenAI.
        with pytest.raises(sponsored_budget.SponsoredRouteUnavailable):
            asyncio.run(image_route_fallback._run_runware_first(
                primary=runware_down, backup=openai_chain, surface="asset", request_key="k"))
    image_route_fallback.RUNWARE_CIRCUIT.reset()
    monkeypatch.setenv("CANARY_ENV", "development")
    assert not sponsored_budget.grant_routes_only()


def test_a_sponsored_stage_holds_no_credits(tmp_path, monkeypatch):
    from novel_to_comic.ai.context import current_ai_request_context
    from novel_to_comic.server import credited_job

    held = []
    monkeypatch.setattr(credited_job, "get_db", lambda: object())
    monkeypatch.setattr(credited_job, "classify_operations", lambda ops: None)
    monkeypatch.setattr(credited_job, "stage_operations", lambda config, stage: ())
    monkeypatch.setattr(credited_job, "estimate_stage_credit_reservation",
                        lambda *a: pytest.fail("a sponsored stage is not priced against the author"))
    monkeypatch.setattr(credited_job, "reserve_credits",
                        lambda db, user, project, stage, amount, **kw: held.append(amount) or (None, "job"))
    monkeypatch.setattr(credited_job, "assert_reservation_active", lambda *a: None)
    seen = []

    async def run():
        seen.append(current_ai_request_context().sponsor)

    asyncio.run(credited_job.run_credited_stage(
        user_id="u", project_id="p", project_dir=tmp_path, config=Config(), state=None,
        stage="extract", run=run, sponsor="cold_open"))
    assert held == [0] and seen == ["cold_open"]


def test_one_free_opening_per_person_not_per_account(tmp_path, monkeypatch):
    volume, part = _free_opening(tmp_path, monkeypatch)
    other = create_part_workspace(volume / "second-account" / "series", "part_0001")
    ask = lambda part_dir, **who: cold_open_jobs.free_opening_sponsor(  # noqa: E731
        part_dir, _extract_state(), "project", "extract", claim=True, applicant=_applicant(**who))

    assert cold_open_jobs.free_opening_sponsor(part, _extract_state(), "project", "extract", claim=True) is None
    assert ask(part, verified=False) is None
    assert ask(part, email=None) is None
    assert ask(part, email="mara@mailinator.com") is None
    assert not (volume / "account" / cold_open_jobs.GRANTS_FILE).exists()
    assert ask(part, email="M.a.ra+comics@googlemail.com") == "cold_open"
    # A second account: the same mailbox, then the same manuscript, are refused.
    assert ask(other, email="mara@gmail.com", ip="198.51.100.2") is None
    assert ask(other, email="someone@example.org", ip="198.51.100.2") is None
    monkeypatch.setattr("novel_to_comic.stages.s1_extract.source_text", lambda *_: "A different story begins here.")
    assert ask(other, email="someone@example.org", ip="198.51.100.2") == "cold_open"
    assert not (volume / "second-account" / free_opening_guard.CLAIMS_FILE).exists()
    stored = (volume / free_opening_guard.CLAIMS_FILE).read_text()
    assert "gmail" not in stored and "198.51" not in stored  # digests only


def test_free_opening_decisions_reach_analytics_once(tmp_path, monkeypatch):
    from novel_to_comic.server import product_events

    events = []
    monkeypatch.setattr(product_events, "capture_server_event",
                        lambda name, **kw: events.append((name, kw["user_id"], kw["properties"])))
    monkeypatch.setattr(cold_open_jobs, "_REPORTED", set())
    volume, part = _free_opening(tmp_path, monkeypatch)
    other = create_part_workspace(volume / "second-account" / "series", "part_0001")
    ask = lambda part_dir, claim=False, **who: cold_open_jobs.free_opening_sponsor(  # noqa: E731
        part_dir, _extract_state(), "project", "extract", claim=claim, applicant=_applicant(**who))

    assert ask(part, claim=True) == "cold_open"
    assert ask(part, claim=True) == "cold_open"  # a retry is not a second grant
    # The same manuscript on a second account, asked about on every estimate refresh.
    assert ask(other, email="someone@example.org") is None
    assert ask(other, email="someone@example.org") is None
    assert events == [
        ("free_opening_granted", "account", {"characters": 9000, "max_characters": 20000}),
        ("free_opening_refused", "second-account", {"reason": "opening_already_drawn", "at": "estimate",
                                                    "characters": 9000, "max_characters": 20000}),
    ]
    for name, _, properties in events:  # the analytics allowlist accepts them
        product_events._clean_properties(name, properties, source="server")
    events.clear()
    monkeypatch.setenv("CANARY_FREE_OPENING_MAX_CHARS", "100")
    assert ask(other, email="someone@example.org") is None
    assert events[0][2]["reason"] == "too_long"


def test_an_address_claims_two_free_openings_a_day(tmp_path, monkeypatch):
    volume, _ = _free_opening(tmp_path, monkeypatch)
    for index, expected in enumerate((None, None, "address_limit")):
        applicant = _applicant(email=f"author{index}@example.com")
        assert free_opening_guard.claim(volume, f"account-{index}", applicant, f"Story number {index}.",
                                        commit=True) == expected
    assert free_opening_guard.claim(volume, "account-9", _applicant(email="x@example.com", ip=None),
                                    "Another story.", commit=False) is None
    monkeypatch.setattr(sponsored_budget, "_today", lambda: "2999-01-01")
    assert free_opening_guard.claim(volume, "account-3", _applicant(email="late@example.com"),
                                    "Tomorrow's story.", commit=True) is None


def test_email_and_opening_normalization(monkeypatch):
    normalize = free_opening_guard.normalize_email
    assert normalize(" Jo.Hn+x@GMail.com ") == normalize("john@googlemail.com") == "john@gmail.com"
    assert normalize("jo.hn+x@example.com") == "jo.hn@example.com"
    assert normalize("not-an-address") is None and normalize("+tag@example.com") is None
    assert free_opening_guard.is_disposable("a@sub.yopmail.com")
    assert not free_opening_guard.is_disposable("a@example.com")
    monkeypatch.setenv("CANARY_DISPOSABLE_EMAIL_DOMAINS", "example.com, ")
    assert free_opening_guard.is_disposable("a@example.com")
    fingerprint = free_opening_guard.opening_fingerprint
    assert fingerprint("The bell rang.  Mara ran!") == fingerprint("the bell rang\nmara ran")
    assert fingerprint("The bell rang.") != fingerprint("The bell sang.")


def test_token_identity_reads_the_authenticated_request():
    import jwt

    from novel_to_comic.server.auth import token_identity

    def request(claims=None, header=None):
        token = jwt.encode(claims, "k" * 32, algorithm="HS256") if claims is not None else ""
        return SimpleNamespace(headers={"authorization": header if header is not None else f"Bearer {token}"})

    assert token_identity(request({"sub": "u", "email": "a@example.com"})) == ("a@example.com", True)
    assert token_identity(request({"sub": "u", "email": "a@example.com",
                                   "user_metadata": {"email_verified": False}})) == ("a@example.com", False)
    assert token_identity(request({"sub": "u"})) == (None, False)
    assert token_identity(request(header="")) == (None, False)
    assert token_identity(request(header="Bearer nonsense")) == (None, False)


def test_the_operator_can_close_the_cash_routes_to_all_image_work(monkeypatch):
    monkeypatch.setenv("CANARY_ENV", "development")
    monkeypatch.delenv("CANARY_IMAGE_CASH_ROUTES_DISABLED", raising=False)
    calls = []

    async def openai():
        calls.append("openai")
        return "image"

    async def chain():
        return await image_route_fallback._run_openai_first(
            primary=openai, backup=openai, surface="draw", request_key="k", estimate_openai_usd=lambda: 0.05)

    image_route_fallback.OPENAI_SUNBURST_CIRCUIT.reset()
    with ai_request_context(user_id="u"):  # the author's own paid work
        assert asyncio.run(chain())[:2] == ("image", "openai")
        monkeypatch.setenv("CANARY_IMAGE_CASH_ROUTES_DISABLED", "true")
        with pytest.raises(sponsored_budget.SponsoredRouteUnavailable):
            asyncio.run(chain())
    assert calls == ["openai"]
