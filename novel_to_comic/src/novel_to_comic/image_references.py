"""Slice 04 — one final, capability-aware, state-safe reference selection.

The :class:`ReferencePlan` owns final reference selection, ordering, authority
facets, selected content hashes, and drop diagnostics before prompt compilation
begins. No later layer — prompt rendering, provider adapter, or transport — may
select, cap, or reorder references. It consumes the finalized plan as-is.

Resolution is semantic, not path-based: candidates are discovered at draw/
estimate time from the panel's active character/location state ids, the
selected primary poses, current asset metadata, and the current files on disk.
No stored path list is consulted; the canonical prompt carries semantic entity
and state ids only.

Design invariants (see the master plan README, "Global invariants"):

- Visible subjects are generation requirements. A subject identity is never
  silently erased from the prompt or diagnostics; when subjects exceed the
  route cap, the overflow policy names every unreferenced subject.
- An active appearance/location state wins over canonical mutable facts. A
  dedicated significant-state reference has full appearance authority; a missing
  significant-state reference omits contradictory canonical full-body
  conditioning.
- Reference ordering has exactly one owner (this plan). Prompt indices and
  uploaded bytes derive from the same final ordering.
- State lineage mismatches are visible and excluded. Until Slice 08 makes
  lineage metadata mandatory, absent lineage is ``unverified_lineage`` under a
  non-blocking safety policy.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal

from novel_to_comic.image_models import (
    ImageModelProfile,
    ImageRoute,
    image_model_profile,
)
from novel_to_comic.models.prompt import ImagePrompt

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Roles and ordering
# ---------------------------------------------------------------------------

#: Reference role a selected asset plays in the final upload. Mirrors the
#: provider ``RefRole`` literal so prompt-domain code never imports HTTP types.
RefRole = Literal["subject", "prop", "continuity", "style", "location_plate"]

#: Canonical final ordering. Subject identity gets the strongest positional
#: weight; contextual refs come last. This MUST match the upload order used by
#: the provider layer (``ai.providers.base.UPLOAD_REF_PRIORITY``).
_SELECTION_ORDER: dict[str, int] = {
    "subject": 0,
    "prop": 1,
    "continuity": 2,
    "style": 3,
    "location_plate": 4,
}


# ---------------------------------------------------------------------------
# Authority facets
# ---------------------------------------------------------------------------


class AuthorityScope(str, Enum):
    """How much of an entity's appearance a selected reference is allowed to
    condition.

    The plan publishes the authority scope so Slice 05's compiled request can
    emit per-reference instructions without re-deriving compatibility. The
    preserve/ignore facet tuples make the scope precise: e.g. a minor text-only
    state may preserve ``("face", "hair", "build")`` but ignore
    ``("wardrobe",)``.
    """

    FULL_APPEARANCE = "full_appearance"
    #: The selected reference is the authoritative appearance for this entity
    #: in this panel — a dedicated significant-state ref, or a base-look ref
    #: when no state is active. The model should match identity, wardrobe,
    #: build, and anatomy.

    IDENTITY_ONLY = "identity_only"
    #: A compatible canonical crop used only for identity facets the active
    #: state does not contradict. Mutable facets (wardrobe, anatomy) are
    #: explicitly ignored. Used when a minor text-only state is active and the
    #: canonical crop is still compatible.

    CONTEXTUAL = "contextual"
    #: A non-identity reference (location plate, style sample, prop, continuity)
    #: conditioning only its own facet — never an entity appearance.


#: Facet vocabulary. Kept deliberately small; new facets are additive.
_IDENTITY_FACETS = ("face", "hair", "build")
_WARDROBE_FACETS = ("wardrobe",)
_ANATOMY_FACETS = ("anatomy",)


# ---------------------------------------------------------------------------
# Drop reasons
# ---------------------------------------------------------------------------


class DropReason(str, Enum):
    """Why a candidate reference was not selected.

    Each reason maps to a documented selection rule. Dropped candidates are
    always reported through the plan so callers can surface warnings (backend
    today; UI in Slice 13).
    """

    MISSING = "missing"
    #: The candidate file does not exist on disk at the resolved path.

    UNREADABLE = "unreadable"
    #: The candidate file exists but cannot be read (permissions, I/O error).

    DUPLICATE_ENTITY = "duplicate_entity"
    #: A crop of an entity already selected (e.g. a second pose of the same
    #: character after one-crop-per-character was applied).

    PROVIDER_CAP = "provider_cap"
    #: The route's hard reference cap was reached; the candidate did not fit.

    UNSUPPORTED_ROLE = "unsupported_role"
    #: The route does not accept this role (e.g. a style sample on GPT Image 2).

    STATE_CONFLICT = "state_conflict"
    #: A canonical ref contradicts the active appearance/location state. Used
    #: for: a canonical full-body ref conditioning a significant state without
    #: its own ref; a canonical location plate substituting for a missing
    #: active state plate.

    STALE_LINEAGE = "stale_lineage"
    #: A state asset's recorded canonical parent hash does not match the
    #: current canonical bytes. The derived ref is excluded until regenerated.

    UNVERIFIED_LINEAGE = "unverified_lineage"
    #: A state asset has no recorded lineage metadata. Until Slice 08 makes
    #: lineage mandatory, this is non-blocking for significant states but
    #: reported so callers know the derivation is unverified.

    LOWER_PRIORITY = "lower_priority"
    #: A valid candidate that lost its slot to a higher-priority candidate
    #: under the deterministic scarce-slot policy (e.g. a non-critical prop
    #: dropped for a location plate).


class ReferenceMaterializationError(ValueError):
    """A selected semantic reference could not be read safely."""


# ---------------------------------------------------------------------------
# Asset models
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    """A resolved candidate before selection: a role + a path + the semantic
    identity it would condition, plus authority hints.

    Candidates are the input to the table-driven policy; ``ReferenceAsset`` is
    the output. A candidate that is not selected becomes a ``DroppedReference``.
    """

    path: Path
    role: RefRole
    entity_id: str | None = None
    appearance_state_id: str | None = None
    #: True when this candidate is a dedicated state-ref (under a state dir).
    is_state_ref: bool = False
    canonical_equivalent: bool = False
    critical: bool = False
    label: str | None = None


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
    """One finally-selected reference with its authority scope and content hash.

    The content hash is the SHA-256 of the selected file's bytes. It
    participates in the selection fingerprint and (via the plan) in panel cache
    identity. ``lineage_parent_sha256`` records the canonical parent the state
    asset was derived from, when the asset's metadata declared one.
    """

    path: Path
    role: RefRole
    entity_id: str | None
    appearance_state_id: str | None
    authority_scope: AuthorityScope
    preserve_facets: tuple[str, ...]
    ignore_facets: tuple[str, ...]
    pose: str | None
    content_sha256: str
    lineage_parent_sha256: str | None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class DroppedReference:
    """A candidate that was not selected, with the reason and human detail."""

    candidate: SemanticCandidate | ReferenceAsset
    reason: DropReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class SelectionFingerprint:
    """Stable SHA-256 over the final selection's semantic identity.

    Covers selected roles, order, entity/state ids, authority scopes/facets, and
    content hashes. NOT affected by unselected candidates or diagnostic drops.
    Drives panel cache identity: a changed selected byte changes the fingerprint
    and invalidates dependent output; a changed unselected byte does not.
    """

    hexdigest: str


# ---------------------------------------------------------------------------
# Pose-crop preference (mirrors image_ref_strategy framing logic)
# ---------------------------------------------------------------------------

_SHOT_VIEW_PREFERENCES: dict[str, tuple[str, ...]] = {
    "close": ("front", "three_quarter", "profile", "gesture", "sheet"),
    "wide": ("gesture", "three_quarter", "front", "profile", "sheet"),
    "default": ("three_quarter", "front", "gesture", "profile", "sheet"),
}

_POSE_CROP_NAMES = ("front", "three_quarter", "profile", "gesture", "sheet")


def _shot_view_preference(composition: str | None) -> tuple[str, ...]:
    text = (composition or "").lower()
    if "close-up" in text or "close up" in text or "portrait" in text:
        return _SHOT_VIEW_PREFERENCES["close"]
    if any(token in text for token in ("wide", "establishing", "panorama", "full body")):
        return _SHOT_VIEW_PREFERENCES["wide"]
    return _SHOT_VIEW_PREFERENCES["default"]


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------


def _file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def _read_lineage_parent(state_meta_path: Path) -> str | None:
    """Return the recorded canonical-parent SHA-256 for a state asset, or None.

    Slice 08 state assets carry ``canonical_parent_sha256`` and an explicit
    lineage status. Pre-contract metadata remains unverified.
    """
    if not state_meta_path.exists():
        return None
    try:
        data = json.loads(state_meta_path.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(data, dict) and data.get("lineage_status") == "stale":
        return "stale"
    if isinstance(data, dict) and data.get("lineage_mode") == "unconditioned":
        return None
    value = (
        data.get("canonical_parent_sha256") or data.get("lineage_parent_sha256")
        if isinstance(data, dict) else None
    )
    return value if isinstance(value, str) and value else None


def _canonical_character_sheet(project_dir: Path, char_id: str) -> Path | None:
    sheet = project_dir / "refs" / char_id / "sheet.png"
    return sheet if sheet.exists() else None


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReferencePlan:
    """The finalized, immutable, capability-aware reference selection.

    Construct exclusively via :func:`build_reference_plan`. ``selected`` is the
    final upload-ordered set (capped, role-checked, state-safe, hashed).
    ``dropped`` carries every excluded candidate with its reason so callers can
    surface warnings. ``selection_fingerprint`` is the stable cache-identity
    hash over the selected plan.
    """

    expected_route: ImageRoute
    selected: tuple[ReferenceAsset, ...]
    dropped: tuple[DroppedReference, ...]
    selection_fingerprint: str
    #: Non-blocking diagnostics (e.g. unverified lineage) that do not exclude a
    #: selected asset but should be reported to the caller.
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ref_count(self) -> int:
        return len(self.selected)

    def to_ref_images(self) -> list:
        """Project the selected assets into provider ``RefImage`` objects.

        Prompt-domain code builds the plan; the provider layer consumes
        ``RefImage`` lists. This projection is the single bridge so the upload
        order and labels always derive from the plan.
        """
        from novel_to_comic.ai.providers.base import RefImage  # local: avoid HTTP import at module load

        return [
            RefImage(path=asset.path, role=asset.role, label=asset.label)
            for asset in self.selected
        ]


# ---------------------------------------------------------------------------
# Fingerprint
# ---------------------------------------------------------------------------


def selection_fingerprint_hex(selected: Iterable[ReferenceAsset]) -> str:
    """Stable SHA-256 over selected roles, order, entity/state ids, authority
    scopes/facets, and content hashes.

    Deterministic and independent of unselected candidates. Changing a selected
    file's bytes changes its ``content_sha256`` and therefore the fingerprint;
    changing an unselected candidate does not.
    """
    projection = []
    for asset in selected:
        projection.append({
            "role": asset.role,
            "entity_id": asset.entity_id,
            "appearance_state_id": asset.appearance_state_id,
            "authority_scope": asset.authority_scope.value,
            "preserve_facets": list(asset.preserve_facets),
            "ignore_facets": list(asset.ignore_facets),
            "content_sha256": asset.content_sha256,
        })
    blob = json.dumps(projection, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Candidate resolution (semantic, not path-based)
# ---------------------------------------------------------------------------


def _available_pose_crops(ref_dir: Path) -> list[Path]:
    """Pose crops available in a ref directory, in deterministic order."""
    found = []
    for name in _POSE_CROP_NAMES:
        candidate = ref_dir / f"{name}.png"
        if candidate.exists():
            found.append(candidate)
    return found


def _choose_pose_crop(
    ref_dir: Path,
    composition: str | None,
    primary_pose: str | None,
) -> Path | None:
    """Pick ONE framing-appropriate pose crop, honoring an explicit primary pose.

    Mirrors the one-crop-per-character rule: a user-chosen primary pose wins on
    every route, including state directories.
    """
    crops = _available_pose_crops(ref_dir)
    if not crops:
        return None
    by_stem = {p.stem: p for p in crops}
    if primary_pose and primary_pose in by_stem:
        return by_stem[primary_pose]
    preference = _shot_view_preference(composition)
    for stem in preference:
        if stem in by_stem:
            return by_stem[stem]
    return crops[0]


def _resolve_subject_candidates(
    project_dir: Path,
    prompt: ImagePrompt,
    primary_poses: dict[str, str],
    route: ImageRoute,
) -> list[SemanticCandidate]:
    """Resolve subject candidates from the panel's active character state ids.

    A character in a significant state with its own generated state refs uses
    the state directory; the canonical directory is only consulted for the
    base look or a compatible minor state. A significant state without its own
    refs produces NO canonical candidate (state-conflict rule) — the identity
    stays text-only rather than be conditioned by a contradictory full-body ref.
    """
    candidates: list[SemanticCandidate] = []
    composition = getattr(prompt, "composition", None)
    for subject in prompt.subjects:
        char_id = subject.character_id
        if not char_id:
            continue
        state_id = subject.appearance_state_id
        locked = getattr(subject, "appearance_locked", False)
        canonical_equivalent = getattr(
            subject, "appearance_state_canonical_equivalent", False
        )
        primary_pose = primary_poses.get(char_id)
        crop_composition = (
            "close-up portrait"
            if route is ImageRoute.GPT_IMAGE_2 and not primary_pose
            else composition
        )

        if state_id:
            state_dir = project_dir / "refs" / char_id / "states" / state_id
            state_crop = _choose_pose_crop(state_dir, crop_composition, primary_pose)
            if state_crop is not None:
                candidates.append(SemanticCandidate(
                    path=state_crop,
                    role="subject",
                    entity_id=char_id,
                    appearance_state_id=state_id,
                    is_state_ref=True,
                    canonical_equivalent=canonical_equivalent,
                    label=subject.name,
                ))
                continue
            # Significant state with no dedicated ref: do NOT fall back to a
            # canonical full-body ref (it would contradict the state). The
            # identity stays text-only. Minor (non-locked) states may use a
            # compatible canonical crop.
            if locked and not canonical_equivalent:
                continue

        # Base look, or a minor (non-significant) state without dedicated refs:
        # use the canonical directory.
        canon_dir = project_dir / "refs" / char_id
        canon_crop = _choose_pose_crop(canon_dir, crop_composition, primary_pose)
        expected_crop = canon_crop or canon_dir / f"{primary_pose or _shot_view_preference(crop_composition)[0]}.png"
        candidates.append(SemanticCandidate(
                path=expected_crop,
                role="subject",
                entity_id=char_id,
                appearance_state_id=state_id,
                is_state_ref=False,
                canonical_equivalent=canonical_equivalent,
                label=subject.name,
            ))
    return candidates


def _resolve_location_candidates(
    project_dir: Path,
    prompt: ImagePrompt,
    scene_to_location: dict[str, str] | None,
) -> list[SemanticCandidate]:
    loc_id = (
        getattr(prompt, "location_id", None)
        or (scene_to_location or {}).get(prompt.scene_id)
    )
    if not loc_id:
        return []
    state_id = getattr(prompt, "location_state_id", None)
    plates_dir = project_dir / "plates"
    if state_id:
        state_plate = plates_dir / f"{state_id}.png"
        if state_plate.exists():
            return [SemanticCandidate(
                path=state_plate,
                role="location_plate",
                entity_id=loc_id,
                appearance_state_id=state_id,
                is_state_ref=True,
                label=loc_id,
            )]
        # Missing active location-state plate: NO canonical substitution. Warn
        # and remain text-only for the location.
        return []
    plate = plates_dir / f"{loc_id}.png"
    return [SemanticCandidate(path=plate, role="location_plate", entity_id=loc_id, label=loc_id)]


def _resolve_prop_candidates(
    project_dir: Path,
    prop_ids: list[str] | None,
    critical_prop_ids: set[str],
) -> list[SemanticCandidate]:
    out: list[SemanticCandidate] = []
    for prop_id in prop_ids or []:
        ref = project_dir / "refs" / "props" / prop_id / "ref.png"
        out.append(SemanticCandidate(
            path=ref,
            role="prop",
            entity_id=prop_id,
            label=prop_id,
            critical=prop_id in critical_prop_ids,
        ))
    return out


def _resolve_style_candidates(style_sample: Path | None) -> list[SemanticCandidate]:
    if style_sample:
        return [SemanticCandidate(path=style_sample, role="style", label="selected style")]
    return []


def _resolve_continuity_candidates(
    project_dir: Path,
    prompt: ImagePrompt,
    prev_subject_states: dict[str, str | None] | None,
    prev_location_state_id: str | None,
    *,
    continuity_enabled: bool = True,
) -> list[SemanticCandidate]:
    """Resolve a previous-panel continuity candidate, suppressed when state
    authority changed across the boundary.

    Continuity references a prior panel's IMAGE, which freezes the entities as
    they looked then. If a subject's or location's active state changed across
    the boundary, the prior image would contradict the current state — so the
    continuity ref is suppressed unless an explicitly compatible match-cut
    policy holds (same subject/location state on both sides).

    ``continuity_enabled`` is the config/route gate (continuity_mode + route
    capability). When False, no continuity candidate is produced.
    """
    if not continuity_enabled:
        return []
    if prompt.panel_number <= 1:
        return []
    prev_image = project_dir / "draw" / prompt.scene_id / f"panel_{prompt.panel_number - 1:03d}.png"
    # State-authority compatibility: every subject in the current panel must
    # have the same active state as in the previous panel, and the location
    # state must match. A change suppresses continuity (except an explicitly
    # compatible match-cut, which by definition keeps the same state).
    prev_states = prev_subject_states or {}
    current_subject_ids = {
        subject.character_id for subject in prompt.subjects if subject.character_id
    }
    if current_subject_ids != set(prev_states):
        return []
    for subject in prompt.subjects:
        char_id = subject.character_id
        if not char_id:
            continue
        current_state = subject.appearance_state_id
        prior_state = prev_states.get(char_id)
        if current_state != prior_state:
            return []
    current_loc_state = getattr(prompt, "location_state_id", None)
    if current_loc_state != prev_location_state_id:
        return []

    return [SemanticCandidate(path=prev_image, role="continuity", label="previous panel")]


# ---------------------------------------------------------------------------
# Selection policy (table-driven)
# ---------------------------------------------------------------------------


def _contextual_priority(
    candidate: SemanticCandidate,
    *,
    has_location_state: bool,
    composition: str | None,
) -> int:
    """Deterministic priority for a contextual (non-subject) slot.

    Lower = higher priority. Active location state normally outranks a
    redundant style sample; explicit critical props and compatible continuity
    rank by shot type; style is the lowest-priority contextual ref.
    """
    role = candidate.role
    shot = _shot_view_preference(composition)[0]
    if role == "prop" and candidate.critical and shot == "front":
        return 0
    if role == "continuity":
        return 0
    if role == "location_plate":
        return 1 if has_location_state else 2
    if role == "prop":
        return 1 if candidate.critical else 3
    if role == "style":
        return 4
    return 5


# ---------------------------------------------------------------------------
# Asset materialization
# ---------------------------------------------------------------------------


def _materialize_subject_asset(
    candidate: SemanticCandidate,
    project_dir: Path,
) -> tuple[ReferenceAsset | None, DropReason | None, str | None]:
    """Verify readability, hash, and lineage; return an asset or a drop reason.

    Authority scope is assigned here:
    - dedicated significant-state ref → FULL_APPEARANCE
    - base-look / minor-state canonical ref → FULL_APPEARANCE (base) or
      IDENTITY_ONLY (minor text-only state)
    """
    if not candidate.path.exists():
        return (
            None,
            DropReason.MISSING,
            f"subject {candidate.label or candidate.entity_id or '<unknown>'} "
            f"has no readable ref at {candidate.path}",
        )
    content_hash = _file_sha256(candidate.path)
    if content_hash is None:
        return None, DropReason.UNREADABLE, f"cannot read subject ref: {candidate.path}"

    # Lineage: only state refs carry a parent hash.
    lineage_parent = None
    if candidate.is_state_ref:
        sheet_meta_path = candidate.path.parent / "sheet.png.meta.json"
        crop_meta_path = candidate.path.with_suffix(candidate.path.suffix + ".meta.json")
        meta_path = sheet_meta_path if sheet_meta_path.exists() else crop_meta_path
        lineage_parent = _read_lineage_parent(meta_path)
        if lineage_parent is not None:
            # Compare against the current canonical character sheet bytes.
            canon_sheet = _canonical_character_sheet(project_dir, candidate.entity_id or "")
            if canon_sheet is not None:
                canon_hash = _file_sha256(canon_sheet)
                if canon_hash is not None and canon_hash != lineage_parent:
                    return (
                        None,
                        DropReason.STALE_LINEAGE,
                        f"state ref {candidate.path} derived from canonical hash "
                        f"{lineage_parent[:12]}… but current canonical hash is "
                        f"{(canon_hash or '')[:12]}…",
                    )

    scope = AuthorityScope.FULL_APPEARANCE
    ignore_facets: tuple[str, ...] = ()
    if (
        candidate.appearance_state_id
        and not candidate.is_state_ref
        and not candidate.canonical_equivalent
    ):
        # A minor text-only state reusing a canonical crop: identity only.
        scope = AuthorityScope.IDENTITY_ONLY
        ignore_facets = _WARDROBE_FACETS + _ANATOMY_FACETS

    asset = ReferenceAsset(
        path=candidate.path,
        role="subject",
        entity_id=candidate.entity_id,
        appearance_state_id=candidate.appearance_state_id,
        authority_scope=scope,
        preserve_facets=_IDENTITY_FACETS if scope is AuthorityScope.IDENTITY_ONLY else _IDENTITY_FACETS + _WARDROBE_FACETS + _ANATOMY_FACETS,
        ignore_facets=ignore_facets,
        pose=candidate.path.stem,
        content_sha256=content_hash,
        lineage_parent_sha256=lineage_parent,
        label=candidate.label,
    )
    return asset, None, None


def _materialize_contextual_asset(
    candidate: SemanticCandidate,
    role: RefRole,
    project_dir: Path,
) -> tuple[ReferenceAsset | None, DropReason | None, str | None]:
    if not candidate.path.exists():
        return None, DropReason.MISSING, f"{role} ref not found: {candidate.path}"
    content_hash = _file_sha256(candidate.path)
    if content_hash is None:
        return None, DropReason.UNREADABLE, f"cannot read {role} ref: {candidate.path}"
    lineage_parent = None
    if role == "location_plate" and candidate.appearance_state_id:
        meta_path = candidate.path.with_suffix(candidate.path.suffix + ".meta.json")
        lineage_parent = _read_lineage_parent(meta_path)
        if lineage_parent is not None and candidate.entity_id:
            canonical = project_dir / "plates" / f"{candidate.entity_id}.png"
            canonical_hash = _file_sha256(canonical) if canonical.exists() else None
            if canonical_hash is not None and canonical_hash != lineage_parent:
                return (
                    None,
                    DropReason.STALE_LINEAGE,
                    f"location state plate {candidate.path} has parent hash "
                    f"{lineage_parent[:12]}… but current canonical hash is "
                    f"{canonical_hash[:12]}…",
                )
    asset = ReferenceAsset(
        path=candidate.path,
        role=role,
        entity_id=candidate.entity_id,
        appearance_state_id=candidate.appearance_state_id,
        authority_scope=AuthorityScope.CONTEXTUAL,
        preserve_facets=(),
        ignore_facets=(),
        pose=None,
        content_sha256=content_hash,
        lineage_parent_sha256=lineage_parent,
        label=candidate.label,
    )
    return asset, None, None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_reference_plan(
    *,
    route_profile: ImageModelProfile,
    project_dir: Path,
    prompt: ImagePrompt,
    style_sample: Path | None = None,
    scene_to_location: dict[str, str] | None = None,
    prop_ids: list[str] | None = None,
    critical_prop_ids: set[str] | None = None,
    primary_poses: dict[str, str] | None = None,
    prev_subject_states: dict[str, str | None] | None = None,
    prev_location_state_id: str | None = None,
    continuity_enabled: bool = False,
) -> ReferencePlan:
    """Build the one final, capability-aware, state-safe reference plan.

    This is the single selection owner. It:
    1. Resolves candidates from semantic ids + filesystem (not stored paths).
    2. Applies one-crop-per-character, state authority, and lineage rules.
    3. Enforces the route hard cap and role restrictions with a deterministic
       scarce-slot policy.
    4. Materializes the final selection (readability + SHA-256 + fingerprint).

    Subject overflow follows the text-only policy: unreferenced subjects are
    named in ``dropped`` diagnostics, never silently erased.
    """
    primary_poses = primary_poses or {}
    critical_prop_ids = set() if critical_prop_ids is None else critical_prop_ids
    dropped: list[DroppedReference] = []
    warnings: list[str] = []

    # ── 1. Resolve candidates ──────────────────────────────────────────────
    subject_candidates = _resolve_subject_candidates(
        project_dir, prompt, primary_poses, route_profile.route
    )
    location_candidates = _resolve_location_candidates(project_dir, prompt, scene_to_location)
    prop_candidates = _resolve_prop_candidates(
        project_dir, prop_ids, critical_prop_ids
    )
    style_candidates = _resolve_style_candidates(style_sample)
    continuity_candidates = _resolve_continuity_candidates(
        project_dir,
        prompt,
        prev_subject_states,
        prev_location_state_id,
        continuity_enabled=continuity_enabled,
    )

    # Report a missing location-state plate as a state_conflict drop so callers
    # know the location is text-only by policy, not by accident.
    loc_state_id = getattr(prompt, "location_state_id", None)
    if loc_state_id and not location_candidates:
        loc_id = getattr(prompt, "location_id", None) or (scene_to_location or {}).get(prompt.scene_id)
        dropped.append(DroppedReference(
            candidate=SemanticCandidate(
                path=project_dir / "plates" / f"{loc_state_id}.png",
                role="location_plate",
                entity_id=loc_id,
                appearance_state_id=loc_state_id,
                label=loc_id,
            ),
            reason=DropReason.STATE_CONFLICT,
            detail=f"active location state {loc_state_id} has no plate; not substituting canonical",
        ))

    # Report missing significant-state subject refs as state_conflict drops.
    for subject in prompt.subjects:
        char_id = subject.character_id
        if not char_id:
            continue
        if (
            subject.appearance_state_id
            and getattr(subject, "appearance_locked", False)
            and not getattr(subject, "appearance_state_canonical_equivalent", False)
        ):
            has_state_ref = any(
                c.entity_id == char_id and c.is_state_ref for c in subject_candidates
            )
            if not has_state_ref:
                dropped.append(DroppedReference(
                    candidate=SemanticCandidate(
                        path=project_dir / "refs" / char_id / "states" / subject.appearance_state_id / "front.png",
                        role="subject",
                        entity_id=char_id,
                        appearance_state_id=subject.appearance_state_id,
                        is_state_ref=True,
                        label=subject.name,
                    ),
                    reason=DropReason.STATE_CONFLICT,
                    detail=f"{subject.name} is in significant state "
                    f"{subject.appearance_state_id} with no dedicated ref; not "
                    "conditioning on the contradictory canonical full-body ref",
                ))

    # ── 2. Materialize subjects (one per character) ───────────────────────
    subject_assets: list[ReferenceAsset] = []
    seen_subject_chars: set[str] = set()
    for candidate in subject_candidates:
        char_id = candidate.entity_id
        if char_id and char_id in seen_subject_chars:
            dropped.append(DroppedReference(candidate=candidate, reason=DropReason.DUPLICATE_ENTITY,
                                            detail=f"second crop of {char_id} dropped (one per character)"))
            continue
        asset, reason, detail = _materialize_subject_asset(candidate, project_dir)
        if asset is None:
            assert reason is not None
            if reason is DropReason.UNREADABLE:
                raise ReferenceMaterializationError(detail or str(candidate.path))
            dropped.append(DroppedReference(candidate=candidate, reason=reason, detail=detail))
            continue
        # Unverified-lineage diagnostic for selected state refs (non-blocking).
        if candidate.is_state_ref and asset.lineage_parent_sha256 is None:
            warnings.append(
                f"unverified_lineage: state ref {asset.path} for {asset.entity_id} "
                f"has no recorded canonical parent hash"
            )
        subject_assets.append(asset)
        if char_id:
            seen_subject_chars.add(char_id)

    # ── 3. Enforce cap + overflow policy on subjects ──────────────────────
    cap = route_profile.max_references
    # Subjects claim slots first, up to the cap. If subjects alone exceed the
    # cap, the overflow is text-only (named in diagnostics).
    subject_slot_budget = min(len(subject_assets), cap)
    kept_subjects = subject_assets[:subject_slot_budget]
    remaining_slots = cap - len(kept_subjects)

    if len(subject_assets) > cap:
        for asset in subject_assets[cap:]:
            name = asset.label or asset.entity_id or "<unknown subject>"
            dropped.append(DroppedReference(
                candidate=asset,
                reason=DropReason.PROVIDER_CAP,
                detail=f"subject {name} could not be referenced; route cap {cap} reached "
                "(proceeding text-only for this subject)",
            ))

    # ── 4. Materialize + prioritize contextual refs into remaining slots ──
    has_location_state = bool(loc_state_id)
    contextual_candidates = (
        location_candidates + prop_candidates + style_candidates + continuity_candidates
    )
    if route_profile.route is ImageRoute.GPT_IMAGE_2 and kept_subjects:
        retained_contextual: list[SemanticCandidate] = []
        for candidate in contextual_candidates:
            if candidate.role == "prop":
                dropped.append(DroppedReference(
                    candidate=candidate,
                    reason=DropReason.LOWER_PRIORITY,
                    detail=(
                        "GPT Image 2 keeps prop refs text-only when subject "
                        "identity refs are present"
                    ),
                ))
            else:
                retained_contextual.append(candidate)
        contextual_candidates = retained_contextual

    # Filter unsupported roles first.
    route_roles = route_profile.supported_roles
    filtered_contextual: list[SemanticCandidate] = []
    for cand in contextual_candidates:
        if cand.role not in route_roles:
            dropped.append(DroppedReference(candidate=cand, reason=DropReason.UNSUPPORTED_ROLE,
                                            detail=f"route {route_profile.route.value} does not accept role {cand.role}"))
        else:
            filtered_contextual.append(cand)

    filtered_contextual.sort(key=lambda c: _contextual_priority(
        c,
        has_location_state=has_location_state,
        composition=getattr(prompt, "composition", None),
    ))

    contextual_assets: list[ReferenceAsset] = []
    for cand in filtered_contextual:
        asset, reason, detail = _materialize_contextual_asset(
            cand, cand.role, project_dir
        )
        if asset is None:
            assert reason is not None
            if reason is DropReason.UNREADABLE:
                raise ReferenceMaterializationError(detail or str(cand.path))
            dropped.append(DroppedReference(candidate=cand, reason=reason, detail=detail))
            continue
        if (
            cand.role == "location_plate"
            and cand.appearance_state_id
            and asset.lineage_parent_sha256 is None
        ):
            warnings.append(
                f"unverified_lineage: location state plate {asset.path} for "
                f"{asset.entity_id} has no recorded canonical parent hash"
            )
        contextual_assets.append(asset)

    # Fill remaining slots in priority order.
    kept_contextual: list[ReferenceAsset] = []
    for asset in contextual_assets:
        if remaining_slots <= 0:
            dropped.append(DroppedReference(candidate=asset, reason=DropReason.LOWER_PRIORITY,
                                            detail=f"{asset.role} ref dropped: route cap {cap} reached"))
            continue
        kept_contextual.append(asset)
        remaining_slots -= 1

    # ── 5. Final ordering (subjects first, then contextual by priority) ───
    final = list(kept_subjects) + list(kept_contextual)
    final.sort(key=lambda a: _SELECTION_ORDER.get(a.role, 99))

    fingerprint = selection_fingerprint_hex(final)
    return ReferencePlan(
        expected_route=route_profile.route,
        selected=tuple(final),
        dropped=tuple(dropped),
        selection_fingerprint=fingerprint,
        warnings=tuple(warnings),
    )


__all__ = [
    "AuthorityScope",
    "DroppedReference",
    "DropReason",
    "ImageModelProfile",
    "ReferenceAsset",
    "ReferencePlan",
    "ReferenceMaterializationError",
    "RefRole",
    "SemanticCandidate",
    "SelectionFingerprint",
    "build_reference_plan",
    "image_model_profile",
    "selection_fingerprint_hex",
]
