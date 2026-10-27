"""The two model calls an author's carried note may need.

``revise_beats`` rewrites the beats a story note names, keeping their place
and source passages; ``check_fact`` asks whether one page's current art
breaks a look fact. Callers price, fund and validate both; neither writes
artifacts.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import AdaptedBeat, BookAdaptation, LetteringItem
from novel_to_comic.models.page import ApprovedVisualReferenceInventory, ComicPage
from novel_to_comic.models.source import SourceDocument
from novel_to_comic.note_scope import NoteScopeError
from novel_to_comic.usage import ApiResult, estimate_text_cost

BEAT_FEATURE = "notes.beat_revision"
FACT_FEATURE = "notes.fact_check"
_IMAGE_PROMPT_CHARS = 4_400
_OUTPUT_CHARS_PER_BEAT = 1_800

_BEAT_SYSTEM = (
    "You revise a comic script's story beats to carry out an author's note. You change only "
    "what the note asks, keep the author's words where they are, and never invent story."
)
_FACT_SYSTEM = (
    "You check a comic page against one stated fact. You report only what is visible, and "
    "say the page is fine when you are unsure."
)


class _RevisedLine(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str | None = Field(default=None, description="Existing line id to keep, or null for a new line.")
    kind: Literal["dialogue", "thought", "caption", "sfx"]
    delivery: Literal["onscreen", "offscreen", "narration", "quoted_text", "display"]
    text: str = Field(min_length=1)
    speaker_entity_id: str | None = None
    speaker: str | None = None


class _RevisedBeat(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=1200)
    entity_ids: tuple[str, ...] = ()
    lettering: tuple[_RevisedLine, ...] = Field(default=(), max_length=16)


class _BeatRevisions(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    beats: tuple[_RevisedBeat, ...] = Field(min_length=1, max_length=6)


class FactReading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    breaks_fact: bool
    panels: tuple[int, ...] = ()
    evidence: str = Field(default="", max_length=400)


def _names(inventory: ApprovedVisualReferenceInventory) -> dict[str, str]:
    return {reference.entity_id: reference.label or reference.entity_id for reference in inventory.references
            if reference.appearance_state_id is None}


def beat_prompt(*, adaptation: BookAdaptation, source: SourceDocument, beat_ids: Sequence[str], note: str,
                inventory: ApprovedVisualReferenceInventory) -> str:
    order = {beat.id: index for index, beat in enumerate(adaptation.beats)}
    targets = [adaptation.beats[order[beat_id]] for beat_id in beat_ids]
    first, last = min(order[b] for b in beat_ids), max(order[b] for b in beat_ids)
    context = [beat.summary for beat in adaptation.beats[max(0, first - 2):first]]
    after = [beat.summary for beat in adaptation.beats[last + 1:last + 3]]
    units = {unit.id: unit.text for unit in source.units}
    passages = {unit_id: units[unit_id] for beat in targets for unit_id in beat.source_unit_ids if unit_id in units}
    names = _names(inventory)
    characters = {entity_id: names[entity_id] for entity_id in names
                  if any(reference.entity_id == entity_id and reference.kind == "character"
                         for reference in inventory.references)}
    return (
        "The author's note below names a story moment the comic gets wrong or leaves out. Revise only "
        "the listed beats so the moment reads clearly. Rules:\n"
        "- Return every listed beat, with its id. Its place in the story and its source passages stay "
        "the same.\n"
        "- Rewrite the summary to say what the reader must see. Add or remove entity_ids when the "
        "moment needs it; use only ids from the Story Bible list.\n"
        "- Keep every existing line with its id and exact wording unless the note asks to change it. "
        "Add a new line (id null) only when the note needs words; take them from the passages where "
        "you can.\n"
        "- Lines: dialogue or thought spoken by a visible character use delivery onscreen and that "
        "character's speaker_entity_id; an unseen voice uses offscreen with a speaker label and no "
        "id; narration is a caption with delivery narration; quoted prose is a caption with delivery "
        "quoted_text; sound effects are sfx with delivery display.\n\n"
        + json.dumps({
            "note": note.strip(),
            "before": context,
            "beats": [beat.model_dump(mode="json", include={"id", "summary", "entity_ids", "lettering"})
                      for beat in targets],
            "after": after,
            "passages": passages,
            "story_bible_characters": characters,
            "story_bible_entities": names,
        }, ensure_ascii=False)
    )


def estimate_beat_revision_cost(config: Config, prompt: str, beat_count: int) -> float:
    return estimate_text_cost(config.effective_adapt_model(), _BEAT_SYSTEM + prompt,
                              output_chars=_OUTPUT_CHARS_PER_BEAT * max(1, beat_count))


def _revised(beat: AdaptedBeat, draft: _RevisedBeat, names: dict[str, str], taken: set[str]) -> AdaptedBeat:
    existing = {item.id: item for item in beat.lettering}
    lettering = []
    for index, line in enumerate(draft.lettering, start=1):
        if line.id is not None and line.id in existing:
            item_id = line.id
        else:
            item_id = f"{beat.id}_note_{index:02d}"
            while item_id in taken:
                item_id += "x"
        taken.add(item_id)
        speaker_id = line.speaker_entity_id if line.delivery == "onscreen" else None
        lettering.append(LetteringItem(
            id=item_id, kind=line.kind, text=line.text.strip(), delivery=line.delivery,
            speaker_entity_id=speaker_id,
            speaker=(names.get(speaker_id) if speaker_id else (line.speaker or None))
            if line.kind in ("dialogue", "thought") else None,
            source_unit_ids=existing[item_id].source_unit_ids if item_id in existing else beat.source_unit_ids,
        ))
    return beat.model_copy(update={
        "summary": draft.summary.strip(),
        "entity_ids": tuple(dict.fromkeys(draft.entity_ids)),
        "lettering": tuple(lettering),
    })


async def revise_beats(*, config: Config, adaptation: BookAdaptation, source: SourceDocument,
                       beat_ids: Sequence[str], note: str, inventory: ApprovedVisualReferenceInventory,
                       generate=None) -> ApiResult[tuple[AdaptedBeat, ...]]:
    if generate is None:
        from novel_to_comic.clients.text import generate_json

        generate = generate_json
    result = await generate(
        config=config, model=config.effective_adapt_model(), system_prompt=_BEAT_SYSTEM,
        user_content=beat_prompt(adaptation=adaptation, source=source, beat_ids=beat_ids, note=note,
                                 inventory=inventory),
        temperature=0.2, feature=BEAT_FEATURE, json_schema=_BeatRevisions.model_json_schema(),
    )
    drafts = {draft.id: draft for draft in _BeatRevisions.model_validate(result.value).beats}
    if set(drafts) != set(beat_ids):
        raise NoteScopeError("The script revision didn't return exactly the beats it was given; try again.")
    names = _names(inventory)
    taken = {item.id for beat in adaptation.beats for item in beat.lettering}
    by_id = {beat.id: beat for beat in adaptation.beats}
    return ApiResult(
        value=tuple(_revised(by_id[beat_id], drafts[beat_id], names, taken) for beat_id in beat_ids),
        usage=result.usage,
    )


def fact_prompt(*, page: ComicPage, entity_name: str, fact: str) -> str:
    panels = [
        {"panel": content.order, "visual_intent": content.visual_intent}
        for content in sorted(page.content, key=lambda content: content.order)
    ]
    return (
        f"Image 1 is a comic page. The author states this fact about {entity_name}: \"{fact.strip()}\"\n"
        "Does any panel of the page visibly contradict it? Look only at panels that show "
        f"{entity_name}. If none does, or you can't tell, answer breaks_fact false. Otherwise list the "
        "panel numbers that contradict it and describe what you see in one short sentence.\n\n"
        + json.dumps({"panels": panels}, ensure_ascii=False)
    )


def estimate_fact_check_cost(config: Config, prompt: str) -> float:
    return estimate_text_cost(config.effective_correction_model(),
                              _FACT_SYSTEM + prompt + " " * _IMAGE_PROMPT_CHARS, output_chars=400)


async def check_fact(*, config: Config, page: ComicPage, image: bytes, entity_name: str, fact: str,
                     generate=None) -> ApiResult[FactReading]:
    if generate is None:
        from novel_to_comic.clients.text import generate_json

        generate = generate_json
    result = await generate(
        config=config, model=config.effective_correction_model(), system_prompt=_FACT_SYSTEM,
        user_content=fact_prompt(page=page, entity_name=entity_name, fact=fact),
        temperature=0.0, feature=FACT_FEATURE, json_schema=FactReading.model_json_schema(),
        image_attachments=((image, "image/png"),),
    )
    return ApiResult(value=FactReading.model_validate(result.value), usage=result.usage)
