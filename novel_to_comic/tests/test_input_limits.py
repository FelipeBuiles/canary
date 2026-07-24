import zipfile
from pathlib import Path

import pytest

from novel_to_comic.input_limits import (
    InputLimitError,
    InputLimits,
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


def test_epub_expansion_is_checked_before_parsing(tmp_path: Path):
    source = tmp_path / "large.epub"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("huge.xhtml", "x" * 1000)

    with pytest.raises(InputLimitError, match="expands beyond"):
        read_source(source, _limits())


def test_remote_gzip_expansion_is_bounded():
    import gzip

    compressed = gzip.compress(b"x" * 100)

    with pytest.raises(InputLimitError, match="allowed size") as exc_info:
        decode_remote_story(compressed, _limits())

    assert exc_info.value.status_code == 413
