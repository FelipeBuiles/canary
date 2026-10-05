"""The author edits the series Story Bible: edit, add, remove, merge and looks."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from novel_to_comic import artifacts
from novel_to_comic.cast_design import CastDesignPlan, CharacterDesign, character_fingerprint, current_designs
from novel_to_comic.config import Config, save_config
from novel_to_comic.models.adaptation import (
    AdaptationLedgerEntry, AdaptedBeat, BookAdaptation, LetteringItem, NarrativeTreatment,
)
from novel_to_comic.models.appearance import AppearanceState, StateActivation, StoryPosition
from novel_to_comic.models.story_bible import (
    Character, CharacterRelationship, ExcludedEntity, Location, Prop, Scene, StoryBible,
)
from novel_to_comic.server import deps
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.routers import projects
from novel_to_comic.stages import s3_cast
from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state
from novel_to_comic.story_bible_edits import (
    EditRejected,
    add_entity,
    add_state,
    edit_entity,
    merge_entities,
    possible_duplicates,
    remove_entity,
    remove_state,
    restore_excluded,
)
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import part_workspace
from tests.queue_fixtures import create_app


def _character(identifier: str, name: str, anchor: str, scene: str = "scene_001", **extra) -> Character:
    return Character(
        id=identifier, name=name, visual_anchor=anchor, age_range="adult", gender="female",
        distinguishing_features=[], default_outfit="grey coat", first_appearance_scene=scene, **extra,
    )


def _scene(identifier: str, part_id: str, location: str, characters: list[str]) -> Scene:
    return Scene(
        id=identifier, part_id=part_id, chapter=1, title=identifier, location_id=location,
        character_ids=characters, summary="Something happens.", scene_type="dialogue",
        narrative_beat="setup", source_start_quote="The lighthouse", source_start_offset=0,
    )


def _bible() -> StoryBible:
    return StoryBible(
        title="Lighthouse", author="Test", total_scenes=3,
        characters=[
            _character("char_001", "Mara", "short black hair, tall, grey coat",
                       relationships=[CharacterRelationship(character_id="char_002", relationship="sister")]),
            _character("char_002", "Ines", "long red hair, freckles"),
            _character("char_003", "Ines Vale", "long red hair, freckles", scene="scene_003",
                       appearance_states=[AppearanceState(id="wet", label="Soaked", visual_anchor="long red hair, soaked")],
                       appearance_timeline=[StateActivation(state_id="wet", at=StoryPosition(scene_id="scene_003"))]),
        ],
        locations=[
            Location(id="loc_001", name="Lamp room", visual_anchor="glass lamp room", mood="calm"),
            Location(id="loc_002", name="The lamp room", visual_anchor="glass lamp room", mood="calm"),
        ],
        props=[Prop(id="prop_001", name="Brass key", visual_anchor="small brass key")],
        scenes=[
            _scene("scene_001", "part_0001", "loc_001", ["char_001", "char_002"]),
            _scene("scene_002", "part_0001", "loc_001", ["char_001"]),
            _scene("scene_003", "part_0002", "loc_002", ["char_003"]),
        ],
        sequences=[],
    )


# ---------------------------------------------------------------------------
# Pure edits
# ---------------------------------------------------------------------------


def test_an_edit_changes_only_editable_details() -> None:
    edited = edit_entity(_bible(), "characters", "char_001",
                         {"name": "  Mara   Holt ", "aliases": ["Mara", "the keeper", "The Keeper"]})
    mara = edited.characters[0]
    assert (mara.name, mara.aliases) == ("Mara Holt", ["Mara", "the keeper"])

    with pytest.raises(EditRejected, match="can't be edited"):
        edit_entity(_bible(), "characters", "char_001", {"id": "other"})
    with pytest.raises(EditRejected, match="physical description"):
        edit_entity(_bible(), "characters", "char_001", {"visual_anchor": " "})
    with pytest.raises(EditRejected, match="another character"):
        edit_entity(_bible(), "characters", "char_001",
                    {"relationships": [{"character_id": "char_001", "relationship": "self"}]})
    with pytest.raises(KeyError):
        edit_entity(_bible(), "props", "prop_404", {"name": "x"})


def test_added_entities_join_only_scenes_that_can_still_change() -> None:
    bible = _bible()
    bible.excluded_entities.append(ExcludedEntity(kind="character", name="Old Tom"))
    added, entity_id = add_entity(
        bible, "characters", {"name": "Old Tom", "visual_anchor": "white beard, oilskin coat"},
        ["scene_003"], editable={"scene_003"},
    )
    tom = next(c for c in added.characters if c.id == entity_id)
    assert entity_id == "author_char_001" and tom.origin == "author"
    assert tom.first_appearance_scene == "scene_003"
    assert entity_id in added.scenes[2].character_ids
    assert added.excluded_entities == []  # re-adding a removed name lifts the removal

    with pytest.raises(EditRejected, match="already adapted"):
        add_entity(_bible(), "characters", {"name": "X", "visual_anchor": "x"}, ["scene_001"], editable={"scene_003"})
    with pytest.raises(EditRejected, match="at least one scene"):
        add_entity(_bible(), "characters", {"name": "X", "visual_anchor": "x"}, [], editable=set())
    _bible_with_prop, prop_id = add_entity(_bible(), "props", {"name": "Lantern", "visual_anchor": "tin lantern"},
                                           [], editable=set())
    assert prop_id == "author_prop_001"


def test_removal_keeps_extraction_from_recreating_the_name() -> None:
    removed = remove_entity(_bible(), "characters", "char_002")
    assert [c.id for c in removed.characters] == ["char_001", "char_003"]
    assert removed.scenes[0].character_ids == ["char_001"]
    assert removed.characters[0].relationships == []
    assert [(e.kind, e.name) for e in removed.excluded_entities] == [("character", "Ines")]
    assert restore_excluded(removed, "characters", "ines").excluded_entities == []

    with pytest.raises(EditRejected, match="Merge it into another place"):
        remove_entity(_bible(), "locations", "loc_001")


def test_restoring_a_removed_entry_brings_it_back_whole() -> None:
    # A new author entry never takes a removed entry's id: its Cast images stay its own.
    added, tom = add_entity(_bible(), "characters", {"name": "Tom", "visual_anchor": "white beard"},
                            ["scene_003"], editable={"scene_003"})
    _, new_id = add_entity(remove_entity(added, "characters", tom), "characters",
                           {"name": "Old Tom", "visual_anchor": "white beard"}, ["scene_003"], editable={"scene_003"})
    assert (tom, new_id) == ("author_char_001", "author_char_002")

    removed = remove_entity(_bible(), "characters", "char_002")
    restored = restore_excluded(removed, "characters", "Ines")
    ines = next(c for c in restored.characters if c.id == "char_002")
    assert ines.visual_anchor == "long red hair, freckles"
    assert "char_002" in restored.scenes[0].character_ids
    assert restored.characters[0].relationships == [CharacterRelationship(character_id="char_002", relationship="sister")]
    assert restored.excluded_entities == []

    renamed = edit_entity(removed, "characters", "char_003", {"aliases": ["Ines"]})
    with pytest.raises(EditRejected, match="already uses that name"):
        restore_excluded(renamed, "characters", "Ines")


def test_possible_duplicates_pair_shared_and_contained_names() -> None:
    pairs = possible_duplicates(_bible(), {})
    assert {(p["kind"], tuple(p["ids"]), p["reason"]) for p in pairs} == {
        ("characters", ("char_002", "char_003"), "name_within"),
        ("locations", ("loc_001", "loc_002"), "same_name"),
    }
    # Both cited: neither can be merged away, so it isn't suggested.
    assert all(p["kind"] != "characters" for p in possible_duplicates(_bible(), {"char_002": ["P"], "char_003": ["P"]}))


def test_merging_folds_scenes_looks_and_names_into_the_kept_entry() -> None:
    merged = merge_entities(_bible(), "characters", "char_003", "char_002")
    ines = next(c for c in merged.characters if c.id == "char_002")
    assert "char_003" not in {c.id for c in merged.characters}
    assert ines.aliases == ["Ines Vale"]
    assert [s.id for s in ines.appearance_states] == ["wet"]
    assert ines.appearance_timeline[0].at.scene_id == "scene_003"
    assert merged.scenes[2].character_ids == ["char_002"]
    assert ines.first_appearance_scene == "scene_001"

    places = merge_entities(_bible(), "locations", "loc_002", "loc_001")
    assert [loc.id for loc in places.locations] == ["loc_001"]
    assert places.scenes[2].location_id == "loc_001"
    assert places.locations[0].aliases == ["The lamp room"]


def test_looks_take_ids_from_their_labels_and_can_start_at_a_scene() -> None:
    bible, state_id = add_state(_bible(), "characters", "char_001",
                                {"label": "Storm gear", "visual_anchor": "short black hair, yellow oilskins"},
                                "scene_002")
    mara = bible.characters[0]
    assert state_id == "storm_gear"
    assert mara.appearance_states[0].visually_significant is True
    assert mara.appearance_timeline[0].at.scene_id == "scene_002"
    again, second = add_state(bible, "characters", "char_001",
                              {"label": "Storm gear", "visual_anchor": "short black hair, wet oilskins"}, None)
    assert second == "storm_gear_2"
    cleared = remove_state(again, "characters", "char_001", "storm_gear")
    assert [s.id for s in cleared.characters[0].appearance_states] == ["storm_gear_2"]
    assert cleared.characters[0].appearance_timeline == []


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


def _adaptation_citing(entity_ids: tuple[str, ...]) -> BookAdaptation:
    return BookAdaptation(
        revision=1, source_sha256="s" * 64, brief_revision=1, brief_sha256="b" * 64,
        treatment=NarrativeTreatment(causal_spine=["The light goes out."]),
        beats=[AdaptedBeat(
            id="beat-1", order=1, summary="The light goes out.", narrative_function="initial",
            source_unit_ids=["source_000001"], entity_ids=entity_ids,
            lettering=[LetteringItem(id="l-1", kind="caption", text="Dark.", source_unit_ids=["source_000001"])],
        )],
        ledger=[AdaptationLedgerEntry(source_unit_id="source_000001", disposition="caption",
                                      adapted_beat_ids=["beat-1"], preserved_function="The light goes out.")],
    )


@pytest.fixture
def series(tmp_path, monkeypatch):
    root = tmp_path / "account" / "book"
    (root / "input").mkdir(parents=True)
    (root / "input" / "novel.txt").write_text("The lighthouse kept its light. " * 20)
    save_config(Config(), root)
    save_state(create_initial_state("Lighthouse", str(root / "input" / "novel.txt")), root)
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = (
        SimpleNamespace(data=[{"name": "book", "share_token": None, "is_public": False}])
    )
    monkeypatch.setattr(deps, "get_db", lambda: db)
    monkeypatch.setattr(projects, "get_db", lambda: db)
    monkeypatch.setattr(deps, "account_config", lambda config, *_args: config)
    app = create_app(tmp_path)
    app.dependency_overrides[get_current_user] = lambda: "account"
    client = TestClient(app)
    client.event_hooks["request"].append(lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4())))
    assert client.get("/api/projects/pid/status").status_code == 200  # migrates into part_0001
    assert client.post("/api/projects/pid/parts", data={"text": "The storm came. " * 20}).status_code == 200
    artifacts.write_story_bible(root, _bible())
    return client, root


def test_edits_are_revision_checked_and_bump_the_revision(series) -> None:
    client, root = series
    stale = client.patch("/api/projects/pid/story-bible/characters/char_001",
                         json={"expected_revision": 7, "changes": {"name": "Mara Holt"}})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_story_bible"

    saved = client.patch("/api/projects/pid/story-bible/characters/char_001",
                         json={"expected_revision": 1, "changes": {"name": "Mara Holt"}})
    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert artifacts.read_story_bible(root).characters[0].name == "Mara Holt"
    assert client.patch("/api/projects/pid/story-bible/characters/char_404",
                        json={"expected_revision": 2, "changes": {"name": "X"}}).status_code == 404
    assert client.patch("/api/projects/pid/story-bible/creatures/char_001",
                        json={"expected_revision": 2, "changes": {"name": "X"}}).status_code == 422


def test_adapted_parts_keep_what_they_cite(series) -> None:
    client, root = series
    TargetArtifacts(part_workspace(root, "part_0001")).write_adaptation(_adaptation_citing(("char_002",)))

    editor = client.get("/api/projects/pid/story-bible/editor").json()
    assert editor["citations"]["char_002"] == ["Part 1"]
    assert editor["editable_scene_ids"] == ["scene_003"]  # part 1 is adapted
    assert [part["id"] for part in editor["parts"]] == ["part_0001", "part_0002"]

    refused = client.delete("/api/projects/pid/story-bible/characters/char_002?expected_revision=1")
    assert refused.status_code == 409
    assert refused.json()["detail"] == {
        "code": "entity_cited", "parts": ["Part 1"],
        "message": "Can't remove it: Part 1 uses it. Restart those parts' adaptation first, or edit it instead.",
    }
    assert client.post("/api/projects/pid/story-bible/characters/char_002/merge",
                       json={"expected_revision": 1, "into": "char_003"}).status_code == 409
    # The cited entry can absorb an uncited duplicate, and can still be edited.
    merged = client.post("/api/projects/pid/story-bible/characters/char_003/merge",
                         json={"expected_revision": 1, "into": "char_002"})
    assert merged.status_code == 200
    assert client.patch("/api/projects/pid/story-bible/characters/char_002",
                        json={"expected_revision": 2, "changes": {"visual_anchor": "long auburn hair"}}).status_code == 200


def test_new_entities_and_looks_reopen_an_approved_cast(series) -> None:
    client, root = series
    state = load_state(root)
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["cast"].status = StageStatus.COMPLETE
    save_state(state, root)

    added = client.post("/api/projects/pid/story-bible/characters", json={
        "expected_revision": 1, "scene_ids": ["scene_003"],
        "details": {"name": "Old Tom", "visual_anchor": "white beard, oilskin coat"},
    })
    assert added.status_code == 200 and added.json()["entity_id"] == "author_char_001"
    assert load_state(root).stages["cast"].status == StageStatus.PENDING

    edited = client.patch("/api/projects/pid/story-bible/props/prop_001",
                          json={"expected_revision": 2, "changes": {"visual_anchor": "large iron key"}})
    assert edited.status_code == 200
    look = client.post("/api/projects/pid/story-bible/props/prop_001/states", json={
        "expected_revision": 3, "details": {"label": "Rusted", "visual_anchor": "large iron key, rusted"},
    })
    assert look.json()["state_id"] == "rusted"
    assert client.delete(
        "/api/projects/pid/story-bible/props/prop_001/states/rusted?expected_revision=4").status_code == 200
    assert client.delete("/api/projects/pid/story-bible/excluded/characters/nobody?expected_revision=5").status_code == 404


def test_no_edit_can_blank_a_visual_anchor(series) -> None:
    client, root = series
    refused = client.patch("/api/projects/pid/story-bible/characters/char_003/states/wet",
                           json={"expected_revision": 1, "changes": {"visual_anchor": " "}})
    assert refused.status_code == 422
    assert refused.json()["detail"] == "Add a visual anchor for: Ines Vale (char_003:wet)"
    assert client.patch("/api/projects/pid/story-bible/characters/char_001",
                        json={"expected_revision": 1, "changes": {"visual_anchor": ""}}).status_code == 422
    assert artifacts.read_story_bible(root).revision == 1


def test_cast_override_promotes_an_incidental_identity_and_reopens_cast(series) -> None:
    client, root = series
    from novel_to_comic.cast_roster import cast_character_ids
    state = load_state(root)
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["cast"].status = StageStatus.COMPLETE
    save_state(state, root)
    assert "char_003" not in cast_character_ids(artifacts.read_story_bible(root), root)

    saved = client.patch("/api/projects/pid/story-bible/characters/char_003", json={
        "expected_revision": 1, "changes": {"cast_required": True},
    })

    assert saved.status_code == 200 and saved.json()["revision"] == 2
    assert "char_003" in cast_character_ids(artifacts.read_story_bible(root), root)
    assert load_state(root).stages["cast"].status == StageStatus.PENDING
    assert artifacts.read_story_bible(root).characters[2].visual_anchor == "long red hair, freckles"


def test_a_blank_anchor_is_filled_once_in_the_series_bible(series) -> None:
    client, root = series
    bible = artifacts.read_story_bible(root)
    # Extractions from before anchors were required can leave them blank.
    bible.props[0].visual_anchor = " "
    bible.characters[2].appearance_states[0].visual_anchor = ""
    artifacts.write_story_bible(root, bible)
    fill = "/api/projects/pid/story-bible/visual-anchor"

    state = load_state(root)
    state.stages["cast"].status = StageStatus.RUNNING
    save_state(state, root)
    assert client.post(fill, json={"entity_id": "prop_001", "visual_anchor": "small brass key"}).status_code == 409
    state.stages["cast"].status = StageStatus.AWAITING_REVIEW
    save_state(state, root)

    filled = client.post(fill, json={"entity_id": "prop_001", "visual_anchor": "  small brass key "})
    assert filled.status_code == 200
    assert filled.json()["revision"] == 2
    assert filled.json()["missing_visual_anchors"] == ["Ines Vale (char_003:wet)"]
    look = client.post(fill, json={
        "entity_id": "char_003", "appearance_state_id": "wet", "visual_anchor": "long red hair, soaked",
    })
    assert look.json()["missing_visual_anchors"] == []
    saved = artifacts.read_story_bible(root)
    assert (saved.props[0].visual_anchor, saved.revision) == ("small brass key", 3)
    assert load_state(root).stages["cast"].status == StageStatus.AWAITING_REVIEW

    # Existing anchors stay verbatim, and an editor loaded before the fill reloads.
    assert client.post(fill, json={"entity_id": "prop_001", "visual_anchor": "iron key"}).status_code == 409
    assert client.post(fill, json={"entity_id": "loc_001", "visual_anchor": "   "}).status_code == 422
    assert client.post(fill, json={"entity_id": "prop_404", "visual_anchor": "x"}).status_code == 404
    stale = client.patch("/api/projects/pid/story-bible/props/prop_001",
                         json={"expected_revision": 1, "changes": {"name": "Key"}})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "stale_story_bible"
    # The Story Bible belongs to the series: no part route writes it (only the
    # web app's static mount matches, and it refuses POST).
    assert client.post("/api/projects/pid/parts/part_0001/story-bible/visual-anchor",
                       json={"entity_id": "prop_001", "visual_anchor": "x"}).status_code in {404, 405}


def test_drafting_reads_only_passages_that_name_the_entity(series, monkeypatch) -> None:
    client, root = series
    from novel_to_comic import entity_drafting
    from novel_to_comic.server import credited_job

    from novel_to_comic.source_extraction import SourceSceneAnchor, build_source_document

    for workspace, text in ((part_workspace(root, "part_0001"), "Calm water. " * 200),
                            (part_workspace(root, "part_0002"), "Calm water. " * 200 + "Old Tom waved. " + "Rain. " * 200)):
        anchor = SourceSceneAnchor(id="scene_x", title="x", opening_quote="Calm water.", start_offset=0)
        TargetArtifacts(workspace).write_source(build_source_document(text, (anchor,)))
    bible = artifacts.read_story_bible(root)
    bible.scenes[2].source_start_offset = 0
    artifacts.write_story_bible(root, bible)

    seen = {}

    async def generate_json(**kwargs):
        seen["request"] = json.loads(kwargs["user_content"])
        return SimpleNamespace(value={
            "visual_anchor": "white beard, oilskin coat", "age_range": "70s", "gender": "male",
            "distinguishing_features": ["white beard"], "default_outfit": "oilskin coat",
        })

    async def run_credited_call(**kwargs):
        seen["stage"] = kwargs["stage"]
        return await kwargs["work"]()

    monkeypatch.setattr(entity_drafting.text, "generate_json", generate_json)
    monkeypatch.setattr(credited_job, "run_credited_call", run_credited_call)

    estimate = client.get("/api/projects/pid/story-bible/characters/draft-estimate", params={"name": "Old Tom"}).json()
    assert estimate["mentioned"] is True and estimate["estimate"]["estimate_credits"] >= 1
    assert estimate["mentioned_scene_ids"] == ["scene_003"]
    assert client.get("/api/projects/pid/story-bible/characters/draft-estimate",
                      params={"name": "Captain Ahab"}).json()["mentioned"] is False

    drafted = client.post("/api/projects/pid/story-bible/characters/draft", json={"name": "old tom"})
    assert drafted.status_code == 200, drafted.text
    body = drafted.json()
    assert body["details"]["visual_anchor"] == "white beard, oilskin coat"
    assert body["suggested_scene_ids"] == ["scene_003"]
    assert seen["stage"] == "extract"
    assert len(seen["request"]["passages"]) == 1 and "Old Tom waved." in seen["request"]["passages"][0]
    assert len(seen["request"]["passages"][0]) < 1600
    missing = client.post("/api/projects/pid/story-bible/characters/draft", json={"name": "Captain Ahab"})
    assert missing.status_code == 422
    assert artifacts.read_story_bible(root).revision == 1  # drafting saves nothing


# ---------------------------------------------------------------------------
# References after edits
# ---------------------------------------------------------------------------


def _cast_project(tmp_path):
    suggestion = {"template": "Follow this sample's rough ink and ochre palette."}
    config = Config(image_model="image-gemini-pro", style_template=style_template_for_suggestion(suggestion))
    bible = _bible()
    bible.characters[0].appearance_states = [
        AppearanceState(id="storm", label="Storm gear", visual_anchor="short black hair, oilskins",
                        visually_significant=True),
    ]
    artifacts.write_story_bible(tmp_path, bible)
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples/style_suggestions.json").write_text(json.dumps({"suggestions": [suggestion]}))
    Image.new("RGB", (32, 40), "orange").save(tmp_path / "samples/style_1.png")
    TargetArtifacts(tmp_path).write_cast_design(CastDesignPlan(
        characters=[CharacterDesign(character_id=c.id, face=f"{c.id} face", hair=f"{c.id} hair",
                                    silhouette=f"{c.id} build", posture="resting", wardrobe="coat",
                                    contrast="distinct") for c in bible.characters],
        fingerprints={c.id: character_fingerprint(config, c) for c in bible.characters},
    ))
    design = s3_cast.read_design(config, tmp_path, bible)
    builder = s3_cast._ReferenceRequests(config, tmp_path, bible, design)
    for kind, entity, appearance in s3_cast._reference_items(bible):
        path = builder.path(kind, entity, appearance)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (16, 16), "gray").save(path)
        request = builder.request(kind, entity, appearance)
        artifacts.write_asset_meta(path, {"provenance": {"execution_fingerprint": request.wire.execution_fingerprint}})
    return config, bible


def _statuses(config, root) -> dict:
    return {(item["entity_id"], item["state_id"]): item["status"] for item in s3_cast.reference_freshness(config, root)}


def test_a_changed_description_flags_only_that_entitys_references_until_kept(tmp_path) -> None:
    config, bible = _cast_project(tmp_path)
    assert set(_statuses(config, tmp_path).values()) == {"current"}

    artifacts.write_story_bible(tmp_path, edit_entity(bible, "characters", "char_002",
                                                      {"visual_anchor": "long auburn hair, freckles"}))
    statuses = _statuses(config, tmp_path)
    assert statuses[("char_002", None)] == "outdated"
    assert {key for key, value in statuses.items() if value != "current"} == {("char_002", None)}

    s3_cast.keep_current_reference(config, tmp_path, "characters", "char_002")
    assert set(_statuses(config, tmp_path).values()) == {"current"}
    assert "char_002" in current_designs(config, tmp_path, artifacts.read_story_bible(tmp_path))
    with pytest.raises(KeyError):
        s3_cast.keep_current_reference(config, tmp_path, "characters", "char_404")


def test_a_rename_carries_current_references_over(tmp_path) -> None:
    config, bible = _cast_project(tmp_path)
    renamed = edit_entity(bible, "characters", "char_001", {"name": "Mara Holt"})
    renamed = edit_entity(renamed, "locations", "loc_001", {"name": "The lantern"})
    artifacts.write_story_bible(tmp_path, renamed)
    stale = {key for key, value in _statuses(config, tmp_path).items() if value != "current"}
    assert stale == {("char_001", None), ("char_001", "storm"), ("loc_001", None)}

    assert s3_cast.carry_over_references(config, tmp_path, bible, renamed, "characters", "char_001") == 2
    assert s3_cast.carry_over_references(config, tmp_path, bible, renamed, "locations", "loc_001") == 1
    assert set(_statuses(config, tmp_path).values()) == {"current"}
    # A changed look is never carried over.
    changed = edit_entity(renamed, "props", "prop_001", {"visual_anchor": "large iron key"})
    artifacts.write_story_bible(tmp_path, changed)
    assert s3_cast.carry_over_references(config, tmp_path, renamed, changed, "props", "prop_001") == 0
    assert _statuses(config, tmp_path)[("prop_001", None)] == "outdated"


def test_cast_reopens_only_for_references_that_are_not_current(series) -> None:
    client, root = series
    references = client.get("/api/projects/pid/cast/freshness").json()["references"]
    assert {item["status"] for item in references} == {"missing"}
    assert client.post("/api/projects/pid/cast/references/keep",
                       json={"kind": "props", "entity_id": "prop_001"}).status_code == 409
    assert client.post("/api/projects/pid/cast/references/keep",
                       json={"kind": "props", "entity_id": "prop_404"}).status_code == 404

    assert client.post("/api/projects/pid/cast/reopen").status_code == 409  # Cast never ran
    state = load_state(root)
    state.stages["cast"].status = StageStatus.COMPLETE
    save_state(state, root)
    reopened = client.post("/api/projects/pid/cast/reopen")
    assert reopened.status_code == 200 and reopened.json()["reopened"] is True
    assert load_state(root).stages["cast"].status == StageStatus.PENDING


def test_reference_form_edits_are_conservative():
    from novel_to_comic.story_bible_edits import edit_state

    bible = _bible()
    edited = edit_entity(bible, "characters", "char_001", {"reference_form": "form"})
    assert edited.characters[0].reference_form == "form"
    with pytest.raises(ValueError, match="only for identity_kind 'group'"):
        edit_entity(bible, "characters", "char_001", {"reference_form": "formation"})

    misted = edit_state(bible, "characters", "char_003", "wet", {"reference_form": "form"})
    assert misted.characters[2].appearance_states[0].reference_form == "form"
    with pytest.raises(EditRejected, match="only for a group"):
        edit_state(bible, "characters", "char_003", "wet", {"reference_form": "formation"})
    flooded, state_id = add_state(bible, "locations", "loc_001", {"label": "Flooded", "visual_anchor": "flooded glass room"}, None)
    with pytest.raises(EditRejected, match="Only a character's look"):
        edit_state(flooded, "locations", "loc_001", state_id, {"reference_form": "form"})


def test_the_newest_edit_can_be_undone_until_something_else_changes(series) -> None:
    client, root = series
    assert client.get("/api/projects/pid/story-bible/editor").json()["undo"] is None
    merged = client.post("/api/projects/pid/story-bible/characters/char_003/merge",
                         json={"expected_revision": 1, "into": "char_002"})
    assert merged.status_code == 200
    editor = client.get("/api/projects/pid/story-bible/editor").json()
    assert editor["undo"] == {"blocked": None, "change": {
        "action": "merge", "kind": "characters", "entity_id": "char_003", "name": "Ines Vale", "into": "Ines"}}

    assert client.post("/api/projects/pid/story-bible/undo", json={"expected_revision": 1}).status_code == 409
    undone = client.post("/api/projects/pid/story-bible/undo", json={"expected_revision": 2})
    assert undone.status_code == 200 and undone.json()["undone"]["action"] == "merge"
    bible = artifacts.read_story_bible(root)
    assert bible.revision == 3 and [c.id for c in bible.characters] == ["char_001", "char_002", "char_003"]
    assert client.get("/api/projects/pid/story-bible/editor").json()["undo"] is None

    # Edits undo newest first; anything else writing the Bible ends the chain.
    client.patch("/api/projects/pid/story-bible/props/prop_001", json={"expected_revision": 3, "changes": {"name": "Key"}})
    client.patch("/api/projects/pid/story-bible/props/prop_001", json={"expected_revision": 4, "changes": {"name": "Old key"}})
    assert client.post("/api/projects/pid/story-bible/undo", json={"expected_revision": 5}).status_code == 200
    assert artifacts.read_story_bible(root).props[0].name == "Key"
    bible = artifacts.read_story_bible(root)
    bible.props[0].aliases = ["the key"]
    artifacts.write_story_bible(root, bible)
    refused = client.post("/api/projects/pid/story-bible/undo", json={"expected_revision": 6})
    assert refused.status_code == 422 and "no edit to undo" in refused.json()["detail"]


def test_undo_never_takes_away_what_an_adapted_part_cites(series) -> None:
    client, root = series
    added = client.post("/api/projects/pid/story-bible/characters", json={
        "expected_revision": 1, "scene_ids": ["scene_003"],
        "details": {"name": "Old Tom", "visual_anchor": "white beard, oilskin coat"},
    })
    assert added.status_code == 200
    TargetArtifacts(part_workspace(root, "part_0002")).write_adaptation(_adaptation_citing(("author_char_001",)))
    assert client.get("/api/projects/pid/story-bible/editor").json()["undo"]["blocked"]
    assert client.post("/api/projects/pid/story-bible/undo", json={"expected_revision": 2}).status_code == 409


def test_removed_entries_come_back_through_restore(series) -> None:
    client, root = series
    assert client.delete("/api/projects/pid/story-bible/characters/char_002?expected_revision=1").status_code == 200
    restored = client.delete("/api/projects/pid/story-bible/excluded/characters/Ines?expected_revision=2")
    assert restored.status_code == 200
    bible = artifacts.read_story_bible(root)
    assert "char_002" in {c.id for c in bible.characters} and "char_002" in bible.scenes[0].character_ids


def test_impact_previews_what_a_merge_or_removal_changes(series) -> None:
    client, root = series
    merge = client.get("/api/projects/pid/story-bible/characters/char_003/impact",
                       params={"action": "merge", "into": "char_002"}).json()
    assert merge["blocked"] is None
    assert [scene["id"] for scene in merge["scenes"]] == ["scene_003"]
    assert merge["looks"] == ["Soaked"] and merge["aliases"] == ["Ines Vale"]
    assert merge["cast_images"] == 0

    remove = client.get("/api/projects/pid/story-bible/characters/char_002/impact").json()
    assert remove["action"] == "remove" and [s["id"] for s in remove["scenes"]] == ["scene_001"]
    assert remove["relationships"] == 1
    place = client.get("/api/projects/pid/story-bible/locations/loc_001/impact").json()
    assert "Merge it into another place" in place["blocked"]

    TargetArtifacts(part_workspace(root, "part_0001")).write_adaptation(_adaptation_citing(("char_002",)))
    cited = client.get("/api/projects/pid/story-bible/characters/char_002/impact").json()
    assert cited["blocked"].startswith("Can't remove it: Part 1 uses it.")
    assert client.get("/api/projects/pid/story-bible/characters/char_002/impact",
                      params={"action": "merge"}).status_code == 422
    assert artifacts.read_story_bible(root).revision == 1  # previews never write
