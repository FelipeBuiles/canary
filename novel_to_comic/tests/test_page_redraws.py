"""Drawn pages whose plan, Story Bible entries or Cast references changed after drawing."""

from __future__ import annotations

import hashlib
import io
from pathlib import Path
from types import SimpleNamespace

from PIL import Image

from novel_to_comic.models.draw import PageReference
from novel_to_comic.models.page import ApprovedVisualReference
from novel_to_comic.page_drawing import ApprovedReferenceFile
from novel_to_comic.page_redraws import pages_needing_redraw, redraw_reasons
from novel_to_comic.reference_sheets import pack_page_references


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reference(ref_id: str, entity_id: str | None, data: bytes, label: str = "", order: int = 1,
               anchor: str = "anchor") -> PageReference:
    return PageReference(id=ref_id if entity_id else "selected-style-proof", order=order, media_type="image/png",
                         content_sha256=_digest(data), visual_anchor=anchor, entity_id=entity_id, label=label)


class _Target:
    """The five reads ``page_redraws`` makes, for drawn pages 1 and 2 and undrawn page 3."""

    def __init__(self, references: dict[int, list], plan_changed: frozenset[int] = frozenset(),
                 written: dict[int, list] | None = None):
        self.references = references
        self.plan_changed = plan_changed
        self.written = written or {}

    def active_render_revision(self, page_number):
        return 1 if page_number in self.references else None

    def read_provenance(self, page_number, revision):
        render = SimpleNamespace(page_number=page_number,
                                 is_stale_for=lambda _page: page_number in self.plan_changed)
        return SimpleNamespace(render=render)

    def read_page(self, page_number):
        return SimpleNamespace(page_number=page_number)

    def producing_request(self, render):
        return SimpleNamespace(references=tuple(self.references[render.page_number]),
                               written_identities=tuple(self.written.get(render.page_number, ())))

    def read_plan(self):
        return SimpleNamespace(pages=[SimpleNamespace(page_number=n) for n in (1, 2, 3)])


def _files(tmp_path: Path, **contents: bytes) -> dict[str, ApprovedReferenceFile]:
    files = {}
    for ref_id, data in contents.items():
        path = tmp_path / f"{ref_id}.png"
        path.write_bytes(data)
        files[ref_id] = ApprovedReferenceFile(reference_id=ref_id, path=path, media_type="image/png")
    return files


def _inventory(*entries: tuple[str, str] | tuple[str, str, str]) -> dict:
    """``(id, label[, anchor])`` for each current Story Bible entry."""
    return {entry[0]: SimpleNamespace(id=entry[0], label=entry[1], visual_anchor=entry[2] if len(entry) > 2 else "anchor",
                                      continuity_guard="") for entry in entries}


def _change(ref_id: str, label: str, *reasons: str) -> dict:
    return {"reference_id": ref_id, "entity_id": ref_id, "appearance_state_id": None, "label": label,
            "reasons": list(reasons)}


def test_only_pages_drawn_from_a_changed_reference_need_redrawing(tmp_path: Path):
    """Regression for the reference-drift gap: a corrected Cast sheet left pages
    drawn from the old sheet looking current."""
    target = _Target({
        1: [_reference("style", None, b"proof"), _reference("carl", "carl", b"old jacket", "Carl", order=2)],
        2: [_reference("donut", "donut", b"cat")],
    })
    files = _files(tmp_path, carl=b"new jacket", donut=b"cat")
    inventory = _inventory(("carl", "Carl"), ("donut", "Donut"))

    assert pages_needing_redraw(target, files, inventory) == {1: {
        "plan_changed": False, "changed_references": [_change("carl", "Carl", "image")],
    }}
    assert redraw_reasons(target, 2, files, inventory) is None
    assert redraw_reasons(target, 3, files, inventory) is None  # Undrawn pages are drawn, not redrawn.


def test_a_re_planned_page_and_a_removed_entry_both_need_redrawing(tmp_path: Path):
    target = _Target({1: [_reference("carl", "carl", b"sheet")], 2: [_reference("gone", "gone", b"x", "Gone")]},
                     plan_changed=frozenset({1}))
    files = _files(tmp_path, carl=b"sheet")
    inventory = _inventory(("carl", "Carl"))

    assert redraw_reasons(target, 1, files, inventory) == {"plan_changed": True, "changed_references": []}
    assert redraw_reasons(target, 2, files, inventory)["changed_references"] == [_change("gone", "Gone", "removed")]


def test_story_bible_wording_changes_need_redrawing_even_without_a_new_image(tmp_path: Path):
    """Descriptions and written-only identities are part of what a page was drawn from."""
    visitor = ApprovedVisualReference(id="visitor", entity_id="visitor", kind="character", requires_image=False,
                                      visual_anchor="long white hair", label="Visitor")
    target = _Target({1: [_reference("key", "key", b"key", "Key", anchor="small brass key")], 2: []},
                     written={2: [visitor]})
    files = _files(tmp_path, key=b"key")
    inventory = _inventory(("key", "Key", "large iron key"), ("visitor", "Visitor", "short white hair"))

    assert pages_needing_redraw(target, files, inventory) == {
        1: {"plan_changed": False, "changed_references": [_change("key", "Key", "description")]},
        2: {"plan_changed": False, "changed_references": [_change("visitor", "Visitor", "description")]},
    }


def test_the_style_proof_never_marks_a_page_out_of_date(tmp_path: Path):
    target = _Target({1: [_reference("selected-style-proof", None, b"old proof")]})
    assert pages_needing_redraw(target, _files(tmp_path), _inventory()) == {}


def _png(color: str) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_references_packed_into_a_sheet_are_compared_one_by_one(tmp_path: Path):
    """Regression: a page over its model's image limit sends a packed sheet whose
    own id is never a Cast file, so every such page looked out of date."""
    carl, donut = _png("red"), _png("blue")
    members = (_reference("carl", "carl", carl, "Carl", order=1), _reference("donut", "donut", donut, "Donut", order=2))
    sheets, _payloads, _bindings = pack_page_references(members, (carl, donut), slots=1)
    assert sheets[0].id.startswith("reference-sheet-")
    target = _Target({1: list(sheets)})
    inventory = _inventory(("carl", "Carl"), ("donut", "Donut"))

    assert pages_needing_redraw(target, _files(tmp_path, carl=carl, donut=donut), inventory) == {}
    reasons = redraw_reasons(target, 1, _files(tmp_path, carl=carl, donut=_png("green")), inventory)
    assert reasons["changed_references"] == [_change("donut", "Donut", "image")]
