"""Admitted hosted close-up reads and entirely local evidence recovery.

The recognition cache contains pixels/provider receipts, never expected text.
Only ``run_checks`` can submit. Every attempt is journaled before the HTTP call.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import os
import threading
import time
import uuid
from decimal import Decimal

import httpx
from PIL import Image

from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.config import TEXTRACT_MINIMUM_CONFIDENCE, TEXTRACT_MODEL, TEXTRACT_REGION, mock_mode_active
from novel_to_comic.crop_ocr import MAX_CROPS, MAX_CROP_PIXELS, MAX_PAGE_PIXELS, PAGE_TIMEOUT_SECONDS
from novel_to_comic.model_costs import get_pricing_resolver
from novel_to_comic.models.crop_ocr import CropOCRLine, CropOCRRead, CropOCRReport
from novel_to_comic.models.textract_ocr import TextractAttempt, TextractCrop, TextractPlan
from novel_to_comic.target_artifacts import ArtifactMissing
from novel_to_comic.text_utils import normalize_display_text

PREPROCESSING = "textract_png_crop_v1"
CONVERTER = "textract_lines_v1"
MAX_BYTES = 4_000_000
_preparation = threading.Lock()


def enabled() -> bool:
    return os.environ.get("CANARY_TEXTRACT_ENABLED", "").lower() in {"1", "true"}


def fingerprint() -> str:
    return f"{TEXTRACT_MODEL}:{TEXTRACT_REGION}:{PREPROCESSING}:{CONVERTER}:{TEXTRACT_MINIMUM_CONFIDENCE}"


def _hash(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def plan_identity(render, extraction, disputed) -> str:
    return _hash({"image": render.image_sha256, "preprocessing": PREPROCESSING,
        "regions": [item.model_dump(mode="json") for item in extraction.observed_regions],
        "observations": [item.id for item in disputed]})


def recognition_identity(render, crop_sha256: str) -> str:
    return _hash([render.image_sha256, crop_sha256, PREPROCESSING, TEXTRACT_MODEL, TEXTRACT_REGION])


def prepare_plan(*, render, extraction, disputed, artifacts, deadline: float) -> TextractPlan | None:
    """Decode one source at a time across pages; keep HTTP work outside this lock."""
    identity = plan_identity(render, extraction, disputed)
    try:
        return artifacts.read_textract_plan(render.page_number, render.revision, identity)
    except ArtifactMissing:
        pass
    if not _preparation.acquire(timeout=max(0, deadline - time.monotonic())):
        return None
    try:
        if time.monotonic() >= deadline:
            return None
        image_bytes = artifacts.read_render(render.page_number, render.revision)
        if hashlib.sha256(image_bytes).hexdigest() != render.image_sha256:
            raise ValueError("Hosted OCR source differs from saved render")
        from novel_to_comic.page_ocr import tight_region_id
        regions = {item.id: item for item in extraction.observed_regions}
        crops = []
        with Image.open(io.BytesIO(image_bytes)) as source:
            if source.width * source.height > MAX_PAGE_PIXELS:
                crops = [TextractCrop(observation_id=item.id, status="over_budget") for item in disputed]
            else:
                with source.convert("RGB") as image:
                    for index, observation in enumerate(disputed):
                        if time.monotonic() >= deadline:
                            # Crops already saved are reusable; an incomplete plan is never frozen.
                            return None
                        region = regions.get(tight_region_id(observation.id))
                        if index >= MAX_CROPS or region is None:
                            crops.append(TextractCrop(observation_id=observation.id,
                                status="over_budget" if index >= MAX_CROPS else "no_region"))
                            continue
                        xs, ys = zip(*region.polygon, strict=True)
                        bounds = (max(0, math.floor((min(xs) - .01) * image.width)),
                            max(0, math.floor((min(ys) - .01) * image.height)),
                            min(image.width, math.ceil((max(xs) + .01) * image.width)),
                            min(image.height, math.ceil((max(ys) + .01) * image.height)))
                        width, height = bounds[2] - bounds[0], bounds[3] - bounds[1]
                        if not (0 < width <= 10000 and 0 < height <= 10000 and width * height <= MAX_CROP_PIXELS):
                            crops.append(TextractCrop(observation_id=observation.id, status="over_budget", bounds=bounds))
                            continue
                        with io.BytesIO() as buffer, image.crop(bounds) as cropped:
                            cropped.save(buffer, format="PNG")
                            png = buffer.getvalue()
                        if len(png) > MAX_BYTES:
                            crops.append(TextractCrop(observation_id=observation.id, status="over_budget", bounds=bounds))
                            continue
                        sha = hashlib.sha256(png).hexdigest()
                        artifacts.write_textract_crop(render.page_number, render.revision,
                            recognition_identity(render, sha), png)
                        crops.append(TextractCrop(observation_id=observation.id, status="ready",
                            bounds=bounds, sha256=sha, width=width, height=height))
        plan = TextractPlan(page_number=render.page_number, render_revision=render.revision,
            render_image_sha256=render.image_sha256, input_sha256=identity, crops=tuple(crops))
        artifacts.write_textract_plan(plan)
        return plan
    finally:
        _preparation.release()


def convert_lines(response: dict, width: int, height: int) -> tuple[CropOCRLine, ...]:
    """Keep provider lines intact. Ambiguous multi-column grouping stays uncertain."""
    blocks = response["Blocks"]
    by_id = {block["Id"]: block for block in blocks}
    if len(by_id) != len(blocks):
        raise ValueError("Duplicate Textract block IDs")
    lines = []
    for block in blocks:
        if block.get("BlockType") != "LINE":
            continue
        children = [by_id[key] for relation in block.get("Relationships", [])
                    if relation["Type"] == "CHILD" for key in relation["Ids"]]
        if not children or any(child.get("BlockType") != "WORD" for child in children):
            raise ValueError("Textract line has no complete word evidence")
        scores = [float(item["Confidence"]) for item in (block, *children)]
        if any(not math.isfinite(score) or not 0 <= score <= 100 for score in scores):
            raise ValueError("Invalid Textract confidence")
        box = block["Geometry"]["BoundingBox"]
        x, y, w, h = (float(box[key]) for key in ("Left", "Top", "Width", "Height"))
        if not all(math.isfinite(v) for v in (x, y, w, h)) or not (
            0 <= x < 1 and 0 <= y < 1 and w > 0 and h > 0 and x + w <= 1.00001 and y + h <= 1.00001
        ):
            raise ValueError("Invalid Textract geometry")
        lines.append(CropOCRLine(text=block["Text"], confidence=min(scores) / 100,
            box=(math.floor(x * width), math.floor(y * height),
                 min(width, math.ceil((x + w) * width)), min(height, math.ceil((y + h) * height)))))
    lines.sort(key=lambda line: (line.box[1], line.box[0]))
    for left, right in zip(lines, lines[1:]):
        overlap = min(left.box[3], right.box[3]) - max(left.box[1], right.box[1])
        if overlap > .5 * min(left.box[3] - left.box[1], right.box[3] - right.box[1]):
            raise ValueError("Ambiguous adjacent Textract lines")
    return tuple(lines)


def cached_report(*, page, render, extraction, disputed, artifacts) -> CropOCRReport:
    """No image preparation, network, SDK, or configuration subprocesses."""
    identity = plan_identity(render, extraction, disputed)
    try:
        plan = artifacts.read_textract_plan(render.page_number, render.revision, identity)
        if plan.render_image_sha256 != render.image_sha256:
            raise ValueError("Hosted OCR plan belongs to different art")
        planned = {item.observation_id: item for item in plan.crops}
    except ArtifactMissing:
        planned = {}
    reads, receipt_ids = [], []
    for item in disputed:
        crop = planned.get(item.id)
        status, lines = "pending", ()
        if crop is not None:
            status = crop.status
            if crop.sha256:
                attempts = artifacts.textract_attempts(render.page_number, render.revision, recognition_identity(render, crop.sha256))
                if any(a.render_image_sha256 != render.image_sha256 or a.crop_sha256 != crop.sha256
                       or a.model != TEXTRACT_MODEL or a.region != TEXTRACT_REGION
                       or a.page_number != render.page_number or a.render_revision != render.revision
                       or a.recognition_sha256 != recognition_identity(render, crop.sha256) for a in attempts):
                    raise ValueError("Hosted OCR receipt belongs to different input; rerun Draw")
                succeeded = next((a for a in reversed(attempts) if a.status == "succeeded"), None)
                if succeeded is not None:
                    receipt_ids.append(succeeded.attempt_id)
                    try:
                        lines = convert_lines(succeeded.response, crop.width, crop.height)
                        status = "read"
                    except (KeyError, ValueError, TypeError):
                        # A completed but unusable answer is final inconclusive evidence.
                        # Policy/converter changes can reinterpret it without another charge.
                        status = "read"
                else:
                    receipt_ids.extend(a.attempt_id + ":" + a.status for a in attempts)
                    status = ("outcome_unknown" if attempts and attempts[-1].status in {"submitting", "outcome_unknown"}
                              else "unavailable" if attempts else "pending")
        verdict = "inconclusive"
        if status == "read" and lines and min(line.confidence for line in lines) >= TEXTRACT_MINIMUM_CONFIDENCE:
            text = normalize_display_text(" ".join(line.text for line in lines))
            verdict = "agrees" if text == normalize_display_text(item.text) else "disagrees"
        reads.append(CropOCRRead(observation_id=item.id, status=status, lines=lines,
            primary_text=item.text, verdict=verdict, bounds=crop.bounds if crop else None,
            crop_sha256=crop.sha256 if crop else None))
    verdicts = {read.verdict for read in reads}
    complete = all(read.status not in {"pending", "outcome_unknown", "unavailable"} for read in reads)
    return CropOCRReport(page_number=page.page_number, render_revision=render.revision,
        render_image_sha256=render.image_sha256, comic_page_sha256=page.content_sha256,
        input_sha256=_hash([identity, fingerprint(), receipt_ids, page.content_sha256]), reader_fingerprint=fingerprint(),
        minimum_confidence=TEXTRACT_MINIMUM_CONFIDENCE, complete=complete, readings=tuple(reads),
        status="disagrees" if "disagrees" in verdicts else "agrees" if verdicts == {"agrees"} else "inconclusive")


def _claim(*, artifacts, render, crop, expires_at, retry, retry_before) -> TextractAttempt | None:
    identity = recognition_identity(render, crop.sha256)
    with production_lock(artifacts.project_dir):
        attempts = artifacts.textract_attempts(render.page_number, render.revision, identity)
        if any(item.status == "succeeded" for item in attempts):
            return None
        if attempts:
            last = attempts[-1]
            if not retry or last.started_at >= retry_before or (
                last.status == "submitting" and last.expires_at >= time.time()
            ):
                return None
        if time.time() >= expires_at:
            return None
        resolver = get_pricing_resolver()
        price, _ = resolver._pricing_for(resolver.resolve_model(TEXTRACT_MODEL))
        unit = Decimal(str(price["output_cost_per_document_page"]))
        if not unit.is_finite() or unit <= 0:
            raise ValueError("Textract needs a configured positive unit price")
        attempt = TextractAttempt(attempt_id=uuid.uuid4().hex, page_number=render.page_number,
            render_revision=render.revision, render_image_sha256=render.image_sha256,
            recognition_sha256=identity, crop_sha256=crop.sha256, model=TEXTRACT_MODEL, region=TEXTRACT_REGION,
            started_at=time.time(), expires_at=expires_at, status="submitting", unit_price_usd=str(unit),
            pricing_snapshot=resolver.pricing_snapshot)
        artifacts.write_textract_attempt(attempt)
        return attempt


async def submit(config, image: bytes, attempt: TextractAttempt) -> dict:
    """Exactly one HTTP request. Never use the text client's repair/retry loop."""
    from novel_to_comic.ai.client import _base_url, _headers
    remaining = attempt.expires_at - time.time()
    if remaining <= 0:
        return {"status": "not_submitted", "error_code": "deadline"}
    envelope = {"schema": "canary.crop-ocr/1", "image": base64.b64encode(image).decode(),
        "sha256": attempt.crop_sha256, "attempt_id": attempt.attempt_id, "expires_at": attempt.expires_at}
    async with asyncio.timeout(remaining), httpx.AsyncClient(timeout=remaining) as client:
        response = await client.post(_base_url(config) + "/v1/chat/completions",
            headers=_headers(config, attempt.attempt_id),
            json={"model": attempt.model, "messages": [{"role": "user", "content": json.dumps(envelope)}], "stream": False})
        response.raise_for_status()
        result = json.loads(response.json()["choices"][0]["message"]["content"])
    if (result.get("schema") != "canary.crop-ocr/1" or result.get("attempt_id") != attempt.attempt_id
            or result.get("sha256") != attempt.crop_sha256 or result.get("region") != attempt.region
            or result.get("status") not in {"succeeded", "failed", "outcome_unknown", "not_submitted"}):
        raise ValueError("Textract receipt does not match the submitted crop")
    if result["status"] == "succeeded" and not isinstance(result.get("response"), dict):
        raise ValueError("Textract returned no raw response")
    return result


def _record_usage(attempt, config):
    from novel_to_comic.ai.client import _finalize_event
    from novel_to_comic.usage import UsageRecord
    succeeded = attempt.status == "succeeded"
    unknown = attempt.status in {"submitting", "outcome_unknown"}
    response = attempt.response or {}
    metadata = response.get("ResponseMetadata", {})
    usage = UsageRecord(call_id=attempt.attempt_id, provider="textract", model=attempt.model,
        provider_model="textract/detect-document-text", operation="ocr", document_pages=int(succeeded),
        cost_usd=None if unknown else float(Decimal(attempt.unit_price_usd)) if succeeded else 0,
        cost_source="configured_document_pages" if succeeded else "not_processed")
    _finalize_event(event_id=attempt.attempt_id, status="succeeded" if succeeded else "failed",
        feature="draw.crop_ocr", model_alias=attempt.model, operation="ocr", config=config, charge_user=False,
        usage=usage, latency_ms=int(((attempt.finished_at or time.time()) - attempt.started_at) * 1000),
        estimated_cost_usd=float(Decimal(attempt.unit_price_usd)),
        response_data={"model": "textract/detect-document-text", "provider_request_id": metadata.get("RequestId"),
            "usage": {"document_pages": int(succeeded), "estimated_document_pages": 1,
                      "outcome": attempt.status, "model_version": response.get("DetectDocumentTextModelVersion"),
                      "pricing_snapshot": attempt.pricing_snapshot, "unit_price_usd": attempt.unit_price_usd}},
        metadata={"funding": "api", "cost_owner": "canary", "region": attempt.region,
                  "crop_sha256": attempt.crop_sha256, "page_number": attempt.page_number})


async def _execute(*, config, artifacts, attempt):
    from novel_to_comic.ai.client import _insert_event_async
    # This record is a searchable projection. The durable artifact is authoritative.
    try:
        await _insert_event_async(event_id=attempt.attempt_id, model_alias=attempt.model, feature="draw.crop_ocr",
            operation="ocr", params_json={"region": attempt.region},
            request_summary_json={"crop_sha256": attempt.crop_sha256}, metadata_json={"funding": "api", "cost_owner": "canary"},
            estimated_cost_usd=float(Decimal(attempt.unit_price_usd)))
        image = await asyncio.to_thread(artifacts.read_textract_crop, attempt.page_number,
            attempt.render_revision, attempt.recognition_sha256)
        if hashlib.sha256(image).hexdigest() != attempt.crop_sha256:
            result = {"status": "not_submitted", "error_code": "crop_hash_mismatch"}
        else:
            result = await submit(config, image, attempt)
        finished = attempt.model_copy(update={"status": "failed" if result["status"] == "not_submitted" else result["status"],
            "finished_at": time.time(), "response": result.get("response"), "error_code": result.get("error_code")})
    except (Exception, asyncio.CancelledError) as exc:
        finished = attempt.model_copy(update={"status": "outcome_unknown", "finished_at": time.time(),
            "error_code": type(exc).__name__})
        # Synchronous atomic write also runs on cancellation, before control escapes.
        artifacts.write_textract_attempt(finished)
        if isinstance(exc, asyncio.CancelledError):
            raise
    artifacts.write_textract_attempt(finished)
    await asyncio.to_thread(_record_usage, finished, config)


async def run_checks(*, config, page, render, extraction, disputed, artifacts, retry=False) -> None:
    """Only called from an admitted fresh/explicit page check, never validation."""
    if not enabled() or not disputed or mock_mode_active(config):
        return
    started = time.time()
    deadline = time.monotonic() + PAGE_TIMEOUT_SECONDS
    plan = await asyncio.to_thread(prepare_plan, render=render, extraction=extraction,
        disputed=disputed, artifacts=artifacts, deadline=deadline)
    if plan is None or time.monotonic() >= deadline:
        return
    attempts = []
    for crop in plan.crops:
        if crop.status != "ready":
            continue
        attempt = await asyncio.to_thread(_claim, artifacts=artifacts, render=render, crop=crop,
            expires_at=started + PAGE_TIMEOUT_SECONDS, retry=retry, retry_before=started)
        if attempt is not None:
            attempts.append(attempt)
    # Unique crop hashes are claimed once; gateway enforces cross-page concurrency.
    results = await asyncio.gather(
        *(_execute(config=config, artifacts=artifacts, attempt=attempt) for attempt in attempts),
        return_exceptions=True,
    )
    # A failed artifact/projection write must not abandon other paid answers.
    for result in results:
        if isinstance(result, Exception):
            raise result
