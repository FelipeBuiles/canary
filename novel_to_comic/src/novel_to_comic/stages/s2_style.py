"""Stage 2: Generate visual style options for review.

Produces five distinct style templates (text descriptions) and one sample
image per style, then enters awaiting_review so the user can preview the
samples and pick an active style before downstream stages run.
"""

import asyncio
import hashlib
import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic.clients import flux, text as text_client
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.prompting import build_style_sample_prompt
from novel_to_comic.stage_runtime import StageRuntime

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

    "Output JSON array only, no markdown: "
    '[{"label": "Style Name (2-4 words)", "template": "40-70 word description"}, ...]'
)


# ---------------------------------------------------------------------------
# Visual-overlap deduplication
# ---------------------------------------------------------------------------

# Visual-technique keywords used to detect sibling suggestions that are
# visually too similar to existing or other-new suggestions.  The set
# concentrates on medium, mark-making technique, and colour approach so
# that "Victorian engraving" and "Tudor etching" are recognised as
# overlapping even though their labels differ.
# Printmaking keywords are also listed in _TOKEN_FAMILY and get collapsed
# into a single "printmaking" token so siblings like "etching", "engraving"
# and "woodblock" are recognised as the same visual family.
_TECHNIQUE_KEYWORDS: set[str] = {
    # ── printmaking (relief / intaglio / planographic) ──────────────────
    "cross-hatching", "cross-hatched", "hatching", "stippling", "stipple",
    "woodblock", "woodcut", "copperplate", "etching", "engraving", "engraved",
    "lithography", "lithograph", "screen print", "silkscreen", "letterpress",
    "monotype", "linocut", "linoleum", "printmaking",
    "drypoint", "aquatint", "mezzotint", "relief print",
    # ── ink-based drawing / illustration ────────────────────────────────
    "ink", "ink wash", "pen and ink", "fountain pen", "ballpoint",
    "marker", "felt tip", "fineliner", "dip pen", "brush pen", "sumi-e",
    # ── dry drawing ──────────────────────────────────────────────────────
    "pencil", "graphite", "charcoal", "pastel", "chalk", "crayon", "conte",
    "colored pencil", "carbon", "sanguine", "silverpoint", "carbon pencil",
    # ── wet paint ────────────────────────────────────────────────────────
    "oil paint", "oil", "watercolor", "gouache", "acrylic", "tempera",
    "encaustic", "casein", "poster paint",
    "brushwork", "brush", "dry brush", "impasto", "glaze", "scumble",
    # ── collage / assemblage ─────────────────────────────────────────────
    "collage", "photomontage", "decoupage", "assemblage",
    "cut paper", "mixed media", "frottage",
    # ── digital ──────────────────────────────────────────────────────────
    "digital", "vector", "pixel art", "voxel", "3d render", "cg", "cgi",
    "ray tracing", "raytraced", "procedural", "generative",
    "glitch", "glitch art", "databending", "fractal",
    # ── lens-based ───────────────────────────────────────────────────────
    "photography", "film still", "cinematography",
    "daguerreotype", "cyanotype", "tintype", "polaroid",
    "pinhole", "photomicrography", "ambrotype",
    # ── airbrush / spray / mural ─────────────────────────────────────────
    "airbrush", "spray paint", "aerosol",
    "graffiti", "mural", "fresco", "stencil", "wheatpaste",
    # ── textile / fibre craft ────────────────────────────────────────────
    "stained glass", "mosaic", "tapestry", "textile", "embroidery",
    "needlepoint", "cross-stitch", "weaving", "knitting", "crochet",
    "lace", "appliqué", "quilting", "patchwork", "batik",
    # ── 3d / sculptural (photographed) ───────────────────────────────────
    "bas-relief", "clay", "terracotta", "plaster", "bronze", "marble",
    "wax", "diorama", "shadow puppet", "stop motion", "claymation",
    "papier-mâché", "papier mache",
    # ── paper craft ──────────────────────────────────────────────────────
    "origami", "kirigami", "paper cut", "silhouette", "pop-up",
    "scherenschnitte", "papel picado",
    # ── illuminated / manuscript ─────────────────────────────────────────
    "illuminated manuscript", "gold leaf", "gilding", "vellum", "parchment",
    "calligraphy", "book of hours",
    # ── signage / display graphics ───────────────────────────────────────
    "neon sign", "billboard", "hand-painted sign", "marquee", "carnival",
    "fairground", "circus poster", "travel poster",
    # ── scientific / documentary / technical ─────────────────────────────
    "blueprint", "x-ray", "infrared", "thermal imaging",
    "anatomical diagram", "scientific illustration", "botanical plate",
    "field journal", "topographical", "cartography", "map",
    "photogram",
    # ── colour / mood descriptors ────────────────────────────────────────
    "monochrome", "monochromatic", "limited palette", "grayscale", "greyscale",
    "black-and-white", "black and white", "chiaroscuro",
    "neon", "synthetic", "fluorescent", "day-glo", "dayglo",
    "phosphorescent", "blacklight", "ultraviolet", "uv-reactive",
    "earth-tones", "earth tones", "ochre", "sepia", "umber",
    "pastel", "vibrant", "saturated", "desaturated", "muted",
    "high-key", "low-key", "high contrast",
    # ── surface / substrate ──────────────────────────────────────────────
    "canvas", "wood panel", "board", "paper", "rice paper", "washi",
    "mulberry paper", "handmade paper", "newsprint", "kraft paper",
    "acetate", "mylar", "glass", "metal", "copper", "aluminium",
    "scratchboard", "scratch board",
}

# Maps individual keywords to canonical family names.  Only categories where
# all members are visually interchangeable are collapsed — e.g. "etching" and
# "engraving" both → "printmaking".  Wet-media keywords ("oil paint",
# "watercolor", "gouache") are kept distinct because they produce visually
# different results.  A keyword that does not appear here is kept as-is.
_TOKEN_FAMILY: dict[str, str] = {
    # printmaking — structurally-unique print terms only.
    # Mark-making keywords like “cross-hatching”, “stippling” are NOT
    # included here because they appear across media (ink, pencil,
    # ballpoint, etc.) and would cause false siblings.
    "woodblock": "printmaking", "woodcut": "printmaking",
    "copperplate": "printmaking",
    "etching": "printmaking", "engraving": "printmaking", "engraved": "printmaking",
    "lithography": "printmaking", "lithograph": "printmaking",
    "screen print": "printmaking", "silkscreen": "printmaking",
    "letterpress": "printmaking",
    "monotype": "printmaking", "linocut": "printmaking", "linoleum": "printmaking",
    "printmaking": "printmaking",
    "drypoint": "printmaking", "aquatint": "printmaking",
    "mezzotint": "printmaking", "relief print": "printmaking",
    # ink-based drawing — calligraphic / line-art / stipple
    "ink": "ink", "ink wash": "ink",
    "pen and ink": "ink", "fountain pen": "ink", "ballpoint": "ink",
    "marker": "ink", "felt tip": "ink", "fineliner": "ink",
    "dip pen": "ink", "brush pen": "ink", "sumi-e": "ink",
    # dry drawing — graphite / charcoal / chalk
    "pencil": "dry-drawing", "graphite": "dry-drawing", "charcoal": "dry-drawing",
    "chalk": "dry-drawing", "crayon": "dry-drawing", "conte": "dry-drawing",
    "colored pencil": "dry-drawing", "carbon": "dry-drawing",
    "sanguine": "dry-drawing", "silverpoint": "dry-drawing",
    "carbon pencil": "dry-drawing",
    # collage / mixed
    "collage": "collage", "photomontage": "collage", "decoupage": "collage",
    "assemblage": "collage", "cut paper": "collage",
    "mixed media": "collage", "frottage": "collage",
    # digital
    "digital": "digital", "vector": "digital", "pixel art": "digital",
    "voxel": "digital", "3d render": "digital", "cg": "digital", "cgi": "digital",
    "ray tracing": "digital", "raytraced": "digital",
    "procedural": "digital", "generative": "digital",
    "glitch": "digital", "glitch art": "digital", "databending": "digital",
    "fractal": "digital",
    # lens-based
    "photography": "lens", "film still": "lens", "cinematography": "lens",
    "daguerreotype": "lens", "cyanotype": "lens", "tintype": "lens",
    "polaroid": "lens", "pinhole": "lens", "photomicrography": "lens",
    "ambrotype": "lens", "photogram": "lens",
    # airbrush/spray/mural
    "airbrush": "spray", "spray paint": "spray", "aerosol": "spray",
    "graffiti": "spray", "mural": "spray", "fresco": "spray",
    "stencil": "spray", "wheatpaste": "spray",
    # textile / fibre
    "stained glass": "craft", "mosaic": "craft", "tapestry": "craft",
    "textile": "craft", "embroidery": "craft",
    "needlepoint": "craft", "cross-stitch": "craft",
    "weaving": "craft", "knitting": "craft", "crochet": "craft",
    "lace": "craft", "appliqué": "craft", "quilting": "craft",
    "patchwork": "craft", "batik": "craft",
    # 3d / sculptural (photographed)
    "bas-relief": "sculpture", "clay": "sculpture", "terracotta": "sculpture",
    "plaster": "sculpture", "bronze": "sculpture", "marble": "sculpture",
    "wax": "sculpture", "diorama": "sculpture",
    "shadow puppet": "sculpture", "stop motion": "sculpture",
    "claymation": "sculpture", "papier-mâché": "sculpture",
    "papier mache": "sculpture",
    # paper craft
    "origami": "paper-art", "kirigami": "paper-art", "paper cut": "paper-art",
    "silhouette": "paper-art", "pop-up": "paper-art",
    "scherenschnitte": "paper-art", "papel picado": "paper-art",
    # illuminated / manuscript
    "illuminated manuscript": "manuscript", "gold leaf": "manuscript",
    "gilding": "manuscript", "vellum": "manuscript", "parchment": "manuscript",
    "book of hours": "manuscript",
    # signage / display
    "neon sign": "signage", "billboard": "signage",
    "hand-painted sign": "signage", "marquee": "signage",
    "carnival": "signage", "fairground": "signage",
    "circus poster": "signage", "travel poster": "signage",
    # scientific / technical
    "blueprint": "technical", "x-ray": "technical", "infrared": "technical",
    "thermal imaging": "technical",
    "anatomical diagram": "technical", "scientific illustration": "technical",
    "botanical plate": "technical", "field journal": "technical",
    "topographical": "technical", "cartography": "technical", "map": "technical",
    # colour approaches — limited-palette is NOT monochrome; kept distinct
    "monochrome": "monochrome", "monochromatic": "monochrome",
    "black-and-white": "monochrome", "black and white": "monochrome",
    "grayscale": "monochrome", "greyscale": "monochrome",
    "chiaroscuro": "monochrome",
    "neon": "neon", "synthetic": "neon", "fluorescent": "neon",
    "day-glo": "neon", "dayglo": "neon",
    "phosphorescent": "neon", "blacklight": "neon",
    "ultraviolet": "neon", "uv-reactive": "neon",
    "earth-tones": "earth", "earth tones": "earth", "ochre": "earth",
    "sepia": "earth", "umber": "earth",
    # surface / substrate
    "canvas": "canvas", "wood panel": "board",
    "paper": "paper", "rice paper": "paper", "washi": "paper",
    "mulberry paper": "paper", "handmade paper": "paper",
    "newsprint": "paper", "kraft paper": "paper",
    "acetate": "transparent", "mylar": "transparent", "glass": "transparent",
    "metal": "metal", "copper": "metal", "aluminium": "metal",
    "scratchboard": "scratchboard", "scratch board": "scratchboard",
}


# Families that define the *primary medium* of a suggestion.  If two
# suggestions share one of these families they are automatically treated
# as overlapping — no Jaccard threshold is consulted — because "woodblock
# print" and "copperplate etching" are obviously the same medium.
_PRIMARY_MEDIUM_FAMILIES: frozenset[str] = frozenset({
    "printmaking", "digital", "lens", "sculpture", "collage",
    "spray", "paper-art", "manuscript", "signage", "technical",
    "craft",   # tapestry, mosaic, stained-glass — all decorative craft
    "dry-drawing",  # charcoal, pencil, graphite
    "ink",          # pen-and-ink, ballpoint, sumi-e
    "scratchboard",
})


def _share_primary_medium(a: set[str], b: set[str]) -> bool:
    """True when both token sets contain at least one shared primary-medium family."""
    shared = a & b
    return bool(shared & _PRIMARY_MEDIUM_FAMILIES)


def _extract_technique_tokens(text: str) -> set[str]:
    """Return the set of canonical visual-technique families present in *text*."""
    text_lower = text.lower()
    raw: set[str] = set()
    # Multi-word phrases first (longest match wins to avoid double-counting)
    for kw in sorted(_TECHNIQUE_KEYWORDS, key=len, reverse=True):
        if kw in text_lower:
            raw.add(kw)
    # Also capture single-word hits that may appear hyphenated/dashed
    words = (
        text_lower.replace(",", " ")
        .replace(".", " ")
        .replace("—", " ")
        .replace("-", " ")
        .split()
    )
    for w in words:
        w = w.strip("'\"()[]{}:;!?")
        if w in _TECHNIQUE_KEYWORDS:
            raw.add(w)
    # Normalise to canonical family names
    return {_TOKEN_FAMILY.get(t, t) for t in raw}


def _jaccard_similarity(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _deduplicate_suggestions(
    new_suggestions: list[dict],
    existing_suggestions: list[dict] | None = None,
    overlap_threshold: float = 0.35,
) -> list[dict]:
    """Drop suggestions whose visual-technique tokens overlap heavily with
    existing suggestions or with already-kept siblings from *new_suggestions*."""
    if existing_suggestions is None:
        existing_suggestions = []

    all_existing_tokens = [
        _extract_technique_tokens(s.get("template", ""))
        for s in existing_suggestions
    ]

    kept: list[dict] = []
    kept_tokens: list[set[str]] = []

    for s in new_suggestions:
        new_tokens = _extract_technique_tokens(s.get("template", ""))

        # ── hard primary-medium gate ───────────────────────────────────
        # If this suggestion shares a primary medium family with any
        # existing or already-kept suggestion, reject it immediately.
        all_prior_tokens = all_existing_tokens + kept_tokens
        if any(_share_primary_medium(new_tokens, pt) for pt in all_prior_tokens):
            continue

        # ── Jaccard soft gate ───────────────────────────────────────────
        if any(
            _jaccard_similarity(new_tokens, pt) > overlap_threshold
            for pt in all_prior_tokens
        ):
            continue

        kept.append(s)
        kept_tokens.append(new_tokens)

    return kept


async def generate_suggestions(
    config: Config,
    story_bible: StoryBible,
    *,
    existing_suggestions: list[dict] | None = None,
):
    """Generate style suggestions via LLM. Returns (suggestions_list, usage).

    When *existing_suggestions* is supplied the LLM prompt is seeded with
    the full template text of every prior suggestion so it can deliberately
    avoid overlapping visual territory, and a post-generation Jaccard-based
    overlap filter drops any remaining near-duplicates.

    The LLM is asked for more suggestions than we need (``LLM_REQUEST_COUNT``)
    so that dedup can still yield at least ``SAMPLE_COUNT``.  If the first
    attempt falls short a second attempt is made with the existing-pool
    expanded to steer the LLM further away.
    """
    total_usage = None
    first_usage = None

    def _build_avoid_block(pool: list[dict]) -> str:
        if not pool:
            return ""
        summaries: list[str] = []
        for s in pool:
            label = s.get("label", "Unknown")
            template = s.get("template", "")
            summaries.append(f'"{label}": {template}')
        return (
            f"\n\nCRITICAL: The following {len(pool)} styles have ALREADY been "
            f"suggested for this story. You MUST explore completely different visual territories. "
            f"Read each description carefully and ensure none of your new suggestions could be "
            f"visually confused with any of these:\n\n"
            + "\n\n---\n\n".join(summaries)
            + "\n\n---\n\n"
            + "Remember: choose styles that are MAXIMALLY DISTINCT from all of the above. "
            + "If a candidate's visual technique or primary medium overlaps with any above, "
            + "discard it and pick a different one."
        )

    async def _call_llm(avoid_pool: list[dict]) -> list[dict]:
        nonlocal first_usage
        avoid = _build_avoid_block(avoid_pool)
        system = (
            _SYSTEM_PROMPT
            + avoid
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
    suggestions = _deduplicate_suggestions(await _call_llm(pool), pool)

    # --- retry if dedup left us with fewer than SAMPLE_COUNT -----------------
    for attempt in range(1, _GENERATION_MAX_ATTEMPTS):
        if len(suggestions) >= SAMPLE_COUNT:
            break
        # Expand the avoid-pool with the *unused* suggestions from the first
        # pass so the retry gets an even stronger steer.
        retry_pool = pool + suggestions
        more = _deduplicate_suggestions(await _call_llm(retry_pool), retry_pool)
        suggestions.extend(more)

    # Trim to SAMPLE_COUNT — the first SAMPLE_COUNT survivors are the most
    # distinct (dedup walks the LLM output in order, keeping the first match
    # in each family).
    suggestions = suggestions[:SAMPLE_COUNT]

    return suggestions, first_usage


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
):
    """Generate one style sample image at sample_path. Returns ApiResult."""
    prompt = build_style_sample_prompt(config, bible)
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

    `on_sample_done(idx, ApiResult)` is awaited after each sample finishes —
    callers use it to record per-item progress and persist incremental state.
    """
    sem = asyncio.Semaphore(concurrency)

    async def _one(idx: int) -> None:
        s = suggestions[idx - 1]
        template = s.get("template", config.style_template)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)
        async with sem:
            result = await generate_sample_image(sample_config, bible, sample_path)
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


from novel_to_comic.stages import Stage  # noqa: E402
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
    clean_paths=lambda d: [
        d / "samples", d / "refs", d / "plates",
        d / "adapt", d / "plan", d / "storyboard",
        d / "direct", d / "draw", d / "compose", d / "exports",
    ],
    estimate_cost=estimate_cost,
)
