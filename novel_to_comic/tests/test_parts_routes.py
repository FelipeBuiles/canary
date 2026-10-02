"""Part routes on a real series project: migration, status, parts and scope."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from novel_to_comic.config import Config, save_config
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
