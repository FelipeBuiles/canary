"""Stage 4: Scene text → Screenplay format

Converts prose scenes into observable-action screenplays suitable for
comic panel breakdown.
"""

import asyncio
import re
from pathlib import Path

from rich.console import Console

from novel_to_comic import artifacts
from novel_to_comic.clients import text
from novel_to_comic.config import Config
from novel_to_comic.events import make_progress
from novel_to_comic.models.appearance import StoryPosition
from novel_to_comic.models.panel import Screenplay
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.text_utils import has_offscreen_marker
from novel_to_comic.usage import ApiResult, estimate_text_cost

console = Console()
PROMPT_PATH = Path(__file__).parent.parent / "prompts" / "screenplay.txt"
_MAX_NARRATION_WORDS = 16


def _is_offscreen_character(char) -> bool:
    text = " ".join(
        str(part)
        for part in (
            char.name,
            char.visual_anchor,
            char.default_outfit,
            char.age_range,
            char.gender,
            " ".join(char.distinguishing_features),
        )
    )
    return has_offscreen_marker(text)


def _build_user_content(
    scene_text: str,
    story_bible: StoryBible,
    scene_id: str,
    max_words_per_bubble: int = 24,
) -> str:
    """Build the user message with scene text and relevant Story Bible context."""
    scene = next((s for s in story_bible.scenes if s.id == scene_id), None)
    if not scene:
        return (
            f"{scene_text}\n\nLETTERING BUDGET:\n"
            f"Aim for {max_words_per_bubble} words or fewer per dialogue or thought bubble. "
            f"Aim for {min(_MAX_NARRATION_WORDS, max_words_per_bubble)} words or fewer per narration caption. "
            "Never split or truncate an utterance or caption solely to meet these targets."
        )

    # Gather character descriptions
    char_info = []
    for cid in scene.character_ids:
        char = next((c for c in story_bible.characters if c.id == cid), None)
        if char and not _is_offscreen_character(char):
            char_info.append(f"- {char.name} ({cid}): {char.visual_anchor}")

    # Gather location
    loc = next((loc for loc in story_bible.locations if loc.id == scene.location_id), None)
    loc_desc = f"Location: {loc.name} — {loc.visual_anchor}" if loc else ""

    # Location/character appearance state is resolved per panel from each
    # entity's appearance_timeline (novel_to_comic.appearance), not tagged onto
    # screenplay beats — so the screenplay LLM no longer stamps state ids.

    # Boundary cue: tell the LLM where the NEXT scene begins so it stops in time.
    boundary_lines: list[str] = []
    scenes_list = story_bible.scenes
    try:
        idx = next(i for i, s in enumerate(scenes_list) if s.id == scene_id)
    except StopIteration:
        idx = -1
    if 0 <= idx < len(scenes_list) - 1:
        next_scene = scenes_list[idx + 1]
        if next_scene.source_start_quote:
            boundary_lines.extend([
                "",
                "SCENE BOUNDARY:",
                f"The NEXT scene ({next_scene.id} — \"{next_scene.title}\") begins with: "
                f"\"{next_scene.source_start_quote}\"",
                "STOP adapting the moment you reach (or approach) this line. Do not include it.",
            ])

    parts = [
        f"SCENE: {scene.id} — {scene.title}",
        f"Type: {scene.scene_type} | Beat: {scene.narrative_beat}",
        loc_desc,
        "",
        "CHARACTERS IN SCENE:",
        *char_info,
        *boundary_lines,
        "",
        "LETTERING BUDGET:",
        f"Aim for {max_words_per_bubble} words or fewer per dialogue or thought bubble.",
        f"Aim for {min(_MAX_NARRATION_WORDS, max_words_per_bubble)} words or fewer per narration caption.",
        "Never split or truncate an utterance or caption solely to meet these targets.",
        "If essential meaning cannot fit naturally, keep the complete self-contained text intact.",
        "",
        "SCENE TEXT:",
        scene_text,
    ]
    return "\n".join(parts)


def _enforce_scene_boundary(
    screenplay: Screenplay,
    story_bible: StoryBible,
) -> tuple[Screenplay, str | None]:
    """Drop beats that adapt content from the NEXT scene.

    The screenplay LLM occasionally overflows its assigned scene and starts
    adapting the next scene's prose, which causes every downstream stage to
    treat the bleed-over panels as belonging to the wrong location_id /
    location_state_id. We use the next scene's source_start_quote as a
    boundary marker: any beat whose source_text contains that marker (or any
    beat after such a beat in the same screenplay) is dropped.

    Returns (possibly-truncated screenplay, warning message or None).
    """
    scenes = story_bible.scenes
    try:
        idx = next(i for i, s in enumerate(scenes) if s.id == screenplay.scene_id)
    except StopIteration:
        return screenplay, None
    if idx >= len(scenes) - 1:
        return screenplay, None
    marker = (scenes[idx + 1].source_start_quote or "").strip()
    if len(marker) < 16:
        return screenplay, None
    marker_lower = marker.lower()
    boundary_idx: int | None = None
    for i, beat in enumerate(screenplay.beats):
        haystack = " ".join(
            part.lower()
            for part in (beat.source_text, beat.content, beat.direction)
            if part
        )
        if marker_lower in haystack:
            boundary_idx = i
            break
    if boundary_idx is None:
        return screenplay, None
    kept_beats = screenplay.beats[:boundary_idx]
    dropped = len(screenplay.beats) - boundary_idx
    warning = (
        f"{screenplay.scene_id}: trimmed {dropped} beat(s) that drifted into the next "
        f"scene's content (matched next-scene start quote)."
    )
    return screenplay.model_copy(update={"beats": kept_beats}), warning


def _normalize_screenplay(screenplay: Screenplay, story_bible: StoryBible) -> Screenplay:
    # TODO: Add first-class off-screen speaker support instead of nulling voice-only speakers.
    offscreen_ids = {char.id for char in story_bible.characters if _is_offscreen_character(char)}
    if not offscreen_ids:
        return screenplay

    visible_characters = [cid for cid in screenplay.characters if cid not in offscreen_ids]
    beats = []
    for beat in screenplay.beats:
        if beat.character_id not in offscreen_ids:
            beats.append(beat)
            continue

        char = next((c for c in story_bible.characters if c.id == beat.character_id), None)
        speaker = char.name if char else beat.character_id
        direction = beat.direction or ""
        cue = f"off-screen voice: {speaker}"
        if cue not in direction:
            direction = f"{cue}. {direction}".strip()
        beats.append(beat.model_copy(update={"character_id": None, "direction": direction}))

    return screenplay.model_copy(update={"characters": visible_characters, "beats": beats})


def _beat_present_ids(text: str, name_patterns: list[tuple[str, re.Pattern]]) -> list[str]:
    """Cast ids whose name is named in ``text``, dropping subsumed matches.

    Character names overlap ("The Miller" ⊂ "The Miller's Daughter", "The King"
    ⊂ "The King's Mother"), so a naive search tags the shorter name inside the
    longer one. We keep only matches not strictly contained in a longer match.
    """
    spans: list[tuple[int, int, str]] = []
    for cid, pat in name_patterns:
        for m in pat.finditer(text):
            spans.append((m.start(), m.end(), cid))
    present: list[str] = []
    for i, (s, e, cid) in enumerate(spans):
        subsumed = any(
            j != i and os <= s and e <= oe and (oe - os) > (e - s)
            for j, (os, oe, _) in enumerate(spans)
        )
        if not subsumed and cid not in present:
            present.append(cid)
    return present


def _resolve_present_characters(screenplay: Screenplay, story_bible: StoryBible) -> Screenplay:
    """Re-attach on-screen cast members the adapt model dropped.

    The adapt LLM occasionally marks a physically-present, named character as an
    "off-screen speaker" (and omits them from ``screenplay.characters``) — e.g.
    The King in scene_004 of the-girl-without-hands. Downstream that strips his
    reference image, so the draw stage redraws him from a hallucinated,
    panel-to-panel-inconsistent description. We re-add any NON-off-screen cast
    member named in an action/transition beat (physical staging establishes who
    is in frame) and tag an otherwise-unattributed action beat that names
    exactly one such character.
    """
    offscreen_ids = {c.id for c in story_bible.characters if _is_offscreen_character(c)}
    cast = [
        (c.id, c.name)
        for c in story_bible.characters
        if c.id not in offscreen_ids and c.name
    ]
    if not cast:
        return screenplay
    name_patterns = [(cid, re.compile(rf"\b{re.escape(name)}", re.IGNORECASE)) for cid, name in cast]

    present_in_scene: list[str] = []
    new_beats = []
    for beat in screenplay.beats:
        text = " ".join(p for p in (beat.content, beat.direction) if p)
        present = _beat_present_ids(text, name_patterns)
        if beat.type in ("action", "transition"):
            for cid in present:
                if cid not in present_in_scene:
                    present_in_scene.append(cid)
        if beat.type == "action" and beat.character_id is None and len(present) == 1:
            beat = beat.model_copy(update={"character_id": present[0]})
        new_beats.append(beat)

    merged = list(screenplay.characters)
    for cid in present_in_scene:
        if cid not in merged:
            merged.append(cid)
    return screenplay.model_copy(update={"characters": merged, "beats": new_beats})


def _transition_type_for_text(text: str) -> str:
    # Keyword table mirrors the examples in prompts/screenplay.txt: fades and
    # cuts are deliberate jumps (hard_cut); visual echoes are match cuts;
    # everything else is a gentle handoff.
    lower = text.lower()
    hard_markers = (
        "smash cut", "cut to", "scene change", "time jump", "jump cut", "fade",
        "flashback", "flash forward", "years earlier", "years later",
        "months earlier", "months later", "days earlier", "days later",
        "hours earlier", "hours later", "elsewhere", "meanwhile",
    )
    if any(marker in lower for marker in hard_markers):
        return "hard_cut"
    if any(marker in lower for marker in ("match cut", "parallel", "echo", "mirrors")):
        return "match_cut"
    return "smooth_continuation"


def _annotate_transition_beats(screenplay: Screenplay) -> Screenplay:
    """Fill in transition_type ONLY where the screenplay model omitted it.

    The model is asked to classify its own transitions; the keyword heuristic
    is a fallback, not an override.
    """
    beats = []
    for beat in screenplay.beats:
        if beat.type == "transition" and not beat.transition_type:
            beats.append(
                beat.model_copy(
                    update={
                        "transition_type": _transition_type_for_text(
                            f"{beat.content} {beat.direction or ''}"
                        ),
                    }
                )
            )
        else:
            beats.append(beat)
    return screenplay.model_copy(update={"beats": beats})


_TRANSITION_STOPWORDS = {
    "the", "her", "his", "their", "them", "and", "for", "with", "from", "into",
    "under", "over", "that", "this", "they", "she", "him", "was", "were", "are",
    "has", "had", "off", "out", "its", "not", "but", "all", "any", "who", "once",
    "then", "she", "you", "your", "now",
}


def _keyword_tokens(text: str) -> set[str]:
    return {
        w
        for w in re.findall(r"[a-z]+", (text or "").lower())
        if len(w) >= 3 and w not in _TRANSITION_STOPWORDS
    }


def _find_transition_beat(activation, state, base_anchor: str, beats) -> int | None:
    """1-indexed ordinal of the beat that DEPICTS an appearance transition.

    Keywords come from the transition ``label`` plus the words the new state
    adds over the base look — deliberately NOT ``transition.cause``, which names
    recurring agents (e.g. "the Devil") that appear all over the scene and would
    mis-pin the boundary. Among matching beats we prefer the LAST action/sfx
    beat (the act itself — the axe falling — happens after the dialogue that
    threatens it). Returns None when nothing matches, leaving the activation at
    scene granularity (never worse than today).
    """
    transition = getattr(activation, "transition", None)
    label = transition.label if transition else ""
    keywords = _keyword_tokens(label)
    if state is not None:
        base_tokens = _keyword_tokens(base_anchor)
        keywords |= {
            t for t in _keyword_tokens(state.visual_anchor)
            if t not in base_tokens and len(t) >= 4
        }
    if not keywords:
        return None
    patterns = [re.compile(rf"\b{re.escape(k)}\b", re.IGNORECASE) for k in keywords]

    matches: list[int] = []
    act_matches: list[int] = []
    for i, beat in enumerate(beats):
        text = " ".join(p for p in (beat.content, beat.direction) if p)
        if any(p.search(text) for p in patterns):
            matches.append(i + 1)
            if beat.type in ("action", "sfx"):
                act_matches.append(i + 1)
    if act_matches:
        return act_matches[-1]
    if matches:
        return matches[-1]
    return None


def _pin_appearance_transitions(project_dir: Path, story_bible: StoryBible) -> int:
    """Pin within-scene appearance transitions to a beat, once screenplays exist.

    Extraction authors appearance activations at scene granularity (``at.beat``
    is null) because beats don't exist yet. The resolver is beat-capable, so a
    scene-level ``at`` wrongly maps the WHOLE transition scene to the new look —
    e.g. the girl shows stumps in scene_003's opening chalk-circle panel, before
    her father severs her hands later in the same scene. We locate the depicting
    beat and set ``at.beat`` to the FIRST beat the new look holds (the act is
    shown in the beat just before), so pre-transformation panels resolve to the
    prior look. Best-effort: unmatched activations stay scene-level. Idempotent
    (only fills null beats). Single-writer — called after the parallel batch.
    """
    scene_ids = {s.id for s in story_bible.scenes}
    screenplay_cache: dict[str, Screenplay | None] = {}

    def beats_for(scene_id: str):
        if scene_id not in screenplay_cache:
            if scene_id in scene_ids and artifacts.screenplay_path(project_dir, scene_id).exists():
                screenplay_cache[scene_id] = artifacts.read_screenplay(project_dir, scene_id)
            else:
                screenplay_cache[scene_id] = None
        sp = screenplay_cache[scene_id]
        return sp.beats if sp else []

    changed = 0
    for entity in [*story_bible.characters, *story_bible.locations]:
        states = {s.id: s for s in entity.appearance_states}
        for activation in entity.appearance_timeline:
            if activation.at.beat is not None:
                continue
            beats = beats_for(activation.at.scene_id)
            if not beats:
                continue
            k = _find_transition_beat(
                activation, states.get(activation.state_id), entity.visual_anchor, beats
            )
            if k is None:
                continue
            activation.at.beat = k + 1 if k < len(beats) else k
            if activation.transition is not None:
                activation.transition.depicted_at = StoryPosition(
                    scene_id=activation.at.scene_id, beat=k
                )
            changed += 1

    if changed:
        artifacts.write_story_bible(project_dir, story_bible)
    return changed


def _localized_system_prompt(config: Config, system_prompt: str) -> str:
    return f"{system_prompt.rstrip()}\n\nLANGUAGE REQUIREMENT:\n{config.generation_language_instruction()}"


async def _process_scene(
    config: Config,
    project_dir: Path,
    story_bible: StoryBible,
    scene_id: str,
    system_prompt: str,
    semaphore: asyncio.Semaphore,
) -> ApiResult[Screenplay | None]:
    """Process a single scene into a screenplay."""
    if not artifacts.scene_text_path(project_dir, scene_id).exists():
        return None

    if artifacts.screenplay_path(project_dir, scene_id).exists():
        return ApiResult(value=artifacts.read_screenplay(project_dir, scene_id), usage=None)

    scene_text = artifacts.read_scene_text(project_dir, scene_id)
    user_content = _build_user_content(
        scene_text,
        story_bible,
        scene_id,
        config.max_words_per_bubble,
    )

    async with semaphore:
        api_result = await text.generate_json(
            config=config,
            model=config.effective_screenplay_model(),
            system_prompt=_localized_system_prompt(config, system_prompt),
            user_content=user_content,
            feature="adapt.screenplay",
        )

    result = api_result.value
    # Some models wrap the response in a list — unwrap before validating.
    if isinstance(result, list):
        result = result[0]
    screenplay = _normalize_screenplay(Screenplay.model_validate(result), story_bible)
    screenplay = _annotate_transition_beats(screenplay)
    screenplay, boundary_warning = _enforce_scene_boundary(screenplay, story_bible)
    if boundary_warning:
        console.print(f"[yellow]{boundary_warning}[/yellow]")
    screenplay = _resolve_present_characters(screenplay, story_bible)
    artifacts.write_screenplay(project_dir, scene_id, screenplay)
    return ApiResult(value=screenplay, usage=api_result.usage)


async def run(
    config: Config,
    project_dir: Path,
    ctx: StageRuntime,
    scene_ids: list[str] | None = None,
) -> None:
    """Execute Stage 4: Convert scenes to screenplays."""
    story_bible = artifacts.read_story_bible(project_dir)
    system_prompt = PROMPT_PATH.read_text()

    ids = scene_ids or [s.id for s in story_bible.scenes]
    if config.dev_mode and not scene_ids:
        ids = ids[:1]

    estimated = 0.0
    for sid in ids:
        if artifacts.screenplay_path(project_dir, sid).exists():
            continue
        scene_path = artifacts.scene_text_path(project_dir, sid)
        scene_text = scene_path.read_text() if scene_path.exists() else "x" * 8000
        estimated += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
        )

    semaphore = asyncio.Semaphore(config.parallel_batch_size)

    with ctx.execute(total=len(ids), estimated_cost_usd=estimated):
        with make_progress(ctx.on_event) as progress:
            task = progress.add_task("Screenplays", total=len(ids))
            for batch_start in range(0, len(ids), config.parallel_batch_size):
                batch = ids[batch_start:batch_start + config.parallel_batch_size]
                coros = [
                    _process_scene(config, project_dir, story_bible, sid, system_prompt, semaphore)
                    for sid in batch
                ]
                results = await asyncio.gather(*coros, return_exceptions=True)
                for sid, result in zip(batch, results):
                    if isinstance(result, Exception):
                        console.print(f"[red]Failed {sid}: {result}[/red]")
                        ctx.log(f"Failed {sid}: {result}", level="error")
                        ctx.record_item_failed(sid)
                    else:
                        ctx.record_item_done(
                            usage=result.usage if result is not None else None,
                        )
                        ctx.progress(ctx.stage_state.items_done, ctx.stage_state.items_total)
                    if task is not None:
                        progress.advance(task)
                ctx.save()

        if len(ctx.stage_state.items_failed) > 0 and ctx.stage_state.items_done == 0:
            raise RuntimeError(
                f"All {len(ctx.stage_state.items_failed)} scenes failed during adapt stage"
            )

        # Now that beats exist, pin within-scene appearance transitions to the
        # depicting beat so the resolver shows pre-transformation panels in the
        # prior look (best-effort; single-writer, after the parallel batch).
        try:
            pinned = _pin_appearance_transitions(project_dir, story_bible)
            if pinned:
                console.print(f"[green]Pinned {pinned} within-scene appearance transition(s).[/green]")
        except Exception as exc:  # noqa: BLE001 — enrichment must not fail the stage
            console.print(f"[yellow]Appearance-transition pinning skipped: {exc}[/yellow]")
            ctx.log(f"appearance pinning skipped: {exc}", level="warning")

        console.print("[green]Adapt stage complete.[/green]")


from novel_to_comic.stages import Stage, clean_cascade  # noqa: E402
from novel_to_comic.state import PipelineState  # noqa: E402


def estimate_cost(config: Config, project_dir: Path, state: PipelineState) -> float:
    story_bible = artifacts.read_story_bible_safe(project_dir)
    if story_bible is None:
        return 0.0

    system_prompt = ""
    if PROMPT_PATH.exists():
        try:
            system_prompt = PROMPT_PATH.read_text()
        except Exception:
            pass
            
    total = 0.0
    for scene in story_bible.scenes:
        if (project_dir / "screenplays" / f"{scene.id}.json").exists():
            continue
        scene_path = project_dir / "scenes" / f"{scene.id}.txt"
        scene_text = ""
        if scene_path.exists():
            try:
                scene_text = scene_path.read_text()
            except Exception:
                pass
        if not scene_text:
            scene_text = "x" * 8000
            
        total += estimate_text_cost(
            config.effective_screenplay_model(),
            system_prompt + "\n" + scene_text,
            output_chars=12000,
        )
    return total


STAGE = Stage(
    name="adapt",
    run=run,
    outputs=lambda d: [d / "screenplays"],
    clean_paths=lambda d: clean_cascade(d, "screenplays"),
    estimate_cost=estimate_cost,
)
