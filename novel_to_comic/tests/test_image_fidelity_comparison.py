"""Offline image/report regression tests; none calls an image provider."""
import hashlib
import importlib.util
import json
from pathlib import Path
import socket

from PIL import Image
import pytest

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "compare_image_fidelity.py"
_spec = importlib.util.spec_from_file_location("compare_image_fidelity", _SCRIPT)
assert _spec and _spec.loader
compare = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare)


def png(path, *, mode="RGBA", size=(40, 30), **save_kwargs):
    image = Image.new(mode, size)
    if mode == "RGBA":
        image.putdata([(x * 5, y * 7, (x + y) * 3, (x * 11) % 256)
                       for y in range(size[1]) for x in range(size[0])])
    image.save(path, format="PNG", **save_kwargs)
    return path


def test_native_crops_preserve_pixels_alpha_and_sources_without_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("The comparison tool must not access the network")
    monkeypatch.setattr(socket, "socket", forbidden)
    source = png(tmp_path / "source.png")
    original_bytes = source.read_bytes()
    report = compare.build_comparison([("source", source)], [("detail", (.25, .2, .5, .4))], tmp_path / "report")
    manifest = json.loads(report.with_name("manifest.json").read_text())
    case = manifest["cases"][0]
    assert source.read_bytes() == original_bytes
    assert case["source_sha256"] == hashlib.sha256(original_bytes).hexdigest()
    assert case["width"] == 40 and case["height"] == 30
    crop_info = case["crops"][0]
    assert crop_info["resampled"] is False and case["preview_resampled"] is True
    with Image.open(source) as original, Image.open(report.parent / crop_info["file"]) as crop:
        expected = original.crop(crop_info["pixel_ltrb"])
        assert crop.mode == expected.mode and crop.size == expected.size
        assert crop.tobytes() == expected.tobytes()
    assert manifest["automatic_quality_verdict"] is None


def test_report_escapes_labels_and_does_not_use_them_as_paths(tmp_path):
    source = png(tmp_path / "source.png")
    label = '<script>alert("x")</script>'
    report = compare.build_comparison([(label, source)], [("../../<unsafe>", (0, 0, 1, 1))], tmp_path / "report")
    text = report.read_text()
    assert "<script>" not in text and "&lt;script&gt;" in text
    assert (report.parent / "case-0-region-0.png").is_file()


def test_original_orientation_is_not_reapplied_to_crops(tmp_path):
    exif = Image.Exif()
    exif[274] = 6
    source = png(tmp_path / "oriented.png", exif=exif, icc_profile=b"test-profile")
    report = compare.build_comparison([("a", source)], [("detail", (0, 0, .5, .5))], tmp_path / "report")
    case = json.loads(report.with_name("manifest.json").read_text())["cases"][0]
    assert case["exif_orientation"] == 6
    with Image.open(report.parent / case["crops"][0]["file"]) as crop:
        assert crop.getexif().get(274) is None
        assert crop.info["icc_profile"] == b"test-profile"


@pytest.mark.parametrize("raw", [
    "r=nan,0,.5,.5", "r=0,inf,.5,.5", "r=-.1,0,.5,.5", "r=0,0,0,.5",
    "r=.9,0,.2,.5", "r=0,.9,.5,.2", "r=0,0,.5", "r=0,0,.5,.5,1", "r=no,0,.5,.5",
])
def test_invalid_regions_fail(raw):
    with pytest.raises(ValueError):
        compare.region_value(raw)


def test_exclusive_output_and_request_label_checks(tmp_path):
    source = png(tmp_path / "a.png")
    output = tmp_path / "existing"
    output.mkdir()
    sentinel = output / "index.html"
    sentinel.write_text("existing report")
    with pytest.raises(ValueError, match="already exists"):
        compare.build_comparison([("a", source)], [("r", (0, 0, 1, 1))], output)
    assert sentinel.read_text() == "existing report"
    with pytest.raises(ValueError, match="match an image"):
        compare.build_comparison([("a", source)], [("r", (0, 0, 1, 1))], tmp_path / "new", {"b": source})
    assert not (tmp_path / "new").exists()


@pytest.mark.parametrize("wire,parents,refs,operation,total", [
    (True, False, 0, "generation", 0),
    (True, False, 2, "reference_conditioned_generation", 2),
    (True, True, 2, "edit", 2),
    (False, False, 0, "generation", 0),
    (False, False, 2, "reference_conditioned_generation", 2),
    (False, True, 2, "edit", 3),
])
def test_metadata_distinguishes_reference_generation_from_true_edit(tmp_path, wire, parents, refs, operation, total):
    value = {"references": [{"content_sha256": str(i) * 64} for i in range(refs)]}
    if wire:
        value.update(discriminator="canary.provider-wire/3", provider_key="openai",
                     edit_parent_indices=[0] if parents else [], controls=[["quality", "high"]],
                     prompt_parts=["Private story prose"], configured_provider_model="gpt-image-2.5-sunburst")
    else:
        value.update(artifact_kind="complete_page", profile_id="frozen-profile", provider="openai",
                     prompt="Private story prose", correction={"parent_render_image_sha256": "a" * 64} if parents else None)
    request = tmp_path / "request.json"
    request.write_text(json.dumps(value))
    original = request.read_bytes()
    summary = compare.request_summary(request)
    assert summary["logical_operation"] == operation
    assert summary["image_input_count"] == total
    assert summary["derived_canary_gateway_endpoint"].endswith("edits" if total else "generations")
    assert "Private story prose" not in json.dumps(summary)
    assert request.read_bytes() == original
    assert "not validated" in summary["evidence"]
    assert summary["declared_quality"] == ("high" if wire else None)


def test_codex_does_not_claim_a_known_http_endpoint(tmp_path):
    request = tmp_path / "request.json"
    request.write_text(json.dumps({"references": [], "discriminator": "canary.provider-wire/3",
        "provider_key": "codex-dev", "edit_parent_indices": [], "controls": [], "prompt_parts": ["p"]}))
    assert compare.request_summary(request)["derived_canary_gateway_endpoint"] is None


def test_malformed_metadata_and_bounded_reads(tmp_path):
    path = tmp_path / "input.json"
    path.write_text('{"references": [], "artifact_kind": "unknown"}')
    with pytest.raises(ValueError, match="Expected a Canary"):
        compare.request_summary(path)
    with pytest.raises(ValueError, match="byte limit"):
        compare.read_bounded(path, 4)


def test_cmyk_is_rejected_before_report_creation(tmp_path):
    source = tmp_path / "cmyk.jpg"
    Image.new("CMYK", (20, 20)).save(source)
    with pytest.raises(ValueError, match="CMYK"):
        compare.build_comparison([("a", source)], [("r", (0, 0, 1, 1))], tmp_path / "report")
    assert not (tmp_path / "report").exists()
