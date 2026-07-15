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

from novel_to_comic.ai.providers.base import RefImage, order_refs_for_upload
from novel_to_comic.config import Config, is_gpt_image_2, is_reve_model, is_seedream_model

_GPT_LOCATION_PLATE_WIDTH = 1536
_GPT_LOCATION_PLATE_HEIGHT = 1024

# Reve style text is clamped so the style reference image, not prose, carries
# the visual guidance.
_REVE_STYLE_TEXT_MAX_CHARS = 200


def is_prop_ref(path: Path) -> bool:
    """True if this ref path lives under a props/ asset directory."""
    parts = path.parts
    return len(parts) >= 3 and parts[-3] == "props"


def _gpt_image_2_subject_refs(paths: list[Path]) -> list[Path]:
    """Return a minimal, stable identity ref set for GPT Image 2 panels.

    Multiple pose crops plus prop refs push GPT Image 2 into noisy edit behavior.
    Prefer one front-facing crop per character. Prop refs stay text-only unless a
    panel has no character refs at all, in which case one prop ref is allowed.
    """
    character_refs = [p for p in paths if not is_prop_ref(p)]
    prop_refs = [p for p in paths if is_prop_ref(p)]
    selected: list[Path] = []
    seen_character_dirs: set[Path] = set()

    def sort_key(path: Path) -> tuple[int, str]:
        preferred = {
            "front.png": 0,
            "three_quarter.png": 1,
            "profile.png": 2,
            "gesture.png": 3,
            "sheet.png": 4,
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


# Pose-crop preference per framing. Close framings want a face-forward crop;
# wide framings want a full-body/gesture crop so proportions carry over.
_SHOT_VIEW_PREFERENCES: dict[str, list[str]] = {
    "close": ["front", "three_quarter", "profile", "gesture", "sheet"],
    "wide": ["gesture", "three_quarter", "front", "profile", "sheet"],
    "default": ["three_quarter", "front", "gesture", "profile", "sheet"],
}


def _shot_view_preference(composition: str | None) -> list[str]:
    text = (composition or "").lower()
    if "close-up" in text or "close up" in text or "portrait" in text:
        return _SHOT_VIEW_PREFERENCES["close"]
    if any(token in text for token in ("wide", "establishing", "panorama", "full body")):
        return _SHOT_VIEW_PREFERENCES["wide"]
    return _SHOT_VIEW_PREFERENCES["default"]


def _select_subject_crops(
    subjects: list[RefImage],
    composition: str | None,
    primary_poses: dict[str, str] | None = None,
) -> list[RefImage]:
    """Pick ONE pose crop per character, matched to the panel's framing.

    Sending several crops of the same character (or a 2x2 sheet grid) makes
    ref-driven models blend poses and occasionally leak the grid layout into
    the panel. One clean, framing-appropriate crop per character keeps identity
    strong without those artifacts. A user-chosen primary pose (keyed by the
    character directory name) overrides the framing preference.
    """
    preference = {stem: i for i, stem in enumerate(_shot_view_preference(composition))}
    primary = primary_poses or {}
    order: list[Path] = []
    by_character: dict[Path, list[RefImage]] = {}
    for ref in subjects:
        character_dir = ref.path.parent
        if character_dir not in by_character:
            by_character[character_dir] = []
            order.append(character_dir)
        by_character[character_dir].append(ref)

    def crop_rank(character_dir: Path, ref: RefImage) -> tuple[int, int, str]:
        is_primary = 0 if primary.get(character_dir.name) == ref.path.stem else 1
        return (is_primary, preference.get(ref.path.stem, 99), str(ref.path))

    return [min(by_character[d], key=lambda r: crop_rank(d, r)) for d in order]


def _reve_refs(
    refs: list[RefImage],
    composition: str | None = None,
    primary_poses: dict[str, str] | None = None,
) -> list[RefImage]:
    """Select up to 4 refs for Reve, identity first.

    Character identity is the thing reference images are best at and the
    hardest to recover via text, so subjects always win slots: one crop per
    character (up to 3), chosen by the panel's framing. Remaining slots fill
    with continuity, prop, style, then location refs.
    """
    subjects = _select_subject_crops(
        [r for r in refs if r.role == "subject"], composition, primary_poses
    )[:3]
    continuities = [r for r in refs if r.role == "continuity"]
    props = [r for r in refs if r.role == "prop"]
    styles = [r for r in refs if r.role == "style"]
    locations = [r for r in refs if r.role == "location_plate"]

    selected: list[RefImage] = list(subjects)
    for ref in [*continuities[:1], *props, *styles[:1], *locations[:1]]:
        if len(selected) >= 4:
            break
        if ref not in selected:
            selected.append(ref)
    return order_refs_for_upload(selected)


@dataclass(frozen=True)
class RefStrategy:
    """Decision surface for one image model route.

    Construct via ``RefStrategy.for_config(config)`` (or directly from a model
    string when config isn't in scope, e.g. prompt rendering).
    """

    model: str

    @classmethod
    def for_config(cls, config: Config) -> RefStrategy:
        return cls(config.effective_image_model())

    @property
    def _gpt_image_2(self) -> bool:
        return is_gpt_image_2(self.model)

    @property
    def _reve(self) -> bool:
        return is_reve_model(self.model)

    @property
    def _seedream(self) -> bool:
        return is_seedream_model(self.model)

    # ------------------------------------------------------------------
    # Draw: panel reference selection
    # ------------------------------------------------------------------

    def select_panel_refs(
        self,
        refs: list[RefImage],
        composition: str | None = None,
        primary_poses: dict[str, str] | None = None,
    ) -> list[RefImage]:
        """Reduce candidate refs to the set this model route should receive.

        Input and output follow the canonical upload order from
        ``order_refs_for_upload`` — the returned list IS the upload order
        assumed by ``render_generation_prompt``. ``primary_poses`` carries the
        user-chosen canonical crop per character (char dir name → pose stem).
        """
        if self._reve:
            return _reve_refs(refs, composition, primary_poses)
        if self._gpt_image_2:
            selected_paths = set(
                _gpt_image_2_subject_refs(
                    [ref.path for ref in refs if ref.role in {"subject", "prop"}]
                )
            )
            return [ref for ref in refs if ref.path in selected_paths]
        if self._seedream:
            return refs[:10]
        return refs

    def use_prev_panel_image(self, prev_transition_type: str | None) -> bool:
        """True if the previous panel's image should be used as a style reference.

        Hard cuts (smash cut, fade to, cut to, scene change, time jump) can make
        the previous panel image actively harmful - the model might blend the
        previous scene into the new one. Smooth continuations should stay
        text-only: previous-panel image refs are strong edit inputs and can
        override character identity, scale, and composition. Reserve image
        continuity for intentional match cuts.
        """
        if not prev_transition_type:
            return False
        transition_type = (prev_transition_type or "").strip().lower()
        if self._gpt_image_2:
            return False
        return transition_type == "match_cut"

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

    def use_clean_text_character_prompt(self) -> bool:
        """Reve gets a clean text character prompt instead of the 2x2 grid sheet."""
        return self._reve

    def clamp_style_text(self, style: str) -> str:
        # When using Reve with style reference, reduce style text to avoid
        # conflicts — the style reference image provides stronger visual guidance.
        if self._reve and len(style) > _REVE_STYLE_TEXT_MAX_CHARS:
            return style[:_REVE_STYLE_TEXT_MAX_CHARS]
        return style

    def use_structured_location_plate_prompt(self) -> bool:
        """GPT Image 2 location plates use the labeled design-plate prompt layout."""
        return self._gpt_image_2

    def location_plate_dimensions(self) -> tuple[int | None, int | None]:
        # Slice 06: location plates promise a "clean wide environment design
        # plate." The generation dimensions must agree with that wide
        # composition for every route — falling back to the (square) panel
        # config dimensions produced a composition/dimension contradiction.
        # GPT Image 2 keeps its verified 1536x1024 size; other routes use the
        # canonical landscape plate dimensions from panel_aspect.
        if self._gpt_image_2:
            return _GPT_LOCATION_PLATE_WIDTH, _GPT_LOCATION_PLATE_HEIGHT
        from novel_to_comic.panel_aspect import location_plate_dimensions as _plate_dims
        return _plate_dims()

    def include_dimensions_in_asset_meta(self) -> bool:
        return self._gpt_image_2

    # ------------------------------------------------------------------
    # Prompt assembly
    # ------------------------------------------------------------------

    def include_rendering_discipline(self) -> bool:
        return self._gpt_image_2

    def use_indexed_ref_instructions(self) -> bool:
        """Reve v2 create prompts reference uploads via <frame>N</frame>.

        Layout-aware render requests bind regions structurally and therefore
        do not use inline tags; this flag is for the ordinary v2 create path.
        """
        return self._reve
