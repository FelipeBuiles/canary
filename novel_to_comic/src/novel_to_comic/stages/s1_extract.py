"""Stage 1: Novel → Story Bible JSON.

Reads the full novel and makes one long-context call to Gemini 3.1 Pro
to extract characters, locations, scenes, and narrative arcs.
"""

import json
import re
from pathlib import Path

from pydantic import ValidationError
from rich.console import Console

from novel_to_comic.clients import text
from novel_to_comic.config import Config
from novel_to_comic.events import EventCallback, _NOOP
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.state import (
    PipelineState,
    begin_stage,
    complete_stage,
    fail_stage,
    record_item_done,
    save_state,
)
from novel_to_comic.usage import ApiResult, estimate_text_cost

console = Console()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"


def _read_novel(novel_path: Path) -> str | bytes:
    """Read novel text from EPUB, PDF, or plain text.

    For image-based PDFs where text extraction yields nothing, returns the raw
    PDF bytes so the caller can pass them directly to Gemini's native PDF
    understanding instead of failing with an empty prompt.
    """
    if novel_path.suffix.lower() == ".epub":
        return _read_epub(novel_path)
    elif novel_path.suffix.lower() == ".pdf":
        text = _read_pdf(novel_path)
        if not text.strip():
            return novel_path.read_bytes()
        return text
    return novel_path.read_text(encoding="utf-8", errors="replace")

def _read_pdf(pdf_path: Path) -> str:
    """Extract text content from a PDF file."""
    from pypdf import PdfReader
    reader = PdfReader(str(pdf_path))
    text_parts = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            text_parts.append(text)
    return "\n\n".join(text_parts)

def _read_epub(epub_path: Path) -> str:
    """Extract text content from an EPUB file."""
    import ebooklib
    from ebooklib import epub
    from html.parser import HTMLParser

    class _TextExtractor(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []

        def handle_data(self, data: str) -> None:
            self.parts.append(data)

    book = epub.read_epub(str(epub_path))
    full_text: list[str] = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        extractor = _TextExtractor()
        raw_bytes = item.get_content()
        decoded = raw_bytes.decode("utf-8", errors="replace")
        if "\ufffd" in decoded:
            console.print("[yellow]Warning: EPUB item contained non-UTF-8 bytes; some content may be garbled.[/yellow]")
        extractor.feed(decoded)
        text = "".join(extractor.parts).strip()
        if text:
            full_text.append(text)
    return "\n\n".join(full_text)


def _normalize_narrative_arcs(arcs: list[dict]) -> list[dict]:
    """Normalize narrative arc dicts to match the NarrativeArc schema.

    LLMs sometimes return variations like:
      - act: "Act 1" instead of 1
      - "description" instead of "title"
      - "scene_ids" / "scene_list" instead of "scenes"
      - "climax_scene_id" (a single id) instead of a list
    """
    normalized = []
    for i, arc in enumerate(arcs, start=1):
        fixed = dict(arc)

        # Normalize title: try common alternative field names
        if "title" not in fixed or not fixed["title"]:
            for alt in ("name", "description", "summary", "label"):
                if alt in fixed and fixed[alt]:
                    fixed["title"] = fixed.pop(alt)
                    break
            else:
                fixed["title"] = f"Act {i}"

        # Normalize scenes list: try common alternative field names
        if "scenes" not in fixed or not fixed["scenes"]:
            for alt in ("scene_ids", "scene_list", "scene_numbers", "scene_id_list"):
                if alt in fixed and fixed[alt]:
                    fixed["scenes"] = fixed.pop(alt)
                    break
            else:
                # Last resort: collect any value that looks like a scene id
                scene_candidates = [
                    v for k, v in fixed.items()
                    if isinstance(v, str) and v.startswith("scene_")
                ]
                fixed["scenes"] = scene_candidates

        # Ensure scenes is a list
        if isinstance(fixed.get("scenes"), str):
            fixed["scenes"] = [fixed["scenes"]]

        normalized.append(fixed)
    return normalized


def _looks_adult(age_range: str, visual_anchor: str) -> bool:
    text = f"{age_range} {visual_anchor}".lower()
    if any(word in text for word in ("adult", "mature", "middle-aged", "middle aged", "elderly")):
        return True
    return any(int(match) >= 18 for match in re.findall(r"\d+", text))


def _normalize_character_anchor_tags(characters: list[dict]) -> list[dict]:
    """Fix common Danbooru age/gender tag slips before validation."""
    for character in characters:
        anchor = character.get("visual_anchor")
        if not isinstance(anchor, str):
            continue

        gender = str(character.get("gender", "")).lower()
        tags = [tag.strip() for tag in anchor.split(",")]
        if not tags:
            continue

        is_androgynous = any(word in gender for word in ("androgyn", "non-binary", "nonbinary"))
        if is_androgynous:
            # Keep explicit ambiguity: avoid forcing binary count/gender tags for
            # characters extracted as androgynous/non-binary.
            if tags[0].lower() in {"1man", "1woman", "1boy", "1girl"}:
                tags[0] = "1other"
            tags = [
                tag for tag in tags
                if tag.lower() not in {"adult male", "adult female", "child male", "child female"}
            ]
            character["visual_anchor"] = ", ".join(tag for tag in tags if tag)
            continue

        if not _looks_adult(str(character.get("age_range", "")), anchor):
            continue

        is_female = any(word in gender for word in ("female", "woman", "girl"))
        is_male = not is_female and any(word in gender for word in ("male", "man", "boy"))

        if is_male and tags[0].lower() in {"1boy", "1girl"}:
            tags[0] = "1man"
            tags = [tag for tag in tags if tag.lower() != "adult"]
            if not any(tag.lower() == "adult male" for tag in tags):
                tags.insert(1, "adult male")
        elif is_female and tags[0].lower() in {"1boy", "1girl"}:
            tags[0] = "1woman"
            tags = [tag for tag in tags if tag.lower() != "adult"]
            if not any(tag.lower() == "adult female" for tag in tags):
                tags.insert(1, "adult female")

        character["visual_anchor"] = ", ".join(tag for tag in tags if tag)
    return characters


def _is_offscreen_character(character: dict) -> bool:
    """Return True for voice-only entities that should not become visual subjects."""
    features = character.get("distinguishing_features", [])
    if isinstance(features, list):
        features_text = " ".join(str(feature) for feature in features)
    else:
        features_text = str(features)
    text = " ".join(
        str(character.get(field, ""))
        for field in ("name", "visual_anchor", "default_outfit", "age_range", "gender")
    )
    text = f"{text} {features_text}".lower()
    return any(
        marker in text
        for marker in (
            "off-screen",
            "off screen",
            "off-panel",
            "off panel",
            "unseen speaker",
            "unseen voice",
            "voice-only",
            "voice only",
            "heard but not seen",
            "not physically shown",
            "never physically shown",
        )
    )


def _remove_offscreen_characters(result: dict) -> dict:
    """Drop voice-only characters until the pipeline models off-screen speakers."""
    characters = result.get("characters")
    if not isinstance(characters, list):
        return result

    # TODO: Add first-class off-screen speaker support instead of dropping them.
    removed_ids = {
        character.get("id")
        for character in characters
        if isinstance(character, dict) and _is_offscreen_character(character)
    }
    removed_ids.discard(None)
    if not removed_ids:
        return result

    result["characters"] = [
        character
        for character in characters
        if not (isinstance(character, dict) and character.get("id") in removed_ids)
    ]

    for character in result["characters"]:
        relationships = character.get("relationships")
        if isinstance(relationships, list):
            character["relationships"] = [
                rel
                for rel in relationships
                if not (isinstance(rel, dict) and rel.get("character_id") in removed_ids)
            ]

    for scene in result.get("scenes", []):
        if isinstance(scene, dict) and isinstance(scene.get("character_ids"), list):
            scene["character_ids"] = [
                character_id
                for character_id in scene["character_ids"]
                if character_id not in removed_ids
            ]

    return result


def _normalize_result(result: dict) -> dict:
    """Apply light normalization to the raw LLM output before Pydantic validation."""
    if "narrative_arcs" in result and isinstance(result["narrative_arcs"], list):
        result["narrative_arcs"] = _normalize_narrative_arcs(result["narrative_arcs"])
    result = _remove_offscreen_characters(result)
    if "characters" in result and isinstance(result["characters"], list):
        result["characters"] = _normalize_character_anchor_tags(result["characters"])
    return result


async def _extract_with_retry(
    config: Config,
    system_prompt: str,
    novel_text: str,
    max_retries: int = 2,
) -> StoryBible:
    """Call the extraction model, normalize, validate, and retry on schema errors."""
    last_error: Exception | None = None
    user_content = novel_text

    last_usage = None
    for attempt in range(max_retries + 1):
        api_result = await text.generate_json(
            config=config,
            model=config.effective_extraction_model(),
            system_prompt=system_prompt,
            user_content=user_content,
            temperature=0.4,
            max_output_tokens=65536,
            feature="extract.story_bible",
        )
        last_usage = api_result.usage
        result = api_result.value
        if isinstance(result, list):
            result = result[0]
        result = _normalize_result(result)

        try:
            return ApiResult(value=StoryBible.model_validate(result), usage=last_usage)
        except ValidationError as e:
            last_error = e
            if attempt < max_retries:
                console.print(f"[yellow]Validation errors (attempt {attempt + 1}), retrying with corrections...[/yellow]")
                # Feed the errors back so the model can fix just the broken fields
                user_content = (
                    f"Your previous response had schema validation errors. "
                    f"Here is the original novel text, followed by your previous JSON output "
                    f"and the specific errors. Please output corrected JSON only.\n\n"
                    f"NOVEL TEXT:\n{novel_text}\n\n"
                    f"YOUR PREVIOUS JSON:\n{json.dumps(result, indent=2)}\n\n"
                    f"VALIDATION ERRORS:\n{e}\n\n"
                    f"Output corrected JSON only, no explanation."
                )
            else:
                raise


    raise last_error  # type: ignore[misc]


def _find_quote_position(text: str, quote: str) -> int:
    """Locate a verbatim scene quote in the novel text.

    Tries progressively shorter prefixes so minor model transcription errors
    (e.g. a misquoted word at the end) don't cause a miss. Returns -1 if
    nothing matches.
    """
    if not quote:
        return -1

    # Normalise smart quotes / dashes the model may have substituted
    def _norm(s: str) -> str:
        return (
            s.replace("\u2018", "'").replace("\u2019", "'")
             .replace("\u201c", '"').replace("\u201d", '"')
             .replace("\u2013", "-").replace("\u2014", "--")
        )

    norm_text = _norm(text)
    norm_quote = _norm(quote)

    for length in (len(norm_quote), 80, 60, 40, 25):
        if length > len(norm_quote):
            continue
        pos = norm_text.find(norm_quote[:length])
        if pos != -1:
            return pos

    return -1


def _write_scene_files(story_bible: StoryBible, novel_text: str, scenes_dir: Path) -> None:
    """Write individual scene text files using verbatim quote anchors.

    For each scene, source_start_quote is searched in the novel text to find
    the exact byte offset. Scenes are sorted by their found position, and each
    scene runs from its anchor to the next scene's anchor (last scene runs to
    end of text).

    Scenes whose quote cannot be found are assigned position -1 and sorted to
    the front — they receive a fallback text block instead of novel prose.
    """
    scenes_dir.mkdir(parents=True, exist_ok=True)

    positions: list[tuple[int, object]] = []
    missing: list = []

    for scene in story_bible.scenes:
        pos = _find_quote_position(novel_text, scene.source_start_quote)
        if pos == -1:
            missing.append(scene)
            console.print(
                f"[yellow]  ⚠ Could not locate quote for {scene.id} "
                f"({scene.title!r}) — will use summary fallback[/yellow]"
            )
        else:
            positions.append((pos, scene))

    positions.sort(key=lambda x: x[0])

    # Write scenes with found positions
    for i, (start, scene) in enumerate(positions):
        end = positions[i + 1][0] if i + 1 < len(positions) else len(novel_text)
        scene_text = novel_text[start:end].strip()
        (scenes_dir / f"{scene.id}.txt").write_text(scene_text)

    # Write fallback files for unlocated scenes
    for scene in missing:
        fallback = f"[Scene: {scene.title}]\n\n{scene.summary}"
        (scenes_dir / f"{scene.id}.txt").write_text(fallback)


async def run(
    config: Config,
    project_dir: Path,
    state: PipelineState,
    on_event: EventCallback | None = None,
) -> StoryBible:
    """Execute Stage 1: Extract Story Bible from the novel."""
    emit = on_event or _NOOP

    begin_stage(state, "extract", total=1)
    emit({"type": "stage_begin", "stage": "extract", "total": 4})
    save_state(state, project_dir)

    try:
        novel_path = Path(state.novel_path)
        if not novel_path.is_absolute():
            novel_path = project_dir / novel_path
        console.print(f"[bold]Reading novel:[/bold] {novel_path}")
        emit({"type": "log", "stage": "extract", "level": "info",
              "message": f"Reading novel: {novel_path}"})
        novel_text = _read_novel(novel_path)
        if isinstance(novel_text, bytes):
            console.print(f"Novel length: {len(novel_text):,} bytes (image-based PDF — using native Gemini processing)")
            emit({"type": "log", "stage": "extract", "level": "dim",
                  "message": f"Novel: image-based PDF, {len(novel_text):,} bytes"})
        else:
            console.print(f"Novel length: {len(novel_text):,} characters (~{len(novel_text) // 4:,} tokens)")
            emit({"type": "log", "stage": "extract", "level": "dim",
                  "message": f"Novel length: {len(novel_text):,} characters"})
        emit({"type": "stage_progress", "stage": "extract", "done": 1, "total": 4})

        system_prompt = PROMPT_PATH.read_text()
        content_for_cost = novel_text if isinstance(novel_text, str) else ""
        estimated = estimate_text_cost(
            config.effective_extraction_model(),
            system_prompt + "\n" + content_for_cost,
            output_chars=65536 * 4,
        )
        state.stages["extract"].estimated_cost_usd = estimated
        emit({"type": "stage_progress", "stage": "extract", "done": 2, "total": 4})

        console.print(f"[bold]Calling {config.effective_extraction_model()}...[/bold]")
        emit({"type": "log", "stage": "extract", "level": "info",
              "message": f"Calling {config.effective_extraction_model()}..."})
        extract_result = await _extract_with_retry(config, system_prompt, novel_text)
        story_bible = extract_result.value
        console.print(
            f"[green]Extracted:[/green] {len(story_bible.characters)} characters, "
            f"{len(story_bible.locations)} locations, {len(story_bible.scenes)} scenes"
        )
        emit({"type": "log", "stage": "extract", "level": "info",
              "message": (f"Extracted: {len(story_bible.characters)} characters, "
                          f"{len(story_bible.locations)} locations, "
                          f"{len(story_bible.scenes)} scenes")})
        emit({"type": "stage_progress", "stage": "extract", "done": 3, "total": 4})

        bible_path = project_dir / "story_bible.json"
        bible_json = story_bible.model_dump_json(indent=2)
        bible_path.write_text(bible_json)
        _write_scene_files(story_bible, novel_text, project_dir / "scenes")

        record_item_done(state, "extract", usage=extract_result.usage)
        emit({"type": "stage_progress", "stage": "extract",
              "done": 4,
              "total": 4})
        complete_stage(state, "extract")
        emit({"type": "stage_complete", "stage": "extract",
              "done": state.stages["extract"].items_done,
              "total": state.stages["extract"].items_total})
        save_state(state, project_dir)

        console.print("[yellow]Stage 1 complete — awaiting review.[/yellow]")
        console.print(f"Review the Story Bible at: {bible_path}")
        console.print("Run [bold]pipeline approve --project . --stage extract[/bold] to continue.")

        return story_bible

    except Exception as e:
        fail_stage(state, "extract", str(e))
        emit({"type": "stage_fail", "stage": "extract", "message": str(e)})
        save_state(state, project_dir)
        raise
