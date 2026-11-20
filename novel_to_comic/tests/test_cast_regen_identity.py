"""Pins the serialised identity of every Cast reference regeneration route.

Persisted jobs and artifacts carry these job kinds, payload keys and colon ids,
so they must not drift when the regeneration code is reorganised.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import pytest

from novel_to_comic.config import Config

from .test_cast_asset_routes import _project
from .test_server_admission import app_at

INSTRUCTION = {"instruction": "Singe her left sleeve."}

# (method path, body) -> kind, payload, operation, arguments, label, debit, response key/value
PLAIN = [
    ("/regen-ref?char_id=char_001", None, "character_ref_regen", {"char_id": "char_001"},
     {"asset_id": "char_001", "kind": "character_ref_regen", "with_looks": False},
     "Character ref / char_001", "Model call: regenerate character ref char_001", ("char_id", "char_001")),
    ("/regen-state-ref?char_id=char_001&state_id=burned", None, "character_ref_regen",
     {"char_id": "char_001:burned"},
     {"asset_id": "char_001:burned", "kind": "character_ref_regen", "with_looks": False},
     "Appearance state / char_001 · burned",
     "Model call: regenerate appearance state char_001/burned", ("char_id", "char_001:burned")),
    ("/regen-plate?loc_id=loc_001", None, "location_plate_regen", {"loc_id": "loc_001"},
     {"asset_id": "loc_001", "kind": "location_plate_regen", "with_looks": False},
     "Location plate / loc_001", "Model call: regenerate location plate loc_001", ("loc_id", "loc_001")),
    ("/locations/loc_001/states/ruined/regenerate", None, "location_plate_regen",
     {"loc_id": "loc_001:ruined"},
     {"asset_id": "loc_001:ruined", "kind": "location_plate_regen", "with_looks": False},
     "Location state / loc_001 · ruined",
     "Model call: regenerate location state loc_001/ruined", ("loc_id", "loc_001:ruined")),
    ("/regen-prop?prop_id=prop_001", None, "prop_ref_regen", {"prop_id": "prop_001"},
     {"asset_id": "prop_001", "kind": "prop_ref_regen", "with_looks": False},
     "Prop ref / prop_001", "Model call: regenerate prop ref prop_001", ("prop_id", "prop_001")),
]

INSTRUCTED = [
    ("/regen-ref-instructed", {"char_id": "char_001"}, "character_ref_regen", {"char_id": "char_001"},
     {"asset_type": "character", "asset_id": "char_001", "state_id": None},
     "Character ref / char_001", "Model call: regenerate instructed character char_001",
     ("char_id", "char_001")),
    ("/characters/char_001/states/burned/regenerate-instructed", {}, "character_ref_regen",
     {"char_id": "char_001:burned"},
     {"asset_type": "character", "asset_id": "char_001", "state_id": "burned"},
     "Appearance state / char_001 · burned", "Model call: regenerate instructed character char_001",
     ("char_id", "char_001")),
    ("/regen-plate-instructed", {"loc_id": "loc_001"}, "location_plate_regen", {"loc_id": "loc_001"},
     {"asset_type": "location", "asset_id": "loc_001", "state_id": None},
     "Location plate / loc_001", "Model call: regenerate instructed location loc_001",
     ("loc_id", "loc_001")),
    ("/locations/loc_001/states/ruined/regenerate-instructed", {}, "location_plate_regen",
     {"loc_id": "loc_001:ruined"},
     {"asset_type": "location", "asset_id": "loc_001", "state_id": "ruined"},
     "Location state / loc_001 · ruined", "Model call: regenerate instructed location loc_001",
     ("loc_id", "loc_001")),
    ("/regen-prop-instructed", {"prop_id": "prop_001"}, "prop_ref_regen", {"prop_id": "prop_001"},
     {"asset_type": "prop", "asset_id": "prop_001", "state_id": None},
     "Prop ref / prop_001", "Model call: regenerate instructed prop prop_001", ("prop_id", "prop_001")),
]


def _post(tmp_path, requests):
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.cast_assets import router

    async def scenario():
        project_dir = _project(tmp_path)
        app = app_at(tmp_path)
        app.include_router(router, prefix="/api/projects/{project_id}")
        app.dependency_overrides[get_project] = lambda: (project_dir, Config(), None)
        app.state.generation_semaphore = asyncio.Semaphore(1)
        admitted = []
        app.state.durable_queue_required = True
        app.state.durable_queue = SimpleNamespace(healthy=True, publish=admitted.append)
        responses = []
        with (
            patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
            patch("novel_to_comic.server.credited_job.assert_sufficient_credits"),
            patch("novel_to_comic.server.credited_job.reserve_credits"),
        ):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                for index, (path, body) in enumerate(requests):
                    responses.append(await client.post(
                        f"/api/projects/book{path}", json=body,
                        headers={"Idempotency-Key": f"key-{index}"}))
        return admitted, responses

    return asyncio.run(scenario())


@pytest.mark.parametrize("route", PLAIN, ids=lambda route: route[0])
def test_plain_regeneration_serialises_its_job_identity(tmp_path, route):
    path, _body, kind, payload, arguments, label, debit, (key, value) = route
    (job,), (response,) = _post(tmp_path, [(path, None)])
    assert response.status_code == 200, response.text
    assert job.kind == kind
    assert {k: v for k, v in job.payload.items() if k in payload or k == "with_looks"} == payload
    assert job.label == label
    assert job.command.operation == "cast_asset"
    assert job.command.arguments == arguments
    assert job.command.stage == "cast"
    assert job.command.debit_description == debit
    assert response.json()[key] == value and response.json()["status"] == "queued"


@pytest.mark.parametrize("route", INSTRUCTED, ids=lambda route: route[0])
def test_instructed_regeneration_serialises_its_job_identity(tmp_path, route):
    path, body, kind, payload, arguments, label, debit, (key, value) = route
    (job,), (response,) = _post(tmp_path, [(path, {**body, **INSTRUCTION})])
    assert response.status_code == 200, response.text
    assert job.kind == kind
    assert {k: v for k, v in job.payload.items() if k in payload} == payload
    assert job.payload["instruction"] == INSTRUCTION["instruction"]
    assert job.label == label
    assert job.command.operation == "cast_instruction"
    assert {k: job.command.arguments[k] for k in arguments} == arguments
    assert job.command.stage == "cast"
    assert job.command.debit_description == debit
    assert response.json()[key] == value and response.json()["status"] == "queued"


def test_a_duplicate_plain_regeneration_returns_the_existing_job(tmp_path):
    admitted, (first, second) = _post(
        tmp_path, [("/regen-ref?char_id=char_001", None)] * 2)
    assert (first.status_code, second.status_code) == (200, 200)
    assert len(admitted) == 1
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


def test_a_duplicate_instructed_regeneration_is_a_conflict(tmp_path):
    request = ("/regen-ref-instructed", {"char_id": "char_001", **INSTRUCTION})
    admitted, (first, second) = _post(tmp_path, [request] * 2)
    assert first.status_code == 200
    assert second.status_code == 409
    assert len(admitted) == 1
