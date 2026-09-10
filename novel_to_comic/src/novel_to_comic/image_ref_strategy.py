"""Per-model reference image strategy.

Every place the pipeline behaves differently per image model route — which
reference images to upload, which prompt sections to add, which output
dimensions to request — asks this module instead of testing model identity
inline. Stage and prompt code ask decision-level questions ("which refs for
this panel?", "what size for a location plate?"); the per-provider rules live
behind this one interface.

The provider transport itself (endpoint choice, payload shape) stays in
``ai/providers`` — that is the provider seam, and provider knowledge there is
legitimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from novel_to_comic.config import Config, is_gpt_image_2, is_seedream_model

_GPT_LOCATION_PLATE_WIDTH = 1536
_GPT_LOCATION_PLATE_HEIGHT = 1024


def is_prop_ref(path: Path) -> bool:
    """True if this ref path lives under a props/ asset directory."""
    parts = path.parts
    return len(parts) >= 3 and parts[-3] == "props"


def _gpt_image_2_subject_refs(paths: list[Path]) -> list[Path]:
    """Return a minimal, stable identity ref set for GPT Image 2 panels.

    Multiple pose crops plus prop refs push GPT Image 2 into noisy edit behavior.
    Prefer one framing-appropriate crop per character. Prop refs stay text-only unless a
    panel has no character refs at all, in which case one prop ref is allowed.
    """
    character_refs = [p for p in paths if not is_prop_ref(p)]
    prop_refs = [p for p in paths if is_prop_ref(p)]
    selected: list[Path] = []
    seen_character_dirs: set[Path] = set()

    def sort_key(path: Path) -> tuple[int, str]:
        preferred = {
            "portrait.png": 0,
            "full_body.png": 1,
            "sheet.png": 2,
        }
        return preferred.get(path.name, 99), str(path)

    for path in sorted(character_refs, key=sort_key):
        character_dir = path.parent
        if character_dir in seen_character_dirs:
            continue
        selected.append(path)
        seen_character_dirs.add(character_dir)

    if selected:
        return selected

    return prop_refs[:1]


@dataclass(frozen=True)
class RefStrategy:
    """Decision surface for one image model route.

    Construct via ``RefStrategy.for_config(config)`` (or directly from a model
    string when config isn't in scope, e.g. prompt rendering).
    """

    model: str

    @classmethod
    def for_config(cls, config: Config) -> RefStrategy:
        from novel_to_comic.codex_dev import route_for

        model = config.effective_image_model()
        return cls("codex-builtin" if route_for("image", model) is not None else model)

    @property
    def _gpt_image_2(self) -> bool:
        return is_gpt_image_2(self.model)


    @property
    def _seedream(self) -> bool:
        return is_seedream_model(self.model)

    def use_location_plate_refs(self) -> bool:
        # GPT Image 2 processes every supplied image at high fidelity, so location
        # plates can leak repeated background textures into panels. Keep locations
        # text-driven for the gpt-image-2 route.
        return not self._gpt_image_2

    def use_style_sample_refs(self) -> bool:
        # GPT Image 2 uses the image edit endpoint whenever any reference image is
        # supplied. Keep style text-driven to avoid copying sample texture/noise.
        return not self._gpt_image_2

    # ------------------------------------------------------------------
    # Cast: asset refs, prompts, and dimensions
    # ------------------------------------------------------------------

    def cast_style_ref(self, style_ref: Path | None) -> Path | None:
        if not self._gpt_image_2:
            return style_ref
        # The gpt-image-2 route treats reference inputs as edit conditioning.
        # Reusing the selected style sample for cast assets can carry over subject
        # details or texture artifacts, so keep its cast refs text-driven.
        return None


    def use_structured_location_plate_prompt(self) -> bool:
        """GPT Image 2 location plates use the labeled design-plate prompt layout."""
        return self._gpt_image_2

    def location_plate_dimensions(self) -> tuple[int | None, int | None]:
        # Slice 06: location plates promise a "clean wide environment design
        # plate." The generation dimensions must agree with that wide
        # composition for every route — falling back to the (square) panel
        # config dimensions produced a composition/dimension contradiction.
        # GPT Image 2 keeps its verified 1536x1024 size; other routes use the
        # canonical landscape plate dimensions from image_geometry.
        if self._gpt_image_2:
            return _GPT_LOCATION_PLATE_WIDTH, _GPT_LOCATION_PLATE_HEIGHT
        from novel_to_comic.image_geometry import location_plate_dimensions as _plate_dims
        return _plate_dims()

    def include_dimensions_in_asset_meta(self) -> bool:
        return self._gpt_image_2

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def include_rendering_discipline(self) -> bool:
        return self._gpt_image_2
