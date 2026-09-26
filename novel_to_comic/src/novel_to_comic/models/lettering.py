"""Independent, provider-free presentation of Adapt's immutable copy.

All positions are normalized page space. Font sizes/spacing are vector units
on a 1000-unit page width, never native raster pixels. Resolved layouts are
server-authored with the shared browser engine and retained for exact exports.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from novel_to_comic.localization import LetteringLocale

from .adaptation import RevisionedArtifact
from .page import NormalizedPoint, PinnedGeometry

FontName = Literal[
    "Comic Neue",
    "EB Garamond",
    "Bangers",
    "Special Elite",
    "M PLUS 1p",
    "Fredoka",
    "Orbitron",
    "Bungee",
    "Baloo 2",
    "Exo 2",
    "Shrikhand",
    "Creepster",
]
RoleName = Literal["caption", "speech", "thought", "sfx"]
Color = Annotated[str, Field(pattern=r"^(#[0-9a-fA-F]{6}|transparent)$")]
Locale = Annotated[str, Field(pattern=r"^(source|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$")]


class RoleStyle(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    font: FontName = "EB Garamond"
    font_weight: Literal[400, 700] = 400
    min_font_size: float = Field(default=16, ge=12, le=100)
    max_font_size: float = Field(default=17, ge=12, le=180)
    line_height: float = Field(default=1.05, ge=0.9, le=2)
    align: Literal["left", "center", "right"] = "center"
    color: Color = "#181818"
    fill: Color = "#ffffff"
    stroke: Color = "#181818"
    stroke_width: float = Field(default=1.6, ge=0, le=12)
    padding: float = Field(default=11, ge=0, le=40)
    corner_radius: float = Field(default=12, ge=0, le=80)
    shape: Literal[
        "box", "round", "balloon", "ellipse", "cloud", "whisper", "burst", "wavy", "electric", "none"
    ] = Field(
        default="balloon",
        description="balloon: speech; cloud: thought; burst: shout; whisper: dashed; "
        "wavy: weak or woozy voice; electric: radio, phone or machine voice; box/round: captions.",
    )
    letter_spacing: float = Field(default=0, ge=-1, le=12)
    text_stroke: Color = "transparent"
    text_stroke_width: float = Field(default=0, ge=0, le=12)
    text_case: Literal["as_written", "upper"] = Field(
        default="as_written", description="upper: classic all-caps comic lettering. Copy stays as written."
    )
    tail_width: float = Field(default=1, ge=0.4, le=2.5, description="Balloon tail root width multiplier.")
    halo_color: Color = "transparent"
    halo_width: float = Field(
        default=0, ge=0, le=16,
        description="Outer knockout outline around the balloon, or around the letters when shape is none.",
    )
    shadow: Literal["none", "drop", "extrude"] = Field(
        default="none", description="drop: offset shadow; extrude: solid 3D depth. Applies like the halo."
    )
    shadow_color: Color = "#181818"
    shadow_x: float = Field(default=4, ge=-40, le=40)
    shadow_y: float = Field(default=4, ge=-40, le=40)
    gradient_color: Color = Field(
        default="transparent", description="Letters fade vertically from color to this color."
    )
    warp: Literal["none", "arc", "wave"] = "none"
    warp_amount: float = Field(default=0.5, ge=-1, le=1, description="Warp strength; negative bends the other way.")
    jitter: float = Field(default=0, ge=0, le=1, description="Seeded per-letter bounce, for sound effects.")
    skew: float = Field(default=0, ge=-30, le=30, description="Letter lean in degrees; positive leans forward.")

    @model_validator(mode="after")
    def _font_range(self):
        if self.min_font_size > self.max_font_size:
            raise ValueError("minimum font size cannot exceed maximum")
        return self


class LetteringRoles(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    caption: RoleStyle = Field(
        default_factory=lambda: RoleStyle(
            font="EB Garamond",
            align="left",
            fill="#fff2d5",
            shape="box",
            corner_radius=0,
            min_font_size=16,
            max_font_size=18,
            padding=8,
            line_height=1.04,
        )
    )
    speech: RoleStyle = Field(default_factory=RoleStyle)
    thought: RoleStyle = Field(
        default_factory=lambda: RoleStyle(shape="cloud", padding=9)
    )
    sfx: RoleStyle = Field(
        default_factory=lambda: RoleStyle(
            font="Bangers",
            min_font_size=24,
            max_font_size=68,
            fill="transparent",
            shape="none",
            color="#fff2b5",
            text_stroke="#181818",
            text_stroke_width=2.5,
            padding=4,
        )
    )


class DesignedLetteringRoles(LetteringRoles):
    """Every generated direction must explicitly design all four semantic roles."""

    caption: RoleStyle = Field(...)
    speech: RoleStyle = Field(...)
    thought: RoleStyle = Field(...)
    sfx: RoleStyle = Field(...)


class LetteringDesign(BaseModel):
    """Provider-authored design tokens, not a persisted artifact/revision hash."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    label: str = Field(min_length=1, max_length=100)
    roles: DesignedLetteringRoles


class LetteringStyle(RevisionedArtifact):
    label: str = Field(default="Literary classic", min_length=1, max_length=100)
    source_direction: str = Field(default="", max_length=10000)
    roles: LetteringRoles = Field(default_factory=LetteringRoles)


class LetteringSettings(RevisionedArtifact):
    """Project-owned display locale; page locales are projections of this setting."""

    locale: LetteringLocale = "source"


class ResolvedLineMetrics(BaseModel):
    """Glyph geometry in 1000-unit page space, relative to the fitted body."""
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    x: float
    baseline: float
    width: float = Field(ge=0)
    ascent: float = Field(ge=0)
    descent: float = Field(ge=0)
    # Glyph start offsets plus the line end, only for letters placed one by one.
    glyph_x: tuple[float, ...] | None = Field(default=None, max_length=401)


class ResolvedLettering(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    engine_version: str
    locale: str
    text: str = Field(max_length=10000)
    lines: tuple[str, ...] = Field(max_length=500)
    font_size: float = Field(ge=12, le=180)
    line_height: float = Field(gt=0, le=360)
    height: float = Field(gt=0, le=1)
    # v1 records remain readable, but engine-version checks require explicit
    # reflow/save before v2 export. New records persist width and glyph baselines.
    width: float | None = Field(default=None, gt=0, le=1)
    line_metrics: tuple[ResolvedLineMetrics, ...] = Field(default=(), max_length=500)
    overflow: bool
    warnings: tuple[str, ...] = ()


class LetteringElement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=100, pattern=r"^[\w.-]+$")
    source_lettering_item_id: str | None = Field(default=None, max_length=100)
    role: RoleName
    text_by_locale: dict[Locale, Annotated[str, Field(max_length=10000)]]
    # Exact display source used for generation or explicit translation review.
    translation_sources: dict[Locale, Annotated[str, Field(max_length=10000)]] = Field(default_factory=dict)
    suggested_placement: PinnedGeometry
    placement: PinnedGeometry
    hidden: bool = False
    # Explicit override of a role: None inherits the book style.
    style_override: RoleStyle | None = None
    tail_target: NormalizedPoint | None = None
    suggested_tail_target: NormalizedPoint | None = None
    # Sideways bow of the tail's spine; 0 is straight.
    tail_bend: float = Field(default=0, ge=-1, le=1)
    # Joins this balloon to an earlier balloon of the same page into one silhouette.
    link_to: str | None = Field(default=None, max_length=100)
    rotation: float = Field(default=0, ge=-180, le=180)
    scale: float = Field(default=1, ge=0.25, le=3)
    z_index: int = Field(default=0, ge=-1000, le=1000)
    tight_box: bool = True
    resolved: ResolvedLettering | None = None

    @model_validator(mode="after")
    def _copy(self):
        if "source" not in self.text_by_locale:
            raise ValueError("every element must retain its source-locale display copy")
        if "source" in self.translation_sources or self.translation_sources.keys() - self.text_by_locale.keys():
            raise ValueError("translation sources must belong to stored target variants")
        if len(self.text_by_locale) > 40:
            raise ValueError("at most forty locale variants per element")
        return self


class PageLettering(RevisionedArtifact):
    page_number: int = Field(ge=1)
    comic_page_sha256: str = Field(min_length=64, max_length=64)
    style_sha256: str = Field(min_length=64, max_length=64)
    locale: Locale = "source"
    canvas_aspect_ratio: float = Field(gt=0.1, lt=10)
    elements: tuple[LetteringElement, ...] = Field(max_length=200)
    reviewed_against_render_revision: int | None = Field(default=None, ge=1)
    reviewed_against_image_sha256: str | None = None

    @model_validator(mode="after")
    def _unique(self):
        ids = [item.id for item in self.elements]
        sources = [
            item.source_lettering_item_id
            for item in self.elements
            if item.source_lettering_item_id is not None
        ]
        if len(ids) != len(set(ids)) or len(sources) != len(set(sources)):
            raise ValueError("lettering element and source IDs must be unique")
        links = {item.id: item.link_to for item in self.elements if item.link_to is not None}
        for start in links:
            seen, cursor = set(), start
            while cursor in links:
                target = links[cursor]
                if cursor in seen or target == cursor or target not in ids:
                    raise ValueError("balloon links must join existing balloons without loops")
                seen.add(cursor)
                cursor = target
        return self
