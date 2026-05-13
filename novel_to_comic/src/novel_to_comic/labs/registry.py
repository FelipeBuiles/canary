"""Curated registry of labs image models loaded from labs_models.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).with_name("labs_models.yaml")


@dataclass(frozen=True)
class LabsModelEntry:
    id: str
    label: str
    provider: str
    endpoint: str
    tier: str = "balanced"
    multi_ref: bool = False
    max_refs: int = 0
    style_refs: bool = False
    approx_cost: float | None = None
    notes: str | None = None
    enabled: bool = True
    params: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        """Serialisation safe to send to the frontend."""
        return {
            "id": self.id,
            "label": self.label,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "tier": self.tier,
            "multi_ref": self.multi_ref,
            "max_refs": self.max_refs,
            "style_refs": self.style_refs,
            "approx_cost": self.approx_cost,
            "notes": self.notes,
        }


def _coerce(entry: dict[str, Any]) -> LabsModelEntry:
    try:
        return LabsModelEntry(
            id=str(entry["id"]),
            label=str(entry.get("label") or entry["id"]),
            provider=str(entry["provider"]),
            endpoint=str(entry["endpoint"]),
            tier=str(entry.get("tier") or "balanced"),
            multi_ref=bool(entry.get("multi_ref", False)),
            max_refs=int(entry.get("max_refs") or 0),
            style_refs=bool(entry.get("style_refs", False)),
            approx_cost=(float(entry["approx_cost"]) if entry.get("approx_cost") is not None else None),
            notes=(str(entry["notes"]) if entry.get("notes") else None),
            enabled=bool(entry.get("enabled", True)),
            params=dict(entry.get("params") or {}),
        )
    except KeyError as exc:
        raise ValueError(f"labs_models.yaml entry missing required field: {exc}") from exc


@lru_cache(maxsize=1)
def load_registry(path: Path | None = None) -> list[LabsModelEntry]:
    target = path or REGISTRY_PATH
    raw = yaml.safe_load(target.read_text()) or {}
    entries = [_coerce(e) for e in (raw.get("models") or [])]
    seen: set[str] = set()
    for e in entries:
        if e.id in seen:
            raise ValueError(f"Duplicate labs model id: {e.id}")
        seen.add(e.id)
    return entries


def get_entry(model_id: str) -> LabsModelEntry:
    for e in load_registry():
        if e.id == model_id:
            return e
    raise KeyError(f"Unknown labs model id: {model_id}")
