"""The one Cast reference a regeneration addresses.

An asset type, a job kind and a payload key name the same thing in three
vocabularies, and persisted jobs carry the ``entity:state`` id. This module is
the only place that maps between them and the only place that builds or splits
that id.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Literal

AssetKind = Literal["character_ref", "location_plate", "prop_ref"]
AssetType = Literal["character", "location", "prop"]

# reference kind, job kind, payload key, telemetry feature for the instruction rewrite.
_VOCABULARY: dict[AssetType, tuple[AssetKind, str, str, str]] = {
    "character": (
        "character_ref", "character_ref_regen", "char_id",
        "cast.character_ref_instruction_rewrite",
    ),
    "location": (
        "location_plate", "location_plate_regen", "loc_id",
        "cast.location_plate_instruction_rewrite",
    ),
    "prop": ("prop_ref", "prop_ref_regen", "prop_id", "cast.prop_ref_instruction_rewrite"),
}
ASSET_TYPES: tuple[AssetType, ...] = tuple(_VOCABULARY)
_BY_JOB_KIND = {entry[1]: asset_type for asset_type, entry in _VOCABULARY.items()}


def scoped_id(entity_id: str, state_id: str | None = None) -> str:
    """``entity:state`` for a state, the bare entity id otherwise."""
    return f"{entity_id}:{state_id}" if state_id else entity_id


def split_scoped_id(value: str) -> tuple[str, str | None]:
    """Inverse of ``scoped_id``; also reads the legacy ``entity/states/state`` spelling."""
    entity_id, _, state_id = value.partition(":")
    if "/states/" in value:
        entity_id, _, state_id = value.partition("/states/")
    return entity_id, state_id or None


@dataclass(frozen=True)
class CastTarget:
    asset_type: AssetType
    entity_id: str
    state_id: str | None = None

    def __post_init__(self) -> None:
        if self.asset_type not in _VOCABULARY:
            raise ValueError(f"Unknown asset_type: {self.asset_type}")
        if self.state_id == "":
            object.__setattr__(self, "state_id", None)
        if self.state_id and self.asset_type == "prop":
            raise ValueError("state_id is not supported for prop assets")

    @classmethod
    def from_job(cls, job_kind: str, job_asset_id: str) -> CastTarget:
        """Rebuild the target a job carries: its kind and its ``entity:state`` id."""
        return cls(_BY_JOB_KIND[job_kind], *split_scoped_id(job_asset_id))

    def with_state(self, state_id: str) -> CastTarget:
        return replace(self, state_id=state_id)

    @property
    def ref_kind(self) -> AssetKind:
        return _VOCABULARY[self.asset_type][0]

    @property
    def job_kind(self) -> str:
        return _VOCABULARY[self.asset_type][1]

    @property
    def payload_key(self) -> str:
        return _VOCABULARY[self.asset_type][2]

    @property
    def feature(self) -> str:
        return _VOCABULARY[self.asset_type][3]

    @property
    def job_asset_id(self) -> str:
        return scoped_id(self.entity_id, self.state_id)

    @property
    def job_identity(self) -> dict[str, str]:
        """The payload that identifies this target's active job."""
        return {self.payload_key: self.job_asset_id}

    @property
    def is_canonical(self) -> bool:
        """A character's main sheet or a location's main plate, never a look or a prop."""
        return self.asset_type != "prop" and self.state_id is None

    @property
    def label(self) -> str:
        """Human-readable job label shown in the generation queue."""
        if self.asset_type == "character":
            base = "Appearance state" if self.state_id else "Character ref"
        elif self.asset_type == "location":
            base = "Location state" if self.state_id else "Location plate"
        else:
            base = "Prop ref"
        subject = f"{self.entity_id} · {self.state_id}" if self.state_id else self.entity_id
        return f"{base} / {subject}"
