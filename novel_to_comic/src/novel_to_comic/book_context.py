"""What one part knows about the whole book.

A part of a series is usually a stretch of one longer story. Its Brief and
adaptation must know that: which part it is, that it may have no ending of its
own, and, when a fresh book map exists, where it sits among the book's acts and
through-lines. Single-part projects have no book context; their part is the
book.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from novel_to_comic.book_map import book_slice, fresh_book_map
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.workspace import series_root, workspace_part_id


def part_position(workspace: Path) -> dict[str, Any] | None:
    """The part's place in the saved manuscript, or None for one-part projects."""
    identifier = workspace_part_id(Path(workspace))
    if identifier is None:
        return None
    try:
        manifest = TargetArtifacts(series_root(Path(workspace))).read_part_manifest()
    except (ArtifactMissing, ArtifactInvalid):
        return None
    if len(manifest.parts) < 2:
        return None
    record = manifest.get(identifier)
    return {"part": record.ordinal, "of": len(manifest.parts), "title": record.title}


def book_context(workspace: Path) -> dict[str, Any] | None:
    """Position plus the fresh book map's slice for this part, when it has one."""
    position = part_position(workspace)
    if position is None:
        return None
    context: dict[str, Any] = {"position": position}
    book_map = fresh_book_map(workspace)
    identifier = workspace_part_id(Path(workspace))
    if book_map is not None and identifier is not None:
        context["map"] = book_slice(book_map, identifier)
    return context


def book_context_instructions(context: dict[str, Any] | None, *, stage: Literal["brief", "adapt"]) -> str:
    """How a part's Brief or treatment must treat its place in the book."""
    if not context:
        return ""
    position = context["position"]
    number, count = position["part"], position["of"]
    text = f"This source is part {number} of {count} of one book. "
    if number < count:
        text += (
            "The story continues in later parts, so this part has no ending of its own. "
            "Never invent a climax, resolution or closing arc the text does not contain; "
            "its last pages carry the source's own final turn forward into the next part. "
        )
    else:
        text += "It is the last saved part: end where the source ends. "
    if number > 1:
        text += "It opens mid-story; established people and situations need no reintroduction. "
    if "map" in context:
        text += (
            "book_context.map summarizes the whole saved book: its acts, this part's role, "
            "the through-lines active here and the people who matter beyond this part. Use it "
            "to weigh what this part sets up or pays off. It is reference, never source: do "
            "not add events from other parts to this part. "
        )
    if stage == "adapt":
        text += (
            "The approved Brief's themes and motifs are the whole book's direction. Carry "
            "one into this part only where this part's source already supports it; never "
            "add a moment to display a theme or motif the text gives this part no reason for. "
        )
    if stage == "brief":
        text += (
            "Story promises, essential events and character turns describe this part's "
            "stretch of the story; a character turn may be partial. "
        )
        if number == 1 and "map" in context:
            text += (
                "Themes, motifs, tone, point of view and narrator treatment become the whole "
                "series' direction: base themes and motifs on the book's, not only this part's. "
            )
    return text
