"""Automatic part grouping preserves source text and whole chapter boundaries."""

import pytest

from novel_to_comic.chapter_detection import chapter_name, detect_chapters, group_chapters, range_title


def _chapter(number: int, length: int = 30_000) -> str:
    return f"Chapter {number}\n" + "The tide turned. " * (length // 17) + "\n\n"


def test_long_manuscript_groups_consecutive_chapters_without_losing_front_matter():
    text = "Title and byline\n\n" + "".join(_chapter(number) for number in range(1, 8))

    pieces = group_chapters(text)

    assert [title for title, _ in pieces] == ["Chapters 1–3", "Chapters 4–6", "Chapter 7"]
    assert "".join(content for _, content in pieces) == text
    assert pieces[0][1].startswith("Title and byline")
    assert detect_chapters(text)[0].opening_characters == len("Title and byline\n\n")
    assert pieces[1][1].startswith("Chapter 4\n")
    assert all(len(content) <= 100_000 for _, content in pieces)


def test_small_manuscripts_keep_one_part_even_with_multiple_chapters():
    text = _chapter(1, 500) + _chapter(2, 500)

    assert group_chapters(text) == [(None, text)]


def test_oversized_chapters_and_unrecognized_headings_stay_intact():
    first = _chapter(1, 120_000)
    second = _chapter(2, 500)

    assert group_chapters(first + second) == [("Chapter 1", first), ("Chapter 2", second)]
    text = "The tide turned. " * 10_000
    assert group_chapters(text) == [(None, text)]


def test_page_numbers_and_repeated_pdf_headers_are_not_chapters():
    body = "The lighthouse kept its light. " * 12
    text = f"Chapter 1\n{body}\n2\n{body}\nChapter 1\n{body}\nChapter 2\n{body}\n3\n{body}"

    chapters = detect_chapters(text)

    assert [chapter.title for chapter in chapters] == ["Chapter 1", "Chapter 2"]
    assert chapters[1].start_offset == text.index("Chapter 2")
    assert "".join(text[chapter.start_offset:chapter.end_offset] for chapter in chapters) == text


def test_numbered_chapters_are_still_detected_when_no_explicit_headings_exist():
    body = "The lighthouse kept its light. " * 12
    text = f"I\n{body}\nII\n{body}"

    assert [chapter.title for chapter in detect_chapters(text)] == ["I", "II"]


def test_a_named_table_of_contents_does_not_hide_bare_chapter_headings():
    body = "The lighthouse kept its light. " * 12
    text = f"Contents\nChapter 1\nChapter 2\n\nI\n{body}\nII\n{body}"

    assert [chapter.title for chapter in detect_chapters(text)] == ["I", "II"]
    assert "".join(content for _, content in group_chapters(text, target_characters=500)) == text


def test_group_target_must_be_positive():
    with pytest.raises(ValueError, match="positive"):
        group_chapters("Story", target_characters=0)


@pytest.mark.parametrize("headings", [("[ 1 ]", "[ 2 ]", "[ 3 ]"), ("(I)", "(II)", "(III)")])
def test_decorated_chapter_numbers_group_whole_chapters_with_front_matter(headings):
    chapters = [f"{heading}\n" + "The tide turned. " * 3500 + "\n\n" for heading in headings]
    text = "Title and byline\n\n" + "".join(chapters)
    detected = detect_chapters(text)
    pieces = group_chapters(text)

    assert [chapter.title for chapter in detected] == list(headings)
    assert len(pieces) == 3
    assert pieces[0][1].startswith("Title and byline")
    assert pieces[1][1].startswith(headings[1] + "\n")
    assert "".join(content for _, content in pieces) == text


def test_inline_citations_and_mismatched_delimiters_are_not_headings():
    body = "The tide turned. " * 30
    text = f"See [1] for details.\n{body}\n[ 2 )\n{body}\n(3]\n{body}"

    assert [chapter.title for chapter in detect_chapters(text)] == ["Full text"]


def test_opening_coverage_distinguishes_real_text_from_blank_padding():
    body = "The lighthouse kept its light. " * 12
    text = f"A remembered promise.\n\n[ 1 ]\n{body}\n[ 2 ]\n{body}"
    chapters = detect_chapters(text)

    assert chapters[0].opening_characters == text.index("[ 1 ]")
    assert chapters[1].opening_characters == 0
    assert detect_chapters(f"\n\nChapter 1\n{body}")[0].opening_characters == 0
    assert detect_chapters(body)[0].opening_characters == 0


def test_named_prologue_stays_in_the_first_group_and_is_not_an_unlabelled_opening():
    text = "Prologue\n" + "The lighthouse kept its light. " * 12 + "\n" + _chapter(1) + _chapter(2)

    pieces = group_chapters(text, target_characters=40_000)

    assert pieces[0][0] == "Prologue – Chapter 1"
    assert detect_chapters(text)[0].opening_characters == 0
    assert "".join(content for _, content in pieces) == text


def test_part_titles_read_as_chapter_ranges_rather_than_raw_headings():
    assert range_title("[ 1 ]", "[ 6 ]") == "Chapters 1–6"
    assert range_title("[ 44 ]", "EPILOGUE") == "Chapter 44 – Epilogue"
    assert range_title("Chapter 3: The Storm", "Chapter 9: Home") == "Chapters 3–9"
    assert range_title("XII.", "XIV") == "Chapters XII–XIV"
    assert range_title("Prologue", "Chapter 2") == "Prologue – Chapter 2"
    assert chapter_name("Chapter 3: The Storm") == "Chapter 3: The Storm"
