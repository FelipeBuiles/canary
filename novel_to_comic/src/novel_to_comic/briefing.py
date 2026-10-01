"""Revision and approval behavior for target adaptation briefs."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, ConfigDict

from novel_to_comic.narrative_instructions import BRIEF_DEPICTION_GUIDANCE
from novel_to_comic.models.adaptation import AdaptationBrief
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.models.story_bible import StoryBible, story_bible_context
from novel_to_comic.target_artifacts import TargetArtifacts

logger = logging.getLogger("canary.briefing")


def recommended_page_envelope(
    *,
    word_count: int,
    scene_count: int,
) -> tuple[int, int]:
    """Return a stable initial editorial range for Brief inference.

    The range is deliberately a recommendation rather than a downstream
    capacity limit. It keeps an unconstrained model from confusing source
    units or prose pages with comic pages while leaving the draft editable.
    """

    words = max(1, word_count)
    scenes = max(1, scene_count)
    minimum = max(scenes * 2, (words + 399) // 400)
    maximum = max(minimum, scenes * 4, (words + 249) // 250)
    return minimum, maximum


def story_page_envelope(
    source: SourceDocument,
    story_bible: StoryBible,
) -> tuple[int, int]:
    return recommended_page_envelope(
        word_count=len(source.text.split()),
        scene_count=len(story_bible.scenes),
    )


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

    page_minimum, page_maximum = story_page_envelope(source, story_bible)
    context = {
        "source_sha256": source.source_sha256,
        "recommended_page_envelope": {
            "minimum": page_minimum,
            "maximum": page_maximum,
        },
        "source_units": [
            unit.model_dump(mode="json", include={"id", "text"})
            for unit in source.units
        ],
        "source_scenes": [
            scene.model_dump(mode="json")
            for scene in source.scenes
        ],
        "story_bible": story_bible_context(story_bible),
    }
    return (
        "Infer an adaptation brief from the canonical source units and Story Bible. "
        "Return one JSON object containing story_promises, themes, point_of_view, "
        "narrator_treatment, tone, ambiguities, motifs, protected_language, "
        "essential_events, character_turns, transformation_level, "
        "desired_emphasis, target_page_min, and target_page_max. "
        "story_promises, themes, ambiguities, motifs, protected_language, "
        "essential_events, character_turns, and desired_emphasis are arrays of "
        "plain strings, never objects. Write character_turns as sentences naming "
        "the character and their change. point_of_view, narrator_treatment, and "
        "tone are plain strings. transformation_level is exactly one of "
        "'faithful', 'medium_specific', or 'transformative'. target_page_min and "
        "target_page_max are positive integers, with min <= max. "
        "The context contains a calibrated recommended_page_envelope. Both "
        "target_page_min and target_page_max MUST remain inside that envelope. "
        "Choose a useful editorial range within it; it is an editable narrative "
        "recommendation, not a page-allocation or layout decision. Do not equate "
        "source units, sentences, paragraphs, or prose pages with comic pages, "
        "and do not assign one page per source unit. "
        "Do not return approval status or revision metadata. "
        + BRIEF_DEPICTION_GUIDANCE
        + "\n"
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
    return propose_brief(
        inferred_content,
        page_envelope=story_page_envelope(source, story_bible),
    )


_LIST_FIELDS = (
    "story_promises",
    "themes",
    "ambiguities",
    "motifs",
    "protected_language",
    "essential_events",
    "character_turns",
    "desired_emphasis",
)
_TEXT_FIELDS = ("point_of_view", "narrator_treatment", "tone")
_TRANSFORMATION_LEVELS = ("faithful", "medium_specific", "transformative")
_AUTHORED_FIELDS = ("revision", "status", "content_sha256")


def _transformation_level(described: str) -> str:
    """Map a described transformation level onto the contract's vocabulary.

    The brief is a draft the Story station presents for approval, so reading the
    model's own word is better than discarding what it said — the user sees the
    result and can change it.
    """

    text = described.casefold()
    if "transformative" in text or "reinvent" in text:
        return "transformative"
    if "faithful" in text:
        return "faithful"
    return "medium_specific"


def normalize_inferred_brief(
    inferred_content: Mapping[str, Any],
    /,
    *,
    page_envelope: tuple[int, int] | None = None,
) -> dict[str, Any]:
    """Repair shape slips in inferred brief content without inventing intent.

    A model asked for a list routinely returns one string, and asked for an enum
    returns a sentence describing it. Those are formatting mistakes, not missing
    creative intent, so they are corrected here rather than costing the user a
    failed stage.
    """

    allowed = set(AdaptationBrief.model_fields) - set(_AUTHORED_FIELDS)
    normalized = {
        key: value for key, value in inferred_content.items() if key in allowed
    }
    for field in _LIST_FIELDS:
        value = normalized.get(field)
        if isinstance(value, str):
            normalized[field] = (value,) if value.strip() else ()
    for field in _TEXT_FIELDS:
        value = normalized.get(field)
        if isinstance(value, (list, tuple)):
            normalized[field] = "; ".join(
                str(item).strip() for item in value if str(item).strip()
            )
    level = normalized.get("transformation_level")
    if isinstance(level, str) and level not in _TRANSFORMATION_LEVELS:
        normalized["transformation_level"] = _transformation_level(level)
        logger.info(
            "Inferred transformation_level %r read as %r",
            level,
            normalized["transformation_level"],
        )
    if page_envelope is not None:
        inferred_minimum = normalized.get("target_page_min")
        inferred_maximum = normalized.get("target_page_max")
        envelope_minimum, envelope_maximum = page_envelope
        if (
            isinstance(inferred_minimum, int)
            and not isinstance(inferred_minimum, bool)
            and isinstance(inferred_maximum, int)
            and not isinstance(inferred_maximum, bool)
            and (
                inferred_minimum < envelope_minimum
                or inferred_maximum > envelope_maximum
                or inferred_minimum > inferred_maximum
            )
        ):
            logger.warning(
                "Inferred page range %d-%d fell outside recommended envelope "
                "%d-%d; using the envelope without another model call",
                inferred_minimum,
                inferred_maximum,
                envelope_minimum,
                envelope_maximum,
            )
            normalized["target_page_min"] = envelope_minimum
            normalized["target_page_max"] = envelope_maximum
    return normalized


def propose_brief(
    inferred_content: Mapping[str, Any],
    /,
    *,
    page_envelope: tuple[int, int] | None = None,
) -> AdaptationBrief:
    """Parse inferred adaptation intent without allowing inference to approve it."""

    return AdaptationBrief.model_validate(
        {
            **normalize_inferred_brief(
                inferred_content,
                page_envelope=page_envelope,
            ),
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
