"""How seeded words are said: voices, stressed words and joined balloons.

Provider-free and evidence-led. A voice comes only from the source's own
speech tags around the quoted line ("she whispered", "crackled over the
radio") or from the copy itself (a quoted document is typed; a short place and
time caption is a location tag). Stress comes from words the copy already sets
in capitals. Canonical copy is never changed: stress is display markup in the
Pages layer, and every choice stays an editable suggestion.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Mapping, Sequence

from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.lettering import RoleStyle

_VOICES_PATH = Path(__file__).with_name("voices.json")
# Effects are cleared before a voice applies, as in the editor. Case and tail
# width belong to the book and are kept.
_CLEARED = {
    "halo_color", "halo_width", "shadow", "shadow_color", "shadow_x", "shadow_y",
    "gradient_color", "warp", "warp_amount", "jitter", "skew",
}


@lru_cache(maxsize=1)
def voice_catalogue() -> dict[str, dict[str, dict]]:
    data = json.loads(_VOICES_PATH.read_text())
    return {
        role: {voice["id"]: voice["patch"] for voice in voices}
        for role, voices in data.items() if not role.startswith("_")
    }


def voice_style(base: RoleStyle, role: str, voice: str) -> RoleStyle:
    """The same restyle the editor's voice tiles apply: effects cleared, then the patch."""
    cleared = {name: RoleStyle.model_fields[name].default for name in _CLEARED}
    return RoleStyle.model_validate(base.model_dump() | cleared | voice_catalogue()[role][voice])


@dataclass(frozen=True)
class Direction:
    voice: str | None = None
    emphasis: tuple[str, ...] = ()


_TAGS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("radio", re.compile(
        r"\b(over|through|on|into) the (radio|phone|telephone|intercom|speaker|loudspeaker|receiver|line|comm|comms|walkie[- ]talkie|headset)\b"
        r"|\bcrackl(ed|ing|es)\b|\bthrough the static\b|\btransmission\b", re.I)),
    ("whisper", re.compile(
        r"\b(whisper(ed|s|ing)?|murmur(ed|s|ing)?|mutter(ed|s|ing)?|breath(ed|es)|hiss(ed|es)?)\b"
        r"|\bunder (his|her|their|my|its) breath\b|\bsotto voce\b|\bsoftly\b|\bin a low voice\b", re.I)),
    ("shout", re.compile(
        r"\b(shout(ed|s|ing)?|yell(ed|s|ing)?|scream(ed|s|ing)?|shriek(ed|s|ing)?|bellow(ed|s|ing)?"
        r"|roar(ed|s|ing)?|holler(ed|s|ing)?|thunder(ed|s)|cried out|called out)\b", re.I)),
    ("weak", re.compile(
        r"\b(weakly|feebly|faintly|gasp(ed|s|ing)|rasp(ed|s|ing)|croak(ed|s|ing)|wheez(ed|es|ing)"
        r"|slurr(ed|ing)|groggily|trembling voice|voice (cracked|shook|trembled))\b", re.I)),
)
_QUOTE = re.compile(r"[\"“”«»]")
_WORD = re.compile(r"[\w']+", re.U)
_PLACE_TIME = re.compile(
    r"^(meanwhile|later|elsewhere|earlier|that (night|morning|evening|afternoon)|the next (day|morning|night)"
    r"|years? (later|ago|before)|hours? later|[\w .'-]+,\s*\d{3,4}\b)|\b1[5-9]\d\d\b|\b20\d\d\b", re.I)


def _speech_window(item: LetteringItem, sources: Mapping[str, str]) -> str:
    """Prose around this line's quotation in its cited units, not the whole passage."""
    words = _WORD.findall(item.text.lower())[:4]
    for unit_id in item.source_unit_ids:
        text = sources.get(unit_id, "")
        if not text:
            continue
        lowered = text.lower()
        if words:
            pattern = r"\W+".join(re.escape(word) for word in words)
            match = re.search(pattern, lowered)
            if match:
                # The tag sits beside this quotation; stop at the neighbouring ones.
                before = [q.end() for q in _QUOTE.finditer(text, 0, max(0, match.start() - 1))]
                start = max(before[-2] if len(before) >= 2 else 0, match.start() - 90)
                close = _QUOTE.search(text, match.end())
                after = close.end() if close else match.end()
                following = _QUOTE.search(text, after)
                end = min(following.start() if following else len(text), after + 140)
                return text[start:end]
        if len(text) <= 360:
            return text
    return ""


def _stressed(text: str) -> tuple[str, ...]:
    """Words already set in capitals inside otherwise mixed-case copy."""
    words = _WORD.findall(text)
    lower = sum(1 for word in words if any(ch.islower() for ch in word))
    if lower < 2:
        return ()
    stressed = [word for word in words if len(word) > 1 and word.isupper() and not word.isdigit()]
    return tuple(dict.fromkeys(stressed))[:4]


def direction_for(item: LetteringItem, sources: Mapping[str, str]) -> Direction:
    emphasis = _stressed(item.text) if item.kind != "sfx" else ()
    if item.kind == "caption":
        if item.delivery == "quoted_text":
            return Direction("journal", emphasis)
        words = _WORD.findall(item.text)
        if len(words) <= 7 and _PLACE_TIME.search(item.text.strip()):
            return Direction("location", ())
        return Direction(None, emphasis)
    if item.kind == "dialogue":
        window = _speech_window(item, sources)
        # Radio before whisper: "crackled softly over the radio" is still a radio.
        for voice, pattern in _TAGS:
            if window and pattern.search(window):
                return Direction(voice, emphasis)
        letters = [ch for ch in item.text if ch.isalpha()]
        if len(letters) >= 3 and all(ch.isupper() for ch in letters) and "!" in item.text:
            return Direction("shout", ())
    return Direction(None, emphasis)


def mark_emphasis(text: str, words: Sequence[str]) -> str:
    """Wrap the first whole-word occurrence of each stressed word in *asterisks*."""
    for word in words:
        text = re.sub(rf"(?<![\w*]){re.escape(word)}(?![\w*])", lambda match: f"*{match.group(0)}*", text, count=1)
    return text


def joined_to(previous: LetteringItem | None, item: LetteringItem) -> bool:
    """One speaker's consecutive balloons in a panel share one outline."""
    return (
        previous is not None
        and previous.kind == item.kind == "dialogue"
        and previous.delivery == item.delivery == "onscreen"
        and previous.speaker_entity_id is not None
        and previous.speaker_entity_id == item.speaker_entity_id
    )
