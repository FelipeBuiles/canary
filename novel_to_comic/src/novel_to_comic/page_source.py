"""Read-only manuscript view for one planned page (Pages → Source).

A page maps back to the manuscript through three canonical links: its
content items cite Adapt beats, beats cite source units, and each canonical
lettering item cites the exact source units it was written from. The
adaptation ledger says which beat units are depicted rather than lettered.
Lettering is panel-level; depiction is beat-level, so a depicted unit points
at every panel on this page that carries its beat.

Panel outlines are derived evidence only: OCR panel boxes observed on the
page's current render. They are never canonical layout and are omitted
whenever they cannot be tied to planned panels. Nothing here calls a
provider or writes artifacts.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Literal

from novel_to_comic.models.draw import RenderAnalysis
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
    depicted: tuple[str, ...] | None,
    lettering: list[tuple[str, str]],
) -> list[dict]:
    """Split one unit into plain and marked runs.

    ``lettering`` holds (content_id, canonical text) pairs citing this unit.
    Verbatim words are marked when the copy quotes the manuscript; a
    paraphrase marks the whole unit, since the citation itself is canonical.
    """

    labels: list[tuple[MarkKind, tuple[str, ...]] | None] = [None] * len(text)
    if depicted is not None:
        start, end = _trimmed(text)
        for index in range(start, end):
            labels[index] = ("depicted", depicted)
    for content_id, copy in lettering:
        spans = _verbatim_spans(text, copy) or [_trimmed(text)]
        for start, end in spans:
            for index in range(start, end):
                current = labels[index]
                ids = current[1] if current and current[0] == "lettering" else ()
                if content_id not in ids:
                    ids = (*ids, content_id)
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
        if segments and segments[-1]["kind"] == kind and segments[-1]["content_ids"] == list(ids):
            segments[-1]["text"] += run_text
        else:
            segments.append({"text": run_text, "kind": kind, "content_ids": list(ids)})
    return segments


def _box(polygon) -> dict:
    xs = [point[0] for point in polygon]
    ys = [point[1] for point in polygon]
    x, y = max(0.0, min(xs)), max(0.0, min(ys))
    return {"x": x, "y": y, "width": min(1.0, max(xs)) - x, "height": min(1.0, max(ys)) - y}


def _panel_boxes(page: ComicPage, analysis: RenderAnalysis) -> dict[str, dict]:
    """Tie observed panel boxes to planned content items, or return nothing.

    Two derived links are accepted: a content item's matched lettering all
    falls inside one observed panel, and a proven observed reading order whose
    panel count equals the plan's (used only when it agrees with every
    lettering-grounded link). Ambiguous items get no outline.
    """

    regions = {region.id: region for region in analysis.observed_regions if region.id.startswith("panel_")}
    if not regions:
        return {}
    region_by_observation = {
        item.id: item.detected_region_id for item in analysis.ocr_observations
    }
    content_by_lettering = {
        item.id: content.id for content in page.content for item in content.lettering
    }
    grounded: dict[str, set[str]] = {}
    for match in analysis.lettering_matches:
        region_id = region_by_observation.get(match.observation_id)
        content_id = content_by_lettering.get(match.lettering_item_id)
        if content_id is None:
            continue
        grounded.setdefault(content_id, set()).add(region_id if region_id and region_id in regions else "")
    assigned = {
        content_id: next(iter(found))
        for content_id, found in grounded.items()
        if len(found) == 1 and "" not in found
    }
    ordered = sorted(page.content, key=lambda item: item.order)
    if analysis.reading_order_proven and len(analysis.observed_reading_order) == len(ordered):
        by_order = {
            content.id: region_id
            for content, region_id in zip(ordered, analysis.observed_reading_order)
        }
        if all(by_order[content_id] == region_id for content_id, region_id in assigned.items()):
            assigned = by_order
    claimed: dict[str, int] = {}
    for region_id in assigned.values():
        claimed[region_id] = claimed.get(region_id, 0) + 1
    return {
        content_id: _box(regions[region_id].polygon)
        for content_id, region_id in assigned.items()
        if claimed[region_id] == 1
    }


def _current_analysis(target: TargetArtifacts, page: ComicPage) -> RenderAnalysis | None:
    revisions = target.provenance_revisions(page.page_number)
    if not revisions:
        return None
    try:
        render = target.read_provenance(page.page_number, revisions[-1]).render
        analysis = target.read_analysis(page.page_number, render.revision)
    except (ArtifactMissing, ArtifactInvalid):
        # The text check is optional evidence; without it there are no outlines.
        return None
    if (
        analysis.render_image_sha256 != render.image_sha256
        or analysis.comic_page_sha256 != page.content_sha256
    ):
        return None
    return analysis


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
    content_by_beat: dict[str, list[str]] = {}
    for content in sorted(page.content, key=lambda item: item.order):
        for beat_id in content.beat_ids:
            content_by_beat.setdefault(beat_id, []).append(content.id)
    unknown_beats = set(content_by_beat) - set(beats)
    if unknown_beats:
        raise PageSourceStale(
            f"Page {page_number} cites beats missing from the adaptation "
            f"({', '.join(sorted(unknown_beats))}). Re-run Plan."
        )

    lettering: dict[str, list[tuple[str, str]]] = {}
    for content in page.content:
        for item in content.lettering:
            for unit_id in item.source_unit_ids:
                lettering.setdefault(unit_id, []).append((content.id, item.text))
    depicted: dict[str, tuple[str, ...]] = {}
    for entry in adaptation.ledger:
        if entry.disposition not in _DEPICTED:
            continue
        panels = [
            content_id
            for beat_id in entry.adapted_beat_ids
            for content_id in content_by_beat.get(beat_id, ())
        ]
        if panels:
            depicted[entry.source_unit_id] = tuple(dict.fromkeys(panels))

    cited = {
        unit_id for beat_id in content_by_beat for unit_id in beats[beat_id].source_unit_ids
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
            "segments": _segments(unit.text, depicted.get(unit.id), lettering.get(unit.id, [])),
        })
        previous = unit.ordinal

    analysis = _current_analysis(target, page)
    boxes = _panel_boxes(page, analysis) if analysis is not None else {}
    geometry_revision = analysis.render_revision if analysis is not None and boxes else None
    return {
        "page_number": page.page_number,
        "page_revision": page.revision,
        "passages": passages,
        "panels": [
            {
                "id": content.id,
                "order": content.order,
                "panel_role": content.panel_role,
                "box": boxes.get(content.id),
            }
            for content in sorted(page.content, key=lambda item: item.order)
        ],
        "geometry_render_revision": geometry_revision,
    }
