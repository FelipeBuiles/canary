"""One-time move of a single-book project into a one-part series.

Earlier projects kept page work at the project root. A series keeps it in part
workspaces, so the move relocates those artifacts into ``parts/part_0001``.
Nothing is regenerated, rewritten or rehashed: every relative path stored in
page artifacts is relative to the directory that now becomes the part
workspace, and every Look path is relative to the root, which stays put.

The move is idempotent and crash-safe. Entries are staged in a hidden
directory and renamed into place; the part manifest is written last and is
the commit point. Rerunning after an interruption resumes where it stopped.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path

from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.models.parts import PartManifest, PartRecord, text_sha256
from novel_to_comic.series import default_part_title
from novel_to_comic.state import PipelineState, StageState, load_state, save_state
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import (
    FIRST_PART_ID,
    PART_MARKER,
    PARTS_DIRNAME,
    create_part_workspace,
    part_workspace,
)

logger = logging.getLogger("canary.series_migration")

#: Root entries that hold one book's page work. Look assets, configuration,
#: uploaded originals, non-page request records and job/lock bookkeeping stay
#: at the series root.
PART_LEVEL_ENTRIES = (
    "brief",
    "adapt",
    "plan",
    "draw",
    "finish",
    "exports",
    "cover",
    "story_changes",
    "editorial",
    ".checkpoints",
)
#: The book lettering style is a Style decision; page lettering moves.
SERIES_LETTERING_FILES = frozenset({"style.json"})
SERIES_STAGES = ("style", "cast")
_STAGING_NAME = f".{FIRST_PART_ID}.migrating"


def needs_series_migration(root: Path) -> bool:
    """True for a project root that predates parts."""

    root = Path(root)
    return (
        (root / "state.json").is_file()
        and not (root / PART_MARKER).exists()
        and not TargetArtifacts(root).part_manifest_path.exists()
    )


def _move(source: Path, destination: Path) -> None:
    if not source.exists() and not source.is_symlink():
        return
    if destination.exists():
        raise FileExistsError(f"cannot migrate {source}: {destination} already exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    source.rename(destination)


def _part_text(root: Path, state: PipelineState) -> str:
    """The exact text part 1 was (or will be) extracted from."""

    target = TargetArtifacts(root)
    staged_source = root / PARTS_DIRNAME / _STAGING_NAME / "source" / "source.json"
    final_source = part_workspace(root, FIRST_PART_ID) / "source" / "source.json"
    for candidate in (target.source_path, staged_source, final_source):
        if candidate.is_file():
            # The canonical document already holds the exact extracted text.
            return TargetArtifacts(candidate.parent.parent).read_source().text
    from novel_to_comic.input_limits import read_source

    novel_path = Path(state.novel_path)
    if not novel_path.is_absolute():
        novel_path = root / novel_path
    text = read_source(novel_path)
    if not isinstance(text, str) or not text:
        raise ValueError(f"project source text is unreadable: {novel_path}")
    return text


def _recompute_total(state: PipelineState) -> None:
    state.total_cost_usd = sum(stage.cost_usd for stage in state.stages.values()) + state.misc_cost_usd


def _split_state(root: Path, workspace: Path) -> None:
    """Give the part its own state; the root keeps only series stages.

    Each stage's history lives in exactly one file, so series and part costs
    can be summed without double counting.
    """

    state = load_state(root)
    if not (workspace / "state.json").exists():
        part_state = state.model_copy(deep=True)
        for name in SERIES_STAGES:
            part_state.stages[name] = StageState()
        part_state.misc_cost_usd = 0.0
        _recompute_total(part_state)
        save_state(part_state, workspace)
    if any(stage != StageState() for name, stage in state.stages.items()
           if name not in SERIES_STAGES):
        for name in list(state.stages):
            if name not in SERIES_STAGES:
                state.stages[name] = StageState()
        _recompute_total(state)
        save_state(state, root)


def migrate_to_series(root: Path, *, title: str | None = None) -> bool:
    """Move a single-book project into ``parts/part_0001``.

    Returns ``True`` when this call completed a migration and ``False`` when
    the project already is a series.
    """

    root = Path(root)
    if not needs_series_migration(root):
        return False
    with production_lock(root):
        if not needs_series_migration(root):
            return False
        state = load_state(root)
        text = _part_text(root, state)
        final = part_workspace(root, FIRST_PART_ID)
        staging = root / PARTS_DIRNAME / _STAGING_NAME
        if not final.exists():
            staging.mkdir(parents=True, exist_ok=True)
            for name in PART_LEVEL_ENTRIES:
                _move(root / name, staging / name)
            _move(root / "source" / "source.json", staging / "source" / "source.json")
            lettering = root / "lettering"
            if lettering.is_dir():
                for child in sorted(lettering.iterdir()):
                    if child.name not in SERIES_LETTERING_FILES:
                        _move(child, staging / "lettering" / child.name)
            staging.rename(final)
        workspace = create_part_workspace(root, FIRST_PART_ID)
        _split_state(root, workspace)

        target = TargetArtifacts(workspace)
        target.write_part_text(FIRST_PART_ID, text)
        record = PartRecord(
            id=FIRST_PART_ID,
            ordinal=1,
            title=(title or default_part_title(1)).strip()[:200] or default_part_title(1),
            text_sha256=text_sha256(text),
            characters=len(text),
            created_at=(state.created_at or datetime.now(UTC)).isoformat(),
            origin=Path(state.novel_path).name,
        )
        # Commit point: the manifest marks the project as a series.
        target.write_part_manifest(PartManifest(parts=(record,)))
    logger.info("Migrated project %s into a one-part series", root.name)
    return True
