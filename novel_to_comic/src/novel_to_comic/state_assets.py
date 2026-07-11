"""Lifecycle contract for character and location alternate-state assets."""

from __future__ import annotations

import hashlib
import json
import re
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

STATE_ASSET_SPEC_VERSION = 1


class LineageMode(StrEnum):
    UNCONDITIONED = "unconditioned"
    CONDITIONED = "conditioned"


class LineageStatus(StrEnum):
    CURRENT = "current"
    STALE = "stale"
    UNVERIFIED = "unverified"


_FACET_PATTERNS: dict[str, tuple[str, ...]] = {
    "age": (r"\bage[sd]?\b", r"\byears? old\b", r"\b(?:young|old|elderly|teen)\b"),
    "hair": (r"\bhair\b", r"\bbald\b", r"\bbraids?\b"),
    "anatomy": (r"\b(?:hand|limb|arm|leg|stump|prosthe|wing|tail|body)\w*\b",),
    "clothing": (r"\b(?:wear|coat|tunic|dress|shirt|trouser|robe|outfit|jacket|armor|clothing)\w*\b",),
    "damage": (r"\b(?:damage|ruin|collapse|crack|burn|broken|destroy|wound|scar|blood)\w*\b",),
    "weather": (r"\b(?:rain|storm|snow|fog|sunny|wind|weather)\w*\b",),
    "light": (r"\b(?:day|night|dawn|dusk|noon|moon|sun|light|dark)\w*\b",),
    "water_level": (r"\b(?:lake|river|water|flood|drain|dry|mud)\w*\b",),
    "architecture": (r"\b(?:wall|roof|building|house|tower|bridge|architecture)\w*\b",),
    "atmosphere": (r"\b(?:mood|peaceful|tense|desolate|atmosphere|eerie|calm|storm)\w*\b",),
}


def _sha256(path: Path | None) -> str | None:
    if path is None or not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _relative(path: Path | None, project_dir: Path) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(project_dir))
    except ValueError:
        return str(path)


def _facets(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    return tuple(
        facet for facet, patterns in _FACET_PATTERNS.items()
        if any(re.search(pattern, lowered) for pattern in patterns)
    )


def _revision(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for line in path.read_text().splitlines() if line.strip())


def _stable_clauses(anchor: str, overridden: set[str]) -> list[str]:
    clauses = [part.strip() for part in re.split(r"[,;]", anchor) if part.strip()]
    return [clause for clause in clauses if not (set(_facets(clause)) & overridden)]


class StateAssetGenerationSpec(BaseModel):
    spec_version: int = STATE_ASSET_SPEC_VERSION
    asset_kind: Literal["character_state_ref", "location_state_plate"]
    entity_id: str
    state_id: str
    active_state_anchor: str
    canonical_parent_identity: str
    canonical_parent_path: str
    canonical_parent_sha256: str | None
    preserved_facets: tuple[str, ...]
    overridden_facets: tuple[str, ...]
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
            "generated_request_link": None,
            "provenance_link": None,
            "preserved_facets": list(self.preserved_facets),
            "overridden_facets": list(self.overridden_facets),
        }


def build_character_state_spec(
    config: Config, project_dir: Path, char: Character, state: AppearanceState,
    *, style_path: Path | None = None,
) -> StateAssetGenerationSpec:
    parent = artifacts.character_ref_sheet_path(project_dir, char.id)
    instructions = artifacts.character_state_ref_instructions_path(project_dir, char.id, state.id)
    addendum = artifacts.read_active_addendum(instructions)
    overridden = set(_facets(state.visual_anchor))
    stable_features = [f for f in char.distinguishing_features if not (set(_facets(f)) & overridden)]
    prompt_parts = [
        config.style_template.strip(),
        f"CHARACTER STATE REFERENCE SHEET — {char.name} ({state.label}).",
        state.visual_anchor,
    ]
    if stable_features:
        prompt_parts.append("Preserve permanent identity marks: " + "; ".join(stable_features) + ".")
    if state.continuity_guard:
        prompt_parts.append("Keep the active state's changed anatomy consistent in every view.")
    if addendum:
        prompt_parts.append(f"USER STATE FIX NOTE: {addendum}")
    prompt_parts.append(
        "One square 2x2 reference sheet: front, three-quarter, profile, and neutral mid-action views. "
        "Use only poses compatible with the anatomy in the active-state anchor. Same identity and active-state appearance in every view. No text or labels."
    )
    parent_hash = _sha256(parent)
    return StateAssetGenerationSpec(
        asset_kind="character_state_ref", entity_id=char.id, state_id=state.id,
        active_state_anchor=state.visual_anchor, canonical_parent_identity=char.visual_anchor,
        canonical_parent_path=_relative(parent, project_dir) or "", canonical_parent_sha256=parent_hash,
        preserved_facets=("identity", *(() if not stable_features else ("distinguishing_features",))),
        overridden_facets=tuple(sorted(overridden)), style_path=_relative(style_path, project_dir),
        style_sha256=_sha256(style_path), configured_route_model=config.effective_image_model(),
        configured_route=image_model_profile_for_config(config).route.value,
        requested_shape="square", effective_width=1024, effective_height=1024,
        state_addendum=addendum, state_addendum_revision=_revision(instructions),
        lineage_status=LineageStatus.UNVERIFIED,
        rendered_prompt="\n\n".join(part for part in prompt_parts if part),
    )


def build_location_state_spec(
    config: Config, project_dir: Path, loc: Location, state: AppearanceState,
    *, style_path: Path | None = None,
) -> StateAssetGenerationSpec:
    parent = artifacts.location_plate_path(project_dir, loc.id)
    instructions = artifacts.location_state_plate_instructions_path(project_dir, loc.id, state.id)
    addendum = artifacts.read_active_addendum(instructions)
    overridden = set(_facets(state.visual_anchor))
    stable = _stable_clauses(loc.visual_anchor, overridden)
    prompt_parts = [config.style_template.strip(), "LOCATION STATE DESIGN PLATE", state.visual_anchor]
    if stable:
        prompt_parts.append("Preserve non-conflicting stable landmarks: " + ", ".join(stable) + ".")
    if addendum:
        prompt_parts.append(f"USER STATE FIX NOTE: {addendum}")
    prompt_parts.append("Wide environment plate. Active-state conditions win. No characters or text.")
    width, height = RefStrategy.for_config(config).location_plate_dimensions()
    parent_hash = _sha256(parent)
    return StateAssetGenerationSpec(
        asset_kind="location_state_plate", entity_id=loc.id, state_id=state.id,
        active_state_anchor=state.visual_anchor, canonical_parent_identity=loc.visual_anchor,
        canonical_parent_path=_relative(parent, project_dir) or "", canonical_parent_sha256=parent_hash,
        preserved_facets=tuple(f"landmark:{item}" for item in stable),
        overridden_facets=tuple(sorted(overridden)), style_path=_relative(style_path, project_dir),
        style_sha256=_sha256(style_path), configured_route_model=config.effective_image_model(),
        configured_route=image_model_profile_for_config(config).route.value,
        requested_shape="landscape", effective_width=width, effective_height=height,
        state_addendum=addendum, state_addendum_revision=_revision(instructions),
        lineage_status=LineageStatus.UNVERIFIED,
        rendered_prompt="\n\n".join(part for part in prompt_parts if part),
    )


def mark_dependent_states_stale(
    project_dir: Path, asset_kind: Literal["character", "location"], entity_id: str,
) -> list[dict]:
    parent = (
        artifacts.character_ref_sheet_path(project_dir, entity_id)
        if asset_kind == "character" else artifacts.location_plate_path(project_dir, entity_id)
    )
    current_hash = _sha256(parent)
    pattern = project_dir / "refs" / entity_id / "states" if asset_kind == "character" else project_dir / "plates"
    warnings: list[dict] = []
    for meta_path in sorted(pattern.glob("**/*.png.meta.json")) if pattern.exists() else []:
        try:
            meta = json.loads(meta_path.read_text())
        except (OSError, ValueError):
            continue
        if meta.get("entity_id") != entity_id:
            continue
        if meta.get("canonical_parent_sha256") == current_hash:
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
    """Revalidate restored/current state metadata against canonical bytes."""
    meta = artifacts.read_asset_meta(state_path)
    if not meta:
        return None
    parent_hash = _sha256(parent_path)
    if meta.get("canonical_parent_sha256") != parent_hash:
        meta["lineage_status"] = LineageStatus.STALE
        meta["lineage_warning"] = {
            "code": "state_asset_regeneration_required",
            "entity_id": meta.get("entity_id"),
            "state_id": meta.get("state_id"),
            "expected_parent_sha256": meta.get("canonical_parent_sha256"),
            "current_parent_sha256": parent_hash,
        }
        artifacts.write_asset_meta(state_path, meta)
    elif meta.get("lineage_mode") == LineageMode.UNCONDITIONED:
        meta["lineage_status"] = LineageStatus.UNVERIFIED
        meta.pop("lineage_warning", None)
        artifacts.write_asset_meta(state_path, meta)
    return meta


__all__ = [
    "LineageMode", "LineageStatus", "STATE_ASSET_SPEC_VERSION",
    "StateAssetGenerationSpec", "build_character_state_spec",
    "build_location_state_spec", "mark_dependent_states_stale",
    "revalidate_state_asset_lineage",
]
