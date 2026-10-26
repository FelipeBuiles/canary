"""Provider-free Style proofs; clean reference art is never overwritten.

The specimens fit the four reservations in STYLE_PROOF_ART_CONSTRAINTS;
speech and shout share the speech reservation. Their words are the project's
story proof copy (lines from the proof scene), or neutral role labels when no
story copy exists. This is a visual specimen, not Adapt copy and not evidence
of image-model reservation adherence.
"""
from __future__ import annotations

import hashlib
import io
import json

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from novel_to_comic.models.lettering import LetteringElement, LetteringStyle, PageLettering
from novel_to_comic.models.page import NormalizedPoint, PinnedGeometry
from novel_to_comic.target_artifacts import TargetArtifacts
from .direction import voice_style
from .renderer import ENGINE_VERSION, render_lettered_page, resolve_lettering

PROOF_VERSION = "software-style-proof-v4"
SPECIMEN_BOUNDS = (
    ("caption", (.05, .04, .47, .14)),
    ("speech", (.54, .37, .23, .13)),
    ("shout", (.80, .37, .14, .13)),
    ("thought", (.05, .53, .44, .16)),
    ("sfx", (.58, .83, .36, .12)),
)
# Character ceilings keep story lines near what every bundled design fits in
# its reservation. Fitting still decides per style: see resolve_style_proof.
SPECIMEN_MAX_CHARS = {"caption": 48, "speech": 22, "shout": 8, "thought": 30, "sfx": 9}
# Where the speech and thought pointers land (page space, approximate): proof
# art stages each line's owner here so a pointer never names the wrong subject.
SPEAKER_POINTS = {"speech": (.60, .56), "thought": (.22, .74)}


class ProofCopy(BaseModel):
    """The five specimen lines every proof of one project shares."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    caption: str = Field(min_length=1, max_length=SPECIMEN_MAX_CHARS["caption"])
    speech: str = Field(min_length=1, max_length=SPECIMEN_MAX_CHARS["speech"])
    shout: str = Field(min_length=1, max_length=SPECIMEN_MAX_CHARS["shout"])
    thought: str = Field(min_length=1, max_length=SPECIMEN_MAX_CHARS["thought"])
    sfx: str = Field(min_length=1, max_length=SPECIMEN_MAX_CHARS["sfx"])
    # Listed subjects who own the lines: speaker says speech and shout, thinker
    # thinks thought. Role labels have no owners.
    speaker: str | None = Field(default=None, min_length=1, max_length=120)
    thinker: str | None = Field(default=None, min_length=1, max_length=120)


# Without story copy, a proof names each lettering role instead of putting
# invented words in the author's characters' mouths.
LABEL_COPY = ProofCopy(caption="Narration", speech="Speech", shout="Shout!", thought="Thought", sfx="SFX")
_TAIL_BEND = {"speech": .35, "thought": -.3}


def specimens(copy: ProofCopy = LABEL_COPY) -> tuple[tuple[str, str, tuple[float, ...]], ...]:
    return tuple((role, getattr(copy, role), bounds) for role, bounds in SPECIMEN_BOUNDS)


def style_proof_state(
    style: LetteringStyle, width: int, height: int, copy: ProofCopy = LABEL_COPY,
) -> PageLettering:
    elements = []
    for specimen, text, bounds in specimens(copy):
        role = "speech" if specimen == "shout" else specimen
        placement = PinnedGeometry(**dict(zip(("x", "y", "width", "height"), bounds)))
        override = (voice_style(style.roles.speech, "speech", "shout").model_copy(update={"align": "center", "padding": 5})
                    if specimen == "shout" else None)
        elements.append(LetteringElement(
            id=f"proof-{specimen}", role=role,
            text_by_locale={"source": text},
            placement=placement, suggested_placement=placement,
            style_override=override,
        ))
    return PageLettering(
        revision=1, page_number=1, comic_page_sha256="0" * 64,
        style_sha256=style.content_sha256, canvas_aspect_ratio=width / height,
        elements=elements,
    )


def _fitted_copy(style: LetteringStyle, width: int, height: int, copy: ProofCopy) -> PageLettering:
    """Resolve story copy; a line this design cannot fit shows its role label."""
    state = resolve_lettering(style_proof_state(style, width, height, copy), style)
    unfit = {
        element.id.removeprefix("proof-") for element in state.elements
        if element.resolved is None or element.resolved.overflow or element.resolved.warnings
    }
    if not unfit or copy == LABEL_COPY:
        return state
    fallback = copy.model_copy(update={role: getattr(LABEL_COPY, role) for role in unfit})
    return resolve_lettering(style_proof_state(style, width, height, fallback), style)


def resolve_style_proof(
    style: LetteringStyle, width: int, height: int, copy: ProofCopy = LABEL_COPY,
) -> PageLettering:
    """Attach specimen pointers to fitted bodies, not the art reservations.

    The pointers land near ``SPEAKER_POINTS``, where proof art stages the
    copy's speaker and thinker. Saved page/editor targets remain untouched.
    """
    state = _fitted_copy(style, width, height, copy)
    elements = []
    for element in state.elements:
        if element.role in {"speech", "thought"} and element.resolved:
            body = element.resolved
            x = element.placement.x + (body.width or element.placement.width) * .38
            y = element.placement.y + body.height
            length = body.font_size * (1.25 if element.role == "thought" else .9) / 1000 * state.canvas_aspect_ratio
            target = NormalizedPoint(x=x, y=min(1, y + length))
            element = element.model_copy(update={
                "tail_target": target, "suggested_tail_target": target,
                "tail_bend": _TAIL_BEND.get(element.id.removeprefix("proof-"), 0),
            })
        elements.append(element)
    return state.model_copy(update={"elements": tuple(elements)})


def style_proof_identity(style: LetteringStyle, image_sha256: str, copy: ProofCopy = LABEL_COPY) -> str:
    """The derivative's content key; proof URLs carry it so browsers keep them."""
    return hashlib.sha256(json.dumps([
        image_sha256, style.content_sha256, ENGINE_VERSION, PROOF_VERSION, specimens(copy),
    ], separators=(",", ":")).encode()).hexdigest()


def render_style_proof(
    target: TargetArtifacts, style: LetteringStyle, image: bytes,
    copy: ProofCopy = LABEL_COPY,
) -> tuple[bytes, str]:
    """Return a cached derivative keyed by art, exact style, engine and specimens.

    Content-addressed, so the renderer runs without the production lock; only
    the cache write takes it. Six proofs render side by side, not in a queue.
    """
    identity = style_proof_identity(style, hashlib.sha256(image).hexdigest(), copy)
    path = target.lettering_proof_path(identity)
    if path.exists():
        return path.read_bytes(), identity
    with Image.open(io.BytesIO(image)) as source:
        width, height = source.size
    state = resolve_style_proof(style, width, height, copy)
    # Invalid/oversize design tokens produce an actionable error, not silent
    # clipping or font shrinking beneath the configured floor.
    result = render_lettered_page(state, style, image, width, height)
    target.write_lettering_proof(identity, result)
    return result, identity
