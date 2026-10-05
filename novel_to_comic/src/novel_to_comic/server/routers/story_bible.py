"""Author edits to the series Story Bible: characters, places, props and looks.

Every write carries the Story Bible revision the editor loaded, so a stale
editor never overwrites newer work. Removing or merging away something an
adapted part names is refused with the parts that name it. Edits change the
Story Bible only: changed descriptions flag that entity's Cast references,
which the author regenerates or keeps from Cast.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, ValidationError

from novel_to_comic import artifacts
from novel_to_comic.models.story_bible import StoryBible, blank_visual_anchors
from novel_to_comic.state import StageStatus
from novel_to_comic.story_bible_edits import (
    AnchorAlreadySet,
    EditRejected,
    EntityCited,
    StaleStoryBible,
    add_entity,
    add_state,
    apply_edit,
    citation_index,
    edit_entity,
    edit_impact,
    edit_state,
    editable_scene_ids,
    fill_blank_anchor,
    merge_entities,
    possible_duplicates,
    refuse_if_cited,
    remove_entity,
    remove_state,
    restore_excluded,
    undo_last_edit,
    undo_preview,
)
from novel_to_comic.target_artifacts import ArtifactInvalid, ArtifactMissing, TargetArtifacts

from ..auth import get_current_user
from ..deps import get_project

router = APIRouter()

Kind = Literal["characters", "locations", "props"]


class Revisioned(BaseModel):
    expected_revision: int = Field(ge=1)


class EntityEdit(Revisioned):
    changes: dict[str, Any]


class EntityAdd(Revisioned):
    details: dict[str, Any]
    scene_ids: list[str] = Field(default=[], max_length=500)


class EntityMerge(Revisioned):
    into: str = Field(min_length=1)


class StateAdd(Revisioned):
    details: dict[str, Any]
    starts_at_scene: str | None = None


class StateEdit(Revisioned):
    changes: dict[str, Any]


class VisualAnchorFill(BaseModel):
    entity_id: str = Field(min_length=1)
    appearance_state_id: str | None = None
    visual_anchor: str = Field(min_length=1, max_length=2000)


class DraftRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    aliases: list[str] = Field(default=[], max_length=10)
    note: str = Field(default="", max_length=1000)


@contextmanager
def _edit_errors():
    try:
        yield
    except StaleStoryBible as exc:
        raise HTTPException(409, {"code": "stale_story_bible", "message": str(exc)}) from exc
    except EntityCited as exc:
        raise HTTPException(409, {"code": "entity_cited", "message": str(exc), "parts": exc.parts}) from exc
    except AnchorAlreadySet as exc:
        raise HTTPException(409, str(exc)) from exc
    except EditRejected as exc:
        raise HTTPException(422, str(exc)) from exc
    except ValidationError as exc:
        from novel_to_comic.clients.structured_call import validation_error_summary

        raise HTTPException(422, validation_error_summary(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, f"Not in the Story Bible: {exc.args[0]}") from exc
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc


def _carry_references(config, root, kind: str, entity_id: str):
    """Keep the entity's current references when the edit changed no appearance."""
    from novel_to_comic.stages.s3_cast import carry_over_references

    return lambda before, after: carry_over_references(config, root, before, after, kind, entity_id)


def _saved(bible: StoryBible, **extra) -> dict:
    return {"story_bible": bible, "revision": bible.revision, **extra}


def _name(bible: StoryBible, kind: str, entity_id: str) -> str:
    return next((item.name for item in getattr(bible, kind) if item.id == entity_id), entity_id)


def _look(bible: StoryBible, kind: str, entity_id: str, state_id: str) -> str:
    entity = next((item for item in getattr(bible, kind) if item.id == entity_id), None)
    states = entity.appearance_states if entity is not None else []
    return next((state.label for state in states if state.id == state_id), state_id)


def _change(action: str, kind: str, entity_id: str, *, into: str | None = None, state_id: str | None = None):
    """Describe an edit for Undo by names, read from the Bible it applied to."""

    def describe(before: StoryBible, after: StoryBible) -> dict:
        source = before if any(item.id == entity_id for item in getattr(before, kind)) else after
        change = {"action": action, "kind": kind, "entity_id": entity_id, "name": _name(source, kind, entity_id)}
        if into is not None:
            change["into"] = _name(before, kind, into)
        if state_id is not None:
            change["look"] = _look(before if action != "add_look" else after, kind, entity_id, state_id)
        return change

    return describe


@router.get("/story-bible/editor")
def story_bible_editor(project=Depends(get_project)):
    """The Story Bible with what the editor needs to keep edits safe."""
    from novel_to_comic.stages.s3_cast import reference_freshness
    from novel_to_comic.cast_roster import story_bible_api_view

    root, config, _state = project
    with _edit_errors():
        bible = artifacts.read_story_bible(root)
    entities, states = citation_index(root)
    try:
        manifest = TargetArtifacts(root).read_part_manifest()
        parts = [{"id": part.id, "title": part.title, "ordinal": part.ordinal} for part in manifest.parts]
    except (ArtifactMissing, ArtifactInvalid):
        parts = []
    state_citations: dict[str, dict[str, list[str]]] = {}
    for (entity_id, state_id), titles in states.items():
        state_citations.setdefault(entity_id, {})[state_id] = titles
    return {
        "undo": undo_preview(root, bible),
        "possible_duplicates": possible_duplicates(bible, entities),
        "story_bible": story_bible_api_view(bible, root),
        "revision": bible.revision,
        "parts": parts,
        "editable_scene_ids": sorted(editable_scene_ids(root, bible)),
        "citations": entities,
        "state_citations": state_citations,
        "references": reference_freshness(config, root),
    }


@router.post("/story-bible/undo")
def undo_story_bible_edit(body: Revisioned, project=Depends(get_project)):
    """Reverse the newest author edit, if nothing has changed the Bible since."""
    root, _config, _state = project
    with _edit_errors():
        bible, change = undo_last_edit(root, body.expected_revision)
    return _saved(bible, undone=change)


@router.get("/story-bible/{kind}/draft-estimate")
def draft_estimate(
    kind: Kind, name: str = Query(min_length=1, max_length=200), aliases: list[str] = Query(default=[]),
    project=Depends(get_project),
):
    """What drafting this name would cost, from the passages it would send."""
    from novel_to_comic.codex_dev import classify_operations
    from novel_to_comic.entity_drafting import NoMentions, draft_cost, mention_passages
    from ..credits import credit_estimate_for_provider_cost

    root, config, _state = project
    try:
        passages, scene_ids = mention_passages(root, [name, *aliases[:10]])
    except NoMentions as exc:
        return {"mentioned": False, "message": str(exc), "mentioned_scene_ids": []}
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    funding = classify_operations((("text", config.effective_extraction_model()),))
    estimate = credit_estimate_for_provider_cost(
        draft_cost(config, kind, name, passages), "extract", reserve=True, funding=funding,
    )
    return {"mentioned": True, "estimate": estimate, "mentioned_scene_ids": scene_ids}


@router.post("/story-bible/{kind}/draft")
async def draft_story_bible_entity(
    kind: Kind, body: DraftRequest, project_id: str, project=Depends(get_project),
    user_id: str = Depends(get_current_user),
):
    """Propose details for an entity the author is adding, from the source text.

    Only passages that mention the name are sent. Nothing is saved.
    """
    from novel_to_comic.codex_dev import CodexRoutingError
    from novel_to_comic.entity_drafting import NoMentions, draft_cost, draft_entity, mention_passages
    from ..credited_job import run_credited_call

    root, config, _state = project
    try:
        passages, scene_ids = mention_passages(root, [body.name, *body.aliases])
    except NoMentions as exc:
        raise HTTPException(422, str(exc)) from exc
    except ArtifactMissing as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        draft = await run_credited_call(
            user_id=user_id, project_id=project_id, project_dir=root, stage="extract",
            estimated_cost_usd=draft_cost(config, kind, body.name, passages, body.note),
            operations=(("text", config.effective_extraction_model()),),
            work=lambda: draft_entity(config, kind, body.name, passages, body.note),
        )
    except CodexRoutingError as exc:
        raise HTTPException(409, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(502, str(exc)) from exc
    editable = editable_scene_ids(root, artifacts.read_story_bible(root))
    return {
        "details": {"name": body.name, "aliases": body.aliases, **draft},
        "suggested_scene_ids": [scene_id for scene_id in scene_ids if scene_id in editable],
        "mentioned_scene_ids": scene_ids,
    }


@router.post("/story-bible/visual-anchor")
def fill_visual_anchor(body: VisualAnchorFill, project=Depends(get_project)):
    """Add a missing visual anchor without resetting any stage.

    Existing anchors stay verbatim: only a blank one can be filled. An entry
    with no written look cannot reach Plan, so no page was drawn from it; an
    existing Cast image of it turns out of date for the author to keep or redo.
    Admission already holds this behind a running Extract.
    """
    root, _config, state = project
    if any(stage.status == StageStatus.RUNNING for stage in state.stages.values()):
        raise HTTPException(409, "Wait for the running stage to finish before adding a visual anchor.")
    with _edit_errors():
        bible = fill_blank_anchor(root, body.entity_id, body.appearance_state_id, body.visual_anchor)
    return _saved(bible, missing_visual_anchors=blank_visual_anchors(bible))


@router.patch("/story-bible/{kind}/{entity_id}")
def edit_story_bible_entity(kind: Kind, entity_id: str, body: EntityEdit, project=Depends(get_project)):
    root, config, _state = project
    with _edit_errors():
        bible, _ = apply_edit(
            root, body.expected_revision, lambda current: edit_entity(current, kind, entity_id, body.changes),
            on_saved=_carry_references(config, root, kind, entity_id),
            change=_change("edit", kind, entity_id),
        )
    return _saved(bible)


@router.post("/story-bible/{kind}")
def add_story_bible_entity(kind: Kind, body: EntityAdd, project=Depends(get_project)):
    root, _config, _state = project
    added: dict[str, str] = {}

    def edit(current: StoryBible):
        result, new_id = add_entity(current, kind, body.details, body.scene_ids, editable_scene_ids(root, current))
        added["id"] = new_id
        return result, new_id

    with _edit_errors():
        bible, entity_id = apply_edit(
            root, body.expected_revision, edit,
            change=lambda before, after: _change("add", kind, added["id"])(before, after),
        )
    return _saved(bible, entity_id=entity_id)


@router.delete("/story-bible/{kind}/{entity_id}")
def remove_story_bible_entity(
    kind: Kind, entity_id: str, expected_revision: int = Query(ge=1), project=Depends(get_project),
):
    root, _config, _state = project

    def edit(current: StoryBible) -> StoryBible:
        refuse_if_cited(root, entity_id, action="remove it")
        return remove_entity(current, kind, entity_id)

    with _edit_errors():
        bible, _ = apply_edit(root, expected_revision, edit, change=_change("remove", kind, entity_id))
    return _saved(bible)


@router.post("/story-bible/{kind}/{entity_id}/merge")
def merge_story_bible_entity(kind: Kind, entity_id: str, body: EntityMerge, project=Depends(get_project)):
    """Fold this entry into ``into``; its name becomes an alias there."""
    root, _config, _state = project

    def edit(current: StoryBible) -> StoryBible:
        refuse_if_cited(root, entity_id, action="merge it away")
        return merge_entities(current, kind, entity_id, body.into)

    with _edit_errors():
        bible, _ = apply_edit(root, body.expected_revision, edit,
                              change=_change("merge", kind, entity_id, into=body.into))
    return _saved(bible)


@router.post("/story-bible/{kind}/{entity_id}/states")
def add_story_bible_state(kind: Kind, entity_id: str, body: StateAdd, project=Depends(get_project)):
    root, _config, _state = project
    added: dict[str, str] = {}

    def edit(current: StoryBible):
        result, new_id = add_state(current, kind, entity_id, body.details, body.starts_at_scene)
        added["id"] = new_id
        return result, new_id

    with _edit_errors():
        bible, state_id = apply_edit(
            root, body.expected_revision, edit,
            change=lambda before, after: _change("add_look", kind, entity_id, state_id=added["id"])(before, after),
        )
    return _saved(bible, state_id=state_id)


@router.patch("/story-bible/{kind}/{entity_id}/states/{state_id}")
def edit_story_bible_state(
    kind: Kind, entity_id: str, state_id: str, body: StateEdit, project=Depends(get_project),
):
    root, config, _state = project
    with _edit_errors():
        bible, _ = apply_edit(
            root, body.expected_revision,
            lambda current: edit_state(current, kind, entity_id, state_id, body.changes),
            on_saved=_carry_references(config, root, kind, entity_id),
            change=_change("edit_look", kind, entity_id, state_id=state_id),
        )
    return _saved(bible)


@router.delete("/story-bible/{kind}/{entity_id}/states/{state_id}")
def remove_story_bible_state(
    kind: Kind, entity_id: str, state_id: str, expected_revision: int = Query(ge=1),
    project=Depends(get_project),
):
    root, _config, _state = project

    def edit(current: StoryBible) -> StoryBible:
        refuse_if_cited(root, entity_id, state_id, action="remove this look")
        return remove_state(current, kind, entity_id, state_id)

    with _edit_errors():
        bible, _ = apply_edit(root, expected_revision, edit,
                              change=_change("remove_look", kind, entity_id, state_id=state_id))
    return _saved(bible)


@router.delete("/story-bible/excluded/{kind}/{name}")
def restore_story_bible_name(
    kind: Kind, name: str, expected_revision: int = Query(ge=1), project=Depends(get_project),
):
    """Bring a removed entry back, or let later extractions find a removed name again."""
    root, _config, _state = project
    with _edit_errors():
        bible, _ = apply_edit(root, expected_revision, lambda current: restore_excluded(current, kind, name),
                              change={"action": "restore", "kind": kind, "name": name})
    return _saved(bible)


@router.get("/story-bible/{kind}/{entity_id}/impact")
def story_bible_edit_impact(
    kind: Kind, entity_id: str, action: Literal["remove", "merge"] = "remove", into: str | None = None,
    project=Depends(get_project),
):
    """What removing or merging this entry would change. Reads only."""
    root, config, _state = project
    if action == "merge" and not into:
        raise HTTPException(422, "Choose the entry to keep.")
    if into == entity_id:
        raise HTTPException(422, "Choose two different entries to merge.")
    with _edit_errors():
        return edit_impact(config, root, kind, entity_id, merge_into=into if action == "merge" else None)
