"""Application operations independent of HTTP routing."""

from __future__ import annotations
from novel_to_comic.cast_instructions import (
    AssetType,
    resolve_cast_asset,
    validate_user_instruction,
    asset_regen_label,
    _ASSET_TYPES,
)
from novel_to_comic.config import Config
from pathlib import Path
from typing import Any
from novel_to_comic.cast_reference_inputs import (
    CastReferenceInput,
    resolve_reference_inputs,
    saved_reference_inputs,
)
from novel_to_comic.codex_dev import classify_operations
from novel_to_comic.server.codex_admission import (
    cast_asset_operations,
    prompt_image_operations,
)


async def apply_asset_instruction(
    config: Config,
    project_dir: Path,
    db: Any,
    user_id: str,
    project_id: str,
    asset_type: AssetType,
    asset_id: str,
    instruction: str,
    app: Any | None = None,
    state_id: str | None = None,
    reference_assets: list[CastReferenceInput] | None = None,
) -> dict[str, Any]:
    """Admit one correction; the reserved job owns both rewrite and image work."""
    from fastapi import HTTPException

    from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
    from novel_to_comic.server.credits import UnifiedCostResolver
    from novel_to_comic.server.generation_jobs import (
        find_active_generation_job,
        generation_job_payload,
        generation_semaphore_for_config,
    )

    classify_operations(prompt_image_operations(config))
    instruction = validate_user_instruction(instruction)
    asset_id = asset_id.strip()
    resolve_cast_asset(project_dir, asset_type, asset_id, state_id)
    if asset_type == "character":
        from novel_to_comic.stages.s3_cast import require_character_inputs
        from novel_to_comic.target_artifacts import ArtifactInvalid

        try:
            require_character_inputs(
                config, project_dir, asset_id, state=bool(state_id)
            )
        except (ValueError, ArtifactInvalid) as exc:
            raise HTTPException(409, str(exc)) from exc
    attachments = (
        reference_assets
        if reference_assets is not None
        else saved_reference_inputs(project_dir, asset_type, asset_id, state_id)
    )
    if len(attachments) > 3:
        raise HTTPException(400, "Choose at most three reference images.")
    refs = resolve_reference_inputs(
        project_dir, attachments, target=(asset_type, asset_id, state_id)
    )
    if refs:
        from novel_to_comic.image_models import image_model_profile_for_config
        from novel_to_comic.stages.s3_cast import estimate_state_reference_count

        profile = image_model_profile_for_config(config)
        # Reserve the style slot even if its image is currently missing. Required
        # identity and style references must never be displaced by attachments.
        base_count = (
            estimate_state_reference_count(
                config, project_dir, asset_type, asset_id, state_id
            )
            if state_id
            else 1
        )
        if base_count + len(refs) > profile.max_references:
            raise HTTPException(
                400,
                f"Too many reference images for this model (limit {profile.max_references}). Remove a reference image.",
            )
        if any(ref.role not in profile.supported_roles for ref in refs):
            raise HTTPException(
                400, "This model does not support the selected reference type."
            )
    ref_kind, job_kind, payload_key, feature = _ASSET_TYPES[asset_type]
    job_asset_id = f"{asset_id}:{state_id}" if state_id else asset_id
    pkey = f"{user_id}:{project_id}"
    identity = {payload_key: job_asset_id}
    if find_active_generation_job(app, pkey, job_kind, identity):
        raise HTTPException(
            409,
            f"A regeneration is already queued or running for this {asset_type}",
        )
    asset_estimate = UnifiedCostResolver.estimate_asset_regen_cost(
        config,
        project_dir,
        job_kind,
        job_asset_id,
        additional_reference_count=len(attachments),
    )
    estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
        config, asset_estimate, "cast"
    )

    from novel_to_comic.server.job_commands import command

    descriptor = command(
        "cast_instruction",
        project_dir,
        config,
        asset_type=asset_type,
        asset_id=asset_id,
        instruction=instruction,
        state_id=state_id,
        attachments=[item.model_dump(mode="json") for item in attachments],
    )

    job, _created = await enqueue_reserved_generation_job(
        app,
        project_name=pkey,
        kind=job_kind,
        label=asset_regen_label(asset_type, asset_id, state_id),
        payload={
            **identity,
            "instruction": instruction,
            "reference_assets": [item.model_dump() for item in attachments],
        },
        command=descriptor,
        project_id=project_id,
        project_dir=project_dir,
        stage="cast",
        reservation_credits=estimate["estimate_credits"],
        operations=(
            ("text", config.effective_prompt_model()),
            *cast_asset_operations(config, job_kind, job_asset_id),
        ),
        debit_description=f"Model call: regenerate instructed {asset_type} {asset_id}",
        user_id=user_id,
        semaphore=generation_semaphore_for_config(app, config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(app, job),
        payload_key: asset_id,
    }
