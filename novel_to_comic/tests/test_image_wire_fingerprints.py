"""Provider-free fingerprints of every paid image route, pinned before the transports merge.

Each case drives a public entry point (Draw's page execution, Look's
``generate_wire_image``) against a scripted gateway and records only what
leaves Canary: the HTTP requests, the usage-event and credit-ledger database
writes, the job holds retained for reconciliation, and the result or error the
caller receives. ``fixtures/image_wire_fingerprints.json`` holds the baseline;
regenerate it with ``CANARY_UPDATE_IMAGE_WIRE_FINGERPRINTS=1`` only when a
change to the money path is intended.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import os
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest
from PIL import Image

from novel_to_comic import image_route_fallback
from novel_to_comic.ai import generate_wire_image
from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.config import Config
from novel_to_comic.models.draw import PageRenderCorrection, RetryProvenance
from novel_to_comic.page_drawing import (
    _integrated_page_profile,
    compile_page_generation_request,
    complete_page_adapter,
    fal_sunburst_page_capability_profile,
    muse_page_capability_profile,
    nano_banana_21_page_capability_profile,
    openai_page_capability_profile,
    prepare_frozen_page_request,
    runware_first_page_capability_profile,
    runware_only_page_capability_profile,
    runware_page_transport,
    select_book_edition,
    sunburst_fallback_page_capability_profile,
)
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_DISCRIMINATOR,
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireReference,
    ProviderWireRequest,
)
from novel_to_comic.server import credits, db as server_db
from novel_to_comic.target_artifacts import TargetArtifacts
from tests.test_complete_page_draw import _inventory, _page, _reference_files

from .page_draw_support import execute_draw

BASELINE = Path(__file__).parent / "fixtures" / "image_wire_fingerprints.json"
UPDATE = os.environ.get("CANARY_UPDATE_IMAGE_WIRE_FINGERPRINTS") == "1"
GATEWAY = "http://gateway.test"
API_KEY = "sk-fingerprint-secret"
USER = "user-fingerprint"
PROJECT = "project-fingerprint"
JOB = "job-fingerprint"

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:\+00:00|Z)?")
_VOLATILE_HEADERS = {"host", "accept", "accept-encoding", "connection", "user-agent", "content-length"}
_VOLATILE_KEYS = {"latency_ms", "finished_at", "started_at", "ai_trace_id", "p_owner"}
_LONG = 400


# Gateway outcomes ---------------------------------------------------------------

def _png(width: int, height: int) -> bytes:
    image = io.BytesIO()
    Image.new("RGB", (width, height), (40, 90, 160)).save(image, format="PNG")
    return image.getvalue()


Outcome = Callable[[httpx.Request], httpx.Response]


def ok(model: str, size: tuple[int, int] = (1024, 1536), *, priced: bool = True) -> Outcome:
    body: dict[str, Any] = {
        "id": "resp-fingerprint", "model": model,
        "data": [{"b64_json": base64.b64encode(_png(*size)).decode()}],
        "usage": {"input_tokens": 1200, "output_tokens": 4160,
                  "input_tokens_details": {"text_tokens": 1000, "image_tokens": 200}},
    }
    headers = {"x-litellm-response-cost": "0.0421"} if priced else {}
    if not priced:
        body.pop("usage")
    return lambda request: httpx.Response(200, json=body, headers=headers)


def refused() -> Outcome:
    body = {"model": "refusal", "error": {"code": "content_policy_violation", "message": "refused"}}
    return lambda request: httpx.Response(200, json=body)


def http_error(status: int, message: str) -> Outcome:
    return lambda request: httpx.Response(status, json={"error": {"message": message}})


def timeout() -> Outcome:
    def outcome(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("response lost after the request was sent", request=request)
    return outcome


def openai_failure(detail: str) -> Outcome:
    """A gateway custom handler failure: the proxy wraps it in a generic 500."""
    return http_error(500, f"Openai-streamException - {detail}")


def runware_failure(detail: str) -> Outcome:
    return http_error(500, f"Runware-streamException - {detail}")


OPENAI_CAPACITY = "OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=429; detail=code=rate_limit"
OPENAI_MODERATION = ("OpenAI image submit failed for gpt-image-2.5-sunburst; upstream_status=400; "
                     "detail=code=moderation_blocked")
RUNWARE_CREDITS = "Runware image submit failed for gpt-image-2.5-sunburst; upstream_status=402"
RUNWARE_UNKNOWN = "Runware image unknown_outcome failed for gpt-image-2.5-sunburst"


# Recording seams ----------------------------------------------------------------

class _Executed:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Statement:
    def __init__(self, ledger: "_Ledger", record: dict[str, Any]) -> None:
        self._ledger, self._record = ledger, record

    def eq(self, column: str, value: Any) -> "_Statement":
        self._record["where"] = {column: value}
        return self

    def execute(self) -> _Executed:
        self._ledger.writes.append(self._record)
        return _Executed(True)


class _Table:
    def __init__(self, ledger: "_Ledger", name: str) -> None:
        self._ledger, self._name = ledger, name

    def insert(self, row: dict[str, Any], **_: Any) -> _Statement:
        return _Statement(self._ledger, {"op": "insert", "table": self._name, "row": row})

    def update(self, row: dict[str, Any], **_: Any) -> _Statement:
        return _Statement(self._ledger, {"op": "update", "table": self._name, "row": row})


class _Ledger:
    """The database as the usage events and credit ledger see it."""

    def __init__(self) -> None:
        self.writes: list[dict[str, Any]] = []

    def table(self, name: str) -> _Table:
        return _Table(self, name)

    def rpc(self, name: str, params: dict[str, Any]) -> _Statement:
        return _Statement(self, {"op": "rpc", "name": name, "params": params})


def _multipart(content: bytes, boundary: str) -> dict[str, Any]:
    fields: dict[str, str] = {}
    files: list[dict[str, Any]] = []
    for chunk in content.split(b"--" + boundary.encode())[1:-1]:
        head, _, body = chunk.removeprefix(b"\r\n").partition(b"\r\n\r\n")
        body = body.removesuffix(b"\r\n")
        headers = dict(
            line.split(": ", 1) for line in head.decode().split("\r\n") if ": " in line
        )
        disposition = dict(re.findall(r'(\w+)="([^"]*)"', headers["Content-Disposition"]))
        if "filename" in disposition:
            files.append({
                "field": disposition["name"], "filename": disposition["filename"],
                "content_type": headers.get("Content-Type"),
                "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest(),
            })
        else:
            fields[disposition["name"]] = body.decode()
    return {"form": dict(sorted(fields.items())), "files": files}


def _request_record(request: httpx.Request) -> dict[str, Any]:
    headers = {
        name.lower(): value for name, value in request.headers.items()
        if name.lower() not in _VOLATILE_HEADERS
    }
    if headers.get("authorization") == f"Bearer {API_KEY}":
        headers["authorization"] = "Bearer <redacted>"
    content_type = headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        headers["content-type"] = "multipart/form-data; boundary=<boundary>"
        body: Any = _multipart(request.content, content_type.split("boundary=", 1)[1])
    elif content_type == "application/json":
        body = {"json": json.loads(request.content)}
    else:
        body = {"sha256": hashlib.sha256(request.content).hexdigest()}
    return {"method": request.method, "url": str(request.url), "headers": dict(sorted(headers.items())), "body": body}


@dataclass
class Capture:
    requests: list[dict[str, Any]] = field(default_factory=list)
    ledger: _Ledger = field(default_factory=_Ledger)
    retained: list[str | None] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    unscripted: list[str] = field(default_factory=list)

    def script(self, outcomes: list[Outcome]) -> None:
        self.outcomes.extend(outcomes)


@pytest.fixture
def capture(monkeypatch, tmp_path):
    """Route every HTTP request to the scripted gateway and record the seams."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(credits, "_unsettled_jobs", set())
    for circuit in (image_route_fallback.OPENAI_SUNBURST_CIRCUIT, image_route_fallback.RUNWARE_CIRCUIT):
        circuit.reset()
    state = Capture()
    monkeypatch.setattr(server_db, "get_db", lambda: state.ledger)
    retain = credits.retain_ambiguous_job

    def recording_retain(job_id: str | None) -> None:
        state.retained.append(job_id)
        retain(job_id)

    monkeypatch.setattr(credits, "retain_ambiguous_job", recording_retain)

    async def gateway(transport, request: httpx.Request) -> httpx.Response:
        await request.aread()
        state.requests.append(_request_record(request))
        if not state.outcomes:
            state.unscripted.append(str(request.url))
            raise httpx.ConnectError("unscripted submission", request=request)
        return state.outcomes.pop(0)(request)

    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", gateway)
    yield state
    for circuit in (image_route_fallback.OPENAI_SUNBURST_CIRCUIT, image_route_fallback.RUNWARE_CIRCUIT):
        circuit.reset()


# Normalisation ------------------------------------------------------------------

def _normalise(record: Any, tmp_path: Path) -> Any:
    """Replace run-specific values (event ids, clocks, paths) with stable labels."""
    labels: dict[str, str] = {}

    def text(value: str) -> Any:
        value = value.replace(str(tmp_path.resolve()), "<tmp>").replace(str(tmp_path), "<tmp>")
        value = _UUID.sub(lambda m: labels.setdefault(m.group(0), f"<uuid-{len(labels) + 1}>"), value)
        value = _TIMESTAMP.sub("<timestamp>", value)
        if len(value) > _LONG:
            return {"chars": len(value), "sha256": hashlib.sha256(value.encode()).hexdigest()}
        return value

    def walk(value: Any, key: str | None = None) -> Any:
        if key in _VOLATILE_KEYS and value is not None:
            return "<volatile>"
        if isinstance(value, dict):
            return {k: walk(value[k], k) for k in sorted(value)}
        if isinstance(value, (list, tuple)):
            return [walk(item) for item in value]
        if isinstance(value, str):
            return text(value)
        return value

    return walk(record)


def _outcome_of(run: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"result": run()}
    except Exception as exc:
        return {"error": {"type": type(exc).__name__, "phase": getattr(exc, "phase", None)}}


def _fingerprint(capture: Capture, outcome: dict[str, Any], tmp_path: Path) -> dict[str, Any]:
    assert not capture.unscripted, f"submitted beyond the scripted outcomes: {capture.unscripted}"
    assert not capture.outcomes, f"{len(capture.outcomes)} scripted outcomes were never requested"
    return _normalise({
        "requests": capture.requests,
        "ledger": capture.ledger.writes,
        "hold_retained": bool(capture.retained),
        "jobs_awaiting_reconciliation": sorted(credits._unsettled_jobs),
        **outcome,
    }, tmp_path)


# Draw ---------------------------------------------------------------------------

def _draw_config(profile) -> Config:
    lettering = "integrated" if profile.exact_visible_lettering else "editable"
    draw_model = "image-nano-banana-2.1" if profile.model == "gemini-nano-banana-2.1" else "image-sunburst"
    return Config(litellm_base_url=GATEWAY, litellm_api_key=API_KEY, lettering_mode=lettering,
                  draw_model=draw_model)


def _compiled(profile, *, references: bool, parent: bytes | None = None):
    files = _reference_files(Path("."))
    inventory = _inventory()
    if not references:
        inventory = inventory.model_copy(update={"references": [
            ref.model_copy(update={"kind": "character", "requires_image": False}) for ref in inventory.references
        ]})
        files = {}
    page = _page()
    options: dict[str, Any] = {}
    if parent is not None:
        options = {
            "correction": PageRenderCorrection(
                issue_ids=(), page_number=page.page_number,
                comic_page_revision=page.revision, comic_page_sha256=page.content_sha256,
                parent_render_revision=1, parent_render_image_sha256=hashlib.sha256(parent).hexdigest(),
                mode="instructed", instruction="Correct the hand.", note="Correct the hand.",
            ),
            "edit_source_bytes": parent,
        }
    return compile_page_generation_request(
        page, select_book_edition(edition_id="fingerprint", profile=profile), inventory, files,
        retry=RetryProvenance(attempt=1), **options,
    )


def _draw(capture: Capture, tmp_path: Path, profile, outcomes, *, references=True, correction=False):
    model, size = _draw_model_and_size(profile)
    compiled = _compiled(profile, references=references, parent=_png(*size) if correction else None)
    adapter = complete_page_adapter(_draw_config(profile), profile)
    artifacts = TargetArtifacts(tmp_path / "project")
    page = _page()

    async def run(**inputs):
        with ai_request_context(user_id=USER, project_id=PROJECT, project_name="fingerprint", stage="draw",
                                job_id=JOB, page_number=page.page_number, is_correction=correction):
            return await execute_draw(compiled, adapter=adapter, artifacts=artifacts, page=page, **inputs)

    if correction:
        initial = _compiled(profile, references=references)
        capture.script([ok(model, size)])

        async def first():
            with ai_request_context(user_id=USER, project_id=PROJECT, job_id=JOB):
                return await execute_draw(initial, adapter=adapter, artifacts=artifacts, page=page)
        asyncio.run(first())
        capture.requests.clear()
        capture.ledger.writes.clear()
        capture.retained.clear()
    capture.script(outcomes)
    inputs = {"parent_render_revision": 1} if correction else {}
    return _fingerprint(capture, _outcome_of(lambda: asyncio.run(run(**inputs)).model_dump(mode="json")), tmp_path)


def _draw_model_and_size(profile) -> tuple[str, tuple[int, int]]:
    size = (profile.output_width, profile.output_height)
    return {
        "openai-fal": "openai/gpt-image-2.5-sunburst",
        "runware-openai-fal": "runware/gpt-image-2.5-sunburst",
        "fal-queue": "fal-queue/openai/gpt-image-2.5/sunburst",
        "openai": f"openai/{profile.model}",
        "openrouter": f"openrouter/{profile.model}",
        "vertex-multimodal": f"vertex_ai/{profile.model}",
        "runware": f"runware/{profile.model}",
    }[profile.provider], size


SUNBURST = sunburst_fallback_page_capability_profile()
RUNWARE_FIRST = runware_first_page_capability_profile()
FAL = fal_sunburst_page_capability_profile()
FLARE = openai_page_capability_profile("gpt-image-2.5-flare", quality="high")
MUSE = muse_page_capability_profile()
NANO = nano_banana_21_page_capability_profile()
OPENAI_OK = ok("openai/gpt-image-2.5-sunburst")
FAL_OK = ok("fal-queue/openai/gpt-image-2.5/sunburst")
RUNWARE_OK = ok("runware/gpt-image-2.5-sunburst")

DRAW_CASES: dict[str, tuple[Any, list[Outcome], dict[str, Any]]] = {}
for lettering, wrap in (("editable", lambda p: p), ("integrated", _integrated_page_profile)):
    sunburst, runware_first = wrap(SUNBURST), wrap(RUNWARE_FIRST)
    DRAW_CASES.update({
        f"sunburst-{lettering}-openai-success": (sunburst, [OPENAI_OK], {}),
        f"sunburst-{lettering}-openai-success-no-references": (sunburst, [OPENAI_OK], {"references": False}),
        f"sunburst-{lettering}-openai-unpriced-success": (sunburst, [ok("openai/gpt-image-2.5-sunburst", priced=False)], {}),
        f"sunburst-{lettering}-openai-capacity-then-fal": (sunburst, [openai_failure(OPENAI_CAPACITY), FAL_OK], {}),
        f"sunburst-{lettering}-openai-timeout-absorbed-then-fal": (sunburst, [timeout(), FAL_OK], {}),
        f"sunburst-{lettering}-openai-timeout-then-fal-timeout": (sunburst, [timeout(), timeout()], {}),
        f"sunburst-{lettering}-openai-moderation-stops": (sunburst, [openai_failure(OPENAI_MODERATION)], {}),
        f"sunburst-{lettering}-openai-http-400-stops": (sunburst, [http_error(400, "bad request")], {}),
        f"sunburst-{lettering}-openai-refusal-payload": (sunburst, [refused()], {}),
        f"runware-first-{lettering}-runware-success": (runware_first, [RUNWARE_OK], {}),
        f"runware-first-{lettering}-credits-then-openai": (runware_first, [runware_failure(RUNWARE_CREDITS), OPENAI_OK], {}),
        f"runware-first-{lettering}-credits-then-openai-timeout-then-fal": (
            runware_first, [runware_failure(RUNWARE_CREDITS), timeout(), FAL_OK], {}),
        f"runware-first-{lettering}-runware-timeout-stops": (runware_first, [timeout()], {}),
        f"runware-first-{lettering}-runware-unknown-outcome-stops": (runware_first, [runware_failure(RUNWARE_UNKNOWN)], {}),
    })
DRAW_CASES.update({
    "sunburst-editable-correction-openai-success": (SUNBURST, [OPENAI_OK], {"correction": True}),
    "fal-editable-success": (FAL, [FAL_OK], {}),
    "fal-integrated-success": (_integrated_page_profile(FAL), [FAL_OK], {}),
    "fal-editable-timeout": (FAL, [timeout()], {}),
    "fal-editable-http-400": (FAL, [http_error(400, "bad request")], {}),
    "openai-flare-editable-success": (FLARE, [ok("openai/gpt-image-2.5-flare")], {}),
    "openai-flare-editable-success-no-references": (FLARE, [ok("openai/gpt-image-2.5-flare")], {"references": False}),
    "openai-flare-editable-refusal-payload": (FLARE, [refused()], {}),
    "openai-flare-editable-timeout": (FLARE, [timeout()], {}),
    "muse-editable-success": (MUSE, [ok("openrouter/meta/muse-image", (1280, 1920))], {}),
    "muse-integrated-success": (_integrated_page_profile(MUSE), [ok("openrouter/meta/muse-image", (1280, 1920))], {}),
    "muse-editable-http-400": (MUSE, [http_error(400, "bad request")], {}),
    "nano-banana-editable-success": (NANO, [ok("vertex_ai/gemini-nano-banana-2.1", (848, 1264))], {}),
    "nano-banana-integrated-success": (
        _integrated_page_profile(NANO), [ok("vertex_ai/gemini-nano-banana-2.1", (848, 1264))], {}),
    "nano-banana-editable-success-no-references": (
        NANO, [ok("vertex_ai/gemini-nano-banana-2.1", (848, 1264))], {"references": False}),
    "nano-banana-editable-correction-success": (
        NANO, [ok("vertex_ai/gemini-nano-banana-2.1", (848, 1264))], {"correction": True}),
    "nano-banana-editable-timeout": (NANO, [timeout()], {}),
    "nano-banana-editable-http-400": (NANO, [http_error(400, "bad request")], {}),
    "nano-banana-editable-refusal-payload": (NANO, [refused()], {}),
})


@pytest.mark.parametrize("case", sorted(DRAW_CASES))
def test_draw_route_fingerprint(case, capture, tmp_path):
    profile, outcomes, options = DRAW_CASES[case]
    _check(f"draw/{case}", _draw(capture, tmp_path, profile, outcomes, **options))


LABS_RUNWARE = runware_only_page_capability_profile("minimax-h3-image")


@pytest.mark.parametrize("case,outcomes", [
    ("success", [ok("runware/minimax-h3-image")]),
    ("provider-error", [runware_failure("Runware image submit failed for minimax-h3-image; upstream_status=500")]),
    ("timeout", [timeout()]),
], ids=["success", "provider-error", "timeout"])
def test_labs_runware_page_route_fingerprint(case, outcomes, capture, tmp_path):
    """Labs submits a prepared page straight to one Runware route."""
    compiled = _compiled(LABS_RUNWARE, references=True)
    prepared = prepare_frozen_page_request(compiled.request, compiled.reference_bytes, LABS_RUNWARE)
    transport = runware_page_transport(_draw_config(LABS_RUNWARE), LABS_RUNWARE)

    async def run():
        with ai_request_context(user_id=USER, project_id=PROJECT, job_id=JOB):
            result = await transport.generate(prepared)
        return {**result.model_dump(mode="json", exclude={"image_bytes"}),
                "image_sha256": hashlib.sha256(result.image_bytes).hexdigest()}

    capture.script(outcomes)
    _check(f"labs-runware-page/{case}", _fingerprint(capture, _outcome_of(lambda: asyncio.run(run())), tmp_path))


# Look (Style and Cast images) -------------------------------------------------------

LOOK_REFERENCES = (("style", "style:proof", b"style-proof-bytes"), ("character", "character:ward", b"ward-bytes"))


def _look_wire(alias: str, provider_key: str, provider_model: str, route: str, *,
               width: int, height: int, controls=(), references: bool) -> ProviderWireRequest:
    refs = []
    if references:
        Path("refs").mkdir(exist_ok=True)
        for index, (role, label, data) in enumerate(LOOK_REFERENCES):
            path = Path("refs") / f"{role}.png"
            path.write_bytes(data)
            refs.append(ProviderWireReference(
                index=index, source_path=str(path), content_sha256=hashlib.sha256(data).hexdigest(),
                role=role, role_label=label, instruction=f"Use the {role} reference.",
                provider_binding=str(index), entity_id="ward" if role == "character" else None,
                appearance_state_id=None, authority_scope="identity" if role == "character" else "rendering",
                preserve_facets=("palette",), ignore_facets=("pose",),
            ))
    wire = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR, schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias=alias, expected_route=route, provider_key=provider_key,
        configured_provider_model=provider_model, prompt_parts=("A lighthouse keeper at dusk, ink and wash.",),
        references=tuple(refs), width=width, height=height, structured_aspect=None,
        controls=tuple(controls), compiled_request_sha256="c" * 64, execution_fingerprint="",
    )
    return replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())


LOOK_ROUTES = {
    "sunburst": dict(alias="image-sunburst", provider_key="openai-fal", provider_model="gpt-image-2.5-sunburst",
                     route="gpt_image_2", width=1024, height=1280, controls=(("quality", "medium"),)),
    "runware-first": dict(alias="image-sunburst", provider_key="runware-openai-fal",
                          provider_model="gpt-image-2.5-sunburst", route="gpt_image_2",
                          width=1024, height=1280, controls=(("quality", "medium"),)),
    "flare": dict(alias="image-flare", provider_key="openai", provider_model="openai/gpt-image-2.5-flare",
                  route="gpt_image_2", width=1024, height=1280, controls=(("quality", "high"),)),
    "nano-banana": dict(alias="image-nano-banana-2.1", provider_key="vertex-multimodal",
                        provider_model="vertex-multimodal/gemini-nano-banana-2.1", route="nano_banana_21",
                        width=848, height=1264),
    "muse": dict(alias="image-muse", provider_key="openrouter", provider_model="openrouter-image/meta/muse-image",
                 route="muse_image", width=1280, height=1920),
    "seedream": dict(alias="image-seedream-v5-lite", provider_key="fal-queue",
                     provider_model="fal-queue/bytedance/seedream/v5/lite/edit", route="seedream",
                     width=1024, height=1280),
    "minimax": dict(alias="image-minimax-h3-runware", provider_key="runware",
                    provider_model="runware/minimax-h3-image", route="minimax_h3", width=1024, height=1536),
}
LOOK_MODELS = {
    "sunburst": "openai/gpt-image-2.5-sunburst", "runware-first": "runware/gpt-image-2.5-sunburst",
    "flare": "openai/gpt-image-2.5-flare", "nano-banana": "vertex_ai/gemini-nano-banana-2.1",
    "muse": "openrouter/meta/muse-image", "seedream": "fal-queue/bytedance/seedream/v5/lite/edit",
    "minimax": "runware/minimax-h3-image",
}

#: Aliases with no configured image price: a credited call fails closed before
#: submission, so their wire shape is pinned on an uncredited (no user) call.
UNPRICED_LOOK_ROUTES = {"muse", "seedream"}

LOOK_CASES: dict[str, tuple[str, list[Outcome], bool]] = {}
for name, route in LOOK_ROUTES.items():
    size = (route["width"], route["height"])
    LOOK_CASES.update({
        f"{name}-success": (name, [ok(LOOK_MODELS[name], size)], True),
        f"{name}-success-no-references": (name, [ok(LOOK_MODELS[name], size)], False),
        f"{name}-unpriced-success": (name, [ok(LOOK_MODELS[name], size, priced=False)], True),
        f"{name}-refusal-payload": (name, [refused()], True),
        f"{name}-http-400": (name, [http_error(400, "bad request")], True),
    })
    if name != "sunburst":
        LOOK_CASES[f"{name}-timeout"] = (name, [timeout()], True)
    if name in UNPRICED_LOOK_ROUTES:
        LOOK_CASES[f"{name}-credited-call-fails-closed"] = (name, [], True)
LOOK_CASES.update({
    "sunburst-openai-capacity-then-fal": ("sunburst", [openai_failure(OPENAI_CAPACITY), ok(
        "fal-queue/openai/gpt-image-2.5/sunburst", (1024, 1280))], True),
    "sunburst-openai-timeout-absorbed-then-fal": ("sunburst", [timeout(), ok(
        "fal-queue/openai/gpt-image-2.5/sunburst", (1024, 1280))], True),
    "sunburst-openai-timeout-then-fal-timeout": ("sunburst", [timeout(), timeout()], True),
    "sunburst-openai-moderation-stops": ("sunburst", [openai_failure(OPENAI_MODERATION)], True),
    "runware-first-credits-then-openai": ("runware-first", [runware_failure(RUNWARE_CREDITS), ok(
        "openai/gpt-image-2.5-sunburst", (1024, 1280))], True),
    "runware-first-credits-then-openai-timeout-then-fal": ("runware-first", [
        runware_failure(RUNWARE_CREDITS), timeout(), ok("fal-queue/openai/gpt-image-2.5/sunburst", (1024, 1280))], True),
    "runware-first-unknown-outcome-stops": ("runware-first", [runware_failure(RUNWARE_UNKNOWN)], True),
})


@pytest.mark.parametrize("case", sorted(LOOK_CASES))
def test_look_route_fingerprint(case, capture, tmp_path):
    route, outcomes, references = LOOK_CASES[case]
    wire = _look_wire(**LOOK_ROUTES[route], references=references)
    config = Config(litellm_base_url=GATEWAY, litellm_api_key=API_KEY)

    credited = route not in UNPRICED_LOOK_ROUTES or case.endswith("fails-closed")

    async def run():
        with ai_request_context(user_id=USER if credited else None, project_id=PROJECT,
                                project_name="fingerprint", stage="style", job_id=JOB):
            result = await generate_wire_image(config=config, wire=wire, output_path=Path("out") / "look.png",
                                               feature="style.sample")
        return {
            "value": str(result.value), "usage": result.usage.model_dump(mode="json") if result.usage else None,
            "provider_request_id": result.provider_request_id,
            "actual_provider_model": result.actual_provider_model,
            "response_metadata": result.response_metadata,
            "output_sha256": hashlib.sha256(Path(result.value).read_bytes()).hexdigest(),
        }

    capture.script(outcomes)
    _check(f"look/{case}", _fingerprint(capture, _outcome_of(lambda: asyncio.run(run())), tmp_path))


# Baseline ---------------------------------------------------------------------------

_updated: dict[str, Any] = {}


def _check(key: str, actual: dict[str, Any]) -> None:
    if UPDATE:
        _updated[key] = actual
        merged = {**(json.loads(BASELINE.read_text()) if BASELINE.exists() else {}), **_updated}
        BASELINE.write_text(json.dumps(dict(sorted(merged.items())), indent=1, sort_keys=True) + "\n")
        return
    baseline = json.loads(BASELINE.read_text())
    assert key in baseline, f"{key} has no baseline; regenerate with CANARY_UPDATE_IMAGE_WIRE_FINGERPRINTS=1"
    assert actual == baseline[key]
