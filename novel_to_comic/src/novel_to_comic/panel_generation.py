"""Authoritative lifecycle for production panel image requests.

Panel callers may prepare prompts in different contexts (stage draw, a manual
rerender, or Labs import), but the provider-facing path is intentionally one
small seam: prepare -> resolve -> compile -> wire -> freeze -> transport.
This module contains no provider selection heuristics and makes no model calls
unless ``prepare_panel_prompt`` is explicitly asked to hydrate missing derived
prompt data.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from types import SimpleNamespace

from novel_to_comic import artifacts
from novel_to_comic.compiled_request import (
    COMPILED_REQUEST_SCHEMA_VERSION,
    GenerationControls,
    CompiledGenerationRequest,
    compile_generation_request,
)
from novel_to_comic.config import Config
from novel_to_comic.frozen_requests import (
    FROZEN_REQUEST_PREPARATION_VERSION,
    FROZEN_REQUEST_SOURCE_VERSION,
    FROZEN_REQUEST_VERSION,
    execute_frozen_request,
    submit_frozen_request,
)
from novel_to_comic.image_models import describe_image_model, image_model_profile_for_config
from novel_to_comic.image_provenance import common_image_provenance
from novel_to_comic.image_references import ReferencePlan
from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireRequest,
    compile_provider_wire_request,
)
from novel_to_comic.usage import ApiResult, estimate_image_cost


PANEL_PROVENANCE_SCHEMA_VERSION = 1


def _redact_diagnostic(value: Any, project_dir: Path | None = None) -> str:
    text = str(value)
    if project_dir is not None:
        try:
            text = text.replace(str(project_dir.resolve()), "<project>")
            text = text.replace(str(project_dir.resolve().parent), "<workspace>")
        except OSError:
            pass
    return text


@dataclass(frozen=True, slots=True)
class PanelRequest:
    """The complete provider-independent and provider-wire panel request."""

    prompt: ImagePrompt
    reference_plan: ReferencePlan
    compiled: CompiledGenerationRequest
    wire: ProviderWireRequest
    prompt_path: Path | None = None


@dataclass(frozen=True, slots=True)
class PanelEstimate:
    cost_usd: float
    status: str  # prepared | provisional
    route: str
    reference_count: int
    dimensions: tuple[int, int]
    execution_fingerprint: str | None
    wire: ProviderWireRequest | None
    prompt_text: str


@dataclass(frozen=True, slots=True)
class PanelSubmission:
    request_id: str | None
    execution_fingerprint: str
    result: ApiResult[Any] | None = None
    job: Any | None = None
    created: bool = True


async def prepare_panel_prompt(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    *,
    story_bible: Any | None = None,
    panel: Any | None = None,
    prev_panel: Any | None = None,
) -> ImagePrompt:
    """Load and hydrate one panel prompt exactly once for a request.

    The content-freshness rebuild remains owned by ``prompt_assembly``. Missing
    derived fields are then hydrated only when absent; a queued runner never
    calls this function because it consumes the frozen wire instead.
    """
    from novel_to_comic.prompt_assembly import (
        ensure_current_panel_prompt,
        ensure_layout,
        ensure_visual_brief,
    )
    from novel_to_comic.prompting import ensure_distilled_prompt

    prompt = ImagePrompt.model_validate_json(prompt_path.read_text())
    if story_bible is not None and panel is not None:
        prompt = ensure_current_panel_prompt(
            config, project_dir, panel, story_bible, prev_panel
        )
    prompt = ensure_distilled_prompt(config, prompt)
    prompt = await ensure_visual_brief(config, prompt)
    prompt = await ensure_layout(config, prompt)
    if prompt_path.exists():
        current = ImagePrompt.model_validate_json(prompt_path.read_text())
        if current.model_dump() != prompt.model_dump():
            prompt_path.write_text(prompt.model_dump_json(indent=2))
    else:
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prompt.model_dump_json(indent=2))
    return prompt


async def prepare_panel_request(
    config: Config,
    project_dir: Path,
    prompt_path: Path,
    *,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    location_labels: dict[str, str] | None = None,
    experiment_inputs: dict[str, Any] | None = None,
) -> PanelRequest:
    """Prepare one stored panel and immediately compile its final request."""
    story_bible = None
    panel = None
    prev_panel = None
    try:
        story_bible = artifacts.read_story_bible(project_dir)
        from novel_to_comic.layout_planning import load_layout_plan, scene_panel_map

        plan_path = artifacts.layout_plan_path(project_dir)
        if plan_path.exists():
            panels = scene_panel_map(load_layout_plan(project_dir)).get(prompt_path.parent.name, [])
            for index, candidate in enumerate(panels):
                if candidate.panel_number == int(prompt_path.stem.split("_")[1]):
                    panel = candidate
                    prev_panel = panels[index - 1] if index else None
                    break
    except Exception:
        story_bible = None
    prompt = await prepare_panel_prompt(
        config,
        project_dir,
        prompt_path,
        story_bible=story_bible,
        panel=panel,
        prev_panel=prev_panel,
    )
    if scene_to_location is None and story_bible is not None:
        scene_to_location = {scene.id: scene.location_id for scene in story_bible.scenes}
    if location_labels is None and story_bible is not None:
        location_labels = {location.id: location.name for location in story_bible.locations}
    return compile_panel_request(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        location_labels=location_labels,
        experiment_inputs=experiment_inputs,
        output_dir=project_dir / "draw" / prompt.scene_id,
    )


def resolve_panel_references(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    output_dir: Path | None = None,
    location_labels: dict[str, str] | None = None,
) -> ReferencePlan:
    """Resolve the final Slice 04 plan; no caller may select again."""
    # Kept as a runtime import because the existing Slice 04 selector lives in
    # s7_draw.  s7_draw itself imports this module only inside call paths.
    from novel_to_comic.stages.s7_draw import build_panel_reference_plan

    return build_panel_reference_plan(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        output_dir=output_dir,
        location_labels=location_labels,
    )


def compile_panel_request(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    reference_plan: ReferencePlan | None = None,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    output_dir: Path | None = None,
    location_labels: dict[str, str] | None = None,
    experiment_inputs: dict[str, Any] | None = None,
) -> PanelRequest:
    """Compile one exact panel request and its portable provider wire."""
    plan = reference_plan or resolve_panel_references(
        config,
        project_dir,
        prompt,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        output_dir=output_dir,
        location_labels=location_labels,
    )
    profile = image_model_profile_for_config(config)
    model = config.effective_image_model()
    description = describe_image_model(model)
    controls = GenerationControls(
        quality=config.image_quality if profile.supports_control("quality") else None,
    )
    # Experimental Labs inputs are explicit compiler inputs.  Keeping them in
    # the style text makes the change visible in both compiled and execution
    # fingerprints without letting a provider adapter invent semantics.
    selected_style = config.style_template
    if experiment_inputs:
        selected_style = (
            f"{selected_style}\n\nExperiment inputs: "
            f"{json.dumps(experiment_inputs, sort_keys=True, ensure_ascii=False)}"
        ).strip()
    compiled = compile_generation_request(
        prompt=prompt,
        reference_plan=plan,
        route_profile=profile,
        requested_alias=model,
        configured_provider_model=description.provider_model,
        selected_style_text=selected_style,
        controls=controls,
        asset_kind="panel",
    )
    wire = compile_provider_wire_request(compiled)
    return PanelRequest(
        prompt=prompt,
        reference_plan=plan,
        compiled=compiled,
        wire=wire,
        prompt_path=prompt_path,
    )


def estimate_panel_request(
    config: Config,
    project_dir: Path,
    prompt: ImagePrompt,
    *,
    reference_plan: ReferencePlan | None = None,
    prompt_path: Path | None = None,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    prepared: bool = False,
    experiment_inputs: dict[str, Any] | None = None,
) -> PanelEstimate:
    """Estimate from the same compiler, without silently preparing a prompt.

    ``prepared=True`` is an assertion by the caller that all derived prompt
    fields were already prepared.  Otherwise the estimate is deliberately
    provisional: it uses current structured input, returns no exact
    fingerprint, and never invokes an LLM preparation pass.
    """
    request = compile_panel_request(
        config,
        project_dir,
        prompt,
        reference_plan=reference_plan,
        prompt_path=prompt_path,
        style_sample=style_sample,
        scene_to_location=scene_to_location,
        experiment_inputs=experiment_inputs,
    )
    cost = estimate_image_cost(
        config.effective_image_model(),
        1,
        quality=getattr(config, "image_quality", None),
        ref_count=len(request.reference_plan.selected),
        prompt_text=request.compiled.final_prompt,
    )
    return PanelEstimate(
        cost_usd=cost,
        status="prepared" if prepared else "provisional",
        route=request.wire.expected_route,
        reference_count=len(request.reference_plan.selected),
        dimensions=(request.wire.width, request.wire.height),
        execution_fingerprint=(request.wire.execution_fingerprint if prepared else None),
        wire=request.wire if prepared else None,
        prompt_text=request.compiled.final_prompt,
    )


def _reference_payload(plan: ReferencePlan, project_dir: Path) -> list[dict[str, Any]]:
    result = []
    for index, asset in enumerate(plan.selected):
        try:
            path = str(asset.path.relative_to(project_dir))
        except ValueError:
            path = str(asset.path)
        result.append({
            "index": index,
            "path": path,
            "role": asset.role,
            "entity_id": asset.entity_id,
            "appearance_state_id": asset.appearance_state_id,
            "authority_scope": asset.authority_scope.value,
            "preserve_facets": list(asset.preserve_facets),
            "ignore_facets": list(asset.ignore_facets),
            "content_sha256": asset.content_sha256,
        })
    return result


def panel_provenance(
    *,
    compiled_sha256: str,
    prompt_source_sha256: str | None = None,
    wire: Any,
    reference_plan: Any,
    request_id: str | None,
    actual_width: int | None = None,
    actual_height: int | None = None,
    actual_provider_model: str | None = None,
    provider_request_id: str | None = None,
    latency_ms: int | None = None,
    cost_usd: float | None = None,
    failure: dict[str, Any] | None = None,
    started_at: str | None = None,
    project_dir: Path | None = None,
    asset_identity: str | None = None,
) -> dict[str, Any]:
    """Build the common redaction-safe panel result/failure envelope."""
    return common_image_provenance(
        asset_kind="panel",
        asset_identity=asset_identity or getattr(wire, "asset_identity", "panel"),
        compiled_sha256=compiled_sha256,
        prompt_source_sha256=prompt_source_sha256,
        wire=wire,
        reference_plan=reference_plan,
        request_id=request_id,
        actual_width=actual_width,
        actual_height=actual_height,
        actual_provider_model=actual_provider_model,
        provider_request_id=provider_request_id,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        failure=failure,
        project_dir=project_dir,
    )
    # The legacy implementation below is retained only as a source reference
    # for the panel migration and is unreachable; all callers use the common
    # non-panel-compatible envelope above.
    selected = []
    for index, asset in enumerate(getattr(reference_plan, "selected", ())):
        path = str(asset.path)
        if project_dir is not None:
            try:
                path = str(asset.path.relative_to(project_dir))
            except ValueError:
                pass
        selected.append({
            "index": index,
            "path": path,
            "role": asset.role,
            "entity_id": asset.entity_id,
            "appearance_state_id": asset.appearance_state_id,
            "authority_scope": asset.authority_scope.value,
            "preserve_facets": list(asset.preserve_facets),
            "ignore_facets": list(asset.ignore_facets),
            "content_sha256": asset.content_sha256,
        })
    dropped = []
    for drop in getattr(reference_plan, "dropped", ()):
        candidate = drop.candidate
        dropped.append({
            "role": candidate.role,
            "entity_id": candidate.entity_id,
            "reason": drop.reason.value,
            "detail": _redact_diagnostic(drop.detail, project_dir),
        })
    envelope: dict[str, Any] = {
        "schema_version": PANEL_PROVENANCE_SCHEMA_VERSION,
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "prepared_prompt_source_sha256": prompt_source_sha256,
        "compiled_request_sha256": compiled_sha256,
        "provider_wire_schema_version": getattr(wire, "schema_version", PROVIDER_WIRE_SCHEMA_VERSION),
        "frozen_request_preparation_version": FROZEN_REQUEST_PREPARATION_VERSION,
        "frozen_request_source_version": FROZEN_REQUEST_SOURCE_VERSION,
        "frozen_request_version": FROZEN_REQUEST_VERSION,
        "request_id": request_id,
        "execution_fingerprint": wire.execution_fingerprint,
        "reference_selection_fingerprint": getattr(reference_plan, "selection_fingerprint", None),
        "selected_references": selected,
        "dropped_candidates": dropped,
        "warnings": [
            _redact_diagnostic(warning, project_dir)
            for warning in getattr(reference_plan, "warnings", ())
        ],
        "requested_alias": wire.requested_alias,
        "expected_route": wire.expected_route,
        "configured_provider_model": wire.configured_provider_model,
        "actual_provider_model": actual_provider_model,
        "requested_dimensions": {"width": wire.width, "height": wire.height},
        "effective_dimensions": {"width": wire.width, "height": wire.height},
        "actual_dimensions": {"width": actual_width, "height": actual_height},
        "provider_request_id": provider_request_id,
        "latency_ms": latency_ms,
        "cost_usd": cost_usd,
        "failure": failure,
        # Timestamps are useful diagnostics but are excluded from the stable
        # record identity below.
        "started_at": started_at or datetime.now(UTC).isoformat(),
    }
    hash_projection = {key: value for key, value in envelope.items() if key not in {"started_at", "latency_ms"}}
    envelope["provenance_record_hash"] = hashlib.sha256(
        json.dumps(hash_projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return envelope


def panel_failure_provenance(
    error: BaseException, project_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a stable envelope when preparation failed before a wire existed."""
    envelope: dict[str, Any] = {
        "schema_version": PANEL_PROVENANCE_SCHEMA_VERSION,
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "provider_wire_schema_version": PROVIDER_WIRE_SCHEMA_VERSION,
        "frozen_request_preparation_version": FROZEN_REQUEST_PREPARATION_VERSION,
        "frozen_request_source_version": FROZEN_REQUEST_SOURCE_VERSION,
        "frozen_request_version": FROZEN_REQUEST_VERSION,
        "request_id": None,
        "execution_fingerprint": None,
        "failure": {
            "type": type(error).__name__,
            "message": _redact_diagnostic(error, project_dir),
        },
        "started_at": datetime.now(UTC).isoformat(),
    }
    projection = {key: value for key, value in envelope.items() if key != "started_at"}
    envelope["provenance_record_hash"] = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return envelope


def wire_provenance(
    wire: ProviderWireRequest,
    *,
    request_id: str | None,
    actual_width: int | None = None,
    actual_height: int | None = None,
    actual_provider_model: str | None = None,
    provider_request_id: str | None = None,
    cost_usd: float | None = None,
    failure: dict[str, Any] | None = None,
    asset_identity: str = "panel",
) -> dict[str, Any]:
    """Build the same provenance envelope for a portable Labs wire."""
    return common_image_provenance(
        asset_kind="panel",
        asset_identity=asset_identity,
        compiled_sha256=wire.compiled_request_sha256,
        prompt_source_sha256=None,
        wire=wire,
        reference_plan=type("WirePlan", (), {
            "selected": tuple(SimpleNamespace(
                path=Path(ref.source_path), role=ref.role, entity_id=ref.entity_id,
                appearance_state_id=ref.appearance_state_id,
                authority_scope=ref.authority_scope,
                preserve_facets=ref.preserve_facets, ignore_facets=ref.ignore_facets,
                content_sha256=ref.content_sha256, lineage_parent_sha256=None,
            ) for ref in wire.references),
            "dropped": tuple(), "warnings": tuple(),
            "selection_fingerprint": None,
        })(),
        request_id=request_id,
        actual_width=actual_width,
        actual_height=actual_height,
        actual_provider_model=actual_provider_model,
        provider_request_id=provider_request_id,
        cost_usd=cost_usd,
        failure=failure,
    )
    # Unreachable legacy serialization is left below only to minimize this
    # migration's diff; callers return through the common helper above.
    record: dict[str, Any] = {
        "schema_version": PANEL_PROVENANCE_SCHEMA_VERSION,
        "compiled_request_schema_version": COMPILED_REQUEST_SCHEMA_VERSION,
        "provider_wire_schema_version": wire.schema_version,
        "frozen_request_preparation_version": FROZEN_REQUEST_PREPARATION_VERSION,
        "frozen_request_source_version": FROZEN_REQUEST_SOURCE_VERSION,
        "frozen_request_version": FROZEN_REQUEST_VERSION,
        "request_id": request_id,
        "execution_fingerprint": wire.execution_fingerprint,
        "compiled_request_sha256": wire.compiled_request_sha256,
        "selected_references": [
            {
                "index": ref.index,
                "role": ref.role,
                "entity_id": ref.entity_id,
                "appearance_state_id": ref.appearance_state_id,
                "authority_scope": ref.authority_scope,
                "preserve_facets": list(ref.preserve_facets),
                "ignore_facets": list(ref.ignore_facets),
                "content_sha256": ref.content_sha256,
            }
            for ref in wire.references
        ],
        "dropped_candidates": [],
        "warnings": [],
        "requested_alias": wire.requested_alias,
        "expected_route": wire.expected_route,
        "configured_provider_model": wire.configured_provider_model,
        "actual_provider_model": actual_provider_model,
        "requested_dimensions": {"width": wire.width, "height": wire.height},
        "effective_dimensions": {"width": wire.width, "height": wire.height},
        "actual_dimensions": {"width": actual_width, "height": actual_height},
        "provider_request_id": provider_request_id,
        "latency_ms": None,
        "cost_usd": cost_usd,
        "failure": failure,
        "started_at": datetime.now(UTC).isoformat(),
    }
    projection = {key: value for key, value in record.items() if key != "started_at"}
    record["provenance_record_hash"] = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    return record


def apply_panel_experiment(
    wire: ProviderWireRequest, experiment_inputs: dict[str, Any] | None,
) -> ProviderWireRequest:
    """Apply explicit Labs experiment inputs without hidden request assembly."""
    if not experiment_inputs:
        return wire
    marker = (
        "\n\nExperiment inputs: "
        + json.dumps(experiment_inputs, sort_keys=True, ensure_ascii=False)
    )
    updated = wire.prompt_parts[:-1] + (wire.prompt_parts[-1] + marker,)
    from dataclasses import replace

    updated_wire = replace(wire, prompt_parts=updated, execution_fingerprint="")
    experiment_hash = hashlib.sha256(
        json.dumps(
            {
                "base_compiled_request_sha256": wire.compiled_request_sha256,
                "experiment_inputs": experiment_inputs,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode()
    ).hexdigest()
    updated_wire = replace(updated_wire, compiled_request_sha256=experiment_hash)
    return replace(
        updated_wire,
        execution_fingerprint=updated_wire.recompute_execution_fingerprint(),
    )


def persist_panel_result_provenance(
    *,
    output_path: Path,
    request: PanelRequest,
    request_id: str | None,
    result: ApiResult[Any] | None = None,
    error: BaseException | None = None,
    project_dir: Path,
) -> None:
    """Persist the common panel envelope for queued and direct callers."""
    actual_width = actual_height = None
    if result is not None and result.value is not None:
        try:
            from PIL import Image

            with Image.open(result.value) as image:
                actual_width, actual_height = image.width, image.height
        except Exception:
            pass
    usage = result.usage if result is not None else None
    provenance = panel_provenance(
        compiled_sha256=request.compiled.compiled_request_sha256,
        prompt_source_sha256=request.compiled.prompt_source_sha256,
        wire=request.wire,
        reference_plan=request.reference_plan,
        request_id=request_id,
        actual_width=actual_width,
        actual_height=actual_height,
        actual_provider_model=(
            result.actual_provider_model
            if result is not None and result.actual_provider_model
            else usage.provider_model if usage else None
        ),
        provider_request_id=result.provider_request_id if result is not None else None,
        cost_usd=usage.cost_usd if usage else None,
        failure=(
            {
                "type": type(error).__name__,
                "message": _redact_diagnostic(error, project_dir),
            }
            if error is not None
            else None
        ),
        project_dir=project_dir,
        asset_identity=request.compiled.asset_identity,
    )
    params = {
        "execution_fingerprint": request.wire.execution_fingerprint,
        "compiled_request_sha256": request.compiled.compiled_request_sha256,
        "reference_selection_fingerprint": request.reference_plan.selection_fingerprint,
        "refs": _reference_payload(request.reference_plan, project_dir),
        "width": request.wire.width,
        "height": request.wire.height,
    }
    meta = {
        "version": 1,
        "kind": "panel_image_failure" if error is not None else "panel_image",
        "prompt": request.wire.prompt_parts[0],
        "prompt_sha256": hashlib.sha256(request.wire.prompt_parts[0].encode()).hexdigest(),
        "parameters": params,
        "provenance": provenance,
    }
    if error is not None:
        meta.update({
            "classification": "generation_error",
            "recoverable": True,
            "error": {
                "type": type(error).__name__,
                "message": _redact_diagnostic(error, project_dir),
            },
        })
        artifacts.write_asset_failure(output_path, meta)
    else:
        artifacts.write_asset_meta(output_path, meta)


async def submit_panel_request(
    *,
    config: Config,
    project_dir: Path,
    request: PanelRequest,
    output_path: Path,
    app: Any | None = None,
    project_name: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    stage: str = "draw",
    kind: str = "panel_regen",
    label: str | None = None,
    payload: dict[str, Any] | None = None,
    debit_description: str = "Model call: generate panel",
    idempotency_key: str | None = None,
    feature: str = "draw.panel_image",
    semaphore: Any | None = None,
    estimate_credits: int = 0,
) -> PanelSubmission:
    """Freeze one request, then either enqueue or execute that frozen request."""
    if app is None:
        frozen = submit_frozen_request(project_dir, request.wire)
        result = await execute_frozen_request(
            project_dir=project_dir,
            request_id=frozen.request_id,
            config=config,
            output_path=output_path,
            feature=feature,
        )
        return PanelSubmission(
            request_id=frozen.request_id,
            execution_fingerprint=frozen.execution_fingerprint,
            result=result,
        )

    if not project_name or user_id is None:
        raise ValueError("queued panel submission requires project_name and user_id")
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    async def _complete(result: ApiResult[Any], frozen: Any) -> None:
        persist_panel_result_provenance(
            output_path=output_path,
            request=request,
            request_id=frozen.request_id,
            result=result,
            project_dir=project_dir,
        )

    async def _failure(error: BaseException, frozen: Any) -> None:
        persist_panel_result_provenance(
            output_path=output_path,
            request=request,
            request_id=frozen.request_id,
            error=error,
            project_dir=project_dir,
        )

    job, created = enqueue_frozen_generation_job(
        app,
        project_name=project_name,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        config=config,
        stage=stage,
        kind=kind,
        label=label or kind,
        payload=payload or {},
        wire=request.wire,
        output_path=output_path,
        debit_description=debit_description,
        idempotency_key=idempotency_key,
        feature=feature,
        semaphore=semaphore,
        estimate_credits=estimate_credits,
        on_complete=_complete,
        on_failure=_failure,
    )
    return PanelSubmission(
        request_id=job.payload.get("frozen_request_id"),
        execution_fingerprint=request.wire.execution_fingerprint,
        job=job,
        created=created,
    )


__all__ = [
    "PANEL_PROVENANCE_SCHEMA_VERSION",
    "PanelEstimate",
    "PanelRequest",
    "PanelSubmission",
    "compile_panel_request",
    "estimate_panel_request",
    "panel_provenance",
    "panel_failure_provenance",
    "persist_panel_result_provenance",
    "apply_panel_experiment",
    "wire_provenance",
    "prepare_panel_request",
    "prepare_panel_prompt",
    "resolve_panel_references",
    "submit_panel_request",
]
