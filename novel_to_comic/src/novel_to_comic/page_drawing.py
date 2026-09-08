"""Complete-page Draw compilation, Vertex submission, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
from datetime import UTC, datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Literal, Protocol

from novel_to_comic.config import (
    COMPLETE_PAGE_BASE_COST_USD,
    COMPLETE_PAGE_GATEWAY_MODEL,
    COMPLETE_PAGE_MAX_ATTEMPTS,
    COMPLETE_PAGE_MAX_PROMPT_CHARACTERS,
    COMPLETE_PAGE_MAX_REFERENCES,
    COMPLETE_PAGE_MODEL,
    COMPLETE_PAGE_OUTPUT_HEIGHT,
    COMPLETE_PAGE_OUTPUT_WIDTH,
    COMPLETE_PAGE_PROFILE_ID,
    COMPLETE_PAGE_PROVIDER,
    COMPLETE_PAGE_REFERENCE_COST_USD,
    PAGE_OCR_ESTIMATED_COST_USD,
    Config,
)
from novel_to_comic.models.draw import (
    BookEdition,
    CompletePageProviderResult,
    CorrectionChange,
    FrozenPageGenerationRequest,
    PageCapabilityProfile,
    PageGenerationProvenance,
    PageGenerationFailure,
    PageReference,
    PageIssue,
    PageRenderRevision,
    PageRenderCorrection,
    RenderAnalysis,
    RetryProvenance,
)
from novel_to_comic.models.page import (
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    ComicPage,
)
from novel_to_comic.style_contract import page_style_template
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord, calculate_cost

if TYPE_CHECKING:
    from fastapi import FastAPI
    from novel_to_comic.page_review import OCRAdapter, PageCorrectionContext
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
        retry_semantics="bounded_submission",
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
        or profile.retry_semantics != "bounded_submission"
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


def ensure_current_page_edition(
    artifacts: TargetArtifacts,
    edition: BookEdition,
) -> BookEdition:
    """Reject incompatible editions; model changes require an explicit redraw."""
    if edition.capability_profile != production_page_capability_profile():
        raise ValueError(
            "This edition uses a different page profile. Start a new edition by "
            "rerunning Draw; existing pages will not be mixed with another model."
        )
    return edition


def _selected_authorities(
    page: ComicPage,
    inventory: ApprovedVisualReferenceInventory,
) -> tuple[ApprovedVisualReference, ...]:
    """Resolve the page's approved authorities from the whole page at once.

    Selection is a property of the page, not of the order its content items
    happen to be listed in. Deciding per content item made the reference set
    depend on traversal: an entity shown with an appearance state early and
    without one later silently lost its base reference, while the reverse
    ordering kept both.
    """

    by_state = {
        (reference.entity_id, reference.appearance_state_id): reference
        for reference in inventory.references
    }
    required: list[tuple[str, str | None]] = []
    for content in page.content:
        for entity_id in content.entity_ids:
            key = (entity_id, content.appearance_states.get(entity_id))
            if key not in by_state:
                raise ValueError(f"page entity/state {key!r} has no approved reference authority")
            if key not in required:
                required.append(key)

    selected: list[ApprovedVisualReference] = []
    selected_ids: set[str] = set()
    for entity_id, state_id in required:
        reference = by_state[(entity_id, state_id)]
        if reference.id not in selected_ids:
            selected.append(reference)
            selected_ids.add(reference.id)
    return tuple(selected)


def _off_canvas_handle(prefix: str, index: int) -> str:
    suffix = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        suffix = chr(65 + remainder) + suffix
    return f"{prefix}-{suffix}"


def _compile_prompt(
    page: ComicPage,
    references: tuple[PageReference, ...],
    correction: PageRenderCorrection | None = None,
    depiction: Literal["canonical", "less_graphic"] = "canonical",
    style_template: str = "",
    correction_context: "PageCorrectionContext | None" = None,
) -> str:
    # Identity is independent of state labels and reference traversal order.
    entity_ids = sorted({
        entity_id for content in page.content
        for entity_id in (
            *content.entity_ids,
            *(item.speaker_entity_id for item in content.lettering if item.speaker_entity_id),
        )
    })
    handles = {
        entity_id: _off_canvas_handle("subject", index)
        for index, entity_id in enumerate(entity_ids, 1)
    }
    direction_pattern = (
        r"(?<![\w-])(" + "|".join(re.escape(key) for key in sorted(handles, key=len, reverse=True))
        + r")(?![\w-])"
        if handles else None
    )

    def provider_safe_direction(text: str) -> str:
        return (
            re.sub(direction_pattern, lambda match: handles[match.group(0)], text)
            if direction_pattern else text
        )

    def subjects(content):
        return [
            {
                "subject": handles[entity_id],
                "references": [
                    {
                        "image": _off_canvas_handle("asset", ref.order),
                        "appearance": ref.label,
                    }
                    for ref in references
                    if ref.entity_id == entity_id
                    and ref.appearance_state_id == content.appearance_states.get(entity_id)
                ],
            }
            for entity_id in content.entity_ids
        ]

    reading_labels = {}
    for content in page.content:
        reading_labels[content.id] = f"Panel {content.order}"
        for index, lettering in enumerate(content.lettering, 1):
            reading_labels[lettering.id] = f"Panel {content.order} lettering {index}"
    ordered_content = sorted(page.content, key=lambda content: content.order)
    payload: dict[str, object] = {
        "reference_scope": (
            "All asset and subject handles are off-canvas bindings, not illustration callouts. "
            "Each asset label binds the immediately preceding supplied image. The separately "
            "labeled parent-edit-base, when present, is not an approved asset and does not "
            "advance asset ordering. Use each asset only for its assigned subject and state; "
            "preserve hairstyle, age, facial structure, clothing design and recurring object "
            "features shown by that authority unless the assigned state explicitly changes them."
        ),
        "approved_page_references": [
            {
                "image": _off_canvas_handle("asset", reference.order),
                "subject": handles[reference.entity_id],
                "appearance": reference.label,
                "visual_anchor": reference.visual_anchor,
                "continuity_guard": reference.continuity_guard,
            }
            for reference in references
        ],
        "project_style_direction": page_style_template(style_template) if style_template.strip() else None,
        "canonical_staging_and_layout": provider_safe_direction(page.layout_intent),
        "canonical_comic_page": {
            "page_turn_role": page.page_turn_role,
            "spread_role": page.spread_role,
            "emphasis": page.emphasis,
            "density_intent": page.density_intent,
            "rhythm_intent": provider_safe_direction(page.rhythm_intent),
            "content": [
                {
                    "order": content.order,
                    "panel_role": content.panel_role,
                    "visual_intent": provider_safe_direction(content.visual_intent),
                    "visible_subjects": subjects(content),
                    "pinned_geometry": content.pinned_geometry.model_dump() if content.pinned_geometry else None,
                }
                for content in ordered_content
            ],
        },
        "exact_lettering": {
            "reading_order": [reading_labels[key] for key in page.reading_order],
            "panels": [
                {
                    "panel": content.order,
                    "lettering": [
                        {
                            "kind": lettering.kind,
                            "text": lettering.text,
                            "speaker": lettering.speaker,
                            "speaker_entity_id": handles.get(lettering.speaker_entity_id),
                            "delivery": lettering.delivery,
                        }
                        for lettering in content.lettering
                    ],
                }
                for content in ordered_content
            ],
        },
    }
    if correction is not None:
        # Aggregated instruction repeats changes, notes and annotations. Send
        # structured author changes once; legacy single-issue instructions once.
        payload["complete_page_correction"] = {
            "mode": correction.mode,
            "retained_render_intent": list(correction.retained_instructions),
            "retained_intent_scope": (
                "Historical producing instructions are non-lettering original constraints. "
                "Preserve deliberate depiction and earlier corrections only where consistent "
                "with current canonical copy, approved identity/state/style and author pins. "
                "Current changes supersede conflicting earlier changes. Historical image and "
                "subject bindings describe the producing request, not current attachments; "
                "never render that historical specification as copy or additional panels."
            ),
            "parent_coordinate_regions": [
                {"polygon": [{"x": x, "y": y} for x, y in region.polygon]}
                for region in correction.resolved_regions
            ],
            "geometry_scope": (
                "Region polygons and annotations use normalized coordinates of parent-edit-base, "
                "origin top left. They localize this correction only, not canonical panel layout. "
                "Preserve untouched composition and framing; return the entire page."
            ),
            "changes": [
                {
                    "instruction": provider_safe_direction(change.instruction),
                    "annotations": [
                        {
                            "kind": annotation.kind,
                            "points": [{"x": point.x, "y": point.y} for point in annotation.points],
                            "bounds": dict(zip(("x", "y", "width", "height"), annotation.bounds, strict=True)),
                            "label": annotation.label,
                            "note": annotation.note,
                        }
                        for annotation in change.annotations
                    ],
                }
                for change in correction.changes
            ] if correction.changes else [{"instruction": provider_safe_direction(correction.instruction)}],
            "author_note": provider_safe_direction(correction.note) if correction.changes else "",
        }
        if correction_context is not None:
            payload["background_context_not_for_rendering"] = {
                "scope": (
                    "Evidence only, never additional panels or lettering. Render only the ordered "
                    "panels above. Their current subject/state assignments govern now; chronology "
                    "describes other moments and must not activate later states. Source prose "
                    "never overrides exact lettering. Explicitly selected passages are retained in full."
                ),
                "treatment_spine": list(correction_context.treatment_spine),
                "beats": list(correction_context.beat_summaries),
                "appearance_chronology": list(correction_context.appearance_chronology),
                "continuity": list(correction_context.beat_transitions),
                "sources": list(correction_context.source_texts),
            }
    depiction_direction = (
        "Use framing, shadow, reaction, or aftermath for graphic details. Preserve "
        "approved identity, costume, story events, exact lettering, and page layout. "
        "Do not alter unaffected subjects or discard their references.\n"
        if depiction == "less_graphic" else ""
    )
    has_lettering = any(content.lettering for content in page.content)
    lettering_direction = (
        "Typeset only the exact lettering strings, preserving capitalization, exactly once "
        "in their assigned panel and reading order. For onscreen delivery, bind each balloon "
        "tail only to speaker_entity_id, not an ambiguous display name; never share tails "
        "between subjects. Offscreen delivery has no tail to a visible subject. Narration "
        "and quoted_text have no character tails.\n"
        if has_lettering else
        "This page is unlettered: no visible text, captions, speech or thought balloons, or SFX. "
        "Style lettering guidance cannot introduce text.\n"
    )
    return (
        "Render exactly one complete comic page, never a panel artifact or reference sheet.\n"
        "AUTHORITY: exact canonical copy and reading order, current approved subject/state "
        "references with verbatim physical anchors and guards, selected project style, and "
        "author-pinned geometry constrain every decision. Anchors describe physical features, "
        "never printable copy. All other instructions and bindings stay off canvas. "
        "The parent-edit-base is subordinate to these authorities: retain its untouched "
        "composition, framing and artwork, but never perpetuate conflicting identity, state, "
        "style or copy. Apply only the authoritative change list within those constraints. "
        "Within them, choose camera, acting, lighting, staging and unpinned panel proportions "
        "to express visual and rhythm intent. Canonical continuity describes established "
        "start/end staging, not a request to repeat completed actions.\n"
        + lettering_direction
        + depiction_direction
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\nOUTPUT: one full page image; exact copy only; assigned identities and states; "
        "no visible metadata, asset handles, subject labels or reference callouts."
    )


def compile_page_generation_request(
    page: ComicPage,
    edition: BookEdition,
    inventory: ApprovedVisualReferenceInventory,
    reference_files: Mapping[str, ApprovedReferenceFile],
    *,
    retry: RetryProvenance,
    correction: PageRenderCorrection | None = None,
    correction_context: "PageCorrectionContext | None" = None,
    edit_source_bytes: bytes | None = None,
    depiction: Literal["canonical", "less_graphic"] = "canonical",
    style_template: str = "",
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
    max_references = selected_edition.capability_profile.max_image_references
    if len(authorities) > max_references:
        raise ValueError(
            f"Page {page.page_number} requires {len(authorities)} approved references, "
            f"but this edition supports {max_references}. Replan this page before drawing; "
            "identity references will not be silently dropped."
        )
    uploaded_authorities = authorities
    references: list[PageReference] = []
    loaded: list[bytes] = []
    for order, authority in enumerate(uploaded_authorities, start=1):
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
                label=authority.label,
                continuity_guard=authority.continuity_guard,
            )
        )
    prompt = _compile_prompt(
        page,
        tuple(references),
        correction,
        depiction,
        style_template,
        correction_context,
    )
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

@dataclass(frozen=True, slots=True)
class PreparedPageCorrection:
    """One validated correction with its compiled request and story context."""

    correction: PageRenderCorrection
    compiled: CompiledPageGeneration
    context: "PageCorrectionContext"


def prepare_page_correction(
    *,
    page: ComicPage,
    edition: BookEdition,
    inventory: ApprovedVisualReferenceInventory,
    reference_files: Mapping[str, ApprovedReferenceFile],
    retry: RetryProvenance,
    parent: PageRenderRevision,
    changes: tuple[CorrectionChange, ...],
    note: str = "",
    context_source_unit_ids: tuple[str, ...] = (),
    artifacts: TargetArtifacts,
    style_template: str = "",
) -> PreparedPageCorrection:
    """Validate and compile one explicit correction set, without spending.

    Preview and submission share this exact path, so the estimate the author
    approves always describes the request that will be enqueued. Manual
    changes carry deterministic issue identities here without any writes;
    the real issues are created inside the reserved job. Every failure here
    raises before any credit hold or provider call.
    """
    from novel_to_comic.page_review import (
        build_aggregated_correction_request,
        build_correction_context,
    )

    profile = edition.capability_profile
    correction = build_aggregated_correction_request(
        changes=changes,
        note=note,
        context_source_unit_ids=context_source_unit_ids,
        page=page,
        parent=parent,
        profile=profile,
        artifacts=artifacts,
    )
    context = build_correction_context(
        page=page, artifacts=artifacts, extra_source_unit_ids=tuple(context_source_unit_ids),
    )
    if context.digest != correction.context_digest:
        raise ValueError("correction story context does not match canonical artifacts")
    compiled = compile_page_generation_request(
        page,
        edition,
        inventory,
        reference_files,
        retry=retry,
        correction=correction,
        correction_context=context,
        edit_source_bytes=artifacts.read_render(page.page_number, parent.revision),
        style_template=style_template,
        depiction=correction.depiction,
    )
    return PreparedPageCorrection(correction=correction, compiled=compiled, context=context)


def correction_credit_estimate(compiled: CompiledPageGeneration, *, reserve: bool):
    """Credit estimate for one compiled correction, including its text check."""
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost

    return credit_estimate_for_provider_cost(
        float(compiled.request.estimated_cost_usd) + float(PAGE_OCR_ESTIMATED_COST_USD),
        "draw",
        reserve=reserve,
        zero_cost_estimate=0,
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
        mismatches: list[str] = []
        if result.artifact_kind != "complete_page":
            mismatches.append(
                f"artifact_kind expected=complete_page actual={result.artifact_kind}"
            )
        if result.media_type != prepared.media_type:
            mismatches.append(
                f"media_type expected={prepared.media_type} actual={result.media_type}"
            )
        if (result.width, result.height) != (prepared.width, prepared.height):
            mismatches.append(
                "dimensions "
                f"expected={prepared.width}x{prepared.height} "
                f"actual={result.width}x{result.height}"
            )
        if actual_model != prepared.model:
            mismatches.append(
                f"model expected={prepared.model} actual={result.actual_provider_model}"
            )
        if mismatches:
            raise ValueError(
                "provider result does not satisfy the fixed complete-page profile: "
                + "; ".join(mismatches)
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
        from novel_to_comic.ai.finalisation import (
            begin_image_call,
            finalise_image_cancelled,
            finalise_image_failure,
        )

        files = []
        ref_reads: list[tuple[Path, bytes | None]] = []
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
            ref_reads.append(
                (Path("complete-page-edit-source.png"), request.edit_source_bytes)
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
        ref_reads.extend(
            (Path(f"complete-page-ref-{reference.order}-{reference.id}"), data)
            for reference, data in zip(
                request.references,
                request.reference_bytes,
                strict=True,
            )
        )
        endpoint = "/v1/images/edits" if files else "/v1/images/generations"
        request_data = {
            # Route through the configured gateway alias while preserving
            # the actual provider/model in the frozen edition manifest.
            "model": COMPLETE_PAGE_GATEWAY_MODEL,
            "prompt": request.prompt,
            "response_format": "b64_json",
            "canary_complete_page_request": request.frozen_request_json,
            "canary_requested_width": str(request.width),
            "canary_requested_height": str(request.height),
            "canary_requested_aspect": str(request.width / request.height),
            "canary_idempotency_key": request.idempotency_key,
        }
        feature = "complete_page_draw"
        ctx = await begin_image_call(
            config=self._config,
            model=COMPLETE_PAGE_GATEWAY_MODEL,
            feature=feature,
            prompt=request.prompt,
            params={
                "model": COMPLETE_PAGE_GATEWAY_MODEL,
                "provider_model": request.model,
                "size": f"{request.width}x{request.height}",
                "quality": self._config.image_quality,
                "artifact_kind": "complete_page",
            },
            ref_reads=ref_reads,
        )
        headers = ai_client._headers(self._config, ctx.event_id)
        url = f"{ai_client._base_url(self._config)}{endpoint}"
        response = None
        try:
            if files:
                response = await ai_client._post_with_retry(
                    url,
                    headers=headers,
                    data=request_data,
                    files=files,
                    retry_ambiguous=False,
                )
            else:
                response = await ai_client._post_with_retry(
                    url,
                    headers=headers,
                    json=request_data,
                    retry_ambiguous=False,
                )
            if response.status_code >= 400:
                raise ai_client._gateway_http_error(
                    response,
                    feature=feature,
                    model=request.model,
                    endpoint=endpoint,
                )
            payload = response.json()
            image_bytes = await ai_client._decode_image_response(payload)
            with Image.open(io.BytesIO(image_bytes)) as image:
                if image.format != "PNG":
                    raise ValueError("Vertex complete-page output must be PNG")
                width, height = image.size
            latency_ms = int((time.perf_counter() - ctx.started) * 1000)
            usage = ai_client._extract_usage(
                payload,
                ctx.event_id,
                COMPLETE_PAGE_GATEWAY_MODEL,
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
            response_model = str(payload.get("model") or "")
            actual_provider_model = (
                f"vertex_ai/{request.model}"
                if response_model == COMPLETE_PAGE_GATEWAY_MODEL
                else response_model or f"vertex_ai/{request.model}"
            )
            usage = usage.model_copy(
                update={
                    "model": COMPLETE_PAGE_GATEWAY_MODEL,
                    "provider_model": actual_provider_model,
                }
            )
            response_data = {
                key: value for key, value in payload.items() if key != "data"
            }
            response_data["model"] = actual_provider_model
        except asyncio.CancelledError as exc:
            await finalise_image_cancelled(
                ctx=ctx,
                config=self._config,
                model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature,
                error=exc,
                error_response=response,
            )
            raise
        except BaseException as exc:
            await finalise_image_failure(
                ctx=ctx,
                config=self._config,
                model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature,
                error=exc,
                error_response=response,
            )
            raise
        # The success write runs outside the cancellation catcher: it is
        # shielded, so a cancel landing mid-write waits it out, then
        # propagates without a second terminal write overwriting success.
        # Only real errors route to failure here; CancelledError propagates.
        try:
            await ai_client._finalize_event_shielded(
                event_id=ctx.event_id,
                status="succeeded",
                feature=feature,
                model_alias=COMPLETE_PAGE_GATEWAY_MODEL,
                latency_ms=latency_ms,
                usage=usage,
                response_data=response_data,
                config=self._config,
                operation=ctx.operation,
                metadata=ctx.metadata,
                estimated_cost_usd=ctx.estimated_cost_usd,
                langfuse_input=ctx.langfuse_input,
                langfuse_output={
                    "artifact_kind": "complete_page",
                    "image_bytes": len(image_bytes),
                    "image_sha256": hashlib.sha256(image_bytes).hexdigest(),
                    "size": f"{width}x{height}",
                    "actual_provider_model": actual_provider_model,
                },
                started_at=ctx.started_at,
            )
        except Exception as exc:
            await finalise_image_failure(
                ctx=ctx,
                config=self._config,
                model=COMPLETE_PAGE_GATEWAY_MODEL,
                feature=feature,
                error=exc,
                error_response=response,
            )
            raise
        return CompletePageProviderResult(
            artifact_kind="complete_page",
            image_bytes=image_bytes,
            media_type="image/png",
            width=width,
            height=height,
            latency_ms=latency_ms,
            provider_request_id=payload.get("id"),
            actual_provider_model=actual_provider_model,
            usage=usage,
        )


async def draw_complete_page(
    compiled: CompiledPageGeneration,
    *,
    adapter: VertexCompletePageAdapter,
    artifacts: TargetArtifacts,
    page: ComicPage,
    ocr: "OCRAdapter | None" = None,
    request_revision: int | None = None,
    render_revision: int | None = None,
    parent_render_revision: int | None = None,
    defer_completion: bool = False,
) -> PageGenerationProvenance:
    """Persist and execute exactly one complete-page request."""

    correction = compiled.request.correction
    if correction is None and parent_render_revision is not None:
        raise ValueError("initial page generation cannot cite correction lineage")
    if correction is not None and (
        parent_render_revision != correction.parent_render_revision
    ):
        raise ValueError("complete-page correction must cite its exact parent render")
    if compiled.request.is_stale_for(page):
        raise ValueError("compiled request is stale for the canonical ComicPage")
    unfinished = artifacts.resumable_generation_request(page.page_number)
    if unfinished is not None and unfinished.request_sha256 != compiled.request.request_sha256:
        raise ValueError("Resume the unfinished paid generation before submitting different page input")
    artifacts.recover_generated_pages(page.page_number)
    for revision in reversed(artifacts.provenance_revisions(page.page_number)):
        saved = artifacts.read_provenance(page.page_number, revision)
        if (saved.render.request_sha256 == compiled.request.request_sha256
                and (render_revision is None or saved.render.revision == render_revision)):
            image = artifacts.read_render(page.page_number, saved.render.revision)
            if hashlib.sha256(image).hexdigest() != saved.render.image_sha256:
                raise ValueError("saved paid render bytes do not match provenance")
            if ocr is not None:
                await analyze_complete_page(
                    page=page, render=saved.render,
                    image=image,
                    ocr=ocr, artifacts=artifacts,
                )
            if not defer_completion:
                artifacts.mark_generation_complete(saved)
            return saved
    occupied_images = set(artifacts.render_revisions(page.page_number))
    occupied_provenance = set(artifacts.provenance_revisions(page.page_number))
    if occupied_images != occupied_provenance:
        raise ValueError(
            "Interrupted page persistence requires recovery before image generation: "
            "render/provenance revisions do not match; preserve existing artwork."
        )
    if render_revision is not None and render_revision in occupied_images:
        raise ValueError("render revision is occupied; no image request submitted")
    prepared = adapter.prepare(compiled)
    # Revisions are allocated here, inside the serialized job, not when the
    # route was called: two corrections requested before either ran would
    # otherwise both claim the same revision number and the second would die
    # on the immutable-artifact guard.
    next_render_revision = (
        max(
            artifacts.provenance_revisions(compiled.request.page_number),
            default=0,
        )
        + 1
    )
    if request_revision is None:
        request_revision = (
            max(
                artifacts.request_revisions(compiled.request.page_number),
                default=0,
            )
            + 1
        )
    if render_revision is None:
        render_revision = next_render_revision
    artifacts.write_request(
        compiled.request,
        request_revision=request_revision,
    )
    provider_result = await adapter.generate(prepared)
    # Do not publish the image until its complete paid-result journal exists.
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
    artifacts.persist_generated_page(provenance, provider_result.image_bytes)
    if ocr is not None:
        await analyze_complete_page(
            page=page,
            render=render,
            image=provider_result.image_bytes,
            ocr=ocr,
            artifacts=artifacts,
        )
    if not defer_completion:
        artifacts.mark_generation_complete(provenance)
    return provenance


def _analysis_usage(
    artifacts: TargetArtifacts,
    provenance: PageGenerationProvenance,
) -> tuple[UsageRecord, ...]:
    """The billable read-back call for this render, if it happened."""

    from novel_to_comic.target_artifacts import ArtifactMissing

    try:
        analysis = artifacts.read_analysis(
            provenance.render.page_number,
            provenance.render.revision,
        )
    except ArtifactMissing:
        return ()
    return () if analysis.analysis_usage is None else (analysis.analysis_usage,)


async def analyze_complete_page(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    ocr: "OCRAdapter",
    artifacts: TargetArtifacts,
) -> RenderAnalysis:
    """Read one existing render back and record its evidence and issues."""

    from novel_to_comic.page_review import (
        analyze_page_render,
        record_analysis_issues,
    )

    analyzed = await analyze_page_render(
        page=page,
        render=render,
        image=image,
        ocr=ocr,
        artifacts=artifacts,
    )
    record_analysis_issues(artifacts, analyzed.analysis)
    return analyzed.analysis


def reconcile_recovered_page_generation(
    *,
    artifacts: TargetArtifacts,
    render: PageRenderRevision,
) -> bool:
    """Complete recovered analysis only after durable original-call settlement.

    This is a read-only accounting check, never a debit or image retry. Missing
    evidence or unavailable accounting leaves the unfinished marker intact.
    """
    from novel_to_comic.server.db import get_db
    from novel_to_comic.target_artifacts import ArtifactMissing

    try:
        provenance = artifacts.read_provenance(render.page_number, render.revision)
        analysis = artifacts.read_analysis(render.page_number, render.revision)
    except ArtifactMissing:
        return False
    if analysis.comic_page_sha256 != render.comic_page_sha256:
        return False
    if provenance.render != render or analysis.render_image_sha256 != render.image_sha256:
        return False
    if hashlib.sha256(artifacts.read_render(render.page_number, render.revision)).hexdigest() != render.image_sha256:
        return False
    if provenance.usage is None:
        return False
    calls = (provenance.usage, *_analysis_usage(artifacts, provenance))
    try:
        db = get_db()
        for usage in calls:
            rows = (
                db.table("credit_ledger").select("usage_call_id,status")
                .eq("usage_call_id", usage.call_id).eq("status", "settled")
                .limit(1).execute().data
            )
            if not rows:
                return False
    except Exception:
        return False
    artifacts.mark_generation_complete(provenance)
    try:
        failure = artifacts.read_page_failure(render.page_number)
    except ArtifactMissing:
        pass
    else:
        if failure.request_sha256 == render.request_sha256:
            artifacts.clear_page_failure(render.page_number)
    return True


async def correct_complete_page(
    compiled: CompiledPageGeneration,
    *,
    issue: PageIssue | None,
    adapter: VertexCompletePageAdapter,
    artifacts: TargetArtifacts,
    page: ComicPage,
    ocr: "OCRAdapter | None" = None,
    request_revision: int | None = None,
    render_revision: int | None = None,
    defer_completion: bool = False,
) -> PageGenerationProvenance:
    """Produce one complete revised page for an explicit correction set.

    Manual issues are created here, inside the reserved job, after the credit
    hold is accepted — never during preview or before deduplication.
    Selected Draw issues move to resolved only when lettering validity proves
    the fix; every other selected issue (including all visual findings) moves
    to revised and stays there until a person confirms it. Unselected issues
    are never touched. A note-only correction carries no issue at all.
    """
    correction = compiled.request.correction
    if correction is None:
        raise ValueError("compiled request carries no correction")
    if issue is not None:
        if issue.id not in correction.issue_ids:
            raise ValueError("compiled request does not correct the supplied page issue")
        if issue.correction_owner != "draw":
            raise ValueError("copy changes must return to Adapt and Plan")
    from novel_to_comic.page_review import ensure_correction_issues

    ensure_correction_issues(artifacts, correction=correction)

    provenance = await draw_complete_page(
        compiled,
        adapter=adapter,
        artifacts=artifacts,
        page=page,
        ocr=ocr,
        request_revision=request_revision,
        render_revision=render_revision,
        parent_render_revision=correction.parent_render_revision,
        defer_completion=True,
    )
    from novel_to_comic.page_review import resolve_page_issue

    analysis = (artifacts.read_analysis(page.page_number, provenance.render.revision)
                if ocr is not None else None)
    corrected_issues = artifacts.read_issues(page.page_number) if correction.issue_ids else ()
    for corrected in corrected_issues:
        if corrected.id not in correction.issue_ids:
            continue
        verified = (
            corrected.issue_type in {"misspelled_lettering", "missing_lettering", "duplicated_lettering", "invented_lettering", "reordered_lettering"}
            and corrected.id.startswith("page-issue-draw-page-")
            and analysis is not None and analysis.lettering_valid
        )
        resolve_page_issue(
            artifacts, issue_id=corrected.id, page_number=page.page_number,
            resolution_revision=provenance.render.revision, verified=verified,
        )
    if not defer_completion:
        artifacts.mark_generation_complete(provenance)
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
    page: ComicPage,
    ocr: "OCRAdapter | None" = None,
    request_revision: int | None = None,
    render_revision: int | None = None,
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
        float(compiled.request.estimated_cost_usd)
        + (0.0 if ocr is None else float(PAGE_OCR_ESTIMATED_COST_USD)),
        "draw",
        reserve=True,
        zero_cost_estimate=0,
    )

    async def _draw() -> ApiResult[PageGenerationProvenance]:
        try:
            if compiled.request.correction is None:
                provenance = await draw_complete_page(
                    compiled,
                    adapter=adapter,
                    artifacts=artifacts,
                    page=page,
                    ocr=ocr,
                    request_revision=request_revision,
                    render_revision=render_revision,
                    parent_render_revision=parent_render_revision,
                    defer_completion=True,
                )
            else:
                provenance = await correct_complete_page(
                    compiled,
                    issue=issue,
                    adapter=adapter,
                    artifacts=artifacts,
                    page=page,
                    ocr=ocr,
                    request_revision=request_revision,
                    render_revision=render_revision,
                    defer_completion=True,
                )
        except BaseException as exc:
            from novel_to_comic.image_failure import (
                classify_image_failure,
                user_message_for_image_failure,
            )

            provenance_revisions = artifacts.provenance_revisions(
                compiled.request.page_number
            )
            analysis_failed = False
            if provenance_revisions:
                latest = artifacts.read_provenance(
                    compiled.request.page_number,
                    provenance_revisions[-1],
                )
                analysis_failed = (
                    latest.render.request_sha256
                    == compiled.request.request_sha256
                    and not artifacts.analysis_path(
                        compiled.request.page_number,
                        latest.render.revision,
                    ).exists()
                )
            classification = (
                "analysis_error"
                if analysis_failed
                else classify_image_failure(exc)
            )
            user_message = (
                "The page is already drawn, but its text check could not be "
                "completed. Retry the text check without redrawing the page."
                if analysis_failed
                else user_message_for_image_failure(classification)
            )
            artifacts.write_page_failure(
                PageGenerationFailure(
                    page_number=compiled.request.page_number,
                    request_sha256=compiled.request.request_sha256,
                    failed_at=datetime.now(UTC),
                    phase="analysis" if analysis_failed else "generation",
                    classification=classification,
                    recoverable=classification != "configuration_error",
                    user_message=user_message,
                    error=(str(exc) or type(exc).__name__)[:1000],
                )
            )
            setattr(exc, "page_failure_phase", "analysis" if analysis_failed else "generation")
            raise
        return ApiResult(
            value=provenance,
            usage=provenance.usage,
            provider_request_id=provenance.provider_request_id,
            actual_provider_model=provenance.render.model,
            additional_usage=_analysis_usage(artifacts, provenance),
        )

    async def _work() -> ApiResult[PageGenerationProvenance]:
        from novel_to_comic.server.credited_job import page_operation_lock

        async with page_operation_lock(project_dir, page.page_number):
            return await _draw()

    def _settled(result: ApiResult[PageGenerationProvenance]) -> None:
        artifacts.clear_page_failure(compiled.request.page_number)
        if on_success is not None:
            on_success(result.value)
        artifacts.mark_generation_complete(result.value)

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
            "issue_ids": list(compiled.request.correction.issue_ids) if compiled.request.correction else [],
        },
        work=_work,
        debit_description=f"Complete page {compiled.request.page_number}",
        reservation_credits=estimate["reserved_credits"] or 0,
        on_settled=_settled,
    )
