"""Complete-page Draw compilation, Vertex submission, and persistence."""

from __future__ import annotations

import hashlib
import io
import json
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Protocol

from novel_to_comic.config import (
    COMPLETE_PAGE_BASE_COST_USD,
    COMPLETE_PAGE_MAX_ATTEMPTS,
    COMPLETE_PAGE_MAX_PROMPT_CHARACTERS,
    COMPLETE_PAGE_MAX_REFERENCES,
    COMPLETE_PAGE_MODEL,
    COMPLETE_PAGE_OUTPUT_HEIGHT,
    COMPLETE_PAGE_OUTPUT_WIDTH,
    COMPLETE_PAGE_PROFILE_ID,
    COMPLETE_PAGE_PROVIDER,
    COMPLETE_PAGE_REFERENCE_COST_USD,
    Config,
)
from novel_to_comic.models.draw import (
    BookEdition,
    CompletePageProviderResult,
    FrozenPageGenerationRequest,
    PageCapabilityProfile,
    PageGenerationProvenance,
    PageReference,
    PageIssue,
    PageRenderRevision,
    PageRenderCorrection,
    RetryProvenance,
)
from novel_to_comic.models.page import (
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    ComicPage,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, calculate_cost

if TYPE_CHECKING:
    from fastapi import FastAPI

    from novel_to_comic.server.generation_jobs import GenerationJob


@dataclass(frozen=True, slots=True)
class ApprovedReferenceFile:
    """The Cast-owned bytes for one approved visual-reference authority."""

    reference_id: str
    path: Path
    media_type: str


@dataclass(frozen=True, slots=True)
class CompiledPageGeneration:
    """A frozen semantic request paired with its verified bytes in one order."""

    request: FrozenPageGenerationRequest
    reference_bytes: tuple[bytes, ...]
    edit_source_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class PreparedVertexPageRequest:
    """The exact immutable object handed to the Vertex transport."""

    request_sha256: str
    model: str
    prompt: str
    references: tuple[PageReference, ...]
    reference_bytes: tuple[bytes, ...]
    edit_source_bytes: bytes | None
    width: int
    height: int
    media_type: str
    idempotency_key: str
    estimated_cost_usd: Decimal
    frozen_request_json: str


class CompletePageTransport(Protocol):
    async def generate(
        self,
        request: PreparedVertexPageRequest,
    ) -> CompletePageProviderResult: ...


def production_page_capability_profile() -> PageCapabilityProfile:
    """Return the single evaluated complete-page production profile."""

    return PageCapabilityProfile(
        id=COMPLETE_PAGE_PROFILE_ID,
        provider=COMPLETE_PAGE_PROVIDER,
        model=COMPLETE_PAGE_MODEL,
        max_image_references=COMPLETE_PAGE_MAX_REFERENCES,
        reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=COMPLETE_PAGE_OUTPUT_WIDTH,
        output_height=COMPLETE_PAGE_OUTPUT_HEIGHT,
        max_prompt_characters=COMPLETE_PAGE_MAX_PROMPT_CHARACTERS,
        retry_semantics="idempotent_request",
        max_attempts=COMPLETE_PAGE_MAX_ATTEMPTS,
        price_per_page_usd=Decimal(COMPLETE_PAGE_BASE_COST_USD),
        price_per_reference_usd=Decimal(COMPLETE_PAGE_REFERENCE_COST_USD),
    )


def select_book_edition(
    *,
    edition_id: str,
    profile: PageCapabilityProfile,
    existing: BookEdition | None = None,
) -> BookEdition:
    """Select the sole production profile, or verify an existing fixed edition."""

    if (
        existing is not None
        and (
            edition_id != existing.id
            or profile != existing.capability_profile
        )
    ):
        raise ValueError("one model and capability profile are fixed for the edition")
    if (
        profile.provider != COMPLETE_PAGE_PROVIDER
        or profile.model != COMPLETE_PAGE_MODEL
        or not profile.complete_page_generation
        or not profile.exact_visible_lettering
        or profile.reference_ordering != "ordered"
        or profile.retry_semantics != "idempotent_request"
        or profile.max_image_references < 1
        or profile.output_width <= 0
        or profile.output_height <= 0
    ):
        raise ValueError(
            "provider/model does not satisfy complete-page production capability"
        )
    selected = BookEdition(
        revision=existing.revision if existing is not None else 1,
        id=edition_id,
        capability_profile=profile,
    )
    if existing is not None and selected != existing:
        raise ValueError("one model and capability profile are fixed for the edition")
    return selected


def _selected_authorities(
    page: ComicPage,
    inventory: ApprovedVisualReferenceInventory,
) -> tuple[ApprovedVisualReference, ...]:
    by_state = {
        reference.appearance_state_id: reference
        for reference in inventory.references
        if reference.appearance_state_id is not None
    }
    base_by_entity = {
        reference.entity_id: reference
        for reference in inventory.references
        if reference.appearance_state_id is None
    }
    selected: list[ApprovedVisualReference] = []
    selected_ids: set[str] = set()
    state_entities: set[str] = set()
    for content in page.content:
        for state_id in content.appearance_state_ids:
            reference = by_state.get(state_id)
            if reference is None or reference.entity_id not in content.entity_ids:
                raise ValueError(
                    f"page appearance state {state_id!r} has no approved entity authority"
                )
            state_entities.add(reference.entity_id)
            if reference.id not in selected_ids:
                selected.append(reference)
                selected_ids.add(reference.id)
        for entity_id in content.entity_ids:
            if entity_id in state_entities:
                continue
            reference = base_by_entity.get(entity_id)
            if reference is None:
                raise ValueError(
                    f"page entity {entity_id!r} has no approved reference authority"
                )
            if reference.id not in selected_ids:
                selected.append(reference)
                selected_ids.add(reference.id)
    return tuple(selected)


def _compile_prompt(
    page: ComicPage,
    references: tuple[PageReference, ...],
    correction: PageRenderCorrection | None = None,
) -> str:
    payload = {
        "canonical_comic_page": page.model_dump(mode="json"),
        "approved_page_references": [
            {
                "order": reference.order,
                "entity_id": reference.entity_id,
                "appearance_state_id": reference.appearance_state_id,
                "visual_anchor": reference.visual_anchor,
            }
            for reference in references
        ],
        "complete_page_correction": (
            correction.model_dump(mode="json") if correction is not None else None
        ),
    }
    return (
        "Render exactly one complete, fully lettered comic page from the canonical "
        "ComicPage below. Preserve every lettering string and every visual_anchor "
        "verbatim. Use references in the supplied order. Return one complete page "
        "image only; never return a panel artifact.\n"
        + json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def compile_page_generation_request(
    page: ComicPage,
    edition: BookEdition,
    inventory: ApprovedVisualReferenceInventory,
    reference_files: Mapping[str, ApprovedReferenceFile],
    *,
    retry: RetryProvenance,
    correction: PageRenderCorrection | None = None,
    edit_source_bytes: bytes | None = None,
) -> CompiledPageGeneration:
    """Compile one immutable request from canonical Plan and Cast authority."""

    selected_edition = select_book_edition(
        edition_id=edition.id,
        profile=edition.capability_profile,
        existing=edition,
    )
    if retry.attempt > selected_edition.capability_profile.max_attempts:
        raise ValueError("retry attempt exceeds the edition capability profile")
    if correction is None and edit_source_bytes is not None:
        raise ValueError("initial generation cannot have an edit source")
    if correction is not None:
        if correction.mode not in selected_edition.capability_profile.editing_modes:
            raise ValueError("correction mode is unsupported by the edition profile")
        if (
            correction.page_number != page.page_number
            or correction.comic_page_revision != page.revision
            or correction.comic_page_sha256 != page.content_sha256
        ):
            raise ValueError("correction is stale for the canonical ComicPage")
        if edit_source_bytes is None:
            raise ValueError("complete-page correction requires its parent page bytes")
        if (
            hashlib.sha256(edit_source_bytes).hexdigest()
            != correction.parent_render_image_sha256
        ):
            raise ValueError("edit source bytes do not match correction lineage")
    authorities = _selected_authorities(page, inventory)
    references: list[PageReference] = []
    loaded: list[bytes] = []
    for order, authority in enumerate(authorities, start=1):
        source = reference_files.get(authority.id)
        if source is None or source.reference_id != authority.id:
            raise ValueError(
                f"approved reference {authority.id!r} has no selected Cast bytes"
            )
        try:
            data = source.path.read_bytes()
        except OSError as exc:
            raise ValueError(
                f"approved reference {authority.id!r} bytes are unreadable"
            ) from exc
        if not data:
            raise ValueError(f"approved reference {authority.id!r} bytes are empty")
        loaded.append(data)
        references.append(
            PageReference(
                id=authority.id,
                order=order,
                media_type=source.media_type,
                content_sha256=hashlib.sha256(data).hexdigest(),
                visual_anchor=authority.visual_anchor,
                entity_id=authority.entity_id,
                appearance_state_id=authority.appearance_state_id,
            )
        )
    prompt = _compile_prompt(page, tuple(references), correction)
    request = FrozenPageGenerationRequest.compile(
        page=page,
        edition=selected_edition,
        prompt=prompt,
        references=references,
        retry=retry,
        correction=correction,
    )
    return CompiledPageGeneration(
        request=request,
        reference_bytes=tuple(loaded),
        edit_source_bytes=edit_source_bytes,
    )


class VertexCompletePageAdapter:
    """Strict complete-page adapter over the proven Vertex multimodal transport."""

    def __init__(self, transport: CompletePageTransport) -> None:
        self._transport = transport

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedVertexPageRequest:
        request = compiled.request
        if request.provider != COMPLETE_PAGE_PROVIDER or request.model != COMPLETE_PAGE_MODEL:
            raise ValueError("complete-page request is not bound to the production Vertex profile")
        if len(request.references) != len(compiled.reference_bytes):
            raise ValueError("reference metadata and uploaded bytes must be one-to-one")
        for reference, data in zip(
            request.references,
            compiled.reference_bytes,
            strict=True,
        ):
            if hashlib.sha256(data).hexdigest() != reference.content_sha256:
                raise ValueError(
                    f"selected reference {reference.order} bytes changed after compilation"
                )
        if request.correction is None and compiled.edit_source_bytes is not None:
            raise ValueError("initial generation cannot submit an edit source")
        if request.correction is not None:
            if compiled.edit_source_bytes is None:
                raise ValueError("complete-page correction is missing its edit source")
            if (
                hashlib.sha256(compiled.edit_source_bytes).hexdigest()
                != request.correction.parent_render_image_sha256
            ):
                raise ValueError("complete-page edit source changed after compilation")
        return PreparedVertexPageRequest(
            request_sha256=request.request_sha256,
            model=request.model,
            prompt=request.prompt,
            references=request.references,
            reference_bytes=compiled.reference_bytes,
            edit_source_bytes=compiled.edit_source_bytes,
            width=request.output_width,
            height=request.output_height,
            media_type=request.output_media_type,
            idempotency_key=request.request_sha256,
            estimated_cost_usd=request.estimated_cost_usd,
            frozen_request_json=request.model_dump_json(),
        )

    async def generate(
        self,
        prepared: PreparedVertexPageRequest,
    ) -> CompletePageProviderResult:
        result = await self._transport.generate(prepared)
        actual_model = result.actual_provider_model
        for prefix in ("vertex_ai/", "vertex-multimodal/"):
            if actual_model.startswith(prefix):
                actual_model = actual_model.removeprefix(prefix)
                break
        if (
            result.artifact_kind != "complete_page"
            or result.media_type != prepared.media_type
            or result.width != prepared.width
            or result.height != prepared.height
            or actual_model != prepared.model
        ):
            raise ValueError(
                "provider result does not satisfy the fixed complete-page profile"
            )
        return result


class GoogleVertexCompletePageTransport:
    """Gateway transport to the isolated native Vertex multimodal handler."""

    def __init__(self, config: Config) -> None:
        self._config = config

    async def generate(
        self,
        request: PreparedVertexPageRequest,
    ) -> CompletePageProviderResult:
        from PIL import Image
        from novel_to_comic.ai import client as ai_client

        event_id = uuid.uuid4().hex
        url = f"{ai_client._base_url(self._config)}/v1/images/edits"
        headers = ai_client._headers(self._config, event_id)
        files = []
        if request.edit_source_bytes is not None:
            files.append(
                (
                    "image",
                    (
                        "complete-page-edit-source.png",
                        request.edit_source_bytes,
                        "image/png",
                    ),
                )
            )
        files.extend(
            [
            (
                "image",
                (
                    f"complete-page-ref-{reference.order}",
                    data,
                    reference.media_type,
                ),
            )
            for reference, data in zip(
                request.references,
                request.reference_bytes,
                strict=True,
            )
            ]
        )
        started = time.perf_counter()
        response = await ai_client._post_with_retry(
            url,
            headers=headers,
            data={
                "model": f"{COMPLETE_PAGE_PROVIDER}/{request.model}",
                "prompt": request.prompt,
                "response_format": "b64_json",
                "canary_complete_page_request": request.frozen_request_json,
                "canary_requested_width": str(request.width),
                "canary_requested_height": str(request.height),
                "canary_requested_aspect": str(request.width / request.height),
                "canary_idempotency_key": request.idempotency_key,
            },
            files=files,
        )
        if response.status_code >= 400:
            response.raise_for_status()
        payload = response.json()
        image_bytes = await ai_client._decode_image_response(payload)
        with Image.open(io.BytesIO(image_bytes)) as image:
            if image.format != "PNG":
                raise ValueError("Vertex complete-page output must be PNG")
            width, height = image.size
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage = ai_client._extract_usage(
            payload,
            event_id,
            request.model,
            "image",
            response.headers,
        )
        if usage.cost_usd is None:
            usage = usage.model_copy(
                update={
                    "cost_usd": float(request.estimated_cost_usd),
                    "cost_source": "capability_profile",
                }
            )
        return CompletePageProviderResult(
            artifact_kind="complete_page",
            image_bytes=image_bytes,
            media_type="image/png",
            width=width,
            height=height,
            latency_ms=latency_ms,
            provider_request_id=payload.get("id"),
            actual_provider_model=str(
                payload.get("model") or f"vertex_ai/{request.model}"
            ),
            usage=usage,
        )


async def draw_complete_page(
    compiled: CompiledPageGeneration,
    *,
    adapter: VertexCompletePageAdapter,
    artifacts: TargetArtifacts,
    request_revision: int,
    render_revision: int,
    parent_render_revision: int | None = None,
) -> PageGenerationProvenance:
    """Persist and execute exactly one complete-page request."""

    correction = compiled.request.correction
    if correction is None and parent_render_revision is not None:
        raise ValueError("initial page generation cannot cite correction lineage")
    if correction is not None and (
        parent_render_revision != correction.parent_render_revision
    ):
        raise ValueError("complete-page correction must cite its exact parent render")
    prepared = adapter.prepare(compiled)
    artifacts.write_request(
        compiled.request,
        request_revision=request_revision,
    )
    provider_result = await adapter.generate(prepared)
    artifacts.write_render(
        page_number=compiled.request.page_number,
        render_revision=render_revision,
        image=provider_result.image_bytes,
    )
    render = PageRenderRevision(
        page_number=compiled.request.page_number,
        revision=render_revision,
        parent_revision=parent_render_revision,
        comic_page_revision=compiled.request.comic_page_revision,
        comic_page_sha256=compiled.request.comic_page_sha256,
        request_sha256=compiled.request.request_sha256,
        image_sha256=hashlib.sha256(provider_result.image_bytes).hexdigest(),
        width=provider_result.width,
        height=provider_result.height,
        provider=compiled.request.provider,
        model=compiled.request.model,
        latency_ms=provider_result.latency_ms,
        cost_usd=Decimal(str(calculate_cost(provider_result.usage))),
    )
    provenance = PageGenerationProvenance(
        render=render,
        usage=provider_result.usage,
        provider_request_id=provider_result.provider_request_id,
    )
    artifacts.write_provenance(provenance)
    return provenance


async def correct_complete_page(
    compiled: CompiledPageGeneration,
    *,
    issue: PageIssue,
    adapter: VertexCompletePageAdapter,
    artifacts: TargetArtifacts,
    request_revision: int,
    render_revision: int,
) -> PageGenerationProvenance:
    """Produce and link one complete revised page for a Draw-owned issue."""

    correction = compiled.request.correction
    if correction is None or correction.issue_id != issue.id:
        raise ValueError("compiled request does not correct the supplied page issue")
    if issue.correction_owner != "draw":
        raise ValueError("copy changes must return to Adapt and Plan")
    provenance = await draw_complete_page(
        compiled,
        adapter=adapter,
        artifacts=artifacts,
        request_revision=request_revision,
        render_revision=render_revision,
        parent_render_revision=correction.parent_render_revision,
    )
    from novel_to_comic.page_review import resolve_page_issue

    resolve_page_issue(
        artifacts,
        issue_id=issue.id,
        page_number=issue.page_number,
        resolution_revision=render_revision,
    )
    return provenance


def enqueue_complete_page_draw(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    compiled: CompiledPageGeneration,
    adapter: VertexCompletePageAdapter,
    artifacts: TargetArtifacts,
    request_revision: int,
    render_revision: int,
    parent_render_revision: int | None = None,
    issue: PageIssue | None = None,
    on_success: Callable[[PageGenerationProvenance], None] | None = None,
) -> tuple[GenerationJob, bool]:
    """Estimate, reserve, execute, settle, and release one complete-page job."""

    # This is deliberately before the credited-job call: capability, geometry,
    # reference capacity, identity, and selected bytes must fail before cost.
    adapter.prepare(compiled)
    from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost

    estimate = credit_estimate_for_provider_cost(
        float(compiled.request.estimated_cost_usd),
        "draw",
        reserve=True,
        zero_cost_estimate=0,
    )

    async def _work() -> ApiResult[PageGenerationProvenance]:
        if issue is None:
            provenance = await draw_complete_page(
                compiled,
                adapter=adapter,
                artifacts=artifacts,
                request_revision=request_revision,
                render_revision=render_revision,
                parent_render_revision=parent_render_revision,
            )
        else:
            provenance = await correct_complete_page(
                compiled,
                issue=issue,
                adapter=adapter,
                artifacts=artifacts,
                request_revision=request_revision,
                render_revision=render_revision,
            )
        if on_success is not None:
            on_success(provenance)
        return ApiResult(
            value=provenance,
            usage=provenance.usage,
            provider_request_id=provenance.provider_request_id,
            actual_provider_model=provenance.render.model,
        )

    return enqueue_reserved_generation_job(
        app,
        project_name=project_name,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage="draw",
        kind="complete_page_draw",
        label=f"Page {compiled.request.page_number}",
        payload={
            "page_number": compiled.request.page_number,
            "request_sha256": compiled.request.request_sha256,
            "retry_attempt": compiled.request.retry.attempt,
            "issue_id": issue.id if issue is not None else None,
        },
        work=_work,
        debit_description=f"Complete page {compiled.request.page_number}",
        reservation_credits=estimate["reserved_credits"] or 0,
    )
