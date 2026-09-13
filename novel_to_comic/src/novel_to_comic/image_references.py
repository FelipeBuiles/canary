"""Immutable reference authority shared by Style and Cast asset requests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal

from novel_to_comic.image_models import ImageRoute

RefRole = Literal["subject", "prop", "style", "location_plate"]

_SELECTION_ORDER: dict[str, int] = {
    "subject": 0,
    "prop": 1,
    "style": 2,
    "location_plate": 3,
}


class AuthorityScope(str, Enum):
    FULL_APPEARANCE = "full_appearance"
    IDENTITY_ONLY = "identity_only"
    CONTEXTUAL = "contextual"


class DropReason(str, Enum):
    MISSING = "missing"
    UNREADABLE = "unreadable"
    DUPLICATE_ENTITY = "duplicate_entity"
    PROVIDER_CAP = "provider_cap"
    UNSUPPORTED_ROLE = "unsupported_role"
    STATE_CONFLICT = "state_conflict"
    STALE_LINEAGE = "stale_lineage"
    UNVERIFIED_LINEAGE = "unverified_lineage"
    LOWER_PRIORITY = "lower_priority"


class ReferenceMaterializationError(ValueError):
    """A selected reference could not be read safely."""


@dataclass(frozen=True, slots=True)
class SemanticCandidate:
    path: Path
    role: RefRole
    entity_id: str | None = None
    appearance_state_id: str | None = None
    is_state_ref: bool = False
    canonical_equivalent: bool = False
    critical: bool = False
    label: str | None = None


@dataclass(frozen=True, slots=True)
class ReferenceAsset:
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
    purpose: Literal["authority", "instruction_context"] = "authority"


@dataclass(frozen=True, slots=True)
class DroppedReference:
    candidate: SemanticCandidate | ReferenceAsset
    reason: DropReason
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ReferencePlan:
    expected_route: ImageRoute
    selected: tuple[ReferenceAsset, ...]
    dropped: tuple[DroppedReference, ...]
    selection_fingerprint: str
    warnings: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ref_count(self) -> int:
        return len(self.selected)

    def to_ref_images(self) -> list:
        from novel_to_comic.ai.providers.base import RefImage

        return [
            RefImage(path=asset.path, role=asset.role, label=asset.label)
            for asset in self.selected
        ]


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def selection_fingerprint_hex(selected: Iterable[ReferenceAsset]) -> str:
    projection = [
        {
            "role": asset.role,
            **({"purpose": asset.purpose} if asset.purpose != "authority" else {}),
            "entity_id": asset.entity_id,
            "appearance_state_id": asset.appearance_state_id,
            "authority_scope": asset.authority_scope.value,
            "preserve_facets": list(asset.preserve_facets),
            "ignore_facets": list(asset.ignore_facets),
            "content_sha256": asset.content_sha256,
        }
        for asset in selected
    ]
    return hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
