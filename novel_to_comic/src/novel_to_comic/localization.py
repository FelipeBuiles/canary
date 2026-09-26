"""Supported product locales; selection never changes a translation's source."""
from typing import Literal, get_args

Language = Literal["en", "es", "fr"]
LetteringLocale = Literal["source", Language]
LANGUAGES = get_args(Language)
LETTERING_LOCALES = get_args(LetteringLocale)
LANGUAGE_NAMES: dict[Language, str] = {"en": "English", "es": "Spanish", "fr": "French"}


def translation_status(texts: dict[str, str], sources: dict[str, str], locale: str) -> str:
    """Missing, stale, or current; an intentionally empty translation is present."""
    if locale not in texts:
        return "missing"
    if locale == "source" or sources.get(locale) == texts["source"]:
        return "current"
    return "stale"
