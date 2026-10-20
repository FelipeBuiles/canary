"""Read-only display metadata for frozen page requests and renders."""
from __future__ import annotations
from novel_to_comic.target_artifacts import TargetArtifacts, ArtifactMissing
from novel_to_comic.stages.s5_plan import approved_reference_files

def render_correction_summary(
    target: TargetArtifacts, page_number: int, revision: int,
) -> dict:
    """Exact submitted correction behind one render, without prompt bulk.

    Resolves the frozen request that produced the render and projects only
    its correction block (edited instructions, annotation notes, manual
    note). Initial draws carry no correction and return null. Raises
    ArtifactMissing when the render or its frozen request record is absent.
    """
    provenance = target.read_provenance(page_number, revision)
    render = provenance.render
    frozen = None
    for request_revision in target.request_revisions(page_number):
        candidate = target.read_request(page_number, request_revision)
        if candidate.request_sha256 == render.request_sha256:
            frozen = candidate
            break
    if frozen is None:
        raise ArtifactMissing("page_request", target.request_path(page_number, revision))
    correction = frozen.correction
    return {
        "page_number": page_number,
        "render_revision": render.revision,
        "parent_render_revision": render.parent_revision,
        "request_sha256": render.request_sha256,
        "correction": (
            None
            if correction is None
            else {
                "mode": correction.mode,
                "changes": [
                    {
                        "id": change.id,
                        "issue_id": change.issue_id,
                        "instruction": change.instruction,
                        "annotations": [
                            annotation.model_dump(exclude_none=True)
                            for annotation in change.annotations
                        ],
                    }
                    for change in correction.changes
                ],
                "note": correction.note,
            }
        ),
    }


def reference_entries(project_dir, references, style_template: str | None = None) -> list[dict]:
    """Reference display metadata with servable image paths, without spending.

    ``image_path`` is project-relative for the existing generic files route
    (``/api/projects/{project}/files/{image_path}``); it is null when the
    approved bytes are missing so the UI never renders a dead thumbnail.
    ``kind`` groups the display: the selected style proof, or the Story Bible
    entity type. The style proof's anchor is a provider instruction, not a
    description, so it is never shown. Accepts frozen-request dicts and
    compiled-request models alike.
    """
    from pathlib import Path as _Path

    from novel_to_comic.models.draw import STYLE_PROOF_REFERENCE_ID

    def _field(reference, name):
        if isinstance(reference, dict):
            return reference.get(name)
        return getattr(reference, name, None)

    try:
        files = approved_reference_files(project_dir)
    except Exception:
        files = {}
    # Cast references live in the series root, beside every part.
    from novel_to_comic.workspace import series_root

    root = series_root(_Path(project_dir)).resolve()

    def servable(path) -> str | None:
        try:
            candidate = _Path(path).resolve()
        except Exception:
            return None
        return candidate.relative_to(root).as_posix() if candidate.is_relative_to(root) and candidate.is_file() else None

    images: dict[str, str | None] = {reference_id: servable(source.path) for reference_id, source in files.items()}
    if style_template is not None:
        from novel_to_comic.style_reference import find_style_reference

        style_path = find_style_reference(_Path(project_dir), style_template)
        images[STYLE_PROOF_REFERENCE_ID] = servable(style_path) if style_path is not None else None
    from novel_to_comic import artifacts as project_artifacts

    bible = project_artifacts.read_story_bible_safe(project_dir)
    kinds = {} if bible is None else {
        **{item.id: "character" for item in bible.characters},
        **{item.id: "location" for item in bible.locations},
        **{item.id: "prop" for item in bible.props},
    }
    entries = []
    from novel_to_comic.reference_sheets import reference_display_members
    references = [member for reference in references for member in reference_display_members(reference)]
    for reference in references:
        reference_id = _field(reference, "id")
        label = _field(reference, "label") or ""
        entity = _field(reference, "entity_id") or ""
        style = reference_id == STYLE_PROOF_REFERENCE_ID
        entries.append(
            {
                "order": _field(reference, "order"),
                "id": reference_id,
                "entity_id": entity,
                "appearance_state_id": _field(reference, "appearance_state_id"),
                "kind": "style" if style else kinds.get(entity),
                "label": label,
                "display_label": "Selected style" if style else label or entity or reference_id,
                "visual_anchor": None if style else _field(reference, "visual_anchor"),
                "media_type": _field(reference, "media_type"),
                "image_path": images.get(reference_id) if reference_id else None,
            }
        )
    return entries

