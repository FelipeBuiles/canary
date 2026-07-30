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
from novel_to_comic.clients import text as text_client
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.models.generation import PromptAnchor, PromptSubject
from novel_to_comic.asset_generation import (
    AbstractStyleProofInput,
    asset_matches_request,
    compile_non_panel_request,
    estimate_non_panel_request,
    style_reference_plan,
    submit_non_panel_request,
)
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.style_briefing import (
    normalize_prose_brief,
    style_sample_fallback_brief,
)
from novel_to_comic.style_contract import (
    DEFAULT_LETTERING_STANDARD,
    DEFAULT_PAGE_FRAMING_STANDARD,
    style_template_for_suggestion,
    page_style_template,
)
from novel_to_comic.stage_runtime import StageRuntime

logger = logging.getLogger(__name__)

SAMPLE_COUNT = 5
LLM_REQUEST_COUNT = 8  # ask for more than we need so dedup still yields >= 5
SAMPLE_CONCURRENCY = 2
_GENERATION_MAX_ATTEMPTS = 2
SUGGESTION_SCHEMA_VERSION = 3
STYLE_BRIEF_VERSION = 3
PORTFOLIO_ROLES = (
    "story_fit_primary", "story_fit_secondary", "adjacent", "contrast", "wildcard",
)
STYLE_VALIDATION_ACTION = "A decisive full-body action with readable silhouette and hand gesture."
STYLE_VALIDATION_COMPOSITION = (
    "One complete portrait comic-page proof with three panels: environment setup, "
    "full-body action, and expressive reaction detail, all using the same declared "
    "framing, border, gutter, and lettering system."
)

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

    "The final five positions matter: return the two strongest story-fit directions, "
    "then one aesthetically adjacent alternative, one viable contrast, and one controlled "
    "wildcard. Judge every direction as sequential art: panel-size readability, repeatable "
    "characters, expressive faces and action, clear environments, and value separation.\n\n"
    "For each direction, also define a production system that can remain invariant across "
    "an entire book:\n"
    "- lettering: name one typeface class/family; require preservation of canonical "
    "capitalization exactly (never convert all copy to a different case); name text, "
    "balloon, and caption colors; balloon/caption shapes; and one outline treatment. "
    "Canonical wording and capitalization must always be preserved exactly. Role-specific "
    "differences must be intentional variants inside the same system, never improvised.\n"
    "- page_framing: choose exactly one outer-page system — either the same fixed margin "
    "on every page or full bleed on every page — plus one panel-border and gutter treatment. "
    "Never alternate systems by page and never use scribbled borders unless that exact "
    "border treatment is the declared invariant.\n\n"
    "Output JSON array only, no markdown. Every object needs: label, medium, palette, "
    "portfolio_role (story_fit_primary, story_fit_secondary, adjacent, contrast, or wildcard), "
    "line_rendering, lighting_value, lettering, page_framing, sequential_art_strengths, "
    "story_fit, risk, and template. Template remains a 40-70 word downstream generation "
    "direction."
)


def _stable_suggestion_id(suggestion: dict) -> str:
    values = (
        suggestion.get("label"),
        suggestion.get("medium"),
        suggestion.get("template"),
        suggestion.get("lettering") or DEFAULT_LETTERING_STANDARD,
        suggestion.get("page_framing") or DEFAULT_PAGE_FRAMING_STANDARD,
    )
    material = "\n".join(str(value or "").strip() for value in values)
    return f"style_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def normalize_suggestion(
    suggestion: dict, *, role: str | None = None, origin: str = "generated",
) -> dict:
    """Normalize generated and safely-read older dictionaries to the v2 shape."""
    normalized = {
        "id": _stable_suggestion_id(suggestion),
        "origin": suggestion.get("origin") or origin,
        "role": role or suggestion.get("role"),
        "label": suggestion.get("label") or "Untitled direction",
        "medium": suggestion.get("medium") or "mixed media",
        "palette": suggestion.get("palette") or "",
        "line_rendering": suggestion.get("line_rendering") or "",
        "lighting_value": suggestion.get("lighting_value") or "",
        "lettering": suggestion.get("lettering") or DEFAULT_LETTERING_STANDARD,
        "page_framing": (
            suggestion.get("page_framing") or DEFAULT_PAGE_FRAMING_STANDARD
        ),
        "sequential_art_strengths": suggestion.get("sequential_art_strengths") or "",
        "story_fit": suggestion.get("story_fit") or "",
        "risk": suggestion.get("risk") or "",
        "template": suggestion.get("template") or "",
    }
    if suggestion.get("direction_id"):
        normalized["direction_id"] = suggestion["direction_id"]
    return normalized


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


_DIVERSITY_FIELDS = ("medium", "palette", "line_rendering", "lighting_value")


def _field_distance(a: str, b: str) -> float:
    left, right = _medium_tokens(a), _medium_tokens(b)
    if not left and not right:
        return 0.0
    return 1.0 - (len(left & right) / len(left | right))


def _portfolio_distance(a: dict, b: dict) -> float:
    return sum(_field_distance(str(a.get(field) or ""), str(b.get(field) or ""))
               for field in _DIVERSITY_FIELDS) / len(_DIVERSITY_FIELDS)


def _select_portfolio(candidates: list[dict], count: int = SAMPLE_COUNT) -> list[dict]:
    """Greedy farthest-first curation with a small model-ranking preference."""
    if len(candidates) <= count:
        return candidates
    selected = [candidates[0]]
    remaining = list(enumerate(candidates[1:], 1))
    while remaining and len(selected) < count:
        index, choice = max(
            remaining,
            key=lambda item: (
                min(_portfolio_distance(item[1], prior) for prior in selected)
                + max(0.0, 0.08 - item[0] * 0.01),
                -item[0],
            ),
        )
        selected.append(choice)
        remaining = [(i, candidate) for i, candidate in remaining if i != index]
    return selected


def _candidate_role(candidate: dict, index: int) -> str:
    declared = str(candidate.get("portfolio_role") or candidate.get("role") or "").strip()
    if declared in PORTFOLIO_ROLES:
        return declared
    # Safe reading for older/model output: preserve the prompt's ranked role
    # contract before diversity selection, rather than relabeling after reorder.
    return PORTFOLIO_ROLES[min(index, len(PORTFOLIO_ROLES) - 1)]


def _select_role_portfolio(candidates: list[dict], roles: tuple[str, ...]) -> list[dict]:
    tagged = [(index, candidate, _candidate_role(candidate, index))
              for index, candidate in enumerate(candidates)]
    selected: list[dict] = []
    used: set[int] = set()
    for desired in roles:
        eligible = [(index, candidate) for index, candidate, role in tagged
                    if index not in used and role == desired]
        if not eligible:
            raise RuntimeError(f"Style curation did not produce required role: {desired}")
        index, choice = max(
            eligible,
            key=lambda item: (
                min((_portfolio_distance(item[1], prior) for prior in selected), default=1.0)
                + max(0.0, 0.08 - item[0] * 0.01),
                -item[0],
            ),
        )
        used.add(index)
        selected.append(choice)
    return selected


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
    custom_direction: dict | None = None,
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
            f"Narrative arcs: {'; '.join(f'{a.title}: {a.turning_point or ""}' for a in story_bible.narrative_arcs) or 'not supplied'}\n"
            f"Scene range: {'; '.join(f'{s.scene_type}/{s.narrative_beat}: {s.summary}' for s in story_bible.scenes[:12])}\n"
            f"Settings: {'; '.join(f'{loc.name} — {loc.mood}: {loc.visual_anchor}' for loc in story_bible.locations[:8])}\n"
            f"Character demands: {'; '.join(f'{char.name}: {char.visual_anchor}' for char in story_bible.characters[:8])}\n"
            + (
                "Author-supplied visual direction to use as the center of gravity while still "
                f"preserving portfolio variance: {custom_direction.get('text') or 'uploaded visual reference'}\n"
                if custom_direction else ""
            )
            + "\n"
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
    required_count = 4 if custom_direction else SAMPLE_COUNT

    # --- retry if dedup left us with fewer than SAMPLE_COUNT -----------------
    for _attempt in range(1, _GENERATION_MAX_ATTEMPTS):
        if len(suggestions) >= required_count:
            break
        # Expand the avoid-pool with the *unused* suggestions from the first
        # pass so the retry gets an even stronger steer.
        retry_pool = pool + suggestions
        suggestions.extend(_dedupe_suggestions(await _call_llm(retry_pool), retry_pool))

    if len(suggestions) < required_count:
        raise RuntimeError(
            f"Style curation produced {len(suggestions)} usable directions; "
            f"{required_count} are required. Please retry."
        )
    portfolio_roles = (
        ("story_fit_primary", "adjacent", "contrast", "wildcard")
        if custom_direction else PORTFOLIO_ROLES
    )
    curated = [
        normalize_suggestion(
            suggestion,
            role=portfolio_roles[index],
            origin="generated_neighbor" if custom_direction else "generated",
        )
        for index, suggestion in enumerate(_select_role_portfolio(suggestions, portfolio_roles))
    ]
    if custom_direction and custom_direction.get("id"):
        for suggestion in curated:
            suggestion["direction_id"] = custom_direction["id"]
    return curated, first_usage


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
    "You write the subject brief for a complete-page style proof used to judge candidate "
    "art and production styles for a comic adaptation of a novel. You receive the story's "
    "curated characters, locations, and early scene evidence.\n"
    "\n"
    "Use the first listed character and first listed location (already curated as the "
    "proof subjects): a face and figure that show how people render, and an environment "
    "with depth and material variety. Use the first scene that contains both as quiet "
    "story context when one is supplied. Do not quote source prose as lettering. Let each "
    "candidate art direction own the palette, contrast, and value structure.\n"
    "\n"
    "Then write that moment as a single flowing brief of 60-120 words, the way a "
    "film director describes the shared visual content of one three-panel proof page:\n"
    "- Introduce the character with their full physical description (age, build, "
    "hair, face, wardrobe) before their action.\n"
    "- Use an environment setup, a three-quarter or full-length character view, and one "
    "expressive detail. Keep them in one coherent place and moment sequence.\n"
    "- Name the physical light source and direction, but do not prescribe its color, "
    "contrast, value range, or shadow density.\n"
    "- Use one quiet, characteristic micro-beat — no climactic story event.\n"
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
    if story_bible.scenes:
        lines.append("Early scene evidence:")
        for scene in story_bible.scenes[:6]:
            anchor = (
                f' Source anchor: "{scene.source_start_quote}"'
                if scene.source_start_quote
                else ""
            )
            lines.append(
                f"- {scene.id} ({scene.scene_type}/{scene.narrative_beat}): "
                f"location={scene.location_id or 'unknown'}; "
                f"characters={','.join(scene.character_ids) or 'none'}; "
                f"{scene.summary}.{anchor}"
            )
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
            max_output_tokens=4096,
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


def _style_sample_brief_source_key(config: Config, story_bible: StoryBible) -> str:
    return hashlib.sha256("\n".join((
        f"brief-schema:{STYLE_BRIEF_VERSION}",
        f"model:{config.effective_prompt_model()}",
        STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT,
        _style_sample_brief_source(story_bible),
    )).encode("utf-8")).hexdigest()


async def ensure_style_sample_brief(
    config: Config, story_bible: StoryBible, project_dir: Path,
) -> str | None:
    """Return a versioned cached proof brief or regenerate it."""
    if not getattr(config, "style_sample_brief_enabled", True):
        return None
    source_key = _style_sample_brief_source_key(config, story_bible)
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
            "version": STYLE_BRIEF_VERSION,
            "kind": "style_sample_brief",
            "source_sha256": source_key,
            "brief": brief,
        },
        indent=2,
        sort_keys=True,
    ))
    return brief


async def generate_sample_image(
    config: Config,
    bible: StoryBible,
    sample_path: Path,
    *,
    brief: str | None = None,
    candidate_id: str | None = None,
    style_reference: Path | None = None,
    project_dir: Path | None = None,
    subject_action: str | None = None,
    composition: str | None = None,
):
    """Generate one style sample image at sample_path. Returns ApiResult.

    *brief* is the shared prose body from ``ensure_style_sample_brief``;
    when None the prompt falls back to its deterministic body.

    Style proof images use a portrait 4:5 complete-page specimen. The generation
    dimensions must agree with that promised composition instead of the
    (default square) panel config dimensions.
    """
    scene_brief = brief or style_sample_fallback_brief(bible)
    sample_path.parent.mkdir(parents=True, exist_ok=True)
    request = build_style_sample_request(
        config, bible, scene_brief,
        candidate_id=candidate_id or sample_path.stem,
        style_reference=style_reference,
        subject_action=subject_action,
        composition=composition,
    )
    submission = await submit_non_panel_request(
        config=config,
        project_dir=project_dir or sample_path.parents[1],
        request=request,
        output_path=sample_path,
        feature="style.sample",
        kind="style_sample",
    )
    return submission.result


def build_style_sample_request(
    config: Config,
    bible: StoryBible,
    scene_brief: str,
    *,
    candidate_id: str,
    style_reference: Path | None = None,
    subject_action: str | None = None,
    composition: str | None = None,
):
    """Compile the canonical, fingerprintable request for one style proof."""
    from novel_to_comic.image_geometry import style_proof_dimensions

    width, height = style_proof_dimensions()
    selected_style = page_style_template(config.style_template)
    character = bible.characters[0] if bible.characters else None
    location = bible.locations[0] if bible.locations else None
    anchors = tuple(filter(None, (
        PromptAnchor(
            kind="character", entity_id=character.id, name=character.name,
            text=character.visual_anchor,
        ) if character else None,
        PromptAnchor(
            kind="location", entity_id=location.id, name=location.name,
            text=location.visual_anchor,
        ) if location else None,
    )))
    subjects = (
        (PromptSubject(
            character_id=character.id, name=character.name,
            identity=character.visual_anchor,
            baseline_affect=character.baseline_affect,
            action=subject_action or "A quiet characteristic action appropriate to the proof scene.",
            position="Three-quarter or full-length focal figure.",
        ),) if character else ()
    )
    input_data = AbstractStyleProofInput(
        asset_identity=f"style_sample:{candidate_id}",
        prompt=GenerationPromptInput(
            anchors=anchors,
            subjects=subjects,
            visual_brief=scene_brief,
            composition=composition or (
                "One complete portrait comic-page style proof with three clearly separated "
                "panels, rendered using the declared invariant outer-page framing, border, "
                "margin, and gutter system."
            ),
            setting=location.visual_anchor if location else None,
            constraints=(
                "This is a production-design proof, not wordless concept art. Include exactly "
                'these three lettering specimens once each: narration “The night held its '
                'breath.”, dialogue “We keep moving.”, and SFX “KRAK”. Apply the declared '
                "lettering standard consistently to all three. No other readable words, title, "
                "logo, signature, or watermark. Show the declared page framing and panel-border "
                "system clearly."
            ),
            width=width,
            height=height,
            generation_width=width,
            generation_height=height,
            generation_shape="portrait",
        ),
        selected_style_text=selected_style,
        selected_style_source_hash=hashlib.sha256(
            selected_style.encode("utf-8")
        ).hexdigest(),
    )
    request = compile_non_panel_request(
        config, input_data,
        reference_plan=style_reference_plan(config, style_reference),
    )
    return request


def load_suggestions(project_dir: Path) -> list[dict]:
    """Read the suggestions list from disk, or return [] if missing."""
    path = artifacts.style_suggestions_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    raw = data.get("suggestions", []) if isinstance(data, dict) else data
    if not isinstance(raw, list):
        return []
    return [normalize_suggestion(item) for item in raw if isinstance(item, dict)]


def save_suggestions(project_dir: Path, suggestions: list[dict], title: str) -> None:
    path = artifacts.style_suggestions_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": SUGGESTION_SCHEMA_VERSION,
        "title": title,
        "suggestions": [normalize_suggestion(s) for s in suggestions],
    }, indent=2))


def load_style_direction(project_dir: Path, direction_id: str) -> dict | None:
    if not re.fullmatch(r"direction_[a-f0-9]{16}", direction_id or ""):
        return None
    try:
        path = artifacts.style_direction_path(project_dir, direction_id)
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("id") == direction_id else None


def style_direction_image(project_dir: Path, direction: dict | None) -> Path | None:
    """Resolve a provenance-checked reference strictly inside its direction directory."""
    if not direction or not direction.get("image_path") or not direction.get("id"):
        return None
    try:
        base = artifacts.style_direction_path(project_dir, direction["id"]).parent.resolve()
    except ValueError:
        return None
    root = project_dir.resolve()
    if not base.is_relative_to(root):
        return None
    candidate = (project_dir / str(direction["image_path"])).resolve()
    if not candidate.is_relative_to(base) or candidate.parent != base:
        return None
    if candidate.suffix.lower() not in {".png", ".jpg", ".webp"} or not candidate.is_file():
        return None
    expected = direction.get("image_sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        return None
    if hashlib.sha256(candidate.read_bytes()).hexdigest() != expected:
        return None
    return candidate


def style_validation_brief(bible: StoryBible) -> str:
    """Deterministic second-proof brief emphasizing action and environment."""
    character = bible.characters[0] if bible.characters else None
    location = bible.locations[0] if bible.locations else None
    scene = next(
        (candidate for candidate in bible.scenes
         if candidate.scene_type == "action"
         and (not character or character.id in candidate.character_ids)
         and (not location or candidate.location_id == location.id)),
        bible.scenes[0] if bible.scenes else None,
    )
    action = scene.summary if scene else "A dynamic physical beat with clear spatial staging."
    return (
        f"{character.name if character else 'The protagonist'} moves decisively through "
        f"{location.name if location else 'the story environment'} during this beat: {action} "
        "Show a readable full-body action silhouette, expressive face and hands, layered "
        "environment depth, and distinct foreground and background materials. One frozen "
        "instant, no lettering or borders."
    )


def custom_direction_candidate(direction: dict) -> dict:
    text = str(direction.get("text") or "").strip()
    if not text:
        text = (
            "Use the supplied visual reference as the controlling art direction. Preserve its "
            "observable palette, mark-making, shapes, material finish, value structure, and level "
            "of realism while adapting the story content into readable sequential illustration."
        )
    candidate = {
        "origin": direction.get("origin") or "user_text",
        "role": "faithful",
        "label": direction.get("label") or "Your direction",
        "medium": "author directed",
        "palette": "As specified by the author direction/reference.",
        "line_rendering": "As specified by the author direction/reference.",
        "lighting_value": "As specified by the author direction/reference.",
        "sequential_art_strengths": "Faithful adaptation of the author's chosen visual language.",
        "story_fit": "Directly supplied by the author.",
        "risk": "A single proof may not expose every sequential-art edge case.",
        "template": text,
        "direction_id": direction["id"],
    }
    return normalize_suggestion(candidate)


def suggestion_index_by_id(suggestions: list[dict], suggestion_id: str) -> int | None:
    return next(
        (index for index, suggestion in enumerate(suggestions, 1)
         if suggestion.get("id") == suggestion_id),
        None,
    )


def _style_reference_for_suggestion(project_dir: Path, suggestion: dict) -> Path | None:
    direction_id = suggestion.get("direction_id")
    if not direction_id:
        return None
    direction = load_style_direction(project_dir, direction_id)
    return style_direction_image(project_dir, direction)


def missing_sample_indices(
    project_dir: Path,
    suggestions: list[dict],
    *,
    config: Config | None = None,
    bible: StoryBible | None = None,
) -> list[int]:
    """Return absent or fingerprint-stale sample positions.

    Callers without config/bible retain the inexpensive existence check.
    Stage execution supplies both and therefore never reuses a proof compiled
    from an older prompt, model, dimensions, template, or reference image.
    """
    brief = None
    brief_cache_valid = False
    if config and bible:
        try:
            cached = json.loads(artifacts.style_sample_brief_path(project_dir).read_text())
            brief_cache_valid = (
                cached.get("source_sha256") == _style_sample_brief_source_key(config, bible)
                and cached.get("version") == STYLE_BRIEF_VERSION
            )
            brief = cached.get("brief") if brief_cache_valid else None
        except (OSError, ValueError):
            pass
    missing = []
    for idx, suggestion in enumerate(suggestions, 1):
        output = artifacts.style_sample_path(project_dir, idx)
        if config is None or bible is None:
            fresh = output.exists()
        else:
            template = style_template_for_suggestion(suggestion)
            request = build_style_sample_request(
                config.model_copy(update={"style_template": template}), bible,
                brief or style_sample_fallback_brief(bible),
                candidate_id=suggestion.get("id") or f"style_{idx}",
                style_reference=_style_reference_for_suggestion(project_dir, suggestion),
            )
            fresh = asset_matches_request(output, request)
        if not fresh:
            missing.append(idx)
    return missing


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
        template = style_template_for_suggestion(s)
        sample_config = config.model_copy(update={"style_template": template})
        sample_path = artifacts.style_sample_path(project_dir, idx)
        candidate_id = s.get("id")
        reference = _style_reference_for_suggestion(project_dir, s)
        async with sem:
            result = await generate_sample_image(
                sample_config, bible, sample_path, brief=brief,
                candidate_id=candidate_id, style_reference=reference,
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
        else missing_sample_indices(
            project_dir, existing_suggestions, config=config, bible=bible,
        )
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


def _style_sample_estimate(config: Config, project_dir: Path, bible: StoryBible, template: str, identity: str):
    from novel_to_comic.image_geometry import style_proof_dimensions

    brief = None
    brief_path = artifacts.style_sample_brief_path(project_dir)
    if brief_path.exists():
        try:
            cached = json.loads(brief_path.read_text())
            brief = cached.get("brief") if isinstance(cached, dict) else None
        except (OSError, ValueError):
            brief = None
    width, height = style_proof_dimensions()
    input_data = AbstractStyleProofInput(
        asset_identity=identity,
        prompt=GenerationPromptInput(
            visual_brief=brief or style_sample_fallback_brief(bible),
            composition=(
                "One complete portrait comic-page style proof with three clearly separated "
                "panels using the invariant outer-page framing system."
            ),
            constraints=(
                "Include the narration “The night held its breath.”, dialogue “We keep "
                "moving.”, and SFX “KRAK” exactly once each, using the declared lettering "
                "standard. Show the declared borders, margins, and gutters. No other text."
            ),
            width=width,
            height=height,
            generation_width=width,
            generation_height=height,
            generation_shape="portrait",
        ),
        selected_style_text=template,
    )
    return estimate_non_panel_request(
        config.model_copy(update={"style_template": template}), input_data,
    )


def estimate_style_proof_cost_usd(
    config: Config,
    project_dir: Path,
    bible: StoryBible,
    template: str,
    candidate_id: str,
    *,
    style_reference: Path | None = None,
    reference_size: tuple[int, int] | None = None,
    subject_action: str | None = None,
    composition: str | None = None,
) -> float:
    """Estimate the exact compiled proof request plus a possible brief-model call."""
    from novel_to_comic.usage import estimate_image_cost, estimate_text_cost

    brief = None
    brief_path = artifacts.style_sample_brief_path(project_dir)
    if brief_path.exists():
        try:
            cached = json.loads(brief_path.read_text())
            if (
                isinstance(cached, dict)
                and cached.get("source_sha256") == _style_sample_brief_source_key(config, bible)
            ):
                brief = (cached.get("brief") or "").strip() or None
        except (OSError, ValueError):
            pass
    brief_cost = 0.0
    if brief is None and getattr(config, "style_sample_brief_enabled", True):
        brief_cost = estimate_text_cost(
            config.effective_prompt_model(),
            STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT + "\n" + _style_sample_brief_source(bible),
        )

    proof_config = config.model_copy(update={"style_template": template})
    request = build_style_sample_request(
        proof_config,
        bible,
        brief or style_sample_fallback_brief(bible),
        candidate_id=candidate_id,
        style_reference=style_reference,
        subject_action=subject_action,
        composition=composition,
    )
    ref_count = request.reference_plan.ref_count
    ref_sizes = None
    from novel_to_comic.image_models import image_model_profile_for_config

    if (
        reference_size is not None
        and "style" in image_model_profile_for_config(proof_config).supported_roles
    ):
        ref_count = 1
        ref_sizes = [reference_size]
    elif ref_count and style_reference is not None:
        try:
            from PIL import Image

            with Image.open(style_reference) as image:
                ref_sizes = [image.size]
        except (OSError, ValueError):
            ref_sizes = None
    image_cost = estimate_image_cost(
        proof_config.effective_image_model(),
        1,
        quality=getattr(proof_config, "image_quality", None),
        ref_count=ref_count,
        prompt_text=request.compiled.final_prompt,
        width=request.wire.width,
        height=request.wire.height,
        ref_image_sizes=ref_sizes,
    )
    return brief_cost + image_cost


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    from novel_to_comic.usage import estimate_image_cost, estimate_text_cost

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
        sample_count = len(missing_sample_indices(
            project_dir, suggestions, config=config,
            bible=artifacts.read_story_bible_safe(project_dir),
        ))

    bible = artifacts.read_story_bible_safe(project_dir)
    if bible is not None:
        templates = (
            [style_template_for_suggestion(s) for s in suggestions]
            if suggestions else [config.style_template] * sample_count
        )
        missing = set(missing_sample_indices(
            project_dir, suggestions, config=config, bible=bible,
        )) if suggestions else set(range(1, sample_count + 1))
        image_cost = sum(
            _style_sample_estimate(config, project_dir, bible, template, f"style_sample:{idx}").cost_usd
            for idx, template in enumerate(templates, 1) if idx in missing
        )
    else:
        image_cost = estimate_image_cost(
            config.effective_image_model(), sample_count,
            quality=getattr(config, "image_quality", None),
        )
    return text_cost + image_cost


def estimate_style_batch_cost_usd(
    config: Config,
    project_dir: Path,
    sample_count: int = SAMPLE_COUNT,
    *,
    has_style_reference: bool = False,
    reference_size: tuple[int, int] | None = None,
    suggestion_attempts: int = _GENERATION_MAX_ATTEMPTS,
) -> float:
    """Conservatively estimate one suggestion batch, including a possible retry."""
    from novel_to_comic.usage import estimate_image_cost, estimate_text_cost

    story_bible_text = ""
    sb_path = artifacts.story_bible_path(project_dir)
    if sb_path.exists():
        try:
            story_bible_text = sb_path.read_text()[:3000]
        except Exception:
            pass

    text_cost = suggestion_attempts * estimate_text_cost(
        config.effective_prompt_model(),
        story_bible_text,
    )
    bible = artifacts.read_story_bible_safe(project_dir)
    if bible is not None:
        estimates = [
            _style_sample_estimate(
                config, project_dir, bible, config.style_template,
                f"style_sample:batch:{index}",
            )
            for index in range(1, sample_count + 1)
        ]
        if has_style_reference:
            image_cost = sum(
                estimate_image_cost(
                    config.effective_image_model(), 1,
                    quality=getattr(config, "image_quality", None),
                    ref_count=1,
                    prompt_text=estimate.prompt_text,
                    width=estimate.dimensions[0],
                    height=estimate.dimensions[1],
                    ref_image_sizes=[reference_size] if reference_size else None,
                )
                for estimate in estimates
            )
        else:
            image_cost = sum(estimate.cost_usd for estimate in estimates)
    else:
        image_cost = estimate_image_cost(
            config.effective_image_model(), sample_count,
            quality=getattr(config, "image_quality", None),
            ref_count=1 if has_style_reference else 0,
            ref_image_sizes=[reference_size] if has_style_reference and reference_size else None,
        )
    return text_cost + image_cost


STAGE = Stage(
    name="style",
    run=run,
    outputs=lambda d: [artifacts.style_suggestions_path(d)],
    clean_paths=lambda d: clean_cascade(d, "samples"),
    estimate_cost=estimate_cost,
)
