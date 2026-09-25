"""Complete-page Draw compilation, profile-bound submission, and persistence."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import re
import time
from datetime import UTC, datetime
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from math import gcd
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
    GPT25_PAGE_ESTIMATED_COST_USD,
    GPT25_REFERENCE_ESTIMATED_COST_USD,
    MUSE_PAGE_ESTIMATED_COST_USD,
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
from novel_to_comic.style_contract import page_style_template, page_art_style_template, POST_LETTERING_MARKER, DESIGN_MARKER
from novel_to_comic.reference_sheets import MAX_MEMBERS_PER_SHEET, pack_page_references
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_BLOCK
from novel_to_comic.usage import ApiResult, UsageRecord, calculate_cost, calculate_cost_breakdown

if TYPE_CHECKING:
    from fastapi import FastAPI
    from novel_to_comic.page_review import OCRAdapter, PageCorrectionContext
    from novel_to_comic.server.generation_jobs import GenerationJob


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ApprovedReferenceFile:
    """The Cast-owned bytes for one approved visual-reference authority."""

    reference_id: str
    path: Path
    media_type: str
    metadata_path: Path | None = None


@dataclass(frozen=True, slots=True)
class CompiledPageGeneration:
    """A frozen semantic request paired with its verified bytes in one order."""

    request: FrozenPageGenerationRequest
    reference_bytes: tuple[bytes, ...]
    edit_source_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class PreparedCompletePageRequest:
    """The exact immutable complete-page request handed to a selected adapter."""

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
        request: PreparedCompletePageRequest,
    ) -> CompletePageProviderResult: ...


class CompletePageAdapter(Protocol):
    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest: ...

    async def generate(self, prepared: PreparedCompletePageRequest) -> CompletePageProviderResult: ...


def legacy_vertex_page_capability_profile() -> PageCapabilityProfile:
    """Describe retained Vertex editions without selecting Vertex for new work."""

    return PageCapabilityProfile(
        id=COMPLETE_PAGE_PROFILE_ID + "-hybrid-v1",
        exact_visible_lettering=False,
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


def openai_page_capability_profile(model: str) -> PageCapabilityProfile:
    if model not in {"gpt-image-2.5-sunburst", "gpt-image-2.5-flare"}:
        raise ValueError("Unsupported complete-page OpenAI model")
    return PageCapabilityProfile(
        id=f"{model}-complete-page-high-hybrid-v1", exact_visible_lettering=False, provider="openai", model=model,
        max_image_references=16, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1024, output_height=1536, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
        price_per_page_usd=Decimal(GPT25_PAGE_ESTIMATED_COST_USD),
        price_per_reference_usd=Decimal(GPT25_REFERENCE_ESTIMATED_COST_USD),
    )


def fal_sunburst_page_capability_profile() -> PageCapabilityProfile:
    """Sunburst complete pages routed through fal.ai's queue adapter."""
    return PageCapabilityProfile(
        id="gpt-image-2.5-sunburst-fal-complete-page-high-hybrid-v1",
        exact_visible_lettering=False, provider="fal-queue", model="openai/gpt-image-2.5/sunburst",
        max_image_references=16, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1024, output_height=1536, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
        price_per_page_usd=Decimal(GPT25_PAGE_ESTIMATED_COST_USD),
        price_per_reference_usd=Decimal(GPT25_REFERENCE_ESTIMATED_COST_USD),
    )


def production_page_capability_profile() -> PageCapabilityProfile:
    """Return the only complete-page profile offered for new API work."""
    return fal_sunburst_page_capability_profile()


def muse_page_capability_profile() -> PageCapabilityProfile:
    """Return Muse's empirically verified native portrait complete-page profile."""
    return PageCapabilityProfile(
        # OpenRouter's image endpoint returns native 1280×1920 portrait output
        # when requested with size="1280x1920", as verified by live probes.
        id="muse-image-complete-page-hybrid-v2", exact_visible_lettering=False, provider="openrouter", model="meta/muse-image",
        max_image_references=10, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1280, output_height=1920, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
        price_per_page_usd=Decimal(MUSE_PAGE_ESTIMATED_COST_USD),
        price_per_reference_usd=Decimal("0"),
    )


def _supported_page_profile(profile: PageCapabilityProfile) -> bool:
    if profile.exact_visible_lettering and profile.id.endswith("-integrated-v1"):
        return _supported_page_profile(profile.model_copy(update={
            "id": profile.id.removesuffix("-integrated-v1"),
            "exact_visible_lettering": False,
        }))
    from novel_to_comic.codex_dev import model_has_vision, selectable_models, selector_available

    if profile == current_page_capability_profile() or any(
        profile == openai_page_capability_profile(model)
        for model in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare")
    ) or profile in (fal_sunburst_page_capability_profile(), _integrated_page_profile(fal_sunburst_page_capability_profile())) or profile == muse_page_capability_profile():
        return True
    return selector_available() and any(
        profile == current_page_capability_profile(Config(draw_model=f"codex-dev/image/{model}"))
        for model in selectable_models() if model_has_vision(model)
    )


_CODEX_PAGE_PROFILE_PREFIX = "codex-dev-complete-page-hybrid-v1-"
_LEGACY_CODEX_PAGE_PROFILE_PREFIX = "codex-dev-complete-page-v1-"


def _integrated_page_profile(profile: PageCapabilityProfile) -> PageCapabilityProfile:
    return profile.model_copy(update={
        "id": profile.id + "-integrated-v1", "exact_visible_lettering": True,
    })


def current_page_capability_profile(config: Config | None = None) -> PageCapabilityProfile:
    profile = _editable_page_capability_profile(config)
    if config is not None and config.lettering_mode == "integrated":
        return _integrated_page_profile(profile)
    return profile


def _editable_page_capability_profile(config: Config | None = None) -> PageCapabilityProfile:
    """Select only from original-process complete-page routing authority."""
    from novel_to_comic.codex_dev import route_for

    selected = getattr(config, "draw_model", COMPLETE_PAGE_GATEWAY_MODEL)
    if selected == "image-sunburst":
        return fal_sunburst_page_capability_profile()
    if selected != COMPLETE_PAGE_GATEWAY_MODEL and not selected.startswith("codex-dev/image/"):
        raise ValueError("Unsupported complete-page model selection")
    route = route_for("complete_page", selected)
    if route is None:
        return production_page_capability_profile()
    if route.image_model != "gpt-image-2":
        raise ValueError("Unsupported Codex complete-page image selector")
    from novel_to_comic.ai import codex_runtime
    binding = json.dumps(
        [route.reasoning_model, sorted(codex_runtime.image_execution_controls())]
        + ([selected] if selected.startswith("codex-dev/image/") else []),
        separators=(",", ":"), ensure_ascii=False,
    )
    return PageCapabilityProfile(
        id=_CODEX_PAGE_PROFILE_PREFIX + hashlib.sha256(binding.encode()).hexdigest(),
        exact_visible_lettering=False,
        provider="codex-dev",
        model=route.image_model,
        max_image_references=5,
        reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=COMPLETE_PAGE_OUTPUT_WIDTH,
        output_height=COMPLETE_PAGE_OUTPUT_HEIGHT,
        max_prompt_characters=COMPLETE_PAGE_MAX_PROMPT_CHARACTERS,
        retry_semantics="bounded_submission",
        max_attempts=1,
        price_per_page_usd=Decimal("0"),
        price_per_reference_usd=Decimal("0"),
    )


def page_profile_uses_native_dimensions(profile: PageCapabilityProfile) -> bool:
    """Recognize retained native editions without requiring their runtime active."""
    return (
        profile.provider == "codex-dev"
        and profile.model == "gpt-image-2"
        and any(re.fullmatch(re.escape(prefix) + r"[0-9a-f]{64}", profile.id.removesuffix("-integrated-v1")) is not None
                for prefix in (_CODEX_PAGE_PROFILE_PREFIX, _LEGACY_CODEX_PAGE_PROFILE_PREFIX))
    )


def complete_page_adapter(config: Config) -> CompletePageAdapter:
    profile = current_page_capability_profile(config)
    if profile.provider == "fal-queue":
        return OpenAICompletePageAdapter(config, profile)
    if profile.provider == "openai":
        return OpenAICompletePageAdapter(config, profile)
    if profile.provider == "openrouter":
        return OpenRouterCompletePageAdapter(config, profile)
    if page_profile_uses_native_dimensions(profile):
        from novel_to_comic.codex_complete_page import CodexCompletePageAdapter

        return CodexCompletePageAdapter(config)
    return VertexCompletePageAdapter(GoogleVertexCompletePageTransport(config), profile)



def retained_baked_profile(profile: PageCapabilityProfile) -> bool:
    """Recognize saved editions for inspection, never select them for new spend."""
    if not profile.exact_visible_lettering:
        return False
    return (
        (profile.id == COMPLETE_PAGE_PROFILE_ID and profile.provider == COMPLETE_PAGE_PROVIDER and profile.model == COMPLETE_PAGE_MODEL)
        or (profile.provider == "openai" and profile.model in {"gpt-image-2.5-sunburst", "gpt-image-2.5-flare"}
            and profile.id == f"{profile.model}-complete-page-high-v1")
        or (profile.provider == "openrouter" and profile.model == "meta/muse-image" and profile.id == "muse-image-complete-page-v2")
        or (profile.provider == "codex-dev" and profile.model == "gpt-image-2"
            and re.fullmatch(re.escape(_LEGACY_CODEX_PAGE_PROFILE_PREFIX) + r"[0-9a-f]{64}", profile.id) is not None)
    )

def select_book_edition(
    *,
    edition_id: str,
    profile: PageCapabilityProfile,
    existing: BookEdition | None = None,
) -> BookEdition:
    """Select the process-bound profile without changing an existing edition."""

    if (
        existing is not None
        and (
            edition_id != existing.id
            or profile != existing.capability_profile
        )
    ):
        raise ValueError("one model and capability profile are fixed for the edition")
    if not _supported_page_profile(profile) and not (existing is not None and retained_baked_profile(profile)):
        raise ValueError(
            "provider/model does not satisfy the current complete-page capability profile; "
            "existing editions cannot change profiles"
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
    config: Config | None = None,
    *, allow_retained_review: bool = False,
) -> BookEdition:
    """New spend is strict; retained baked art remains inspectable without rebinding."""
    if allow_retained_review and retained_baked_profile(edition.capability_profile):
        return edition
    if edition.capability_profile != current_page_capability_profile(config):
        raise ValueError(
            "This edition uses a different page profile. Existing editions cannot "
            "change profiles; existing pages will not be mixed with another model."
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
    cast_art_direction: Mapping[str, str] | None = None,
    exact_visible_lettering: bool = True,
    reference_bindings: Mapping[str, dict] | None = None,
    style_reference: PageReference | None = None,
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

    def acting(content, entity_id):
        # Plan's per-panel performance overrides the reference sheet's pose and face.
        item = next((item for item in content.acting if item.entity_id == entity_id), None)
        if item is None:
            return {}
        return {"acting": {
            "facing": item.facing.replace("_", " ") + " (reader's screen direction)",
            "gaze": provider_safe_direction(item.gaze),
            "expression": provider_safe_direction(item.expression),
            **({"gesture": provider_safe_direction(item.gesture)} if item.gesture.strip() else {}),
        }}

    def subjects(content):
        return [
            {
                "subject": handles[entity_id],
                **acting(content, entity_id),
                "references": [
                    {
                        "image": _off_canvas_handle("asset", (reference_bindings or {}).get(ref.id, {}).get("input_order", ref.order)),
                        **({key: value for key, value in reference_bindings[ref.id].items() if key != "input_order"}
                           if reference_bindings and ref.id in reference_bindings else {}),
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
            "advance asset ordering. The selected_style_proof is rendering evidence only. "
            "Use each subject asset only for its assigned subject and state; "
            "preserve hairstyle, age, facial structure, clothing design and recurring object "
            "features shown by that authority unless the assigned state explicitly changes them. "
            "Character references establish identity and appearance, not a fixed pose, facing "
            "direction, gaze, expression or camera angle. Re-stage each character for the panel's "
            "action and relationships: direct eyelines toward the relevant person or event, "
            "and choose body orientation, gesture and expression from the scene. Use profiles, "
            "rear views and opposing eyelines when the scene calls for them; do not default "
            "to the reference portrait's three-quarter view or camera-facing lineup. When a "
            "visible subject carries acting, draw exactly that facing, gaze target, expression "
            "and gesture, and frame the panel with its camera shot and angle. Preserve "
            "anatomical constraints and sided identifying features when changing viewpoint; "
            "do not mirror asymmetric features. Respect canonical staging, continuity and "
            "author pins rather than varying direction arbitrarily. For corrections, change "
            "acting or viewpoint only within the requested scope; preserve untouched artwork. "
            "When an asset includes owner art_direction, it records the approved Cast design: "
            "it overrides conflicting source appearance and continuity defaults for that asset/state. "
            "Preserve its requested design in the page without changing exact lettering or story events."
        ),
        "approved_page_references": [
            {
                "image": _off_canvas_handle("asset", (reference_bindings or {}).get(reference.id, {}).get("input_order", reference.order)),
                **({key: value for key, value in reference_bindings[reference.id].items() if key != "input_order"}
                   if reference_bindings and reference.id in reference_bindings else {}),
                "subject": handles[reference.entity_id],
                "appearance": reference.label,
                "visual_anchor": reference.visual_anchor,
                "continuity_guard": reference.continuity_guard,
                **({"art_direction": cast_art_direction[reference.id]}
                   if cast_art_direction and reference.id in cast_art_direction else {}),
            }
            for reference in references
        ],
        "project_style_direction": page_style_template(style_template.split(POST_LETTERING_MARKER, 1)[0].split(DESIGN_MARKER, 1)[0]) if style_template.strip() else None,
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
                    **({"camera": f"{content.camera.shot.replace('_', ' ')} shot, "
                                  f"{content.camera.angle.replace('_', ' ')}"}
                       if content.camera else {}),
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
            # The initial frozen request is preserved verbatim in correction
            # provenance, but replaying that complete prompt duplicates the
            # current Plan, style, copy and reference authorities above. It
            # can consume half a fixed-profile prompt by itself. Keep prior
            # authored corrections in order; current authorities supply the
            # original page intent without re-sending its full specification.
            "retained_render_intent": [instruction for instruction in correction.retained_instructions
                                       if not instruction.startswith("PAGE CANVAS: ")],
            "retained_intent_scope": (
                "Preserve deliberate depiction and earlier author corrections only where consistent "
                "with current canonical copy, approved identity/state/style and author pins. "
                "Current changes supersede conflicting earlier changes. The original complete "
                "page specification is retained in provenance; current canonical authorities "
                "supply its page intent without duplicating its old bindings."
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
    if style_reference is not None:
        payload["selected_style_proof"] = {
            "image": _off_canvas_handle("asset", style_reference.order),
            "authority": style_reference.visual_anchor,
        }
    if not exact_visible_lettering:
        if page.lettering_reservations is None:
            raise ValueError("This Plan predates lettering reservations. Rerun Plan before drawing a hybrid edition.")
        payload.pop("exact_lettering")
        payload["project_style_direction"] = page_art_style_template(style_template)
        # Placement reservations seed the editable layer only; exposing them to
        # the image model can bake blank caption boxes into the artwork.
        return _hybrid_prompt(payload, page, depiction)
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
        f"{RENDERING_FIDELITY_BLOCK}\n"
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



def _hybrid_prompt(payload: dict, page: ComicPage, depiction: str) -> str:
    copy = sorted({item.text for content in page.content for item in content.lettering}, key=len, reverse=True)

    # Remove quoted publishable phrases from editorial/context prose without
    # corrupting identifiers or verbatim reference authorities. Short utterances
    # can also be ordinary English ("I", "No"); their occurrence in visual prose
    # is not a lettering payload. Canonical text fields are absent altogether.
    authority_fields = {"visual_anchor", "continuity_guard"}

    def without_copy(value, field=""):
        if field in authority_fields:
            return value
        if isinstance(value, str):
            for text in copy:
                if text and len(text.strip()) >= 12:
                    value = value.replace(text, "[story copy omitted]")
            return value
        if isinstance(value, list):
            return [without_copy(item, field) for item in value]
        if isinstance(value, dict):
            return {key: without_copy(item, key) for key, item in value.items()}
        return value

    payload = without_copy(payload)
    policy = (
        "Render exactly one COMPLETE COMIC PAGE of base artwork, never per-panel assets.\n"
        "LETTERING POLICY: Final dialogue, thoughts, narration, captions and sound effects are added "
        "after illustration by Canary. Draw NO speech or thought balloons, caption/narration boxes, "
        "SFX glyphs, subtitles, words, placeholder text, lorem ipsum or pseudo-writing for these elements. "
        "Draw continuous scene artwork throughout every panel. Do not reserve space for lettering "
        "or draw blank boxes, empty balloons, parchment patches, placeholder areas or tail corridors, "
        "even if layout notes or reference images suggest them. "
        "Legitimate in-world signage is distinct; never substitute it for publishable copy.\n"
        "AUTHORITY: preserve approved subject/state references, physical anchors and continuity guards "
        "verbatim in meaning, current staging, selected art direction, page framing and author pins. "
        "Compose each scene naturally within its panel. "
        "Style proof images are RENDERING/STYLE authority only: do not copy their words, balloons, "
        "captions or page content. Subject and location assets own identity, state, architecture "
        "and material identity; they do not prescribe an additional surface-texture layer. "
        "The selected art direction owns rendering. Preserve authored markings and deliberate "
        "medium texture, but do not transfer incidental paper stains or mottling onto skin, "
        "clothing, sky and other unrelated materials. Reconstruct new surfaces with coherent "
        "tonal areas and material-specific marks. For corrections, this does not authorize "
        "cleanup outside the requested change. "
        "The parent-edit-base is immutable art, not a lettered proof.\n"
    )
    if depiction == "less_graphic":
        policy += "Use framing, shadow, reaction or aftermath for graphic details; preserve identity, story and references.\n"
    return policy + json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + (
        "\nOUTPUT: one complete page of continuous scene artwork. NO generated comic lettering."
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
    style_reference_path: Path | None = None,
) -> CompiledPageGeneration:
    """Compile one immutable request from canonical Plan and Cast authority."""

    selected_edition = select_book_edition(
        edition_id=edition.id,
        profile=edition.capability_profile,
        existing=edition,
    )
    # RetryProvenance counts author-requested generations, not automatic
    # submissions within one operation. Each draw invokes the provider once.
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
    if (page_profile_uses_native_dimensions(selected_edition.capability_profile) or selected_edition.capability_profile.provider in {"openai", "openrouter", "fal-queue"}) and correction is not None:
        max_references -= 1  # The parent is an input image, never an authority replacement.
    if style_reference_path is not None:
        max_references -= 1  # Keep the proof separate from subject transport sheets.
    if max_references < 0:
        raise ValueError("This edition has no image capacity for the selected Style proof and edit parent")
    sheet_capacity = max_references * MAX_MEMBERS_PER_SHEET if selected_edition.capability_profile.provider == "codex-dev" else max_references
    if len(authorities) > sheet_capacity:
        raise ValueError(
            f"Page {page.page_number} requires {len(authorities)} approved references, "
            f"but this edition can carry {sheet_capacity} with its available image inputs. "
            "Choose a higher-capacity Draw model before starting an edition, or revise "
            "the book's page composition. Identity references will not be silently dropped."
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
    # Use direction stored with the rendered image, never a newer failed draft.
    # Version restoration restores this sidecar alongside the reference pixels.
    cast_art_direction: dict[str, str] = {}
    for reference in references:
        source = reference_files[reference.id]
        meta_path = source.metadata_path or source.path.with_suffix(f"{source.path.suffix}.meta.json")
        if meta_path.exists():
            metadata = json.loads(meta_path.read_text())
            direction = metadata.get("art_direction")
            if isinstance(direction, str) and direction.strip():
                cast_art_direction[reference.id] = direction
    uploaded_references, uploaded_bytes, reference_bindings = pack_page_references(
        references, loaded, max_references,
    ) if selected_edition.capability_profile.provider == "codex-dev" else (tuple(references), tuple(loaded), {})
    style_reference = None
    if style_reference_path is not None:
        try:
            style_bytes = style_reference_path.read_bytes()
        except OSError as exc:
            raise ValueError("Selected Style proof is unreadable. Rerun Style before Draw.") from exc
        if not style_bytes:
            raise ValueError("Selected Style proof is empty. Rerun Style before Draw.")
        style_reference = PageReference(
            id="selected-style-proof", entity_id=None,
            order=len(uploaded_references) + 1, media_type="image/png",
            content_sha256=hashlib.sha256(style_bytes).hexdigest(),
            label="Selected Style proof",
            visual_anchor=(
                "Rendering authority only: match the selected proof's medium, palette, "
                "line weight, edge treatment, shadow depth, facial abstraction, character "
                "proportion system and degree of simplification. Transfer how people and "
                "environments are drawn, not their identities, hairstyles, costumes or content. "
                "Cast assets own identity and active-state anatomy; they do not override this "
                "rendering language or prescribe an additional surface-texture layer. "
                "Do not copy the proof's poses, gaze, expressions, camera angles, composition, "
                "panels, text or lettering. Plan owns staging and acting; the selected written "
                "standards own page framing and lettering. Preserve authored material marks "
                "without amplifying incidental texture. For corrections preserve untouched "
                "artwork; this reference does not authorize restyling outside the requested scope."
            ),
        )
        uploaded_references += (style_reference,)
        uploaded_bytes += (style_bytes,)
    profile = selected_edition.capability_profile
    prompt_context = correction_context
    prompt = _compile_prompt(
        page,
        tuple(references),
        correction,
        depiction,
        style_template,
        prompt_context,
        cast_art_direction,
        exact_visible_lettering=profile.exact_visible_lettering,
        reference_bindings=reference_bindings,
        style_reference=style_reference,
    )
    if correction is not None and correction_context is not None and len(prompt) > profile.max_prompt_characters - 1024:
        # A long book's entire beat/transition history can exceed a fixed
        # Draw edition's prompt capacity before its page-specific authorities
        # are added. Keep the full context and digest on the correction, but
        # send nearby beats plus the book's causal spine to the image model.
        # Exact author-selected sources, current Plan and visual anchors stay.
        active = {beat for content in page.content for beat in content.beat_ids}
        ordered = correction_context.beat_ids
        indexes = {i for i, beat in enumerate(ordered) if beat in active}
        nearby = {ordered[j] for i in indexes for j in range(max(0, i - 1), min(len(ordered), i + 2))}
        prompt_context = correction_context.model_copy(update={
            "beat_summaries": tuple(summary for beat, summary in zip(
                ordered, correction_context.beat_summaries, strict=True,
            ) if beat in nearby),
            "beat_transitions": tuple(item for item in correction_context.beat_transitions
                                      if any(item.startswith(f"Beat {beat} [") for beat in nearby)),
            "appearance_chronology": tuple(item for item in correction_context.appearance_chronology
                                            if any(item.startswith(f"Beat {beat} [") for beat in nearby)),
        })
        prompt = _compile_prompt(
            page,
            tuple(references),
            correction,
            depiction,
            style_template,
            prompt_context,
            cast_art_direction,
            exact_visible_lettering=profile.exact_visible_lettering,
            reference_bindings=reference_bindings,
            style_reference=style_reference,
        )
    if reference_bindings:
        prompt += (
            "\nREFERENCE SHEETS: asset-A, asset-B, etc. identify uploaded authority images in order "
            "(excluding parent-edit-base). Some contain two separately labeled references. "
            "region_pixels and sheet dimensions locate each subject's original image; preserve "
            "each subject's separate identity, state, anchors and continuity. Labels and sheet "
            "borders are off-canvas reference guides: never draw them, combine identities, or "
            "copy the sheet arrangement into the comic page."
        )
    # Native image tools may expose only automatic sizing, so the frozen prompt
    # must carry the same canvas authority as providers' structured size fields.
    prompt = (
        f"PAGE CANVAS: {profile.output_width} pixels wide by {profile.output_height} pixels high. "
        "Use this portrait width-to-height ratio for the entire output image on every page. "
        "Panel layout and story density must fit inside this fixed page canvas; they must not "
        "change its aspect ratio. Never output a landscape or square canvas, rotate the page, "
        "or add blank padding to simulate the requested shape. Reference images and correction "
        "parents do not override this output canvas requirement.\n"
    ) + prompt
    request = FrozenPageGenerationRequest.compile(
        page=page,
        edition=selected_edition,
        prompt=prompt,
        references=uploaded_references,
        retry=retry,
        correction=correction,
    )
    return CompiledPageGeneration(
        request=request,
        reference_bytes=uploaded_bytes,
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
    style_reference_path: Path | None = None,
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
        style_reference_path=style_reference_path,
        depiction=correction.depiction,
    )
    return PreparedPageCorrection(correction=correction, compiled=compiled, context=context)


def estimate_draw_api_cost(
    config: Config, image_cost: float, *, ocr: bool | None = None,
    compiled: CompiledPageGeneration | None = None,
) -> float:
    """Include only the API portions of a page render and its automatic readback."""
    from novel_to_comic.codex_dev import route_for
    from novel_to_comic.server.codex_admission import draw_reads_pages

    ocr = draw_reads_pages(config) if ocr is None else ocr

    if compiled is not None and compiled.request.provider in {"openai", "fal-queue"}:
        from novel_to_comic.usage import estimate_image_cost

        request = compiled.request
        # Pricing is a current quote, separate from the frozen edition and
        # request identity. Corrections also send the parent page as an input.
        image_cost = estimate_image_cost(
            request.model, 1, quality="high",
            ref_count=len(request.references) + int(compiled.edit_source_bytes is not None),
            prompt_text=request.prompt,
            width=request.output_width, height=request.output_height,
        )
    total = 0.0 if route_for("complete_page", config.draw_model) else image_cost
    if ocr and route_for("text", config.effective_page_ocr_model()) is None:
        total += float(PAGE_OCR_ESTIMATED_COST_USD)
    return total


def correction_credit_estimate(compiled: CompiledPageGeneration, *, config: Config, reserve: bool):
    """Credit estimate for one compiled artwork correction."""
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    funding = classify_operations(draw_operations(config))

    return credit_estimate_for_provider_cost(
        estimate_draw_api_cost(config, float(compiled.request.estimated_cost_usd), compiled=compiled),
        "draw",
        reserve=reserve,
        zero_cost_estimate=0,
        funding=funding,
    )


def _validate_compiled_page(
    compiled: CompiledPageGeneration, profile: PageCapabilityProfile, *, drawable: bool = True,
) -> None:
    request = compiled.request
    if drawable and not _supported_page_profile(profile):
        raise ValueError("Complete-page profile changed; existing requests cannot be rerouted")
    if (
        request.profile_id != profile.id
        or request.profile_sha256 != profile.content_sha256
        or request.provider != profile.provider
        or request.model != profile.model
        or (request.output_width, request.output_height) != (profile.output_width, profile.output_height)
        or request.output_media_type != profile.output_media_type
        or len(request.prompt) > profile.max_prompt_characters
        or request.estimated_cost_usd != profile.price_per_page_usd + profile.price_per_reference_usd * len(request.references)
    ):
        raise ValueError("Frozen complete-page request does not match the selected profile")
    total = len(request.references)
    if (page_profile_uses_native_dimensions(profile) or profile.provider in {"openai", "openrouter", "fal-queue"}) and request.correction is not None:
        total += 1
    if total > profile.max_image_references:
        raise ValueError("Complete-page image inputs exceed profile capacity; references cannot be dropped")
    if request.correction is not None and request.correction.mode not in profile.editing_modes:
        raise ValueError("Correction mode is unsupported by the selected profile")
    if len(request.references) != len(compiled.reference_bytes):
        raise ValueError("reference metadata and uploaded bytes must be one-to-one")
    for reference, data in zip(request.references, compiled.reference_bytes, strict=True):
        if hashlib.sha256(data).hexdigest() != reference.content_sha256:
            raise ValueError(f"selected reference {reference.order} bytes changed after compilation")
    if request.correction is None:
        if compiled.edit_source_bytes is not None:
            raise ValueError("initial generation cannot submit an edit source")
    elif compiled.edit_source_bytes is None or (
        hashlib.sha256(compiled.edit_source_bytes).hexdigest() != request.correction.parent_render_image_sha256
    ):
        raise ValueError("complete-page edit source changed after compilation")


def validate_review_request(compiled: CompiledPageGeneration, edition: BookEdition) -> None:
    """Check the compiled evidence for reviewing existing art under its own edition.

    Review reads a finished render; it never draws, so it must not require the
    edition's profile to be selectable for new pages today.
    """
    _validate_compiled_page(compiled, edition.capability_profile, drawable=False)


def _prepare_complete_page(
    compiled: CompiledPageGeneration, profile: PageCapabilityProfile,
) -> PreparedCompletePageRequest:
    _validate_compiled_page(compiled, profile)
    request = compiled.request
    return PreparedCompletePageRequest(
        request_sha256=request.request_sha256, model=request.model, prompt=request.prompt,
        references=request.references, reference_bytes=compiled.reference_bytes,
        edit_source_bytes=compiled.edit_source_bytes,
        width=request.output_width, height=request.output_height,
        media_type=request.output_media_type, idempotency_key=request.request_sha256,
        estimated_cost_usd=request.estimated_cost_usd, frozen_request_json=request.model_dump_json(),
    )


def _validate_prepared_page(
    prepared: PreparedCompletePageRequest, profile: PageCapabilityProfile,
) -> None:
    request = FrozenPageGenerationRequest.model_validate_json(prepared.frozen_request_json)
    compiled = CompiledPageGeneration(request, prepared.reference_bytes, prepared.edit_source_bytes)
    if prepared != _prepare_complete_page(compiled, profile):
        raise ValueError("Prepared complete-page request differs from its frozen semantic request")


class VertexCompletePageAdapter:
    """Validate a frozen complete-page request and its transport result."""

    def __init__(self, transport: CompletePageTransport, profile: PageCapabilityProfile | None = None) -> None:
        self._transport = transport
        self._profile = profile or production_page_capability_profile()

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        request = compiled.request
        if request.provider != self._profile.provider or request.model != self._profile.model:
            raise ValueError("complete-page request is not bound to the adapter profile")
        return _prepare_complete_page(compiled, self._profile)

    async def generate(
        self,
        prepared: PreparedCompletePageRequest,
    ) -> CompletePageProviderResult:
        _validate_prepared_page(prepared, self._profile)
        result = await self._transport.generate(prepared)
        actual_model = result.actual_provider_model
        for prefix in ("vertex_ai/", "vertex-multimodal/"):
            if actual_model is not None and actual_model.startswith(prefix):
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
        self._profile = current_page_capability_profile(config)
        self._gateway_model = COMPLETE_PAGE_GATEWAY_MODEL

    async def generate(
        self,
        request: PreparedCompletePageRequest,
    ) -> CompletePageProviderResult:
        from PIL import Image
        from novel_to_comic.ai import client as ai_client
        from novel_to_comic.ai.finalisation import (
            begin_image_call,
            finalise_image_cancelled,
            finalise_image_failure,
        )

        _validate_prepared_page(request, self._profile)
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
            "model": self._gateway_model,
            "prompt": request.prompt,
            "response_format": "b64_json",
            "canary_complete_page_request": request.frozen_request_json,
            "canary_requested_width": str(request.width),
            "canary_requested_height": str(request.height),
            "canary_requested_aspect": str(request.width / request.height),
            "canary_idempotency_key": request.idempotency_key,
        }
        if self._profile.provider in {"openai", "openrouter", "fal-queue"}:
            # GPT Image 2.5 rejects input_fidelity, including on image edits.
            # Reference images are still sent unchanged in the multipart files.
            request_data = {
                "model": self._gateway_model, "prompt": request.prompt,
                "size": f"{request.width}x{request.height}", "n": 1,
            }
            if self._profile.provider == "openai":
                request_data.update({"quality": "high", "output_format": "png"})
            elif self._profile.provider == "fal-queue":
                request_data.update({"quality": "high", "output_format": "png"})
                # Custom-provider routing can strip standard Images fields.
                # Preserve dimensions and controls through the same manifest
                # consumed by the FAL handler for other image requests.
                request_data["canary_wire_request"] = json.dumps({
                    "width": request.width,
                    "height": request.height,
                    "controls": [
                        ["quality", "high"],
                        ["output_format", "png"],
                        ["n", 1],
                    ],
                })
            else:
                # LiteLLM 1.83.14 drops named size on custom image edits but
                # forwards aspect_ratio through optional_params to OpenRouter.
                divisor = gcd(request.width, request.height)
                request_data["aspect_ratio"] = f"{request.width // divisor}:{request.height // divisor}"
                # Canary renders public-domain literature whose canonical
                # content can include distress (e.g. The Gift of the Magi).
                # Mirror the Vertex safety-off precedent: request Muse's
                # documented relaxed moderation tier instead of retrying
                # content-management-policy rejections that no other control
                # can clear.
                request_data["moderation"] = "low"
        feature = "complete_page_draw"
        ctx = await begin_image_call(
            config=self._config,
            model=self._gateway_model,
            feature=feature,
            prompt=request.prompt,
            params={
                "model": self._gateway_model,
                "provider_model": request.model,
                "size": f"{request.width}x{request.height}",
                "quality": "high" if self._profile.provider in {"openai", "fal-queue"} else self._config.image_quality,
                "artifact_kind": "complete_page",
            },
            ref_reads=ref_reads,
        )
        headers = ai_client._headers(self._config, ctx.event_id)
        url = f"{ai_client._base_url(self._config)}{endpoint}"
        response = None
        payload = None

        def retain_incomplete_response() -> None:
            # An accepted response is not proof of a settled usable result.
            # Preserve known refusal semantics; retain every other incomplete
            # successful response for explicit reconciliation.
            try:
                refused = isinstance(payload, dict) and ai_client._is_refusal(payload)
            except (AttributeError, TypeError, IndexError):
                refused = False  # Malformed refusal fields are not known refusal.
            if response is not None and response.status_code < 400 and not refused:
                from novel_to_comic.server.credits import retain_ambiguous_job
                retain_ambiguous_job(ai_client.current_ai_request_context().job_id)

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
                source_format = image.format
                if source_format not in {"PNG", "JPEG", "WEBP"}:
                    raise ValueError(
                        "Complete-page output must be PNG, JPEG, or WebP"
                    )
                width, height = image.size
                # Muse does not advertise a supported output-format control,
                # and OpenRouter may therefore return a valid JPEG or WebP.
                # The frozen edition still promises a PNG artifact, so
                # normalize successful raster output locally rather than
                # rejecting a completed, chargeable image submission.
                if source_format != "PNG":
                    image.load()
                    normalized = io.BytesIO()
                    image.save(normalized, format="PNG")
                    image_bytes = normalized.getvalue()
            if (width, height) != (request.width, request.height):
                raise ValueError(
                    "Complete-page output dimensions do not match frozen profile: "
                    f"actual={width}x{height} expected={request.width}x{request.height}"
                )
            latency_ms = int((time.perf_counter() - ctx.started) * 1000)
            usage = ai_client._extract_usage(
                payload,
                ctx.event_id,
                self._gateway_model,
                "image",
                response.headers,
            )
            if usage.cost_usd is None and self._profile.provider != "openai":
                usage = usage.model_copy(
                    update={
                        "cost_usd": float(request.estimated_cost_usd),
                        "cost_source": "capability_profile",
                    }
                )
            response_model = str(payload.get("model") or "")
            actual_provider_model = (
                f"{'vertex_ai' if self._profile.provider == 'vertex-multimodal' else self._profile.provider}/{request.model}"
                if response_model == self._gateway_model
                else response_model or f"{'vertex_ai' if self._profile.provider == 'vertex-multimodal' else self._profile.provider}/{request.model}"
            )
            if self._profile.provider == "openai" and actual_provider_model.removeprefix("openai/") not in {
                request.model, request.model + "-2026-09-08",
            }:
                raise ValueError("OpenAI response model does not match frozen page profile")
            if self._profile.provider == "fal-queue":
                observed = actual_provider_model.removeprefix("fal-queue/")
                if observed not in {
                    request.model,
                    request.model + "/text-to-image",
                    request.model + "/edit",
                }:
                    raise ValueError("FAL response model does not match frozen page profile")
            if self._profile.provider == "openrouter" and actual_provider_model.removeprefix("openrouter/") != request.model:
                raise ValueError("OpenRouter response model does not match frozen page profile")
            usage = usage.model_copy(
                update={
                    "model": self._gateway_model,
                    "provider_model": actual_provider_model,
                    "provider": self._profile.provider,
                }
            )
            response_data = {
                key: value for key, value in payload.items() if key != "data"
            }
            response_data["model"] = actual_provider_model
        except asyncio.CancelledError as exc:
            retain_incomplete_response()
            await finalise_image_cancelled(
                ctx=ctx,
                config=self._config,
                model=self._gateway_model,
                feature=feature,
                error=exc,
                error_response=response,
            )
            raise
        except BaseException as exc:
            retain_incomplete_response()
            await finalise_image_failure(
                ctx=ctx,
                config=self._config,
                model=self._gateway_model,
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
                model_alias=self._gateway_model,
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
                model=self._gateway_model,
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


class OpenAICompletePageAdapter(GoogleVertexCompletePageTransport):
    """Public Image API through the gateway; one accounted submission per page."""

    def __init__(self, config: Config, profile: PageCapabilityProfile) -> None:
        super().__init__(config)
        base = (fal_sunburst_page_capability_profile()
                if profile.provider == "fal-queue"
                else openai_page_capability_profile(profile.model))
        if profile not in (base, _integrated_page_profile(base)):
            raise ValueError("Unsupported complete-page profile")
        self._profile = profile
        self._gateway_model = (
            "image-sunburst" if profile.provider == "fal-queue"
            else "image-" + profile.model.removeprefix("gpt-image-2.5-")
        )

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        return _prepare_complete_page(compiled, self._profile)


class OpenRouterCompletePageAdapter(GoogleVertexCompletePageTransport):
    """Muse Image via the gateway's OpenRouter-compatible Images API."""

    def __init__(self, config: Config, profile: PageCapabilityProfile) -> None:
        super().__init__(config)
        base = muse_page_capability_profile()
        if profile not in (base, _integrated_page_profile(base)):
            raise ValueError("Unsupported OpenRouter complete-page profile")
        self._profile = profile
        self._gateway_model = "image-muse"

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        return _prepare_complete_page(compiled, self._profile)


async def draw_complete_page(
    compiled: CompiledPageGeneration,
    *,
    adapter: CompletePageAdapter,
    artifacts: TargetArtifacts,
    page: ComicPage,
    ocr: "OCRAdapter | None" = None,
    request_revision: int | None = None,
    render_revision: int | None = None,
    parent_render_revision: int | None = None,
    defer_completion: bool = False,
) -> PageGenerationProvenance:
    """Persist and execute exactly one complete-page request."""

    adapter.prepare(compiled)

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
                await _read_back(page=page, render=saved.render, image=image, ocr=ocr, artifacts=artifacts)
            if not defer_completion and calculate_cost_breakdown(saved.usage).source != "unknown_provider_usage":
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
        cost_usd=(
            None if (provider_result.usage.funding == "codex_subscription"
            and provider_result.usage.cost_usd is None)
            or calculate_cost_breakdown(provider_result.usage).source == "unknown_provider_usage"
            else Decimal(str(calculate_cost(provider_result.usage)))
        ),
    )
    provenance = PageGenerationProvenance(
        render=render,
        usage=provider_result.usage,
        provider_request_id=provider_result.provider_request_id,
        response_metadata=provider_result.response_metadata,
    )
    artifacts.persist_generated_page(provenance, provider_result.image_bytes)
    if ocr is not None:
        await _read_back(page=page, render=render, image=provider_result.image_bytes, ocr=ocr, artifacts=artifacts)
    if not defer_completion and calculate_cost_breakdown(provenance.usage).source != "unknown_provider_usage":
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


async def _read_back(*, page, render, image, ocr, artifacts) -> None:
    """Every draw's automatic page read. Best effort: the paid art is already
    saved, so a failed read never fails the page; the page stays unchecked
    and can be read again without redrawing."""
    try:
        await analyze_complete_page(page=page, render=render, image=image, ocr=ocr, artifacts=artifacts)
    except Exception:
        logger.warning("Page %s read-back failed; the drawn page is kept unchecked",
                       page.page_number, exc_info=True)


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
    adapter: CompletePageAdapter,
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
                if artifacts.analysis_path(page.page_number, provenance.render.revision).exists()
                else None)
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
    if not defer_completion and calculate_cost_breakdown(provenance.usage).source != "unknown_provider_usage":
        artifacts.mark_generation_complete(provenance)
    return provenance


def page_draw_execution(
    *, project_dir, compiled, adapter, artifacts, page, ocr=None,
    request_revision=None, render_revision=None, parent_render_revision=None,
    issue=None, on_success=None,
):
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
            actual_provider_model=provenance.usage.provider_model,
            additional_usage=_analysis_usage(artifacts, provenance),
            response_metadata=provenance.response_metadata,
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

    return _work, _settled


def enqueue_complete_page_draw(
    app: FastAPI,
    *,
    project_name: str,
    user_id: str,
    project_id: str | None,
    project_dir: Path,
    config: Config,
    compiled: CompiledPageGeneration,
    adapter: CompletePageAdapter,
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
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    operations = draw_operations(config, ocr=ocr is not None)
    funding = classify_operations(operations)

    estimate = credit_estimate_for_provider_cost(
        estimate_draw_api_cost(config, float(compiled.request.estimated_cost_usd), ocr=ocr is not None, compiled=compiled),
        "draw",
        reserve=True,
        zero_cost_estimate=0,
        funding=funding,
    )

    _work, _settled = page_draw_execution(
        project_dir=project_dir, compiled=compiled, adapter=adapter, artifacts=artifacts,
        page=page, ocr=ocr, request_revision=request_revision, render_revision=render_revision,
        parent_render_revision=parent_render_revision, issue=issue, on_success=on_success,
    )
    from novel_to_comic.server.job_commands import command, save_blob
    descriptor = command("page_draw", project_dir, config,
        request=compiled.request.model_dump(mode="json"),
        references=[save_blob(project_dir, data) for data in compiled.reference_bytes],
        edit_source=save_blob(project_dir, compiled.edit_source_bytes),
        page=page.model_dump(mode="json"), ocr=ocr is not None,
        request_revision=request_revision, render_revision=render_revision,
        parent_render_revision=parent_render_revision,
        issue=issue.model_dump(mode="json") if issue else None,
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
            "issue_ids": list(compiled.request.correction.issue_ids) if compiled.request.correction else [],
        },
        work=_work,
        debit_description=f"Complete page {compiled.request.page_number}",
        reservation_credits=estimate["reserved_credits"] or 0,
        operations=operations,
        on_settled=_settled,
        command=descriptor,
    )
