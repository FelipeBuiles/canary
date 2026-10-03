"""Active Brief stage for the full-page pipeline."""

from __future__ import annotations

import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.briefing import (
    brief_inference_schema,
    build_brief_inference_prompt,
    inherited_brief_fields,
    propose_brief,
    series_brief,
    story_page_envelope,
)
from novel_to_comic.clients.structured_call import (
    StructuredCallError,
    generate_validated_json,
    validation_error_summary,
)
from novel_to_comic.book_context import book_context
from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost
from novel_to_comic.workspace import workspace_part_id

from novel_to_comic.stages import Stage


def _inference_prompt(project_dir: Path):
    """The part's source, its Brief prompt, page envelope and inherited fields."""
    target = TargetArtifacts(project_dir)
    source = target.read_source()
    story_bible = artifacts.read_story_bible(project_dir)
    part = workspace_part_id(project_dir)
    previous = series_brief(project_dir)
    prompt = build_brief_inference_prompt(source, story_bible, part_id=part, previous_brief=previous,
                                          book=book_context(project_dir))
    page_envelope = story_page_envelope(source, story_bible, part_id=part)
    inherited = inherited_brief_fields(previous) if previous is not None else None
    return prompt, page_envelope, inherited


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    target = TargetArtifacts(project_dir)
    prompt, page_envelope, inherited = _inference_prompt(project_dir)
    model = config.effective_brief_model()
    schema = brief_inference_schema(inherited=inherited)
    estimate = estimate_text_cost(model, prompt + json.dumps(schema), output_chars=8_000)

    def parse(raw: object):
        return propose_brief(raw, page_envelope=page_envelope, inherited=inherited)

    def correction(raw: object, error: Exception) -> str:
        # Provider traces can truncate before the validation feedback. Keep the
        # rejection reason in the existing opt-in project diagnostic journal.
        from novel_to_comic.server.diagnostics import record_diagnostic

        record_diagnostic(
            project_dir, "structured_response_rejected", stage="brief",
            feature="brief.infer", model=model,
            message=validation_error_summary(error), status="retrying",
        )
        # Shape slips are repaired deterministically in propose_brief; anything
        # still invalid needs the model, so it gets the exact errors rather than
        # costing the user the whole stage.
        return (
            f"{prompt}\n\nYour previous response did not satisfy the adaptation "
            "brief contract. Return one corrected JSON object; use exactly one of "
            "'faithful', 'medium_specific', or 'transformative' for "
            "transformation_level, and JSON arrays of strings for every list "
            f"field.\n\nYOUR PREVIOUS JSON:\n{json.dumps(raw, indent=2, default=str)}"
            f"\n\nVALIDATION ERRORS:\n{error}"
        )

    with ctx.execute(total=1, estimated_cost_usd=estimate):
        try:
            outcome = await generate_validated_json(
                config,
                model=model,
                system_prompt=(
                    "Infer the adaptation brief. Return only the requested JSON object."
                ),
                user_content=prompt,
                parse=parse,
                correction=correction,
                label="Adaptation brief inference",
                feature="brief.infer",
                json_schema=schema,
            )
        except StructuredCallError as exc:
            raise exc.last_error from exc
        brief = outcome.value
        target.write_brief(brief)
        for retry_usage in outcome.usage_records[:-1]:
            ctx.record_api_usage(retry_usage)
        ctx.record_item_done(
            usage=outcome.usage_records[-1] if outcome.usage_records else None
        )
        ctx.progress(1, 1)
    return brief


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.source_path.exists() or not artifacts.story_bible_path(project_dir).exists():
        return 0.0
    prompt, _envelope, inherited = _inference_prompt(project_dir)
    return estimate_text_cost(
        config.effective_brief_model(),
        prompt + json.dumps(brief_inference_schema(inherited=inherited)),
        output_chars=8_000,
    )


STAGE = Stage(
    name="brief",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).brief_path],
    clean_paths=lambda d: [
        d / "brief",
        d / "adapt",
        d / "plan",
        d / "draw",
        d / "finish",
        d / "exports",
    ],
    estimate_cost=estimate_cost,
)
