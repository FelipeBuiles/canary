"""Quote, admit and execute one Cast reference regeneration.

Plain and instructed regeneration take the same ``CastTarget``, share one quote,
and differ only in the instruction they carry and in what a duplicate does.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException

from novel_to_comic.cast_instructions import resolve_cast_asset, validate_user_instruction
from novel_to_comic.cast_reference_inputs import (
    CastReferenceInput,
    resolve_reference_inputs,
    saved_reference_inputs,
)
from novel_to_comic.cast_target import CastTarget
from novel_to_comic.codex_dev import classify_operations
from novel_to_comic.config import Config
from novel_to_comic.server.codex_admission import (
    cast_asset_operations,
    prompt_image_operations,
)

if TYPE_CHECKING:
    from novel_to_comic.server.credits import CreditEstimate


class DuplicateRegen(enum.Enum):
    """What asking again does while the same target's job is queued or running.

    ``RETURN_EXISTING`` lets credited admission hand back the active job;
    ``REJECT`` refuses with 409 before any estimate.
    """

    RETURN_EXISTING = "return_existing"
    REJECT = "reject"


PLAIN_DUPLICATE = DuplicateRegen.RETURN_EXISTING
INSTRUCTED_DUPLICATE = DuplicateRegen.REJECT


def _apply_duplicate_policy(app: FastAPI, pkey: str, target: CastTarget, policy: DuplicateRegen) -> None:
    from novel_to_comic.server.generation_jobs import find_active_generation_job

    if policy is DuplicateRegen.REJECT and find_active_generation_job(
            app, pkey, target.job_kind, target.job_identity):
        raise HTTPException(
            409,
            f"A regeneration is already queued or running for this {target.asset_type}",
        )


@dataclass(frozen=True)
class CastRegenQuote:
    """The image estimate for a target, plus the looks a main redraw would bring along."""

    asset_estimate: CreditEstimate
    looks: dict[str, Any] | None


def looks_admission(config: Config, project_dir: Path, target: CastTarget) -> dict[str, Any]:
    """What redrawing an entity's looks with its main image adds to one job.

    Returns the look ids, their summed credit estimate and their operations, so
    the job reserves for every image it may make before anything is spent.
    """
    from novel_to_comic.server.credits import UnifiedCostResolver
    from novel_to_comic.stages.s3_cast import entity_look_ids

    look_ids = (entity_look_ids(project_dir, target.asset_type, target.entity_id)
                if target.asset_type != "prop" else [])
    credits, operations = 0, []
    for look_id in look_ids:
        look = target.with_state(look_id)
        credits += UnifiedCostResolver.estimate_asset_regen_cost(
            config, project_dir, look)["estimate_credits"]
        operations.extend(cast_asset_operations(config, look))
    return {"look_ids": look_ids, "estimate_credits": credits, "operations": tuple(operations)}


def quote_cast_regen(
    config: Config,
    project_dir: Path,
    target: CastTarget,
    *,
    reference_count: int | None = None,
    with_looks: bool = False,
) -> CastRegenQuote:
    from novel_to_comic.server.credits import UnifiedCostResolver

    asset_estimate = UnifiedCostResolver.estimate_asset_regen_cost(
        config, project_dir, target, additional_reference_count=reference_count)
    looks = None
    if with_looks and target.is_canonical:
        looks = looks_admission(config, project_dir, target)
        if not looks["look_ids"]:
            looks = None
    return CastRegenQuote(asset_estimate, looks)


def _require_character_inputs(config: Config, project_dir: Path, target: CastTarget) -> None:
    if target.asset_type != "character":
        return
    from novel_to_comic.stages.s3_cast import require_character_inputs
    from novel_to_comic.target_artifacts import ArtifactInvalid

    try:
        require_character_inputs(
            config, project_dir, target.entity_id, state=bool(target.state_id))
    except (ValueError, ArtifactInvalid) as exc:
        raise HTTPException(409, str(exc)) from exc


async def submit_cast_regen(
    app: FastAPI,
    config: Config,
    project_dir: Path,
    user_id: str,
    project_id: str,
    target: CastTarget,
    *,
    with_looks: bool = False,
) -> dict[str, Any]:
    """Admit a plain redraw. A second request for the same target joins the first job."""
    from novel_to_comic.server.credited_job import enqueue_credited_job
    from novel_to_comic.server.deps import project_key
    from novel_to_comic.server.generation_jobs import (
        generation_job_payload,
        generation_semaphore_for_config,
    )
    from novel_to_comic.server.job_commands import command

    resolve_cast_asset(project_dir, target.asset_type, target.entity_id, target.state_id)
    _require_character_inputs(config, project_dir, target)
    # Each regen calls the image model for real and is debited on success. A
    # positive estimate also makes enqueue_credited_job block zero-balance users.
    pkey = project_key(user_id, project_id)
    _apply_duplicate_policy(app, pkey, target, PLAIN_DUPLICATE)
    quote = quote_cast_regen(config, project_dir, target, with_looks=with_looks)
    looks = quote.looks
    subject = (f"{target.entity_id}/{target.state_id}" if target.state_id else target.entity_id)
    noun = {"character": "appearance state" if target.state_id else "character ref",
            "location": "location state" if target.state_id else "location plate",
            "prop": "prop ref"}[target.asset_type]
    job, _created = await enqueue_credited_job(
        app,
        project_name=pkey,
        user_id=user_id,
        project_id=project_id,
        project_dir=project_dir,
        stage="cast",
        kind=target.job_kind,
        label=target.label,
        payload={**target.job_identity, **({"with_looks": looks["look_ids"]} if looks else {})},
        command=command("cast_asset", project_dir, config, kind=target.job_kind,
                        asset_id=target.job_asset_id, with_looks=looks is not None),
        debit_description=f"Model call: regenerate {noun} {subject}",
        semaphore=generation_semaphore_for_config(app, config),
        estimate_credits=quote.asset_estimate["estimate_credits"] + (looks["estimate_credits"] if looks else 0),
        operations=(*cast_asset_operations(config, target), *(looks["operations"] if looks else ())),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(app, job),
        target.payload_key: target.job_asset_id,
    }


async def submit_instructed_regen(
    app: FastAPI,
    config: Config,
    project_dir: Path,
    user_id: str,
    project_id: str,
    target: CastTarget,
    instruction: str,
    reference_assets: list[CastReferenceInput] | None = None,
    with_looks: bool = False,
) -> dict[str, Any]:
    """Admit one correction; the reserved job owns both rewrite and image work."""
    from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
    from novel_to_comic.server.deps import project_key
    from novel_to_comic.server.credits import UnifiedCostResolver
    from novel_to_comic.server.generation_jobs import (
        generation_job_payload,
        generation_semaphore_for_config,
    )

    classify_operations(prompt_image_operations(config))
    instruction = validate_user_instruction(instruction)
    target = replace(target, entity_id=target.entity_id.strip())
    resolve_cast_asset(project_dir, target.asset_type, target.entity_id, target.state_id)
    _require_character_inputs(config, project_dir, target)
    attachments = (
        reference_assets
        if reference_assets is not None
        else saved_reference_inputs(project_dir, target.asset_type, target.entity_id, target.state_id)
    )
    if len(attachments) > 3:
        raise HTTPException(400, "Choose at most three reference images.")
    refs = resolve_reference_inputs(
        project_dir, attachments, target=(target.asset_type, target.entity_id, target.state_id)
    )
    if refs:
        from novel_to_comic.image_models import image_model_profile_for_config
        from novel_to_comic.stages.s3_cast import estimate_state_reference_count

        profile = image_model_profile_for_config(config)
        # Reserve the style slot even if its image is currently missing. Required
        # identity and style references must never be displaced by attachments.
        base_count = (
            estimate_state_reference_count(
                config, project_dir, target.asset_type, target.entity_id, target.state_id)
            if target.state_id
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
    pkey = project_key(user_id, project_id)
    _apply_duplicate_policy(app, pkey, target, INSTRUCTED_DUPLICATE)
    quote = quote_cast_regen(
        config, project_dir, target, reference_count=len(attachments),
        with_looks=with_looks)
    looks = quote.looks
    estimate = UnifiedCostResolver.estimate_instructed_regen_cost(
        config, quote.asset_estimate, "cast"
    )

    from novel_to_comic.server.job_commands import command

    descriptor = command(
        "cast_instruction",
        project_dir,
        config,
        asset_type=target.asset_type,
        asset_id=target.entity_id,
        instruction=instruction,
        state_id=target.state_id,
        attachments=[item.model_dump(mode="json") for item in attachments],
        with_looks=looks is not None,
    )

    job, _created = await enqueue_reserved_generation_job(
        app,
        project_name=pkey,
        kind=target.job_kind,
        label=target.label,
        payload={
            **target.job_identity,
            "instruction": instruction,
            "reference_assets": [item.model_dump() for item in attachments],
            **({"with_looks": looks["look_ids"]} if looks else {}),
        },
        command=descriptor,
        project_id=project_id,
        project_dir=project_dir,
        stage="cast",
        reservation_credits=estimate["estimate_credits"] + (looks["estimate_credits"] if looks else 0),
        operations=(
            ("text", config.effective_prompt_model()),
            *cast_asset_operations(config, target),
            *(looks["operations"] if looks else ()),
        ),
        debit_description=f"Model call: regenerate instructed {target.asset_type} {target.entity_id}",
        user_id=user_id,
        semaphore=generation_semaphore_for_config(app, config),
    )
    return {
        "status": "queued",
        "job": generation_job_payload(app, job),
        target.payload_key: target.entity_id,
    }
