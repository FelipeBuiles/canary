"""The book map tells each part where it sits in the whole saved manuscript."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from novel_to_comic.book_map import (
    book_slice,
    check_synthesis,
    ensure_book_map,
    estimate_book_map,
    fresh_book_map,
    promote_recurring_cast,
    read_book_map,
)
from novel_to_comic.config import Config
from novel_to_comic.models.book_map import BookAct, BookCharacter, BookMap, BookMapPart, BookSynthesis, BookThread
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.series import append_parts, initialize_series
from novel_to_comic.usage import ApiResult

PARTS = ["part_0001", "part_0002", "part_0003"]
SHA = "0" * 64


class _Context:
    def __init__(self) -> None:
        self.logs: list[str] = []

    def log(self, message: str, **_kwargs) -> None:
        self.logs.append(message)

    def activity(self, **_kwargs) -> None:
        pass


def _synthesis(**changes) -> BookSynthesis:
    values = dict(
        synopsis="A keeper and a stranger hold the light against the storm.",
        acts=[
            BookAct(number=7, title="Arrival", summary="The stranger comes.", first_part="part_0001", last_part="part_0002"),
            BookAct(number=9, title="Storm", summary="The storm breaks.", first_part="part_0002", last_part="part_0003"),
        ],
        parts=[{"part_id": part, "role": f"Role {index}"} for index, part in enumerate(PARTS, 1)],
        threads=[BookThread(id="thread_009", title="The debt", summary="Who owes whom.",
                            opens_in="part_0001", resolves_in="part_0003")],
    )
    values.update(changes)
    return BookSynthesis.model_validate(values)


def test_acts_follow_the_book_and_code_owns_their_numbering():
    checked = check_synthesis(_synthesis(), PARTS)

    assert [act.number for act in checked.acts] == [1, 2]
    assert [thread.id for thread in checked.threads] == ["thread_001"]


@pytest.mark.parametrize("changes, message", [
    (dict(acts=[BookAct(number=1, title="A", summary="a", first_part="part_0001", last_part="part_0002")]),
     "uncovered"),
    (dict(acts=[BookAct(number=1, title="A", summary="a", first_part="part_0002", last_part="part_0003"),
                BookAct(number=2, title="B", summary="b", first_part="part_0001", last_part="part_0001")]),
     "forward"),
    (dict(parts=[{"part_id": "part_0001", "role": "r"}]), "every saved part"),
    (dict(threads=[BookThread(id="thread_001", title="T", summary="t", opens_in="part_0003",
                              resolves_in="part_0001")]), "resolve before"),
    (dict(characters=[BookCharacter(name="Ann", role="r", prominence="principal",
                                    first_part="part_0004", last_part="part_0004")]), "saved part"),
])
def test_synthesis_rejects_maps_that_do_not_fit_the_saved_parts(changes, message):
    with pytest.raises(ValueError, match=message):
        check_synthesis(_synthesis(**changes), PARTS)


def _map() -> BookMap:
    synthesis = check_synthesis(_synthesis(
        threads=[
            BookThread(id="thread_001", title="Opens here", summary="s", opens_in="part_0002"),
            BookThread(id="thread_002", title="Carried", summary="s", opens_in="part_0001", resolves_in="part_0003"),
            BookThread(id="thread_003", title="Closed", summary="s", opens_in="part_0001", resolves_in="part_0001"),
            BookThread(id="thread_004", title="Later", summary="s", opens_in="part_0003"),
        ],
        characters=[
            BookCharacter(name="Keeper", role="r", prominence="principal", first_part="part_0001", last_part="part_0003"),
            BookCharacter(name="Clerk", role="r", prominence="minor", first_part="part_0002", last_part="part_0002"),
            BookCharacter(name="Heir", role="r", prominence="recurring", first_part="part_0003", last_part="part_0003"),
        ],
    ), PARTS)
    return BookMap(
        synopsis=synthesis.synopsis,
        parts=[BookMapPart(part_id=part, text_sha256=SHA, synopsis=f"Synopsis {index}", role=f"Role {index}")
               for index, part in enumerate(PARTS, 1)],
        acts=synthesis.acts, threads=synthesis.threads, characters=synthesis.characters,
        themes=["duty"], motifs=["the lamp"],
    )


def test_a_part_sees_only_what_is_active_where_it_sits():
    view = book_slice(_map(), "part_0002")

    assert view["this_part"] == {"part_id": "part_0002", "synopsis": "Synopsis 2", "role": "Role 2"}
    # Both acts touch part 2: it ends one movement and begins the next.
    assert [act["title"] for act in view["acts"]] == ["Arrival", "Storm"]
    assert [(thread["title"], thread["here"]) for thread in view["threads"]] == [
        ("Opens here", "opens"), ("Carried", "continues")]
    # Minor and not-yet-present people stay out.
    assert [character["name"] for character in view["characters"]] == ["Keeper"]
    assert view["earlier_parts"] == [{"part_id": "part_0001", "synopsis": "Synopsis 1"}]
    assert book_slice(_map(), "part_0003")["threads"][1]["here"] == "resolves"


def _bible(name: str) -> StoryBible:
    return StoryBible(
        title="Light", author="A", total_scenes=1, sequences=[],
        characters=[Character(id="c1", name=name, visual_anchor="1man, adult male, beard", age_range="adult",
                              gender="male", distinguishing_features=[], default_outfit="coat",
                              first_appearance_scene="s1")],
        locations=[Location(id="l1", name="Tower", visual_anchor="stone tower", mood="grim")],
        scenes=[Scene(id="s1", part_id="part_0001", chapter=1, title="S", location_id="l1",
                      character_ids=["c1"], summary="s", scene_type="dialogue", narrative_beat="setup",
                      source_start_quote="x")],
    )


def test_people_the_book_keeps_returning_to_get_a_cast_reference():
    bible = _bible("The Keeper")
    assert promote_recurring_cast(bible, _map(), "part_0001") == ["The Keeper"]
    assert bible.characters[0].cast_required

    clerk = _bible("Clerk")
    assert promote_recurring_cast(clerk, _map(), "part_0001") == []
    assert not clerk.characters[0].cast_required


def _fake_generate(calls: list[str]):
    async def generate(*, config, feature, user_content, **_kwargs):
        calls.append(feature)
        content = json.loads(user_content)
        if feature == "extract.book_map_digest":
            return ApiResult(value={"synopsis": content["text"][:20]})
        parts = [part["part_id"] for part in content["parts"]]
        return ApiResult(value={
            "synopsis": "The whole book.",
            "acts": [{"number": 1, "title": "All", "summary": "Everything.",
                      "first_part": parts[0], "last_part": parts[-1]}],
            "parts": [{"part_id": part, "role": "A stretch"} for part in parts],
        })
    return generate


def test_the_map_reads_each_part_once_and_rebuilds_only_for_new_text(tmp_path: Path):
    root = tmp_path / "book"
    root.mkdir()
    workspace = initialize_series(root, project_name="Light", novel_path=root / "n.txt", text="First part text.")
    config = Config()
    calls: list[str] = []
    # A single-part project is its own book.
    assert asyncio.run(ensure_book_map(config, workspace, _Context(), generate=_fake_generate(calls))) is None
    assert estimate_book_map(config, workspace) == 0.0

    append_parts(root, [("Part 2", "Second part text.")])
    assert estimate_book_map(config, workspace) > 0
    book_map = asyncio.run(ensure_book_map(config, workspace, _Context(), generate=_fake_generate(calls)))
    assert book_map is not None
    assert calls == ["extract.book_map_digest", "extract.book_map_digest", "extract.book_map"]
    assert [part.synopsis for part in book_map.parts] == ["First part text.", "Second part text."]
    assert read_book_map(workspace) == book_map == fresh_book_map(workspace)
    assert estimate_book_map(config, workspace) == 0.0

    calls.clear()
    asyncio.run(ensure_book_map(config, workspace, _Context(), generate=_fake_generate(calls)))
    assert calls == []

    append_parts(root, [("Part 3", "Third part text.")])
    assert fresh_book_map(workspace) is None  # a stale map is never used
    asyncio.run(ensure_book_map(config, workspace, _Context(), generate=_fake_generate(calls)))
    assert calls == ["extract.book_map_digest", "extract.book_map"]
    rebuilt = fresh_book_map(workspace)
    assert rebuilt is not None and len(rebuilt.parts) == 3


def test_a_story_bible_with_book_acts_must_be_analyzed_again():
    with pytest.raises(ValueError, match="before part sequences replaced acts"):
        StoryBible.model_validate({
            "title": "T", "author": "A", "total_scenes": 0, "characters": [], "locations": [],
            "scenes": [], "narrative_arcs": [],
        })


def test_sequences_partition_a_part_in_order_however_many_it_has():
    from novel_to_comic.extraction_sections import check_sequences
    from novel_to_comic.models.story_bible import StorySequence
    from novel_to_comic.stages.s1_extract import _normalize_sequences

    one = [StorySequence(number=1, title="All", scenes=["a", "b", "c"])]
    check_sequences(one, ["a", "b", "c"])
    with pytest.raises(ValueError, match="partition"):
        check_sequences([StorySequence(number=1, title="x", scenes=["b", "a"])], ["a", "b"])
    # Reading order is the authority; numbering is assigned by code.
    assert [s["number"] for s in _normalize_sequences([{"title": "x", "scenes": "a"}, {"name": "y", "scene_ids": ["b"]}])] == [1, 2]


def test_map_schemas_fit_strict_providers_and_leave_numbering_to_code():
    from novel_to_comic.ai.anthropic_schema import anthropic_output_schema
    from novel_to_comic.ai.codex_schema import strict_output_schema
    from novel_to_comic.book_map import digest_schema, synthesis_schema

    schema = synthesis_schema(PARTS)
    assert "id" not in schema["$defs"]["BookThread"]["properties"]
    assert schema["$defs"]["BookAct"]["properties"]["first_part"]["enum"] == PARTS
    for adapter in (strict_output_schema, anthropic_output_schema):
        adapter(schema)
        adapter(digest_schema())
