"""Revisioned lettering editing, seeding and composite delivery; zero provider calls."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
from typing import Mapping, Sequence

from PIL import Image

from novel_to_comic.artifact_lock import locked_mutation, production_lock
from novel_to_comic.config import Config, load_config
from novel_to_comic.models.draw import PageRenderRevision
from novel_to_comic.models.lettering import (
    LetteringElement,
    LetteringRoles,
    LetteringStyle,
    PageLettering,
)
from novel_to_comic.models.page import ComicPage, NormalizedPoint, PinnedGeometry
from novel_to_comic.style_contract import (
    POST_LETTERING_MARKER,
    DESIGN_MARKER,
    lettering_design_from_template,
    post_production_lettering_direction,
)
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from . import placement
from .direction import direction_for, joined_to, mark_emphasis, voice_style
from .page_read import read_for_render
from .panels import detect_panels
from .renderer import (
    ENGINE_VERSION,
    render_lettered_page,
    resolve_lettering,
    validate_lettering_render,
)


class LetteringConflict(ValueError):
    """A draft must not overwrite a newer page, style, art selection or edit."""


def project_lettering_mode(artifacts: TargetArtifacts, config: Config) -> str:
    """Presentation follows the frozen edition, including retained baked books."""
    try:
        integrated = artifacts.read_book_edition().capability_profile.exact_visible_lettering
    except ArtifactMissing:
        return config.lettering_mode
    return "integrated" if integrated else "editable"


def is_hybrid(artifacts: TargetArtifacts) -> bool:
    try:
        return (
            not artifacts.read_book_edition().capability_profile.exact_visible_lettering
        )
    except ArtifactMissing:
        return False


def active_render(artifacts: TargetArtifacts, page_number: int):
    revisions = artifacts.provenance_revisions(page_number)
    if not revisions:
        raise LetteringConflict("Draw this page before editing lettering.")
    render = artifacts.read_provenance(page_number, revisions[-1]).render
    if render.is_stale_for(artifacts.read_page(page_number)):
        raise LetteringConflict(
            "The artwork belongs to an earlier plan. Draw the current page first."
        )
    return render


# Hand-lettered dialogue convention: all caps, a comic face, snug balloons.
_COMIC_VOICE = {"font": "Comic Neue", "min_font_size": 17, "max_font_size": 21, "text_case": "upper"}
# Book-wide lettering looks. Each patches the literary defaults per role.
PRESETS: dict[str, tuple[str, dict[str, dict]]] = {
    "literary": ("Literary classic", {}),
    "classic": ("Classic comic", {
        "caption": {"font": "Comic Neue", "min_font_size": 17, "max_font_size": 23, "text_case": "upper"},
        "speech": _COMIC_VOICE,
        "thought": _COMIC_VOICE,
        "sfx": {"color": "#ffe14d", "gradient_color": "#ff8a1f", "shadow": "extrude",
                "shadow_color": "#8c2a0e", "shadow_x": 4, "shadow_y": 5,
                "halo_color": "#181818", "halo_width": 1.2, "jitter": 0.2},
    }),
    "golden_age": ("Golden age", {
        "caption": {"font": "Comic Neue", "font_weight": 700, "fill": "#ffe36e", "stroke_width": 2,
                    "min_font_size": 17, "max_font_size": 22, "text_case": "upper"},
        "speech": {**_COMIC_VOICE, "stroke_width": 2},
        "thought": {**_COMIC_VOICE, "stroke_width": 2},
        "sfx": {"color": "#ff3b2f", "gradient_color": "#ffc93c", "text_stroke_width": 3,
                "shadow": "extrude", "shadow_color": "#181818", "shadow_x": 5, "shadow_y": 6,
                "jitter": 0.3, "skew": -6},
    }),
    "pulp": ("Pulp ink", {
        "caption": {"font": "Special Elite", "fill": "#fff0b8", "min_font_size": 18, "max_font_size": 24,
                    "shadow": "drop", "shadow_x": 3, "shadow_y": 3},
        "speech": _COMIC_VOICE,
        "thought": _COMIC_VOICE,
        "sfx": {"font": "Bungee", "color": "#fff0b8", "gradient_color": "#f5b642",
                "shadow": "drop", "shadow_x": 6, "shadow_y": 6, "skew": 8},
    }),
    "manga": ("Manga", {
        "caption": {"font": "Comic Neue", "fill": "#ffffff", "min_font_size": 16, "max_font_size": 20,
                    "stroke_width": 1.2, "text_case": "upper"},
        "speech": {**_COMIC_VOICE, "shape": "ellipse", "stroke_width": 1.3},
        "thought": {**_COMIC_VOICE, "shape": "wavy", "stroke_width": 1.2},
        "sfx": {"color": "#181818", "text_stroke": "#ffffff", "text_stroke_width": 3.5,
                "halo_color": "#181818", "halo_width": 1.2, "skew": -10, "jitter": 0.35},
    }),
    "noir": ("Noir", {
        "caption": {"font": "Special Elite", "fill": "#1b1b1b", "color": "#efe9dc", "stroke": "#1b1b1b",
                    "min_font_size": 17, "max_font_size": 22},
        "speech": _COMIC_VOICE,
        "thought": {**_COMIC_VOICE, "shape": "round", "fill": "#e9e6df", "corner_radius": 16},
        "sfx": {"color": "#f4f1ea", "text_stroke_width": 3, "shadow": "drop",
                "shadow_x": 5, "shadow_y": 5, "skew": 6},
    }),
    "horror": ("Horror", {
        "caption": {"font": "Special Elite", "fill": "#efe3c8", "color": "#3a2418", "stroke": "#3a2418",
                    "min_font_size": 17, "max_font_size": 22, "shadow": "drop", "shadow_color": "#0d0806",
                    "shadow_x": 3, "shadow_y": 3},
        "speech": _COMIC_VOICE,
        "thought": {**_COMIC_VOICE, "shape": "wavy", "fill": "#f3efe6"},
        # A pale knockout keeps dripping red legible over dark, firelit art.
        "sfx": {"font": "Creepster", "color": "#ff5a5f", "gradient_color": "#8e1022",
                "text_stroke": "#0a0a0a", "text_stroke_width": 2.5, "halo_color": "#f3e6c8",
                "halo_width": 1.4, "warp": "wave", "warp_amount": 0.22, "jitter": 0.12,
                "letter_spacing": 2.5},
    }),
    "scifi": ("Sci-fi", {
        "caption": {"font": "Exo 2", "fill": "#0f1d2b", "color": "#bfefff", "stroke": "#5ad1ff",
                    "shape": "round", "corner_radius": 6, "min_font_size": 16, "max_font_size": 21},
        "speech": {"font": "Exo 2", "min_font_size": 16, "max_font_size": 20, "text_case": "upper"},
        "thought": {"font": "Exo 2", "min_font_size": 16, "max_font_size": 20, "text_case": "upper"},
        "sfx": {"font": "Orbitron", "color": "#b8f4ff", "gradient_color": "#2a7fff",
                "text_stroke": "#06202a", "halo_color": "#b8f4ff", "halo_width": 1, "skew": 10},
    }),
    "storybook": ("Storybook", {
        "caption": {"font": "Baloo 2", "fill": "#fff6e0", "shape": "round", "corner_radius": 14,
                    "min_font_size": 17, "max_font_size": 23},
        "speech": {"font": "Baloo 2", "min_font_size": 17, "max_font_size": 22},
        "thought": {"font": "Baloo 2", "min_font_size": 17, "max_font_size": 22},
        "sfx": {"font": "Shrikhand", "color": "#ff6f61", "gradient_color": "#ffb347",
                "text_stroke": "#3b1f1a", "text_stroke_width": 2, "shadow": "drop",
                "shadow_color": "#3b1f1a", "shadow_x": 3, "shadow_y": 4, "warp": "arc", "warp_amount": 0.4},
    }),
    "minimal": ("Quiet modern", {
        "caption": {"font": "Comic Neue", "fill": "#ffffff", "stroke_width": 1,
                    "min_font_size": 17, "max_font_size": 24},
        "speech": {"font": "Comic Neue", "min_font_size": 17, "max_font_size": 21,
                   "stroke_width": 1, "corner_radius": 18},
        "thought": {"font": "Comic Neue", "min_font_size": 17, "max_font_size": 21},
    }),
}


def preset_style(
    name: str = "literary", *, direction: str = "", revision: int = 1
) -> LetteringStyle:
    label, patches = PRESETS.get(name) or PRESETS["literary"]
    roles = LetteringRoles().model_dump()
    for role, patch in patches.items():
        roles[role].update(patch)
    return LetteringStyle(
        revision=revision, label=label, source_direction=direction, roles=roles
    )


def style_from_template(template: str, *, revision: int = 1) -> LetteringStyle:
    """Seed software tokens from the selected design, without a provider call."""
    direction = post_production_lettering_direction(template)
    design = lettering_design_from_template(template)
    if design is not None:
        return LetteringStyle(
            revision=revision, label=design.label, source_direction=direction,
            roles=design.roles.model_dump(),
        )
    # Existing/custom directions do not falsely claim to have a generated design.
    prose = template.split(DESIGN_MARKER, 1)[0]
    name = prose.split(POST_LETTERING_MARKER)[-1].strip() if POST_LETTERING_MARKER in prose else "literary"
    return preset_style(name, direction=direction, revision=revision)


@locked_mutation
def ensure_style(artifacts: TargetArtifacts) -> LetteringStyle:
    try:
        return artifacts.read_lettering_style()
    except ArtifactMissing:
        style = style_from_template(load_config(artifacts.project_dir)[0].style_template)
        artifacts.write_lettering_style(style)
        return style


def _suggestion(
    reservation, panel, index: int, total: int, panel_count: int
) -> PinnedGeometry:
    if reservation.bounds is not None:
        return reservation.bounds
    # This is an EDITABLE suggestion, not a claim about observed raster panels.
    # Plan can supply page-space bounds for irregular grids; in their absence
    # arrange compact sequential reservations in conservative horizontal tiers.
    area = panel.pinned_geometry or PinnedGeometry(
        x=0.035,
        y=0.025 + (panel.order - 1) * 0.95 / panel_count,
        width=0.93,
        height=0.95 / panel_count,
    )
    fractions = {"compact": 0.42, "standard": 0.65, "wide": 0.94, "tall": 0.5}
    width = area.width * fractions[reservation.footprint]
    height = min(
        area.height * 0.85 / max(1, total),
        max(0.05, reservation.line_budget * 0.026 + 0.018),
    )
    zone = reservation.preferred_zone
    left = area.x + 0.012 * area.width
    if zone.endswith("right"):
        left = area.x + area.width - width - 0.012 * area.width
    elif zone.endswith("center"):
        left = area.x + (area.width - width) / 2
    top = area.y + area.height * 0.03 + index * height
    if zone.startswith("bottom"):
        top = area.y + area.height * 0.97 - height * (total - index)
    elif zone.startswith("middle"):
        top = area.y + (area.height - height * total) / 2 + index * height
    return PinnedGeometry(
        x=max(0, min(1 - width, left)),
        y=max(0, min(1 - height, top)),
        width=width,
        height=height,
    )


def default_tail_target(rect: PinnedGeometry) -> NormalizedPoint | None:
    """Provisional pointer: page-bounded, never a claim about detected speakers.

    Keep this insertion rule in parity with engine.mjs defaultTailTarget.
    Existing saved targets, including intentional None, are left untouched.
    """
    x, y, w, h = rect.x, rect.y, rect.width, rect.height
    if 1 - y - h > .025:
        return NormalizedPoint(x=x + w * .28, y=y + h + min(.06, (1 - y - h) * .7))
    if y > .025:
        return NormalizedPoint(x=x + w * .28, y=y - min(.06, y * .7))
    if 1 - x - w > .025:
        return NormalizedPoint(x=x + w + min(.06, (1 - x - w) * .7), y=y + h * .6)
    if x > .025:
        return NormalizedPoint(x=x - min(.06, x * .7), y=y + h * .6)
    return None


def seed_lettering(
    page: ComicPage,
    render,
    style: LetteringStyle,
    *,
    revision: int = 1,
    locale: str = "source",
    panels: Sequence[PinnedGeometry] | None = None,
    heads: Sequence = (),
    sources: Mapping[str, str] | None = None,
) -> PageLettering:
    """First-draft placement. ``panels`` (gutters of the base art) keep each item
    inside its drawn panel; ``heads`` (a stored page read) put speech over its
    speaker and off faces. Without panels Plan's reservations are used as-is.
    Either way these are seeds for the author, never reviewed placement.
    ``sources`` (source unit text) lets each seed take the voice its prose
    tags give it; see ``direction``.
    """
    if page.lettering_reservations is None:
        raise LetteringConflict(
            "This plan has no lettering reservations. Rerun Plan for a hybrid edition."
        )
    reservation_by_id = {
        item.lettering_item_id: item for item in page.lettering_reservations
    }
    layout = None
    if panels is not None and placement.usable(page, panels):
        layout = placement.layout_page(
            page, panels, lambda item, reservation, panel: placement.frame_size(reservation, panel),
            heads,
        )
    elements = []
    for panel in sorted(page.content, key=lambda part: part.order):
        for index, item in enumerate(panel.lettering):
            reservation = reservation_by_id[item.id]
            role = placement.ROLE[item.kind]
            voice = direction_for(item, sources or {})
            joined = index > 0 and joined_to(panel.lettering[index - 1], item)
            if layout is not None:
                # The tail is Plan's pointer when it fits the drawn panel.
                suggestion, tail_target = layout[item.id]
            else:
                suggestion = _suggestion(
                    reservation, panel, index, len(panel.lettering), len(page.content)
                )
                tail_target = reservation.tail_target
                if tail_target is None and placement.wants_tail(item):
                    tail_target = default_tail_target(suggestion)
            if joined:
                tail_target = None  # A joined balloon speaks through its lead's tail.
            elements.append(
                LetteringElement(
                    id=item.id,
                    source_lettering_item_id=item.id,
                    role=role,
                    # Stress is display markup; the canonical words are untouched.
                    text_by_locale={"source": mark_emphasis(item.text, voice.emphasis)},
                    suggested_placement=suggestion,
                    placement=suggestion,
                    tail_target=tail_target,
                    suggested_tail_target=tail_target,
                    style_override=(
                        voice_style(getattr(style.roles, role), role, voice.voice)
                        if voice.voice else None
                    ),
                    link_to=panel.lettering[index - 1].id if joined else None,
                    z_index=len(elements),
                )
            )
    return PageLettering(
        revision=revision,
        page_number=page.page_number,
        comic_page_sha256=page.content_sha256,
        style_sha256=style.content_sha256,
        locale=locale,
        canvas_aspect_ratio=render.width / render.height,
        elements=elements,
    )


_FRAME_SLACK = 0.002  # Keeps the measured wrap feasible when the page edge trims a frame.


def settle_seeds(
    state: PageLettering,
    page: ComicPage,
    style: LetteringStyle,
    panels: Sequence[PinnedGeometry] | None,
    heads: Sequence = (),
) -> PageLettering:
    """Resolve a fresh seed, then arrange it again with measured balloon sizes.

    Tight balloons anchor at their frame's top-left, so a balloon lands where
    it is arranged once its real size is known and its frame's corner moves
    there. Frames keep Plan's roomier size so longer translations still fit;
    only the page edge trims them. An element whose wrap would change keeps
    its first frame and may shift left or up to stay on the page.
    """
    first = resolve_lettering(state, style)
    if panels is None or not placement.usable(page, panels):
        return first
    measured = {element.id: element for element in first.elements}

    def fits(element: LetteringElement) -> bool:
        return element.tight_box and element.resolved is not None and not element.resolved.overflow

    def size_of(item, reservation, panel):
        element = measured[item.id]
        if fits(element):
            return element.resolved.width, element.resolved.height
        return element.placement.width, element.placement.height

    layout = placement.layout_page(page, panels, size_of, heads)

    def moved(element: LetteringElement, keep_frame: bool) -> LetteringElement:
        body, tail = layout[element.id]
        width, height = element.placement.width, element.placement.height
        if fits(element) and not keep_frame:
            width = max(min(width, 1 - body.x), min(1 - body.x, body.width + _FRAME_SLACK))
            height = max(min(height, 1 - body.y), min(1 - body.y, body.height + _FRAME_SLACK))
        frame = PinnedGeometry(
            x=min(body.x, 1 - min(1.0, width)), y=min(body.y, 1 - min(1.0, height)),
            width=min(1.0, width), height=min(1.0, height),
        )
        if element.tail_target is None:
            tail = None  # Captions, offscreen and narrated copy have no tail.
        return element.model_copy(update={
            "placement": frame, "suggested_placement": frame,
            "tail_target": tail, "suggested_tail_target": tail, "resolved": None,
        })

    second = resolve_lettering(
        _replace(first, elements=[moved(e, False) for e in first.elements]), style
    )
    changed = {
        element.id
        for element in second.elements
        if fits(measured[element.id]) and (
            element.resolved is None
            or element.resolved.lines != measured[element.id].resolved.lines
            or element.resolved.font_size != measured[element.id].resolved.font_size
        )
    }
    if not changed:
        return second
    return resolve_lettering(
        _replace(first, elements=[moved(e, e.id in changed) for e in first.elements]), style
    )


def page_panels(artifacts: TargetArtifacts, page_number: int, render) -> tuple[PinnedGeometry, ...]:
    with Image.open(io.BytesIO(artifacts.read_render(page_number, render.revision))) as image:
        return detect_panels(image)


def source_texts(artifacts: TargetArtifacts, page: ComicPage) -> dict[str, str]:
    """Source prose cited by this page's lettering, for voice direction only."""
    cited = {
        unit for panel in page.content for item in panel.lettering for unit in item.source_unit_ids
    }
    if not cited:
        return {}
    try:
        units = artifacts.read_source().units
    except ArtifactMissing:
        return {}
    return {unit.id: unit.text for unit in units if unit.id in cited}


def seed_page(
    artifacts: TargetArtifacts,
    page: ComicPage,
    render,
    style: LetteringStyle,
    *,
    revision: int = 1,
    locale: str = "source",
) -> PageLettering:
    """Resolved first-draft lettering for the current art. Placement review stays pending.

    Uses a stored page read for this exact art when there is one; never requests one.
    """
    panels = page_panels(artifacts, page.page_number, render)
    read = read_for_render(artifacts, page.page_number, render)
    heads = (read.heads or ()) if read is not None else ()
    return settle_seeds(
        seed_lettering(
            page, render, style, revision=revision, locale=locale, panels=panels, heads=heads,
            sources=source_texts(artifacts, page),
        ),
        page, style, panels, heads,
    )


@locked_mutation
def ensure_lettering(artifacts: TargetArtifacts, page_number: int) -> PageLettering:
    if not is_hybrid(artifacts):
        raise LetteringConflict(
            "This edition has lettering baked into its artwork. Start a new Draw edition to use editable lettering."
        )
    try:
        return artifacts.read_lettering(page_number)
    except ArtifactMissing:
        style = ensure_style(artifacts)
        state = seed_page(
            artifacts,
            artifacts.read_page(page_number),
            active_render(artifacts, page_number),
            style,
            locale=artifacts.read_lettering_settings().locale,
        )
        artifacts.write_lettering(state)
        return state


_POSITION = {"placement", "suggested_placement", "tail_target", "suggested_tail_target", "resolved"}


def _untouched_seed(saved: PageLettering, fresh: PageLettering) -> bool:
    """Nobody has edited this page: it is still a seed apart from where it sits."""
    if saved.reviewed_against_render_revision is not None or saved.locale != fresh.locale:
        return False
    if [e.id for e in saved.elements] != [e.id for e in fresh.elements]:
        return False
    return all(
        old.placement == old.suggested_placement
        and old.tail_target == old.suggested_tail_target
        and old.model_dump(exclude=_POSITION) == new.model_dump(exclude=_POSITION)
        for old, new in zip(saved.elements, fresh.elements, strict=True)
    )


@locked_mutation
def reseed_after_read(artifacts: TargetArtifacts, page_number: int) -> bool:
    """Re-place an untouched seed once a page read of the current art lands.

    Drawing reads each page back automatically; a seed made before that read
    finished (or for earlier art) moves to its speakers' faces. Any author
    edit, review or translation keeps the saved lettering as it is. The
    result is still a seed: placement review stays pending.
    """
    if not is_hybrid(artifacts):
        return False
    try:
        saved = artifacts.read_lettering(page_number)
    except ArtifactMissing:
        return False  # Seeded lazily later, already with the read.
    page = artifacts.read_page(page_number)
    if saved.comic_page_sha256 != page.content_sha256:
        return False
    fresh = seed_page(
        artifacts, page, active_render(artifacts, page_number), ensure_style(artifacts),
        revision=saved.revision + 1, locale=saved.locale,
    )
    if not _untouched_seed(saved, fresh) or [e.placement for e in fresh.elements] == [
        e.placement for e in saved.elements
    ]:
        return False
    artifacts.write_lettering(fresh)
    return True


def _replace(state: PageLettering, **values) -> PageLettering:
    return PageLettering.model_validate(
        state.model_dump() | values | {"content_sha256": ""}
    )


@locked_mutation
def editor_state(artifacts: TargetArtifacts, page_number: int) -> dict:
    if not is_hybrid(artifacts):
        return {
            "mode": "baked",
            "message": "This edition's words are part of the artwork; no overlay is added.",
        }
    render = active_render(artifacts, page_number)
    page = artifacts.read_page(page_number)
    style = ensure_style(artifacts)
    saved = ensure_lettering(artifacts, page_number)
    settings = artifacts.read_lettering_settings()
    source_stale = saved.comic_page_sha256 != page.content_sha256
    reflow = (
        saved.locale != settings.locale
        or saved.style_sha256 != style.content_sha256
        or abs(saved.canvas_aspect_ratio - render.width / render.height) > 1e-8
        or any(
            element.resolved is None
            or element.resolved.engine_version != ENGINE_VERSION
            for element in saved.elements
        )
    )
    state = saved
    if reflow and not source_stale:
        state = resolve_lettering(
            _replace(
                saved, locale=settings.locale,
                canvas_aspect_ratio=render.width / render.height,
                reviewed_against_render_revision=None,
                reviewed_against_image_sha256=None,
            ), style
        )
    return {
        "mode": "hybrid",
        "state": state,
        "style": style,
        "settings": settings,
        "saved_revision": saved.revision,
        "render_revision": render.revision,
        "render_image_sha256": render.image_sha256,
        "source_stale": source_stale,
        "needs_save": reflow,
        "placement_review_needed": source_stale or placement_review_needed(state, render),
        "evidence": placement_evidence(artifacts, page, render),
        "canonical": {
            item.id: {
                "text": item.text,
                "kind": item.kind,
                "speaker": item.speaker,
                "delivery": item.delivery,
                "panel_number": part.order,
            }
            for part in page.content
            for item in part.lettering
        },
    }


def placement_evidence(
    artifacts: TargetArtifacts, page: ComicPage, render
) -> dict:
    """What the editor's live placement checks read; free and provider-free.

    Panels come from the art's gutters. ``page_read`` is the stored text
    check for exactly this art (heads, stray lettering, in-world writing), or
    None when the page has not been checked. Hints only, never acceptance.
    """
    read = read_for_render(artifacts, page.page_number, render)
    speakers = {
        item.id: item.speaker_entity_id if item.delivery == "onscreen" else None
        for part in page.content for item in part.lettering
    }
    names = {
        item.speaker_entity_id: item.speaker
        for part in page.content for item in part.lettering
        if item.speaker_entity_id and item.speaker
    }
    rect = lambda r: {"x": r.x, "y": r.y, "width": r.width, "height": r.height}  # noqa: E731
    return {
        "panels": [rect(p) for p in page_panels(artifacts, page.page_number, render)],
        "speakers": speakers,
        "speaker_names": names,
        "page_read": None if read is None else {
            "render_revision": read.render_revision,
            "heads": None if read.heads is None else [
                {"id": h.id, "entity_id": h.entity_id, **rect(h)} for h in read.heads
            ],
            "stray_lettering": [{"text": m.text, **rect(m)} for m in read.stray_lettering],
            "in_world_text": [{"text": m.text, **rect(m)} for m in read.in_world_text],
        },
    }


def suggested_placements(artifacts: TargetArtifacts, page_number: int) -> dict:
    """A fresh first draft for the current art, as a proposal only.

    Nothing is saved: the editor applies it as an undoable draft change and
    the author still confirms placement. Suggested placement stays the seed.
    """
    if not is_hybrid(artifacts):
        raise LetteringConflict("This edition's words are part of the artwork.")
    render = active_render(artifacts, page_number)
    page = artifacts.read_page(page_number)
    seeded = seed_page(
        artifacts, page, render, ensure_style(artifacts),
        locale=artifacts.read_lettering_settings().locale,
    )
    return {
        "render_revision": render.revision,
        "render_image_sha256": render.image_sha256,
        "uses_faces": bool((read := read_for_render(artifacts, page_number, render)) and read.heads),
        "elements": {
            element.id: {"placement": element.placement, "tail_target": element.tail_target}
            for element in seeded.elements
        },
    }


def _engine_stale(state: PageLettering) -> bool:
    return any(
        element.resolved is None or element.resolved.engine_version != ENGINE_VERSION
        for element in state.elements
    )


def placement_review_needed(state: PageLettering, render: PageRenderRevision) -> bool:
    """Visual acceptance belongs to this saved presentation and artwork only.

    A layout from an earlier engine renders differently than what was accepted.
    """
    return (
        state.reviewed_against_render_revision != render.revision
        or state.reviewed_against_image_sha256 != render.image_sha256
        or _engine_stale(state)
    )


@locked_mutation
def save_lettering(
    artifacts: TargetArtifacts,
    page_number: int,
    incoming: PageLettering,
    *,
    expected_revision: int,
    expected_image_sha256: str,
    expected_style_sha256: str,
    mark_reviewed: bool = False,
) -> PageLettering:
    saved = ensure_lettering(artifacts, page_number)
    render = active_render(artifacts, page_number)
    page = artifacts.read_page(page_number)
    style = ensure_style(artifacts)
    if incoming.locale != artifacts.read_lettering_settings().locale:
        raise LetteringConflict("Lettering language belongs to the project. Use Translate project to change it.")
    if (
        saved.revision != expected_revision
        or render.image_sha256 != expected_image_sha256
        or style.content_sha256 != expected_style_sha256
    ):
        raise LetteringConflict(
            "The page, artwork or book style changed elsewhere. Your draft is kept; reload before applying it."
        )
    if (
        incoming.page_number != page_number
        or incoming.comic_page_sha256 != page.content_sha256
        or saved.comic_page_sha256 != page.content_sha256
    ):
        raise LetteringConflict(
            "The source plan changed. Rebuild lettering explicitly; the previous version is retained."
        )
    canonical = {
        item.id: item
        for part in sorted(page.content, key=lambda part: part.order)
        for item in part.lettering
    }
    sources = {
        item.source_lettering_item_id
        for item in incoming.elements
        if item.source_lettering_item_id is not None
    }
    if sources != canonical.keys():
        raise ValueError(
            "Preserve each source-backed element exactly once. Hide unwanted elements instead of removing them."
        )
    if [
        item.source_lettering_item_id
        for item in incoming.elements
        if item.source_lettering_item_id is not None
    ] != list(canonical):
        raise ValueError(
            "Source-backed elements must retain the locked reading order. Use z-order for layering."
        )
    previous = {item.id: item for item in saved.elements}
    for element in incoming.elements:
        source = canonical.get(element.source_lettering_item_id)
        if source is not None:
            old = previous.get(element.id)
            if old is None or old.source_lettering_item_id != source.id:
                raise ValueError("Source-backed element identity cannot be replaced.")
            if (
                element.suggested_placement != old.suggested_placement
                or element.suggested_tail_target != old.suggested_tail_target
            ):
                raise ValueError(
                    "Suggested placement is retained for Reset placement; edit placement instead."
                )
            if element.tail_target is not None and (
                source.delivery != "onscreen"
                or source.kind not in {"dialogue", "thought"}
            ):
                raise ValueError(
                    "Offscreen copy and captions cannot point to a visible speaker."
                )
    state = _replace(
        incoming,
        revision=saved.revision + 1,
        canvas_aspect_ratio=render.width / render.height,
        reviewed_against_render_revision=None,
        reviewed_against_image_sha256=None,
    )
    state = resolve_lettering(
        state, style
    )  # Never trust client-supplied resolved lines or visual-review markers.
    excluded = {
        "revision", "content_sha256", "reviewed_against_render_revision",
        "reviewed_against_image_sha256",
    }
    unchanged = state.model_dump(exclude=excluded) == saved.model_dump(exclude=excluded)
    if mark_reviewed or unchanged:
        state = _replace(
            state,
            reviewed_against_render_revision=(
                render.revision if mark_reviewed else saved.reviewed_against_render_revision
            ),
            reviewed_against_image_sha256=(
                render.image_sha256 if mark_reviewed else saved.reviewed_against_image_sha256
            ),
        )
    artifacts.write_lettering(state)
    return state


@locked_mutation
def reset_lettering(
    artifacts: TargetArtifacts,
    page_number: int,
    *,
    expected_revision: int,
    expected_image_sha256: str,
) -> PageLettering:
    previous = ensure_lettering(artifacts, page_number)
    render = active_render(artifacts, page_number)
    if (
        previous.revision != expected_revision
        or render.image_sha256 != expected_image_sha256
    ):
        raise LetteringConflict(
            "The page changed. Reload before rebuilding its lettering."
        )
    style = ensure_style(artifacts)
    state = seed_page(
        artifacts,
        artifacts.read_page(page_number),
        render,
        style,
        revision=previous.revision + 1,
        locale=artifacts.read_lettering_settings().locale,
    )
    artifacts.write_lettering(state)
    return state


@locked_mutation
def save_style(
    artifacts: TargetArtifacts, incoming: LetteringStyle, *, expected_revision: int
) -> LetteringStyle:
    current = ensure_style(artifacts)
    if current.revision != expected_revision:
        raise LetteringConflict(
            "Book lettering style changed elsewhere. Reload before applying your style."
        )
    style = LetteringStyle.model_validate(
        incoming.model_dump() | {"revision": current.revision + 1, "content_sha256": ""}
    )
    updates = []
    # Reflow all current pages first; a measurement failure publishes nothing.
    try:
        pages = artifacts.read_plan().pages
    except ArtifactMissing:
        pages = ()  # Style can be designed before Plan/Draw exist.
    for selected in pages:
        try:
            state = artifacts.read_lettering(selected.page_number)
        except ArtifactMissing:
            continue
        if (
            state.comic_page_sha256
            != artifacts.read_page(selected.page_number).content_sha256
        ):
            continue  # Keep stale-source drafts recoverable, never silently reseed.
        updates.append(
            resolve_lettering(_replace(
                state, revision=state.revision + 1,
                reviewed_against_render_revision=None,
                reviewed_against_image_sha256=None,
            ), style)
        )
    for state in updates:
        artifacts.write_lettering(state)
    artifacts.write_lettering_style(style)
    return style


def composite_identity(render, state: PageLettering, style: LetteringStyle) -> str:
    return hashlib.sha256(
        json.dumps(
            [
                render.image_sha256,
                state.content_sha256,
                state.locale,
                style.content_sha256,
                ENGINE_VERSION,
            ],
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def stores_locale(state: PageLettering, locale: str) -> bool:
    """Translation's ``translate_count == 0`` rule: every element, hidden ones too."""
    return all(locale in element.text_by_locale for element in state.elements)


@locked_mutation
def render_stored_locale(
    artifacts: TargetArtifacts,
    page_number: int,
    locale: str,
    *,
    expected_render_revision: int,
) -> bytes:
    """Letter the current art in another stored language; the project is unchanged.

    The saved placement is laid out again for ``locale`` in memory and must pass
    publication validation (no overflow, warnings or missing copy).
    """
    if not is_hybrid(artifacts):
        raise LetteringConflict("Baked lettering has no other languages.")
    render = active_render(artifacts, page_number)
    if render.revision != expected_render_revision:
        raise LetteringConflict("The selected artwork changed. Refresh the page preview.")
    state = artifacts.read_lettering(page_number)
    style = artifacts.read_lettering_style()
    if state.comic_page_sha256 != artifacts.read_page(page_number).content_sha256:
        raise LetteringConflict(
            "Lettering belongs to an earlier plan. Open Lettering and rebuild it explicitly."
        )
    if not stores_locale(state, locale):
        raise LetteringConflict(
            f"Page {page_number} has lettering without a saved {locale} translation."
        )
    localized = resolve_lettering(_replace(state, locale=locale), style)
    validate_lettering_render(localized, style, render.width, render.height)
    image = artifacts.read_render(page_number, render.revision)
    if hashlib.sha256(image).hexdigest() != render.image_sha256:
        raise ValueError("Base artwork checksum does not match its provenance.")
    identity = composite_identity(render, localized, style)
    path = artifacts.composite_path(page_number, identity)
    if path.is_file():
        return path.read_bytes()
    data = render_lettered_page(localized, style, image, render.width, render.height)
    artifacts.write_composite(page_number, identity, data)
    return data


# Pages whose saved layout predates the current engine are laid out again for
# every preview. Remember those layouts, so a gallery of thumbnails does not
# relaunch the renderer for each page on each view.
_RELAID: dict[tuple[str, str], PageLettering] = {}


def _current_layout(state: PageLettering, style: LetteringStyle) -> PageLettering:
    key = (state.content_sha256, style.content_sha256)
    if key not in _RELAID:
        if len(_RELAID) >= 256:
            _RELAID.clear()
        _RELAID[key] = resolve_lettering(state, style)
    return _RELAID[key]


def composite_page(
    artifacts: TargetArtifacts,
    page_number: int,
    *,
    rendition: str = "full",
    expected_render_revision: int | None = None,
    draft_preview: bool = False,
) -> tuple[Path, str | None]:
    """Lettered page preview. Reads and decisions hold the production lock; the
    renderer does not, because composites are content-addressed derivatives
    (a slow render must not stall every other request for the project)."""
    with production_lock(artifacts.project_dir):
        render = active_render(artifacts, page_number)
        if rendition not in {"full", "reader", "thumbnail"}:
            raise ValueError("Unknown preview rendition.")
        if (
            expected_render_revision is not None
            and render.revision != expected_render_revision
        ):
            raise LetteringConflict(
                "The selected artwork changed. Refresh the page preview."
            )
        if not is_hybrid(artifacts):
            if rendition == "full":
                return artifacts.render_path(page_number, render.revision), None
            from novel_to_comic.page_previews import ensure_page_render_preview

            return ensure_page_render_preview(
                artifacts,
                page_number=page_number,
                render_revision=render.revision,
                rendition=rendition,
            ), None
        state = ensure_lettering(artifacts, page_number)
        if state.locale != artifacts.read_lettering_settings().locale:
            raise LetteringConflict(
                "Page locale differs from project lettering language. Open Lettering and save its reflow, or translate the project before exporting."
            )
        style = ensure_style(artifacts)
        if state.comic_page_sha256 != artifacts.read_page(page_number).content_sha256:
            raise LetteringConflict(
                "Lettering belongs to an earlier plan. Open Lettering and rebuild it explicitly."
            )
    if _engine_stale(state) and state.style_sha256 == style.content_sha256:
        # An engine upgrade only changes measurement, not the author's copy,
        # placement or style. Lay it out again here, as the editor does, rather
        # than blocking every page until it is opened. Nothing is saved: an
        # open editor's revision stays valid, and placement still needs review.
        state = _current_layout(state, style)
    # Publication must validate even when a draft preview already populated the cache.
    validate_lettering_render(
        state, style, render.width, render.height, draft_preview=draft_preview
    )
    identity = composite_identity(render, state, style)
    path = artifacts.composite_path(page_number, identity, rendition)
    # Always validate/read raw art separately from lettering. Its bytes never change.
    image = artifacts.read_render(page_number, render.revision)
    if hashlib.sha256(image).hexdigest() != render.image_sha256:
        raise ValueError("Base artwork checksum does not match its provenance.")
    if path.is_file():
        return path, identity
    full = artifacts.composite_path(page_number, identity)
    if not full.is_file():
        data = render_lettered_page(
            state, style, image, render.width, render.height, draft_preview=draft_preview
        )
        artifacts.write_composite(page_number, identity, data)
    if rendition == "full":
        return full, identity
    max_width = {"thumbnail": 424, "reader": 1024}.get(rendition)
    if max_width is None:
        raise ValueError("Unknown preview rendition.")
    with Image.open(full) as opened:
        preview = opened.convert("RGB")
        preview.thumbnail(
            (max_width, round(max_width * render.height / render.width)),
            Image.Resampling.LANCZOS,
        )
        output = io.BytesIO()
        preview.save(output, format="WEBP", quality=86, method=6)
    return artifacts.write_composite(
        page_number, identity, output.getvalue(), rendition
    ), identity
