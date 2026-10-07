"""Bounded shared-authority concurrency checks, without providers/browsers."""

import threading

from novel_to_comic.lettering.service import LetteringConflict, preset_style, save_style
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.workspace import create_part_workspace


def test_two_part_style_edits_accept_only_one_expected_revision(tmp_path):
    targets = [
        TargetArtifacts(create_part_workspace(tmp_path, f"part_{i:04d}"))
        for i in (1, 2)
    ]
    style = preset_style("literary")
    targets[0].write_lettering_style(style)
    barrier = threading.Barrier(2)
    results = []

    def edit(target):
        barrier.wait(timeout=2)
        try:
            results.append(save_style(target, style, expected_revision=1))
        except LetteringConflict:
            results.append("conflict")

    workers = [
        threading.Thread(target=edit, args=(target,), daemon=True) for target in targets
    ]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(timeout=3)
    assert not any(worker.is_alive() for worker in workers), (
        "shared artifact commit deadlocked"
    )
    assert results.count("conflict") == 1
    assert targets[0].read_lettering_style().revision == 2
    assert targets[1].read_lettering_style().revision == 2


def test_style_change_invalidates_all_parts_finish(tmp_path):
    targets = [
        TargetArtifacts(create_part_workspace(tmp_path, f"part_{i:04d}"))
        for i in (1, 2)
    ]
    for target in targets:
        output = target.project_dir / "finish/preflight.json"
        output.parent.mkdir()
        output.write_text("old")
    targets[0].write_lettering_style(preset_style("literary"))
    assert all(not (target.project_dir / "finish").exists() for target in targets)
