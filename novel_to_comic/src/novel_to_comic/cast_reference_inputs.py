"""Explicit, project-local reference attachments for Cast corrections."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator

from novel_to_comic import artifacts
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset


class CastReferenceInput(BaseModel):
    asset_type: Literal["character", "location", "prop"]
    asset_id: str = Field(min_length=1)
    state_id: str | None = None

    @field_validator("asset_id", "state_id")
    @classmethod
    def safe_id(cls, value):
        if value is not None and (not value or value in {".", ".."} or any(c in value for c in "/\\\x00")):
            raise ValueError("Invalid asset identifier")
        return value


def saved_reference_inputs(project_dir, asset_type, asset_id, state_id=None):
    from novel_to_comic.cast_instructions import _instructions_path

    path = _instructions_path(project_dir, asset_type, asset_id, state_id)
    if not path.exists():
        return []
    current = []
    for line in path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("patch", {}).get("addendum") or entry.get("operation") == "restore":
            current = [CastReferenceInput.model_validate(item) for item in entry.get("reference_assets", [])]
    return current


def resolve_reference_inputs(project_dir: Path, attachments, *, target=None):
    from novel_to_comic.cast_instructions import resolve_cast_asset

    selected = []
    seen = set()
    for item in attachments:
        key = (item.asset_type, item.asset_id, item.state_id)
        if key == target:
            raise HTTPException(400, "Choose a different asset to compare against.")
        if key in seen:
            raise HTTPException(400, "The same reference asset was selected twice.")
        seen.add(key)
        if item.asset_type == "prop" and item.state_id:
            raise HTTPException(400, "Prop appearance attachments are not supported.")
        entity, state = resolve_cast_asset(project_dir, *key)
        if item.asset_type == "character":
            path = (artifacts.character_state_ref_sheet_path(project_dir, item.asset_id, item.state_id)
                    if item.state_id else artifacts.character_ref_sheet_path(project_dir, item.asset_id))
            role = "subject"
        elif item.asset_type == "location":
            path = (artifacts.location_state_plate_path(project_dir, item.asset_id, item.state_id)
                    if item.state_id else artifacts.location_plate_path(project_dir, item.asset_id))
            role = "location_plate"
        else:
            path, role = artifacts.prop_ref_path(project_dir, item.asset_id), "prop"
        if not path.is_file() or not path.resolve().is_relative_to(project_dir.resolve()):
            raise HTTPException(400, f"Generate the reference image for {entity.name} first.")
        from PIL import Image
        try:
            with Image.open(path) as image:
                image.verify()
        except (OSError, ValueError) as exc:
            raise HTTPException(400, f"Regenerate the unreadable reference image for {entity.name}.") from exc
        selected.append(ReferenceAsset(
            path=path, role=role, entity_id=item.asset_id, appearance_state_id=item.state_id,
            authority_scope=AuthorityScope.CONTEXTUAL, preserve_facets=(), ignore_facets=(),
            pose=None, content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
            lineage_parent_sha256=None, label=entity.name + (f" · {state.label}" if state else ""),
            purpose="instruction_context",
        ))
    return selected


def with_cast_reference_inputs(config, project_dir, input_data, plan):
    from novel_to_comic.asset_generation import reference_plan_for_assets

    kind = input_data.asset_kind
    asset_type = {"character_ref": "character", "character_state_ref": "character",
                  "location_plate": "location", "location_state_plate": "location", "prop_ref": "prop"}.get(kind)
    if asset_type is None:
        return plan
    if asset_type == "character":
        subject = input_data.prompt.subjects[0]
        entity_id, state_id = subject.character_id, subject.appearance_state_id
    else:
        anchor = input_data.prompt.anchors[0]
        entity_id, state_id = anchor.entity_id, anchor.appearance_state_id
    if asset_type == "prop" and state_id:
        return plan
    attachments = saved_reference_inputs(project_dir, asset_type, entity_id, state_id or None)
    if not attachments:
        return plan
    refs = resolve_reference_inputs(project_dir, attachments, target=(asset_type, entity_id, state_id or None))
    return reference_plan_for_assets(config, [*plan.selected, *refs])
