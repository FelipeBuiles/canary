"""Artifact orchestration for provider-free lettering; no AI/billing imports."""

from __future__ import annotations

import io
import os
from uuid import uuid4
from PIL import Image
from novel_to_comic.models.lettering import PageLettering, ResolvedText
from novel_to_comic.page_lettering import (
    composite_identity,
    compose_page,
    initial_style,
    overlay_svg,
    reservations_for_page,
    resolve_lettering,
    seed_lettering,
)
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts


def hybrid_edition(artifacts: TargetArtifacts) -> bool:
    return not artifacts.read_book_edition().capability_profile.exact_visible_lettering


def default_style(artifacts: TargetArtifacts):
    from novel_to_comic.config import load_config
    from novel_to_comic.models.lettering import LetteringStyle
    from novel_to_comic.stages.s2_style import load_suggestions
    from novel_to_comic.style_contract import (
        page_style_template,
        postproduction_lettering_direction,
        style_template_for_suggestion,
    )

    config, _ = load_config(artifacts.project_dir)
    direction = postproduction_lettering_direction(config.style_template)
    try:
        saved = artifacts.read_lettering_style()
        if saved.direction == direction:
            return saved
    except ArtifactMissing:
        pass
    for suggestion in load_suggestions(artifacts.project_dir):
        if style_template_for_suggestion(suggestion) == page_style_template(
            config.style_template
        ) and suggestion.get("lettering_style"):
            return LetteringStyle.model_validate(
                suggestion["lettering_style"]
            ).model_copy(update={"direction": direction})
    # Retained suggestions predate executable tokens. Their prose is shown in
    # the editor; a curated preset is an editable starting point, not a claim
    # that arbitrary historic prose can be reproduced exactly.
    return initial_style(direction)


def page_aspect(artifacts: TargetArtifacts, page_number: int):
    revisions = artifacts.provenance_revisions(page_number)
    if not revisions:
        raise ValueError("Draw this page before editing its lettering")
    revision = revisions[-1]
    with Image.open(io.BytesIO(artifacts.read_render(page_number, revision))) as image:
        return image.height / image.width, revision


def load_lettering(
    artifacts: TargetArtifacts, page_number: int, aspect: float, *, reseed: bool = False
):
    page = artifacts.read_page(page_number)
    if not reseed:
        try:
            state = artifacts.read_lettering(page_number)
            if state.comic_page_sha256 != page.content_sha256:
                raise ValueError(
                    "Plan changed. Export your lettering draft, then explicitly reset lettering for this page."
                )
            return state
        except ArtifactMissing:
            pass
    try:
        reserved = artifacts.read_reservations(page_number)
    except ArtifactMissing:
        reserved = reservations_for_page(page)
    return seed_lettering(page, reserved, default_style(artifacts), aspect)


def prepare_lettering(artifacts: TargetArtifacts, state: PageLettering):
    if not hybrid_edition(artifacts):
        raise ValueError(
            "This retained edition has baked-in text. Create a fresh Draw edition for editable lettering; no text removal is performed."
        )
    aspect, revision = page_aspect(artifacts, state.page_number)
    if sum(len(copy) for e in state.elements for copy in e.copies.values()) > 30000:
        raise ValueError("Page lettering exceeds the 30,000 character editing limit")
    if state.reviewed_against_render_revision not in {None, revision}:
        raise ValueError(
            "Artwork changed while editing. Review placement against the current render before marking it checked."
        )
    # Resolved lines arriving from HTTP are untrusted, even with a matching signature.
    state = state.model_copy(
        update={
            "elements": tuple(
                e.model_copy(update={"resolved": ResolvedText()})
                for e in state.elements
            )
        }
    )
    resolved = resolve_lettering(state, artifacts.read_page(state.page_number), aspect)
    return resolved, aspect, revision


def response_payload(artifacts, state, aspect, revision):
    saved = (
        artifacts.read_lettering(state.page_number)
        if artifacts.lettering_path(state.page_number).exists()
        else None
    )
    page = artifacts.read_page(state.page_number)
    items = {i.id: i for p in page.content for i in p.lettering}
    return {
        "mode": "editable",
        "state": state,
        "svg": overlay_svg(state, aspect, embed_fonts=False),
        "aspect": aspect,
        "render_revision": revision,
        "saved_sha256": saved.content_sha256 if saved else None,
        "saved_revision": saved.revision if saved else 0,
        "canonical_copy": {key: item.text for key, item in items.items()},
        "placement_needs_review": state.reviewed_against_render_revision != revision,
    }


def save_lettering(artifacts, state, *, expected_sha256):
    """Caller holds lettering_lock across read/resolve/CAS/Finish invalidation."""
    resolved, aspect, render_revision = prepare_lettering(artifacts, state)
    saved = PageLettering(
        **(
            resolved.model_dump(exclude={"content_sha256", "revision"})
            | {"revision": artifacts.next_lettering_revision(state.page_number)}
        )
    )
    artifacts.write_lettering(saved, expected_sha256=expected_sha256)
    return response_payload(artifacts, saved, aspect, render_revision)


def saved_composite(artifacts, page_number: int, image: bytes):
    with Image.open(io.BytesIO(image)) as art:
        aspect = art.height / art.width
    state = load_lettering(artifacts, page_number, aspect)
    checked = resolve_lettering(state, artifacts.read_page(page_number), aspect)
    if checked.content_sha256 != state.content_sha256:
        raise ValueError(
            "Lettering layout needs refresh. Open Lettering and save before exporting."
        )
    identity = composite_identity(image, state)
    path = artifacts.composite_path(identity, "full")
    if not path.exists():
        image = compose_page(image, state)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_bytes(image)
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
    return path.read_bytes(), state, identity
