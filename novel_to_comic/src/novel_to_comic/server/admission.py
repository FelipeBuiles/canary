"""Serialize project mutations and durably deduplicate explicit user actions.

The journal lives on the same persistent volume as project artifacts. An accepted
but interrupted request is never automatically dispatched again after restart.
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

from .auth import SESSION_COOKIE_NAME, get_current_user
from .deps import project_key

_PROJECT = re.compile(r"^/api/projects/([^/]+)(/.*)?$")
_PAID = re.compile(r"^/(?:run|regen-[^/]+|cover|approve/(?:brief|cast)|styles/(?:direction|suggest|generate-samples|validation)|pages/\d+/(?:generate|analyze|visual-review|corrections)|(?:characters|locations)/[^/]+/states/[^/]+/(?:regenerate|regenerate-instructed)|story-changes/[^/]+/apply)$")
_LETTERING = re.compile(r"^/(?:pages/\d+/lettering(?:/(?:preview|reset))?|lettering/style)$")
_TARGETED = re.compile(r"^/(?:regen-(?!extract)[^/]+|cover|pages/\d+/(?:generate|analyze|visual-review|corrections)|(?:characters|locations)/[^/]+/states/[^/]+/(?:regenerate|regenerate-instructed))$")


def project_busy(app, key: str) -> bool:
    for name in ("running_tasks", "style_tasks"):
        task = getattr(app.state, name, {}).get(key)
        if task is not None and not task.done():
            return True
    return any(job.project_name == key and job.status in {"queued", "running"}
               for job in getattr(app.state, "generation_jobs", {}).values())


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
    status_read = bool(match and request.method == "GET" and match.group(2) == "/status")
    if not match or (not status_read and request.method not in {"POST", "PUT", "PATCH", "DELETE"}):
        return await call_next(request)
    project_id, suffix = match.group(1), match.group(2) or ""
    if project_id in {"import-story", "short-stories"}:
        return await call_next(request)
    admission = request.app.state.admission
    provider_free_lettering = bool(_LETTERING.fullmatch(suffix)) and request.method in {"POST", "PUT"}
    targeted = bool(_TARGETED.fullmatch(suffix)) or provider_free_lettering
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
        route = f"{request.method} {request.url.path}"
        body = await request.body()
        try:
            canonical = json.dumps(json.loads(body), sort_keys=True, separators=(",", ":")).encode() if body else b""
        except ValueError:
            canonical = body
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            fields = []
            async with request.form() as form:
                for name, value in form.multi_items():
                    if hasattr(value, "filename"):
                        fields.append((name, value.filename, hashlib.sha256(await value.read()).hexdigest()))
                    else:
                        fields.append((name, str(value)))
            canonical = json.dumps(sorted(fields), separators=(",", ":")).encode()
        fingerprint = hashlib.sha256(request.url.query.encode() + b"\0" + canonical).hexdigest()
        async with admission.enter(project_key(account, project_id)):
            if key:
                with admission.journal() as db:
                    row = db.execute("SELECT fingerprint,status,body FROM requests WHERE account=? AND route=? AND key=?", (account, route, key)).fetchone()
                if row:
                    if row[0] != fingerprint:
                        raise HTTPException(409, {"code": "idempotency_conflict", "message": "This action key was used with different input."})
                    if row[1] is None:
                        raise HTTPException(409, {"code": "idempotency_indeterminate", "message": "This action may have been accepted. Inspect project status before starting a new action."})
                    return Response(row[2], status_code=row[1], media_type="application/json", headers={"Idempotency-Replayed": "true"})
            if admission.draining:
                raise HTTPException(503, {"code": "server_draining", "message": "Generation is paused for deployment."})
            from .credits import reservation_leases_healthy
            if not provider_free_lettering and hasattr(request.app.state, "credit_leases_ready") and (
                not request.app.state.credit_leases_ready or not reservation_leases_healthy()
            ):
                raise HTTPException(503, {"code": "credits_unavailable", "message": "Credit authorization is temporarily unavailable. Try again when service is ready."})
            pkey = project_key(account, project_id)
            if not targeted and project_busy(request.app, pkey):
                raise HTTPException(409, "Wait for all project jobs to finish before changing this project.")
            if targeted:
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
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers)
