import json
from types import SimpleNamespace

import pytest

from novel_to_comic.config import Config
from novel_to_comic.server.admission import Admission
from novel_to_comic.server.generation_jobs import GenerationJob, generation_job_payload
from novel_to_comic.server.job_commands import command
from novel_to_comic.server.routers.pipeline import get_generation_jobs
from novel_to_comic.state import hash_style_template


@pytest.mark.parametrize("kind,identity", [
    ("character_ref_regen", "char_id"),
    ("location_plate_regen", "loc_id"),
    ("prop_ref_regen", "prop_id"),
])
@pytest.mark.parametrize("recovered", [False, True])
def test_reference_history_retains_the_style_used_before_selection(tmp_path, kind, identity, recovered):
    job = GenerationJob(
        id="old-correction", project_name="account:book", kind=kind,
        label="Reference", payload={identity: "entity:appearance"}, sequence=1,
        runner=None, status="failed", error="Previous provider failure",
        command=command("cast_asset", tmp_path, Config(style_template="old ink"), asset_id="entity:appearance", kind=kind),
    )
    app = SimpleNamespace(state=SimpleNamespace(
        generation_jobs={job.id: job}, admission=Admission(tmp_path),
    ))
    from novel_to_comic.server.generation_jobs import persist_generation_job
    persist_generation_job(app, job)
    if recovered:
        with app.state.admission.journal() as db:
            db.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, project TEXT NOT NULL, payload TEXT NOT NULL)")
            db.execute("CREATE TABLE operation_outbox (id TEXT PRIMARY KEY, command TEXT NOT NULL, dispatched INTEGER)")
            # Persisted history from before style hashes were exposed in the API.
            payload = generation_job_payload(app, job)
            db.execute("INSERT OR REPLACE INTO jobs VALUES(?,?,?)", (job.id, job.project_name, json.dumps(payload)))
            db.execute("INSERT INTO operation_outbox VALUES(?,?,?)", (job.id, job.command.model_dump_json(), 1))
        app.state.generation_jobs.clear()
    result = get_generation_jobs(
        SimpleNamespace(app=app), "book", ids=None, before=None, limit=100, user_id="account",
        project=(tmp_path, Config(style_template="new wash"), None),
    )
    assert result["current_reference_style_hash"] == hash_style_template("new wash")
    assert result["jobs"][0]["reference_style_hash"] == hash_style_template("old ink")
    assert result["jobs"][0]["status"] == "failed"
    assert result["jobs"][0]["error"] == "Previous provider failure"
    assert "command" not in result["jobs"][0]


def test_current_reference_job_uses_whitespace_normalized_style(tmp_path):
    job = GenerationJob(
        id="current", project_name="account:book", kind="character_ref_regen",
        label="Reference", payload={"char_id": "entity"}, sequence=1, runner=None,
        command=command("cast_asset", tmp_path, Config(style_template="ink\n wash"), asset_id="entity", kind="character_ref_regen"),
    )
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={job.id: job}, admission=Admission(tmp_path)))
    result = get_generation_jobs(
        SimpleNamespace(app=app), "book", ids=None, before=None, limit=100, user_id="account",
        project=(tmp_path, Config(style_template="ink wash"), None),
    )
    assert result["jobs"][0]["reference_style_hash"] == result["current_reference_style_hash"]
    assert result["jobs"][0]["status"] == "queued"
