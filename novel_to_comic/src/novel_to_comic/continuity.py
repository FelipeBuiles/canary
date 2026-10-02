"""Continuity a part's adaptation inherits from the parts before it.

A later part is adapted after the earlier parts' scripts exist, so its
treatment can continue their arcs instead of re-introducing the cast or
repeating events. The context is compact: the earlier parts' causal spines and
aftermath, and the previous part's closing beats with their exact lettering.

The adapted scripts it was built from are recorded beside the part's
adaptation. Re-adapting an earlier part later changes those scripts, which is
reported as an advisory "earlier part changed" notice; nothing re-runs.
"""

from __future__ import annotations

import json
from pathlib import Path

from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import part_id, part_ordinal, part_workspace, series_root, workspace_part_id

#: Bounded so a long series never crowds out the part's own source.
EARLIER_PARTS = 3
CLOSING_BEATS = 8
RECORD = "continuity.json"


def _earlier_adaptations(workspace: Path) -> list[tuple[str, object]]:
    identifier = workspace_part_id(workspace)
    if identifier is None:
        return []
    root = series_root(workspace)
    found = []
    for number in range(1, part_ordinal(identifier)):
        earlier = part_id(number)
        try:
            found.append((earlier, TargetArtifacts(part_workspace(root, earlier)).read_adaptation()))
        except (ArtifactMissing, ArtifactInvalid):
            continue
    return found


def continuity_context(workspace: Path) -> dict | None:
    """What a part's treatment needs to continue the story, or ``None``."""

    earlier = _earlier_adaptations(workspace)
    if not earlier:
        return None
    previous_id = part_id(part_ordinal(workspace_part_id(workspace)) - 1)
    previous = next((adaptation for pid, adaptation in earlier if pid == previous_id), None)
    return {
        "earlier_parts": [
            {
                "part_id": pid,
                "causal_spine": list(adaptation.treatment.causal_spine),
                "aftermath": list(adaptation.treatment.aftermath),
            }
            for pid, adaptation in earlier[-EARLIER_PARTS:]
        ],
        "previous_part_ending": [
            {"summary": beat.summary, "lettering": [item.text for item in beat.lettering]}
            for beat in (previous.beats[-CLOSING_BEATS:] if previous is not None else ())
        ],
    }


def _sources(workspace: Path) -> dict[str, str]:
    return {pid: adaptation.content_sha256 for pid, adaptation in _earlier_adaptations(workspace)}


def write_continuity_record(workspace: Path) -> None:
    """Record which earlier scripts this part's adaptation continued."""

    path = Path(workspace) / "adapt" / RECORD
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps({"version": 1, "sources": _sources(workspace)}, indent=2))
    temporary.replace(path)


def earlier_part_changed(workspace: Path) -> bool:
    """Whether an earlier part was re-adapted after this part's adaptation."""

    path = Path(workspace) / "adapt" / RECORD
    if not path.exists() or not TargetArtifacts(workspace).adaptation_path.exists():
        return False
    try:
        recorded = json.loads(path.read_text()).get("sources", {})
    except (OSError, ValueError):
        return False
    return recorded != _sources(workspace)
