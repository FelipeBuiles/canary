"""Part routes on a real series project: migration, status, parts and scope."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from novel_to_comic import artifacts
from novel_to_comic.config import Config, save_config
from novel_to_comic.models.book_map import BookAct, BookMap, BookMapPart
from novel_to_comic.models.story_bible import Prop, StoryBible
from novel_to_comic.server import deps
from tests.queue_fixtures import create_app
from novel_to_comic.server.auth import get_current_user
from novel_to_comic.server.routers import projects
from novel_to_comic.state import StageStatus, create_initial_state, load_state, save_state
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import part_workspace

BODY = "The lighthouse kept its light. " * 12
TEXT = "Chapter 1\n" + BODY + "\nChapter 2\n" + BODY


@pytest.fixture
def client(tmp_path, monkeypatch):
    root = tmp_path / "account" / "book"
    (root / "input").mkdir(parents=True)
    (root / "input" / "novel.txt").write_text(TEXT)
    save_config(Config(), root)
    # A project created before parts: everything at the root.
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
    test_client = TestClient(app)
    test_client.event_hooks["request"].append(
        lambda request: request.headers.setdefault("Idempotency-Key", str(uuid4()))
    )
    return test_client, root


def test_opening_a_legacy_project_migrates_it_into_one_part(client) -> None:
    test_client, root = client

    response = test_client.get("/api/projects/pid/status")

    assert response.status_code == 200
    body = response.json()
    assert body["part_id"] == "part_0001"
    assert [part["id"] for part in body["parts"]] == ["part_0001"]
    assert body["parts"][0]["text_editable"] is True
    assert TargetArtifacts(root).read_part_text("part_0001") == TEXT
    part_status = test_client.get("/api/projects/pid/parts/part_0001/status")
    assert part_status.status_code == 200
    assert part_status.json()["stages"]["extract"]["status"] == "pending"
    assert test_client.get("/api/projects/pid/parts/part_0009/status").status_code == 404


def test_parts_can_be_appended_split_renamed_and_deleted(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")

    added = test_client.post("/api/projects/pid/parts", data={"text": TEXT, "title": "Book Two"})
    assert added.status_code == 200
    assert added.json()["part"]["id"] == "part_0002"
    assert [chapter["title"] for chapter in added.json()["chapters"]] == ["Chapter 1", "Chapter 2"]

    boundary = added.json()["chapters"][1]["start_offset"]
    split = test_client.post("/api/projects/pid/parts/part_0002/split",
                             json={"boundaries": [boundary], "titles": ["Book Two", "Book Three"]})
    assert split.status_code == 200
    assert [part["title"] for part in split.json()["parts"]] == ["Part 1", "Book Two", "Book Three"]

    renamed = test_client.patch("/api/projects/pid/parts/part_0001", json={"title": "Book One"})
    assert renamed.json()["part"]["title"] == "Book One"

    assert test_client.delete("/api/projects/pid/parts/part_0002").status_code == 200
    listing = test_client.get("/api/projects/pid/parts").json()["parts"]
    assert [(part["id"], part["title"]) for part in listing] == [
        ("part_0001", "Book One"), ("part_0002", "Book Three"),
    ]
    assert test_client.post("/api/projects/pid/parts", data={}).status_code == 422


@pytest.mark.parametrize("method,path", [
    ("POST", "/api/projects/pid/parts"),
    ("PUT", "/api/projects/pid/parts/part_0001/text"),
])
def test_part_file_uploads_above_the_generic_body_limit_are_accepted(client, method, path) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    text = "The tide turned. " * 190_000  # More than the generic 2 MB body cap.

    response = test_client.request(method, path, files={"file": ("long.txt", text, "text/plain")})

    assert response.status_code == 200, response.text
    identifier = response.json()["part"]["id"]
    assert TargetArtifacts(root).read_part_text(identifier) == text
    assert (root / "input" / "parts" / "long.txt").read_text() == text
    assert not list((root / "input" / "parts").glob(".incoming-*"))


def test_appended_uploads_group_chapters_and_return_the_created_parts(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    text = "Title\n\n" + "".join(f"Chapter {number}\n" + BODY * 90 + "\n\n" for number in range(1, 8))

    response = test_client.post("/api/projects/pid/parts", files={"file": ("book.txt", text, "text/plain")})

    assert response.status_code == 200, response.text
    created = response.json()["created"]
    assert created == ["part_0002", "part_0003", "part_0004", "part_0005"]
    assert response.json()["part"]["id"] == created[0]
    target = TargetArtifacts(root)
    assert "".join(target.read_part_text(identifier) for identifier in created) == text
    assert target.read_part_text("part_0001") == TEXT
    first_text = target.read_part_text(created[0])
    assert response.json()["chapters"][-1]["end_offset"] == len(first_text)


def test_grouped_upload_replays_without_appending_duplicate_parts(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    text = f"Chapter 1\n{BODY * 200}\nChapter 2\n{BODY * 200}"
    headers = {"Idempotency-Key": "grouped-upload"}

    first = test_client.post("/api/projects/pid/parts", files={"file": ("book.txt", text, "text/plain")}, headers=headers)
    replay = test_client.post("/api/projects/pid/parts", files={"file": ("book.txt", text, "text/plain")}, headers=headers)

    assert first.status_code == replay.status_code == 200
    assert first.json()["created"] == ["part_0002", "part_0003"]
    assert replay.json() == first.json()
    assert replay.headers["Idempotency-Replayed"] == "true"
    assert len(TargetArtifacts(root).read_part_manifest().parts) == 3
    assert [path.name for path in (root / "input" / "parts").iterdir()] == ["book.txt"]


def test_initial_project_upload_creates_chapter_groups_and_opens_the_first_part(client, monkeypatch) -> None:
    from novel_to_comic.server import account_models

    test_client, root = client
    monkeypatch.setattr(projects, "_count_user_projects", lambda _user: 0)
    monkeypatch.setattr(account_models, "creation_config", lambda *_args: Config())
    projects.get_db().table.return_value.insert.return_value.execute.return_value = SimpleNamespace(data=[{"id": "new-project"}])
    text = "Title\n\n" + "".join(f"Chapter {number}\n" + BODY * 90 + "\n\n" for number in range(1, 8))

    response = test_client.post("/api/projects/", data={"name": "Full Book"},
                                files={"file": ("book.txt", text, "text/plain")})

    assert response.status_code == 200, response.text
    assert response.json()["part_id"] == "part_0001"
    target = TargetArtifacts(root.parent / "full-book")
    manifest = target.read_part_manifest()
    assert len(manifest.parts) == 4
    assert "".join(target.read_part_text(part.id) for part in manifest.parts) == text
    assert (root.parent / "full-book" / "input" / "book.txt").read_text() == text


def test_source_preview_reports_the_same_parts_creation_makes_without_storing_anything(client) -> None:
    test_client, root = client
    text = "Title\n\n" + "".join(f"Chapter {number}\n" + BODY * 90 + "\n\n" for number in range(1, 8))
    before = sorted(path.name for path in root.parent.iterdir())

    response = test_client.post("/api/projects/source-preview",
                                files={"file": ("book.txt", text, "text/plain")})

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["chapters"] == 7
    assert body["words"] == len(text.split())
    assert len(body["parts"]) == 4
    assert body["parts"][0]["title"] == "Chapters 1–2"
    assert sum(part["characters"] for part in body["parts"]) == len(text)
    assert sorted(path.name for path in root.parent.iterdir()) == before


def test_source_preview_accepts_manuscripts_above_the_generic_body_limit(client, monkeypatch) -> None:
    test_client, _root = client
    monkeypatch.setenv("CANARY_MAX_BODY_MB", "1")
    text = "".join(f"Chapter {number}\n" + BODY * 1500 + "\n\n" for number in range(1, 4))
    assert len(text.encode()) > 1024 * 1024

    response = test_client.post("/api/projects/source-preview",
                                files={"file": ("book.txt", text, "text/plain")})

    assert response.status_code == 200, response.text
    assert response.json()["chapters"] == 3


def test_source_preview_rejects_unreadable_and_empty_sources(client) -> None:
    test_client, _root = client

    unsupported = test_client.post("/api/projects/source-preview",
                                   files={"file": ("book.rtf", "x", "application/rtf")})
    empty = test_client.post("/api/projects/source-preview",
                             files={"file": ("pasted-manuscript.txt", "  \n ", "text/plain")})

    assert unsupported.status_code == 400
    assert empty.status_code == 422


def test_chapter_proposals_still_report_the_opening_before_the_first_heading(client) -> None:
    test_client, _root = client
    test_client.get("/api/projects/pid/status")
    opening = "An epigraph and an unnumbered opening.\n\n"
    text = opening + f"[ 1 ]\n{BODY}\n[ 2 ]\n{BODY}"

    added = test_client.post("/api/projects/pid/parts", data={"text": text})

    assert added.status_code == 200
    assert added.json()["chapters"][0]["opening_characters"] == len(opening)
    assert "opening_characters" not in added.json()["parts"][1]


def test_parts_carry_their_book_map_synopsis_until_their_text_changes(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    test_client.post("/api/projects/pid/parts", data={"text": TEXT})
    manifest = TargetArtifacts(root).read_part_manifest()
    book_map = BookMap(
        synopsis="A keeper guards the light.",
        parts=[BookMapPart(part_id=record.id, text_sha256=record.text_sha256,
                           synopsis=f"Synopsis {record.ordinal}", role=f"Role {record.ordinal}")
               for record in manifest.parts],
        acts=[BookAct(number=1, title="Watch", summary="The watch.",
                      first_part="part_0001", last_part="part_0002")],
    )
    (root / "book_map").mkdir()
    (root / "book_map" / "book_map.json").write_text(book_map.model_dump_json())

    listed = test_client.get("/api/projects/pid/parts").json()["parts"]
    assert [(part["synopsis"], part["book_role"]) for part in listed] == [
        ("Synopsis 1", "Role 1"), ("Synopsis 2", "Role 2")]

    replaced = test_client.put("/api/projects/pid/parts/part_0002/text", data={"text": "New text.\n" + BODY})
    assert replaced.status_code == 200
    assert [part["synopsis"] for part in replaced.json()["parts"]] == ["Synopsis 1", None]


def test_automatic_grouping_can_be_disabled_when_appending(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    text = f"Chapter 1\n{BODY * 200}\nChapter 2\n{BODY * 200}"

    response = test_client.post("/api/projects/pid/parts", data={"text": text, "auto_split": "false", "title": "Book Two"})

    assert response.status_code == 200, response.text
    assert response.json()["created"] == ["part_0002"]
    assert response.json()["part"]["title"] == "Book Two"
    assert TargetArtifacts(root).read_part_text("part_0002") == text


@pytest.mark.parametrize("method,path,identifier", [
    ("POST", "/api/projects/pid/parts", "part_0002"),
    ("PUT", "/api/projects/pid/parts/part_0001/text", "part_0001"),
])
def test_large_pasted_text_uses_the_source_character_budget(client, method, path, identifier) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    text = "The tide turned. " * 190_000

    response = test_client.request(method, path, files={"text": (None, text)})

    assert response.status_code == 200, response.text
    assert TargetArtifacts(root).read_part_text(identifier) == text


def test_rejected_part_upload_cleans_staging_and_preserves_the_manifest(client, monkeypatch) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    monkeypatch.setenv("CANARY_MAX_UPLOAD_MB", "2")
    before = TargetArtifacts(root).read_part_manifest()

    response = test_client.post("/api/projects/pid/parts", files={"file": ("large.txt", b"x" * (2_500_000), "text/plain")})

    assert response.status_code == 413
    assert response.json()["detail"] == "Uploaded file exceeds the 2 MB limit."
    assert TargetArtifacts(root).read_part_manifest() == before
    assert not list((root / "input" / "parts").iterdir())


def test_text_edits_are_rejected_once_adaptation_starts(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    workspace = part_workspace(root, "part_0001")
    state = load_state(workspace)
    state.stages["adapt"].status = StageStatus.RUNNING
    save_state(state, workspace)

    response = test_client.put("/api/projects/pid/parts/part_0001/text", data={"text": "New text. " * 5})

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "part_locked"
    assert TargetArtifacts(root).read_part_text("part_0001") == TEXT


def test_part_stages_need_a_part_route_and_parts_extract_in_order(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    test_client.post("/api/projects/pid/parts", data={"text": BODY})

    series_route = test_client.post("/api/projects/pid/run?stage=extract")
    assert series_route.status_code == 409
    assert series_route.json()["detail"]["code"] == "part_required"

    out_of_order = test_client.post("/api/projects/pid/parts/part_0002/run?stage=extract")
    assert out_of_order.status_code == 409
    assert out_of_order.json()["detail"]["code"] == "part_order"


def test_a_later_part_waits_for_blank_anchors_before_extracting(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    test_client.post("/api/projects/pid/parts", data={"text": BODY})
    first = part_workspace(root, "part_0001")
    state = load_state(first)
    state.stages["extract"].status = StageStatus.COMPLETE
    save_state(state, first)
    # An extraction from before anchors were required can leave one blank.
    artifacts.write_story_bible(root, StoryBible(
        title="Lighthouse", author="A. Writer", total_scenes=0, scenes=[], characters=[], locations=[],
        sequences=[], props=[Prop(id="lamp", name="Lamp", visual_anchor=" ")],
    ))

    for response in (test_client.get("/api/projects/pid/parts/part_0002/estimate?stage=extract"),
                     test_client.post("/api/projects/pid/parts/part_0002/run?stage=extract")):
        assert response.status_code == 409
        assert response.json()["detail"] == (
            "These Story Bible entries have no visual anchor: Lamp (lamp). "
            "Add the missing descriptions in the Cast station or the Story Bible."
        )


def test_page_routes_live_under_a_part(client) -> None:
    test_client, _root = client
    test_client.get("/api/projects/pid/status")

    assert test_client.get("/api/projects/pid/pages").status_code == 404
    response = test_client.get("/api/projects/pid/parts/part_0001/pages")
    assert response.status_code in {200, 404}
    assert response.status_code != 404 or "Part" not in response.text


def test_files_resolve_against_the_addressed_root(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    (root / "samples").mkdir(exist_ok=True)
    (root / "samples" / "style_1.png").write_bytes(b"style")
    cover = part_workspace(root, "part_0001") / "cover" / "cover.png"
    cover.parent.mkdir(exist_ok=True)
    cover.write_bytes(b"cover")

    assert test_client.get("/api/projects/pid/files/samples/style_1.png").content == b"style"
    assert test_client.get("/api/projects/pid/parts/part_0001/files/cover/cover.png").content == b"cover"
    assert test_client.get("/api/projects/pid/parts/part_0001/files/part.json").status_code in {200, 403}
    assert test_client.get("/api/projects/pid/files/parts/part_0001/state.json").status_code in {200, 403}


def test_jobs_are_listed_per_part(client) -> None:
    test_client, root = client
    test_client.get("/api/projects/pid/status")
    assert test_client.post("/api/projects/pid/parts", data={"text": BODY}).status_code == 200
    from novel_to_comic.server.generation_jobs import GenerationJob
    from novel_to_comic.server.job_commands import command

    app = test_client.app
    for identifier, directory in (("a", part_workspace(root, "part_0001")), ("b", root)):
        app.state.generation_jobs[identifier] = GenerationJob(
            id=identifier, project_name="account:pid", kind="pipeline_stage", label=identifier,
            payload={}, sequence=1, runner=None, command=command("pipeline", directory, Config()),
        )
    part_two = test_client.get("/api/projects/pid/parts/part_0002/jobs").json()["jobs"]
    part_one = test_client.get("/api/projects/pid/parts/part_0001/jobs").json()["jobs"]

    assert [job["id"] for job in part_one] == ["a", "b"]
    assert [job["id"] for job in part_two] == ["b"]
    assert part_one[0]["part_id"] == "part_0001"
    assert part_one[1]["part_id"] is None
