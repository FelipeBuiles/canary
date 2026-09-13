"""Stage 1: Novel → Story Bible JSON.

Reads the full novel and makes one long-context call through the configured
Gemini 3.7 Flash text route to extract characters, locations, scenes, and
narrative arcs.
"""

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients.structured_call import (
    StructuredCallError,
    generate_validated_json,
)
from novel_to_comic.config import Config
from novel_to_comic.input_limits import read_source
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.source_extraction import (
    align_scene_anchors,
    produce_source_document,
)
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.text_utils import clean, has_offscreen_marker
from novel_to_comic.usage import ApiResult, estimate_text_cost, estimate_token_count

console = Console()

PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "extraction.txt"
EXTRACT_MAX_OUTPUT_TOKENS = 65536
ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS = 12000
ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS = 24000

class _CharacterParticipation(BaseModel):
    """Source evidence consumed only at the extraction boundary."""

    model_config = ConfigDict(extra="forbid")
    character_id: str
    scene_id: str
    classification: Literal["direct_action", "staged_recollection", "background_only"]
    source_quote: str = Field(min_length=1)


class _ExtractionParticipation(BaseModel):
    character_participation: list[_CharacterParticipation]



def estimate_story_bible_output_chars(novel_text: str | bytes | int) -> int:
    """Estimate Stage 1 JSON size without reserving the full max-token budget."""
    input_tokens = estimate_token_count(novel_text)
    output_tokens = max(
        ESTIMATED_STORY_BIBLE_MIN_OUTPUT_TOKENS,
        min(ESTIMATED_STORY_BIBLE_MAX_OUTPUT_TOKENS, input_tokens // 8),
    )
    return output_tokens * 4


def _read_novel(novel_path: Path) -> str:
    """Read a source using the same budgets enforced during upload."""
    return read_source(novel_path)


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
        if not tags or tags[0].lower() not in {"1man", "1woman", "1boy", "1girl", "1other"}:
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


def _remove_offscreen_characters(result: dict, excluded_ids: set[str] | None = None) -> dict:
    """Drop excluded visual subjects and clean their roster/relationship references."""
    characters = result.get("characters")
    if not isinstance(characters, list):
        return result

    removed_ids = (excluded_ids or set()) | {
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


def _parse_extraction(raw: object, novel_text: str) -> StoryBible:
    result = raw[0] if isinstance(raw, list) else raw
    participation = _ExtractionParticipation.model_validate(result).character_participation
    # Work on a separate payload so schema-correction feedback retains the evidence.
    result = json.loads(json.dumps(result))
    characters = {character["id"] for character in result.get("characters", [])}
    scenes = {scene["id"]: scene for scene in result.get("scenes", [])}
    classified: set[tuple[str, str]] = set()
    visible: set[tuple[str, str]] = set()
    normalized_source = clean(novel_text)
    for evidence in participation:
        pair = (evidence.character_id, evidence.scene_id)
        if evidence.character_id not in characters or evidence.scene_id not in scenes:
            raise ValueError("Participation evidence must reference existing characters and scenes")
        if pair in classified:
            raise ValueError(f"Duplicate participation evidence: {pair}")
        normalized_quote = clean(evidence.source_quote)
        if not normalized_quote or normalized_quote not in normalized_source:
            raise ValueError(
                f"Participation quote must occur verbatim in the source "
                f"(ignoring whitespace): {pair}"
            )
        classified.add(pair)
        if evidence.classification != "background_only":
            visible.add(pair)
    for scene in scenes.values():
        for character_id in scene["character_ids"]:
            if (character_id, scene["id"]) not in classified:
                raise ValueError(f"Missing participation evidence: {character_id} / {scene['id']}")
        scene["character_ids"] = [
            character_id for character_id in scene["character_ids"]
            if (character_id, scene["id"]) in visible
        ]
    for character_id, scene_id in visible:
        if character_id not in scenes[scene_id]["character_ids"]:
            raise ValueError(f"Staged participant missing from scene roster: {character_id} / {scene_id}")
    if characters - {character_id for character_id, _ in classified}:
        raise ValueError("Every candidate character requires participation evidence")
    excluded = characters - {character_id for character_id, _ in visible}
    result = _remove_offscreen_characters(result, excluded)
    for character in result["characters"]:
        character["first_appearance_scene"] = next(
            scene["id"] for scene in scenes.values()
            if character["id"] in scene["character_ids"]
        )
    result.pop("character_participation", None)
    result = _normalize_result(result)
    for kind in ("characters", "locations", "props"):
        for entity in result.get(kind, []):
            for appearance in entity.get("appearance_states", []):
                if "changed_facets" not in appearance or "replaces_identity" not in appearance:
                    raise ValueError(
                        f"Appearance state {entity['id']} / {appearance['id']} must explicitly "
                        "declare changed_facets and replaces_identity; do not infer empty defaults."
                    )
            positions = set()
            for activation in entity.get("appearance_timeline", []):
                at = activation["at"]
                position = (at["scene_id"], at.get("beat"))
                if position in positions:
                    raise ValueError(
                        f"Conflicting appearance activations for {entity['id']} at {position}; "
                        "use distinct beats or scenes so every state has a visible interval."
                    )
                positions.add(position)
    return StoryBible.model_validate(result)


async def _extract_with_retry(
    config: Config,
    system_prompt: str,
    novel_text: str,
    max_retries: int = 2,
) -> ApiResult[StoryBible]:
    """Call the extraction model, normalize, validate, and retry on schema errors."""

    def parse(raw: object) -> StoryBible:
        bible = _parse_extraction(raw, novel_text)
        aligned = bible.model_copy(deep=True)
        unresolved = align_scene_anchors(aligned, novel_text)
        if unresolved:
            raise ValueError(
                "Story Bible scenes must remain in source-text order and every "
                "source_start_quote must resolve to a monotonically later complete "
                "source sentence. Unresolved scene IDs: "
                + ", ".join(unresolved)
            )
        return aligned

    def correction(raw: object, error: Exception) -> str:
        result = raw[0] if isinstance(raw, list) else raw
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
            parse=parse,
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
    return ApiResult(
        value=outcome.value,
        usage=usage,
        additional_usage=tuple(outcome.usage_records[:-1]),
    )


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
        unresolved = align_scene_anchors(story_bible, novel_text)
        if unresolved:
            # The scene still exists in the Story Bible; only its source
            # boundary is unknown, so its units stay with the preceding scene.
            console.print(
                "[yellow]Scene anchors not found in the source:[/yellow] "
                + ", ".join(unresolved)
            )
            ctx.log(
                f"{len(unresolved)} scene anchor(s) could not be located in the "
                "source text and were merged into the preceding scene: "
                + ", ".join(unresolved),
                level="dim",
            )
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
        produce_source_document(
            TargetArtifacts(project_dir),
            novel_text,
            story_bible,
        )

        for retry_usage in extract_result.additional_usage:
            ctx.record_api_usage(retry_usage)
        ctx.record_item_done(usage=extract_result.usage)
        ctx.progress(4, 4)

        console.print("[green]Extract stage complete — starting Brief next.[/green]")
        ctx.log("Extract stage complete; Brief will start automatically.")

    return story_bible


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    novel_path = Path(state.novel_path)
    if not novel_path.is_absolute():
        novel_path = project_dir / novel_path
    try:
        novel_text = read_source(novel_path)
    except Exception:
        novel_text = ""
    input_payload: str | int = PROMPT_PATH.read_text() + "\n" + novel_text
    return estimate_text_cost(
        config.effective_extraction_model(),
        input_payload,
        output_chars=estimate_story_bible_output_chars(novel_text),
    )


STAGE = Stage(
    name="extract",
    run=run,
    outputs=lambda d: [
        artifacts.story_bible_path(d),
        d / "source" / "source.json",
    ],
    clean_paths=lambda d: [
        artifacts.story_bible_path(d),
        *clean_cascade(d, "source"),
    ],
    estimate_cost=estimate_cost,
)
