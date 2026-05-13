from pathlib import Path

from novel_to_comic.labs import storage


def test_labs_storage_keeps_prompt_variants_separate(tmp_path: Path):
    run_id = "run_1"
    manifest = {
        "model_ids": ["model-a"],
        "prompt_compare_mode": True,
        "panels": [
            {
                "idx": 1,
                "label": "Panel 1",
                "prompt": "Prompt A",
                "prompt_variant_b": "Prompt B",
            }
        ],
    }
    storage.write_manifest(tmp_path, run_id, manifest)

    storage.write_cell(
        tmp_path,
        run_id,
        1,
        "model-a",
        variant="A",
        image_bytes=b"a",
        meta={"status": "ok", "cost_usd": 0.01},
    )
    storage.write_cell(
        tmp_path,
        run_id,
        1,
        "model-a",
        variant="B",
        image_bytes=b"b",
        meta={"status": "ok", "cost_usd": 0.02},
    )

    assert storage.cell_image_path(tmp_path, run_id, 1, "model-a", "A").read_bytes() == b"a"
    assert storage.cell_image_path(tmp_path, run_id, 1, "model-a", "B").read_bytes() == b"b"
    assert storage.read_cell_meta(tmp_path, run_id, 1, "model-a", "A")["variant"] == "A"
    assert storage.read_cell_meta(tmp_path, run_id, 1, "model-a", "B")["variant"] == "B"
    assert storage.sum_run_cost(tmp_path, run_id) == 0.03


def test_labs_storage_normal_mode_uses_variant_a(tmp_path: Path):
    run_id = "run_1"
    storage.write_manifest(
        tmp_path,
        run_id,
        {
            "model_ids": ["model-a"],
            "prompt_compare_mode": False,
            "panels": [{"idx": 1, "label": "Panel 1", "prompt": "Prompt A"}],
        },
    )

    storage.write_cell(
        tmp_path,
        run_id,
        1,
        "model-a",
        image_bytes=None,
        meta={"status": "failed"},
    )

    assert storage.read_cell_meta(tmp_path, run_id, 1, "model-a")["variant"] == "A"
    assert storage.panel_variants({"idx": 1, "prompt": "Prompt A"}, False) == ["A"]
