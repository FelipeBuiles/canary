"""Isolate older allocation/schema tests from new editorial model judgments.

These fixtures still exercise real review parsing, caching and receipt storage.
Dedicated narrative-review tests supply adversarial and repairing responses.
"""

from novel_to_comic.narrative_review import review_narrative, narrative_signals
from novel_to_comic.usage import ApiResult


async def accept_narrative(context, **kwargs):
    async def reviewer(**request):
        return ApiResult(
            value={
                "findings": [],
                "signal_assessments": [
                    {
                        "signal_id": s["id"],
                        "acceptable": True,
                        "evidence": "Intentional visual sequence in this isolated allocation fixture.",
                    }
                    for s in narrative_signals(context)
                ],
            }
        )

    return await review_narrative(context, **{**kwargs, "generate": reviewer})


def approve_recovery_candidate(artifacts, source, bible, brief, candidate):
    import asyncio
    from datetime import datetime, timezone
    from novel_to_comic.book_adaptation import _canonicalize_candidate_requirements
    from novel_to_comic.narrative_review import adaptation_context
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import PipelineState

    canonical = _canonicalize_candidate_requirements(
        candidate, source, brief, story_bible=bible
    )
    ctx = StageRuntime(
        "adapt",
        PipelineState(
            project_name="review-fixture",
            novel_path="novel.txt",
            created_at=datetime.now(timezone.utc),
        ),
        artifacts.project_dir,
    )
    asyncio.run(
        accept_narrative(
            adaptation_context(source, brief, canonical),
            artifacts=artifacts,
            ctx=ctx,
            model="test-editor",
        )
    )
