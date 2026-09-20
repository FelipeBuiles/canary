"""Reference packing preserves pixels and independently addressable authorities."""
import hashlib
import io
import json

import pytest
from PIL import Image

from novel_to_comic.models.draw import PageReference
from novel_to_comic.reference_sheets import pack_page_references


def references(count):
    refs, images = [], []
    for i in range(count):
        output = io.BytesIO()
        Image.new("RGBA", (160 + i, 100 + i), (i, 100, 200, 128 + i)).save(output, format="PNG")
        data = output.getvalue()
        refs.append(PageReference(id=f"ref{i}", order=i + 1, entity_id=f"char{i}",
                                  label=f"Character {i}", media_type="image/png",
                                  content_sha256=hashlib.sha256(data).hexdigest(),
                                  visual_anchor=f"Anchor {i}", continuity_guard=f"Guard {i}"))
        images.append(data)
    return refs, images


@pytest.mark.parametrize("count,slots", [(6, 5), (7, 5), (8, 4), (10, 5)])
def test_sheets_retain_every_pixel_hash_and_authority(count, slots):
    refs, images = references(count)
    packed, data, bindings = pack_page_references(refs, images, slots)
    assert len(packed) == len(data) == slots
    assert set(bindings) == {ref.id for ref in refs}
    for ref, source in zip(refs, images, strict=True):
        binding = bindings[ref.id]
        index = binding["input_order"] - 1
        if "region_pixels" not in binding:
            assert data[index] == source
            continue
        region = binding["region_pixels"]
        image = Image.open(io.BytesIO(data[index]))
        crop = image.crop((region["x"], region["y"], region["x"] + region["width"], region["y"] + region["height"]))
        assert crop.tobytes() == Image.open(io.BytesIO(source)).tobytes()
        members = json.loads(packed[index].visual_anchor)["members"]
        assert any(m["authority"] == ref.model_dump(mode="json") for m in members)
    assert pack_page_references(refs, images, slots) == (packed, data, bindings)


def test_references_that_fit_keep_their_original_identity_and_bytes():
    refs, images = references(4)
    assert pack_page_references(refs, images, 5) == (tuple(refs), tuple(images), {})


def test_overflow_and_invalid_images_fail_instead_of_discarding_an_authority():
    refs, images = references(11)
    with pytest.raises(ValueError, match="capacity"):
        pack_page_references(refs, images, 5)
    with pytest.raises(ValueError, match="one-to-one"):
        pack_page_references(refs, images[:-1], 5)
    refs, images = references(6)
    images[0] = b"not an image"
    refs[0] = refs[0].model_copy(update={"content_sha256": hashlib.sha256(images[0]).hexdigest()})
    with pytest.raises(ValueError, match="Rerun Cast"):
        pack_page_references(refs, images, 5)


def test_display_members_preserve_original_subjects_and_source_hashes():
    from novel_to_comic.reference_sheets import reference_display_members
    refs, images = references(7)
    packed, _, _ = pack_page_references(refs, images, 5)
    members = [member for sheet in packed for member in reference_display_members(sheet)]
    assert [m["id"] for m in members] == [r.id for r in refs]
    assert [m["visual_anchor"] for m in members] == [r.visual_anchor for r in refs]
    images[0] = images[1]
    with pytest.raises(ValueError, match="approved hashes"):
        pack_page_references(refs, images, 5)


def test_pixel_budget_rejects_instead_of_resizing(monkeypatch):
    monkeypatch.setattr("novel_to_comic.reference_sheets.MAX_SHEET_PIXELS", 10)
    refs, images = references(6)
    with pytest.raises(ValueError, match="too large"):
        pack_page_references(refs, images, 5)
