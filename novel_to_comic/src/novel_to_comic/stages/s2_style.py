"""Stage 2: Generate visual style options for review.

Produces five distinct style templates (text descriptions) and one sample
image per style, then enters awaiting_review so the user can preview the
samples and pick an active style before downstream stages run.
"""

import asyncio
import hashlib
import json
import logging
import re
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.clients import flux, text as text_client
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompt_assembly import normalize_prose_brief
from novel_to_comic.prompting import build_style_sample_prompt
from novel_to_comic.stage_runtime import StageRuntime

logger = logging.getLogger(__name__)

SAMPLE_COUNT = 5
LLM_REQUEST_COUNT = 8  # ask for more than we need so dedup still yields >= 5
SAMPLE_CONCURRENCY = 2
_GENERATION_MAX_ATTEMPTS = 2

_SYSTEM_PROMPT = (
    "You are a visual art director for adapted fiction. Surface 8 genuinely distinctive "
    "visual styles a comic adaptation of this story could take.\n\n"

    "Work in THREE passes:\n\n"

    "1) BRAINSTORM (silently). List 30-40 candidate visual approaches by populating "
    "EVERY one of these six dimensions at least 4 times. Be exhaustive — push past "
    "the obvious first ten ideas:\n"
    "- MEDIUM: oil, watercolor, gouache, acrylic, pastel, charcoal, pencil, ink, digital "
    "paint, vector art, collage, screen print, lithography, woodblock, etching, "
    "photography, stained glass, mosaic, textile, mixed media, clay, wax, origami, "
    "scratchboard, sumi-e, cyanotype, papier-mâché, diorama, batik, calligraphy\n"
    "- ERA: pre-1800s, 1800s, 1900-1940, 1940-1970, 1970-1995, 1995-present\n"
    "- REGION: East Asian, South Asian, Middle Eastern, European, North American, Latin "
    "American, African, Oceanian, Indigenous\n"
    "- COLOR: monochrome, limited palette (2-4 colors), full naturalistic, neon/synthetic, "
    "pastel, earth-tones, metallic, high-key, low-key/chiaroscuro, sepia, blacklight-reactive\n"
    "- MARK-MAKING: line art, stippling, cross-hatching, wash/bleed, flat/block color, "
    "painterly brushwork, textured/dry brush, airbrush, digital clean, pixel art, "
    "scratchboard scraping, collage tearing, wax resist, impasto, wood grain\n"
    "- VISUAL LOGIC: photorealistic, representational, stylized, abstract/non-objective, "
    "symbolic/iconographic, decorative/ornamental, documentary/journalistic, "
    "diagrammatic/scientific, naive/folk, grotesque/caricature\n\n"

    "2) CURATE (silently). From your brainstorm, pick 8 candidates that are MAXIMALLY "
    "DISTINCT. Hard constraints:\n"
    "- No two suggestions may share the same primary medium. If one uses an etching, "
    "no other may use any printmaking technique (etching, engraving, lithography, "
    "woodblock, screen print). If one uses photography, no other may use a lens-based "
    "medium. If one uses clay/sculpture, no other may use any 3d medium.\n"
    "- The 8 must collectively span at least 5 of the 6 dimensions.\n"
    "- At least 4 must match the story's mood; at least 1 must productively contradict it.\n\n"

    "3) WRITE. Every template must name at least one real anchor: a specific artist, "
    "illustrator, magazine, studio, film, decade, movement, region, or publication. "
    "Avoid abstract descriptors like \"moody painterly.\"\n\n"

    "VARY YOUR PROSE: never start two templates with the same verb. Avoid crutch verbs "
    "(\"Channel,\" \"Adopt,\" \"Embrace,\" \"Utilize,\" \"Employ,\" \"Borrow\") — if you "
    "use one at all, use it at most once.\n\n"

    "Each template: 40-70 words of vivid, specific visual direction. Describe a general "
    "visual aesthetic only — do not reference characters, locations, or plot from the "
    "story; those get combined in later.\n\n"

    "For each suggestion also declare its primary medium: the dominant physical or "
    "digital medium in 1-3 lowercase words (e.g. \"woodblock print\", \"gouache\", "
    "\"cut-paper collage\", \"35mm photography\"). This is the field your curation "
    "constraint is checked against, so name the medium honestly and specifically.\n\n"

    "Output JSON array only, no markdown: "
    '[{"label": "Style Name (2-4 words)", "medium": "primary medium, 1-3 words", '
    '"template": "40-70 word description"}, ...]'
)


# ---------------------------------------------------------------------------
# Suggestion diversity
# ---------------------------------------------------------------------------
#
# Diversity is enforced upstream in _SYSTEM_PROMPT: the LLM brainstorms across
# six dimensions, curates maximally-distinct candidates, and declares each
# suggestion's primary medium in its output. The code below is only a thin
# safety net that drops suggestions whose declared medium repeats one already
# in the pool. (This replaced ~280 lines of hand-maintained technique-keyword
# tables and Jaccard token-overlap scoring — bag-of-words overlap misjudges
# visual similarity in both directions.)


def _medium_tokens(value: str) -> frozenset[str]:
    """Normalise a declared medium into a comparable token set."""
    return frozenset(re.sub(r"[^a-z0-9]+", " ", (value or "").lower()).split())


def _mediums_collide(a: frozenset[str], b: frozenset[str]) -> bool:
    """True when one declared medium equals or refines the other
    ("etching" vs "copper etching")."""
    if not a or not b:
        return False
    return a <= b or b <= a


def _dedupe_suggestions(
    new_suggestions: list[dict],
    existing_suggestions: list[dict] | None = None,
) -> list[dict]:
    """Drop malformed suggestions and ones whose declared primary medium
    repeats an existing or already-kept suggestion's."""
    prior = [_medium_tokens(s.get("medium", "")) for s in (existing_suggestions or [])]
    kept: list[dict] = []
    for s in new_suggestions:
        if not (s.get("template") or "").strip():
            continue
        tokens = _medium_tokens(s.get("medium", ""))
        if any(_mediums_collide(tokens, p) for p in prior):
            continue
        kept.append(s)
        prior.append(tokens)
    return kept


def _build_avoid_block(pool: list[dict]) -> str:
    if not pool:
        return ""
    mediums = sorted({m for s in pool if (m := (s.get("medium") or "").strip().lower())})
    medium_line = (
        "Primary mediums already used — none of your suggestions may use these or a "
        "close relative: " + ", ".join(mediums) + ".\n\n"
        if mediums
        else ""
    )
    summaries = [f'"{s.get("label", "Unknown")}": {s.get("template", "")}' for s in pool]
    return (
        f"\n\nCRITICAL: The following {len(pool)} styles have ALREADY been "
        f"suggested for this story. You MUST explore completely different visual "
        f"territories.\n\n"
        + medium_line
        + "\n\n---\n\n".join(summaries)
        + "\n\n---\n\n"
        + "Remember: choose styles that are MAXIMALLY DISTINCT from all of the above."
    )


async def generate_suggestions(
    config: Config,
    story_bible: StoryBible,
    *,
    existing_suggestions: list[dict] | None = None,
):
    """Generate style suggestions via LLM. Returns (suggestions_list, usage).

    When *existing_suggestions* is supplied the LLM prompt is seeded with the
    template text and declared primary medium of every prior suggestion so it
    can deliberately avoid overlapping visual territory; a thin declared-medium
    filter then drops any remaining repeats.

    The LLM is asked for more suggestions than we need (``LLM_REQUEST_COUNT``)
    so that dedup can still yield at least ``SAMPLE_COUNT``.  If the first
    attempt falls short a second attempt is made with the existing-pool
    expanded to steer the LLM further away.
    """
    first_usage = None

    async def _call_llm(avoid_pool: list[dict]) -> list[dict]:
        nonlocal first_usage
        system = (
            _SYSTEM_PROMPT
            + _build_avoid_block(avoid_pool)
            + config.generation_language_instruction()
        )
        user = (
            f'Story: "{story_bible.title}" by {story_bible.author}\n'
            f"Style notes: {story_bible.style_notes or 'none'}\n"
            f"Genre/tone: {', '.join({s.scene_type for s in story_bible.scenes})}\n\n"
            f"Generate {LLM_REQUEST_COUNT} style options for this story."
        )

        api_result = await text_client.generate_json(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=system,
            user_content=user,
            temperature=1.0,
            feature="style.suggestions",
        )
        if first_usage is None:
            first_usage = api_result.usage

        result = api_result.value
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("styles", [])
        return []

    # --- first attempt -------------------------------------------------------
    pool = existing_suggestions or []
    suggestions = _dedupe_suggestions(await _call_llm(pool), pool)

    # --- retry if dedup left us with fewer than SAMPLE_COUNT -----------------
    for _attempt in range(1, _GENERATION_MAX_ATTEMPTS):
        if len(suggestions) >= SAMPLE_COUNT:
            break
        # Expand the avoid-pool with the *unused* suggestions from the first
        # pass so the retry gets an even stronger steer.
        retry_pool = pool + suggestions
        suggestions.extend(_dedupe_suggestions(await _call_llm(retry_pool), retry_pool))

    return suggestions[:SAMPLE_COUNT], first_usage


# ---------------------------------------------------------------------------
# Style-sample brief
# ---------------------------------------------------------------------------
#
# The proof images for every candidate style share one subject/setting brief
# so styles are compared on identical content. An LLM picks the most
# style-revealing character/location pairing from the story bible and writes
# it as flowing prose, cached on disk per project; when the pass is disabled
# or fails, build_style_sample_prompt falls back to a deterministic body.

STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT = (
    "You write the subject brief for a style proof image: one image used to judge "
    "candidate art styles for a comic adaptation of a novel. You receive the story's "
    "main characters and locations.\n"
    "\n"
    "First pick the one character and one location that together reveal the most "
    "about a visual style: a face and figure that show how people render, an "
    "environment with depth and material variety, and a lighting situation that "
    "spans bright accents and deep shadow.\n"
    "\n"
    "Then write that moment as a single flowing brief of 60-120 words, the way a "
    "film director describes one frozen frame:\n"
    "- Introduce the character with their full physical description (age, build, "
    "hair, face, wardrobe) before their action.\n"
    "- Keep the figure the clear focal point at three-quarter or full length, with "
    "the location giving depth behind them; compose for a portrait frame.\n"
    "- Give light its own concrete sentence: direction, color, quality, and where "
    "the shadows fall.\n"
    "- Exactly one frozen instant and a quiet, characteristic action — no climactic "
    "story beat.\n"
    "- Never mention art style, medium, or rendering technique: the same brief is "
    "rendered in several candidate styles and must not favor any of them.\n"
    "- Plain declarative prose only: no headings, labels, bullet points, markdown, "
    "or meta-commentary.\n"
    "\n"
    "Output only the brief text."
)


def _style_sample_brief_source(story_bible: StoryBible) -> str:
    """Compact character/location roster the brief LLM picks its subject from."""
    lines = [f'Story: "{story_bible.title}" by {story_bible.author}']
    if story_bible.style_notes:
        lines.append(f"Story notes: {story_bible.style_notes}")
    if story_bible.characters:
        lines.append("Characters:")
        for char in story_bible.characters[:6]:
            traits = ", ".join(t for t in (char.age_range, char.gender) if t)
            suffix = f" ({traits})" if traits else ""
            lines.append(f"- {char.name}{suffix}: {char.visual_anchor or char.name}")
    if story_bible.locations:
        lines.append("Locations:")
        for loc in story_bible.locations[:6]:
            mood = f" (mood: {loc.mood})" if loc.mood else ""
            lines.append(f"- {loc.name}{mood}: {loc.visual_anchor or loc.name}")
    return "\n".join(lines)


async def generate_style_sample_brief(
    config: Config, story_bible: StoryBible,
) -> str | None:
    """One LLM call: story-bible roster → shared prose brief for style samples.

    Returns None (never raises) when the call fails or the output fails
    validation — callers fall back to the deterministic sample body.
    """
    source = _style_sample_brief_source(story_bible)
    try:
        result = await text_client.generate_text(
            config=config,
            model=config.effective_prompt_model(),
            system_prompt=STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT,
            user_content=source,
            temperature=0.4,
            max_output_tokens=300,
            feature="style.sample_brief",
        )
    except Exception:
        logger.warning(
            "Style sample brief generation failed; falling back to deterministic body",
            exc_info=True,
        )
        return None
    brief = normalize_prose_brief(result.value)
    if brief is None:
        logger.warning(
            "Style sample brief output rejected (malformed or out of bounds); "
            "falling back to deterministic body"
        )
    return brief


async def ensure_style_sample_brief(
    config: Config, story_bible: StoryBible, project_dir: Path,
) -> str | None:
    """Return the project's shared sample brief, generating and caching it on
    first use so every candidate style renders the identical scene.

    Returns None when the pass is disabled or generation fails.
    """
    if not getattr(config, "style_sample_brief_enabled", True):
        return None
    source_key = hashlib.sha256(
        _style_sample_brief_source(story_bible).encode("utf-8")
    ).hexdigest()
    path = artifacts.style_sample_brief_path(project_dir)
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except Exception:
            data = {}
        if data.get("source_sha256") == source_key and (data.get("brief") or "").strip():
            return data["brief"]
    brief = await generate_style_sample_brief(config, story_bible)
    if not brief:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {
            "version": 1,
            "kind": "style_sample_brief",
            "source_sha256": source_key,
            "brief": brief,
        },
        indent=2,
        sort_keys=True,
    ))
    return brief


def _sample_meta_path(sample_path: Path) -> Path:
    return sample_path.with_suffix(f"{sample_path.suffix}.meta.json")


def _sample_meta(config: Config, prompt: str) -> dict:
    return {
        "version": 1,
        "kind": "style_sample",
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "parameters": {
            "image_model": config.effective_image_model(),
            "width": config.image_width,
            "height": config.image_height,
            "steps": config.effective_image_steps(),
            "guidance_scale": config.flux_guidance_scale,
            "style_template": config.style_template,
        },
    }


async def generate_sample_image(
    config: Config,
    bible: StoryBible,
    sample_path: Path,
    *,
    brief: str | None = None,
):
    """Generate one style sample image at sample_path. Returns ApiResult.

    *brief* is the shared prose body from ``ensure_style_sample_brief``;
    when None the prompt falls back to its deterministic body.
    """
    prompt = build_style_sample_prompt(config, bible, brief=brief)
    meta = _sample_meta(config, prompt)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    result = await flux.generate_image(
        config=config,
        prompt=prompt,
        output_path=sample_path,
        feature="style.sample",
    )
    _sample_meta_path(sample_path).write_text(json.dumps(meta, indent=2, sort_keys=True))
    return result


def load_suggestions(project_dir: Path) -> list[dict]:
    """Read the suggestions list from disk, or return [] if missing."""
    path = artifacts.style_suggestions_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, dict):
        return data.get("suggestions", []) or []
    if isinstance(data, list):
        return data
    return []


def save_suggestions(project_dir: Path, suggestions: list[dict], title: str) -> None:
    path = artifacts.style_suggestions_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"title": title, "suggestions": suggestions}, indent=2))


def missing_sample_indices(project_dir: Path, suggestions: list[dict]) -> list[int]:
    """Return 1-indexed positions of suggestions that don't have a sample image."""
    return [
        idx
        for idx in range(1, len(suggestions) + 1)
        if not artifacts.style_sample_path(project_dir, idx).exists()
    ]


async def generate_samples_for_indices(
    config: Config,
    bible: StoryBible,
    project_dir: Path,
    suggestions: list[dict],
    indices: list[int],
    *,
    on_sample_done=None,
    concurrency: int = SAMPLE_CONCURRENCY,
) -> None:
    """Generate sample images for the given 1-indexed suggestions in parallel.

    The shared sample brief is resolved once up front so every sample in the
    batch renders the identical scene. `on_sample_done(idx, ApiResult)` is
    awaited after each sample finishes — callers use it to record per-item
    progress and persist incremental state.
    """
    brief = await ensure_style_sample_brief(config, bible, project_dir)
    sem = asyncio.Semaphore(concurrency)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)
        async with sem:
            result = await generate_sample_image(
                sample_config, bible, sample_path, brief=brief,
            )
        if on_sample_done is not None:
            await on_sample_done(idx, result)

    await asyncio.gather(*[_one(i) for i in indices])


async def run(config: Config, project_dir: Path, ctx: StageRuntime) -> None:
    """Execute Stage 2: 5 style suggestions + 5 sample images."""
    bible = artifacts.read_story_bible(project_dir)
    existing_suggestions = load_suggestions(project_dir)
    needs_suggestions = not existing_suggestions
    pending_sample_indices = (
        list(range(1, SAMPLE_COUNT + 1))
        if needs_suggestions
        else missing_sample_indices(project_dir, existing_suggestions)
    )
    total = (1 if needs_suggestions else 0) + len(pending_sample_indices)

    with ctx.execute(total=total):
        if needs_suggestions:
            suggestions, usage = await generate_suggestions(config, bible)
            if usage:
                ctx.record_api_usage(usage)
            save_suggestions(project_dir, suggestions, bible.title)
            ctx.record_item_done()
            ctx.log(f"Generated {len(suggestions)} style suggestions.")
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
            ctx.save()
            pending_sample_indices = list(range(1, len(suggestions) + 1))
        else:
            suggestions = existing_suggestions
            ctx.log("Style suggestions already exist — generating missing samples.", level="dim")

        async def _record(_idx: int, result) -> None:
            if result.usage:
                ctx.record_item_done(usage=result.usage)
            else:
                ctx.record_item_done()
            ctx.save()
            ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)

        if pending_sample_indices:
            await generate_samples_for_indices(
                config,
                bible,
                project_dir,
                suggestions,
                pending_sample_indices,
                on_sample_done=_record,
            )


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_text_cost, estimate_image_cost

    suggestions = load_suggestions(project_dir)
    needs_suggestions = not suggestions
    if needs_suggestions:
        story_bible_text = ""
        sb_path = artifacts.story_bible_path(project_dir)
        if sb_path.exists():
            try:
                story_bible_text = sb_path.read_text()[:3000]
            except Exception:
                pass
        text_cost = estimate_text_cost(
            config.effective_prompt_model(),
            story_bible_text,
        )
        sample_count = SAMPLE_COUNT
    else:
        text_cost = 0.0
        sample_count = len(missing_sample_indices(project_dir, suggestions))

    image_cost = estimate_image_cost(
        config.effective_image_model(),
        sample_count,
        quality=getattr(config, "image_quality", None),
    )
    return text_cost + image_cost


def estimate_style_batch_cost_usd(config: Config, project_dir: Path) -> float:
    """Estimate provider cost for one 'Suggest More Styles' batch (text + samples)."""
    from novel_to_comic.usage import estimate_text_cost, estimate_image_cost

    story_bible_text = ""
    sb_path = artifacts.story_bible_path(project_dir)
    if sb_path.exists():
        try:
            story_bible_text = sb_path.read_text()[:3000]
        except Exception:
            pass

    text_cost = estimate_text_cost(
        config.effective_prompt_model(),
        story_bible_text,
    )
    image_cost = estimate_image_cost(
        config.effective_image_model(),
        SAMPLE_COUNT,
        quality=getattr(config, "image_quality", None),
    )
    return text_cost + image_cost


STAGE = Stage(
    name="style",
    run=run,
    outputs=lambda d: [artifacts.style_suggestions_path(d)],
    clean_paths=lambda d: clean_cascade(d, "samples"),
    estimate_cost=estimate_cost,
)
