"""Which drawn pages no longer match their inputs, and why.

A page's active art goes out of date in two ways: its plan changed after it was
drawn (a new ``ComicPage`` revision), or something it was drawn from changed in
the Story Bible or Cast. Each drawing froze its references and written
identities; they are compared with what Draw would send now: the reference
bytes, the visual anchor and continuity guard, and whether the entry still
exists. This is the only staleness check for drawn pages. Nothing here spends
or regenerates; the author chooses what to redraw, and old art stays in the
page's history.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from novel_to_comic.reference_sheets import reference_display_members
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts


_DIGESTS: dict[tuple[str, int, int], str] = {}


class _Digests:
    """Current reference file hashes, reused while a file is unchanged on disk.

    Pages are polled while drawing; a file is rehashed only when its size or
    modification time changes.
    """

    def __call__(self, path: Path) -> str | None:
        try:
            stat = path.stat()
            key = (str(path), stat.st_mtime_ns, stat.st_size)
            if key not in _DIGESTS:
                if len(_DIGESTS) > 4096:
                    _DIGESTS.clear()
                _DIGESTS[key] = hashlib.sha256(path.read_bytes()).hexdigest()
            return _DIGESTS[key]
        except OSError:
            return None


def redraw_reasons(target: TargetArtifacts, page_number: int, reference_files, inventory,
                   digests=None) -> dict | None:
    """Why the page's active art is out of date, or None when it is current.

    ``reference_files`` is ``approved_reference_files(project_dir)`` and
    ``inventory`` maps reference ids to ``approved_visual_inventory`` entries.
    Each change lists its reasons: ``image``, ``description``, ``continuity``
    or ``removed``.
    """
    revision = target.active_render_revision(page_number)
    if revision is None:
        return None
    digests = digests or _Digests()
    try:
        render = target.read_provenance(page_number, revision).render
        plan_changed = render.is_stale_for(target.read_page(page_number))
        request = target.producing_request(render)
    except (ArtifactMissing, ArtifactInvalid, ValueError):
        return None
    # A page over its model's image limit sends lossless sheets that pack
    # several references; each member keeps its own id and source hash.
    frozen = [member for reference in request.references for member in reference_display_members(reference)]
    frozen += [identity.model_dump(mode="json") for identity in request.written_identities]
    changed = []
    for member in frozen:
        if member["entity_id"] is None:
            continue  # The Style proof is fixed once a part is adapted.
        current = inventory.get(member["id"])
        if current is None:
            reasons = ["removed"]
        else:
            source = reference_files.get(member["id"])
            image_changed = "content_sha256" in member and (
                source is None or digests(source.path) != member["content_sha256"])
            reasons = [reason for reason, differs in (
                ("image", image_changed),
                ("description", current.visual_anchor != member["visual_anchor"]),
                ("continuity", (current.continuity_guard or "") != (member.get("continuity_guard") or "")),
            ) if differs]
        if reasons:
            changed.append({
                "reference_id": member["id"], "entity_id": member["entity_id"],
                "appearance_state_id": member.get("appearance_state_id"),
                "label": current.label if current is not None else (member.get("label") or member["entity_id"]),
                "reasons": reasons,
            })
    if not plan_changed and not changed:
        return None
    return {"plan_changed": plan_changed, "changed_references": changed}


def pages_needing_redraw(target: TargetArtifacts, reference_files, inventory) -> dict[int, dict]:
    digests = _Digests()
    out = {}
    for selected in target.read_plan().pages:
        reasons = redraw_reasons(target, selected.page_number, reference_files, inventory, digests)
        if reasons is not None:
            out[selected.page_number] = reasons
    return out
