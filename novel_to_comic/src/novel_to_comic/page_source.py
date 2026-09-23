"""Read-only manuscript view for one planned page (Pages → Source).

A page maps back to the manuscript through canonical links: its content
items cite Adapt beats, beats cite source units, and each canonical lettering
item cites the exact source units it was written from. The adaptation ledger
says which beat units are depicted rather than lettered.

The drawing model owns page composition, so planned content items are not
panels on the art. Only lettering has a verifiable place on the page: an
editable edition's saved lettering placement, or, for integrated lettering,
the text region a text check matched on the current render. Depicted detail
has no recorded position and is never located. Nothing here calls a provider
or writes artifacts.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

from novel_to_comic.lettering.service import is_hybrid
from novel_to_comic.models.page import ComicPage
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

MarkKind = Literal["lettering", "depicted"]

# Shortest verbatim run (in characters) worth highlighting inside a unit.
# Shorter coincidences ("of the ") would scatter noise across the passage.
_MIN_VERBATIM_RUN = 12
_DEPICTED = frozenset({"depicted", "visual_motif"})
_FOLD = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"', "—": "-", "–": "-"})


class PageSourceStale(ValueError):
    """The page's lineage no longer matches the manuscript it would cite."""


def _fold(text: str) -> str:
    """Length-preserving normalization so offsets map back to the source."""

    return "".join(" " if char.isspace() else char for char in text.translate(_FOLD)).casefold()


def _word_span(text: str, start: int, end: int) -> tuple[int, int] | None:
    """Shrink a matched run to whole words; partial edge words are not proof."""

    if start > 0 and text[start - 1].isalnum():
        while start < end and text[start].isalnum():
            start += 1
    if end < len(text) and text[end].isalnum():
        while end > start and text[end - 1].isalnum():
            end -= 1
    while start < end and not text[start].isalnum():
        start += 1
    while end > start and not (text[end - 1].isalnum() or text[end - 1] in ".,;:!?'\"’”)"):
        end -= 1
    return (start, end) if end - start >= _MIN_VERBATIM_RUN else None


def _verbatim_spans(unit_text: str, lettering_text: str) -> list[tuple[int, int]]:
    folded = _fold(unit_text)
    matcher = SequenceMatcher(None, folded, _fold(lettering_text), autojunk=False)
    spans = []
    for block in matcher.get_matching_blocks():
        if block.size < _MIN_VERBATIM_RUN:
            continue
        span = _word_span(unit_text, block.a, block.a + block.size)
        if span is not None:
            spans.append(span)
    return spans


def _trimmed(text: str) -> tuple[int, int]:
    start = len(text) - len(text.lstrip())
    return start, max(start, len(text.rstrip()))


def _segments(
    text: str,
    depicted: bool,
    lettering: list[tuple[str, str]],
) -> list[dict]:
    """Split one unit into plain and marked runs.

    ``lettering`` holds (lettering_item_id, canonical text) pairs citing this unit.
    Verbatim words are marked when the copy quotes the manuscript; a
    paraphrase marks the whole unit, since the citation itself is canonical.
    """

    labels: list[tuple[MarkKind, tuple[str, ...]] | None] = [None] * len(text)
    if depicted:
        start, end = _trimmed(text)
        for index in range(start, end):
            labels[index] = ("depicted", ())
    for item_id, copy in lettering:
        spans = _verbatim_spans(text, copy) or [_trimmed(text)]
        for start, end in spans:
            for index in range(start, end):
                current = labels[index]
                ids = current[1] if current and current[0] == "lettering" else ()
                if item_id not in ids:
                    ids = (*ids, item_id)
                labels[index] = ("lettering", ids)
    runs: list[list] = []
    for char, label in zip(text, labels):
        if runs and runs[-1][1] == label:
            runs[-1][0] += char
        else:
            runs.append([char, label])
    segments: list[dict] = []
    for run_text, label in runs:
        # Punctuation left between lettered words is not a depicted detail.
        if label and label[0] == "depicted" and not any(char.isalnum() for char in run_text):
            label = None
        kind, ids = label if label else (None, ())
        if segments and segments[-1]["kind"] == kind and segments[-1]["lettering_item_ids"] == list(ids):
            segments[-1]["text"] += run_text
        else:
            segments.append({"text": run_text, "kind": kind, "lettering_item_ids": list(ids)})
    return segments


def _box(polygon) -> dict:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    x, y = max(0.0, min(xs)), max(0.0, min(ys))
    return {"x": x, "y": y, "width": min(1.0, max(xs)) - x, "height": min(1.0, max(ys)) - y}


def _placements(target: TargetArtifacts, page: ComicPage) -> tuple[dict[str, dict], dict | None]:
    """Editable lettering elements by canonical item, as saved for this page.

    Elements are returned whole: the shared lettering engine owns how a
    placement, fitted size, scale, and rotation become the drawn balloon.
    """

    try:
        state = target.read_lettering(page.page_number)
    except (ArtifactMissing, ArtifactInvalid):
        return {}, None
    if state.comic_page_sha256 != page.content_sha256:
        return {}, None
    elements = {
        element.source_lettering_item_id: element.model_dump(mode="json")
        for element in state.elements
        if element.source_lettering_item_id is not None and not element.hidden
    }
    return elements, {"source": "lettering_placement", "lettering_revision": state.revision}


def _text_regions(target: TargetArtifacts, page: ComicPage) -> tuple[dict[str, dict], dict | None]:
    """Where a text check found each canonical lettering item on the current render."""

    revisions = target.provenance_revisions(page.page_number)
    if not revisions:
        return {}, None
    try:
        render = target.read_provenance(page.page_number, revisions[-1]).render
        analysis = target.read_analysis(page.page_number, render.revision)
    except (ArtifactMissing, ArtifactInvalid):
        # The text check is optional evidence; without it nothing is located.
        return {}, None
    if (
        analysis.render_image_sha256 != render.image_sha256
        or analysis.comic_page_sha256 != page.content_sha256
    ):
        return {}, None
    regions = {region.id: region for region in analysis.observed_regions}
    located = {}
    for match in analysis.lettering_matches:
        # page_ocr keeps a tight region per observation: ocr_NNN ↔ region_NNN.
        region = regions.get("region_" + match.observation_id.removeprefix("ocr_"))
        if region is not None:
            located[match.lettering_item_id] = _box(region.polygon)
    if not located:
        return {}, None
    return located, {"source": "text_check", "render_revision": render.revision}


def page_source_view(target: TargetArtifacts, page_number: int) -> dict:
    source = target.read_source()
    adaptation = target.read_adaptation()
    page = target.read_page(page_number)
    if adaptation.source_sha256 != source.source_sha256:
        raise PageSourceStale(
            "The adaptation no longer matches the manuscript. Re-run Adapt, then Plan."
        )
    if page.adaptation_sha256 != adaptation.content_sha256:
        raise PageSourceStale(
            f"Page {page_number} was planned from an older adaptation. Re-run Plan."
        )

    units = {unit.id: unit for unit in source.units}
    beats = {beat.id: beat for beat in adaptation.beats}
    page_beats = {beat_id for content in page.content for beat_id in content.beat_ids}
    unknown_beats = page_beats - set(beats)
    if unknown_beats:
        raise PageSourceStale(
            f"Page {page_number} cites beats missing from the adaptation "
            f"({', '.join(sorted(unknown_beats))}). Re-run Plan."
        )

    lettering: dict[str, list[tuple[str, str]]] = {}
    for content in page.content:
        for item in content.lettering:
            for unit_id in item.source_unit_ids:
                lettering.setdefault(unit_id, []).append((item.id, item.text))
    depicted = {
        entry.source_unit_id
        for entry in adaptation.ledger
        if entry.disposition in _DEPICTED
        and any(beat_id in page_beats for beat_id in entry.adapted_beat_ids)
    }

    cited = {
        unit_id for beat_id in page_beats for unit_id in beats[beat_id].source_unit_ids
    } | set(lettering)
    unknown_units = cited - set(units)
    if unknown_units:
        raise PageSourceStale(
            f"Page {page_number} cites source units missing from the manuscript. Re-run Adapt, then Plan."
        )

    scene_by_ordinal = []
    for scene in source.scenes:
        scene_by_ordinal.append(
            (units[scene.first_unit_id].ordinal, units[scene.last_unit_id].ordinal, scene.title)
        )

    def scene_title(ordinal: int) -> str | None:
        return next((title for first, last, title in scene_by_ordinal if first <= ordinal <= last), None)

    passages: list[dict] = []
    previous = None
    for unit in sorted((units[unit_id] for unit_id in cited), key=lambda item: item.ordinal):
        if previous is None or unit.ordinal != previous + 1:
            passages.append({"scene_title": scene_title(unit.ordinal), "units": []})
        passages[-1]["units"].append({
            "id": unit.id,
            "ordinal": unit.ordinal,
            "segments": _segments(unit.text, unit.id in depicted, lettering.get(unit.id, [])),
        })
        previous = unit.ordinal

    if is_hybrid(target):
        elements, geometry = _placements(target, page)
        regions: dict[str, dict] = {}
    else:
        regions, geometry = _text_regions(target, page)
        elements = {}
    items = [item for content in sorted(page.content, key=lambda c: c.order) for item in content.lettering]
    return {
        "page_number": page.page_number,
        "page_revision": page.revision,
        "passages": passages,
        "lettering": [
            {
                "id": item.id,
                "text": item.text,
                "element": elements.get(item.id),
                "region": regions.get(item.id),
            }
            for item in items
        ],
        "geometry": geometry,
    }
