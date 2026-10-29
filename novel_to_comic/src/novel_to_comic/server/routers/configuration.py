"""Thin ops-token protected configuration proxy. No deployment decisions here."""
from __future__ import annotations

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field

from ..configuration import forward
from ..deployment_status import require_ops_token

router = APIRouter(dependencies=[Depends(require_ops_token)])
Digest = Annotated[str, Field(pattern=r'^[0-9a-f]{64}$')]


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    patch: dict[str, str] = Field(default_factory=dict, max_length=32)
    bundle_id: str | None = Field(default=None, pattern=r'^[0-9a-f-]{36}$')


class ApplyRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    request_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    plan_id: str = Field(pattern=r'^[0-9a-f-]{36}$')
    plan_digest: Digest


@router.get('/status')
def status(operation: UUID | None = None):
    return forward({'action': 'config_status', **({'operation_id': str(operation)} if operation else {})})


@router.get('/events')
def events(operation: UUID, after: int = Query(default=0, ge=0)):
    return forward({'action': 'config_events', 'operation_id': str(operation), 'after': after})


@router.post('/plan', status_code=202)
def plan(body: PlanRequest):
    return forward({'action': 'config_plan', **body.model_dump(exclude_none=True)})


@router.post('/apply', status_code=202)
def apply(body: ApplyRequest):
    return forward({'action': 'config_apply', **body.model_dump()})


@router.post('/bundles')
async def upload(request: Request):
    # Enforce before buffering or parsing JSON (Content-Length is only a hint).
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 3 * 1024 * 1024:
            raise HTTPException(413, {'code': 'upload_too_large'})
        data.extend(chunk)
    try:
        body = json.loads(data)
        if not isinstance(body, dict) or set(body) != {'bundle', 'manifest', 'signature'}:
            raise ValueError('invalid_shape')
    except (ValueError, TypeError):
        raise HTTPException(422, {'code': 'invalid_request'}) from None
    # Run blocking host transport outside the event loop, just like sync routes.
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(forward, {'action': 'config_stage_bundle', **body}, upload=True)
