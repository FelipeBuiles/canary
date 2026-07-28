"""Active book-level Adapt stage."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.book_adaptation import (
    build_narrative_treatment_prompt,
    produce_book_adaptation,
)
from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost

from novel_to_comic.stages import Stage, clean_cascade


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    target = TargetArtifacts(project_dir)
    model = config.effective_adapt_model()

    async def generate(**kwargs):
        return await generate_json(config=config, model=model, **kwargs)

    return await produce_book_adaptation(
        target.read_source(),
        artifacts.read_story_bible(project_dir),
        target.read_brief(),
        artifacts=target,
        ctx=ctx,
        model=model,
        generate=generate,
    )


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
    prompt = build_narrative_treatment_prompt(source, bible, brief)
    return estimate_text_cost(
        config.effective_adapt_model(),
        prompt,
        output_chars=max(12_000, len(source.text) * 3),
    )


STAGE = Stage(
    name="adapt",
    run=run,
    outputs=lambda d: [TargetArtifacts(d).adaptation_path],
    clean_paths=lambda d: clean_cascade(d, "adapt"),
    estimate_cost=estimate_cost,
)
