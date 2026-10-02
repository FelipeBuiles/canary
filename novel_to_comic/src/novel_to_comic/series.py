"""Series operations: creating, appending, splitting, replacing and deleting parts.

Parts are appended in reading order and freeze as work builds on them. A
part's text can change only while its Adapt has not started and no later part
has started extraction: later parts' extraction builds on the entities a part
introduced, and adapted text is the authority for drawn pages. Replacing or
deleting an extracted part removes exactly its recorded Story Bible additions.
"""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.artifact_lock import production_lock
from novel_to_comic.models.parts import PartManifest, PartRecord, text_sha256
from novel_to_comic.state import StageStatus, create_initial_state, load_series_state, load_state, save_state
from novel_to_comic.target_artifacts import ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import (
    FIRST_PART_ID,
    PART_MARKER,
    create_part_workspace,
    part_id,
    part_workspace,
    series_root,
)

#: Directories each layer starts with; stages create the rest on demand.
SERIES_DIRECTORIES = ("input", "source", "samples", "refs", "plates")
PART_DIRECTORIES = ("source", "brief", "adapt", "plan", "draw", "finish", "exports", "cover")
EXTRACTION_DELTA = "extraction_delta.json"


class PartEditRejected(ValueError):
    """A part's text can no longer change; the message says why."""


def default_part_title(ordinal: int) -> str:
    return f"Part {ordinal}"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean_title(title: str | None, ordinal: int) -> str:
    return (title or default_part_title(ordinal)).strip()[:200] or default_part_title(ordinal)


def _record(ordinal: int, text: str, *, title: str | None, origin: str) -> PartRecord:
    if not text.strip():
        raise PartEditRejected("A part needs some text.")
    return PartRecord(
        id=part_id(ordinal),
        ordinal=ordinal,
        title=_clean_title(title, ordinal),
        text_sha256=text_sha256(text),
        characters=len(text),
        created_at=_now(),
        origin=origin,
    )


def _new_workspace(root: Path, identifier: str, project_name: str) -> Path:
    workspace = create_part_workspace(root, identifier)
    for name in PART_DIRECTORIES:
        (workspace / name).mkdir(exist_ok=True)
    text_path = TargetArtifacts(root).part_text_path(identifier)
    save_state(create_initial_state(project_name, str(text_path)), workspace)
    return workspace


def initialize_series(
    root: Path,
    *,
    project_name: str,
    novel_path: Path,
    text: str,
    origin: str = "",
    title: str | None = None,
) -> Path:
    """Create a new project as a one-part series and return part 1's workspace.

    ``root`` must already exist. The part text is the exact text Extract will
    read, so it is stored and hashed once here.
    """

    if not text:
        raise ValueError("source text cannot be empty")
    for name in SERIES_DIRECTORIES:
        (root / name).mkdir(exist_ok=True)
    save_state(create_initial_state(project_name, str(novel_path)), root)
    workspace = create_part_workspace(root, FIRST_PART_ID)
    for name in PART_DIRECTORIES:
        (workspace / name).mkdir(exist_ok=True)
    save_state(create_initial_state(project_name, str(novel_path)), workspace)
    target = TargetArtifacts(workspace)
    target.write_part_text(FIRST_PART_ID, text)
    target.write_part_manifest(PartManifest(parts=(_record(1, text, title=title, origin=origin),)))
    return workspace


def edit_blocker(root: Path, identifier: str) -> str | None:
    """Why a part's text can no longer change, or ``None`` when it can."""

    root = series_root(root)
    manifest = TargetArtifacts(root).read_part_manifest()
    record = manifest.get(identifier)
    workspace = part_workspace(root, identifier)
    state = load_state(workspace)
    if state.stages["extract"].status == StageStatus.RUNNING:
        return "This part is being extracted. Wait for it to finish."
    if (state.stages["adapt"].status != StageStatus.PENDING
            or TargetArtifacts(workspace).adaptation_path.exists()):
        return "This part's adaptation has started, so its text is final."
    for later in manifest.parts[record.ordinal:]:
        if load_state(part_workspace(root, later.id)).stages["extract"].status != StageStatus.PENDING:
            return f"{later.title} has been extracted from the story so far, so this part's text is final."
    return None


def _require_editable(root: Path, identifier: str) -> None:
    reason = edit_blocker(root, identifier)
    if reason:
        raise PartEditRejected(reason)


def append_parts(
    root: Path, pieces: list[tuple[str | None, str]], *, origin: str = "",
) -> list[PartRecord]:
    """Append parts in order. ``pieces`` holds ``(title, text)`` pairs."""

    root = series_root(root)
    if not pieces:
        raise PartEditRejected("Add at least one part.")
    with production_lock(root):
        target = TargetArtifacts(root)
        manifest = target.read_part_manifest()
        project_name = load_series_state(root).project_name
        records = list(manifest.parts)
        created = []
        for title, text in pieces:
            record = _record(len(records) + 1, text, title=title, origin=origin)
            target.write_part_text(record.id, text)
            _new_workspace(root, record.id, project_name)
            records.append(record)
            created.append(record)
        target.write_part_manifest(PartManifest(revision=manifest.revision + 1, parts=tuple(records)))
    return created


def rename_part(root: Path, identifier: str, title: str) -> PartRecord:
    root = series_root(root)
    with production_lock(root):
        target = TargetArtifacts(root)
        manifest = target.read_part_manifest()
        record = manifest.get(identifier)
        renamed = record.model_copy(update={"title": _clean_title(title, record.ordinal)})
        parts = tuple(renamed if part.id == identifier else part for part in manifest.parts)
        target.write_part_manifest(PartManifest(revision=manifest.revision + 1, parts=parts))
    return renamed


def _delta_path(workspace: Path) -> Path:
    return workspace / "source" / EXTRACTION_DELTA


def read_extraction_delta(workspace: Path):
    from novel_to_comic.extraction_delta import ExtractionDelta

    path = _delta_path(workspace)
    if not path.exists():
        raise ArtifactMissing("extraction_delta", path)
    return ExtractionDelta.model_validate_json(path.read_text())


def write_extraction_delta(workspace: Path, delta) -> None:
    path = _delta_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(delta.model_dump_json(indent=2))
    temporary.replace(path)


def _withdraw_extraction(root: Path, workspace: Path) -> None:
    """Remove one part's Story Bible additions before its text changes."""

    from novel_to_comic.extraction_delta import remove_delta, removal_conflicts

    state = load_state(workspace)
    extracted = state.stages["extract"].status != StageStatus.PENDING or TargetArtifacts(workspace).source_path.exists()
    if not extracted:
        return
    try:
        delta = read_extraction_delta(workspace)
    except ArtifactMissing:
        delta = None
    bible_path = artifacts.story_bible_path(root)
    if delta is not None and bible_path.exists():
        bible = artifacts.read_story_bible(root)
        conflicts = removal_conflicts(bible, delta)
        if conflicts:
            raise PartEditRejected(
                "These characters you added appear only in this part: "
                + ", ".join(conflicts) + ". Move them to other scenes or remove them first."
            )
        withdrawn = remove_delta(bible, delta)
        withdrawn.revision = bible.revision + 1
        artifacts.write_story_bible(root, withdrawn)
    elif bible_path.exists() and state.stages["extract"].status == StageStatus.COMPLETE:
        raise PartEditRejected(
            "This part's extraction record is missing, so its Story Bible additions can't be removed safely."
        )
    # A part that never finished extracting added nothing to the Story Bible.
    for name in ("source", "brief", ".checkpoints"):
        path = workspace / name
        if path.is_dir():
            shutil.rmtree(path)
    (workspace / "source").mkdir(exist_ok=True)
    (workspace / "brief").mkdir(exist_ok=True)


def next_unit_ordinal(workspace: Path) -> int:
    """The first source-unit ordinal of a part: units continue across parts."""

    from novel_to_comic.workspace import part_ordinal, workspace_part_id

    identifier = workspace_part_id(workspace)
    if identifier is None or part_ordinal(identifier) == 1:
        return 1
    previous = part_workspace(series_root(workspace), part_id(part_ordinal(identifier) - 1))
    try:
        return TargetArtifacts(previous).read_source().units[-1].ordinal + 1
    except ArtifactMissing:
        raise PartEditRejected("Extract the previous part first.") from None


def withdraw_for_reextraction(workspace: Path) -> None:
    """Remove a part's extraction so it can run again (text edit rules apply)."""

    root = series_root(workspace)
    from novel_to_comic.workspace import workspace_part_id

    identifier = workspace_part_id(workspace)
    if identifier is None:
        return
    with production_lock(root):
        _require_editable(root, identifier)
        _withdraw_extraction(root, workspace)


def _reset_part_state(workspace: Path, project_name: str, text_path: Path) -> None:
    save_state(create_initial_state(project_name, str(text_path)), workspace)


def replace_part_text(root: Path, identifier: str, text: str, *, origin: str = "") -> PartRecord:
    """Give a not-yet-adapted part new text; its extraction starts over."""

    root = series_root(root)
    with production_lock(root):
        _require_editable(root, identifier)
        target = TargetArtifacts(root)
        manifest = target.read_part_manifest()
        record = manifest.get(identifier)
        workspace = part_workspace(root, identifier)
        _withdraw_extraction(root, workspace)
        replaced = _record(record.ordinal, text, title=record.title, origin=origin or record.origin)
        target.write_part_text(identifier, text)
        _reset_part_state(workspace, load_series_state(root).project_name, target.part_text_path(identifier))
        parts = tuple(replaced if part.id == identifier else part for part in manifest.parts)
        target.write_part_manifest(PartManifest(revision=manifest.revision + 1, parts=parts))
    return replaced


def _move_part(root: Path, source_id: str, destination_id: str) -> None:
    """Renumber an unstarted part (only its marker, state and text exist)."""

    target = TargetArtifacts(root)
    source = part_workspace(root, source_id)
    destination = part_workspace(root, destination_id)
    if destination.exists():
        raise FileExistsError(f"cannot renumber {source_id}: {destination_id} exists")
    source.rename(destination)
    marker = destination / PART_MARKER
    marker.write_text(json.dumps({"id": destination_id}) + "\n")
    target.part_text_path(source_id).rename(target.part_text_path(destination_id))
    state = load_state(destination)
    state.novel_path = str(target.part_text_path(destination_id))
    save_state(state, destination)


def split_part(
    root: Path, identifier: str, boundaries: list[int], titles: list[str | None] | None = None,
) -> list[PartRecord]:
    """Split an unextracted part at line starts into consecutive parts."""

    from novel_to_comic.chapter_detection import validate_split

    root = series_root(root)
    with production_lock(root):
        _require_editable(root, identifier)
        target = TargetArtifacts(root)
        manifest = target.read_part_manifest()
        record = manifest.get(identifier)
        workspace = part_workspace(root, identifier)
        if load_state(workspace).stages["extract"].status != StageStatus.PENDING:
            raise PartEditRejected("Split a part before extracting it.")
        text = target.read_part_text(identifier)
        try:
            spans = validate_split(text, sorted(boundaries))
        except ValueError as exc:
            raise PartEditRejected(str(exc)) from exc
        if len(spans) < 2:
            raise PartEditRejected("Choose at least one split point.")
        titles = list(titles or [])
        added = len(spans) - 1
        later = list(manifest.parts[record.ordinal:])
        # Make room from the end so no renumbered workspace overwrites another.
        for part in reversed(later):
            _move_part(root, part.id, part_id(part.ordinal + added))
        project_name = load_series_state(root).project_name
        pieces = []
        for index, (start, end) in enumerate(spans):
            ordinal = record.ordinal + index
            title = titles[index] if index < len(titles) and titles[index] else (
                record.title if index == 0 else None)
            piece = _record(ordinal, text[start:end], title=title, origin=record.origin)
            target.write_part_text(piece.id, text[start:end])
            if index > 0:
                _new_workspace(root, piece.id, project_name)
            pieces.append(piece)
        renumbered = [
            part.model_copy(update={"id": part_id(part.ordinal + added), "ordinal": part.ordinal + added})
            for part in later
        ]
        parts = (*manifest.parts[: record.ordinal - 1], *pieces, *renumbered)
        target.write_part_manifest(PartManifest(revision=manifest.revision + 1, parts=parts))
    return pieces


def delete_part(root: Path, identifier: str) -> None:
    """Remove a not-yet-adapted part; later unstarted parts move up."""

    root = series_root(root)
    with production_lock(root):
        target = TargetArtifacts(root)
        manifest = target.read_part_manifest()
        if len(manifest.parts) == 1:
            raise PartEditRejected("A project keeps at least one part.")
        _require_editable(root, identifier)
        record = manifest.get(identifier)
        workspace = part_workspace(root, identifier)
        _withdraw_extraction(root, workspace)
        shutil.rmtree(workspace)
        target.part_text_path(identifier).unlink(missing_ok=True)
        later = list(manifest.parts[record.ordinal:])
        for part in later:
            _move_part(root, part.id, part_id(part.ordinal - 1))
        renumbered = [
            part.model_copy(update={"id": part_id(part.ordinal - 1), "ordinal": part.ordinal - 1})
            for part in later
        ]
        parts = (*manifest.parts[: record.ordinal - 1], *renumbered)
        target.write_part_manifest(PartManifest(revision=manifest.revision + 1, parts=parts))


def cast_inventory_keys(root: Path) -> set[tuple[str, str | None]]:
    """Every entity and appearance state that needs an approved reference."""

    from novel_to_comic.stages.s5_plan import approved_visual_inventory

    try:
        inventory = approved_visual_inventory(series_root(root))
    except Exception:
        return set()
    return {(ref.entity_id, ref.appearance_state_id) for ref in inventory.references}


def reopen_cast(root: Path) -> bool:
    """Return an approved (or awaiting) Cast to pending without deleting anything."""

    from novel_to_comic.state import StageState

    root = series_root(root)
    series = load_series_state(root)
    if series.stages["cast"].status not in {StageStatus.COMPLETE, StageStatus.AWAITING_REVIEW}:
        return False
    series.stages["cast"] = StageState()
    save_state(series, root)
    return True


def reopen_cast_for_new_inventory(root: Path, before: set[tuple[str, str | None]]) -> bool:
    """New entities or states need references before any part can adapt them.

    Cast is a series checkpoint: when the inventory grows (a part's extraction
    or an author's addition), an approved Cast reopens for the new items only.
    """

    added = cast_inventory_keys(root) - before
    return bool(added) and reopen_cast(root)
