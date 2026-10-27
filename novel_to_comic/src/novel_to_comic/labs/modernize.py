"""Source modernization: rewrite an excerpt's dialogue and narration for today's readers.

An experiment, not a stage. It reads a passage of a project's manuscript (or
pasted text) and asks one or more text models to update archaic, obscure or
offensive language under the operator's controls:

  intensity   light (words and forms only), moderate (phrasing), or
              contemporary (today's idiom throughout)
  scope       dialogue, narration, or both
  sensitive   keep (flag only), soften, or remove offensive language
  setting     keep the period setting free of anachronisms, or not
  comic       comic-ready: speakable balloon-length dialogue, drawable
              narration, and named referents a panel-by-panel reader needs
  notes       free-text direction for this passage

Plot facts, names and each character's attitude are never changed, so a
bigoted character stays bigoted even when the slur is gone. Each arm returns
the passage paragraph by paragraph, aligned to the input, with a list of the
notable changes it made (offensive language, every inferred addition and
every dropped clause), leaving routine rewording to the word diff. Deterministic checks
record what a reader would otherwise have to spot: missing paragraphs, edits
outside the chosen scope, and the reading load of sentences and speeches.

The excerpt is frozen into the run's ``source.json`` so every arm and every
retry compares against the same text, and the project is only read. Calls are
operator-funded like every Labs run and never touch account credits.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.config import load_config
from novel_to_comic.input_limits import read_source
from novel_to_comic.state import load_state
from novel_to_comic.text_models import default_reasoning, reasoning_options
from novel_to_comic.text_route_fallback import pinned_text_routes

from . import stage_models, storage

KIND = "modernize"
INTENSITIES = {
    "light": (
        "Light touch. Replace only archaic or obsolete words and grammatical forms "
        "(thee/thou, 'tis, 'twas, shan't, ere, whilst, hath) and terms a modern "
        "reader would not understand. Keep sentence structure, rhythm and length."
    ),
    "moderate": (
        "Moderate. Also rephrase stiff, convoluted or obsolete constructions so they "
        "read naturally aloud, while keeping the author's rhythm, imagery and a "
        "sense of the period. Expect the passage to come out up to about 10% shorter."
    ),
    "contemporary": (
        "Contemporary. Rewrite in natural present-day English, as if a skilled novelist "
        "wrote it today. Restructure sentences freely: break long periodic sentences "
        "into short ones, use active voice, and cut throat-clearing and stacked "
        "qualifiers. Keep every story beat and image. Tighten the wording hard: saying "
        "the same content in fewer, plainer words is the job at this level and is not "
        "a cut. Expect the passage to come out about 10-20% shorter. Following the "
        "original's sentence structure closely is a failure; dropping content (a fact, "
        "action, image, line of dialogue or tone cue) to save words is also a failure."
    ),
}
SCOPES = {
    "dialogue": "Change only spoken dialogue (text inside quotation marks). Return narration exactly as given.",
    "narration": "Change only narration (text outside quotation marks). Return dialogue exactly as given.",
    "both": "Change dialogue and narration.",
}
_OFFENSIVE = (
    "Offensive language means slurs, demeaning terms, and any generalization that "
    "belittles a group by race, ethnicity, religion, sex, disability or class, "
    "whether a character says it or the narrator does (for example a narrator aside "
    "such as 'as patiently as her sex would permit'). List every instance you find "
    "in changes with category 'offensive', whatever you do with it."
)
SENSITIVE = {
    "keep": (
        f"{_OFFENSIVE} Keep each instance as written, with revised equal to original "
        "and a note on why it may need attention."
    ),
    "soften": (
        f"{_OFFENSIVE} Replace each with neutral or period-plausible wording. A "
        "character's prejudice must still come through; do not make prejudiced "
        "characters kind. A narrator generalization becomes a neutral statement "
        "about the individual."
    ),
    "remove": (
        f"{_OFFENSIVE} Remove each, rewriting the line so a character's prejudice is "
        "shown by action or implication rather than voiced, and dropping narrator "
        "generalizations. Keep the plot consequence."
    ),
}
COMIC = (
    "Comic-ready. This text will be adapted into comic pages, where every line of "
    "dialogue sits in a balloon and narration in a small caption.",
    "- Dialogue: make every line easy to say aloud. Prefer sentences under about 15 "
    "words; split a long speech at its natural beats instead of cutting what the "
    "scene needs.",
    "- Dialogue tags: prefer plain 'said' or an action beat. An adverb or phrase that "
    "tells the artist how the speaker looks or sounds ('politely', 'solemnly', "
    "'off-handedly', 'with pretended horror') is a drawing cue: keep it, or turn it "
    "into a visible beat ('his face grave'). Drop only a tag adverb the line "
    "itself already makes obvious.",
    "- Narration: keep concrete, drawable detail (light, weather, gestures, props, "
    "expressions) and the facts a reader needs; cut abstract commentary and "
    "description that repeats what dialogue or action already shows.",
    "- Sentence length: aim for narration sentences of about 9-10 words on average, "
    "mixing short and medium; one idea per sentence. Split a long sentence rather "
    "than keep its clauses chained with commas and semicolons.",
    "- Clarity: a reader sees one panel at a time. Where a pronoun's referent is "
    "unclear, name the person or thing. Where the text implies a physical action "
    "the reader must picture to follow the scene, state it plainly. List each such "
    "addition in changes with category 'inferred' so it can be reviewed.",
)
CATEGORIES = ("archaic", "offensive", "clarity", "idiom", "tightened", "inferred")
MAX_WORDS = 4000
MAX_ARMS = 4
MAX_NOTES = 1000

_QUOTED = re.compile(r"“[^”]*”|\"[^\"]*\"|‘[^’]*’")


def selectable_models() -> list[dict[str, Any]]:
    return stage_models.selectable_models()


# ── Source text ─────────────────────────────────────────────────────────────


def paragraphs(text: str) -> list[str]:
    """Paragraphs from blank-line blocks; a hard-wrapped block's lines are rejoined.

    A block is hard-wrapped when every line but its last fills a typical
    40–80 character wrap width; otherwise each line is its own paragraph, as in
    sources that write one paragraph per line and use blank lines only between parts.
    """
    result: list[str] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        if len(lines) > 1 and all(40 <= len(line) <= 80 for line in lines[:-1]):
            result.append(" ".join(lines))
        else:
            result.extend(lines)
    return result


def _words(text: str) -> int:
    return len(text.split())


def manuscript(project_dir: Path, part_id: str | None = None) -> list[str]:
    source = stage_models.source_workspace(project_dir, part_id)
    state = load_state(source)
    novel = Path(state.novel_path)
    if not novel.is_absolute():
        novel = source / novel
    return paragraphs(read_source(novel))


def excerpt(all_paragraphs: list[str], start: int, max_words: int) -> dict[str, Any]:
    """Whole paragraphs from ``start`` until the next would pass ``max_words`` (at least one)."""
    if not 0 <= start < max(len(all_paragraphs), 1) or not 1 <= max_words <= MAX_WORDS:
        raise ValueError(f"Choose a start paragraph in range and 1–{MAX_WORDS} words")
    chosen: list[str] = []
    total = 0
    for paragraph in all_paragraphs[start:]:
        if chosen and total + _words(paragraph) > max_words:
            break
        chosen.append(paragraph)
        total += _words(paragraph)
    return {
        "start": start, "end": start + len(chosen), "words": total,
        "total_paragraphs": len(all_paragraphs), "total_words": sum(map(_words, all_paragraphs)),
        "paragraphs": chosen,
    }


# ── Spec ────────────────────────────────────────────────────────────────────


def validate_controls(controls: Any) -> dict[str, Any]:
    if not isinstance(controls, dict):
        raise ValueError("controls must be an object")
    intensity = controls.get("intensity", "moderate")
    scope = controls.get("scope", "both")
    sensitive = controls.get("sensitive", "soften")
    notes = controls.get("notes") or ""
    if intensity not in INTENSITIES:
        raise ValueError(f"intensity must be one of: {', '.join(INTENSITIES)}")
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of: {', '.join(SCOPES)}")
    if sensitive not in SENSITIVE:
        raise ValueError(f"sensitive must be one of: {', '.join(SENSITIVE)}")
    if not isinstance(notes, str) or len(notes) > MAX_NOTES:
        raise ValueError(f"notes must be text of at most {MAX_NOTES} characters")
    return {"intensity": intensity, "scope": scope, "sensitive": sensitive,
            "keep_setting": bool(controls.get("keep_setting", True)),
            "comic_ready": bool(controls.get("comic_ready", True)), "notes": notes.strip()}


def validate_arms(arms: Any) -> list[dict[str, Any]]:
    if not isinstance(arms, list) or not 1 <= len(arms) <= MAX_ARMS:
        raise ValueError(f"Choose between one and {MAX_ARMS} models")
    catalog = {model["id"]: model for model in selectable_models()}
    result, used = [], set()
    for arm in arms:
        if not isinstance(arm, dict):
            raise ValueError("Each arm must be an object")
        identity, model = arm.get("id"), arm.get("model")
        if not isinstance(identity, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identity) or identity in used:
            raise ValueError("Arm IDs must be unique letters, numbers, underscores or hyphens")
        if model not in catalog:
            raise ValueError(f"Unknown text model: {model}")
        if not catalog[model]["available"]:
            raise ValueError(f"Not enabled in this server process: {model}")
        reasoning = arm.get("reasoning") or default_reasoning(model)
        if reasoning not in reasoning_options(model):
            raise ValueError(f"Unsupported reasoning for {model}: {reasoning}")
        used.add(identity)
        result.append({"id": identity, "model": model, "reasoning": reasoning})
    return result


def validate_source(body: dict[str, Any], project_dir: Path) -> dict[str, Any]:
    """The frozen input: an excerpt of the project's manuscript, or pasted text."""
    pasted = body.get("text")
    if pasted is not None:
        if not isinstance(pasted, str):
            raise ValueError("text must be a string")
        chosen = paragraphs(pasted)
        words = sum(map(_words, chosen))
        if not chosen or words > MAX_WORDS:
            raise ValueError(f"Paste between 1 and {MAX_WORDS} words")
        return {"origin": "pasted", "paragraphs": chosen, "words": words}
    start, max_words = body.get("start", 0), body.get("max_words", 1500)
    if not isinstance(start, int) or not isinstance(max_words, int):
        raise ValueError("start and max_words must be integers")
    part_id = body.get("part_id")
    found = excerpt(manuscript(project_dir, part_id), start, max_words)
    return {"origin": "manuscript", "part_id": part_id, "start": found["start"], "end": found["end"],
            "paragraphs": found["paragraphs"], "words": found["words"]}


# ── Prompt ──────────────────────────────────────────────────────────────────


def system_prompt(controls: dict[str, Any]) -> str:
    rules = [
        "You modernize the language of public-domain fiction for a comic adaptation.",
        "Readers should meet the same story, characters and events, in language that reads clearly today.",
        "",
        f"Intensity: {INTENSITIES[controls['intensity']]}",
        f"Scope: {SCOPES[controls['scope']]}",
        f"Offensive language: {SENSITIVE[controls['sensitive']]}",
        ("Setting: keep the story in its period. Do not introduce modern technology, institutions, "
         "slang or references that would be anachronistic in the original setting."
         if controls["keep_setting"] else
         "Setting: you may use present-day idiom freely, but do not change events or places."),
    ]
    if controls.get("comic_ready", True):
        rules += ["", *COMIC]
    rules += [
        "",
        "Always:",
        "- Keep every event, fact, name, place, relationship and story beat.",
        "- Keep each character's distinct voice and register relative to the others "
        "(a formal character stays more formal than a casual one).",
        "- Keep each character's intent and attitude, including cruelty or prejudice; change the words, not who they are.",
        "- Keep the connotation of loaded words and the narrator's irony: a 'stealthy' knock stays furtive, "
        "not merely quiet; an ironic 'cleverly' stays ironic.",
        "- Use the variety of English the story is set in, consistently: a story set in England keeps British "
        "words (postman, trousers, pavement) and never mixes in American ones, and the reverse.",
        "- Unless intensity is light, standardize grammar that reads as a mistake today (\"he don't\"); keep "
        "dialect only where it marks a character's background, and keep it consistent for that character.",
        "- Keep violence, danger and mature themes; this is a language update, not censorship of the plot.",
        "- Return chapter and part headings unchanged.",
        "- Return every input paragraph, in order, with the same index. Return unchanged paragraphs verbatim.",
        "- Use the same quotation-mark style as the input.",
        "- Unless intensity is light, put dialogue tags subject first ('his father said', 'Morris replied'), "
        "not inverted ('said his father', 'replied the son').",
        "- Keep the author's typographic emphasis: words in ALL CAPS or italics stay emphasized the same way "
        "(\"THE PAW!\" stays in capitals), because emphasis decides bold lettering and balloon shape.",
        "",
        "Changes list: a reviewer reads it beside a word diff, so list only what deserves a second look:",
        "- every offensive instance (offensive);",
        "- inferred: anything your text states that the source does not, however obvious: a name in place of "
        "a pronoun, an action, a prop, a place or a purpose. Use 'inferred', never 'clarity', for these;",
        "- tightened: content of the source that your text drops: a fact, action, image, line of dialogue or "
        "tone cue, one entry each, with revised empty if nothing replaces it. Fewer words for the same content "
        "is routine rewording, not tightened;",
        "- obsolete terms or idioms whose meaning you had to interpret (archaic, idiom), and word choices that "
        "change emphasis or meaning without adding or dropping anything, such as 'disappointment' becoming "
        "'heartbreak' (clarity).",
        "Before answering, compare each paragraph with its source and add any inferred, tightened or clarity "
        "entry you missed. Do not list routine rewording. Quote the exact original phrase (not a whole sentence or passage) and "
        "its exact replacement. Notes are one short clause.",
    ]
    if controls["notes"]:
        rules += ["", f"Author direction for this passage: {controls['notes']}"]
    return "\n".join(rules)


def user_content(source_paragraphs: list[str]) -> str:
    return "Paragraphs to modernize:\n\n" + "\n\n".join(
        f"[{index}] {text}" for index, text in enumerate(source_paragraphs)
    )


RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["paragraphs", "changes"],
    "properties": {
        "paragraphs": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["index", "text"],
            "properties": {"index": {"type": "integer"}, "text": {"type": "string"}},
        }},
        "changes": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["paragraph", "original", "revised", "category", "note"],
            "properties": {
                "paragraph": {"type": "integer"}, "original": {"type": "string"}, "revised": {"type": "string"},
                "category": {"type": "string", "enum": list(CATEGORIES)}, "note": {"type": "string"},
            },
        }},
    },
}


def max_output_tokens(words: int) -> int:
    return min(64_000, 4_000 + words * 5)


# ── Checks ──────────────────────────────────────────────────────────────────


def _normalize(text: str) -> str:
    return " ".join(text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"').split())


def _narration(text: str) -> str:
    return _normalize(_QUOTED.sub("", text))


def _dialogue(text: str) -> str:
    return _normalize(" ".join(_QUOTED.findall(text)))


_SENTENCE_END = re.compile(r"(?<=[.!?])[\"”’]?\s+")
# A balloon past this many words crowds a panel.
LONG_SPEECH_WORDS = 25


def comic_metrics(paragraph_texts: list[str]) -> dict[str, Any]:
    """Reading load a letterer would feel: sentence length and the longest single speech."""
    sentences = [sentence for text in paragraph_texts for sentence in _SENTENCE_END.split(text) if sentence.strip()]
    speeches = [_words(quote) for text in paragraph_texts for quote in _QUOTED.findall(text)]
    return {
        "avg_sentence_words": round(sum(map(_words, sentences)) / len(sentences), 1) if sentences else 0,
        "longest_speech_words": max(speeches, default=0),
        "long_speeches": sum(1 for words in speeches if words > LONG_SPEECH_WORDS),
    }


def align(source_paragraphs: list[str], value: dict[str, Any]) -> tuple[list[str], dict[str, Any]]:
    """Revised paragraphs aligned to the input, and what a reader should know about them.

    A paragraph the model dropped keeps its original text and is listed as missing.
    """
    returned: dict[int, str] = {}
    for item in value.get("paragraphs") or []:
        if isinstance(item, dict) and isinstance(item.get("index"), int) and isinstance(item.get("text"), str):
            returned.setdefault(item["index"], item["text"].strip())
    revised = [returned.get(index, original) for index, original in enumerate(source_paragraphs)]
    missing = [index for index in range(len(source_paragraphs)) if index not in returned]
    changed = [index for index, (before, after) in enumerate(zip(source_paragraphs, revised))
               if _normalize(before) != _normalize(after)]
    checks = {
        "changed_paragraphs": len(changed),
        "missing_paragraphs": missing,
        "extra_paragraphs": sorted(index for index in returned if not 0 <= index < len(source_paragraphs)),
        "words_before": sum(map(_words, source_paragraphs)),
        "words_after": sum(map(_words, revised)),
        "dialogue_edits": [index for index in changed
                           if _dialogue(source_paragraphs[index]) != _dialogue(revised[index])],
        "narration_edits": [index for index in changed
                            if _narration(source_paragraphs[index]) != _narration(revised[index])],
        "comic_before": comic_metrics(source_paragraphs),
        "comic_after": comic_metrics(revised),
    }
    return revised, checks


def scope_violations(scope: str, checks: dict[str, Any]) -> list[int]:
    """Paragraphs edited outside the chosen scope; quote detection is heuristic."""
    if scope == "dialogue":
        return checks["narration_edits"]
    if scope == "narration":
        return checks["dialogue_edits"]
    return []


def _changes(value: dict[str, Any], count: int) -> list[dict[str, Any]]:
    result = []
    for item in value.get("changes") or []:
        if not isinstance(item, dict):
            continue
        paragraph = item.get("paragraph")
        result.append({
            "paragraph": paragraph if isinstance(paragraph, int) and 0 <= paragraph < count else None,
            "original": str(item.get("original") or ""), "revised": str(item.get("revised") or ""),
            "category": item.get("category") if item.get("category") in CATEGORIES else "clarity",
            "note": str(item.get("note") or ""),
        })
    return result


# ── Run ─────────────────────────────────────────────────────────────────────


def source_sha256(source: dict[str, Any]) -> str:
    return hashlib.sha256("\n\n".join(source["paragraphs"]).encode()).hexdigest()


def write_source(user_root: Path, run_id: str, source: dict[str, Any]) -> None:
    storage.write_json(storage.run_file(user_root, run_id, "source.json"), source)


def read_source_file(user_root: Path, run_id: str) -> dict[str, Any]:
    return json.loads(storage.run_file(user_root, run_id, "source.json").read_text())


def _usage(records: list[Any]) -> dict[str, Any]:
    log = [record.model_dump() for record in records if record is not None]
    costs = [entry.get("cost_usd") for entry in log]
    return {
        "calls": len(log),
        "input_tokens": sum(entry.get("input_tokens") or 0 for entry in log),
        "output_tokens": sum(entry.get("output_tokens") or 0 for entry in log),
        "cost_usd": round(sum(cost for cost in costs if cost is not None), 6),
        "unpriced_calls": sum(1 for cost in costs if cost is None),
        "api_equivalent_usd": stage_models.api_equivalent_usd(log) if log else None,
    }


async def run_arm(user_root: Path, run_id: str, project: str, arm: dict[str, Any],
                  controls: dict[str, Any], *, retry_of: dict[str, Any] | None = None) -> None:
    from novel_to_comic.clients.text import generate_json
    from novel_to_comic.server.telemetry import ai_span
    from novel_to_comic.text_utils import clean_exception_message

    cell_id = arm["id"]
    attempts = list((retry_of or {}).get("attempts", []))
    if retry_of is not None:
        attempts.append({key: retry_of.get(key) for key in ("started_at", "seconds", "error", "usage")})
    funding = stage_models._funding(arm["model"])
    cell: dict[str, Any] = {"arm": arm["id"], "model": arm["model"], "reasoning": arm["reasoning"],
                            "funding": funding, "status": "running", "started_at": storage.now(),
                            "attempts": attempts}
    storage.write_cell(user_root, run_id, cell_id, cell)
    started = time.perf_counter()
    records: list[Any] = []
    try:
        source = read_source_file(user_root, run_id)
        config, _ = load_config(stage_models.source_workspace(user_root / project, source.get("part_id")))
        config = config.model_copy(update={
            "dev_model_selections": {}, "text_reasoning_efforts": {}, "text_reasoning_effort": arm["reasoning"],
        })
        with ai_span("labs.modernize", experiment_id=run_id, variant=cell_id, fixture_id=storage.fixture_id(project)), \
                ai_request_context(stage="modernize", project_name=f"labs/{run_id}/{cell_id}"), \
                pinned_text_routes():
            result = await generate_json(
                config, arm["model"], system_prompt(controls), user_content(source["paragraphs"]),
                temperature=0.4, max_output_tokens=max_output_tokens(source["words"]),
                json_schema=RESPONSE_SCHEMA, feature="labs.modernize",
            )
        records = [result.usage, *result.additional_usage]
        revised, checks = align(source["paragraphs"], result.value)
        checks["scope_violations"] = scope_violations(controls["scope"], checks)
        cell |= {"status": "ok", "paragraphs": revised, "changes": _changes(result.value, len(revised)),
                 "checks": checks}
    except Exception as exc:  # noqa: BLE001 - recorded on the cell for the reader
        cell |= {"status": "failed", "error": clean_exception_message(exc)}
    usage = _usage(records)
    storage.write_cell(user_root, run_id, cell_id, cell | {
        "seconds": round(time.perf_counter() - started, 1), "usage": usage,
        "cost_usd": usage["cost_usd"], "finished_at": storage.now(),
    })


async def run(user_root: Path, run_id: str, project: str, arms: list[dict[str, Any]],
              controls: dict[str, Any]) -> None:
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in stage_models._CONCURRENCY.items()}

    async def bounded(arm: dict[str, Any]) -> None:
        async with stage_models._acquire(semaphores, [arm["model"]]):
            await run_arm(user_root, run_id, project, arm, controls)

    await asyncio.gather(*(bounded(arm) for arm in arms))


def failed_cells(user_root: Path, run_id: str, cell_ids: list[str] | None) -> list[dict[str, Any]]:
    run_record = storage.read_run(user_root, run_id)
    if run_record is None or run_record.get("kind") != KIND:
        raise ValueError("Run not found")
    failed = [cell for cell in run_record["cells"] if cell.get("status") == "failed"]
    if cell_ids is None:
        return failed
    selected = [cell for cell in failed if cell["cell_id"] in set(cell_ids)]
    if len(selected) != len(set(cell_ids)):
        raise ValueError("Only failed cells can be retried")
    return selected


async def retry(user_root: Path, run_id: str, cells: list[dict[str, Any]]) -> None:
    spec = (storage.read_run(user_root, run_id) or {}).get("spec") or {}
    arms = {arm["id"]: arm for arm in spec.get("arms", [])}
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in stage_models._CONCURRENCY.items()}

    async def bounded(cell: dict[str, Any]) -> None:
        arm = arms[cell["cell_id"]]
        async with stage_models._acquire(semaphores, [arm["model"]]):
            await run_arm(user_root, run_id, spec["project"], arm, spec["controls"], retry_of=cell)

    await asyncio.gather(*(bounded(cell) for cell in cells))


# Output tokens per source word before any history exists: the rewrite (~1.4
# tokens a word) plus the changes list, times a reasoning allowance. Reasoning
# models bill thinking as output, which a plain length guess misses by 2x or more.
_OUTPUT_PER_WORD = 1.4 * 1.3
_REASONING_ALLOWANCE = {"none": 1.0, "enabled": 2.0, "low": 1.5, "medium": 2.2, "high": 3.0}
_HISTORY = 10


def output_ratios(user_root: Path, arms: list[dict[str, Any]]) -> dict[str, list[float]]:
    """Recorded output tokens per source word of this model and reasoning, newest runs first."""
    wanted = {(arm["model"], arm["reasoning"]): arm["id"] for arm in arms}
    ratios: dict[str, list[float]] = {arm["id"]: [] for arm in arms}
    root = storage.runs_root(user_root)
    for directory in sorted(root.iterdir(), reverse=True) if root.exists() else ():
        for path in (directory / "cells").glob("*.json"):
            try:
                cell = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            arm_id = wanted.get((cell.get("model"), cell.get("reasoning")))
            words = (cell.get("checks") or {}).get("words_before")
            output = (cell.get("usage") or {}).get("output_tokens")
            if arm_id and cell.get("status") == "ok" and words and output and len(ratios[arm_id]) < _HISTORY:
                ratios[arm_id].append(output / words)
    return ratios


def estimate_usd(user_root: Path, source: dict[str, Any], arms: list[dict[str, Any]],
                 controls: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-arm price guess and its basis: earlier runs of the same model and reasoning, else a heuristic.

    Input is ~4 characters a token. Output is the median recorded tokens per
    source word when this model and reasoning have run before, otherwise the
    passage once more plus changes, with a reasoning allowance. Subscription
    arms cost no USD, so they estimate to 0.
    """
    from novel_to_comic.model_costs import get_pricing_resolver

    resolver = get_pricing_resolver()
    input_tokens = len(system_prompt(controls) + user_content(source["paragraphs"])) // 4
    history = output_ratios(user_root, arms)
    estimates: dict[str, dict[str, Any]] = {}
    for arm in arms:
        past = sorted(history[arm["id"]])
        if past:
            per_word, basis = past[len(past) // 2], {"basis": "history", "runs": len(past)}
        else:
            per_word = _OUTPUT_PER_WORD * _REASONING_ALLOWANCE.get(arm["reasoning"], 2.0)
            basis = {"basis": "heuristic", "runs": 0}
        if stage_models._funding(arm["model"]) != "api":
            estimates[arm["id"]] = {"usd": 0.0, **basis}
            continue
        breakdown = resolver.calculate(
            model_alias=arm["model"], provider_model=resolver.resolve_model(arm["model"]), operation="text",
            input_tokens=input_tokens, output_tokens=int(source["words"] * per_word),
        )
        estimates[arm["id"]] = {"usd": None if breakdown.cost_usd is None else round(breakdown.cost_usd, 4), **basis}
    return estimates
