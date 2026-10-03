"""Map the whole saved manuscript so each part knows where it sits.

Extract analyzes one part at a time. Before it does, a multi-part series gets
a book map: every saved part is read once on its own (a digest, cached by the
part's exact text) and the digests are combined into the book's acts,
through-lines and recurring people. Each part then sees a bounded slice of
that map, however long the book is.

The map belongs to the series root and is rebuilt when the saved parts change
(appended, split or replaced text); unchanged parts keep their digests, so a
rebuild pays only for new text and one combining call. Single-part projects
have no map: their part is the whole book.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from novel_to_comic.clients.structured_call import generate_validated_json
from novel_to_comic.models.book_map import BookMap, BookMapPart, BookSynthesis, PartDigest
from novel_to_comic.models.parts import PartManifest, PartRecord
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts
from novel_to_comic.usage import estimate_text_cost
from novel_to_comic.workspace import series_root

DIRECTORY = "book_map"
#: Earlier parts summarized in a slice; older ones are covered by the acts.
EARLIER_SYNOPSES = 5
DIGEST_OUTPUT_TOKENS = 8000
SYNTHESIS_OUTPUT_TOKENS = 16000

DIGEST_PROMPT = """Read one part of a longer book and record what a reader of the
whole book needs to remember about it. The part may begin and end mid-story.
Return JSON with:
- synopsis: two to four sentences on what happens in this part, in story order.
- chapters: one entry per chapter or headed division, in order: label (the
  heading as a reader would name it, such as "Chapter 7" or "Epilogue") and
  synopsis (one sentence). Text before the first heading gets an "Opening"
  entry only when it contains story events.
- characters: everyone who matters to this part's events: name, aliases (other
  names the text uses for them), role (one phrase: who they are in the story)
  and presence: central (drives this part), supporting (acts in several
  scenes) or passing (appears briefly).
- threads: story questions, goals, mysteries, relationships and setups this
  part opens, advances or resolves: name (a short label), status (opens,
  advances or resolves) and note (one sentence).
- motifs: recurring images, objects or phrases.
Record only what the text states. Never predict later events.
"""

SYNTHESIS_PROMPT = """Combine the digests of one book's parts into a book map.
Parts are in reading order. The saved manuscript may stop before the book ends.
Return JSON with:
- synopsis: the book so far in three to six sentences.
- acts: the book's large movements, in order: number, title, summary,
  first_part and last_part (inclusive part IDs). Acts follow the whole book,
  not part boundaries: an act may span several parts, and a part may hold the
  end of one act and the start of the next. Together the acts cover every part.
  Use as many acts as the story has; do not force three.
- parts: one entry per part, in order: part_id and role (one sentence on what
  the part does in the book's structure).
- threads: the book's significant through-lines: title, summary (one or two sentences), opens_in (part ID) and resolves_in
  (part ID, or null while still open at the end of the saved text). Merge the
  same thread across digests.
- characters: people who matter beyond one part or drive the book: name,
  aliases, role, prominence (principal, recurring or minor), first_part and
  last_part. Merge digest entries that name the same person.
- themes and motifs: the book's themes and recurring motifs.
Use only the digests.
"""


Generate = Callable[..., Awaitable[Any]]


def _directory(workspace: Path) -> Path:
    return series_root(Path(workspace)) / DIRECTORY


def map_path(workspace: Path) -> Path:
    return _directory(workspace) / "book_map.json"


def _digest_path(workspace: Path, text_sha256: str) -> Path:
    return _directory(workspace) / "digests" / f"{text_sha256}.json"


def _write_json(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(payload)
    temporary.replace(path)


def _manifest(workspace: Path) -> PartManifest | None:
    try:
        return TargetArtifacts(series_root(Path(workspace))).read_part_manifest()
    except (ArtifactMissing, ArtifactInvalid):
        return None


def read_book_map(workspace: Path) -> BookMap | None:
    """The saved map, or None when there is none or it no longer parses."""
    path = map_path(workspace)
    if not path.exists():
        return None
    try:
        return BookMap.model_validate_json(path.read_text())
    except ValueError:
        return None


def is_fresh(book_map: BookMap, manifest: PartManifest) -> bool:
    """Whether the map read exactly the parts saved now."""
    return ([(part.part_id, part.text_sha256) for part in book_map.parts]
            == [(record.id, record.text_sha256) for record in manifest.parts])


def needs_book_map(workspace: Path) -> bool:
    manifest = _manifest(workspace)
    return manifest is not None and len(manifest.parts) > 1


def fresh_book_map(workspace: Path) -> BookMap | None:
    """The map when it matches the saved parts; a stale map is never used."""
    manifest = _manifest(workspace)
    book_map = read_book_map(workspace)
    if manifest is None or book_map is None or not is_fresh(book_map, manifest):
        return None
    return book_map


def _read_digest(workspace: Path, text_sha256: str) -> PartDigest | None:
    path = _digest_path(workspace, text_sha256)
    if not path.exists():
        return None
    try:
        return PartDigest.model_validate_json(path.read_text())
    except ValueError:
        return None


def digest_schema() -> dict:
    return PartDigest.model_json_schema()


def synthesis_schema(part_ids: list[str]) -> dict:
    """The combining response, with part references limited to saved parts."""
    schema = BookSynthesis.model_json_schema()
    definitions = schema["$defs"]
    definitions["BookThread"]["properties"].pop("id")  # code numbers threads
    part = {"type": "string", "enum": part_ids}
    for name, fields in (("BookAct", ("first_part", "last_part")),
                         ("BookCharacter", ("first_part", "last_part")),
                         ("BookThread", ("opens_in",)), ("PartRole", ("part_id",))):
        for field in fields:
            definitions[name]["properties"][field] = dict(part)
    definitions["BookThread"]["properties"]["resolves_in"] = {"anyOf": [dict(part), {"type": "null"}]}
    return schema


def check_synthesis(value: BookSynthesis, part_ids: list[str]) -> BookSynthesis:
    """Validate part references and coverage; code owns act and thread numbering."""
    order = {identifier: index for index, identifier in enumerate(part_ids)}

    def position(identifier: str | None, field: str) -> int:
        if identifier not in order:
            raise ValueError(f"{field} must name a saved part, not {identifier!r}")
        return order[identifier]

    if [role.part_id for role in value.parts] != part_ids:
        raise ValueError(f"parts must list every saved part once, in order: {part_ids}")
    covered: set[int] = set()
    previous_start = -1
    for act in value.acts:
        start, end = position(act.first_part, "first_part"), position(act.last_part, "last_part")
        if end < start or start < previous_start:
            raise ValueError("Acts must run forward through the parts, in reading order.")
        previous_start = start
        covered.update(range(start, end + 1))
    if covered != set(range(len(part_ids))):
        missing = [part_ids[index] for index in range(len(part_ids)) if index not in covered]
        raise ValueError(f"Acts must cover every part; uncovered: {missing}")
    for thread in value.threads:
        opens = position(thread.opens_in, "opens_in")
        if thread.resolves_in is not None and position(thread.resolves_in, "resolves_in") < opens:
            raise ValueError(f"Thread {thread.title!r} cannot resolve before it opens.")
    for character in value.characters:
        if position(character.last_part, "last_part") < position(character.first_part, "first_part"):
            raise ValueError(f"{character.name}'s last_part comes before their first_part.")
    return value.model_copy(update={
        "acts": [act.model_copy(update={"number": number}) for number, act in enumerate(value.acts, 1)],
        "threads": [thread.model_copy(update={"id": f"thread_{number:03d}"})
                    for number, thread in enumerate(value.threads, 1)],
    })


def _correction(content: str) -> Callable[[Any, Exception], str]:
    return lambda raw, error: (
        f"{content}\n\nYour previous JSON did not satisfy the contract.\n"
        f"PREVIOUS JSON: {json.dumps(raw, ensure_ascii=False, default=str)}\nFIX: {error}"
    )


async def ensure_book_map(config, workspace: Path, ctx, *, generate: Generate) -> BookMap | None:
    """Return a fresh map for a multi-part series, building what is missing.

    ``generate`` is the stage's recording, checkpointed text generator.
    """
    workspace = Path(workspace)
    manifest = _manifest(workspace)
    if manifest is None or len(manifest.parts) < 2:
        return None
    existing = read_book_map(workspace)
    if existing is not None and is_fresh(existing, manifest):
        return existing
    model = config.effective_extraction_model()
    target = TargetArtifacts(series_root(workspace))
    missing = [record for record in manifest.parts if _read_digest(workspace, record.text_sha256) is None]
    if missing:
        ctx.log(f"Mapping the whole book: reading {len(missing)} of {len(manifest.parts)} parts...")
    limit = asyncio.Semaphore(max(1, config.effective_text_concurrency()))

    async def digest(record: PartRecord) -> None:
        async with limit:
            content = json.dumps({"text": target.read_part_text(record.id)}, ensure_ascii=False)
            outcome = await generate_validated_json(
                config, model=model, system_prompt=DIGEST_PROMPT, user_content=content,
                parse=PartDigest.model_validate, correction=_correction(content),
                label=f"Book map: {record.title}", feature="extract.book_map_digest",
                max_output_tokens=DIGEST_OUTPUT_TOKENS, json_schema=digest_schema(),
                generate=generate,
            )
            _write_json(_digest_path(workspace, record.text_sha256), outcome.value.model_dump_json(indent=2))
            ctx.activity(detail=f"Book map: {record.title}", force=True)

    await asyncio.gather(*(digest(record) for record in missing))
    digests: dict[str, PartDigest] = {}
    for record in manifest.parts:
        saved = _read_digest(workspace, record.text_sha256)
        if saved is None:
            raise ArtifactMissing("book_map_digest", _digest_path(workspace, record.text_sha256))
        digests[record.id] = saved
    part_ids = [record.id for record in manifest.parts]
    content = json.dumps({"parts": [
        {"part_id": record.id, "title": record.title, "digest": digests[record.id].model_dump(mode="json")}
        for record in manifest.parts
    ]}, ensure_ascii=False)
    ctx.log("Mapping the whole book: combining acts, through-lines and recurring characters...")
    outcome = await generate_validated_json(
        config, model=model, system_prompt=SYNTHESIS_PROMPT, user_content=content,
        parse=lambda raw: check_synthesis(BookSynthesis.model_validate(raw), part_ids),
        correction=_correction(content), label="Book map", feature="extract.book_map",
        max_output_tokens=SYNTHESIS_OUTPUT_TOKENS, json_schema=synthesis_schema(part_ids),
        generate=generate,
    )
    synthesis = outcome.value
    roles = {role.part_id: role.role for role in synthesis.parts}
    book_map = BookMap(
        synopsis=synthesis.synopsis,
        parts=[BookMapPart(part_id=record.id, text_sha256=record.text_sha256,
                           synopsis=digests[record.id].synopsis, role=roles[record.id])
               for record in manifest.parts],
        acts=synthesis.acts, threads=synthesis.threads, characters=synthesis.characters,
        themes=synthesis.themes, motifs=synthesis.motifs,
    )
    _write_json(map_path(workspace), book_map.model_dump_json(indent=2))
    ctx.log(f"Book map ready: {len(book_map.acts)} acts across {len(book_map.parts)} parts.")
    return book_map


def estimate_book_map(config, workspace: Path) -> float:
    """What a fresh map still costs: uncached digests and one combining call."""
    manifest = _manifest(workspace)
    if manifest is None or len(manifest.parts) < 2:
        return 0.0
    existing = read_book_map(workspace)
    if existing is not None and is_fresh(existing, manifest):
        return 0.0
    model = config.effective_extraction_model()
    schema = len(json.dumps(digest_schema()))
    cost = sum(
        estimate_text_cost(model, len(DIGEST_PROMPT) + schema + record.characters + 200, output_chars=6000)
        for record in manifest.parts if _read_digest(Path(workspace), record.text_sha256) is None
    )
    count = len(manifest.parts)
    return cost + estimate_text_cost(
        model, len(SYNTHESIS_PROMPT) + len(json.dumps(synthesis_schema([r.id for r in manifest.parts])))
        + count * 5000, output_chars=4000 + count * 1500,
    )


def part_entry(book_map: BookMap | None, record: PartRecord) -> BookMapPart | None:
    """A part's map entry while it still describes that part's text."""
    if book_map is None:
        return None
    entry = next((part for part in book_map.parts if part.part_id == record.id), None)
    return entry if entry is not None and entry.text_sha256 == record.text_sha256 else None


def book_slice(book_map: BookMap, part_id: str) -> dict[str, Any]:
    """What one part needs from the map: bounded however long the book is."""
    order = {part.part_id: index for index, part in enumerate(book_map.parts)}
    here = order[part_id]

    def spans(first: str, last: str) -> bool:
        return order[first] <= here <= order[last]

    threads = []
    for thread in book_map.threads:
        opens, resolves = order[thread.opens_in], order.get(thread.resolves_in) if thread.resolves_in else None
        if opens <= here and (resolves is None or resolves >= here):
            threads.append({
                "title": thread.title, "summary": thread.summary,
                "here": "opens" if opens == here else "resolves" if resolves == here else "continues",
                "opens_in": thread.opens_in, "resolves_in": thread.resolves_in,
            })
    part = book_map.parts[here]
    return {
        "book_synopsis": book_map.synopsis,
        "this_part": {"part_id": part.part_id, "synopsis": part.synopsis, "role": part.role},
        "acts": [act.model_dump(mode="json") for act in book_map.acts if spans(act.first_part, act.last_part)],
        "earlier_parts": [{"part_id": earlier.part_id, "synopsis": earlier.synopsis}
                          for earlier in book_map.parts[max(0, here - EARLIER_SYNOPSES):here]],
        "threads": threads,
        "characters": [character.model_dump(mode="json") for character in book_map.characters
                       if character.prominence != "minor" and spans(character.first_part, character.last_part)],
        "themes": list(book_map.themes),
        "motifs": list(book_map.motifs),
    }


def _names(*values: str) -> set[str]:
    names = set()
    for value in values:
        name = " ".join(value.casefold().split())
        if name:
            names.add(name)
            names.add(name.removeprefix("the "))
    return names


def promote_recurring_cast(bible: StoryBible, book_map: BookMap, part_id: str) -> list[str]:
    """Require Cast references for this part's people the book keeps returning to.

    A principal or recurring character in the map can appear only briefly in
    the part that introduces them; scene counts alone would skip their Cast
    reference. Matching is by exact name or alias. Nothing is ever demoted.
    """
    important = set()
    for character in book_map.characters:
        if character.prominence in {"principal", "recurring"}:
            important |= _names(character.name, *character.aliases)
    rostered = {cid for scene in bible.scenes if scene.part_id == part_id for cid in scene.character_ids}
    promoted = []
    for character in bible.characters:
        if (character.id in rostered and not character.cast_required
                and _names(character.name, *character.aliases) & important):
            character.cast_required = True
            promoted.append(character.name)
    return promoted
