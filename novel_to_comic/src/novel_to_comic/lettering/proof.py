"""Provider-free Style proofs; clean reference art is never overwritten.

The specimens fit the four reservations in STYLE_PROOF_ART_CONSTRAINTS;
speech and shout share the speech reservation. This is a visual
specimen, not Adapt copy and not evidence of image-model reservation adherence.
"""
from __future__ import annotations

import hashlib
import io
import json

from PIL import Image

from novel_to_comic.artifact_lock import locked_mutation
from novel_to_comic.models.lettering import LetteringElement, LetteringStyle, PageLettering
from novel_to_comic.models.page import NormalizedPoint, PinnedGeometry
from novel_to_comic.target_artifacts import TargetArtifacts
from .renderer import ENGINE_VERSION, render_lettered_page, resolve_lettering

PROOF_VERSION = "software-style-proof-v2"
SPECIMENS = (
    ("caption", "The night held its breath.", (.05, .04, .47, .14)),
    ("speech", "We keep moving.", (.54, .37, .23, .13)),
    ("shout", "Run!", (.80, .37, .14, .13)),
    ("thought", "Did you hear that?", (.05, .53, .44, .16)),
    ("sfx", "KRAK", (.58, .83, .36, .12)),
)


def style_proof_state(style: LetteringStyle, width: int, height: int) -> PageLettering:
    elements = []
    for specimen, text, bounds in SPECIMENS:
        role = "speech" if specimen == "shout" else specimen
        placement = PinnedGeometry(**dict(zip(("x", "y", "width", "height"), bounds)))
        override = (style.roles.speech.model_copy(update={"shape": "burst", "align": "center", "padding": 5})
                    if specimen == "shout" else None)
        elements.append(LetteringElement(
            id=f"proof-{specimen}", role=role, text_by_locale={"source": text},
            placement=placement, suggested_placement=placement,
            style_override=override,
        ))
    return PageLettering(
        revision=1, page_number=1, comic_page_sha256="0" * 64,
        style_sha256=style.content_sha256, canvas_aspect_ratio=width / height,
        elements=elements,
    )


def resolve_style_proof(style: LetteringStyle, width: int, height: int) -> PageLettering:
    """Attach specimen pointers to fitted bodies, not the art reservations.

    These short pointers demonstrate typography; they do not identify speakers.
    Saved page/editor targets remain untouched.
    """
    state = resolve_lettering(style_proof_state(style, width, height), style)
    elements = []
    for element in state.elements:
        if element.role in {"speech", "thought"} and element.resolved:
            body = element.resolved
            x = element.placement.x + (body.width or element.placement.width) * .38
            y = element.placement.y + body.height
            length = body.font_size * (1.25 if element.role == "thought" else .9) / 1000 * state.canvas_aspect_ratio
            target = NormalizedPoint(x=x, y=min(1, y + length))
            element = element.model_copy(update={"tail_target": target, "suggested_tail_target": target})
        elements.append(element)
    return state.model_copy(update={"elements": tuple(elements)})


@locked_mutation
def render_style_proof(
    target: TargetArtifacts, style: LetteringStyle, image: bytes,
) -> tuple[bytes, str]:
    """Return a cached derivative keyed by art, exact style, engine and specimens."""
    identity = hashlib.sha256(json.dumps([
        hashlib.sha256(image).hexdigest(), style.content_sha256, ENGINE_VERSION,
        PROOF_VERSION, SPECIMENS,
    ], separators=(",", ":")).encode()).hexdigest()
    path = target.lettering_proof_path(identity)
    if path.exists():
        return path.read_bytes(), identity
    with Image.open(io.BytesIO(image)) as source:
        width, height = source.size
    state = resolve_style_proof(style, width, height)
    # Invalid/oversize design tokens produce an actionable error, not silent
    # clipping or font shrinking beneath the configured floor.
    result = render_lettered_page(state, style, image, width, height)
    target.write_lettering_proof(identity, result)
    return result, identity
