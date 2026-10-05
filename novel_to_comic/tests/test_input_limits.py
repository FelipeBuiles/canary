import zipfile
from pathlib import Path

import pytest

from novel_to_comic.input_limits import (
    InputLimitError,
    InputLimits,
    clean_markdown,
    decode_remote_story,
    read_source,
)


def _limits(**overrides) -> InputLimits:
    values = {
        "upload_bytes": 1_000_000,
        "pdf_pages": 2,
        "epub_documents": 2,
        "extracted_characters": 100,
        "remote_compressed_bytes": 100,
        "remote_decompressed_characters": 20,
        "extraction_seconds": 30,
    }
    values.update(overrides)
    return InputLimits(**values)


def test_txt_character_budget_is_shared_by_source_reader(tmp_path: Path):
    source = tmp_path / "story.txt"
    source.write_text("x" * 101)

    with pytest.raises(InputLimitError, match="character limit") as exc_info:
        read_source(source, _limits())

    assert exc_info.value.status_code == 413


def test_encrypted_pdf_is_rejected(tmp_path: Path):
    from pypdf import PdfWriter

    source = tmp_path / "locked.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("secret")
    with source.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(InputLimitError, match="Encrypted PDFs"):
        read_source(source, _limits())


def test_a_384_page_book_is_accepted_with_default_limits(tmp_path: Path, monkeypatch):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    for name in ("CANARY_MAX_UPLOAD_MB", "CANARY_MAX_PDF_PAGES", "CANARY_MAX_EXTRACTED_CHARACTERS", "CANARY_MAX_EXTRACTION_SECONDS"):
        monkeypatch.delenv(name, raising=False)
    source = tmp_path / "book.pdf"
    writer = PdfWriter()
    font = writer._add_object(DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    }))
    for number in range(1, 385):
        page = writer.add_blank_page(width=300, height=400)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 10 300 Td (Book page {number}.) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    with source.open("wb") as handle:
        writer.write(handle)

    text = read_source(source)

    assert text.startswith("Book page 1.")
    assert text.endswith("Book page 384.")
    assert text.count("Book page ") == 384


def test_pdf_page_limit_remains_configurable(tmp_path: Path):
    from pypdf import PdfWriter

    source = tmp_path / "book.pdf"
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=100, height=100)
    with source.open("wb") as handle:
        writer.write(handle)

    with pytest.raises(InputLimitError, match="2-page limit") as error:
        read_source(source, _limits())
    assert error.value.status_code == 413


def test_pdf_cleanup_precedes_chapter_grouping_and_does_not_change_upload(tmp_path: Path, monkeypatch):
    from types import SimpleNamespace
    from novel_to_comic.chapter_detection import detect_chapters

    original = b"original PDF bytes"
    source = tmp_path / "book.pdf"
    source.write_bytes(original)
    body = "The transformation lasted. " * 30
    page = f"OceanofPDF.com\n\n[ 1 ]\nT HE  TRANSFORMATION\n{body}\x00\n\nABOUT THE AUTHOR\nPromotional matter."
    monkeypatch.setattr("pypdf.PdfReader", lambda _path: SimpleNamespace(
        is_encrypted=False, pages=[SimpleNamespace(extract_text=lambda: page)]))

    text = read_source(source, _limits(extracted_characters=2000))

    assert "OceanofPDF" not in text and "\x00" not in text
    assert "THE  TRANSFORMATION" in text
    assert "Promotional" not in text
    assert [chapter.title for chapter in detect_chapters(text)] == ["[ 1 ]"]
    assert source.read_bytes() == original


def test_epub_expansion_is_checked_before_parsing(tmp_path: Path):
    source = tmp_path / "large.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("huge.xhtml", "x" * 1000)

    with pytest.raises(InputLimitError, match="expands beyond"):
        read_source(source, _limits())


def test_epub_preserves_chapter_headings_and_spine_order_for_grouping(tmp_path: Path):
    from ebooklib import epub
    from novel_to_comic.chapter_detection import group_chapters

    source = tmp_path / "book.epub"
    book = epub.EpubBook()
    book.set_identifier("chapter-groups")
    book.set_title("The Tide")
    book.set_language("en")
    chapters = []
    for number in range(1, 5):
        chapter = epub.EpubHtml(title=f"Chapter {number}", file_name=f"chapter-{number}.xhtml", uid=f"chapter-{number}")
        chapter.content = f"<h1>Chapter {number}</h1><p>" + "The tide turned. " * 2300 + "</p>"
        chapters.append(chapter)
    # Manifest item order is not the book's reading order.
    for chapter in reversed(chapters):
        book.add_item(chapter)
    book.toc = chapters
    book.add_item(epub.EpubNcx())
    book.spine = chapters
    epub.write_epub(str(source), book)
    # Minified XHTML must still separate headings from paragraphs.
    with zipfile.ZipFile(source) as archive:
        entries = [(info, archive.read(info)) for info in archive.infolist()]
    with zipfile.ZipFile(source, "w") as archive:
        for info, data in entries:
            archive.writestr(info, data.replace(b"\n", b"") if info.filename.endswith(".xhtml") else data)

    text = read_source(source)
    pieces = group_chapters(text)

    assert text.startswith("Chapter 1\n")
    assert text.index("Chapter 2\n") < text.index("Chapter 3\n") < text.index("Chapter 4\n")
    assert [title for title, _ in pieces] == ["Chapters 1–2", "Chapters 3–4"]
    assert "".join(content for _, content in pieces) == text


def test_remote_gzip_expansion_is_bounded():
    import gzip

    compressed = gzip.compress(b"x" * 100)

    with pytest.raises(InputLimitError, match="allowed size") as exc_info:
        decode_remote_story(compressed, _limits())

    assert exc_info.value.status_code == 413


def _docx(path: Path, body: str) -> Path:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{namespace}"><w:body>{body}</w:body></w:document>')
    return path


def test_docx_paragraphs_become_blank_line_separated_text(tmp_path: Path):
    source = _docx(tmp_path / "novel.docx", (
        "<w:p><w:r><w:t>Chapter 1</w:t></w:r></w:p>"
        "<w:p/>"
        "<w:p><w:r><w:t xml:space=\"preserve\">The keeper </w:t></w:r><w:r><w:t>climbed.</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>Line one</w:t><w:br/><w:t>line two</w:t></w:r></w:p>"
    ))

    assert read_source(source, _limits()) == "Chapter 1\n\nThe keeper climbed.\n\nLine one\nline two"


def test_docx_budgets_and_malformed_documents_are_rejected(tmp_path: Path):
    long = _docx(tmp_path / "long.docx", "<w:p><w:r><w:t>" + "x" * 101 + "</w:t></w:r></w:p>")
    with pytest.raises(InputLimitError, match="character limit") as exc_info:
        read_source(long, _limits())
    assert exc_info.value.status_code == 413

    empty = _docx(tmp_path / "empty.docx", "<w:p/>")
    with pytest.raises(InputLimitError, match="no text"):
        read_source(empty, _limits())

    not_zip = tmp_path / "broken.docx"
    not_zip.write_bytes(b"not a zip")
    with pytest.raises(InputLimitError, match="Word document could not be read"):
        read_source(not_zip, _limits())

    entities = tmp_path / "entities.docx"
    with zipfile.ZipFile(entities, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>')
    with pytest.raises(InputLimitError, match="Word document could not be read"):
        read_source(entities, _limits())


def test_markdown_keeps_prose_and_chapter_headings_without_markup():
    text = (
        "---\ntitle: Draft\n---\n"
        "# Chapter 1\n\nShe said **no** and *meant* it. See [the map](map.png).\n"
        "![cover](cover.png)\n\n---\n\nsnake_case_word stays.\n"
    )

    assert clean_markdown(text) == (
        "# Chapter 1\n\nShe said no and meant it. See the map.\n"
        "\n\n* * *\n\nsnake_case_word stays.\n"
    )


def test_markdown_files_are_read_as_cleaned_text(tmp_path: Path):
    source = tmp_path / "novel.md"
    source.write_text("# Chapter 1\n\n**Bold** start.")

    assert read_source(source, _limits()) == "# Chapter 1\n\nBold start."
