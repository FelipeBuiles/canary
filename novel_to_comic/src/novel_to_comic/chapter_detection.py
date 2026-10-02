"""Find chapter headings so a long upload can be grouped into parts.

Detection only proposes boundaries; the author decides how chapters group into
parts. Boundaries always fall at the start of a line, so splitting the text at
them never cuts a sentence, and the pieces concatenate back to the original.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field

_NUMBER_WORDS = (
    "one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|thirteen|"
    "fourteen|fifteen|sixteen|seventeen|eighteen|nineteen|twenty|thirty|forty|fifty"
)
_ROMAN = r"[ivxlcdm]+"
_ORDINAL = rf"(?:\d+|{_ROMAN}|(?:{_NUMBER_WORDS})(?:[- ](?:{_NUMBER_WORDS}))?)"
# A heading is a short line that names a chapter-like division, optionally
# followed by a title ("Chapter 3: The Storm", "BOOK TWO", "Prologue").
_HEADING = re.compile(
    rf"^(?:#{{1,3}}\s*)?(?:(?:chapter|part|book|volume)\s+{_ORDINAL}\b.*"
    r"|(?:prologue|epilogue|interlude|afterword|foreword)\b.*)$",
    re.IGNORECASE,
)
# A bare numeral on its own line ("12", "XII", "12.") is also a common marker.
_BARE_NUMBER = re.compile(rf"^(?:\d{{1,3}}|{_ROMAN})\.?$", re.IGNORECASE)
_MAX_HEADING_CHARS = 80


class DetectedChapter(BaseModel):
    """One proposed division: its heading and exact half-open text span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=1)
    title: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)

    @property
    def characters(self) -> int:
        return self.end_offset - self.start_offset


def _heading_starts(text: str) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if (
            stripped
            and len(stripped) <= _MAX_HEADING_CHARS
            and (_HEADING.match(stripped) or _BARE_NUMBER.match(stripped))
        ):
            starts.append((offset, stripped.lstrip("#").strip()))
        offset += len(line)
    return starts


def detect_chapters(text: str) -> list[DetectedChapter]:
    """Return contiguous chapters covering all of ``text``.

    Text before the first heading (a title page or epigraph) belongs to the
    first chapter, so no characters are ever left out. A text without
    recognizable headings is one chapter.
    """

    if not text:
        return []
    starts = _heading_starts(text)
    # Repeated markers with nothing between them (a table of contents) would
    # create empty chapters; keep only headings that begin real content.
    meaningful: list[tuple[int, str]] = []
    for position, (offset, title) in enumerate(starts):
        following = starts[position + 1][0] if position + 1 < len(starts) else len(text)
        body = text[offset:following].split("\n", 1)
        if len(body) > 1 and len(body[1].strip()) >= 200:
            meaningful.append((offset, title))
    if not meaningful:
        return [DetectedChapter(index=1, title="Full text", start_offset=0, end_offset=len(text))]
    boundaries = [0] + [offset for offset, _ in meaningful[1:]] + [len(text)]
    titles = [title for _, title in meaningful]
    return [
        DetectedChapter(index=index, title=titles[index - 1], start_offset=start, end_offset=end)
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
    ]


def validate_split(text: str, boundaries: list[int]) -> list[tuple[int, int]]:
    """Check author-chosen split points and return the resulting spans.

    Each boundary must fall strictly inside the text, at the start of a line,
    in increasing order, and leave no piece without readable text.
    """

    spans: list[tuple[int, int]] = []
    previous = 0
    for boundary in [*boundaries, len(text)]:
        if not previous < boundary <= len(text):
            raise ValueError("Split points must be increasing and inside the text.")
        if boundary < len(text) and text[boundary - 1] != "\n":
            raise ValueError("Split points must fall at the start of a line.")
        if not text[previous:boundary].strip():
            raise ValueError("Every part needs some text.")
        spans.append((previous, boundary))
        previous = boundary
    return spans
