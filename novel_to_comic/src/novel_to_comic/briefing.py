"""Revision and approval behavior for target adaptation briefs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from novel_to_comic.models.adaptation import AdaptationBrief
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.target_artifacts import TargetArtifacts


class StoryDecision(BaseModel):
    """The Story station's single review and approval contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    story_bible: StoryBible
    brief: AdaptationBrief


def build_brief_inference_prompt(
    source: SourceDocument,
    story_bible: StoryBible,
) -> str:
    """Compile the target Brief inference contract from canonical Story inputs."""

    context = {
        "source_sha256": source.source_sha256,
        "source_units": [
            unit.model_dump(mode="json")
            for unit in source.units
        ],
        "source_scenes": [
            scene.model_dump(mode="json")
            for scene in source.scenes
        ],
        "story_bible": story_bible.model_dump(mode="json"),
    }
    return (
        "Infer an adaptation brief from the canonical source units and Story Bible. "
        "Return one JSON object containing story_promises, themes, point_of_view, "
        "narrator_treatment, tone, ambiguities, motifs, protected_language, "
        "essential_events, character_turns, transformation_level, "
        "desired_emphasis, target_page_min, and target_page_max. "
        "Do not return approval status or revision metadata.\n"
        + json.dumps(
            context,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


async def infer_brief(
    source: SourceDocument,
    story_bible: StoryBible,
    /,
    *,
    infer: Callable[[str], Awaitable[Mapping[str, Any]]],
) -> AdaptationBrief:
    """Produce a validated draft through an injected model adapter."""

    inferred_content = await infer(build_brief_inference_prompt(source, story_bible))
    return propose_brief(inferred_content)


def propose_brief(inferred_content: Mapping[str, Any], /) -> AdaptationBrief:
    """Parse inferred adaptation intent without allowing inference to approve it."""

    return AdaptationBrief.model_validate(
        {
            **inferred_content,
            "revision": 1,
            "status": "draft",
            "content_sha256": "",
        }
    )


def _reject_stale_revision(
    brief: AdaptationBrief,
    expected_revision: int,
) -> None:
    if expected_revision != brief.revision:
        raise ValueError(
            "stale adaptation brief revision: "
            f"expected {expected_revision}, current revision is {brief.revision}"
        )


def revise_brief(
    brief: AdaptationBrief,
    /,
    *,
    expected_revision: int,
    **changes: Any,
) -> AdaptationBrief:
    """Create a new non-authoritative brief revision with authored changes."""

    _reject_stale_revision(brief, expected_revision)
    payload = brief.model_dump()
    payload.update(changes)
    payload.update(
        revision=brief.revision + 1,
        status="draft",
        content_sha256="",
    )
    return AdaptationBrief.model_validate(payload)


def revise_persisted_brief(
    artifacts: TargetArtifacts,
    /,
    *,
    expected_revision: int,
    **changes: Any,
) -> AdaptationBrief:
    """Persist a stale-safe edit and remove every artifact derived from Brief."""

    revised = revise_brief(
        artifacts.read_brief(),
        expected_revision=expected_revision,
        **changes,
    )
    artifacts.invalidate_after_brief()
    artifacts.write_brief(revised)
    return revised


def revise_story(
    decision: StoryDecision,
    /,
    *,
    expected_revision: int,
    story_bible: StoryBible | None = None,
    **brief_changes: Any,
) -> StoryDecision:
    """Create one revised Story decision and return it to draft review."""

    return StoryDecision(
        story_bible=(
            decision.story_bible
            if story_bible is None
            else story_bible
        ),
        brief=revise_brief(
            decision.brief,
            expected_revision=expected_revision,
            **brief_changes,
        ),
    )


def approve_brief(
    brief: AdaptationBrief,
    /,
    *,
    expected_revision: int,
) -> AdaptationBrief:
    """Approve the current draft, rejecting an editor based on stale content."""

    _reject_stale_revision(brief, expected_revision)
    if brief.status != "draft":
        raise ValueError("approval requires a draft adaptation brief")
    return AdaptationBrief.model_validate(
        {
            **brief.model_dump(),
            "revision": brief.revision + 1,
            "status": "approved",
            "content_sha256": "",
        }
    )


def approve_story(
    decision: StoryDecision,
    /,
    *,
    expected_revision: int,
) -> StoryDecision:
    """Approve the Story Bible and current Brief through one decision."""

    return StoryDecision(
        story_bible=decision.story_bible,
        brief=approve_brief(
            decision.brief,
            expected_revision=expected_revision,
        ),
    )


def require_approved_brief(brief: AdaptationBrief, /) -> AdaptationBrief:
    """Return authoritative Brief input or block Adapt before work begins."""

    if brief.status != "approved":
        raise ValueError("Adapt requires an approved adaptation brief")
    return brief
