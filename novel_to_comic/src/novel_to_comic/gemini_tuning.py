"""Gemini's promoted stage checklists and request-local experiment control.

The wording comes from the successful medium-reasoning Labs tuning arm.
Reviews and features without a checklist retain their original instructions.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any, Iterator

from novel_to_comic.ai.prompt_parts import cache_join
from novel_to_comic.text_models import is_gemini_model, text_wire, tuning_model

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
        "- Put a turn reveal at the top of a left-hand (even) page, with its setup closing the "
        "right-hand (odd) page before it, so the page turn lands it.\n"
        "- Allocate dialogue-heavy stretches against the edition-specific word and item budgets "
        "supplied in the main prompt before locking the page map.\n"
    ),
}
_PANEL_RULES = (
    "- Vary panel counts with the page's job: peaks and reveals 1-3 large panels; establishing and "
    "transition pages 2-4; dialogue-heavy prolongation 4-6. These are options, not quotas; "
    "keep a repeated grid when it supports the story tone or timing.\n"
    "- Keep each panel's lettering under about 50 words in total. When a beat carries more, spread "
    "its lettering across several panels of that beat (new angle, reaction, or close-up).\n"
)
ADDENDA["plan.detail"] = _HEADER + _PANEL_RULES
ADDENDA["plan.book"] = ADDENDA["plan.map"] + _PANEL_RULES
# The single-call Adapt path asks for beats and lettering together.
ADDENDA["adapt.book"] = ADDENDA["adapt.blueprint"] + ADDENDA["adapt.lettering"].removeprefix(_HEADER)


# Route-specific additions after the shared Gemini checklist. Argon follows the
# completeness rules literally: in Labs run 20261013-143611-7df22e it lettered
# 2,316 words (48 captions) from a 3,931-word story where Flash used 1,213 (10),
# narrating actions, including the climax, that the panels already show.
_ARGON_SHOW_DONT_CAPTION = (
    "- Show, do not caption. Narration that describes visible action, gesture, expression, "
    "appearance, or setting is realized by its drawn beat: cite it on the beat, not in any "
    "lettering item. A depicted source unit fully satisfies faithful completeness. "
    "For example, \"She crossed the room and sat by the fire\" is drawn; \"It was the last "
    "evening they would spend together\" is a caption.\n"
    "- A caption must add what the panel cannot show: the narrator's voice or judgment, a time or "
    "place jump, unspoken interiority, or a causal link. Most beats need no caption and rarely more "
    "than one. Do not caption the action of a peak or reveal beat unless its words are protected.\n"
    "- Keep dialogue in the speakers' own words and protected passages verbatim. Captions should "
    "carry well under a quarter of the source's narration sentences.\n"
    # Labs run 20261013-160909-c706ad dropped both bookend lines as "setting".
    "- Keep the narrator's signature lines as captions even when they describe a scene: the story's "
    "opening and closing sentences and any line a reader would quote.\n"
    "- Before leaving a beat silent, check that the reader still learns every name, relationship, "
    "or cause that later copy relies on (who an organization is to a character, what a character "
    "imagines or fears); keep the shortest narration that establishes it.\n"
)
# Labs run 20261013-160909-c706ad: Argon protected 29 lines, splitting quotes
# at their dialogue tags into fragments ("If you must wish," / "Wish for
# something sensible.") and keeping game moves ("Check.", "Mate,"), while
# leaving out the story's opening and closing lines, which Adapt then dropped.
_ARGON_PROTECTED_LANGUAGE = (
    "- Protected language is for lines whose exact wording carries the story: lines a reader would "
    "quote, a wish or vow, a reveal, the story's opening and closing sentences when they set its "
    "tone, and narration in a voice the adaptation must keep. Protect each such line whole; quote "
    "a speech across its dialogue tag rather than splitting it into fragments.\n"
    "- Do not protect routine exchanges, single words, game moves, or cries that any adaptation "
    "would letter anyway. A short story rarely needs more than about fifteen protected lines.\n"
)
# Argon reads the whole source well but kept anchors thin ("young man, adult
# son") where details appear only later in the story.
_ARGON_ANCHORS = (
    "- Character and location anchors: gather every visible detail the source states anywhere, "
    "not only at a first appearance (age, build, hair, clothing, belongings, condition, period). "
    "Never add a detail the source does not state or plainly establish.\n"
)
# The same run: 16 of Argon's 30 pages used four panels and 7 were marked
# cliffhangers, so the page turn stopped carrying weight.
_ARGON_PAGE_RHYTHM = (
    "- Do not fall back on one grid. Across the book, mix panel counts so no single count holds "
    "most pages; give each peak or reveal a page of 1-3 panels and let a quiet aftermath breathe "
    "on a sparse page.\n"
    "- Mark a page as a cliffhanger only when its last panel withholds an answer the next page "
    "gives. Most stories need a few, not one every few pages; use setup, release, or none otherwise.\n"
)
# Labs run 20261013-171728-bf5a8d: Flash Adapt invented cries ("NOOOOO—!",
# "AIIIEEEEE—!"), voiced reported narration as dialogue ("A tailor's bill!
# Retired Sergeant-Majors and their bibulous habits...") and rewrote "If only he
# could find it" as a first-person thought, despite the main prompt's rules.
_FLASH_SOURCE_WORDING = (
    "- Letter only words the source supplies. Never invent a cry, scream, or exclamation the source "
    "does not write out: a wail or shriek the narrator describes is drawn, or captioned in the "
    "narrator's words. Sound effects for sounds the source describes are fine.\n"
    "- Speech the narrator reports indirectly (she apologized for the room; it led to remarks about "
    "his habits) stays a caption in the narrator's words or is drawn; do not voice it as new dialogue.\n"
    "- Never turn narration into a thought balloon. 'If only he could find it' in narration is a "
    "caption, not the thought 'If only I can find it'.\n"
)
MODEL_ADDENDA: dict[str, dict[str, str]] = {
    "gemini-3.8-flash": {
        "adapt.lettering": _FLASH_SOURCE_WORDING,
        "adapt.book": _FLASH_SOURCE_WORDING,
    },
    "gemini-4-argon": {
        "extract.story_bible": _ARGON_ANCHORS,
        "brief.infer": _ARGON_PROTECTED_LANGUAGE,
        "adapt.lettering": _ARGON_SHOW_DONT_CAPTION,
        "adapt.book": _ARGON_SHOW_DONT_CAPTION,
        "plan.map": _ARGON_PAGE_RHYTHM,
        "plan.book": _ARGON_PAGE_RHYTHM,
    },
}


def _addendum(model: str, feature: str) -> str:
    shared = ADDENDA.get(feature, "")
    extra = MODEL_ADDENDA.get(tuning_model(model), {}).get(feature, "")
    return shared + extra if shared else (_HEADER + extra if extra else "")


def gemini_tuning_enabled(model: str) -> bool:
    return is_gemini_model(model) and _ENABLED.get()


def tuned_user_content(model: str, feature: str, content: str) -> str:
    if not gemini_tuning_enabled(model):
        return content
    # Its own trailing part, so a repair that appends to the content above
    # keeps that content's leading part, and Vertex's cached prefix, intact.
    addendum = _addendum(model, feature).lstrip("\n")
    return cache_join(content, addendum) if addendum and not content.endswith(addendum) else content


# Schemas carry per-window and per-shard ID enums; in the system prompt they
# make every shard's prefix unique after ~5k characters. Argon takes the
# contract after the content (validated in Labs run 20261013-171728-bf5a8d,
# zero Plan repairs). Flash keeps its long-validated system-prompt contract:
# the move bought no cache hits (3 of 226 calls in that run) and Flash's Plan
# repairs rose to 11-19 calls after it.
_CONTRACT_AFTER_CONTENT = frozenset({"gemini-4-argon"})


def tuned_request(model: str, request: dict[str, Any]) -> dict[str, Any]:
    """Use the same effective input for paid checkpoints and the HTTP request."""
    if not is_gemini_model(model) and not text_wire(model).schema_instructions:
        return request
    from novel_to_comic.ai.gemini_schema import gemini_output_schema, output_contract, schema_instructions

    result = dict(request)
    if isinstance(result.get("user_content"), str):
        result["user_content"] = tuned_user_content(model, result.get("feature", ""), result["user_content"])
    if result.get("json_schema") and text_wire(model).schema_instructions:
        # These routes send every structured call as JSON mode with the compiled
        # schema as instructions; see ai/gemini_schema.py and TextModel.
        schema = gemini_output_schema(result["json_schema"])
        if tuning_model(model) in _CONTRACT_AFTER_CONTENT:
            result["user_content"] = cache_join(result.get("user_content", ""), output_contract(schema))
        else:
            result["system_prompt"] = schema_instructions(result.get("system_prompt", ""), schema)
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
