"""Serialize project mutations and durably deduplicate explicit user actions.

The journal lives on the same persistent volume as project artifacts. Unstarted durable
operations survive restart; interrupted execution is never automatically replayed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path

from fastapi import HTTPException, Response
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .auth import SESSION_COOKIE_NAME, get_current_user
from .body_limit import form_part_cap_bytes
from .deps import project_key

_PROJECT = re.compile(r"^/api/projects/([^/]+)(/.*)?$")
_PAID = re.compile(r"^/(?:run|regen-[^/]+|cover|lettering/translate|approve/(?:brief|cast)|styles/(?:direction|suggest|generate-samples|validation)|pages/\d+/(?:generate|analyze|visual-review|corrections|replan)|(?:characters|locations)/[^/]+/states/[^/]+/(?:regenerate|regenerate-instructed)|story-changes/[^/]+/apply|story-bible/(?:characters|locations|props)/draft)$")
# Correction previews read the same page inputs as submission and must remain
# available while independent page jobs run. Submission owns same-page conflicts.
_TARGETED = re.compile(r"^/(?:regen-(?!extract)[^/]+|cover|pages/\d+/(?:generate|analyze|visual-review|corrections(?:/preview)?)|(?:characters|locations)/[^/]+/states/[^/]+/(?:regenerate|regenerate-instructed))$")
# These routes only admit durable work. Execution owns artifact changes, so
# accepting a correction never requires the author to wait for a stage.
_QUEUED = re.compile(r"^/(?:regen-(?:ref|state-ref|plate|prop)(?:-instructed)?|cover|styles/(?:direction|generate-samples|validation)|pages/\d+/(?:generate|corrections)|(?:characters|locations)/[^/]+/states/[^/]+/(?:regenerate|regenerate-instructed))$")
_REVIEW = re.compile(r"^/(?:pages/\d+/(?:corrections/preview|issues(?:/[^/]+/(?:accept|dismiss))?)|editorial/decisions|story-changes/preview)$")


_PART_ROUTE = re.compile(r"^/parts/(part_\d{4})(/.*)?$")
_STYLE_PRESENTATION = re.compile(r"^/styles/style_[0-9a-f]{16}$")
_APPROVAL = re.compile(r"^/approve/[a-z_]+$")


_CAST_REVIEW_REJECTION = "Compare the current character references before approving Cast. Resume Cast to run its visual review."


def cast_approval_was_rejected(method: str, suffix: str, status: int, body: bytes) -> bool:
    """Recognize only gates known to precede approval, holds and dispatch.

    Unknown conflicts remain durable receipts: some may follow side effects.
    The exact older message lets already-stored rejected actions recover too.
    """
    if method != "POST" or suffix != "/approve/cast" or status != 409:
        return False
    try:
        detail = json.loads(body).get("detail")
    except (ValueError, TypeError, AttributeError):
        return False
    return detail == _CAST_REVIEW_REJECTION or (
        isinstance(detail, dict) and detail.get("code") == "cast_approval_rejected"
    )


def _job_part(job) -> str | None:
    from .generation_jobs import job_part_id

    return job_part_id(job)


def _active_jobs(app, key: str) -> list:
    return [job for job in getattr(app.state, "generation_jobs", {}).values()
            if job.project_name == key and job.status in {"queued", "running"}]


def _live_task(app, key: str) -> bool:
    # Legacy live tasks are exclusive during rolling/test compatibility.
    return any(task is not None and not task.done() for task in
               (getattr(app.state, name, {}).get(key) for name in ("running_tasks", "style_tasks")))


def project_busy(app, key: str, part: str | None = None, *, series: bool = False) -> bool:
    """Whether new work must wait for work already in the project.

    Parts progress independently: a part's stage waits only for that part's
    jobs and series work (Style, Cast), and a series stage waits only for
    series work. Without a part or series scope the whole project counts.
    """
    if _live_task(app, key):
        return True
    for job in _active_jobs(app, key):
        if series:
            if _job_part(job) is None:
                return True
        elif part is None or _job_part(job) in {part, None}:
            return True
    return False


def mutation_conflicts(app, key: str, suffix: str, part: str | None = None,
                       method: str = "POST") -> bool:
    """Resource policy: independent presentation edits do not own all artwork.

    ``part`` is the part a route addresses; another part's work never blocks it.
    """
    jobs = _active_jobs(app, key)
    if _live_task(app, key):
        return True
    if part is not None:
        if method == "PATCH" and suffix == "":
            return False  # renaming a part changes no work
        jobs = [job for job in jobs if _job_part(job) in {part, None}]
    elif suffix in {"/parts", "/parts/export"}:
        # Appending a part or combining finished parts touches no running work.
        return False
    elif suffix.startswith("/story-bible"):
        # Story Bible edits wait only for an extraction writing the same Bible.
        # Removing, merging or undoing also waits for Adapt and Plan, which cite entities.
        takes_away = method == "DELETE" or suffix.endswith(("/merge", "/undo"))
        citing = {"extract", "adapt", "plan"} if takes_away else {"extract"}
        return any(job.kind == "pipeline_stage" and job.payload.get("stage") in citing for job in jobs)
    elif (suffix == "/run" or _APPROVAL.fullmatch(suffix) or suffix.startswith("/reset/")
          or suffix in {"/cast/references/keep", "/cast/reopen"}):
        # Series pipeline actions (Style, Cast) wait only for series work.
        jobs = [job for job in jobs if _job_part(job) is None]
    if suffix == "/styles/active":
        return any(job.kind not in {"style_sample", "style_suggest", "style_validation"} for job in jobs)
    # Approving a checkpoint changes no artwork. The cover that Cast starts on
    # completion reads only finished references, and anything approval chains
    # (Adapt) queues behind it, so the cover never holds approval back.
    if _APPROVAL.fullmatch(suffix):
        return any(job.kind != "project_cover" for job in jobs)
    # Naming or hiding a proof is presentation only; the suggestion list is
    # merged under the artifact lock, so it never waits for artwork.
    if _STYLE_PRESENTATION.fullmatch(suffix):
        return False
    # Author directions append independently under the artifact lock, each with
    # its own hold, so they queue behind other proofs instead of failing.
    if suffix == "/styles/direction":
        return any(job.kind not in {"style_sample", "style_validation"} for job in jobs)
    # Switching among stored languages rewrites every page's lettering, not art.
    if suffix == "/lettering/locale":
        return any(job.kind in {"pipeline_stage", "lettering_translation", "complete_page_draw"} for job in jobs)
    lettering = re.fullmatch(r"/pages/(\d+)/lettering(?:/reset)?", suffix)
    if lettering:
        number = int(lettering.group(1))
        return any(job.kind in {"pipeline_stage", "lettering_translation"}
                   or (job.kind == "complete_page_draw" and job.payload.get("page_number") == number)
                   for job in jobs)
    return bool(jobs)


def review_conflicts(app, key: str, suffix: str, part: str | None) -> bool:
    """Review records only wait for writers of their own saved evidence."""
    jobs = [job for job in _active_jobs(app, key)
            if part is None or _job_part(job) in {part, None}]
    page = re.fullmatch(r"/pages/(\d+)/issues(?:/[^/]+/(?:accept|dismiss))?", suffix)
    if page:
        return any(
            (job.kind == "complete_page_draw" and job.payload.get("page_number") == int(page.group(1)))
            or (job.kind == "pipeline_stage" and job.payload.get("stage") in {"extract", "adapt", "plan", "draw"})
            for job in jobs
        )
    if suffix == "/editorial/decisions":
        return any(job.kind == "pipeline_stage" and job.payload.get("stage") in {"extract", "adapt", "plan"}
                   for job in jobs)
    return False


class Admission:
    def __init__(self, root: Path):
        self.root = root
        self.draining = False
        self.active_requests = 0
        self.locks: dict[str, asyncio.Lock] = {}
        self.gate = asyncio.Lock()
        with self.journal() as db:
            db.execute("CREATE TABLE IF NOT EXISTS operational_intent (id INTEGER PRIMARY KEY CHECK(id=1), draining INTEGER NOT NULL)")
            row = db.execute("SELECT draining FROM operational_intent WHERE id=1").fetchone()
            self.draining = bool(row and row[0])

    def set_draining(self, draining: bool) -> None:
        """Explicit operator intent survives crashes; shutdown alone isn't intent."""
        with self.journal() as db:
            db.execute("INSERT OR REPLACE INTO operational_intent VALUES(1,?)", (int(draining),))
        self.draining = draining

    @contextmanager
    def journal(self):
        self.root.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.root / ".request-journal.sqlite3", timeout=30)
        db.execute("CREATE TABLE IF NOT EXISTS requests (account TEXT, route TEXT, key TEXT, fingerprint TEXT NOT NULL, status INTEGER, body BLOB, PRIMARY KEY(account,route,key))")
        db.commit()
        try:
            with db:
                yield db
        finally:
            db.close()

    @asynccontextmanager
    async def enter(self, key: str):
        lock = self.locks.setdefault(key, asyncio.Lock())
        async with lock:
            async with self.gate:
                self.active_requests += 1
            try:
                yield
            finally:
                self.active_requests -= 1


async def admission_middleware(request, call_next):
    match = _PROJECT.match(request.url.path)
    project_id, suffix = (match.group(1), match.group(2) or "") if match else ("", "")
    # Part routes share every suffix policy with their series-scoped forms.
    part_route = _PART_ROUTE.match(suffix)
    if part_route:
        suffix = part_route.group(2) or ""
    status_read = bool(match and request.method == "GET" and suffix == "/status")
    if not match or (not status_read and request.method not in {"POST", "PUT", "PATCH", "DELETE"}):
        return await call_next(request)
    if project_id in {"import-story", "short-stories"}:
        return await call_next(request)
    admission = request.app.state.admission
    try:
        auth = request.app.dependency_overrides.get(get_current_user, get_current_user)
        if auth is get_current_user:
            account = await auth(request, Response(), request.headers.get("authorization"), request.cookies.get(SESSION_COOKIE_NAME))
        else:
            import inspect
            account = auth()
            if inspect.isawaitable(account):
                account = await account
        if status_read:
            # Status can reconcile completed artifacts into pipeline state.
            # Serialize before dependencies load state, including queue admission.
            async with admission.enter(project_key(account, project_id)):
                return await call_next(request)
        key = request.headers.get("idempotency-key")
        if _PAID.fullmatch(suffix) and not key:
            raise HTTPException(400, {"code": "idempotency_key_required", "message": "An Idempotency-Key is required for this action."})
        if key is not None and (not key.strip() or len(key) > 200):
            raise HTTPException(400, "Invalid Idempotency-Key")
        # Finish preflight only rebuilds local derived artifacts. It must check
        # current inputs again even when an older client retains an interrupted
        # receipt; replaying a completed receipt could also return stale checks.
        # Keep all paid and publishing mutations on the existing receipt path.
        if request.method == "POST" and suffix == "/export/preflight":
            key = None
        route = f"{request.method} {request.url.path}"
        body = await request.body()
        # Cache-only recovery cannot submit OCR. Recompute current evidence,
        # including after a lost response, rather than replaying stale results.
        if request.method == "POST" and suffix == "/pages/checks/recover":
            try:
                recovery_body = json.loads(body)
            except ValueError:
                recovery_body = None
            if isinstance(recovery_body, dict) and recovery_body.get("allow_paid") is False:
                key = None
            elif not key:
                raise HTTPException(400, {"code": "idempotency_key_required", "message": "An Idempotency-Key is required for this action."})
        try:
            canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode() if body else b""
        except ValueError:
            canonical = body
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            fields = []
            async with request.form(max_part_size=form_part_cap_bytes(request.url.path, request.method)) as form:
                for name, value in form.multi_items():
                    if hasattr(value, "filename"):
                        fields.append((name, value.filename, hashlib.sha256(await value.read()).hexdigest()))
                    else:
                        fields.append((name, str(value)))
            canonical = json.dumps(sorted(fields), separators=(",", ":")).encode()
        fingerprint = hashlib.sha256(request.url.query.encode() + b"\0" + canonical).hexdigest()
        async with admission.enter(project_key(account, project_id)):
            # Cancelling unstarted page work must remain possible while that
            # work makes the project busy, including during a credit outage.
            if request.method == "POST" and suffix == "/jobs/cancel-queued-pages":
                return await call_next(request)
            if key:
                with admission.journal() as db:
                    row = db.execute("SELECT fingerprint,status,body FROM requests WHERE account=? AND route=? AND key=?", (account, route, key)).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise HTTPException(409, {"code": "idempotency_conflict", "message": "This action key was used with different input."})
                    if row[1] is None:
                        raise HTTPException(409, {"code": "idempotency_indeterminate", "message": "This action may have been accepted. Inspect project status before starting a new action."})
                    if cast_approval_was_rejected(request.method, suffix, row[1], row[2]):
                        # The prerequisite may now be satisfied. Re-evaluate it
                        # under the same project lock; no action was admitted.
                        with admission.journal() as db:
                            db.execute("DELETE FROM requests WHERE account=? AND route=? AND key=?", (account, route, key))
                    else:
                        return Response(row[2], status_code=row[1], media_type="application/json", headers={"Idempotency-Replayed": "true"})
            if admission.draining:
                raise HTTPException(503, {"code": "server_draining", "message": "Generation is paused for deployment."})
            durable = getattr(request.app.state, "durable_queue", None)
            if getattr(request.app.state, "durable_queue_required", False) is True and (durable is None or not durable.healthy):
                raise HTTPException(503, {"code": "queue_unavailable", "message": "Generation queue is unavailable. Saved work is preserved."})
            from .credits import reservation_leases_healthy
            if hasattr(request.app.state, "credit_leases_ready") and (
                not request.app.state.credit_leases_ready or not reservation_leases_healthy()
            ):
                raise HTTPException(503, {"code": "credits_unavailable", "message": "Credit authorization is temporarily unavailable. Try again when service is ready."})
            pkey = project_key(account, project_id)
            part = part_route.group(1) if part_route else None
            review_or_queue = request.method == "POST" and bool(_QUEUED.fullmatch(suffix) or _REVIEW.fullmatch(suffix))
            if _REVIEW.fullmatch(suffix) and review_conflicts(request.app, pkey, suffix, part):
                raise HTTPException(409, "This review's saved evidence is being updated. Other reviews remain available.")
            if not review_or_queue and any(job.project_name == pkey and getattr(job, "kind", None) == "lettering_translation" and job.status in {"queued", "running"}
                   and (part is None or _job_part(job) in {part, None})
                   for job in getattr(request.app.state, "generation_jobs", {}).values()):
                raise HTTPException(409, "Wait for project lettering translation to finish before changing this project.")
            if not review_or_queue and not _TARGETED.fullmatch(suffix) and mutation_conflicts(request.app, pkey, suffix, part, request.method):
                raise HTTPException(409, "Wait for all project jobs to finish before changing this project.")
            if not review_or_queue and _TARGETED.fullmatch(suffix):
                if any(job.project_name == pkey and job.status in {"queued", "running"}
                       and job.kind in {"pipeline_stage", "style_suggest"}
                       for job in request.app.state.generation_jobs.values()):
                    raise HTTPException(409, "Wait for the active project stage to finish.")
                for name in ("running_tasks", "style_tasks"):
                    task = getattr(request.app.state, name, {}).get(pkey)
                    if task is not None and not task.done():
                        raise HTTPException(409, "Wait for the active project stage to finish.")
            if key:
                with admission.journal() as db:
                    db.execute("INSERT INTO requests(account,route,key,fingerprint) VALUES(?,?,?,?)", (account, route, key, fingerprint))
            response = await call_next(request)
            if key:
                content = b"".join([chunk async for chunk in response.body_iterator])
                # Persist the response before returning any bytes to the browser.
                with admission.journal() as db:
                    db.execute("UPDATE requests SET status=?,body=? WHERE account=? AND route=? AND key=?", (response.status_code, content, account, route, key))
                return Response(content, status_code=response.status_code, headers=dict(response.headers), media_type=response.media_type)
            return response
    except StarletteHTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
