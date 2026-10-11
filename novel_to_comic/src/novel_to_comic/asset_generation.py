"""Style/Cast asset compile, freeze, transport, and provenance lifecycle."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from novel_to_comic import artifacts
from novel_to_comic.compiled_request import (
    CompiledGenerationRequest,
    GenerationControls,
    compile_generation_request,
)
from novel_to_comic.config import Config
from novel_to_comic.codex_dev import route_for
from novel_to_comic.frozen_requests import (
    execute_frozen_request,
    submit_frozen_request,
)
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_models import (
    describe_image_model,
    image_model_profile_for_config,
    image_quality_for_model,
)
from novel_to_comic.image_provenance import (
    common_image_provenance,
    failed_image_provenance,
)
from novel_to_comic.image_failure import (
    classify_image_failure,
    user_message_for_image_failure,
)
from novel_to_comic.generation_request_preview import compiled_request_context
from novel_to_comic.image_references import (
    AuthorityScope,
    ReferenceAsset,
    ReferencePlan,
    selection_fingerprint_hex,
)
from novel_to_comic.provider_wire import ProviderWireRequest, compile_provider_wire_request
from novel_to_comic.usage import ApiResult, estimate_image_cost

AssetKind = Literal[
    "style_sample", "style_calibration", "character_ref", "location_plate", "prop_ref", "project_cover",
]


@dataclass(frozen=True, slots=True)
class AssetGenerationInput:
    """Explicit non-panel request input; no panel identifiers are permitted."""

    prompt: GenerationPromptInput
    asset_identity: str
    selected_style_text: str | None = None
    selected_style_source_hash: str | None = None
    asset_kind: AssetKind = "style_sample"
    lineage: dict[str, Any] | None = None
    edit_parent_indices: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AbstractStyleProofInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="style_sample", init=False)


@dataclass(frozen=True, slots=True)
class EntityStyleProofInput(AbstractStyleProofInput):
    """Style proof with supplied structured anchors; the compiler protects them."""


@dataclass(frozen=True, slots=True)
class StyleCalibrationInput(AssetGenerationInput):
    """Rendering-only board derived from the selected proof, with no subjects."""

    asset_kind: AssetKind = field(default="style_calibration", init=False)


@dataclass(frozen=True, slots=True)
class CanonicalCharacterReferenceInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="character_ref", init=False)


@dataclass(frozen=True, slots=True)
class CanonicalLocationPlateInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="location_plate", init=False)


@dataclass(frozen=True, slots=True)
class CharacterStateReferenceInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="character_ref", init=False)


@dataclass(frozen=True, slots=True)
class LocationStatePlateInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="location_plate", init=False)


@dataclass(frozen=True, slots=True)
class PropReferenceInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="prop_ref", init=False)


@dataclass(frozen=True, slots=True)
class ProjectCoverInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="project_cover", init=False)


@dataclass(frozen=True, slots=True)
class NonPanelRequest:
    input: AssetGenerationInput
    reference_plan: ReferencePlan
    compiled: CompiledGenerationRequest
    wire: ProviderWireRequest

    @property
    def compiled_request_sha256(self) -> str:
        return self.compiled.compiled_request_sha256

    @property
    def execution_fingerprint(self) -> str:
        return self.wire.execution_fingerprint


@dataclass(frozen=True, slots=True)
class NonPanelEstimate:
    cost_usd: float
    status: str
    route: str
    reference_count: int
    dimensions: tuple[int, int]
    execution_fingerprint: str | None
    wire: ProviderWireRequest | None
    prompt_text: str


@dataclass(frozen=True, slots=True)
class NonPanelSubmission:
    request_id: str
    execution_fingerprint: str
    result: ApiResult[Any] | None = None


def reference_plan_for_assets(config: Config, references: list[ReferenceAsset]) -> ReferencePlan:
    """Create a final plan from already-resolved semantic references."""
    profile = image_model_profile_for_config(config)
    selected: list[ReferenceAsset] = []
    for reference in references:
        if reference.role not in profile.supported_roles:
            raise ValueError(
                f"Required reference role {reference.role} is unsupported by route {profile.route.value}."
            )
        if not reference.path.exists():
            raise ValueError(f"Required reference is missing at {reference.path}; regenerate it before continuing.")
        selected.append(reference)
    if len(selected) > profile.max_references:
        raise ValueError(
            f"Reference overflow: {len(selected)} required references exceed "
            f"route {profile.route.value} limit {profile.max_references}."
        )
    return ReferencePlan(
        expected_route=profile.route,
        selected=tuple(selected),
        dropped=(),
        selection_fingerprint=selection_fingerprint_hex(selected),
    )


def style_reference_plan(
    config: Config, style_path: Path | None, *,
    mode: Literal["faithful", "variation"] = "faithful",
    preserve_facets: tuple[str, ...] = (),
    label: str = "selected style",
) -> ReferencePlan:
    """Resolve one optional style reference without filename-based inference."""
    if style_path is None:
        return reference_plan_for_assets(config, [])
    digest = hashlib.sha256(style_path.read_bytes()).hexdigest() if style_path.exists() else ""
    reference = ReferenceAsset(
        path=style_path, role="style", entity_id=None, appearance_state_id=None,
        authority_scope=AuthorityScope.CONTEXTUAL, preserve_facets=preserve_facets,
        ignore_facets=("candidate-controlled rendering facets",) if mode == "variation" else (),
        pose=None, content_sha256=digest, lineage_parent_sha256=None,
        label=label,
    )
    return reference_plan_for_assets(config, [reference])


def compile_non_panel_request(
    config: Config,
    input_data: AssetGenerationInput,
    *,
    reference_plan: ReferencePlan | None = None,
) -> NonPanelRequest:
    profile = image_model_profile_for_config(config)
    model = config.effective_image_model()
    codex_route = route_for("image", model)
    controls = GenerationControls(
        quality=image_quality_for_model(model, config.image_quality) if profile.supports_control("quality") else None,
    )
    plan = reference_plan or reference_plan_for_assets(config, [])
    compiled = compile_generation_request(
        prompt=input_data.prompt,
        reference_plan=plan,
        route_profile=profile,
        requested_alias=model,
        configured_provider_model=(
            codex_route.image_model if codex_route else describe_image_model(model).provider_model
        ),
        selected_style_text=input_data.selected_style_text,
        selected_style_source_hash=input_data.selected_style_source_hash,
        controls=controls,
        asset_kind=input_data.asset_kind,
        asset_identity=input_data.asset_identity,
    )
    return NonPanelRequest(
        input=input_data,
        reference_plan=plan,
        compiled=compiled,
        wire=compile_provider_wire_request(compiled, edit_parent_indices=input_data.edit_parent_indices),
    )


def estimate_non_panel_request(
    config: Config,
    input_data: AssetGenerationInput,
    *,
    reference_plan: ReferencePlan | None = None,
    prepared: bool = False,
) -> NonPanelEstimate:
    request = compile_non_panel_request(config, input_data, reference_plan=reference_plan)
    cost = 0.0 if request.wire.provider_key == "codex-dev" else estimate_image_cost(
        config.effective_image_model(), 1,
        quality=dict(request.wire.controls).get("quality"),
        ref_count=request.reference_plan.ref_count,
        prompt_text=request.compiled.final_prompt,
        width=request.wire.width,
        height=request.wire.height,
    )
    return NonPanelEstimate(
        cost_usd=cost,
        status="prepared" if prepared else "provisional",
        route=request.wire.expected_route,
        reference_count=request.reference_plan.ref_count,
        dimensions=(request.wire.width, request.wire.height),
        execution_fingerprint=request.wire.execution_fingerprint if prepared else None,
        wire=request.wire if prepared else None,
        prompt_text=request.compiled.final_prompt,
    )


def _actual_dimensions(path: Path) -> tuple[int | None, int | None]:
    try:
        from PIL import Image

        with Image.open(path) as image:
            return image.width, image.height
    except Exception:
        return None, None


def _meta_payload(
    request: NonPanelRequest, provenance: dict[str, Any], *,
    error: BaseException | None = None, attempts: int = 1,
) -> dict[str, Any]:
    payload = {
        "version": 1,
        "kind": request.input.asset_kind,
        "asset_identity": request.input.asset_identity,
        "prompt": request.wire.prompt_parts[0],
        "prompt_sha256": hashlib.sha256(request.wire.prompt_parts[0].encode()).hexdigest(),
        "parameters": {
            "compiled_request_sha256": request.compiled.compiled_request_sha256,
            "execution_fingerprint": request.wire.execution_fingerprint,
            "reference_selection_fingerprint": request.reference_plan.selection_fingerprint,
            "refs": [
                {"index": index, "role": asset.role, "entity_id": asset.entity_id,
                 "appearance_state_id": asset.appearance_state_id,
                 "content_sha256": asset.content_sha256}
                for index, asset in enumerate(request.reference_plan.selected)
            ],
            "width": request.wire.width,
            "height": request.wire.height,
            "controls": dict(request.wire.controls),
        },
        "provenance": provenance,
        "art_direction": request.input.prompt.editorial_addendum,
        "reference_assets": [
            # Uploads are content-addressed: their id is the image hash prefix.
            {"upload_id": asset.content_sha256[:32]} if asset.entity_id is None else
            {"asset_type": {"subject": "character", "location_plate": "location", "prop": "prop"}[asset.role],
             "asset_id": asset.entity_id, "state_id": asset.appearance_state_id}
            for asset in request.reference_plan.selected if asset.purpose == "instruction_context"
        ],
    }
    if request.input.lineage:
        # State-asset readers historically consume these fields at the sidecar
        # root. Keep the asset-specific extension alongside the common envelope.
        payload.update(request.input.lineage)
    if error is not None:
        classification = classify_image_failure(error)
        payload.update({
            "attempts": attempts,
            "classification": classification,
            "recoverable": classification != "configuration_error",
            "user_message": user_message_for_image_failure(classification),
            "error": {
                "type": type(error).__name__,
                "message": "image asset generation failed",
            },
        })
    return payload


# An unchanged request that the provider declined is expected to be declined
# again. Opaque errors get one more try before they are held as well.
_HELD_FAILURES = frozenset({"provider_blocked"})
_HELD_AFTER_REPEAT = frozenset({"generation_error", "empty_response"})


def read_asset_failure(output_path: Path) -> dict[str, Any] | None:
    try:
        failure = json.loads(artifacts.asset_failure_path(output_path).read_text())
    except (OSError, ValueError):
        return None
    return failure if isinstance(failure, dict) else None


def _failure_fingerprint(failure: dict[str, Any] | None) -> str | None:
    provenance = failure.get("provenance") if failure else None
    return provenance.get("execution_fingerprint") if isinstance(provenance, dict) else None


def held_asset_failure(output_path: Path, request: NonPanelRequest) -> dict[str, Any] | None:
    """Return the stored failure when resubmitting this exact request would repeat it.

    Stage resumes skip held assets instead of spending time or credits on a
    known outcome. Changing the asset's direction produces a new fingerprint,
    and explicit per-asset regeneration never consults this hold.
    """
    failure = read_asset_failure(output_path)
    if failure is None or _failure_fingerprint(failure) != request.wire.execution_fingerprint:
        return None
    classification = failure.get("classification")
    attempts = failure.get("attempts")
    attempts = attempts if type(attempts) is int else 1
    if classification in _HELD_FAILURES or (classification in _HELD_AFTER_REPEAT and attempts >= 2):
        return failure
    return None


def asset_matches_request(output_path: Path, request: NonPanelRequest) -> bool:
    """Return true when an existing result has the same frozen identity.

    The author can also explicitly keep an image after editing its entity's
    description; that acceptance is recorded beside the provenance (never in
    place of it) and counts as current for exactly the accepted request.
    """
    if not output_path.exists():
        return False
    try:
        meta = artifacts.read_asset_meta(output_path)
    except Exception:
        return False
    if not isinstance(meta, dict):
        return False
    fingerprint = request.wire.execution_fingerprint
    provenance = meta.get("provenance")
    if isinstance(provenance, dict) and provenance.get("execution_fingerprint") == fingerprint:
        return True
    return any(isinstance(item, dict) and item.get("execution_fingerprint") == fingerprint
               for item in meta.get("accepted_requests", ()))


def accept_existing_asset(output_path: Path, request: NonPanelRequest, *, reason: str) -> None:
    """Record the author's decision to keep an image for a changed request."""
    from datetime import UTC, datetime

    meta = artifacts.read_asset_meta(output_path)
    accepted = [item for item in meta.get("accepted_requests", ())
                if item.get("execution_fingerprint") != request.wire.execution_fingerprint]
    accepted.append({
        "execution_fingerprint": request.wire.execution_fingerprint,
        "accepted_at": datetime.now(UTC).isoformat(),
        "reason": reason,
    })
    artifacts.write_asset_meta(output_path, {**meta, "accepted_requests": accepted})


def persist_non_panel_provenance(
    *, request: NonPanelRequest, output_path: Path, project_dir: Path,
    request_id: str | None, result: ApiResult[Any] | None = None,
    error: BaseException | None = None,
) -> None:
    from novel_to_comic.asset_scope import require_project_asset_path

    require_project_asset_path(project_dir, output_path)
    width = height = None
    if result is not None and result.value is not None:
        width, height = _actual_dimensions(Path(result.value))
    usage = result.usage if result is not None else None
    provenance = common_image_provenance(
        asset_kind=request.input.asset_kind,
        asset_identity=request.input.asset_identity,
        compiled_sha256=request.compiled.compiled_request_sha256,
        prompt_source_sha256=request.compiled.prompt_source_sha256,
        wire=request.wire,
        reference_plan=request.reference_plan,
        request_id=request_id,
        actual_width=width,
        actual_height=height,
        actual_provider_model=(result.actual_provider_model if result and result.actual_provider_model
                               else usage.provider_model if usage and request.wire.provider_key != "codex-dev" else None),
        provider_request_id=result.provider_request_id if result else None,
        cost_usd=usage.cost_usd if usage else None,
        failure=(
            {"type": type(error).__name__, "message": str(error)} if error else None
        ),
        project_dir=project_dir,
        lineage=request.input.lineage,
        funding=usage.funding if usage else ("codex_subscription" if request.wire.provider_key == "codex-dev" else "api"),
        response_metadata=result.response_metadata if result else None,
    )
    if error is not None:
        previous = read_asset_failure(output_path)
        attempts = 1
        if _failure_fingerprint(previous) == request.wire.execution_fingerprint:
            prior = previous.get("attempts") if previous else None
            attempts = (prior if type(prior) is int else 1) + 1
        artifacts.write_asset_failure(output_path, _meta_payload(request, provenance, error=error, attempts=attempts))
    else:
        artifacts.write_asset_meta(output_path, _meta_payload(request, provenance))
        artifacts.asset_failure_path(output_path).unlink(missing_ok=True)


async def submit_non_panel_request(*, config: Config, project_dir: Path,
    request: NonPanelRequest, output_path: Path, kind: str = "asset_regen",
    idempotency_key: str | None = None, feature: str = "image.non_panel") -> NonPanelSubmission:
    frozen = submit_frozen_request(
        project_dir,
        request.wire,
        idempotency_key=idempotency_key,
        request_context=compiled_request_context(request.compiled),
    )
    try:
        result = await execute_frozen_request(
            project_dir=project_dir, request_id=frozen.request_id,
            config=config, output_path=output_path, feature=feature,
        )
    except BaseException as error:
        persist_non_panel_provenance(
            request=request, output_path=output_path, project_dir=project_dir,
            request_id=frozen.request_id, error=error,
        )
        raise
    persist_non_panel_provenance(
        request=request, output_path=output_path, project_dir=project_dir,
        request_id=frozen.request_id, result=result,
    )
    return NonPanelSubmission(frozen.request_id, frozen.execution_fingerprint, result=result)


__all__ = [
    "AbstractStyleProofInput", "AssetGenerationInput", "CanonicalCharacterReferenceInput",
    "CanonicalLocationPlateInput", "CharacterStateReferenceInput", "EntityStyleProofInput",
    "LocationStatePlateInput", "NonPanelEstimate", "NonPanelRequest", "NonPanelSubmission",
    "ProjectCoverInput", "PropReferenceInput", "compile_non_panel_request",
    "common_image_provenance", "estimate_non_panel_request", "failed_image_provenance",
    "persist_non_panel_provenance", "reference_plan_for_assets", "style_reference_plan",
    "submit_non_panel_request", "asset_matches_request", "held_asset_failure",
    "read_asset_failure",
]
