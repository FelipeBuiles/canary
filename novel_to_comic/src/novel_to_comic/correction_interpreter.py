"""Read an author's change requests against the page before they are drawn.

An image edit can only change artwork. A request that moves a line to another
panel, gives it to another speaker or rewords it contradicts the canonical
lettering the edit prompt also carries, so the image model gets two orders it
cannot both follow. This step looks at the current render and the canonical
page, rewrites each drawable request as one precise edit, and routes the rest:
panel and staging changes to Plan, wording to the script.

The result is advice for the author's draft. Nothing here edits the draft,
submits a correction or replans a page; the author applies each suggestion.
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.config import Config
from novel_to_comic.models.draw import CorrectionChange
from novel_to_comic.models.page import ApprovedVisualReferenceInventory, ComicPage
from novel_to_comic.usage import ApiResult, estimate_text_cost

FEATURE = "draw.correction_interpret"
# A page render costs roughly this much prompt text in image tokens.
_IMAGE_PROMPT_CHARS = 4_400
_OUTPUT_CHARS_PER_CHANGE = 900

_SYSTEM = (
    "You prepare an author's change requests for a comic page before an image model edits it. "
    "You are precise and conservative, and you never invent changes the author did not ask for."
)


class ChangeReading(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    change_id: str = Field(min_length=1)
    route: Literal["draw", "plan", "script"]
    instruction: str = Field(min_length=1, max_length=1000)
    reason: str = Field(min_length=1, max_length=400)
    # What the request reaches beyond this page's art. Facts only: code, not
    # the model, finds the pages (note_scope).
    reach: Literal["page", "beyond_page"] = "page"
    entity_id: str | None = None
    fact: str | None = Field(default=None, max_length=600)
    look_id: str | None = None
    look_label: str | None = Field(default=None, max_length=80)
    look_anchor: str | None = Field(default=None, max_length=1200)
    lettering_item_id: str | None = None
    new_text: str | None = Field(default=None, max_length=2000)
    new_speaker_entity_id: str | None = None
    panel: int | None = Field(default=None, ge=1)


class CorrectionReadings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    changes: tuple[ChangeReading, ...] = Field(max_length=24)


def _percent(points) -> str:
    xs = [point.x for point in points]
    ys = [point.y for point in points]
    return (f"{round(min(xs) * 100)}-{round(max(xs) * 100)}% across, "
            f"{round(min(ys) * 100)}-{round(max(ys) * 100)}% down")


def _page_facts(page: ComicPage, inventory: ApprovedVisualReferenceInventory) -> list[dict]:
    names = {reference.entity_id: reference.label or reference.entity_id for reference in inventory.references}
    return [
        {
            "panel": content.order,
            "shows": [{"id": entity_id, "name": names.get(entity_id, entity_id),
                       "look": content.appearance_states.get(entity_id)} for entity_id in content.entity_ids],
            "visual_intent": content.visual_intent,
            "lettering": [
                {"id": item.id, "kind": item.kind, "speaker": item.speaker, "delivery": item.delivery,
                 "text": item.text}
                for item in content.lettering
            ],
        }
        for content in sorted(page.content, key=lambda content: content.order)
    ]


def _looks(page: ComicPage, inventory: ApprovedVisualReferenceInventory) -> list[dict]:
    """Each visible entity's descriptions, so a fact can name an existing look or a new one."""
    visible = list(dict.fromkeys(entity_id for content in page.content for entity_id in content.entity_ids))
    entries = []
    for entity_id in visible:
        references = [reference for reference in inventory.references if reference.entity_id == entity_id]
        base = next((reference for reference in references if reference.appearance_state_id is None), None)
        if base is None or base.kind not in ("character", "location", "prop"):
            continue
        entries.append({
            "id": entity_id, "name": base.label or entity_id, "description": base.visual_anchor,
            "looks": [{"look_id": reference.appearance_state_id, "description": reference.visual_anchor}
                      for reference in references if reference.appearance_state_id is not None],
        })
    return entries


def _requests(changes: tuple[CorrectionChange, ...]) -> list[dict]:
    return [
        {
            "change_id": change.id,
            "request": change.instruction,
            "marked_locations": [
                f"{annotation.kind} at {_percent(annotation.points)}"
                + (f": {annotation.note.strip()}" if annotation.note.strip() else "")
                for annotation in change.annotations
            ],
        }
        for change in changes
    ]


def interpretation_prompt(
    *,
    page: ComicPage,
    inventory: ApprovedVisualReferenceInventory,
    changes: tuple[CorrectionChange, ...],
    lettering_in_art: bool,
) -> str:
    lettering_rule = (
        "The artwork carries the comic lettering. Fixing how a canonical line is drawn is a draw change: "
        "a misspelling, a missing or duplicated balloon, or a tail pointing at the wrong character."
        if lettering_in_art else
        "The artwork carries no comic lettering; Canary letters the page separately. Any request about "
        "balloons, captions, tails or wording is not a draw change unless it asks to remove text drawn into the art."
    )
    return (
        "Image 1 is the current comic page. Below are the page's canonical panels and lettering, then the "
        "author's change requests in their own words, with any locations they marked as page fractions "
        "(origin top-left).\n\n"
        "For each request, decide where it belongs:\n"
        "- draw: a change to the artwork of this page. Rewrite it as one precise edit instruction: name the "
        "panel, the subject and the exact visual change, using what you see in Image 1. Keep the author's "
        "intent and scope; do not add changes. Keep marked locations meaningful by naming what is there.\n"
        "- plan: a change to which panel shows what, which panel a canonical lettering line sits in, the "
        "number or order of panels, or which characters appear. Rewrite it as a request to the page "
        "planner, naming the lettering line or panel exactly.\n"
        "- script: a change to the wording of a line, who says it, or adding or removing lines. Rewrite it "
        "as the script change, quoting the line.\n"
        f"{lettering_rule}\n"
        "A request mixing kinds takes the route of its main change and names the rest in the reason. "
        "The reason is one short sentence for the author, in plain language.\n\n"
        "Then say how far the request reaches; leave every field below empty when it is about this page "
        "alone:\n"
        "- A script request about one line: set lettering_item_id to that line's id, and new_text to its "
        "exact new wording and/or new_speaker_entity_id to the character who should say it. A script "
        "request about a missing or unclear story moment: set panel to the panel where it belongs.\n"
        "- A draw or plan request that states a fact which should also hold on later pages (clothing, "
        "hair, an injury, something carried, a place's layout), as in 'she took her apron off a few pages "
        "back' or 'the staircase is on the right of the door': set reach to beyond_page, entity_id to the "
        "character, place or prop, and fact to one plain sentence of what holds. If one of its looks "
        "already matches, set look_id. If its description contradicts the fact, set look_label to a short "
        "name for the new look and look_anchor to a complete description of it in that look, written "
        "from its current description with only the fact changed. If its description already agrees "
        "with the fact, set neither: only the art is wrong.\n\n"
        "Return one entry per request, in the same order, with its change_id.\n\n"
        + json.dumps({"panels": _page_facts(page, inventory), "descriptions": _looks(page, inventory),
                      "requests": _requests(changes)}, ensure_ascii=False)
    )


def estimate_interpretation_cost(config: Config, prompt: str, change_count: int) -> float:
    return estimate_text_cost(
        config.effective_correction_model(),
        _SYSTEM + prompt + " " * _IMAGE_PROMPT_CHARS,
        output_chars=_OUTPUT_CHARS_PER_CHANGE * max(1, change_count),
    )


async def interpret_changes(
    *,
    config: Config,
    page: ComicPage,
    inventory: ApprovedVisualReferenceInventory,
    image: bytes,
    changes: tuple[CorrectionChange, ...],
    lettering_in_art: bool,
    generate=None,
) -> ApiResult[CorrectionReadings]:
    if not changes:
        raise ValueError("add a change before checking it")
    if generate is None:
        from novel_to_comic.clients.text import generate_json

        generate = generate_json
    result = await generate(
        config=config,
        model=config.effective_correction_model(),
        system_prompt=_SYSTEM,
        user_content=interpretation_prompt(page=page, inventory=inventory, changes=changes,
                                           lettering_in_art=lettering_in_art),
        temperature=0.0,
        feature=FEATURE,
        json_schema=CorrectionReadings.model_json_schema(),
        image_attachments=((image, "image/png"),),
    )
    readings = CorrectionReadings.model_validate(result.value)
    expected = [change.id for change in changes]
    if [reading.change_id for reading in readings.changes] != expected:
        by_id = {reading.change_id: reading for reading in readings.changes}
        if set(by_id) != set(expected):
            raise ValueError("the change check did not return one reading per request; try again")
        readings = CorrectionReadings(changes=tuple(by_id[change_id] for change_id in expected))
    return ApiResult(value=readings, usage=result.usage)


def claim_for(reading: ChangeReading, page: ComicPage):
    """The typed claim a reading names, for note_scope to resolve; None when page-local."""
    from novel_to_comic.note_scope import BeatClaim, LineClaim, LookClaim

    item_ids = {item.id for content in page.content for item in content.lettering}
    if reading.route == "script":
        if reading.lettering_item_id in item_ids and (reading.new_text or reading.new_speaker_entity_id):
            return LineClaim(lettering_item_id=reading.lettering_item_id, text=reading.new_text,
                             speaker_entity_id=reading.new_speaker_entity_id)
        panel = next((content for content in page.content if content.order == reading.panel), None)
        beat_ids = panel.beat_ids if panel is not None else page.cited_beat_ids
        return BeatClaim(beat_ids=tuple(beat_ids)[:6], note=reading.instruction)
    if reading.reach == "beyond_page" and reading.entity_id and (reading.fact or "").strip():
        visible = {entity_id for content in page.content for entity_id in content.entity_ids}
        if reading.entity_id not in visible:
            return None
        return LookClaim(entity_id=reading.entity_id, fact=reading.fact.strip(), start_page=page.page_number,
                         state_id=reading.look_id or None, look_label=reading.look_label or None,
                         look_anchor=reading.look_anchor or None)
    return None
