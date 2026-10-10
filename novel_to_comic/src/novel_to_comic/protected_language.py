"""Protected language: locating approved verbatim wording in source and lettering.

The Brief model quotes the passages a comic must keep word for word, and Adapt
letters them. Both are model output, so they routinely disagree on quote style,
dash form, line wrapping and attribution tags while carrying identical words.
These helpers compare both sides under one display-text policy, and anchor a
Brief phrase to the source wording it quotes, so a protected obligation is always
something the source actually says.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from novel_to_comic.models.source import SourceDocument
from novel_to_comic.text_utils import normalize_display_text


def protected_display_wording(text: str) -> str:
    return re.sub(r"\s+/\s+", " ", normalize_display_text(text)).strip()


def protected_language_key(text: str) -> str:
    # Briefs frequently preserve dialogue with source quotation marks, while
    # a comic balloon correctly carries only the spoken words.  Those wrappers
    # are presentation, not protected wording; retain every interior character
    # (including Spanish opening/closing punctuation) for the verbatim check.
    return protected_display_wording(text).strip('"“”«»').strip()


def protected_language_pattern(phrase: str) -> re.Pattern[str] | None:
    """Match wording, allowing only the initial case change of an excerpt.

    The Brief may capitalize a clause lifted from mid-sentence. Interior case,
    punctuation and words remain significant; neither authority is rewritten.
    """
    excerpt = protected_language_key(phrase)
    if not excerpt:
        return None
    initial = "(?:" + "|".join(re.escape(c) for c in {excerpt[0].lower(), excerpt[0].upper()}) + ")"
    return re.compile(r"(?<!\w)" + initial + re.escape(excerpt[1:]) + r"(?!\w)")


def contains_protected_language(text: str, phrase: str) -> bool:
    pattern = protected_language_pattern(phrase)
    return pattern is not None and pattern.search(protected_language_key(text)) is not None


_QUOTATION = re.compile(r'"([^"]*)"|«([^«»]*)»')


def protected_speech(phrase: str) -> tuple[str, ...]:
    """Return the quotations of a dialogue-led protected passage.

    A Brief may protect speech with its attribution, e.g. ``"Goblins aren't
    very bright," he thought. "I'm bigger."``. A comic letters only the spoken
    words: the tag becomes balloon ownership and its comma a sentence break.
    Such a passage obliges each quotation verbatim, less that tag comma.
    Narration-led phrases and lone quotations are not dialogue passages.
    """
    wording = protected_display_wording(phrase)
    spans = list(_QUOTATION.finditer(wording))
    if not spans or spans[0].start() != 0 or (len(spans) == 1 and spans[0].end() == len(wording)):
        return ()
    return tuple(
        speech
        for span in spans
        if (speech := (span.group(1) or span.group(2) or "").strip().removesuffix(",").rstrip())
    )


def protected_caption_text(phrase: str) -> str:
    """Display copy that letters a protected phrase as one quoted caption.

    A dialogue passage drops its attribution tags but keeps the speaker's own
    punctuation, so the caption reads as the quotation it is.
    """
    if not protected_speech(phrase):
        return protected_display_wording(phrase)
    quotations = [
        (span.group(1) or span.group(2) or "").strip()
        for span in _QUOTATION.finditer(protected_display_wording(phrase))
    ]
    return '"' + " ".join(quotation for quotation in quotations if quotation) + '"'


def _lettered_in_reading_order(phrase: str, wordings: tuple[str, ...]) -> bool:
    """Whether one balloon, or a run of consecutive ones, letters the phrase.

    A comic splits a long protected speech across balloons. Each word must
    still survive verbatim and in reading order; a balloon break reads as the
    space between sentences.
    """
    if (pattern := protected_language_pattern(phrase)) is None:
        return False
    keys = tuple(protected_language_key(wording) for wording in wordings)
    length = len(protected_language_key(phrase))
    for start, first in enumerate(keys):
        run = first
        if pattern.search(run):
            return True
        # Extend only while the match could still begin inside the first item;
        # a later start covers the remaining runs.
        for key in keys[start + 1:]:
            if len(run) - len(first) >= length:
                break
            run = f"{run} {key}"
            if pattern.search(run):
                return True
    return False


def protected_language_realized(phrase: str, wordings: Iterable[str]) -> bool:
    wordings = tuple(wordings)
    if _lettered_in_reading_order(phrase, wordings):
        return True
    speech = protected_speech(phrase)
    return bool(speech) and all(
        _lettered_in_reading_order(quotation, wordings) for quotation in speech
    )


def strip_source_emphasis(text: str) -> str:
    # Only paired word-boundary emphasis, not arbitrary asterisks/underscores
    # (multiplication and identifiers remain literal source wording).
    return re.sub(r"(?<![\w\\])(\*\*|__|\*|_)(?=\S)(.+?\S|\S)\1(?!\w)", r"\2", text)


def protected_source_key(text: str) -> str:
    """Compare source emphasis as presentation without changing source bytes."""
    return protected_language_key(strip_source_emphasis(text))


def _joined_source(source: SourceDocument) -> tuple[str, list[tuple[str, int, int]]]:
    """The source as a reader sees it, with each unit's span in that text.

    Extraction splits sentences, quotations, and attribution tags into separate
    units, while a Brief quotes the passage whole.
    """
    joined, bounds = "", []
    for unit in source.units:
        if not (wording := protected_display_wording(strip_source_emphasis(unit.text))):
            continue
        start = len(joined) + 1 if joined else 0
        joined = f"{joined} {wording}" if joined else wording
        bounds.append((unit.id, start, len(joined)))
    return joined, bounds


def protected_source_unit_ids(source: SourceDocument, phrase: str) -> tuple[str, ...]:
    """Source units carrying a phrase's protected wording, in source order.

    Search the joined source so wording that crosses a unit boundary is still
    located.
    """
    joined, bounds = _joined_source(source)
    matched: set[str] = set()
    for needle in protected_speech(phrase) or (phrase,):
        if (pattern := protected_language_pattern(needle)) is None:
            continue
        for match in pattern.finditer(joined):
            matched.update(unit_id for unit_id, start, end in bounds
                           if start < match.end() and match.start() < end)
    return tuple(unit_id for unit_id, _, _ in bounds if unit_id in matched)


_WORD = re.compile(r"\w+(?:'\w+)*")
# An attribution tag sits between a closing and a reopening quotation mark:
# `," said the sergeant-major, "`. Bound its length so unrelated speech is
# never stitched together.
_ATTRIBUTION_GAP = re.compile(r'[^\w"«»]*["»][^"«»]*["«][^\w"«»]*')
_MAX_ATTRIBUTION_WORDS = 8


def _align_phrase(
    folded: Sequence[str],
    words: Sequence[re.Match[str]],
    joined: str,
    start: int,
    wanted: Sequence[str],
) -> tuple[int, bool] | None:
    """The last source word index of an in-order match, and whether a tag was elided."""
    position, elided = start, False
    for expected in wanted[1:]:
        if position + 1 < len(folded) and folded[position + 1] == expected:
            position += 1
            continue
        limit = min(len(folded), position + 2 + _MAX_ATTRIBUTION_WORDS)
        for candidate in range(position + 2, limit):
            if folded[candidate] != expected:
                continue
            if _ATTRIBUTION_GAP.fullmatch(joined[words[position].end():words[candidate].start()]):
                position, elided = candidate, True
                break
        else:
            return None
    return position, elided


def anchor_protected_phrase(source: SourceDocument, phrase: str) -> str | None:
    """The source wording a Brief phrase quotes, or None when the source lacks it.

    A phrase the source already carries is returned unchanged. Otherwise the
    phrase is matched word for word, in order, ignoring case and punctuation and
    allowing elided attribution tags, and the source's own wording is returned:
    a dialogue passage keeps its tags so each quotation stays a verbatim
    obligation. Nothing is matched by similarity; a reworded phrase anchors to
    nothing.
    """
    if not protected_language_key(phrase):
        return None
    if protected_source_unit_ids(source, phrase):
        return phrase
    wanted = [word.casefold() for word in _WORD.findall(protected_display_wording(phrase))]
    if not wanted:
        return None
    joined, _ = _joined_source(source)
    words = list(_WORD.finditer(joined))
    folded = [word.group(0).casefold() for word in words]
    terminal = protected_language_key(phrase)[-1:] in {".", "!", "?"}
    for start, word in enumerate(folded):
        if word != wanted[0]:
            continue
        aligned = _align_phrase(folded, words, joined, start, wanted)
        if aligned is None:
            continue
        last, elided = aligned
        end = words[last].end()
        if terminal:
            end += len(joined[end:]) - len(joined[end:].lstrip(".!?"))
        passage = joined[words[start].start():end]
        # The elided tag closed and reopened a quotation, so the passage
        # begins and ends inside one.
        return f'"{passage}"' if elided else passage
    return None


def anchor_protected_language(
    source: SourceDocument, phrases: Iterable[str],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Split phrases into source-anchored wording and phrases the source lacks."""
    anchored: list[str] = []
    unmatched: list[str] = []
    for phrase in phrases:
        if not phrase.strip():
            continue
        wording = anchor_protected_phrase(source, phrase)
        if wording is None:
            unmatched.append(phrase)
        elif wording not in anchored:
            anchored.append(wording)
    return tuple(anchored), tuple(unmatched)
