"""Stage 1: Novel → Story Bible JSON.

Reads the full novel and makes one long-context call to Gemini 3.1 Pro
to extract characters, locations, scenes, and narrative arcs.
"""

import json
import re
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients.structured_call import (
    StructuredCallError,
    generate_validated_json,
)
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.text_utils import has_offscreen_marker
from novel_to_comic.usage import ApiResult, estimate_text_cost, estimate_token_count

console = Console()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"
EXTRACT_MAX_OUTPUT_TOKENS = 65536
ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS = 12000
ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS = 24000


def estimate_story_bible_output_chars(novel_text: str | bytes | int) -> int:
    """Estimate Stage 1 JSON size without reserving the full max-token budget."""
    input_tokens = estimate_token_count(novel_text)
    output_tokens = max(
        ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS,
        min(ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS, input_tokens // 8),
    )
    return output_tokens * 4


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
    return has_offscreen_marker(f"{text} {features_text}")


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


def _parse_extraction(raw: object) -> StoryBible:
    result = raw[0] if isinstance(raw, list) else raw
    return StoryBible.model_validate(_normalize_result(result))


async def _extract_with_retry(
    config: Config,
    system_prompt: str,
    novel_text: str,
    max_retries: int = 2,
) -> ApiResult[StoryBible]:
    """Call the extraction model, normalize, validate, and retry on schema errors."""

    def correction(raw: object, error: Exception) -> str:
        result = raw[0] if isinstance(raw, list) else raw
        result = _normalize_result(result)
        # Feed the errors back so the model can fix just the broken fields
        return (
            f"Your previous response had schema validation errors. "
            f"Here is the original novel text, followed by your previous JSON output "
            f"and the specific errors. Please output corrected JSON only.\n\n"
            f"NOVEL TEXT:\n{novel_text}\n\n"
            f"YOUR PREVIOUS JSON:\n{json.dumps(result, indent=2)}\n\n"
            f"VALIDATION ERRORS:\n{error}\n\n"
            f"Output corrected JSON only, no explanation."
        )

    try:
        outcome = await generate_validated_json(
            config,
            model=config.effective_extraction_model(),
            system_prompt=system_prompt,
            user_content=novel_text,
            parse=_parse_extraction,
            correction=correction,
            label="Story Bible extraction",
            feature="extract.story_bible",
            max_output_tokens=EXTRACT_MAX_OUTPUT_TOKENS,
            retries=max_retries,
            temperatures=(0.4,),
        )
    except StructuredCallError as exc:
        raise exc.last_error from exc

    usage = outcome.usage_records[-1] if outcome.usage_records else None
    return ApiResult(value=outcome.value, usage=usage)


def _norm_quote_text(s: str) -> str:
    """Normalise smart quotes / dashes the model may have substituted."""
    return (
        s.replace("\u2018", "'").replace("\u2019", "'")
         .replace("\u201c", '"').replace("\u201d", '"')
         .replace("\u2013", "-").replace("\u2014", "--")
    )


def _fuzzy_find_quote(norm_text: str, norm_quote: str, start: int = 0) -> int:
    """Fuzzy-locate a quote whose exact prefix never matches.

    Anchors candidate windows on individual words of the quote, then scores
    each window with SequenceMatcher. Only a strong match (>0.85) is accepted
    so a wrong-but-similar passage doesn't mis-anchor the scene.
    """
    from difflib import SequenceMatcher

    probe = norm_quote[:60].lower()
    if len(probe) < 20:
        return -1
    text_lower = norm_text.lower()
    words = [w.strip("\"'.,;:!?") for w in probe.split()]
    words = [w for w in words if len(w) >= 4]
    if not words:
        return -1

    seen: set[int] = set()
    best_pos = -1
    best_ratio = 0.85
    for word in words[:6]:
        offset = probe.find(word)
        idx = text_lower.find(word, start)
        hops = 0
        while idx != -1 and hops < 500:
            window_start = idx - offset
            if window_start >= start and window_start not in seen:
                seen.add(window_start)
                window = text_lower[window_start:window_start + len(probe)]
                ratio = SequenceMatcher(None, probe, window).ratio()
                if ratio > best_ratio or (
                    ratio == best_ratio and best_pos != -1 and window_start < best_pos
                ):
                    best_pos = window_start
                    best_ratio = ratio
            hops += 1
            idx = text_lower.find(word, idx + 1)
    return best_pos


def _find_quote_position(text: str, quote: str, start: int = 0) -> int:
    """Locate a verbatim scene quote in the novel text at or after ``start``.

    Tries progressively shorter prefixes so minor model transcription errors
    (e.g. a misquoted word at the end) don't cause a miss, then falls back to
    a fuzzy word-anchored search. Searching from ``start`` keeps anchors
    monotonic: a short prefix like "The next morning" can't match an earlier
    occurrence and silently reorder scenes. Returns -1 if nothing matches.
    """
    if not quote:
        return -1

    norm_text = _norm_quote_text(text)
    norm_quote = _norm_quote_text(quote)

    for length in (len(norm_quote), 80, 60, 40, 25):
        if length > len(norm_quote):
            continue
        pos = norm_text.find(norm_quote[:length], start)
        if pos != -1:
            return pos

    return _fuzzy_find_quote(norm_text, norm_quote, start)


_SENTENCE_CLOSERS = {'"', "'", "\u2019", "\u201d", ")", "]"}
_PERIOD_ABBREVIATIONS = {
    "dr", "jr", "mr", "mrs", "ms", "prof", "sr", "st", "vs",
}


def _sentence_end_after(text: str, start: int) -> int | None:
    """Return the end of the first sentence ending at or after ``start``.

    The model-provided quote is only an anchor. Walking the source text makes
    the excerpt shown in the Story room deterministic and prevents a fixed
    character limit from leaving a dangling half-phrase.
    """
    for match in re.finditer(r"[.!?]", text[start:]):
        punctuation = start + match.start()
        mark = text[punctuation]

        if mark == ".":
            if punctuation > 0 and punctuation + 1 < len(text):
                if text[punctuation - 1].isdigit() and text[punctuation + 1].isdigit():
                    continue
            word_match = re.search(r"([A-Za-z]+)$", text[:punctuation])
            if word_match and word_match.group(1).lower() in _PERIOD_ABBREVIATIONS:
                continue

        end = punctuation + 1
        while end < len(text) and text[end] in _SENTENCE_CLOSERS:
            end += 1

        following = text[end:].lstrip()
        if not following or following[0].isupper() or following[0].isdigit():
            return end

    return None


def _complete_source_start_quotes(story_bible: StoryBible, novel_text: str) -> None:
    """Extend each scene's source anchor through its opening sentence.

    ``source_start_quote`` remains verbatim source text and continues to serve
    as the scene-boundary anchor. This post-processing repairs both older
    fixed-length model output and occasional future model truncation.
    """
    search_from = 0
    for scene in story_bible.scenes:
        quote = scene.source_start_quote.strip()
        if not quote:
            continue

        position = novel_text.find(quote, search_from)
        if position == -1:
            position = _find_quote_position(novel_text, quote, start=search_from)
        if position == -1:
            continue

        if not re.search(r"[.!?][\"'\u2019\u201d)\]]*$", quote):
            quote_end = position + len(quote)
            sentence_end = _sentence_end_after(novel_text, quote_end)
            if sentence_end is not None:
                scene.source_start_quote = novel_text[position:sentence_end].strip()
        search_from = position + 1


def _write_scene_files(story_bible: StoryBible, novel_text: str, scenes_dir: Path) -> None:
    """Write individual scene text files using verbatim quote anchors.

    For each scene, source_start_quote is searched in the novel text to find
    the exact byte offset. Scenes are sorted by their found position, and each
    scene runs from its anchor to the next scene's anchor (last scene runs to
    end of text).

    Anchors are resolved monotonically: each scene's quote is searched at or
    after the previous scene's anchor, so a short or repeated opening phrase
    cannot match an earlier passage and silently reorder scene boundaries.
    A quote found only *before* the previous anchor indicates extraction
    disorder and is treated as missing (with a loud warning).

    Scenes whose quote cannot be found receive a fallback text block instead
    of novel prose.
    """
    scenes_dir.mkdir(parents=True, exist_ok=True)

    positions: list[tuple[int, object]] = []
    missing: list = []
    search_from = 0

    for scene in story_bible.scenes:
        pos = _find_quote_position(novel_text, scene.source_start_quote, start=search_from)
        if pos == -1 and search_from > 0:
            # Diagnose: does the quote exist earlier in the text? That means
            # the bible's scene order disagrees with the novel — surface it.
            earlier = _find_quote_position(novel_text, scene.source_start_quote)
            if earlier != -1:
                console.print(
                    f"[yellow]  ⚠ Quote for {scene.id} ({scene.title!r}) only matches "
                    f"BEFORE the previous scene's anchor — scene order may be wrong. "
                    f"Using summary fallback.[/yellow]"
                )
                missing.append(scene)
                continue
        if pos == -1:
            missing.append(scene)
            console.print(
                f"[yellow]  ⚠ Could not locate quote for {scene.id} "
                f"({scene.title!r}) — will use summary fallback[/yellow]"
            )
        else:
            positions.append((pos, scene))
            search_from = pos + 1

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


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> StoryBible:
    """Execute Stage 1: Extract Story Bible from the novel."""
    with ctx.execute(total=4):
        novel_path = Path(ctx.state.novel_path)
        if not novel_path.is_absolute():
            novel_path = project_dir / novel_path
        console.print(f"[bold]Reading novel:[/bold] {novel_path}")
        # SSE logs are rendered directly in the production UI. Keep the
        # resolved path in server diagnostics above, but never expose the
        # host machine's filesystem layout to the user.
        ctx.log("Reading source text...")
        novel_text = _read_novel(novel_path)
        if isinstance(novel_text, bytes):
            raise ValueError(
                "Image-based (scanned) PDFs are not supported. The LiteLLM gateway does not "
                "support raw PDF bytes. Use a text-based PDF, EPUB, or plain text file, or add "
                "OCR preprocessing before running Stage 1."
            )
        else:
            console.print(f"Novel length: {len(novel_text):,} characters (~{len(novel_text) // 4:,} tokens)")
            ctx.log(f"Novel length: {len(novel_text):,} characters", level="dim")
        ctx.progress(1, 4)

        system_prompt = PROMPT_PATH.read_text()
        content_for_cost = novel_text if isinstance(novel_text, str) else ""
        estimated = estimate_text_cost(
            config.effective_extraction_model(),
            system_prompt + "\n" + content_for_cost,
            output_chars=estimate_story_bible_output_chars(content_for_cost),
        )
        ctx.set_estimated_cost(estimated)
        ctx.progress(2, 4)

        console.print(f"[bold]Calling {config.effective_extraction_model()}...[/bold]")
        ctx.log(f"Calling {config.effective_extraction_model()}...")
        extract_result = await _extract_with_retry(config, system_prompt, novel_text)
        story_bible = extract_result.value
        _complete_source_start_quotes(story_bible, novel_text)
        console.print(
            f"[green]Extracted:[/green] {len(story_bible.characters)} characters, "
            f"{len(story_bible.locations)} locations, {len(story_bible.scenes)} scenes"
        )
        ctx.log(
            f"Extracted: {len(story_bible.characters)} characters, "
            f"{len(story_bible.locations)} locations, "
            f"{len(story_bible.scenes)} scenes"
        )
        ctx.stage_state.items_done = 3
        ctx.save()
        ctx.progress(3, 4)

        artifacts.write_story_bible(project_dir, story_bible)
        _write_scene_files(story_bible, novel_text, project_dir / "scenes")

        ctx.record_item_done(usage=extract_result.usage)
        ctx.progress(4, 4)

        console.print("[yellow]Extract stage complete — awaiting review.[/yellow]")
        console.print(f"Review the Story Bible at: {artifacts.story_bible_path(project_dir)}")
        console.print("Run [bold]pipeline approve --project . --stage extract[/bold] to continue.")

    return story_bible


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    novel_path = Path(state.novel_path)
    if not novel_path.is_absolute():
        novel_path = project_dir / novel_path
    try:
        raw = novel_path.read_bytes()
    except Exception:
        raw = b""
    try:
        novel_text = raw.decode("utf-8")
        input_payload: str | int = PROMPT_PATH.read_text() + "\n" + novel_text
    except UnicodeDecodeError:
        novel_text = ""
        input_payload = len(raw)
    return estimate_text_cost(
        config.effective_extraction_model(),
        input_payload,
        output_chars=estimate_story_bible_output_chars(novel_text or len(raw)),
    )


STAGE = Stage(
    name="extract",
    run=run,
    outputs=lambda d: [artifacts.story_bible_path(d)],
    # Style samples survive a re-extract (cascade starts at "refs"), so the
    # user's selected style isn't lost when the bible is regenerated.
    clean_paths=lambda d: [
        artifacts.story_bible_path(d),
        d / "scenes",
        *clean_cascade(d, "refs"),
    ],
    estimate_cost=estimate_cost,
)
