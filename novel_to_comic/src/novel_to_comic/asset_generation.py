"""Style/Cast asset compile, freeze, transport, and provenance lifecycle."""

from __future__ import annotations

import hashlib
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
from novel_to_comic.frozen_requests import (
    execute_frozen_request,
    submit_frozen_request,
)
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_models import describe_image_model, image_model_profile_for_config
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
    "labs_image",
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


@dataclass(frozen=True, slots=True)
class AbstractStyleProofInput(AssetGenerationInput):
    asset_kind: AssetKind = field(default="style_sample", init=False)


@dataclass(frozen=True, slots=True)
class EntityStyleProofInput(AbstractStyleProofInput):
    """Style proof with supplied structured anchors; the compiler protects them."""


@dataclass(frozen=True, slots=True)
class CharacterStyleCalibrationInput(AssetGenerationInput):
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
    job: Any | None = None
    created: bool = True


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
        label="selected style",
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
    controls = GenerationControls(
        quality=config.image_quality if profile.supports_control("quality") else None,
    )
    plan = reference_plan or reference_plan_for_assets(config, [])
    compiled = compile_generation_request(
        prompt=input_data.prompt,
        reference_plan=plan,
        route_profile=profile,
        requested_alias=model,
        configured_provider_model=describe_image_model(model).provider_model,
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
        wire=compile_provider_wire_request(compiled),
    )


def estimate_non_panel_request(
    config: Config,
    input_data: AssetGenerationInput,
    *,
    reference_plan: ReferencePlan | None = None,
    prepared: bool = False,
) -> NonPanelEstimate:
    request = compile_non_panel_request(config, input_data, reference_plan=reference_plan)
    cost = estimate_image_cost(
        config.effective_image_model(), 1,
        quality=getattr(config, "image_quality", None),
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


def _meta_payload(request: NonPanelRequest, provenance: dict[str, Any], *, error: BaseException | None = None) -> dict[str, Any]:
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
    }
    if request.input.lineage:
        # State-asset readers historically consume these fields at the sidecar
        # root. Keep the asset-specific extension alongside the common envelope.
        payload.update(request.input.lineage)
    if error is not None:
        classification = classify_image_failure(error)
        payload.update({
            "classification": classification,
            "recoverable": classification != "configuration_error",
            "user_message": user_message_for_image_failure(classification),
            "error": {
                "type": type(error).__name__,
                "message": "image asset generation failed",
            },
        })
    return payload


def asset_matches_request(output_path: Path, request: NonPanelRequest) -> bool:
    """Return true only when an existing result has the same frozen identity."""
    if not output_path.exists():
        return False
    try:
        meta = artifacts.read_asset_meta(output_path)
    except Exception:
        return False
    provenance = meta.get("provenance") if isinstance(meta, dict) else None
    return isinstance(provenance, dict) and provenance.get("execution_fingerprint") == request.wire.execution_fingerprint


def persist_non_panel_provenance(
    *, request: NonPanelRequest, output_path: Path, project_dir: Path,
    request_id: str | None, result: ApiResult[Any] | None = None,
    error: BaseException | None = None,
) -> None:
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
                               else usage.provider_model if usage else None),
        provider_request_id=result.provider_request_id if result else None,
        cost_usd=usage.cost_usd if usage else None,
        failure=(
            {"type": type(error).__name__, "message": str(error)} if error else None
        ),
        project_dir=project_dir,
        lineage=request.input.lineage,
    )
    payload = _meta_payload(request, provenance, error=error)
    if error is not None:
        artifacts.write_asset_failure(output_path, payload)
    else:
        artifacts.write_asset_meta(output_path, payload)


async def submit_non_panel_request(
    *, config: Config, project_dir: Path, request: NonPanelRequest, output_path: Path,
    app: Any | None = None, project_name: str | None = None, user_id: str | None = None,
    project_id: str | None = None, stage: str = "cast", kind: str = "asset_regen",
    label: str | None = None, payload: dict[str, Any] | None = None,
    debit_description: str = "Model call: generate image asset",
    idempotency_key: str | None = None, feature: str = "image.non_panel",
    semaphore: Any | None = None, estimate_credits: int = 0,
) -> NonPanelSubmission:
    if app is None:
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

    if not project_name or user_id is None:
        raise ValueError("queued non-panel submission requires project_name and user_id")
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    async def _complete(result: ApiResult[Any], frozen: Any) -> None:
        persist_non_panel_provenance(
            request=request, output_path=output_path, project_dir=project_dir,
            request_id=frozen.request_id, result=result,
        )

    async def _failure(error: BaseException, frozen: Any) -> None:
        persist_non_panel_provenance(
            request=request, output_path=output_path, project_dir=project_dir,
            request_id=frozen.request_id, error=error,
        )

    job, created = enqueue_frozen_generation_job(
        app, project_name=project_name, user_id=user_id, project_id=project_id,
        project_dir=project_dir, config=config, stage=stage, kind=kind,
        label=label or kind, payload=payload or {}, wire=request.wire,
        output_path=output_path, debit_description=debit_description,
        idempotency_key=idempotency_key, feature=feature, semaphore=semaphore,
        estimate_credits=estimate_credits, on_complete=_complete, on_failure=_failure,
        request_context=compiled_request_context(request.compiled),
    )
    return NonPanelSubmission(
        job.payload["frozen_request_id"], request.wire.execution_fingerprint,
        job=job, created=created,
    )


__all__ = [
    "AbstractStyleProofInput", "AssetGenerationInput", "CanonicalCharacterReferenceInput",
    "CanonicalLocationPlateInput", "CharacterStateReferenceInput", "EntityStyleProofInput",
    "LocationStatePlateInput", "NonPanelEstimate", "NonPanelRequest", "NonPanelSubmission",
    "ProjectCoverInput", "PropReferenceInput", "compile_non_panel_request",
    "common_image_provenance", "estimate_non_panel_request", "failed_image_provenance",
    "persist_non_panel_provenance", "reference_plan_for_assets", "style_reference_plan",
    "submit_non_panel_request", "asset_matches_request",
]
