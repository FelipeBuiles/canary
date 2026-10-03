"""Find chapter headings so a long upload can be grouped into parts.

Long uploads group consecutive chapters into parts. Authors can also choose
boundaries manually. Boundaries always fall at the start of a line, so splitting
never cuts a sentence, and the pieces concatenate back to the original.
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
# Some books decorate chapter numbers ("[ 1 ]", "(XII)"). Keep the
# matching delimiters and whole-line requirement so inline citations do not
# become chapter boundaries.
_DECORATED_NUMBER = re.compile(
    rf"^(?:\[\s*(?:\d{{1,3}}|{_ROMAN})\s*\]|\(\s*(?:\d{{1,3}}|{_ROMAN})\s*\))$",
    re.IGNORECASE,
)
_MAX_HEADING_CHARS = 80
PART_TARGET_CHARACTERS = 100_000


class DetectedChapter(BaseModel):
    """One proposed division: its heading and exact half-open text span."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    index: int = Field(ge=1)
    title: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    # The first span starts at zero even when its heading follows an opening.
    # Expose that distinction for source coverage labels without changing text.
    opening_characters: int = Field(default=0, ge=0)

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
            and (_HEADING.match(stripped) or _BARE_NUMBER.match(stripped)
                 or _DECORATED_NUMBER.match(stripped))
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
    # PDFs often put page numbers on their own lines. When numbered chapter
    # headings are available, those numbers must not become chapter boundaries.
    numbered_headings = [
        item for item in starts
        if re.match(r"^(?:chapter|part|book|volume)\s+", item[1], re.IGNORECASE)
    ]
    # A table of contents can spell out chapter names even when the actual
    # chapters use bare numerals. Require headings with body text before
    # preferring them to the numerals.
    numbered_bodies = 0
    for position, (offset, _title) in enumerate(numbered_headings):
        following = numbered_headings[position + 1][0] if position + 1 < len(numbered_headings) else len(text)
        if len(text[offset:following].partition("\n")[2].strip()) >= 200:
            numbered_bodies += 1
    if numbered_bodies >= 2:
        starts = [item for item in starts if _HEADING.match(item[1])]
    # Repeated markers with nothing between them (a table of contents) would
    # create empty chapters; keep only headings that begin real content.
    meaningful: list[tuple[int, str]] = []
    for position, (offset, title) in enumerate(starts):
        following = starts[position + 1][0] if position + 1 < len(starts) else len(text)
        body = text[offset:following].split("\n", 1)
        if len(body) > 1 and len(body[1].strip()) >= 200:
            # A repeated running chapter header does not begin a new chapter.
            if not meaningful or meaningful[-1][1].casefold() != title.casefold():
                meaningful.append((offset, title))
    if not meaningful:
        return [DetectedChapter(index=1, title="Full text", start_offset=0, end_offset=len(text))]
    boundaries = [0] + [offset for offset, _ in meaningful[1:]] + [len(text)]
    titles = [title for _, title in meaningful]
    return [
        DetectedChapter(
            index=index, title=titles[index - 1], start_offset=start, end_offset=end,
            opening_characters=meaningful[0][0]
            if index == 1 and text[:meaningful[0][0]].strip() else 0,
        )
        for index, (start, end) in enumerate(zip(boundaries, boundaries[1:]), start=1)
    ]


def group_chapters(
    text: str, *, target_characters: int = PART_TARGET_CHARACTERS,
) -> list[tuple[str | None, str]]:
    """Group whole chapters near a text budget, preserving every character.

    Short manuscripts remain one part. The target is advisory: an oversized
    chapter or a source with no detected headings stays intact rather than
    inventing a chapter boundary. Titles describe each group's chapter range.
    """
    if target_characters < 1:
        raise ValueError("The part target must be positive.")
    if len(text) <= target_characters:
        return [(None, text)]
    chapters = detect_chapters(text)
    groups: list[list[DetectedChapter]] = []
    current: list[DetectedChapter] = []
    for chapter in chapters:
        if current and chapter.end_offset - current[0].start_offset > target_characters:
            groups.append(current)
            current = []
        current.append(chapter)
    if current:
        groups.append(current)
    if len(groups) <= 1:
        return [(None, text)]
    return [
        (range_title(group[0].title, group[-1].title), text[group[0].start_offset:group[-1].end_offset])
        for group in groups
    ]


_NUMBER_ONLY = re.compile(rf"^[\[(]?\s*({_ORDINAL})\s*[\])]?\.?$", re.IGNORECASE)
_CHAPTER_NUMBER = re.compile(rf"^chapter\s+({_ORDINAL})(?![\w-])", re.IGNORECASE)


def chapter_name(heading: str) -> str:
    """A reader-facing name for a detected heading.

    Decorated or bare numerals ("[ 7 ]", "XII.") become "Chapter 7"; shouted
    headings ("EPILOGUE") are put in title case. Named headings keep their words.
    """
    name = heading.strip().lstrip("#").strip()
    if match := _NUMBER_ONLY.match(name):
        number = match.group(1)
        return f"Chapter {number.upper() if re.fullmatch(_ROMAN, number, re.IGNORECASE) else number}"
    return name.title() if name.isupper() else name


_WORD_VALUES = {word: value for value, word in enumerate(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen twenty".split(), 1)} | {"thirty": 30, "forty": 40, "fifty": 50}
_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


def _ordinal_value(ordinal: str) -> int | None:
    ordinal = ordinal.lower()
    if ordinal.isdigit():
        return int(ordinal)
    if re.fullmatch(_ROMAN, ordinal):
        values = [_ROMAN_VALUES[character] for character in ordinal]
        return sum(-value if index + 1 < len(values) and value < values[index + 1] else value
                   for index, value in enumerate(values))
    words = re.split(r"[- ]", ordinal)
    if all(word in _WORD_VALUES for word in words):
        return sum(_WORD_VALUES[word] for word in words)
    return None


def heading_number(heading: str) -> int | None:
    """The chapter number a heading states ("[ 7 ]", "Chapter XII"), if any.

    Part, book and volume numbers are not chapter numbers; named headings
    ("Prologue") state none.
    """
    name = chapter_name(heading)
    match = _CHAPTER_NUMBER.match(name)
    return _ordinal_value(match.group(1)) if match else None


def range_title(first: str, last: str) -> str:
    """Name a group of chapters: "Chapters 1–6", "Chapter 44 – Epilogue"."""
    start, end = chapter_name(first), chapter_name(last)
    if start == end:
        return start
    first_number, last_number = _CHAPTER_NUMBER.match(start), _CHAPTER_NUMBER.match(end)
    if first_number and last_number:
        return f"Chapters {first_number.group(1)}–{last_number.group(1)}"
    return f"{start} – {end}"


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
