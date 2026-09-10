"""Active book-level Adapt stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.book_adaptation import (
    estimate_book_adaptation_cost,
    produce_book_adaptation,
)
from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.stages import Stage, clean_cascade


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    from novel_to_comic.editorial import (
        load_story_directive,
        mark_story_change_applied,
    )

    target = TargetArtifacts(project_dir)
    # An explicitly applied story change travels as a retained directive: it
    # is validated before any paid call, stays in place when generation
    # fails so the user can retry explicitly, and is cleared only after the
    # regenerated artifact is persisted. Nothing here retries paid work.
    directive = load_story_directive(target, "adapt")
    instruction = directive.instruction if directive is not None else ""
    if directive is not None:
        # A failed candidate from an earlier run predates the approved
        # revision; recovering it would publish stale story while marking the
        # change applied. Regenerate from the instruction instead.
        target.clear_failed_adaptation_candidate()
    model = config.effective_adapt_model()

    async def generate(**kwargs):
        return await generate_json(
            config=config,
            model=model,
            # Preserve expressive adaptation while reducing structural variance
            # that otherwise turns into paid schema and invariant repairs.
            temperature=0.6,
            **kwargs,
        )

    result = await produce_book_adaptation(
        target.read_source(),
        artifacts.read_story_bible(project_dir),
        target.read_brief(),
        artifacts=target,
        ctx=ctx,
        model=model,
        generate=generate,
        story_instruction=instruction,
    )
    if directive is not None:
        target.clear_story_directive("adapt")
        mark_story_change_applied(target, directive.proposal_id)
    return result


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not all(
        path.exists()
        for path in (
            target.source_path,
            target.brief_path,
            artifacts.story_bible_path(project_dir),
        )
    ):
        return 0.0
    source = target.read_source()
    brief = target.read_brief()
    bible = artifacts.read_story_bible(project_dir)
    directive = target.peek_story_directive("adapt")
    return estimate_book_adaptation_cost(
        source,
        bible,
        brief,
        model=config.effective_adapt_model(),
        story_instruction=directive.instruction if directive is not None else "",
    )


STAGE = Stage(
    name="adapt",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).adaptation_path],
    clean_paths=lambda d: clean_cascade(d, "adapt"),
    estimate_cost=estimate_cost,
)
