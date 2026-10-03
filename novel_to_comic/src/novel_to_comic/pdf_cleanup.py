"""Conservative PDF formatting cleanup before source text becomes immutable."""

import re

_WATERMARK = re.compile(r"^[ \t]*(?:https?://)?(?:www\.)?OceanofPDF\.com/?[ \t]*$", re.IGNORECASE | re.MULTILINE)
_CONTROLS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f]")
_SMALL_CAPS = re.compile(r"\b([A-Z]) ([A-Z]+)\b")
_AUTHOR_HEADING = re.compile(r"^[ \t]*(?:#{1,3}[ \t]+)?ABOUT[ \t]+THE[ \t]+AUTHOR[ \t]*$", re.IGNORECASE | re.MULTILINE)


def clean_pdf_text(text: str) -> str:
    """Remove known scan noise while keeping words, compound hyphens and chapters.

    Original uploads remain on disk. Only newly read PDFs pass through here;
    saved source units and their citation offsets are never edited in place.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    text = _CONTROLS.sub("", text)
    text = _WATERMARK.sub("", text)
    # An early table of contents is not an author section. Use the final
    # standalone heading only when it is in the back quarter of the document.
    headings = list(_AUTHOR_HEADING.finditer(text))
    if headings and headings[-1].start() >= len(text) * .75:
        text = text[:headings[-1].start()].rstrip() + "\n"
    words = {word.casefold() for word in re.findall(r"\b[A-Za-z]+\b", text)}

    def small_caps(match: re.Match) -> str:
        initial, rest = match.groups()
        joined = initial + rest
        # Preserve normal "I SAID" and "A HOUSE", and ambiguous initials.
        if joined.casefold() in words or (initial not in {"A", "I"} and len(rest) > 1):
            return joined
        if joined in {"ILLUSTRATION", "ILLUSTRATIONS", "INTERIOR", "AND", "AN", "AS", "AT",
                      "ALL", "ALSO", "ARE", "ABOUT", "AFTER", "AGAIN", "IF", "IN", "INTO", "IS", "IT", "ITS"}:
            return joined
        return match.group()

    text = _SMALL_CAPS.sub(small_caps, text)
    text = re.sub(r"(?<=\w)\u00ad\n[ \t]*(?=\w)", "", text)

    def wrapped_word(match: re.Match) -> str:
        first, second = match.groups()
        joined = first + second
        # Most hard-hyphen wraps are authored compounds. Remove a hard hyphen
        # only with an unbroken occurrence elsewhere in this source.
        return joined if joined.casefold() in words else first + "-" + second

    text = re.sub(r"\b([A-Za-z]+)-\n[ \t]*([a-z]+)\b", wrapped_word, text)
    return re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", text)
