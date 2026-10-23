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
from typing import TYPE_CHECKING, Literal, Protocol

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
    PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD,
    GPT25_PAGE_ESTIMATED_COST_USD,
    GPT25_REFERENCE_ESTIMATED_COST_USD,
    MUSE_PAGE_ESTIMATED_COST_USD,
    Config,
)
from novel_to_comic.image_models import (
    GATEWAY_IMAGE_FLARE_RUNWARE,
    GATEWAY_IMAGE_NANO_BANANA_21,
    GATEWAY_IMAGE_SUNBURST_RUNWARE,
    runware_first_enabled,
)
from novel_to_comic.image_route_fallback import (
    FAL_SUNBURST_GATEWAY_MODEL,
    OPENAI_SUNBURST_GATEWAY_MODEL,
    RUNWARE_FIRST_PROVIDER,
    SUNBURST_FALLBACK_PROVIDER,
    run_openai_first,
    run_runware_first,
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
    check_render_lineage,
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
from novel_to_comic.lettering.room import framing_notes
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_BLOCK
from novel_to_comic.usage import ApiResult, UsageRecord, calculate_cost, calculate_cost_breakdown

if TYPE_CHECKING:
    from novel_to_comic.page_review import OCRAdapter, PageCorrectionContext


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


_NANO_BANANA_21_PAGE_PROFILE_ID = "nano-banana-2.1-complete-page-1k-hybrid-v1"


def nano_banana_21_page_capability_profile() -> PageCapabilityProfile:
    """Native Vertex 1K portrait profile (2:3 output is 848x1264)."""
    from novel_to_comic.usage import get_pricing_resolver

    pricing, _ = get_pricing_resolver()._pricing_for("gemini-nano-banana-2.1")
    return PageCapabilityProfile(
        id=_NANO_BANANA_21_PAGE_PROFILE_ID, exact_visible_lettering=False,
        provider="vertex-multimodal", model="gemini-nano-banana-2.1",
        max_image_references=14, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=848, output_height=1264, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
        price_per_page_usd=Decimal(str(pricing["estimated_output_cost_per_image"])),
        price_per_reference_usd=Decimal(str(pricing["estimated_input_cost_per_reference"])),
    )


def openai_page_capability_profile(
    model: str, *, quality: Literal["high", "medium"] = "high",
) -> PageCapabilityProfile:
    if model not in {"gpt-image-2.5-sunburst", "gpt-image-2.5-flare"}:
        raise ValueError("Unsupported complete-page OpenAI model")
    if quality not in {"high", "medium"}:
        raise ValueError("Unsupported complete-page OpenAI quality")
    return PageCapabilityProfile(
        id=f"{model}-complete-page-{quality}-hybrid-v1", exact_visible_lettering=False, provider="openai", model=model,
        max_image_references=16, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1024, output_height=1536, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
        price_per_page_usd=Decimal(GPT25_PAGE_ESTIMATED_COST_USD),
        price_per_reference_usd=Decimal(GPT25_REFERENCE_ESTIMATED_COST_USD),
    )


_FAL_SUNBURST_PAGE_PROFILE_ID = "gpt-image-2.5-sunburst-fal-complete-page-medium-hybrid-v1"


def fal_sunburst_page_capability_profile() -> PageCapabilityProfile:
    """Sunburst complete pages at medium quality via fal.ai's queue adapter."""
    return PageCapabilityProfile(
        id=_FAL_SUNBURST_PAGE_PROFILE_ID,
        exact_visible_lettering=False, provider="fal-queue", model="openai/gpt-image-2.5/sunburst",
        max_image_references=16, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1024, output_height=1536, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=1,
    )


_SUNBURST_FALLBACK_PAGE_PROFILE_ID = "gpt-image-2.5-sunburst-openai-fal-complete-page-medium-hybrid-v1"


def sunburst_fallback_page_capability_profile() -> PageCapabilityProfile:
    """Sunburst at medium quality: OpenAI first, one FAL attempt as backup.

    The route order is part of this versioned identity; changing it needs a
    new profile id. Both routes accept the same references, size, and quality.
    """
    return PageCapabilityProfile(
        id=_SUNBURST_FALLBACK_PAGE_PROFILE_ID,
        exact_visible_lettering=False, provider=SUNBURST_FALLBACK_PROVIDER, model="gpt-image-2.5-sunburst",
        max_image_references=16, reference_ordering="ordered",
        editing_modes=("instructed", "region_targeted"),
        output_width=1024, output_height=1536, max_prompt_characters=32_000,
        retry_semantics="bounded_submission", max_attempts=2,
    )


_RUNWARE_FIRST_PAGE_PROFILE_ID = "gpt-image-2.5-sunburst-runware-openai-fal-complete-page-medium-hybrid-v1"


def runware_first_page_capability_profile() -> PageCapabilityProfile:
    """Sunburst at medium quality: Runware first, then the OpenAI-first chain.

    Selected for new work only while ``CANARY_RUNWARE_FIRST_ENABLED`` is set;
    editions created with it stay drawable after the switch is turned off.
    Every route accepts the same references, size, and quality.
    """
    return sunburst_fallback_page_capability_profile().model_copy(update={
        "id": _RUNWARE_FIRST_PAGE_PROFILE_ID, "provider": RUNWARE_FIRST_PROVIDER, "max_attempts": 3,
    })


# Providers whose corrections upload the parent page beside the references.
_EDIT_SOURCE_COUNTS_AS_REFERENCE = frozenset({
    "openai", "openrouter", "fal-queue", SUNBURST_FALLBACK_PROVIDER, RUNWARE_FIRST_PROVIDER,
})


def _edit_source_counts_as_reference(profile: PageCapabilityProfile) -> bool:
    return (
        page_profile_uses_native_dimensions(profile)
        or profile.provider in _EDIT_SOURCE_COUNTS_AS_REFERENCE
        or (profile.provider == "vertex-multimodal" and profile.model == "gemini-nano-banana-2.1")
    )


def page_image_quality(profile_id: str, provider: str) -> str | None:
    """The image quality an edition's profile submits, fixed by its identity."""
    if provider == "vertex-multimodal" and profile_id.removesuffix("-integrated-v1") == _NANO_BANANA_21_PAGE_PROFILE_ID:
        return "low"
    if profile_id.removesuffix("-integrated-v1") in {
        _FAL_SUNBURST_PAGE_PROFILE_ID, _SUNBURST_FALLBACK_PAGE_PROFILE_ID, _RUNWARE_FIRST_PAGE_PROFILE_ID,
    }:
        return "medium"
    if provider == "openai" and profile_id.removesuffix("-integrated-v1") in {
        f"{model}-complete-page-medium-hybrid-v1"
        for model in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare")
    }:
        return "medium"
    # Retained direct-OpenAI and FAL editions were drawn at high quality.
    if provider in {"openai", "fal-queue"}:
        return "high"
    return None


def estimate_page_request_cost_usd(
    compiled: CompiledPageGeneration, *, basis: Literal["reservation", "expected"] = "reservation",
) -> float:
    """Current configured price of one compiled page request.

    Pricing is a quote from the pricing overrides, separate from the frozen
    edition and request identity. Corrections also send the parent page.
    """
    from novel_to_comic.usage import estimate_image_cost

    request = compiled.request
    return estimate_image_cost(
        request.model, 1, quality=page_image_quality(request.profile_id, request.provider),
        ref_count=len(request.references) + int(compiled.edit_source_bytes is not None),
        prompt_text=request.prompt,
        width=request.output_width, height=request.output_height, basis=basis,
    )


def production_page_capability_profile() -> PageCapabilityProfile:
    """Return the default complete-page profile for new API work."""
    if runware_first_enabled():
        return runware_first_page_capability_profile()
    return sunburst_fallback_page_capability_profile()


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

    if profile == nano_banana_21_page_capability_profile() or profile == current_page_capability_profile() or any(
        profile == openai_page_capability_profile(model, quality=quality)
        for model in ("gpt-image-2.5-sunburst", "gpt-image-2.5-flare")
        for quality in ("high", "medium")
    ) or profile in (fal_sunburst_page_capability_profile(), _integrated_page_profile(fal_sunburst_page_capability_profile()),
                     sunburst_fallback_page_capability_profile(),
                     _integrated_page_profile(sunburst_fallback_page_capability_profile()),
                     runware_first_page_capability_profile(),
                     _integrated_page_profile(runware_first_page_capability_profile())) or profile == muse_page_capability_profile():
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
    if selected == GATEWAY_IMAGE_NANO_BANANA_21:
        return nano_banana_21_page_capability_profile()
    if selected == "image-sunburst":
        return production_page_capability_profile()
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


def spendable_page_profiles(config: Config | None = None) -> tuple[PageCapabilityProfile, ...]:
    """Profiles this project may still spend on: the current one for new
    editions, plus the Sunburst profiles its existing editions were bound to
    (FAL, and whichever multi-route identity ``CANARY_RUNWARE_FIRST_ENABLED``
    does not select now). Existing editions never change profile; they keep
    drawing on their route.
    """
    current = current_page_capability_profile(config)
    if getattr(config, "draw_model", COMPLETE_PAGE_GATEWAY_MODEL) != "image-sunburst":
        return (current,)
    retained = [fal_sunburst_page_capability_profile()] + [
        profile for profile in (sunburst_fallback_page_capability_profile(), runware_first_page_capability_profile())
        if profile.id != current.id.removesuffix("-integrated-v1")
    ]
    return (current, *(_integrated_page_profile(profile) if current.exact_visible_lettering else profile
                       for profile in retained))


def initial_page_profile(project_dir, config: Config | None = None) -> PageCapabilityProfile:
    """The profile a part's first edition binds to.

    Parts of a series keep one look: a new part inherits the previous part's
    profile while this project can still spend on it, and otherwise uses the
    current profile. Existing editions never change profile either way.
    """
    from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
    from novel_to_comic.workspace import part_id, part_ordinal, part_workspace, series_root, workspace_part_id

    spendable = spendable_page_profiles(config)
    identifier = workspace_part_id(project_dir)
    if identifier is not None:
        root = series_root(project_dir)
        for number in range(part_ordinal(identifier) - 1, 0, -1):
            try:
                edition = TargetArtifacts(part_workspace(root, part_id(number))).read_book_edition()
            except (ArtifactMissing, ArtifactInvalid):
                continue
            if edition.capability_profile in spendable:
                return edition.capability_profile
            break
    return current_page_capability_profile(config)


def request_page_profile(config: Config, request: FrozenPageGenerationRequest) -> PageCapabilityProfile:
    """The spendable profile a frozen request was compiled against."""
    for profile in spendable_page_profiles(config):
        if profile.id == request.profile_id and profile.content_sha256 == request.profile_sha256:
            return profile
    raise ValueError(
        "This page request belongs to a page profile this project can no longer draw with; "
        "prepare a new draw."
    )


def complete_page_adapter(
    config: Config,
    profile: PageCapabilityProfile | None = None,
    *, request: FrozenPageGenerationRequest | None = None,
) -> CompletePageAdapter:
    """The adapter for an edition's profile (or a frozen request's), never
    re-derived from mutable settings when either is known."""
    if request is not None:
        profile = request_page_profile(config, request)
    profile = profile or current_page_capability_profile(config)
    if profile.provider == RUNWARE_FIRST_PROVIDER:
        return RunwareFirstPageAdapter(config, profile)
    if profile.provider == SUNBURST_FALLBACK_PROVIDER:
        return SunburstFallbackPageAdapter(config, profile)
    if profile.provider in {"fal-queue", "openai"}:
        return OpenAICompletePageAdapter(config, profile)
    if profile.provider == "openrouter":
        return OpenRouterCompletePageAdapter(config, profile)
    if page_profile_uses_native_dimensions(profile):
        from novel_to_comic.codex_complete_page import CodexCompletePageAdapter

        return CodexCompletePageAdapter(config)
    return VertexCompletePageAdapter(GoogleVertexCompletePageTransport(config, profile), profile)



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
    """Select a supported profile, advancing the edition when it changes."""
    if existing is not None and edition_id != existing.id:
        raise ValueError("the identity is fixed for the edition")
    if not _supported_page_profile(profile) and not (
        existing is not None and profile == existing.capability_profile and retained_baked_profile(profile)
    ):
        raise ValueError("provider/model does not satisfy the current complete-page capability profile")
    changed = existing is not None and profile != existing.capability_profile
    return BookEdition(
        revision=existing.revision + int(changed) if existing is not None else 1,
        id=edition_id,
        capability_profile=profile,
    )


def ensure_current_page_edition(
    artifacts: TargetArtifacts,
    edition: BookEdition,
    config: Config | None = None,
    *, allow_retained_review: bool = False, persist: bool = True,
) -> BookEdition:
    """Use the configured profile for new work, retaining old request provenance.

    Estimates select the same revision without persisting it. Existing render
    bytes and frozen requests remain unchanged when the active profile advances.
    """
    if allow_retained_review:
        return edition
    if edition.capability_profile in spendable_page_profiles(config):
        return edition
    profile = current_page_capability_profile(config)
    if profile.exact_visible_lettering != edition.capability_profile.exact_visible_lettering:
        raise ValueError("This edition uses a different page profile lettering mode; create a new project to change lettering modes.")
    selected = select_book_edition(edition_id=edition.id, profile=profile, existing=edition)
    if persist:
        artifacts.replace_book_edition(selected)
    return selected


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


def _edit_image_numbers(payload: dict) -> dict[str, int]:
    """One-based upload positions: Image 1 is the parent page on every transport.

    Images APIs do not interleave Vertex's textual asset labels, so authorities
    are bound to their actual upload order, which follows asset order.
    """
    handles = dict.fromkeys(ref["image"] for ref in payload["approved_page_references"])
    return {
        handle: index
        for index, handle in enumerate(sorted(handles, key=lambda handle: (len(handle), handle)), start=2)
    }


def _percent_box(points: list[tuple[float, float]]) -> str:
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    return (f"{round(min(xs) * 100)}-{round(max(xs) * 100)}% across, "
            f"{round(min(ys) * 100)}-{round(max(ys) * 100)}% down the page")


def _edit_prompt(
    payload: dict,
    page: ComicPage,
    correction_context: "PageCorrectionContext | None",
    depiction: str,
    exact_visible_lettering: bool,
) -> str:
    """A short, priority-ordered edit of Image 1.

    The author's change leads and is restated last; everything after it is a
    constraint, not a page specification. Image 1 already carries the page's
    composition, style and story, so the original generation brief, story
    spine and style essay are omitted from the provider prompt (they remain in
    provenance). Approved anchors and guards stay verbatim.
    """
    edit = payload["complete_page_correction"]
    numbers = _edit_image_numbers(payload)
    lines = ["EDIT IMAGE 1. Image 1 is the current comic page. Return the complete page with only the "
             "requested changes below applied.", "",
             "REQUESTED CHANGES (top priority; each must be clearly visible in the output - keeping "
             "Image 1's version of these details does not count):"]
    summaries = []
    for index, change in enumerate(edit["changes"], 1):
        instruction = change["instruction"].strip()
        # The whole request: a seeded issue line may be followed by the
        # author's own wording, which the final check must not drop.
        summaries.append(" ".join(instruction.split()))
        lines.append(f"{index}. {instruction}")
        for mark in change.get("annotations", ()):
            points = [(point["x"], point["y"]) for point in mark["points"]]
            where = f"   Marked {mark['kind']}: {_percent_box(points)}"
            if mark["kind"] == "arrow" and len(points) >= 2:
                (x0, y0), (x1, y1) = points[0], points[-1]
                where += f" (from {round(x0 * 100)}%,{round(y0 * 100)}% to {round(x1 * 100)}%,{round(y1 * 100)}%)"
            details = " - ".join(part for part in (mark.get("label"), mark.get("note")) if part)
            lines.append(where + (f": {details}" if details else ""))
    for region in edit["parent_coordinate_regions"]:
        lines.append(f"   Edit region: {_percent_box([(point['x'], point['y']) for point in region['polygon']])}")
    if edit["author_note"]:
        lines.append(f"Author note: {edit['author_note']}")
    lines += [
        "These changes override Image 1 and any original pose, gaze, expression, gesture or staging they "
        "conflict with. When a change involves a pose, contact point, direction or object, redraw that "
        "pose or object completely so the result is correct, in every panel the change affects.",
        "",
        "KEEP EVERYTHING ELSE EXACTLY AS IN IMAGE 1: panels, borders, framing, composition, characters, "
        "colors, lighting, line work and lettering outside the requested changes. Do not redraw, restyle, "
        "sharpen, re-texture or add detail to untouched areas; match Image 1's existing rendering where "
        "the edit meets them.",
        RENDERING_FIDELITY_BLOCK,
        "",
        "CONSTRAINTS (keep these while editing):",
        "- Images 2 onward are the approved reference sheets listed below. Reference "
        "sheets give identity, costume and design only. Never copy their pose, facial expression, "
        "background or layout, and never draw them as extra panels.",
    ]
    known = {"image", "subject", "appearance", "identity", "visual_anchor", "continuity_guard", "art_direction"}
    for reference in payload["approved_page_references"]:
        detail = (f"- Image {numbers[reference['image']]} ({reference['image']}) = "
                  f"{reference['appearance']} ({reference['subject']})")
        binding = {key: value for key, value in reference.items() if key not in known}
        if binding:
            detail += f"; sheet binding {json.dumps(binding, ensure_ascii=False, separators=(',', ':'))}"
        if reference.get("identity"):
            detail += f"; {reference['identity']}"
        detail += f". Visual anchor: {reference['visual_anchor']}"
        if reference.get("continuity_guard"):
            detail += f" Continuity guard: {reference['continuity_guard']}"
        if reference.get("art_direction"):
            detail += f" Approved art direction: {reference['art_direction']}"
        lines.append(detail)
    for panel in payload["canonical_comic_page"]["content"]:
        cast = []
        for subject in panel["visible_subjects"]:
            images = [f"Image {numbers[ref['image']]}" for ref in subject["references"] if ref["image"] in numbers]
            labels = [ref["appearance"] for ref in subject["references"]]
            written = subject.get("written_identity")
            if written:
                labels.append(written["appearance"])
            cast.append(f"{' / '.join(dict.fromkeys(labels)) or subject['subject']} ({subject['subject']}"
                        + (f", {', '.join(images)}" if images else "") + ")")
        if cast:
            lines.append(f"- Panel {panel['order']} shows: {'; '.join(cast)}.")
        for subject in panel["visible_subjects"]:
            written = subject.get("written_identity")
            if written:
                detail = f"- {written['appearance']} ({subject['subject']}, no reference image)"
                if written.get("identity"):
                    detail += f"; {written['identity']}"
                detail += f". Visual anchor: {written['visual_anchor']}"
                if written.get("continuity_guard"):
                    detail += f" Continuity guard: {written['continuity_guard']}"
                lines.append(detail)
        if panel["pinned_geometry"]:
            lines.append(f"- Panel {panel['order']} author-pinned geometry: "
                         f"{json.dumps(panel['pinned_geometry'], ensure_ascii=False, separators=(',', ':'))}")
    if edit["retained_render_intent"]:
        lines.append("- Earlier author requests on this page still apply unless a requested change above says otherwise:")
        lines += [f"  * {instruction}" for instruction in edit["retained_render_intent"]]
    if depiction == "less_graphic":
        lines.append("- Use framing, shadow, reaction or aftermath for graphic details; preserve identity and story.")
    if exact_visible_lettering:
        lettering = payload["exact_lettering"]["panels"]
        if any(panel["lettering"] for panel in lettering):
            # Requested typesetting fixes (a tail, a typo) are allowed; the
            # canonical list below stays the authority for wording and panel.
            lines.append("- Lettering: apart from the requested changes, keep Image 1's lettering and typesetting. "
                         "Each string must appear exactly once, in its assigned panel, with this exact wording:")
            lines += [
                f"  * Panel {panel['panel']} {item['kind']}"
                + (f" ({item['speaker']})" if item.get("speaker") else "")
                + f": {json.dumps(item['text'], ensure_ascii=False)}"
                for panel in lettering for item in panel["lettering"]
            ]
        else:
            lines.append("- This page is unlettered: add no text, captions, balloons or SFX.")
    else:
        lines.append("- No comic lettering: Canary adds dialogue, captions and SFX later. Add no balloons, caption "
                     "boxes, SFX, words, pseudo-writing or blank lettering areas; existing in-world signage may stay.")
    if correction_context is not None:
        story = list(correction_context.beat_summaries)
        selected = set(correction_context.selected_source_unit_ids)
        passages = [text for unit_id, text in zip(correction_context.source_unit_ids,
                                                  correction_context.source_texts, strict=True)
                    if unit_id in selected]
        if story or passages:
            lines += ["", "STORY CONTEXT (reference only; never extra panels, text or edits):"]
            lines += [f"- {beat}" for beat in story]
            lines += [f"- Source passage chosen by the author: {text}" for text in passages]
    lines += ["", "BEFORE RETURNING, CHECK: the output is the complete page and shows "
              + " ".join(f"({index}) {summary}" for index, summary in enumerate(summaries, 1))
              + " Everything else matches Image 1."]
    return "\n".join(lines)


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
    text_authorities: tuple[ApprovedVisualReference, ...] = (),
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
        def written_identity(entity_id):
            authority = next((ref for ref in text_authorities if ref.entity_id == entity_id
                              and ref.appearance_state_id == content.appearance_states.get(entity_id)), None)
            return ({"written_identity": {"appearance": authority.label,
                     **({"identity": authority.identity} if authority.identity else {}),
                     "visual_anchor": authority.visual_anchor, "continuity_guard": authority.continuity_guard}}
                    if authority is not None else {})
        return [
            {
                "subject": handles[entity_id],
                **acting(content, entity_id),
                **written_identity(entity_id),
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
            "advance asset ordering. "
            "Do not borrow rooms, background props, staging or story events from "
            "character/prop reference backgrounds. The panel setting controls the environment. "
            "Use each subject asset only for its assigned subject and state; "
            "preserve hairstyle, age, recognizable facial features, clothing design and recurring "
            "object features shown by that authority unless the assigned state explicitly changes "
            "them. "
            "A subject's identity line states canonical gender, age and any unusual stature: "
            "keep that gender and age legible in every panel, and keep a stated stature at its "
            "true scale beside other figures, furniture and doorways in every panel, seated or "
            "standing; never normalize it to ordinary height. A plain scale silhouette on a "
            "reference sheet is a measuring guide, never a figure to draw. "
            "Character references establish identity and appearance, not a fixed pose, facing "
            "direction, gaze, expression or camera angle. An appearance-state asset shows how "
            "its subject looks in that state (wounds, blood, clothing, hair), never the "
            "situation: take posture, support such as lying, hanging or being pinned, and the "
            "placement and orientation of anything touching the body from the panel's visual "
            "intent, acting and the state's continuity guard. Re-stage each character for the panel's "
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
                **({"identity": reference.identity} if reference.identity else {}),
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
            # provenance; replaying it duplicates current authorities.
            "retained_render_intent": [instruction for instruction in correction.retained_instructions
                                       if not instruction.startswith("PAGE CANVAS: ")],
            "parent_coordinate_regions": [
                {"polygon": [{"x": x, "y": y} for x, y in region.polygon]}
                for region in correction.resolved_regions
            ],
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
    if text_authorities:
        payload["reference_scope"] += (
            " Incidental participants and scene objects use written_identity instead of a "
            "dedicated image; draw a scene object identically in every panel and page that shows it. "
            "Preserve each supplied visual_anchor and continuity_guard verbatim as appearance "
            "authority; take acting and staging from the panel. During corrections preserve "
            "their existing identity in the parent artwork unless the author changes it."
        )
    if not exact_visible_lettering and page.lettering_reservations is None:
        raise ValueError("This Plan predates lettering reservations. Rerun Plan before drawing a hybrid edition.")
    if correction is not None:
        edit = payload["complete_page_correction"]
        current = {change["instruction"] for change in edit["changes"]} | {edit["author_note"]}
        edit["retained_render_intent"] = list(dict.fromkeys(
            instruction for instruction in edit["retained_render_intent"] if instruction not in current
        ))
        if not exact_visible_lettering:
            # Publishable phrases stay out of hybrid base-art edits.
            return _edit_prompt(_without_copy(payload, page), page,
                                _without_context_copy(correction_context, page), depiction, False)
        return _edit_prompt(payload, page, correction_context, depiction, True)
    if not exact_visible_lettering:
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
        "to realize the planned layout proportions, grouping and rhythm within the selected style; "
        "do not add unplanned overlaps, insets or extra panels. Canonical continuity describes established "
        "start/end staging, not a request to repeat completed actions.\n"
        + lettering_direction
        + depiction_direction
        + json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        + "\nOUTPUT: one full page image; exact copy only; assigned identities and states; "
        "no visible metadata, asset handles, subject labels or reference callouts."
    )



def _publishable_copy(page: ComicPage) -> list[str]:
    return sorted({item.text for content in page.content for item in content.lettering}, key=len, reverse=True)


def _without_copy(value, page: ComicPage, field: str = ""):
    """Remove quoted publishable phrases from editorial/context prose.

    Identifiers and verbatim reference authorities are untouched. Short
    utterances can also be ordinary English ("I", "No"); their occurrence in
    visual prose is not a lettering payload.
    """
    if field in {"visual_anchor", "continuity_guard"}:
        return value
    if isinstance(value, str):
        for text in _publishable_copy(page):
            if text and len(text.strip()) >= 12:
                value = value.replace(text, "[story copy omitted]")
        return value
    if isinstance(value, list):
        return [_without_copy(item, page, field) for item in value]
    if isinstance(value, dict):
        return {key: _without_copy(item, page, key) for key, item in value.items()}
    return value


def _without_context_copy(context: "PageCorrectionContext | None", page: ComicPage):
    if context is None:
        return None
    return context.model_copy(update={
        "beat_summaries": tuple(_without_copy(list(context.beat_summaries), page)),
        "source_texts": tuple(_without_copy(list(context.source_texts), page)),
    })


def _hybrid_prompt(payload: dict, page: ComicPage, depiction: str) -> str:
    # Canonical text fields are absent altogether from hybrid generation.
    payload = _without_copy(payload, page)
    policy = (
"Render exactly one COMPLETE COMIC PAGE of base artwork, never per-panel assets.\n"
        "LETTERING POLICY: Final dialogue, thoughts, narration, captions and sound effects are added "
        "after illustration by Canary. Draw NO speech or thought balloons, caption/narration boxes, "
        "SFX glyphs, subtitles, words, placeholder text, lorem ipsum or pseudo-writing for these elements. "
        "Draw continuous scene artwork throughout every panel. Never draw blank boxes, empty balloons, "
        "parchment patches, placeholder areas or tail corridors, even if layout notes or reference "
        "images suggest them. "
        "Legitimate in-world signage is distinct; never substitute it for publishable copy.\n"
        "AUTHORITY: preserve approved subject/state references, physical anchors and continuity guards "
        "verbatim in meaning, current staging, selected art direction, page framing and author pins. "
        "Realize the planned panel proportions, grouping and reading order within the selected style; "
        "do not add unplanned overlaps, insets or extra panels. Compose each scene naturally within its panel. "
        "Subject and location assets own identity, state, architecture and material identity "
        "and were drawn in the selected style; they do not prescribe an additional "
        "surface-texture layer. "
        "Preserve authored markings and deliberate "
        "medium texture, but do not transfer incidental paper stains or mottling onto skin, "
        "clothing, sky and other unrelated materials. Reconstruct new surfaces with coherent "
        "tonal areas and material-specific marks.\n"
    )
    if depiction == "less_graphic":
        policy += "Use framing, shadow, reaction or aftermath for graphic details; preserve identity, story and references.\n"
    if notes := framing_notes(page):
        # Lettering lands on the finished art: leave it scene to sit on, not gaps.
        policy += "FRAMING (continuous scene artwork, never empty areas):\n" + "".join(
            f"- {note}\n" for note in notes
        )
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
    text_authorities = tuple(authority for authority in authorities if not authority.requires_image)
    authorities = tuple(authority for authority in authorities if authority.requires_image)
    max_references = selected_edition.capability_profile.max_image_references
    if correction is not None and _edit_source_counts_as_reference(selected_edition.capability_profile):
        max_references -= 1  # The parent is an input image, never an authority replacement.
    if max_references < 0:
        raise ValueError("This edition has no image capacity for the edit parent")
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
                identity=authority.identity,
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
    profile = selected_edition.capability_profile
    prompt_context = correction_context
    if correction is not None and correction_context is not None:
        # Bookwide history belongs in provenance, not every image edit.
        # Always restrict provider grounding to the page and nearby beats;
        # a small edit must not replay remote staging just because it fits
        # below the model's character limit. Keep explicitly selected prose.
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
        text_authorities=text_authorities,
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
        written_identities=text_authorities,
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


def estimate_draw_api_cost(
    config: Config, compiled: CompiledPageGeneration, *, checks: bool = True,
) -> float:
    """Include only the API portions of a page render and its automatic checks."""
    from novel_to_comic.codex_dev import route_for

    total = 0.0 if route_for("complete_page", config.draw_model) else estimate_page_request_cost_usd(compiled)
    if checks and route_for("text", config.effective_page_ocr_model()) is None:
        total += float(PAGE_OCR_ESTIMATED_COST_USD)
    if checks and route_for("text", config.effective_visual_review_model()) is None:
        total += float(PAGE_VISUAL_REVIEW_ESTIMATED_COST_USD)
    return total


def correction_credit_estimate(compiled: CompiledPageGeneration, *, config: Config, reserve: bool):
    """Credit estimate for one compiled artwork correction."""
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.server.codex_admission import draw_operations

    funding = classify_operations(draw_operations(config))

    return credit_estimate_for_provider_cost(
        estimate_draw_api_cost(config, compiled),
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
    if request.correction is not None and _edit_source_counts_as_reference(profile):
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

    def __init__(self, config: Config, profile: PageCapabilityProfile | None = None) -> None:
        self._config = config
        self._profile = profile or current_page_capability_profile(config)
        self._gateway_model = (GATEWAY_IMAGE_NANO_BANANA_21 if self._profile.model == "gemini-nano-banana-2.1"
                               else COMPLETE_PAGE_GATEWAY_MODEL)
        # The provider and upstream model this transport submits to. A
        # single-route profile's route is the profile itself.
        self._route_provider = self._profile.provider
        self._provider_model: str | None = None

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
            with_request_estimate,
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
        if self._route_provider in {"openai", "openrouter", "fal-queue", "runware"}:
            # GPT Image 2.5 rejects input_fidelity, including on image edits.
            # Reference images are still sent unchanged in the multipart files.
            request_data = {
                "model": self._gateway_model, "prompt": request.prompt,
                "size": f"{request.width}x{request.height}", "n": 1,
            }
            quality = page_image_quality(self._profile.id, self._profile.provider)
            if self._route_provider in {"openai", "fal-queue", "runware"}:
                request_data.update({"quality": quality, "output_format": "png"})
                # Both routes run through custom gateway handlers, which lose
                # standard Images fields. Preserve dimensions and controls
                # through the manifest those handlers consume.
                request_data["canary_wire_request"] = json.dumps({
                    "width": request.width,
                    "height": request.height,
                    "controls": [
                        ["quality", quality],
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
                "quality": page_image_quality(self._profile.id, self._profile.provider) or self._config.image_quality,
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
            from novel_to_comic.ai.image_previews import post_image_request

            if files:
                response = await post_image_request(
                    url,
                    headers=headers,
                    data=request_data,
                    files=files,
                    target=f"page:{json.loads(request.frozen_request_json)['page_number']}",
                )
            else:
                response = await post_image_request(
                    url,
                    headers=headers,
                    json=request_data,
                    target=f"page:{json.loads(request.frozen_request_json)['page_number']}",
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
            usage = with_request_estimate(usage, ctx)
            response_model = str(payload.get("model") or "")
            route_model = self._provider_model or request.model
            route_prefix = "vertex_ai" if self._route_provider == "vertex-multimodal" else self._route_provider
            actual_provider_model = (
                f"{route_prefix}/{route_model}"
                if response_model == self._gateway_model
                else response_model or f"{route_prefix}/{route_model}"
            )
            if self._route_provider == "openai" and actual_provider_model.removeprefix("openai/") not in {
                route_model, route_model + "-2026-09-08",
            }:
                raise ValueError("OpenAI response model does not match frozen page profile")
            if self._route_provider == "fal-queue":
                observed = actual_provider_model.removeprefix("fal-queue/")
                if observed not in {
                    route_model,
                    route_model + "/text-to-image",
                    route_model + "/edit",
                }:
                    raise ValueError("FAL response model does not match frozen page profile")
            if self._route_provider == "runware" and actual_provider_model.removeprefix("runware/") != route_model:
                raise ValueError("Runware response model does not match frozen page profile")
            if self._route_provider == "openrouter" and actual_provider_model.removeprefix("openrouter/") != route_model:
                raise ValueError("OpenRouter response model does not match frozen page profile")
            usage = usage.model_copy(
                update={
                    "model": self._gateway_model,
                    "provider_model": actual_provider_model,
                    "provider": self._route_provider,
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
            # Lets a fallback coordinator name the usage event it absorbs;
            # per exception, so parallel pages sharing an adapter never mix.
            if not hasattr(exc, "canary_usage_event_id"):
                try:
                    exc.canary_usage_event_id = ctx.event_id  # type: ignore[attr-defined]
                except AttributeError:
                    pass
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
                expected_cost_usd=ctx.settlement_estimate_usd,


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
            provider_request_id=payload.get("provider_request_id") or payload.get("id"),
            actual_provider_model=actual_provider_model,
            usage=usage,
        )


class OpenAICompletePageAdapter(GoogleVertexCompletePageTransport):
    """Public Image API through the gateway; one accounted submission per page."""

    def __init__(self, config: Config, profile: PageCapabilityProfile) -> None:
        super().__init__(config, profile)
        base = (fal_sunburst_page_capability_profile()
                if profile.provider == "fal-queue"
                else openai_page_capability_profile(
                    profile.model, quality=page_image_quality(profile.id, profile.provider),
                ))
        if profile not in (base, _integrated_page_profile(base)):
            raise ValueError("Unsupported complete-page profile")
        self._gateway_model = (
            "image-sunburst" if profile.provider == "fal-queue"
            else OPENAI_SUNBURST_GATEWAY_MODEL if profile.model == "gpt-image-2.5-sunburst"
            else "image-" + profile.model.removeprefix("gpt-image-2.5-")
        )

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        return _prepare_complete_page(compiled, self._profile)




class _PageRouteTransport(GoogleVertexCompletePageTransport):
    """One route of a multi-route profile: the profile's frozen request, sent
    to a specific provider deployment."""

    def __init__(self, config: Config, profile: PageCapabilityProfile, *,
                 provider: str, gateway_model: str, provider_model: str) -> None:
        super().__init__(config, profile)
        self._route_provider = provider
        self._gateway_model = gateway_model
        self._provider_model = provider_model


def sunburst_openai_page_transport(config: Config, profile: PageCapabilityProfile) -> CompletePageTransport:
    """The OpenAI Sunburst route alone, with no fallback."""
    return _PageRouteTransport(
        config, profile, provider="openai",
        gateway_model=OPENAI_SUNBURST_GATEWAY_MODEL, provider_model="gpt-image-2.5-sunburst",
    )


def sunburst_fal_page_transport(config: Config, profile: PageCapabilityProfile) -> CompletePageTransport:
    """The FAL Sunburst route alone, with no fallback."""
    return _PageRouteTransport(
        config, profile, provider="fal-queue",
        gateway_model=FAL_SUNBURST_GATEWAY_MODEL, provider_model="openai/gpt-image-2.5/sunburst",
    )


def runware_page_transport(config: Config, profile: PageCapabilityProfile) -> CompletePageTransport:
    """The profile's GPT Image 2.5 model through Runware alone, with no fallback."""
    gateway_models = {
        "gpt-image-2.5-sunburst": GATEWAY_IMAGE_SUNBURST_RUNWARE,
        "gpt-image-2.5-flare": GATEWAY_IMAGE_FLARE_RUNWARE,
    }
    if profile.model not in gateway_models:
        raise ValueError(f"Runware has no route for {profile.model}")
    return _PageRouteTransport(
        config, profile, provider="runware",
        gateway_model=gateway_models[profile.model], provider_model=profile.model,
    )


def prepare_frozen_page_request(
    request: FrozenPageGenerationRequest,
    reference_bytes: tuple[bytes, ...],
    profile: PageCapabilityProfile,
) -> PreparedCompletePageRequest:
    """Prepare an already-frozen initial-generation request for submission."""
    return _prepare_complete_page(CompiledPageGeneration(request, reference_bytes, None), profile)


def _with_route(result: CompletePageProviderResult, route: str, fallback: dict | None = None) -> CompletePageProviderResult:
    metadata: dict[str, object] = {**(result.response_metadata or {}), "route": route}
    if fallback is not None:
        metadata["fallback"] = fallback
    return result.model_copy(update={"response_metadata": metadata})


class SunburstFallbackPageAdapter:
    """OpenAI Sunburst first; one FAL attempt when OpenAI fails for availability.

    An OpenAI attempt with an unknown outcome still falls back once: its image
    can never arrive later, so no duplicate page can be published. Canary
    absorbs that attempt's possible charge — its call guarantee is released and
    the job hold is not retained for it. The user's credits settle only the
    attempt that produced the page. Everything else keeps today's behaviour.
    """

    _base = staticmethod(sunburst_fallback_page_capability_profile)

    def __init__(self, config: Config, profile: PageCapabilityProfile) -> None:
        base = self._base()
        if profile not in (base, _integrated_page_profile(base)):
            raise ValueError("Unsupported Sunburst fallback page profile")
        self._config = config
        self._profile = profile
        self._primary = sunburst_openai_page_transport(config, profile)
        self._backup = sunburst_fal_page_transport(config, profile)

    def prepare(self, compiled: CompiledPageGeneration) -> PreparedCompletePageRequest:
        return _prepare_complete_page(compiled, self._profile)

    async def generate(self, prepared: PreparedCompletePageRequest) -> CompletePageProviderResult:
        _validate_prepared_page(prepared, self._profile)
        return _with_route(*await self._openai_first(prepared))

    def _openai_first(self, prepared: PreparedCompletePageRequest):
        return run_openai_first(
            primary=lambda: self._primary.generate(prepared),
            backup=lambda: self._backup.generate(prepared),
            surface="draw", request_key=prepared.request_sha256,
            estimate_openai_usd=lambda: self._openai_attempt_estimate_usd(prepared),
        )

    def _openai_attempt_estimate_usd(self, prepared: PreparedCompletePageRequest) -> float:
        from novel_to_comic.usage import estimate_image_cost

        return estimate_image_cost(
            OPENAI_SUNBURST_GATEWAY_MODEL, 1,
            quality=page_image_quality(self._profile.id, self._profile.provider),
            ref_count=len(prepared.references) + int(prepared.edit_source_bytes is not None),
            prompt_text=prepared.prompt, width=prepared.width, height=prepared.height, basis="expected",
        )


class RunwareFirstPageAdapter(SunburstFallbackPageAdapter):
    """Runware Sunburst first; the OpenAI-first chain only when Runware
    definitely did not run the page (``run_runware_first``). Runware sends no
    partial previews."""

    _base = staticmethod(runware_first_page_capability_profile)

    def __init__(self, config: Config, profile: PageCapabilityProfile) -> None:
        super().__init__(config, profile)
        self._runware = runware_page_transport(config, profile)

    async def generate(self, prepared: PreparedCompletePageRequest) -> CompletePageProviderResult:
        _validate_prepared_page(prepared, self._profile)
        return _with_route(*await run_runware_first(
            primary=lambda: self._runware.generate(prepared),
            backup=lambda: self._openai_first(prepared),
            surface="draw", request_key=prepared.request_sha256,
        ))


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
    await asyncio.to_thread(artifacts.recover_generated_pages, page.page_number)
    for revision in reversed(artifacts.provenance_revisions(page.page_number)):
        saved = artifacts.read_provenance(page.page_number, revision)
        if (saved.render.request_sha256 == compiled.request.request_sha256
                and (render_revision is None or saved.render.revision == render_revision)):
            image = artifacts.read_render(page.page_number, saved.render.revision)
            if hashlib.sha256(image).hexdigest() != saved.render.image_sha256:
                raise ValueError("saved paid render bytes do not match provenance")
            if ocr is not None:
                await _read_back(page=page, render=saved.render, image=image, ocr=ocr, artifacts=artifacts)
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
    check_render_lineage(render_revision, parent_render_revision)
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
    from novel_to_comic.server.telemetry import current_ai_trace_id

    provenance = PageGenerationProvenance(
        render=render,
        usage=provider_result.usage,
        provider_request_id=provider_result.provider_request_id,
        response_metadata=provider_result.response_metadata,
        ai_trace_id=current_ai_trace_id(),
    )
    await asyncio.to_thread(artifacts.persist_generated_page, provenance, provider_result.image_bytes)
    if ocr is not None:
        await _read_back(page=page, render=render, image=provider_result.image_bytes, ocr=ocr, artifacts=artifacts)
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
    saved, so a failed read never fails the page. A read (not an image) is
    retried once; after that the page stays unchecked and can be read again
    without redrawing."""
    for attempt in (1, 2):
        try:
            await analyze_complete_page(page=page, render=render, image=image, ocr=ocr, artifacts=artifacts)
            return
        except Exception:
            logger.warning("Page %s read-back attempt %d failed%s", page.page_number, attempt,
                           "; retrying once" if attempt == 1 else "; the drawn page is kept unchecked",
                           exc_info=True)


async def analyze_complete_page(
    *,
    page: ComicPage,
    render: PageRenderRevision,
    image: bytes,
    ocr: "OCRAdapter",
    artifacts: TargetArtifacts,
    retry_crop_ocr: bool = False,
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
        config=getattr(ocr, "config", None),
        retry_crop_ocr=retry_crop_ocr,
    )
    await asyncio.to_thread(record_analysis_issues, artifacts, analyzed.analysis)
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

    await asyncio.to_thread(ensure_correction_issues, artifacts, correction=correction)

    provenance = await draw_complete_page(
        compiled,
        adapter=adapter,
        artifacts=artifacts,
        page=page,
        ocr=ocr,
        request_revision=request_revision,
        render_revision=render_revision,
        parent_render_revision=correction.parent_render_revision,
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
        await asyncio.to_thread(resolve_page_issue,
            artifacts, issue_id=corrected.id, page_number=page.page_number,
            resolution_revision=provenance.render.revision, verified=verified,
        )
    return provenance


async def _review_back(*, review, page, render, artifacts) -> tuple[UsageRecord, ...]:
    """Every draw's automatic visual review. Best effort, like the read: the
    paid art is kept and the page can be reviewed later without redrawing."""
    try:
        result = await review(render, artifacts.read_render(page.page_number, render.revision))
    except Exception:
        logger.warning("Page %s visual review failed; the drawn page is kept unreviewed",
                       page.page_number, exc_info=True)
        return ()
    return () if result.value.usage is None else (result.value.usage,)


def page_draw_execution(
    *, project_dir, compiled, adapter, artifacts, page, ocr=None, visual_review=None,
    request_revision=None, render_revision=None, parent_render_revision=None,
    issue=None, on_success=None,
):
    """``visual_review(render, image)`` reviews the finished render; with the
    read in ``ocr`` it makes the page's automatic checks."""

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
            await asyncio.to_thread(artifacts.write_page_failure,
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
        review_usage = (
            await _review_back(review=visual_review, page=page, render=provenance.render, artifacts=artifacts)
            if visual_review is not None else ()
        )
        return ApiResult(
            value=provenance,
            usage=provenance.usage,
            provider_request_id=provenance.provider_request_id,
            actual_provider_model=provenance.usage.provider_model,
            additional_usage=(*_analysis_usage(artifacts, provenance), *review_usage),
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


def page_visual_check(config: Config, project_dir: Path, artifacts: TargetArtifacts, page: ComicPage):
    """The visual review a draw job runs on its finished render."""

    async def review(render: PageRenderRevision, image: bytes):
        from novel_to_comic.page_visual_review import review_drawn_page

        return await review_drawn_page(
            config=config, project_dir=project_dir, artifacts=artifacts,
            page=page, render=render, image=image,
        )

    return review
