"""Gemini's promoted stage checklists and request-local experiment control.

The wording comes from the successful medium-reasoning Labs tuning arm.
Reviews and features without a checklist retain their original instructions.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Iterator

from novel_to_comic.text_models import is_gemini_model

_ENABLED: ContextVar[bool] = ContextVar("gemini_tuning_enabled", default=True)

_HEADER = "\n\nFINAL CHECKLIST (apply to the material above before you answer):\n"

ADDENDA: dict[str, str] = {
    "extract.story_bible": _HEADER + (
        "- Scenes: start a new scene at every change of place, time, or dramatic situation. "
        "An opening incident counts as its own scene even when it is narrated in a few sentences.\n"
        "- Locations: every setting where an event happens or is narrated as happening is a separate "
        "location, including the setting of an opening incident told in flashback or summary. "
        "Never merge two settings because one is brief.\n"
        "- Appearance states: whenever a character's or location's visible look changes or differs "
        "from its base (injury, death, damage, costume, age, transformation), record an "
        "appearance_states entry and a matching appearance_timeline entry.\n"
        "- Before answering, reread the source from beginning to end and confirm each paragraph is "
        "covered by a scene, and each setting and visible change by a location or state.\n"
    ),
    "brief.infer": _HEADER + (
        "- Essential events: one item per distinct event, reveal, or turn, in story order. "
        "Never fold several reveals into one item.\n"
        "- Keep concrete specifics the story relies on: named people, dates, places, numbers, "
        "and paired examples. Do not abstract them into general statements.\n"
        "- Record each point where a character's understanding or feeling changes as a character turn, "
        "and each open question a reader would notice as an ambiguity.\n"
        "- Protect memorable source lines verbatim when the adaptation should keep their exact wording.\n"
    ),
    "adapt.blueprint": _HEADER + (
        "- A beat is ONE moment a single panel could show. Most beats cite 1-4 source units. "
        "A beat citing more than 5 source units almost always holds several moments: split it, "
        "unless it is one continuous line of narration or speech.\n"
        "- Give each reveal, each reaction to a reveal, each question-and-answer turn that changes "
        "what a character knows, and each transition its own beat.\n"
        "- The page target is not a beat target; do not merge beats to fit pages.\n"
        "- Before answering, count source units per beat and split any beat that fails the rule above.\n"
    ),
    "adapt.lettering": _HEADER + (
        "- One lettering item is one balloon or caption: at most about 25 words. Split longer speeches "
        "into consecutive items with the same speaker, only at sentence boundaries.\n"
        "- Prefer the source's own wording; paraphrase only to fit a balloon, and keep protected "
        "language verbatim.\n"
    ),
    "plan.map": _HEADER + (
        "- Each page's emphasis must equal the narrative_function of at least one beat on that page.\n"
        "- Put a reveal at the top of a page, with its setup closing the previous page, so the page turn "
        "lands it.\n"
        "- Allocate pages so dialogue-heavy stretches are not crammed: a page should not carry more "
        "lettering than about 4-6 panels can hold at 25 words each.\n"
    ),
}
_PANEL_RULES = (
    "- Vary panel counts with the page's job: peaks and reveals 1-3 large panels; establishing and "
    "transition pages 2-4; dialogue-heavy prolongation 4-6. Never use the same panel count on more "
    "than three consecutive pages.\n"
    "- Keep each panel's lettering under about 25 words in total. When a beat carries more, spread "
    "its lettering across several panels of that beat (new angle, reaction, or close-up).\n"
)
ADDENDA["plan.detail"] = _HEADER + _PANEL_RULES
ADDENDA["plan.book"] = ADDENDA["plan.map"] + _PANEL_RULES
# The single-call Adapt path asks for beats and lettering together.
ADDENDA["adapt.book"] = ADDENDA["adapt.blueprint"] + ADDENDA["adapt.lettering"].removeprefix(_HEADER)


def gemini_tuning_enabled(model: str) -> bool:
    return is_gemini_model(model) and _ENABLED.get()


def tuned_user_content(model: str, feature: str, content: str) -> str:
    if not gemini_tuning_enabled(model):
        return content
    addendum = ADDENDA.get(feature)
    return content + addendum if addendum and not content.endswith(addendum) else content


def tuned_request(model: str, request: dict[str, Any]) -> dict[str, Any]:
    """Use the same effective input for paid checkpoints and the HTTP request."""
    if not is_gemini_model(model):
        return request
    from novel_to_comic.ai.gemini_schema import gemini_output_schema, schema_instructions

    result = dict(request)
    if isinstance(result.get("user_content"), str):
        result["user_content"] = tuned_user_content(model, result.get("feature", ""), result["user_content"])
    if result.get("json_schema"):
        # Every Gemini structured call uses JSON mode with the compiled schema
        # as instructions; see ai/gemini_schema.py for why native decoding is not used.
        result["system_prompt"] = schema_instructions(
            result.get("system_prompt", ""), gemini_output_schema(result["json_schema"]),
        )
        result["json_schema"] = None
        result["json_mode"] = True
    return result


@contextmanager
def gemini_tuning_override(enabled: bool) -> Iterator[None]:
    """Let historical Labs arms compare their original workflow in one context."""
    token = _ENABLED.set(enabled)
    try:
        yield
    finally:
        _ENABLED.reset(token)


def generic_detail_schema(schema: dict, target_pages: Any) -> dict:
    """One page template for the whole batch, so the schema does not grow per page.

    Built from the shared-panel schema: beats are the batch's union, page numbers
    a range, and lettering placements a list whose items name their lettering
    ID, with no page-array bounds. Probes on 2026-10-01 found Gemini rejects
    (400 INVALID_ARGUMENT) both an anyOf over page variants and any page-array
    bound of 2+, independent of prompt and size. Per-page ownership and the page
    count move from the decoder to Plan's own validators
    (_compile_detail_response and _detail_matches_map), which already check it.
    """
    template = deepcopy(schema["$defs"]["_PageDetailDraft"]["anyOf"][0])
    numbers = [page.page_number for page in target_pages]
    template["properties"]["page_number"] = {"type": "integer", "minimum": min(numbers), "maximum": max(numbers)}
    lettering_ids = list(dict.fromkeys(item for page in target_pages for item in page.lettering_ids))
    placement = deepcopy(schema["$defs"]["_LetteringPlacementDraft"])
    placement["properties"] = {"lettering_item_id": {"type": "string", "enum": lettering_ids}
                               if lettering_ids else {"type": "string"}, **placement["properties"]}
    placement["required"] = ["lettering_item_id", *placement.get("required", [])]
    template["properties"]["lettering_placements"] = {"type": "array", "items": placement}
    template["required"] = list(dict.fromkeys([*template.get("required", []), "page_number"]))
    defs = {k: v for k, v in schema["$defs"].items() if k != "_PageDetailDraft"} | {"_PageDetailDraft": template}
    # Gemini rejects page arrays bounded at 2+ items (minItems or maxItems); the
    # count is checked by _compile_detail_response ("Expected N pages").
    pages = {k: v for k, v in schema["properties"]["pages"].items() if k not in ("minItems", "maxItems")}
    return {**schema, "$defs": defs, "properties": {**schema["properties"], "pages": pages}}


def ungeneric_detail_response(value: Any) -> Any:
    """Turn each page's placement list back into the ID-keyed map Plan validates."""
    if not isinstance(value, dict) or not isinstance(value.get("pages"), list):
        return value
    pages = []
    for page in value["pages"]:
        placements = page.get("lettering_placements") if isinstance(page, dict) else None
        if isinstance(placements, list):
            keyed: dict[str, Any] = {}
            for entry in placements:
                if not isinstance(entry, dict) or not isinstance(entry.get("lettering_item_id"), str):
                    raise ValueError("Each lettering placement must be an object with a lettering_item_id.")
                item_id = entry.get("lettering_item_id")
                if item_id in keyed:
                    raise ValueError(f"Page {page.get('page_number')} places lettering {item_id!r} twice.")
                keyed[item_id] = {k: v for k, v in entry.items() if k != "lettering_item_id"}
            page = {**page, "lettering_placements": keyed}
        pages.append(page)
    return {**value, "pages": pages}


def generic_detail_view(value: dict[str, Any]) -> dict[str, Any]:
    """Render a locally validated placement map for a Gemini repair request."""
    value = deepcopy(value)
    for page in value["pages"]:
        placements = page["lettering_placements"]
        page["lettering_placements"] = [{"lettering_item_id": item_id, **placement}
                                        for item_id, placement in placements.items()]
    return value
