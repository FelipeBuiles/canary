"""Concurrency, integrity and retention regressions from the PR architecture review."""

import asyncio
import hashlib
import io
import json
import os
import threading
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile

from novel_to_comic.server import storage_budget
from novel_to_comic.server.async_credits import ledger_call
from novel_to_comic.verified_files import verified_file
from tests.queue_fixtures import create_app


@pytest.mark.parametrize("failure", ["operation", "cleanup"])
def test_cancelled_ledger_call_keeps_cancellation_when_completion_fails(failure):
    entered, finish = threading.Event(), threading.Event()

    def operation():
        entered.set()
        assert finish.wait(3)
        if failure == "operation":
            raise ValueError("reservation denied after cancellation")
        return "hold", "job"

    def cleanup(_result):
        raise ValueError("release failed after cancellation")

    async def exercise():
        task = asyncio.create_task(ledger_call(operation, cancel_cleanup=cleanup))
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        finish.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(exercise())


def test_restore_retries_quarantine_persistence_without_replacing_the_job(tmp_path, monkeypatch):
    from novel_to_comic.server import generation_jobs

    app = create_app(tmp_path)
    job = generation_jobs.GenerationJob("lost", "owner:book", "project_cover", "Lost", {}, 1, None, status="running")
    generation_jobs.persist_generation_job(app, job)
    persist = generation_jobs.persist_generation_job
    attempts = []

    def fail_once(app, job):
        attempts.append(job)
        if len(attempts) == 1:
            raise OSError("journal unavailable")
        persist(app, job)

    monkeypatch.setattr(generation_jobs, "persist_generation_job", fail_once)

    async def exercise():
        with pytest.raises(OSError, match="journal unavailable"):
            await app.state.durable_queue.restore()
        restored = app.state.generation_jobs["lost"]
        assert restored.phase == "outcome_unknown"
        await app.state.durable_queue.restore()
        assert app.state.generation_jobs["lost"] is restored
        assert attempts == [restored, restored]
        with app.state.admission.journal() as db:
            record = json.loads(db.execute("SELECT payload FROM jobs WHERE id='lost'").fetchone()[0])
        assert record["phase"] == "outcome_unknown" and record["status"] == "failed"

    asyncio.run(exercise())


def test_cancelled_restore_loader_cannot_publish_or_quarantine_jobs(tmp_path, monkeypatch):
    from novel_to_comic.server import generation_jobs

    app = create_app(tmp_path)
    queue = app.state.durable_queue
    job = generation_jobs.GenerationJob("lost", "owner:book", "project_cover", "Lost", {}, 1, None, status="running")
    generation_jobs.persist_generation_job(app, job)
    load = queue._load_saved_jobs
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()

    def blocked_load():
        records = load()
        entered.set()
        try:
            assert release.wait(5)
            return records
        finally:
            finished.set()

    monkeypatch.setattr(queue, "_load_saved_jobs", blocked_load)

    async def exercise():
        task = asyncio.create_task(queue.run())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert queue.owner.closed
            release.set()
            assert await asyncio.to_thread(finished.wait, 2)
            assert not app.state.generation_jobs
            with app.state.admission.journal() as db:
                record = json.loads(db.execute("SELECT payload FROM jobs WHERE id='lost'").fetchone()[0])
            assert record["status"] == "running"
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_queued_payload_uses_one_snapshot_during_threaded_serialization(tmp_path):
    from novel_to_comic.server.generation_jobs import GenerationJob, generation_job_payload

    app = create_app(tmp_path)
    loop_thread = threading.get_ident()
    entered, release = threading.Event(), threading.Event()

    class ReadingJob(GenerationJob):
        def __getattribute__(self, name):
            if name == "status" and threading.get_ident() != loop_thread:
                entered.set()
                assert release.wait(5)
            return super().__getattribute__(name)

    queued = GenerationJob("queued", "owner:book", "project_cover", "Queued", {}, 1, None, user_id="owner")
    observed = ReadingJob("observed", "owner:book", "project_cover", "Observed", {}, 2, None, status="complete")
    app.state.generation_jobs.update({job.id: job for job in (queued, observed)})

    async def exercise():
        task = asyncio.create_task(asyncio.to_thread(generation_job_payload, app, queued))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            busy = GenerationJob("busy", "owner:other", "project_cover", "Busy", {}, 3, None, user_id="owner", status="running")
            app.state.generation_jobs[busy.id] = busy
            release.set()
            payload = await task
            assert payload["queue_position"] == 1 and not payload["waiting_for_other_project"]
            assert generation_job_payload(app, queued)["waiting_for_other_project"]
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


@pytest.mark.parametrize("write_fails", [False, True])
def test_cancelled_restore_keeps_volume_ownership_until_writes_finish(tmp_path, monkeypatch, write_fails):
    import fcntl

    from novel_to_comic.server import generation_jobs

    app = create_app(tmp_path)
    queue = app.state.durable_queue
    job = generation_jobs.GenerationJob("lost", "owner:book", "project_cover", "Lost", {}, 1, None, status="running")
    generation_jobs.persist_generation_job(app, job)
    reconcile = queue._reconcile_restored_jobs
    entered, release = threading.Event(), threading.Event()

    def blocked_write(*args):
        entered.set()
        assert release.wait(5)
        if write_fails:
            raise OSError("journal unavailable during cancellation")
        reconcile(*args)

    monkeypatch.setattr(queue, "_reconcile_restored_jobs", blocked_write)

    async def exercise():
        task = asyncio.create_task(queue.run())
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done() and not queue.owner.closed
            with (tmp_path / ".queue-owner.lock").open("a+b") as contender:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(contender.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert queue.owner.closed
            with app.state.admission.journal() as db:
                record = json.loads(db.execute("SELECT payload FROM jobs WHERE id='lost'").fetchone()[0])
            assert record["status"] == ("running" if write_fails else "failed")
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

    asyncio.run(exercise())


def test_reconnect_preserves_live_objects_and_older_terminal_history(tmp_path):
    from novel_to_comic.server.generation_jobs import GenerationJob, persist_generation_job

    app = create_app(tmp_path)
    running = GenerationJob(id="live", project_name="owner:book", kind="project_cover", label="Cover", payload={}, sequence=2, runner=None, status="running")
    old = GenerationJob(id="old", project_name="owner:book", kind="project_cover", label="Cover", payload={}, sequence=1, runner=None, status="complete")
    app.state.generation_jobs.update({job.id: job for job in (running, old)})
    for job in (old, running):
        persist_generation_job(app, job)
    with app.state.admission.journal() as db:
        payload = json.loads(db.execute("SELECT payload FROM jobs WHERE id='old'").fetchone()[0])
        for number in range(220):
            record = payload | {"id": f"recent-{number}"}
            db.execute("INSERT INTO jobs VALUES(?,?,?)", (record["id"], "owner:book", json.dumps(record)))
    asyncio.run(app.state.durable_queue.restore())
    assert app.state.generation_jobs["live"] is running and running.status == "running"
    assert app.state.generation_jobs["old"] is old
    # A new process still fences interrupted work; a reconnect does not.
    restarted = create_app(tmp_path)
    asyncio.run(restarted.state.durable_queue.restore())
    assert restarted.state.generation_jobs["live"].phase == "outcome_unknown"
    assert "old" not in restarted.state.generation_jobs


def test_checksums_reuse_bytes_but_detect_same_size_restored_mtime_and_replacement(tmp_path, monkeypatch):
    from novel_to_comic import verified_files

    path = tmp_path / "page"
    data = b"original page"
    expected = hashlib.sha256(data).hexdigest()
    path.write_bytes(data)
    calls = []
    digest = hashlib.file_digest

    def count(stream, *args):
        calls.append(stream.name)
        return digest(stream, *args)

    monkeypatch.setattr(hashlib, "file_digest", count)
    clock = verified_files.time_ns
    settled = max(path.stat().st_mtime_ns, path.stat().st_ctime_ns) + verified_files._QUIET_NS + 1
    monkeypatch.setattr(verified_files, "time_ns", lambda: settled)
    assert verified_file(path, expected)
    assert verified_file(path, expected)
    assert not verified_file(path, "0" * 64)
    assert len(calls) == 1
    previous = path.stat()
    monkeypatch.setattr(verified_files, "time_ns", clock)
    path.write_bytes(b"x" * len(data))
    os.utime(path, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    assert not verified_file(path, expected)
    assert len(calls) == 2
    replacement = tmp_path / "replacement"
    replacement.write_bytes(data)
    os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
    os.replace(replacement, path)
    assert verified_file(path, expected)
    assert len(calls) == 3


def test_recent_coarse_timestamps_never_reuse_a_cached_digest(tmp_path, monkeypatch):
    from novel_to_comic import verified_files

    path = tmp_path / "page"
    original = b"original page"
    path.write_bytes(original)
    expected = hashlib.sha256(original).hexdigest()
    with path.open("rb") as stream:
        identity = verified_files._identity(stream)
    # Model multiple writes in one kernel clock tick, including restored mtime.
    monkeypatch.setattr(verified_files, "_identity", lambda stream: identity)
    monkeypatch.setattr(verified_files, "time_ns", lambda: identity[4] + 1)
    assert verified_file(path, expected)
    assert identity not in verified_files._digests
    path.write_bytes(b"x" * len(original))
    os.utime(path, ns=(identity[3], identity[3]))
    assert not verified_file(path, expected)
    assert identity not in verified_files._digests
    # Once settled, the next check hashes the new bytes before caching them.
    monkeypatch.setattr(verified_files, "time_ns", lambda: max(identity[3:]) + verified_files._QUIET_NS + 1)
    assert not verified_file(path, expected)
    assert verified_file(path, hashlib.sha256(path.read_bytes()).hexdigest())


def test_repeated_download_does_not_read_or_hash_unchanged_images(tmp_path, monkeypatch):
    from novel_to_comic import verified_files
    from novel_to_comic.page_finishing import finish_book, open_verified_package
    from tests.test_page_finishing import _write_valid_book

    target, _ = _write_valid_book(tmp_path)
    finish_book(target, formats=("pdf",))
    settled = verified_files.time_ns() + verified_files._QUIET_NS + 1
    monkeypatch.setattr(verified_files, "time_ns", lambda: settled)
    calls = []
    digest = hashlib.file_digest

    def count(stream, *args):
        calls.append(stream.name)
        return digest(stream, *args)

    monkeypatch.setattr(hashlib, "file_digest", count)
    for iteration in range(2):
        stream, package, _preflight = open_verified_package(target, "pdf")
        assert len(stream.read()) == package.byte_size
        stream.close()
        if len(calls) == 0:
            pytest.fail("The first read must verify the file bytes")
        if iteration == 0:
            first = len(calls)
    assert len(calls) == first


def test_uploaded_part_survives_housekeeping_and_account_lock_directory_is_skipped(tmp_path):
    from novel_to_comic.series import append_parts, initialize_series
    from novel_to_comic.server.routers.parts import _commit_text
    from novel_to_comic.target_artifacts import TargetArtifacts

    root = tmp_path / "owner" / "book"
    root.mkdir(parents=True)
    initialize_series(root, project_name="Book", novel_path=root / "original.txt", text="Original story.", auto_split=False)
    source = b"The next part belongs to the author."
    file = UploadFile(io.BytesIO(source), filename="next.txt", size=len(source))
    _, parts = _commit_text(root, file, None, lambda text, origin: append_parts(root, [("Next", text)], origin=origin))
    lock_input = root.parent / ".locks" / ".jobs" / "inputs" / "keep"
    lock_input.parent.mkdir(parents=True, exist_ok=True)
    lock_input.write_bytes(b"not a project")
    app = create_app(tmp_path)
    app.state.admission.set_draining(True)
    storage_budget.housekeeping(app)
    assert (root / "input" / "parts" / "next.txt").read_bytes() == source
    assert TargetArtifacts(root).read_part_text(parts[0].id) == source.decode()
    assert lock_input.exists()


def test_part_upload_uses_one_account_scan_and_counts_expanded_text(tmp_path, monkeypatch):
    from novel_to_comic.server.routers.parts import _commit_text

    root = tmp_path / "owner" / "book"
    root.mkdir(parents=True)
    scans = []
    usage = storage_budget.usage

    def count(account):
        scans.append(account)
        return usage(account)

    monkeypatch.setattr(storage_budget, "usage", count)
    monkeypatch.setenv("CANARY_ACCOUNT_STORAGE_BYTES", "65550")
    # Raw upload fits, expanded text plus raw bytes does not.
    monkeypatch.setattr("novel_to_comic.server.routers.parts.read_source", lambda path: "x" * 100)
    file = UploadFile(io.BytesIO(b"raw"), filename="story.txt", size=3)
    with pytest.raises(HTTPException) as caught:
        _commit_text(root, file, None, lambda *_: pytest.fail("must reject before commit"))
    assert caught.value.status_code == 413
    assert len(scans) == 1
    assert not list((root / "input" / "parts").glob("*"))


def test_streamed_project_upload_uses_one_scan_and_cumulative_bytes(tmp_path, monkeypatch):
    from novel_to_comic.server.routers.projects import _save_upload_capped

    account = tmp_path / "owner"
    account.mkdir()
    monkeypatch.setenv("CANARY_ACCOUNT_STORAGE_BYTES", str(1024 * 1024 + 1))
    scans = []
    usage = storage_budget.usage
    monkeypatch.setattr(storage_budget, "usage", lambda path: (scans.append(path), usage(path))[1])
    file = UploadFile(io.BytesIO(b"x" * (2 * 1024 * 1024)), filename="story.txt")
    with pytest.raises(HTTPException) as caught:
        _save_upload_capped(file, account / "source.txt", account=account)
    assert caught.value.status_code == 413 and len(scans) == 1
    assert not (account / "source.txt").exists()


@pytest.mark.parametrize("part", ["", "/parts/part_0001"])
def test_readiness_and_receipt_variants_come_from_route_metadata(tmp_path, part):
    from novel_to_comic.server.action_policy import request_policy

    app = create_app(tmp_path)
    def policy(suffix, body=b""):
        request = SimpleNamespace(app=app, method="POST", url=SimpleNamespace(path=f"/api/projects/book{part}{suffix}"))
        return request_policy(request, body)
    for stage in ("brief", "cast"):
        assert policy(f"/approve/{stage}").spends and policy(f"/approve/{stage}").dispatches
    for stage in ("style", "draw"):
        assert not policy(f"/approve/{stage}").spends and not policy(f"/approve/{stage}").dispatches
    if part:  # Exports and Pages actions are registered only on part workspaces.
        assert not policy("/export/preflight").replay
        free = policy("/pages/checks/recover", b'{"allow_paid":false}')
        assert not free.spends and not free.replay
        assert not policy("/pages/checks/recover", b'{}').spends
        assert policy("/pages/checks/recover", b'{"allow_paid":true}').spends
        assert policy("/pages/checks/recover", b'bad JSON').spends


def test_threaded_artifact_callback_wakes_event_subscribers():
    from novel_to_comic.server.event_channel import EventChannel

    async def exercise():
        channel = EventChannel()
        queue = channel.subscribe()
        await asyncio.to_thread(channel.put_nowait, {"type": "page_done"})
        assert await asyncio.wait_for(queue.get(), 1) == {"type": "page_done"}
    asyncio.run(exercise())


def test_translation_admission_waiting_for_another_part_keeps_loop_responsive(tmp_path, monkeypatch):
    from novel_to_comic.artifact_lock import production_lock
    from novel_to_comic.server.routers import lettering
    from novel_to_comic.workspace import create_part_workspace

    root = tmp_path / "owner" / "book"
    first = create_part_workspace(root, "part_0001")
    second = create_part_workspace(root, "part_0002")
    held, release, entered = threading.Event(), threading.Event(), threading.Event()

    def export():
        with production_lock(first):
            held.set()
            assert release.wait(3)

    def prepare(target, *_args):
        entered.set()
        with production_lock(target.project_dir):
            raise lettering.LetteringConflict("No translation work after the wait")

    monkeypatch.setattr(lettering, "prepare_translation", prepare)
    writer = threading.Thread(target=export)
    writer.start()
    assert held.wait(2)
    # Bound a regression that blocks the loop: the independent timer releases
    # the lock even if the async handler incorrectly takes it synchronously.
    fallback = threading.Timer(1, release.set)
    fallback.start()

    async def exercise():
        from time import monotonic
        body = lettering.LetteringTranslate(target_locale="es", expected_snapshot_sha256="a" * 64)
        started = monotonic()
        task = asyncio.create_task(lettering.post_translation("book", body, SimpleNamespace(), project=(second, None, None), user_id="owner"))
        try:
            assert await asyncio.to_thread(entered.wait, 0.5)
            assert monotonic() - started < 0.5
            assert not task.done()  # The lock is still held by the export.
        finally:
            release.set()
            with pytest.raises(HTTPException) as caught:
                await task
            assert caught.value.status_code == 409

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        fallback.cancel()
        writer.join(3)


def test_queue_restore_keeps_loop_responsive_before_connecting(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager
    from time import monotonic

    queue = create_app(tmp_path).state.durable_queue
    entered, release = threading.Event(), threading.Event()

    def load():
        entered.set()
        assert release.wait(3)
        return []

    @asynccontextmanager
    async def connection():
        raise ValueError("restore finished before connection")
        yield  # pragma: no cover

    monkeypatch.setattr(queue, "_load_saved_jobs", load)
    monkeypatch.setattr(queue.backend, "open_async", connection)
    fallback = threading.Timer(1, release.set)
    fallback.start()

    async def exercise():
        started = monotonic()
        task = asyncio.create_task(queue.run())
        try:
            assert await asyncio.to_thread(entered.wait, 0.5)
            assert monotonic() - started < 0.5 and not task.done()
        finally:
            release.set()
            with pytest.raises(ValueError, match="restore finished"):
                await task
        assert queue.owner.closed

    try:
        asyncio.run(exercise())
    finally:
        release.set()
        fallback.cancel()


def test_restore_loads_detached_jobs_and_keeps_threaded_status_reads_safe(tmp_path, monkeypatch):
    from contextlib import asynccontextmanager

    import httpx

    from novel_to_comic.server import generation_jobs

    loop_thread = threading.get_ident()
    loaded, load_release = threading.Event(), threading.Event()
    reading, read_release = threading.Event(), threading.Event()
    construction_threads, insertion_threads = [], []
    job_type = generation_jobs.GenerationJob
    app = create_app(tmp_path)
    queue = app.state.durable_queue
    monkeypatch.setenv("CANARY_OPS_TOKEN", "review-restore")
    for identity, status in (("recent", "complete"), ("reconnected", "running"), ("interrupted", "running")):
        job = job_type(identity, "owner:book", "project_cover", identity, {}, 1, None, status=status)
        generation_jobs.persist_generation_job(app, job)

    class ObservedJobs(dict):
        def __setitem__(self, key, value):
            insertion_threads.append(threading.get_ident())
            super().__setitem__(key, value)

    class ReadingJob(job_type):
        def __getattribute__(self, name):
            if name == "status" and threading.get_ident() != loop_thread:
                reading.set()
                assert read_release.wait(5)
            return super().__getattribute__(name)

    live = ReadingJob("live", "owner:book", "project_cover", "Live", {}, 1, None, status="running")
    app.state.generation_jobs = ObservedJobs()
    app.state.generation_jobs[live.id] = live

    def construct(*args, **kwargs):
        job = job_type(*args, **kwargs)
        construction_threads.append(threading.get_ident())
        if len(construction_threads) == 3:
            loaded.set()
            assert load_release.wait(5)
        return job

    @asynccontextmanager
    async def connection():
        raise ValueError("restore finished before connection")
        yield  # pragma: no cover

    monkeypatch.setattr(generation_jobs, "GenerationJob", construct)
    monkeypatch.setattr(queue.backend, "open_async", connection)

    async def exercise():
        restore_task = asyncio.create_task(queue.run())
        read_task = None
        try:
            assert await asyncio.to_thread(loaded.wait, 2)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                read_task = asyncio.create_task(client.get("/api/ops/deployment-status", headers={"X-Canary-Ops-Token": "review-restore"}))
                assert await asyncio.to_thread(reading.wait, 2)
                # Journal parsing must not publish partial results into memory.
                assert set(app.state.generation_jobs) == {"live"}
                current = job_type("reconnected", "owner:book", "project_cover", "Current", {}, 2, None, status="running")
                app.state.generation_jobs[current.id] = current
                load_release.set()
                with pytest.raises(ValueError, match="restore finished"):
                    await restore_task
                assert app.state.generation_jobs["live"] is live
                assert app.state.generation_jobs["reconnected"] is current
                assert app.state.generation_jobs["interrupted"].phase == "outcome_unknown"
                assert all(identity == loop_thread for identity in insertion_threads)
                assert all(identity != loop_thread for identity in construction_threads)
                read_release.set()
                response = await read_task
                assert response.status_code == 200
                # This request began before the restored/new jobs were merged.
                assert response.json()["counts"]["running_generation_jobs"] == 1
                with app.state.admission.journal() as db:
                    records = {identity: json.loads(payload) for identity, payload in db.execute("SELECT id,payload FROM jobs")}
                assert records["reconnected"]["status"] == "running"
                assert records["interrupted"]["phase"] == "outcome_unknown"
                assert queue.owner.closed
        finally:
            load_release.set()
            read_release.set()
            await asyncio.gather(restore_task, *([read_task] if read_task else []), return_exceptions=True)

    asyncio.run(exercise())
