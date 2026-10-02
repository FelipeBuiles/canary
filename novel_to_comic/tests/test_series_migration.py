"""Single-book projects move into a one-part series without regeneration."""

from __future__ import annotations

from pathlib import Path

from novel_to_comic.config import Config, save_config
from novel_to_comic.models.parts import text_sha256
from novel_to_comic.series_migration import migrate_to_series, needs_series_migration
from novel_to_comic.source_extraction import SourceSceneAnchor, build_source_document
from novel_to_comic.state import (
    PipelineState,
    StageStatus,
    create_initial_state,
    load_state,
    save_state,
)
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import FIRST_PART_ID, series_root, workspace_part_id

TEXT = "The door opened. A stranger waited outside. Rain fell."


def _legacy_project(root: Path, *, extracted: bool = True) -> Path:
    root.mkdir()
    (root / "input").mkdir()
    (root / "input" / "novel.txt").write_text(TEXT)
    save_config(Config(), root)
    state = create_initial_state("Night Visitor", str(root / "input" / "novel.txt"))
    state.stages["extract"].status = StageStatus.COMPLETE
    state.stages["extract"].cost_usd = 1.5
    state.stages["style"].status = StageStatus.COMPLETE
    state.stages["style"].cost_usd = 2.0
    state.stages["cast"].status = StageStatus.COMPLETE
    state.stages["cast"].cost_usd = 3.0
    state.stages["draw"].status = StageStatus.AWAITING_REVIEW
    state.stages["draw"].cost_usd = 4.0
    state.misc_cost_usd = 0.5
    save_state(state, root)
    files = {
        "story_bible.json": "{}",
        "brief/adaptation_brief.json": "{}",
        "adapt/book.json": "{}",
        "plan/book.json": "{}",
        "draw/pages/page_001/render_001.png": "png",
        "lettering/style.json": "{}",
        "lettering/pages/page_001.json": "{}",
        "refs/char_001/sheet.png": "png",
        "plates/loc_001.png": "png",
        "samples/style_1.png": "png",
        "cover/cover.png": "png",
        "exports/comic.pdf": "pdf",
        ".checkpoints/adapt/work.json": "{}",
        "requests/abc/manifest.json": "{}",
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    if extracted:
        TargetArtifacts(root).write_source(build_source_document(
            TEXT, (SourceSceneAnchor(id="scene_001", title="Door", opening_quote="The door opened."),),
        ))
    return root


def test_page_work_moves_into_part_one_and_look_assets_stay(tmp_path) -> None:
    root = _legacy_project(tmp_path / "book")
    source_before = TargetArtifacts(root).read_source()

    assert needs_series_migration(root)
    assert migrate_to_series(root) is True
    assert migrate_to_series(root) is False
    assert not needs_series_migration(root)

    workspace = root / "parts" / FIRST_PART_ID
    assert workspace_part_id(workspace) == FIRST_PART_ID
    assert series_root(workspace) == root
    for moved in ("brief/adaptation_brief.json", "adapt/book.json", "plan/book.json",
                  "draw/pages/page_001/render_001.png", "lettering/pages/page_001.json",
                  "cover/cover.png", "exports/comic.pdf", ".checkpoints/adapt/work.json"):
        assert (workspace / moved).is_file(), moved
        assert not (root / moved).exists(), moved
    for kept in ("story_bible.json", "lettering/style.json", "refs/char_001/sheet.png",
                 "plates/loc_001.png", "samples/style_1.png", "input/novel.txt",
                 "config.yaml", "requests/abc/manifest.json"):
        assert (root / kept).is_file(), kept
    assert not (workspace / "lettering" / "style.json").exists()

    # The source document is unchanged, so every downstream hash still binds.
    assert TargetArtifacts(workspace).read_source() == source_before
    manifest = TargetArtifacts(root).read_part_manifest()
    assert [part.id for part in manifest.parts] == [FIRST_PART_ID]
    assert manifest.parts[0].title == "Part 1"
    assert manifest.parts[0].text_sha256 == text_sha256(TEXT) == source_before.source_sha256
    assert TargetArtifacts(root).read_part_text(FIRST_PART_ID) == TEXT


def test_state_splits_into_series_and_part_without_double_counting(tmp_path) -> None:
    root = _legacy_project(tmp_path / "book")
    migrate_to_series(root)

    series = load_state(root)
    workspace = root / "parts" / FIRST_PART_ID
    part_file = PipelineState.model_validate_json((workspace / "state.json").read_text())

    assert series.stages["style"].status == StageStatus.COMPLETE
    assert series.stages["cast"].status == StageStatus.COMPLETE
    assert series.stages["extract"].status == StageStatus.PENDING
    assert series.stages["draw"].status == StageStatus.PENDING
    assert part_file.stages["extract"].status == StageStatus.COMPLETE
    assert part_file.stages["draw"].status == StageStatus.AWAITING_REVIEW
    # Each stage's history lives in one file only...
    assert part_file.stages["style"].status == StageStatus.PENDING
    assert series.total_cost_usd == 5.5  # style + cast + misc
    assert part_file.total_cost_usd == 5.5  # extract + draw
    assert part_file.misc_cost_usd == 0
    # ...while a part's loaded view sees the current series decisions.
    assert load_state(workspace).stages["style"].status == StageStatus.COMPLETE


def test_an_unextracted_project_takes_part_text_from_its_upload(tmp_path) -> None:
    root = _legacy_project(tmp_path / "book", extracted=False)

    assert migrate_to_series(root, title="Book One") is True

    manifest = TargetArtifacts(root).read_part_manifest()
    assert manifest.parts[0].title == "Book One"
    assert manifest.parts[0].origin == "novel.txt"
    assert TargetArtifacts(root).read_part_text(FIRST_PART_ID) == TEXT


def test_an_interrupted_move_resumes(tmp_path) -> None:
    root = _legacy_project(tmp_path / "book")
    staging = root / "parts" / f".{FIRST_PART_ID}.migrating"
    staging.mkdir(parents=True)
    (root / "brief").rename(staging / "brief")
    (root / "adapt").rename(staging / "adapt")

    assert migrate_to_series(root) is True

    workspace = root / "parts" / FIRST_PART_ID
    assert (workspace / "brief" / "adaptation_brief.json").is_file()
    assert (workspace / "adapt" / "book.json").is_file()
    assert (workspace / "plan" / "book.json").is_file()
    assert not staging.exists()


def test_a_crash_after_the_rename_finishes_on_rerun(tmp_path) -> None:
    root = _legacy_project(tmp_path / "book")
    migrate_to_series(root)
    # Simulate a crash before the commit point: no manifest yet.
    TargetArtifacts(root).part_manifest_path.unlink()

    assert needs_series_migration(root)
    assert migrate_to_series(root) is True
    assert TargetArtifacts(root).read_part_text(FIRST_PART_ID) == TEXT
    assert load_state(root / "parts" / FIRST_PART_ID).stages["extract"].status == StageStatus.COMPLETE
