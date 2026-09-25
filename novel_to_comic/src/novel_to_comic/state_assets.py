"""Lifecycle contract for character and location alternate-state assets."""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, Location
from novel_to_comic.image_models import image_model_profile_for_config
from novel_to_comic.image_ref_strategy import RefStrategy
from novel_to_comic.style_contract import rendering_style_template

STATE_ASSET_SPEC_VERSION = 2


class LineageMode(StrEnum):
    UNCONDITIONED = "unconditioned"
    CONDITIONED = "conditioned"
    #: Total transformation/destruction with no compatible canonical facets. The
    #: canonical parent hash is retained as semantic lineage but not sent; the
    #: request generates from the self-contained state anchor.
    STATE_ONLY = "state_only"


class LineageStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNVERIFIED = "unverified"



# Value-bearing spans keep a change to one facet from looking like a change to
# every facet named in the same clause. The broad facet patterns above discover
# which facets are present; these patterns compare the local values.


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _relative(path: Path | None, project_dir: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)




def _revision(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())














class StateAssetGenerationSpec(BaseModel):
    spec_version: int = STATE_ASSET_SPEC_VERSION
    asset_kind: Literal["character_state_ref", "location_state_plate", "prop_state_ref"]
    entity_id: str
    state_id: str
    active_state_anchor: str
    continuity_guard: str | None = None
    baseline_affect: str | None = None
    canonical_parent_identity: str
    canonical_parent_path: str
    canonical_parent_sha256: str | None
    preserved_facets: tuple[str, ...]
    overridden_facets: tuple[str, ...]
    replaces_identity: bool = False
    style_path: str | None = None
    style_sha256: str | None = None
    configured_route_model: str
    configured_route: str
    requested_shape: Literal["square", "landscape"]
    effective_width: int
    effective_height: int
    state_addendum: str = ""
    state_addendum_revision: int = 0
    lineage_mode: LineageMode = LineageMode.UNCONDITIONED
    lineage_status: LineageStatus
    rendered_prompt: str
    # Provider-bound scene direction derived from the state spec, excluding the
    # protected active-state anchor and selected style text. This keeps the
    # state addendum/continuity rules on the shared compiler path without
    # duplicating protected anchors in the final prompt.
    state_direction: str = ""
    #: Reference roles + content hashes from the conditioning plan (Slice 09).
    #: Populated by ``build_state_reference_plan``; empty for pre-Slice-09 specs.
    reference_summary: tuple[dict, ...] = ()
    #: Every dropped candidate and its reason, retained for diagnostics and
    #: provenance rather than being lost with the transient ReferencePlan.
    reference_diagnostics: tuple[dict, ...] = ()
    #: Compiled/wire request identity hashes (Slice 09). Populated when the state
    #: request is compiled; remain ``None`` placeholders until provenance slices.
    compiled_request_sha256: str | None = None
    execution_fingerprint: str | None = None

    def lineage_metadata(self) -> dict:
        return {
            "state_asset_schema_version": self.spec_version,
            "asset_kind": self.asset_kind,
            "entity_id": self.entity_id,
            "state_id": self.state_id,
            "active_state_anchor": self.active_state_anchor,
            "rendered_prompt_sha256": hashlib.sha256(self.rendered_prompt.encode()).hexdigest(),
            "canonical_parent_path": self.canonical_parent_path,
            "canonical_parent_sha256": self.canonical_parent_sha256,
            "style_path": self.style_path,
            "style_sha256": self.style_sha256,
            "configured_route_model": self.configured_route_model,
            "configured_route": self.configured_route,
            "effective_dimensions": [self.effective_width, self.effective_height],
            "state_addendum_revision": self.state_addendum_revision,
            "lineage_mode": self.lineage_mode,
            "lineage_status": self.lineage_status,
            "reference_summary": [dict(item) for item in self.reference_summary],
            "reference_diagnostics": [dict(item) for item in self.reference_diagnostics],
            "compiled_request_sha256": self.compiled_request_sha256,
            "execution_fingerprint": self.execution_fingerprint,
            "generated_request_link": None,
            "provenance_link": None,
            "preserved_facets": list(self.preserved_facets),
            "overridden_facets": list(self.overridden_facets),
            "replaces_identity": self.replaces_identity,
        }


def build_character_state_spec(
    config: Config, project_dir: Path, char: Character, state: AppearanceState,
    *, style_path: Path | None = None,
) -> StateAssetGenerationSpec:
    parent = artifacts.character_ref_sheet_path(project_dir, char.id)
    instructions = artifacts.character_state_ref_instructions_path(project_dir, char.id, state.id)
    addendum = artifacts.read_active_addendum(instructions)
    overridden = set(state.changed_facets)
    prompt_parts = [
        rendering_style_template(config.style_template),
        f"CHARACTER STATE REFERENCE SHEET — {char.name} ({state.label}).",
        state.visual_anchor,
    ]
    direction_parts = [f"CHARACTER STATE REFERENCE SHEET — {char.name} ({state.label})."]
    if state.continuity_guard:
        prompt_parts.append(state.continuity_guard)
    composition = (
        "One wide appearance-state reference sheet: in the left third, a head-and-shoulders "
        "three-quarter portrait above a head-and-shoulders side profile; in the right two "
        "thirds, one full-body front view in a neutral design stance compatible with the "
        "active-state anatomy. Show only how this state looks on the body, face, hair and "
        "clothing; leave out objects that pierce, pin, bind or are held, other people, "
        "scenery, and the situation itself, keeping only their visible marks. The selected "
        "style owns rendering. Same active identity and appearance in all three views, each "
        "fully contained within its own region. No text or labels."
    )
    prompt_parts.append(composition)
    direction_parts.append(composition)
    parent_hash = _sha256(parent)
    return StateAssetGenerationSpec(
        asset_kind="character_state_ref", entity_id=char.id, state_id=state.id,
        active_state_anchor=state.visual_anchor, canonical_parent_identity=char.visual_anchor,
        continuity_guard=state.continuity_guard,
        # Only an authored state affect belongs on a sheet; everyday demeanor is acting.
        baseline_affect=state.baseline_affect,
        canonical_parent_path=_relative(parent, project_dir) or "", canonical_parent_sha256=parent_hash,
        preserved_facets=() if state.replaces_identity else ("identity",),
        overridden_facets=tuple(sorted(overridden)), replaces_identity=state.replaces_identity, style_path=_relative(style_path, project_dir),
        style_sha256=_sha256(style_path), configured_route_model=config.effective_image_model(),
        configured_route=image_model_profile_for_config(config).route.value,
        requested_shape="landscape", effective_width=state_reference_dimensions(config, "character")[0],
        effective_height=state_reference_dimensions(config, "character")[1],
        state_addendum=addendum, state_addendum_revision=_revision(instructions),
        lineage_status=LineageStatus.UNVERIFIED,
        rendered_prompt="\n\n".join(part for part in prompt_parts if part),
        state_direction="\n\n".join(part for part in direction_parts if part),
    )


def state_reference_dimensions(config: Config, asset_kind: str) -> tuple[int | None, int | None]:
    """Generation size of one state reference; specs and quotes share it."""
    if asset_kind == "character":
        return 1536, 1024
    if asset_kind == "location":
        return RefStrategy.for_config(config).location_plate_dimensions()
    return 1024, 1024


def build_location_state_spec(
    config: Config, project_dir: Path, loc: Location, state: AppearanceState,
    *, style_path: Path | None = None,
) -> StateAssetGenerationSpec:
    parent = artifacts.location_plate_path(project_dir, loc.id)
    instructions = artifacts.location_state_plate_instructions_path(project_dir, loc.id, state.id)
    addendum = artifacts.read_active_addendum(instructions)
    overridden = set(state.changed_facets)
    prompt_parts = [rendering_style_template(config.style_template), "LOCATION STATE DESIGN PLATE", state.visual_anchor]
    direction_parts = ["LOCATION STATE DESIGN PLATE"]
    composition = "Wide environment plate. Active-state conditions win. No characters or text."
    prompt_parts.append(composition)
    direction_parts.append(composition)
    width, height = state_reference_dimensions(config, "location")
    parent_hash = _sha256(parent)
    return StateAssetGenerationSpec(
        asset_kind="location_state_plate", entity_id=loc.id, state_id=state.id,
        active_state_anchor=state.visual_anchor, canonical_parent_identity=loc.visual_anchor,
        continuity_guard=state.continuity_guard,
        canonical_parent_path=_relative(parent, project_dir) or "", canonical_parent_sha256=parent_hash,
        preserved_facets=(),
        overridden_facets=tuple(sorted(overridden)), replaces_identity=state.replaces_identity, style_path=_relative(style_path, project_dir),
        style_sha256=_sha256(style_path), configured_route_model=config.effective_image_model(),
        configured_route=image_model_profile_for_config(config).route.value,
        requested_shape="landscape", effective_width=width, effective_height=height,
        state_addendum=addendum, state_addendum_revision=_revision(instructions),
        lineage_status=LineageStatus.UNVERIFIED,
        rendered_prompt="\n\n".join(part for part in prompt_parts if part),
        state_direction="\n\n".join(part for part in direction_parts if part),
    )


def mark_dependent_states_stale(
    project_dir: Path, asset_kind: Literal["character", "location"], entity_id: str,
) -> list[dict]:
    parent = (
        artifacts.character_ref_sheet_path(project_dir, entity_id)
        if asset_kind == "character" else artifacts.location_plate_path(project_dir, entity_id)
    )
    current_hash = _sha256(parent)
    pattern = (project_dir / "refs" / entity_id / "states" if asset_kind == "character"
               else project_dir / "plates" / entity_id / "states")
    warnings: list[dict] = []
    for meta_path in sorted(pattern.glob("**/*.png.meta.json")) if pattern.exists() else []:
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        if meta.get("entity_id") != entity_id:
            continue
        if current_hash is not None and meta.get("canonical_parent_sha256") == current_hash:
            continue
        meta["lineage_status"] = LineageStatus.STALE
        meta["lineage_warning"] = {
            "code": "state_asset_regeneration_required",
            "entity_id": entity_id,
            "state_id": meta.get("state_id"),
            "expected_parent_sha256": meta.get("canonical_parent_sha256"),
            "current_parent_sha256": current_hash,
        }
        meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
        warnings.append(meta["lineage_warning"])
    return warnings


def revalidate_state_asset_lineage(state_path: Path, parent_path: Path) -> dict | None:
    """Revalidate restored/current state metadata against canonical bytes.

    Slice 09: conditioned and state-only assets whose parent hash still matches
    are current; only unconditioned assets remain unverified (they were never
    conditioned on the canonical parent).
    """
    meta = artifacts.read_asset_meta(state_path)
    if not meta:
        return None
    parent_hash = _sha256(parent_path)
    if parent_hash is None or meta.get("canonical_parent_sha256") != parent_hash:
        meta["lineage_status"] = LineageStatus.STALE
        meta["lineage_warning"] = {
            "code": "state_asset_regeneration_required",
            "entity_id": meta.get("entity_id"),
            "state_id": meta.get("state_id"),
            "expected_parent_sha256": meta.get("canonical_parent_sha256"),
            "current_parent_sha256": parent_hash,
        }
        artifacts.write_asset_meta(state_path, meta)
    else:
        mode = meta.get("lineage_mode")
        if mode == LineageMode.UNCONDITIONED:
            meta["lineage_status"] = LineageStatus.UNVERIFIED
            meta.pop("lineage_warning", None)
            artifacts.write_asset_meta(state_path, meta)
        elif mode in (LineageMode.CONDITIONED, LineageMode.STATE_ONLY):
            # Parent hash matches: a conditioned/state-only asset is current.
            meta["lineage_status"] = LineageStatus.CURRENT
            meta.pop("lineage_warning", None)
            artifacts.write_asset_meta(state_path, meta)
    return meta


# ---------------------------------------------------------------------------
# Slice 09 — canonical-conditioned reference plan for state assets
# ---------------------------------------------------------------------------

#: Character identity facets the canonical parent can safely condition even when
#: a state overrides mutable facets (clothing, anatomy, age, hair). A dedicated
#: state ref carries full appearance authority; the canonical parent used as a
#: compatible identity reference preserves only these facets.
_CHARACTER_IDENTITY_FACETS: tuple[str, ...] = ("face", "hair", "build")


#: Facets that a character state anchor may override. When overridden, the
#: canonical parent ignores them (it must not reassert the canonical version).
_CHARACTER_OVERRIDABLE_FACETS: dict[str, tuple[str, ...]] = {
    "age": ("age", "build", "proportions"),
    "hair": ("hair",),
    "face": ("face",),
    "build": ("build", "proportions", "silhouette"),
    "anatomy": ("anatomy", "build", "proportions", "silhouette"),
    "clothing": ("wardrobe",),
}

#: Location identity facets the canonical plate can safely condition.
_LOCATION_IDENTITY_FACETS: tuple[str, ...] = ("architecture", "landmarks", "materials")

#: Facets that a location state anchor may override. When overridden, the
#: canonical plate defers to the active state's version of that facet.
_LOCATION_OVERRIDABLE_FACETS: dict[str, tuple[str, ...]] = {
    "architecture": ("architecture",),
    "damage": ("damage",),
    "water_level": ("water_level",),
    "weather": ("weather",),
    "light": ("light",),
    "atmosphere": ("atmosphere",),
}

#: State-anchor facets that represent a TOTAL transformation: when every one of
#: a parent's identity facets is overridden, the parent is contradictory and is
#: omitted rather than sent. Identity facets are face, hair, build — when all
#: three are changed, the canonical parent has nothing compatible to offer.


#: Patterns that signal a total identity replacement (human → non-human form),
#: even when not every identity facet keyword appears. Used as an additional
#: total-transformation signal beyond facet-keyword comparison.


class StateConditioningError(ValueError):
    """A state asset cannot be safely conditioned on its canonical parent."""


def _character_state_is_total(spec: StateAssetGenerationSpec) -> bool:
    return spec.replaces_identity


def _location_state_is_total(spec: StateAssetGenerationSpec) -> bool:
    return spec.replaces_identity


def state_is_total_transformation(spec: StateAssetGenerationSpec) -> bool:
    """Return whether a state replaces every useful canonical identity facet."""
    return (
        _character_state_is_total(spec)
        if spec.asset_kind == "character_state_ref"
        else _location_state_is_total(spec)
    )


def _map_overridden_facets(
    overridden_facets: tuple[str, ...], table: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """Map state-anchor facet names to the identity-facet vocabulary the
    reference plan uses (e.g. state ``clothing`` → plan ``wardrobe``)."""
    out: list[str] = []
    for facet in overridden_facets:
        out.extend(table.get(facet, (facet,)))
    return tuple(dict.fromkeys(out))  # dedupe preserving order


def _build_character_conditioning_assets(
    spec: StateAssetGenerationSpec,
    project_dir: Path,
    parent_path: Path,
    parent_hash: str,
    *,
    route_profile,
) -> tuple[list, list, bool]:
    """Resolve the canonical character identity reference + style for a state.

    Returns (assets, dropped, is_total_transformation).
    """
    from novel_to_comic.image_references import (
        AuthorityScope,
        DroppedReference,
        DropReason,
        ReferenceAsset,
        SemanticCandidate,
    )

    # A total transformation replaces every useful identity facet (face, hair,
    # build), or explicitly describes a non-human/incompatible form.
    is_total = _character_state_is_total(spec)
    changed = set(spec.overridden_facets)
    changed_mapped = _map_overridden_facets(
        tuple(sorted(changed)), _CHARACTER_OVERRIDABLE_FACETS
    )
    # A total transformation replaces every useful identity facet — face is the
    # only thing the canonical parent could still offer, but a winged serpent
    # with no human face has nothing compatible left.
    if is_total:
        dropped = [DroppedReference(
            candidate=SemanticCandidate(
                path=parent_path, role="subject", entity_id=spec.entity_id,
                appearance_state_id=spec.state_id, label=spec.entity_id,
            ),
            reason=DropReason.STATE_CONFLICT,
            detail=(
                f"state {spec.state_id} is a total transformation; every "
                "identity facet is overridden — the canonical parent is "
                "contradictory and omitted"
            ),
        )]
        return [], dropped, True

    ignore_facets = changed_mapped
    # Identity facets not overridden are what the parent can still condition.
    preserve_facets = tuple(
        f for f in _CHARACTER_IDENTITY_FACETS if f not in set(ignore_facets)
    )
    asset = ReferenceAsset(
        path=parent_path,
        role="subject",
        entity_id=spec.entity_id,
        appearance_state_id=spec.state_id,
        authority_scope=AuthorityScope.IDENTITY_ONLY,
        preserve_facets=preserve_facets,
        ignore_facets=ignore_facets,
        pose="sheet",
        content_sha256=parent_hash,
        lineage_parent_sha256=parent_hash,
        label=spec.entity_id,
    )
    return [asset], [], False


def _build_location_conditioning_assets(
    spec: StateAssetGenerationSpec,
    project_dir: Path,
    parent_path: Path,
    parent_hash: str,
    *,
    route_profile,
) -> tuple[list, list, bool]:
    """Resolve the canonical location identity reference + style for a state.

    Returns (assets, dropped, is_total_transformation).
    """
    from novel_to_comic.image_references import (
        AuthorityScope,
        DroppedReference,
        DropReason,
        ReferenceAsset,
        SemanticCandidate,
    )

    changed_loc = set(spec.overridden_facets)
    # A total location destruction explicitly negates core structure and is
    # irrecoverable. When the anchor removes the primary landmark AND signals
    # annihilation, the canonical plate is contradictory and omitted.
    is_total = _location_state_is_total(spec)
    if is_total:
        dropped = [DroppedReference(
            candidate=SemanticCandidate(
                path=parent_path, role="prop" if spec.asset_kind == "prop_state_ref" else "location_plate", entity_id=spec.entity_id,
                appearance_state_id=spec.state_id, label=spec.entity_id,
            ),
            reason=DropReason.STATE_CONFLICT,
            detail=(
                f"state {spec.state_id} is a total destruction; every location "
                "facet is overridden — the canonical plate is contradictory "
                "and omitted"
            ),
        )]
        return [], dropped, True

    preserve_facets = tuple(
        facet for facet in (("shape", "materials", "color") if spec.asset_kind == "prop_state_ref" else _LOCATION_IDENTITY_FACETS) if facet not in changed_loc
    )
    ignore_facets = tuple(sorted(changed_loc))
    asset = ReferenceAsset(
        path=parent_path,
        role="prop" if spec.asset_kind == "prop_state_ref" else "location_plate",
        entity_id=spec.entity_id,
        appearance_state_id=spec.state_id,
        authority_scope=AuthorityScope.CONTEXTUAL,
        preserve_facets=preserve_facets,
        ignore_facets=ignore_facets,
        pose=None,
        content_sha256=parent_hash,
        lineage_parent_sha256=parent_hash,
        label=spec.entity_id,
    )
    return [asset], [], False


def _maybe_style_asset(
    spec: StateAssetGenerationSpec, project_dir: Path
) -> tuple[object | None, object | None]:
    """Build a style reference asset from the spec's style path, if present.

    The spec stores a project-relative style path; resolve it against
    ``project_dir``.
    """
    if not spec.style_path:
        return None, None
    style_path = Path(spec.style_path)
    if not style_path.is_absolute():
        style_path = project_dir / style_path
    from novel_to_comic.image_references import (
        AuthorityScope,
        DropReason,
        DroppedReference,
        ReferenceAsset,
        SemanticCandidate,
        _file_sha256,
    )

    candidate = SemanticCandidate(path=style_path, role="style", label="selected style")
    if not style_path.exists():
        spec.style_sha256 = None
        return None, DroppedReference(
            candidate=candidate,
            reason=DropReason.MISSING,
            detail=f"style reference is missing at {style_path}",
        )
    content_hash = _file_sha256(style_path)
    if content_hash is None:
        spec.style_sha256 = None
        return None, DroppedReference(
            candidate=candidate,
            reason=DropReason.UNREADABLE,
            detail=f"style reference is unreadable at {style_path}",
        )
    # The path is resolved at request-build time. If its bytes changed after
    # the spec was created, the selected reference and persisted metadata must
    # use the same current digest.
    spec.style_sha256 = content_hash
    return ReferenceAsset(
        path=style_path, role="style", entity_id=None, appearance_state_id=None,
        authority_scope=AuthorityScope.CONTEXTUAL,
        preserve_facets=(), ignore_facets=(), pose=None,
        content_sha256=content_hash, lineage_parent_sha256=None,
        label="selected style",
    ), None


def build_state_reference_plan(
    spec: StateAssetGenerationSpec,
    project_dir: Path,
    *,
    route_profile=None,
):
    """Build the canonical-conditioned reference plan for a state asset.

    The plan reuses the Slice 04 ``ReferencePlan`` type and route caps: the
    canonical parent (character sheet / location plate) is selected as a
    compatible identity reference whose ``ignore_facets`` cover every facet the
    active state overrides. Style is added when the route cap has room.

    - When the state spec records a canonical parent hash, the parent bytes on
      disk are verified against it. A missing or digest-mismatched parent fails
      with :class:`StateConditioningError` before any provider I/O.
    - A total transformation/destruction (no compatible identity facets) omits
      the contradictory parent, records a ``state_conflict`` drop, and sets
      ``lineage_mode=state_only``.

    The spec's ``lineage_mode``/``lineage_status`` and ``reference_summary`` are
    updated as a side effect so the persisted metadata reflects the plan.
    """
    from novel_to_comic.image_references import (
        DroppedReference,
        DropReason,
        ReferencePlan,
        selection_fingerprint_hex,
        _SELECTION_ORDER,
    )

    if route_profile is None:
        # Derive the route profile from the spec's recorded route/model. Re-load
        # a minimal config-like object: the spec already carries the route name.
        from novel_to_comic.image_models import ImageRoute
        route_name = spec.configured_route
        route = next(
            (r for r in ImageRoute if r.value == route_name), ImageRoute.UNKNOWN
        )
        route_profile = image_model_profile_for_route(route)

    is_character = spec.asset_kind == "character_state_ref"
    is_prop = spec.asset_kind == "prop_state_ref"
    parent_path = (
        artifacts.character_ref_sheet_path(project_dir, spec.entity_id)
        if is_character else artifacts.prop_ref_path(project_dir, spec.entity_id)
        if is_prop else artifacts.location_plate_path(project_dir, spec.entity_id)
    )

    # ── 1. Verify canonical parent exists and matches the recorded digest. ──
    if not parent_path.exists():
        raise StateConditioningError(
            f"canonical parent for state {spec.entity_id}:{spec.state_id} is "
            f"missing at {parent_path} — cannot condition state asset without a "
            "canonical parent"
        )
    try:
        parent_hash = _file_sha256_for_state(parent_path)
    except OSError as exc:
        raise StateConditioningError(
            f"canonical parent for state {spec.entity_id}:{spec.state_id} is "
            f"unreadable at {parent_path} — cannot condition state asset"
        ) from exc
    recorded_hash = spec.canonical_parent_sha256
    if recorded_hash is not None and parent_hash != recorded_hash:
        raise StateConditioningError(
            f"canonical parent for state {spec.entity_id}:{spec.state_id} has "
            f"changed (expected {recorded_hash[:12]}…, got {parent_hash[:12]}…) "
            "— regenerate the canonical asset before conditioning the state"
        )
    if recorded_hash is None:
        spec.canonical_parent_sha256 = parent_hash

    # ── 2. Resolve canonical identity candidate (compatibility-checked). ─────
    if is_character:
        assets, dropped, is_total = _build_character_conditioning_assets(
            spec, project_dir, parent_path, parent_hash, route_profile=route_profile,
        )
    else:
        assets, dropped, is_total = _build_location_conditioning_assets(
            spec, project_dir, parent_path, parent_hash, route_profile=route_profile,
        )

    required_role = "subject" if is_character else "prop" if is_prop else "location_plate"
    if not is_total and required_role not in route_profile.supported_roles:
        raise StateConditioningError(
            f"route {route_profile.route.value} does not support {required_role} "
            f"references for state {spec.entity_id}:{spec.state_id}"
        )

    # ── 3. Add style where space permits (lower priority than identity). ─────
    style_asset, style_drop = _maybe_style_asset(spec, project_dir)
    if style_drop is not None:
        dropped.append(style_drop)

    cap = route_profile.max_references

    # Identity assets claim slots first; canonical identity has priority over
    # redundant style under a tight cap.
    selected: list = []
    for asset in assets:
        if len(selected) >= cap:
            dropped.append(DroppedReference(
                candidate=asset,
                reason=DropReason.PROVIDER_CAP,
                detail=f"{asset.role} dropped: route cap {cap} reached",
            ))
        else:
            selected.append(asset)

    # Style fills a remaining slot only if the route accepts it.
    if style_asset is not None:
        if "style" in route_profile.supported_roles:
            if len(selected) < cap:
                selected.append(style_asset)
            else:
                dropped.append(DroppedReference(
                    candidate=style_asset,
                    reason=DropReason.PROVIDER_CAP,
                    detail=(
                        "style dropped: route cap reached — canonical identity "
                        "kept; style is redundant"
                    ),
                ))
        else:
            dropped.append(DroppedReference(
                candidate=style_asset,
                reason=DropReason.UNSUPPORTED_ROLE,
                detail=f"route {route_profile.route.value} does not accept style refs",
            ))

    # ── 4. Final ordering (subjects before contextual). ─────────────────────
    selected.sort(key=lambda a: _SELECTION_ORDER.get(a.role, 99))
    fingerprint = selection_fingerprint_hex(selected)

    # ── 5. Update the spec's lineage mode/status + reference summary. ───────
    if is_total:
        spec.lineage_mode = LineageMode.STATE_ONLY
        spec.lineage_status = LineageStatus.CURRENT
    else:
        spec.lineage_mode = LineageMode.CONDITIONED
        spec.lineage_status = LineageStatus.CURRENT
    spec.reference_summary = tuple(
        {
            "role": a.role,
            "entity_id": a.entity_id,
            "content_sha256": a.content_sha256,
            "authority_scope": a.authority_scope.value,
            "ignore_facets": list(a.ignore_facets),
            "preserve_facets": list(a.preserve_facets),
        }
        for a in selected
    )
    spec.reference_diagnostics = tuple(
        {
            "path": _relative(drop.candidate.path, project_dir),
            "role": drop.candidate.role,
            "entity_id": drop.candidate.entity_id,
            "appearance_state_id": drop.candidate.appearance_state_id,
            "reason": drop.reason.value,
            "detail": drop.detail,
        }
        for drop in dropped
    )

    return ReferencePlan(
        expected_route=route_profile.route,
        selected=tuple(selected),
        dropped=tuple(dropped),
        selection_fingerprint=fingerprint,
        warnings=(),
    )


def _file_sha256_for_state(path: Path) -> str:
    """Streaming SHA-256 for a state-asset parent file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def image_model_profile_for_route(route) -> object:
    """Resolve an :class:`ImageModelProfile` from an :class:`ImageRoute`.

    Thin wrapper so state conditioning can derive the cap/roles from the spec's
    recorded route without a full ``Config``.
    """
    from novel_to_comic.image_models import _profile_for_route
    return _profile_for_route(route)


__all__ = [
    "LineageMode", "LineageStatus", "STATE_ASSET_SPEC_VERSION",
    "StateAssetGenerationSpec", "StateConditioningError",
    "build_character_state_spec", "build_location_state_spec",
    "build_state_reference_plan", "mark_dependent_states_stale",
    "revalidate_state_asset_lineage", "state_is_total_transformation",
]


def build_prop_state_spec(config: Config, project_dir: Path, prop, state: AppearanceState, *, style_path: Path | None = None) -> StateAssetGenerationSpec:
    parent = artifacts.prop_ref_path(project_dir, prop.id)
    direction = f"Depict only {prop.name} in state {state.label}. Neutral background. No text."
    return StateAssetGenerationSpec(
        asset_kind="prop_state_ref", entity_id=prop.id, state_id=state.id,
        active_state_anchor=state.visual_anchor, canonical_parent_identity=prop.visual_anchor,
        continuity_guard=state.continuity_guard,
        canonical_parent_path=_relative(parent, project_dir) or "", canonical_parent_sha256=_sha256(parent),
        preserved_facets=("identity",), overridden_facets=state.changed_facets,
        replaces_identity=state.replaces_identity,
        style_path=_relative(style_path, project_dir), style_sha256=_sha256(style_path),
        configured_route_model=config.effective_image_model(), configured_route=image_model_profile_for_config(config).route.value,
        requested_shape="square", effective_width=state_reference_dimensions(config, "prop")[0],
        effective_height=state_reference_dimensions(config, "prop")[1],
        lineage_status=LineageStatus.UNVERIFIED, rendered_prompt=direction + "\n" + state.visual_anchor, state_direction=direction,
    )
