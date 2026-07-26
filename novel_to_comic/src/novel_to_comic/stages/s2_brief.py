"""Active Brief stage for the full-page pipeline."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.briefing import build_brief_inference_prompt, propose_brief
from novel_to_comic.clients.text import generate_json
from novel_to_comic.config import Config
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import PipelineState
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import estimate_text_cost

from novel_to_comic.stages import Stage


async def run(config: Config, project_dir: Path, ctx: StageRuntime):
    target = TargetArtifacts(project_dir)
    source = target.read_source()
    story_bible = artifacts.read_story_bible(project_dir)
    prompt = build_brief_inference_prompt(source, story_bible)
    model = config.effective_extraction_model()
    estimate = estimate_text_cost(model, prompt, output_chars=8_000)
    with ctx.execute(total=1, estimated_cost_usd=estimate):
        result = await generate_json(
            config,
            model,
            "Infer the adaptation brief. Return only the requested JSON object.",
            prompt,
            feature="brief.infer",
        )
        brief = propose_brief(result.value)
        target.write_brief(brief)
        ctx.record_item_done(usage=result.usage)
        ctx.progress(1, 1)
    return brief


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    target = TargetArtifacts(project_dir)
    if not target.source_path.exists() or not artifacts.story_bible_path(project_dir).exists():
        return 0.0
    prompt = build_brief_inference_prompt(
        target.read_source(),
        artifacts.read_story_bible(project_dir),
    )
    return estimate_text_cost(
        config.effective_extraction_model(),
        prompt,
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
