"""The page read: one vision look at the base art, reused by lettering.

The text check's single OCR call also locates heads (labelled by cast portrait
IDs). Editable lettering reads that stored evidence for the current render to
seed balloons above speakers and to show placement hints. It is derived
evidence: it never marks placement reviewed and is never requested here.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image

from novel_to_comic.artifacts import character_ref_pose_path
from novel_to_comic.models.draw import ObservedFigure, PageRenderRevision
from novel_to_comic.models.page import ComicPage
from novel_to_comic.page_ocr import CastPortrait, GatewayPageOCRAdapter
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts

MAX_PORTRAITS = 4  # Keeps the check's extra image input small and its price stable.
PORTRAIT_EDGE = 256


@dataclass(frozen=True)
class TextMark:
    text: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class PageRead:
    render_revision: int
    heads: tuple[ObservedFigure, ...] | None  # None: this read predates head reading.
    stray_lettering: tuple[TextMark, ...]  # Comic-style text on base art that should be quiet.
    in_world_text: tuple[TextMark, ...]  # Signs, labels, screens: worth not covering.


def speakers(page: ComicPage) -> tuple[str, ...]:
    """Onscreen speakers in order of first speech (Plan normalizes the rest to None)."""
    seen: dict[str, None] = {}
    for part in sorted(page.content, key=lambda part: part.order):
        for item in part.lettering:
            if item.delivery == "onscreen" and item.speaker_entity_id:
                seen.setdefault(item.speaker_entity_id)
    return tuple(seen)


def cast_portraits(artifacts: TargetArtifacts, page: ComicPage) -> tuple[CastPortrait, ...]:
    """Small approved portraits of the page's onscreen speakers, in the state drawn."""
    states: dict[str, str] = {}
    for part in sorted(page.content, key=lambda part: part.order):
        for entity, state in part.appearance_states.items():
            states.setdefault(entity, state)
    portraits = []
    for entity in speakers(page)[:MAX_PORTRAITS]:
        root = artifacts.project_dir / "refs" / entity
        candidates = [root / "states" / states[entity] / "portrait.png"] if entity in states else []
        candidates.append(character_ref_pose_path(artifacts.project_dir, entity, "portrait"))
        path = next((c for c in candidates if c.is_file()), None)
        if path is None:
            continue
        with Image.open(path) as opened:
            image = opened.convert("RGB")
        image.thumbnail((PORTRAIT_EDGE, PORTRAIT_EDGE), Image.Resampling.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        portraits.append(CastPortrait(entity_id=entity, image=buffer.getvalue()))
    return tuple(portraits)


def page_read_adapter(config, artifacts: TargetArtifacts, page: ComicPage) -> GatewayPageOCRAdapter:
    """The page read run with every draw; editable editions also label speakers' heads."""
    from .service import is_hybrid

    # Resolved when the page is read, inside the job: enqueueing reads no files.
    return GatewayPageOCRAdapter(
        config, page_number=page.page_number,
        portraits=lambda: cast_portraits(artifacts, page) if is_hybrid(artifacts) else (),
    )


def _bounds(polygon) -> tuple[float, float, float, float]:
    xs, ys = [p[0] for p in polygon], [p[1] for p in polygon]
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def read_for_render(
    artifacts: TargetArtifacts, page_number: int, render: PageRenderRevision
) -> PageRead | None:
    """Stored page read for exactly this art, or None. Never calls a provider."""
    try:
        raw = artifacts.read_raw_ocr(page_number, render.revision)
    except ArtifactMissing:
        return None
    if raw.render_image_sha256 != render.image_sha256:
        return None
    extraction = raw.extraction
    regions = {region.id: region for region in extraction.observed_regions}

    def marks(items) -> tuple[TextMark, ...]:
        result = []
        for item in items:
            # Every observation keeps its own box as region_NNN beside any panel citation.
            region = regions.get(item.id.replace("ocr_", "region_", 1))
            if region is not None:
                result.append(TextMark(item.text, *_bounds(region.polygon)))
        return tuple(result)

    return PageRead(
        render_revision=render.revision,
        heads=extraction.figures if raw.figures_read else None,
        stray_lettering=marks(extraction.lettering),
        in_world_text=marks(extraction.incidental_text),
    )


def draw_page_read(config, artifacts: TargetArtifacts, page: ComicPage) -> GatewayPageOCRAdapter | None:
    """The automatic read-back a draw job runs, or None when this project's draws skip it."""
    from novel_to_comic.server.codex_admission import draw_reads_pages

    return page_read_adapter(config, artifacts, page) if draw_reads_pages(config) else None
