"""Slice 06 — prompt hygiene: text safety, deduplication, and budgeting.

The compiled-request compiler (``compiled_request._build_sections``) calls into
this module so that every editable/dynamic scene field is:

1. **Text-safe** — adversarial readable-text cues (lettering, captions, speech
   balloons, on-screen text) are removed or converted to a physical text-free
   description before they enter the provider-bound prompt. Text is a Stage 9
   concern; generated panel art must contain no lettering. Protected anchors are
   NEVER sanitized (global invariant #1) — if an anchor conflicts with the
   no-lettering policy, a structured diagnostic is emitted while the anchor is
   preserved verbatim.
2. **Non-duplicative** — each fact has one owner. ``visual_requirements`` is
   normalized and deduplicated against subject action/expression/position, key
   objects, props, and setting delta. The must-show list is capped to the
   planner's intended 1–4 non-redundant details.
3. **Budgeted** — when a route has a verified ``prompt_char_limit``, protected
   sections (anchors, reference instructions, system constraints, active-state
   locks) are non-truncatable; lower-priority scene prose is compressed first.
   A request that cannot fit protected material fails explicitly rather than
   letting a provider prefix-slice it later.

Material guidance (medium wording) is owned by the selected style and must
never be hardcoded into a scene-direction or location-plate prompt. The
hygiene layer strips unconditional medium directives (e.g. hardcoded
"gouache") that contradict a non-gouache selected style.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from novel_to_comic.models.prompt import ImagePrompt
from novel_to_comic.text_utils import clean as _clean

#: Hard cap on the number of must-show (``visual_requirements``) details that
#: survive deduplication. The planner intends 1–4 must-show details; retaining
#: a long clause list dilutes attention and duplicates subject/object facts.
_MUST_SHOW_MAX = 4

# Adversarial readable-text cues. When a scene-direction field instructs the
# model to render readable content (a sign reading "X", a glowing caption, a
# speech balloon), the readable-content request is removed while the physical
# description of any text-bearing object is preserved. E.g. "a neon sign
# reading OPEN" → "a neon sign".
#
# Sentence-level removal is too blunt for physical text-bearing objects (it
# would drop "a neon sign" entirely), so the strategy is:
#   1. Strip "reading"/"reading X"/"that says X"/"labelled X" clauses.
#   2. Then drop any remaining sentence that is purely a text-render
#      instruction (no physical object survives).
_TEXT_RENDER_TOKENS = (
    "lettering", "subtitle", "caption box", "caption", "speech balloon",
    "speech bubble", "word balloon", "word bubble", "text crawl",
    "floating text", "scrolling text", "on-screen text", "onscreen text",
    "bold text", "glowing text", "burning text", "corrupted text",
    "readable text", "title card", "lower third",
)

# Clauses that attach readable content to a physical object. "a wooden sign
# reading KEEP OUT" → "a wooden sign". "a book whose pages spell HELP" →
# "a book". These are stripped so the physical object survives but the
# requested readable content does not.
_READABLE_CLAUSE_RE = re.compile(
    r"\s*\b(?:reading|read|reading out|that reads|that says|that read|"
    r"saying|spelling|spelled|spelt|label(?:l?ed|ing)?|inscribed|"
    r"emblazoned|carrying the text|bearing the text|with the text|"
    r"with text|displaying the text|showing the text)\b.*",
    re.IGNORECASE,
)

# A sentence is treated as a pure text-render instruction (and dropped) when it
# matches a text-render token and does not name a physical object that should
# survive. Physical-object nouns let the sentence survive as a physical
# description after the readable clause is stripped.
_PHYSICAL_OBJECT_CUE_RE = re.compile(
    r"\b(sign|neon|billboard|plaque|banner|poster|book|page|scroll|"
    r"tablet|screen|monitor|graffiti|mural|painting|title card|card|"
    r"letter|envelope|note|page|blackboard|chalkboard|whiteboard)\b",
    re.IGNORECASE,
)


def sanitize_dynamic_text(value: str | None) -> str:
    """Remove readable-text cues from one editable/dynamic scene field.

    - Strips "reading/saying/labelled X" clauses from physical text-bearing
      objects (the physical object survives, the requested readable content
      does not).
    - Strips comma/phrase fragments that merely name a text-render element
      (e.g. "medium shot with lettering on the wall" → "medium shot").
    - Drops sentences that are purely text-render instructions.
    - Never called on protected anchors — those are preserved verbatim.

    Returns the cleaned string. Whitespace is collapsed by ``_clean``.
    """
    text = _clean(value)
    if not text:
        return ""
    # First, strip readable-content clauses so physical objects survive.
    text = _READABLE_CLAUSE_RE.sub("", text)
    text = _clean(text).rstrip(" ,;:")
    # Then strip phrase fragments that merely name a text-render element.
    # "medium shot with lettering on the wall" → "medium shot". A physical
    # text-bearing object ("a neon sign") survives because it is not "merely"
    # a text-render element — it carries visual weight.
    text = _strip_text_render_phrases(text)
    # Finally, drop sentences that are purely text-render instructions (no
    # surviving physical object).
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for sentence in sentences:
        lowered = sentence.lower()
        is_text_instruction = any(tok in lowered for tok in _TEXT_RENDER_TOKENS)
        if is_text_instruction and not _PHYSICAL_OBJECT_CUE_RE.search(sentence):
            continue
        kept.append(sentence)
    return _clean(" ".join(kept))


# A phrase fragment that merely names a text-render element, possibly with a
# leading connector ("with lettering", "showing a speech balloon"). When the
# phrase does NOT contain a physical text-bearing object (sign, book,
# neon...), strip it so the surrounding framing survives. The leading
# connector is anchored (with/showing/...) so we never strip an arbitrary
# prefix like "medium shot" — only the text-render element and its tail.
_TEXT_RENDER_PHRASE_RE = re.compile(
    r"(?:,\s*|\s+)"
    r"(?:with\s+|showing\s+|containing\s+|including\s+|featuring\s+|having\s+|and\s+|plus\s+)?"
    r"(?:(?:a|an|the)\s+)?"
    r"(?:lettering|subtitle|caption(?:\s+box)?|speech\s+balloon|speech\s+bubble|"
    r"word\s+balloon|word\s+bubble|text\s+crawl|floating\s+text|"
    r"scrolling\s+text|on[- ]screen\s+text|onscreen\s+text|bold\s+text|"
    r"glowing\s+text|burning\s+text|corrupted\s+text|readable\s+text|"
    r"title\s+card|lower\s+third)"
    r"(?:\s+[a-z\s]{0,40}?(?=[.,;]|\s+and\s|$))?",
    re.IGNORECASE,
)


def _strip_text_render_phrases(text: str) -> str:
    """Strip phrase fragments that merely name a text-render element.

    Preserves physical text-bearing objects (sign, neon, book, ...) — those are
    stripped of their readable content by ``_READABLE_CLAUSE_RE`` but kept as
    physical descriptions. This only removes bare text-render mentions that
    add no visual value.
    """
    if not text:
        return text
    # Repeatedly strip until stable (overlapping phrases).
    previous = None
    current = text
    while previous != current:
        previous = current
        # Only strip a text-render phrase when the match span does NOT contain
        # a physical-object cue (otherwise we'd nuke "a neon sign").
        def _strip_match(m: re.Match) -> str:
            span = m.group(0)
            if _PHYSICAL_OBJECT_CUE_RE.search(span):
                return span  # keep physical object
            return ""
        current = _TEXT_RENDER_PHRASE_RE.sub(_strip_match, current)
        current = _clean(current)
    # Clean up dangling prepositions/connectors left after stripping
    # (e.g. "Warm glow from a" → "Warm glow").
    current = re.sub(
        r"\s+(?:from|with|of|on|in|at|to|for|containing|showing|having|and|plus)\s*$",
        "",
        current,
        flags=re.IGNORECASE,
    )
    return _clean(current).rstrip(" ,;:")


def sanitize_dynamic_list(values: list[str] | None) -> list[str]:
    """Sanitize each item in a dynamic list field (key objects, must-show)."""
    out: list[str] = []
    for value in values or []:
        cleaned = sanitize_dynamic_text(value)
        if cleaned:
            out.append(cleaned)
    return out


@dataclass(frozen=True, slots=True)
class AnchorTextConflict:
    """Diagnostic when a protected anchor itself conflicts with no-lettering.

    The anchor is preserved verbatim; this diagnostic surfaces the conflict for
    upstream correction. The generated no-lettering constraint is retained.
    """

    entity_id: str
    name: str
    anchor_text: str
    cue: str


def detect_anchor_text_conflicts(prompt: ImagePrompt) -> list[AnchorTextConflict]:
    """Detect protected anchors that request readable text.

    Never mutates the anchor. Returns a diagnostic per conflicting anchor so
    the compiler can record it as a structured upstream-correction warning.
    """
    conflicts: list[AnchorTextConflict] = []

    def _check(entity_id: str, name: str, text: str) -> None:
        lowered = (text or "").lower()
        for token in _TEXT_RENDER_TOKENS:
            if token in lowered:
                conflicts.append(AnchorTextConflict(
                    entity_id=entity_id,
                    name=name,
                    anchor_text=text,
                    cue=token,
                ))
                return

    for subject in getattr(prompt, "subjects", []) or []:
        _check(subject.character_id or subject.name, subject.name, subject.identity or "")
    for anchor in getattr(prompt, "anchors", []) or []:
        _check(anchor.entity_id, anchor.name, anchor.text or "")
    return conflicts


# ---------------------------------------------------------------------------
# Visual-requirements normalization and semantic deduplication
# ---------------------------------------------------------------------------

_STOPWORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "from", "with", "without", "near", "by", "as", "is", "are", "was",
    "were", "be", "been", "being", "this", "that", "these", "those", "it",
    "its", "her", "his", "their", "them", "they", "he", "she", "we", "us",
    "you", "your", "must", "show", "clearly", "visible", "panel", "scene",
})

_PHRASE_SPLIT_RE = re.compile(r",|\band\b", re.IGNORECASE)


def _significant_tokens(text: str) -> set[str]:
    if not text:
        return set()
    normalized = text.lower().replace("_", " ")
    return {
        tok
        for tok in re.split(r"[^a-z0-9]+", normalized)
        if tok and len(tok) > 2 and tok not in _STOPWORDS
    }


def _known_tokens_from_subjects(prompt: ImagePrompt) -> set[str]:
    """Tokens already owned by subject identity/action/expression/position."""
    known: set[str] = set()
    for subject in getattr(prompt, "subjects", []) or []:
        for field in (subject.identity, subject.action, subject.expression, subject.position):
            known |= _significant_tokens(field or "")
    return known


def dedupe_visual_requirements(
    prompt: ImagePrompt,
) -> tuple[list[str], set[str]]:
    """Normalize and semantically deduplicate ``visual_requirements``.

    Drops a requirement when all its significant tokens are already owned by
    subject action/expression/position, key objects, props, or setting delta.
    Enforces the planner's intended 1–4 must-show details. Returns the deduped
    list and the union of significant tokens it contributed (for callers that
    want to avoid further duplication).
    """
    raw = list(getattr(prompt, "visual_requirements", []) or [])
    if not raw:
        return [], set()

    known: set[str] = _known_tokens_from_subjects(prompt)
    for value in (getattr(prompt, "key_objects", []) or []):
        known |= _significant_tokens(value)
    for value in (getattr(prompt, "props", []) or []):
        known |= _significant_tokens(value)
    setting = getattr(prompt, "setting", None)
    if setting:
        known |= _significant_tokens(setting)

    seen: set[str] = set()
    deduped: list[str] = []
    contributed: set[str] = set()
    for value in raw:
        cleaned = sanitize_dynamic_text(value)
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        tokens = _significant_tokens(cleaned)
        # Drop a requirement only when ALL its significant tokens are already
        # owned upstream — a partial overlap (e.g. "character holding flowers"
        # when "character" is owned but "flowers" is new) is retained.
        if tokens and tokens.issubset(known):
            continue
        seen.add(key)
        deduped.append(cleaned)
        contributed |= tokens
        if len(deduped) >= _MUST_SHOW_MAX:
            break
    return deduped, contributed


# ---------------------------------------------------------------------------
# Single-owner: visual brief dedup against continuity
# ---------------------------------------------------------------------------


def dedupe_brief_against_continuity(brief: str | None, continuity: str | None) -> str:
    """Remove continuity-note content from the visual brief so it appears once.

    The continuity note owns the "CONTINUING FROM / TRANSITION" directive. The
    LLM-composed visual brief can repeat it verbatim or near-verbatim, which
    doubles the directive across two scene-direction lanes. This strips
    sentences from the brief whose significant tokens are fully covered by the
    continuity note, preserving the brief's other scene prose.
    """
    brief_text = _clean(brief)
    cont_text = _clean(continuity)
    if not brief_text or not cont_text:
        return brief_text
    cont_tokens = _significant_tokens(cont_text)
    if not cont_tokens:
        return brief_text
    sentences = re.split(r"(?<=[.!?])\s+", brief_text)
    kept = [
        s for s in sentences
        if not _significant_tokens(s).issubset(cont_tokens)
    ]
    return _clean(" ".join(kept))


# ---------------------------------------------------------------------------
# Hardcoded medium-conflict removal
# ---------------------------------------------------------------------------

# Unconditional medium directives that can contradict a non-matching selected
# style. "Use broad opaque gouache color blocks" injects gouache even when the
# selected style is ink wash or digital. The selected style owns medium
# guidance; scene-direction prose must not hardcode a competing medium.
_HARDCODED_MEDIUM_RE = re.compile(
    r"\b(?:use\s+(?:broad\s+)?(?:opaque\s+)?"
    r"(?:gouache|oil\s+paint|watercolou?r|acrylic|tempera|pastel|encaustic)\b"
    r"[^.]*\.)",
    re.IGNORECASE,
)


def strip_hardcoded_mediums(text: str | None) -> str:
    """Remove unconditional medium directives from scene-direction prose.

    Medium guidance must derive from the active selected style and appear once.
    This strips hardcoded medium sentences so a non-gouache style receives no
    gouache direction.
    """
    cleaned = _clean(text)
    if not cleaned:
        return ""
    stripped = _HARDCODED_MEDIUM_RE.sub("", cleaned)
    return _clean(stripped)


# ---------------------------------------------------------------------------
# Section-aware budgeting
# ---------------------------------------------------------------------------

#: Section kinds that are NEVER truncated. Protected anchors, reference
#: instructions, system constraints, and active-state locks must reach the
#: provider intact — a provider-side prefix slice that discards them is a
#: correctness bug, not a length tradeoff.
_NON_TRUNCATABLE_SECTIONS = frozenset({
    "protected_anchors",
    "reference_instructions",
    "system_constraints",
})

#: Section kinds that may be compressed or omitted when a route budget is
#: exceeded, in priority order (lowest priority first). User addenda is kept
#: above the visual brief because it is an explicit authored correction.
_COMPRESSIBLE_SECTION_ORDER = (
    "scene_direction",   # editable scene prose — compress the visual brief first
    "user_addenda",      # authored corrections — keep above generated prose
)


@dataclass(frozen=True, slots=True)
class BudgetResult:
    """Outcome of section-aware budgeting.

    ``final_prompt`` is the budgeted prompt string. ``overshoot`` is the number
    of characters by which protected material alone exceeds the budget (zero
    when protected material fits). ``budgeted`` is True when a limit was
    applied.
    """

    final_prompt: str
    overshoot: int
    budgeted: bool
    retained_sections: tuple[tuple[str, str], ...]


def apply_prompt_budget(
    sections_body_pairs: list[tuple[str, str]],
    *,
    char_limit: int | None,
) -> BudgetResult:
    """Apply a section-aware character budget to ordered ``(kind, body)`` pairs.

    Protected sections (anchors, reference instructions, system constraints)
    are never truncated. Compressible sections are dropped lowest-priority-first
    until the remaining body fits the limit. If protected material alone
    exceeds the limit, the function returns a non-zero ``overshoot`` so the
    compiler can fail explicitly.

    ``char_limit`` of ``None`` means no budget is applied (the route has no
    provider-side prefix slice that threatens protected content).
    """
    if char_limit is None:
        return BudgetResult(
            final_prompt="\n\n".join(body for _, body in sections_body_pairs if body),
            overshoot=0,
            budgeted=False,
            retained_sections=tuple((kind, body) for kind, body in sections_body_pairs if body),
        )

    protected_bodies = [
        body for kind, body in sections_body_pairs
        if kind in _NON_TRUNCATABLE_SECTIONS and body
    ]
    protected_total = sum(len(b) + 2 for b in protected_bodies)  # +2 for "\n\n"
    if protected_total > char_limit:
        # Protected material alone exceeds the budget — cannot trim safely.
        return BudgetResult(
            final_prompt="\n\n".join(body for _, body in sections_body_pairs if body),
            overshoot=protected_total - char_limit,
            budgeted=True,
            retained_sections=tuple((kind, body) for kind, body in sections_body_pairs if body),
        )

    # Greedily keep sections in order, dropping the lowest-priority
    # compressible section first when the running total would exceed the limit.
    # We keep all protected/uncompressible sections; among compressible ones we
    # drop from the end of the priority list (lowest priority) until it fits.
    kept: list[tuple[str, str]] = []
    for kind, body in sections_body_pairs:
        if body:
            kept.append((kind, body))

    def _total(items: list[tuple[str, str]]) -> int:
        return sum(len(b) + 2 for _, b in items if b)

    # Iteratively drop the lowest-priority compressible section until it fits
    # or no compressible section remains.
    while _total(kept) > char_limit:
        drop_index = None
        # The table is ordered lowest-priority-first.
        for target in _COMPRESSIBLE_SECTION_ORDER:
            for i, (kind, _body) in enumerate(kept):
                if kind == target:
                    drop_index = i
                    break
            if drop_index is not None:
                break
        if drop_index is None:
            break  # no more compressible sections to drop
        kept.pop(drop_index)

    total = _total(kept)
    return BudgetResult(
        final_prompt="\n\n".join(body for _, body in kept if body),
        overshoot=max(0, total - char_limit),
        budgeted=True,
        retained_sections=tuple(kept),
    )


__all__ = [
    "AnchorTextConflict",
    "BudgetResult",
    "apply_prompt_budget",
    "dedupe_brief_against_continuity",
    "dedupe_visual_requirements",
    "detect_anchor_text_conflicts",
    "sanitize_dynamic_list",
    "sanitize_dynamic_text",
    "strip_hardcoded_mediums",
]
