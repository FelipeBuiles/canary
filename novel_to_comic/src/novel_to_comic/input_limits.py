"""Shared source-input budgets used by upload validation and Stage 1."""

from __future__ import annotations

import os
import re
import time
import zipfile
import gzip
from io import BytesIO
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


class InputLimitError(ValueError):
    """Stable, customer-safe input rejection."""

    def __init__(self, message: str, *, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _positive_env(name: str, default: int) -> int:
    try:
        return max(1, int(os.environ.get(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class InputLimits:
    upload_bytes: int
    pdf_pages: int
    epub_documents: int
    extracted_characters: int
    remote_compressed_bytes: int
    remote_decompressed_characters: int
    extraction_seconds: int

    @classmethod
    def from_env(cls) -> "InputLimits":
        return cls(
            upload_bytes=_positive_env("CANARY_MAX_UPLOAD_MB", 50) * 1024 * 1024,
            pdf_pages=_positive_env("CANARY_MAX_PDF_PAGES", 2000),
            epub_documents=_positive_env("CANARY_MAX_EPUB_DOCUMENTS", 500),
            extracted_characters=_positive_env(
                "CANARY_MAX_EXTRACTED_CHARACTERS", 5_000_000
            ),
            remote_compressed_bytes=_positive_env(
                "CANARY_MAX_REMOTE_COMPRESSED_MB", 5
            )
            * 1024
            * 1024,
            remote_decompressed_characters=_positive_env(
                "CANARY_MAX_REMOTE_DECOMPRESSED_CHARACTERS", 2_000_000
            ),
            extraction_seconds=_positive_env("CANARY_MAX_EXTRACTION_SECONDS", 60),
        )


def _check_elapsed(started: float, limits: InputLimits) -> None:
    if time.monotonic() - started > limits.extraction_seconds:
        raise InputLimitError(
            "Source extraction took too long. Please upload a smaller source.",
            status_code=413,
        )


def _check_characters(text: str, limits: InputLimits) -> str:
    if len(text) > limits.extracted_characters:
        raise InputLimitError(
            (
                "Extracted source exceeds the "
                f"{limits.extracted_characters:,}-character limit."
            ),
            status_code=413,
        )
    return text


def _read_pdf(path: Path, limits: InputLimits, started: float) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(path))
        if reader.is_encrypted:
            raise InputLimitError("Encrypted PDFs are not supported.")
        if len(reader.pages) > limits.pdf_pages:
            raise InputLimitError(
                f"PDF exceeds the {limits.pdf_pages}-page limit.",
                status_code=413,
            )
        parts: list[str] = []
        characters = 0
        for page in reader.pages:
            _check_elapsed(started, limits)
            text = page.extract_text() or ""
            characters += len(text)
            if characters > limits.extracted_characters:
                raise InputLimitError(
                    (
                        "Extracted source exceeds the "
                        f"{limits.extracted_characters:,}-character limit."
                    ),
                    status_code=413,
                )
            if text:
                parts.append(text)
    except InputLimitError:
        raise
    except Exception as exc:
        raise InputLimitError(
            "This PDF could not be read. Please upload a valid, unencrypted PDF."
        ) from exc
    from novel_to_comic.pdf_cleanup import clean_pdf_text

    result = clean_pdf_text("\n\n".join(parts))
    if not result.strip():
        raise InputLimitError(
            "This PDF has no extractable text. Please use a text-based PDF, EPUB, or TXT file."
        )
    return result


class _TextExtractor(HTMLParser):
    _BLOCKS = {
        "h1", "h2", "h3", "h4", "h5", "h6", "p", "div", "section",
        "article", "br", "li", "blockquote", "pre", "tr",
    }
    _IGNORED = {"head", "script", "style"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.ignored_depth = 0

    def _break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n\n"):
            self.parts.append("\n\n")

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._IGNORED:
            self.ignored_depth += 1
        elif not self.ignored_depth and tag in self._BLOCKS:
            self._break()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._IGNORED:
            self.ignored_depth = max(0, self.ignored_depth - 1)
        elif not self.ignored_depth and tag in self._BLOCKS:
            self._break()

    def handle_data(self, data: str) -> None:
        if not self.ignored_depth:
            self.parts.append(data)


def _read_epub(path: Path, limits: InputLimits, started: float) -> str:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > limits.epub_documents * 10:
                raise InputLimitError(
                    "EPUB contains too many archive entries.", status_code=413
                )
            expanded_bytes = sum(info.file_size for info in infos)
            if expanded_bytes > limits.extracted_characters * 4:
                raise InputLimitError(
                    "EPUB expands beyond the allowed source size.", status_code=413
                )

        import ebooklib
        from ebooklib import epub

        book = epub.read_epub(str(path))
        documents = list(book.get_items_of_type(ebooklib.ITEM_DOCUMENT))
        if len(documents) > limits.epub_documents or len(book.spine) > limits.epub_documents:
            raise InputLimitError(
                f"EPUB exceeds the {limits.epub_documents}-document limit.",
                status_code=413,
            )
        if not book.spine:
            raise InputLimitError("This EPUB has no reading order. Please upload a valid EPUB, PDF, or TXT file.")
        by_id = {item.get_id(): item for item in documents}
        try:
            documents = [by_id[identifier] for identifier, _linear in book.spine]
        except KeyError as exc:
            raise InputLimitError("This EPUB's reading order contains an unreadable chapter.") from exc
        parts: list[str] = []
        characters = 0
        for item in documents:
            _check_elapsed(started, limits)
            extractor = _TextExtractor()
            extractor.feed(item.get_content().decode("utf-8", errors="replace"))
            text = "".join(extractor.parts).strip()
            characters += len(text)
            if characters > limits.extracted_characters:
                raise InputLimitError(
                    (
                        "Extracted source exceeds the "
                        f"{limits.extracted_characters:,}-character limit."
                    ),
                    status_code=413,
                )
            if text:
                parts.append(text)
    except InputLimitError:
        raise
    except (zipfile.BadZipFile, KeyError, OSError, ValueError) as exc:
        raise InputLimitError(
            "This EPUB could not be read. Please upload a valid EPUB file."
        ) from exc
    return "\n\n".join(parts)


_WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _read_docx(path: Path, limits: InputLimits, started: float) -> str:
    """Read a Word document's body paragraphs; formatting and notes are dropped."""
    from xml.etree import ElementTree

    try:
        with zipfile.ZipFile(path) as archive:
            try:
                info = archive.getinfo("word/document.xml")
            except KeyError as exc:
                raise InputLimitError(
                    "This Word document could not be read. Please upload a valid .docx file."
                ) from exc
            # Markup is far larger than its text, but bound it like EPUB expansion.
            if info.file_size > limits.extracted_characters * 20:
                raise InputLimitError(
                    "Word document expands beyond the allowed source size.", status_code=413
                )
            xml = archive.read(info)
        if b"<!DOCTYPE" in xml[:4096]:
            raise InputLimitError("This Word document could not be read. Please upload a valid .docx file.")
        _check_elapsed(started, limits)
        body = ElementTree.fromstring(xml).find(f"{_WORD_NS}body")
    except InputLimitError:
        raise
    except (zipfile.BadZipFile, ElementTree.ParseError, OSError, ValueError) as exc:
        raise InputLimitError(
            "This Word document could not be read. Please upload a valid .docx file."
        ) from exc
    paragraphs: list[str] = []
    characters = 0
    for paragraph in body.iter(f"{_WORD_NS}p") if body is not None else ():
        pieces: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{_WORD_NS}t" and node.text:
                pieces.append(node.text)
            elif node.tag == f"{_WORD_NS}tab":
                pieces.append("\t")
            elif node.tag in (f"{_WORD_NS}br", f"{_WORD_NS}cr"):
                pieces.append("\n")
        text = "".join(pieces).strip()
        if not text:
            continue
        characters += len(text) + 2
        if characters > limits.extracted_characters:
            raise InputLimitError(
                f"Extracted source exceeds the {limits.extracted_characters:,}-character limit.",
                status_code=413,
            )
        paragraphs.append(text)
    if not paragraphs:
        raise InputLimitError("This Word document has no text.")
    return "\n\n".join(paragraphs)


_MD_FRONT_MATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.DOTALL)
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MD_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_MD_EMPHASIS = re.compile(r"(?<!\w)(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1(?!\w)")
_MD_RULE = re.compile(r"^[ \t]{0,3}(?:[-*_][ \t]*){3,}$", re.MULTILINE)


def clean_markdown(text: str) -> str:
    """Keep a Markdown manuscript's prose and headings, without its markup.

    ATX heading markers are kept because chapter detection reads them;
    horizontal rules become a centered scene-break marker.
    """
    text = _MD_FRONT_MATTER.sub("", text)
    text = _MD_IMAGE.sub("", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_RULE.sub("* * *", text)
    return _MD_EMPHASIS.sub(r"\2", text)


def read_source(path: Path, limits: InputLimits | None = None) -> str:
    """Read and validate a TXT, Markdown, Word, PDF, or EPUB within the shared budgets."""
    limits = limits or InputLimits.from_env()
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise InputLimitError("The source file could not be read.") from exc
    if size > limits.upload_bytes:
        raise InputLimitError(
            f"Uploaded file exceeds the {limits.upload_bytes // (1024 * 1024)} MB limit.",
            status_code=413,
        )

    started = time.monotonic()
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text = _read_pdf(path, limits, started)
    elif suffix == ".epub":
        text = _read_epub(path, limits, started)
    elif suffix == ".docx":
        text = _read_docx(path, limits, started)
    elif suffix in {".txt", ".md", ".markdown"}:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise InputLimitError("The source file could not be read.") from exc
        if suffix != ".txt":
            text = clean_markdown(text)
    else:
        raise InputLimitError("Unsupported source type. Use TXT, Markdown, Word (.docx), PDF, or EPUB.")
    _check_elapsed(started, limits)
    return _check_characters(text, limits)


def decode_remote_story(
    content: bytes, limits: InputLimits | None = None
) -> str:
    """Decode plain/gzip remote story bytes without decompression bombs."""
    limits = limits or InputLimits.from_env()
    if len(content) > limits.remote_compressed_bytes:
        raise InputLimitError(
            "Remote story exceeds the compressed download limit.", status_code=413
        )

    if content.startswith(b"\x1f\x8b"):
        expanded = bytearray()
        try:
            with gzip.GzipFile(fileobj=BytesIO(content)) as stream:
                while chunk := stream.read(64 * 1024):
                    expanded.extend(chunk)
                    if len(expanded) > limits.remote_decompressed_characters * 4:
                        raise InputLimitError(
                            "Remote story expands beyond the allowed size.",
                            status_code=413,
                        )
            raw = bytes(expanded)
        except InputLimitError:
            raise
        except (OSError, EOFError) as exc:
            raise InputLimitError("Remote story archive is malformed.") from exc
    else:
        raw = content

    text = raw.decode("utf-8", errors="replace")
    if len(text) > limits.remote_decompressed_characters:
        raise InputLimitError(
            "Remote story exceeds the decompressed character limit.",
            status_code=413,
        )
    return text
