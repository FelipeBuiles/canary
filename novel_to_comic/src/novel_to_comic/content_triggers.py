"""Find wording that commonly trips image providers' safety filters.

Providers often decline an image without saying why. After a decline, this
scans the request that was actually sent and names the phrases most likely
responsible, so the author knows what to reword. It is a provider-free,
deterministic heuristic: a match is a likely cause, never a verdict, and no
match does not clear the request.
"""

from __future__ import annotations

import re
from typing import Literal, TypedDict

TriggerCategory = Literal["nudity", "sexual", "gore", "violence"]
TriggerSource = Literal["description", "direction", "style", "other"]

_BODY = r"(?:torso|chest|breasts?|bosom|skin|body|bottom|buttocks|hips|thighs|flesh|midriff)"

# Ordered most specific first; overlapping matches keep the earliest pattern.
_PATTERNS: tuple[tuple[TriggerCategory, str], ...] = (
    ("nudity", rf"\b(?:bare|exposed|uncovered|naked|nude)\W+(?:\w+\W+){{0,2}}?{_BODY}\b"),
    ("nudity", r"\b(?:naked|nude|nudity|topless|bottomless|undressed|unclothed|disrobed)\b"),
    ("nudity", r"\bbare[- ]?(?:chested|breasted|skinned|bottomed)\b"),
    ("nudity", r"\b(?:nipples?|areolae?|genitals?|genitalia|groin|cleavage)\b"),
    ("sexual", r"\b(?:sexual|sexy|erotic|sensual|seductive|lingerie|aroused|provocative|lewd|lustful|voluptuous)\b"),
    ("gore", r"\b(?:gore|gory|bloody|blood-soaked|bloodied|bloodletting|entrails|guts|innards)\b"),
    ("gore", r"\b(?:severed|dismember(?:ed|ment)?|decapitat\w*|beheaded|disembowel\w*|mutilat\w*|flayed|eviscerat\w*)\b"),
    ("gore", r"\b(?:corpse|cadaver|gaping wound|open wound|exposed bone)\b"),
    ("violence", r"\b(?:impaled|stabbed|stabbing|slit throat|throat slit|torture[ds]?|execution|hanged)\b"),
)
_COMPILED: tuple[tuple[TriggerCategory, re.Pattern[str]], ...] = tuple(
    (category, re.compile(pattern, re.IGNORECASE)) for category, pattern in _PATTERNS)

# Compiled request section titles (compiled_request.py) and what each holds.
_SECTIONS: dict[str, TriggerSource] = {
    "Protected anchors": "description",
    "Your art direction": "direction",
    "Scene direction": "direction",
    "User constraint notes": "direction",
    "Secondary style notes": "style",
}


class ContentTrigger(TypedDict):
    phrase: str
    category: TriggerCategory
    source: TriggerSource
    context: str


def _source_at(prompt: str, offset: int) -> TriggerSource:
    best, best_at = "other", -1
    for title, source in _SECTIONS.items():
        at = prompt.rfind(f"\n{title}\n", 0, offset)
        if at < 0 and prompt.startswith(f"{title}\n"):
            at = 0
        if at > best_at:
            best, best_at = source, at
    return best  # type: ignore[return-value]


def _context(text: str, start: int, end: int, width: int = 48) -> str:
    left, right = max(0, start - width), min(len(text), end + width)
    snippet = " ".join(text[left:right].split())
    return f"{'…' if left else ''}{snippet}{'…' if right < len(text) else ''}"


def find_content_triggers(prompt: str, limit: int = 6) -> list[ContentTrigger]:
    """Return likely trigger phrases in source order, one per distinct phrase."""
    if not prompt:
        return []
    spans: list[tuple[int, int, TriggerCategory]] = []
    for category, pattern in _COMPILED:
        for match in pattern.finditer(prompt):
            if any(match.start() < end and start < match.end() for start, end, _ in spans):
                continue
            spans.append((match.start(), match.end(), category))
    found: list[ContentTrigger] = []
    seen: set[str] = set()
    for start, end, category in sorted(spans):
        phrase = " ".join(prompt[start:end].split())
        source = _source_at(prompt, start)
        # Fixed system sections (constraints, reference roles) are not the author's to change.
        if source == "other" or phrase.casefold() in seen:
            continue
        seen.add(phrase.casefold())
        found.append({"phrase": phrase, "category": category, "source": source, "context": _context(prompt, start, end)})
        if len(found) >= limit:
            break
    return found


__all__ = ["ContentTrigger", "find_content_triggers"]
