"""Explicit reference attachments for Cast corrections: project assets or author uploads."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from novel_to_comic import artifacts
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset
from novel_to_comic.uploaded_images import decode_uploaded_image
from novel_to_comic.workspace import series_root


class CastAssetReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_type: Literal["character", "location", "prop"]
    asset_id: str = Field(min_length=1)
    state_id: str | None = None

    @field_validator("asset_id", "state_id")
    @classmethod
    def safe_id(cls, value):
        if value is not None and (not value or value in {".", ".."} or any(c in value for c in "/\\\x00")):
            raise ValueError("Invalid asset identifier")
        return value


class UploadedReference(BaseModel):
    """An image the author uploaded for this correction (see ``store_reference_upload``)."""
    model_config = ConfigDict(extra="forbid")
    upload_id: str = Field(pattern=r"^[a-f0-9]{32}$")


CastReferenceInput = CastAssetReference | UploadedReference
_INPUT = TypeAdapter(CastReferenceInput)


def parse_reference_input(value) -> CastReferenceInput:
    return _INPUT.validate_python(value)


def store_reference_upload(project_dir: Path, image_bytes: bytes, suffix: str, filename: str | None) -> dict:
    """Persist validated image bytes once per content; return the attachment descriptor."""
    upload_id = hashlib.sha256(image_bytes).hexdigest()[:32]
    image_path = artifacts.reference_upload_path(project_dir, upload_id, suffix)
    meta_path = artifacts.reference_upload_path(project_dir, upload_id, ".json")
    image_path.parent.mkdir(parents=True, exist_ok=True)
    if not image_path.is_file():
        image_path.write_bytes(image_bytes)
    label = (Path(filename or "").name.strip() or "Uploaded image")[:120]
    if not meta_path.is_file():
        meta_path.write_text(json.dumps({"suffix": suffix, "label": label}, sort_keys=True))
    return upload_descriptor(project_dir, upload_id)


def _upload_image(project_dir: Path, upload_id: str) -> tuple[Path, str]:
    try:
        meta = json.loads(artifacts.reference_upload_path(project_dir, upload_id, ".json").read_text())
        path = artifacts.reference_upload_path(project_dir, upload_id, meta["suffix"])
    except (OSError, ValueError, KeyError, TypeError):
        raise HTTPException(400, "An uploaded reference image is no longer available. Upload it again.") from None
    if not path.is_file():
        raise HTTPException(400, "An uploaded reference image is no longer available. Upload it again.")
    return path, str(meta.get("label") or "Uploaded image")


def upload_descriptor(project_dir: Path, upload_id: str) -> dict:
    path, label = _upload_image(project_dir, upload_id)
    return {"upload_id": upload_id, "label": label,
            "image_path": path.relative_to(series_root(project_dir)).as_posix()}


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
            current = [parse_reference_input(item) for item in entry.get("reference_assets", [])]
    return current


def _resolve_upload(project_dir: Path, item: UploadedReference) -> ReferenceAsset:
    path, label = _upload_image(project_dir, item.upload_id)
    data = path.read_bytes()
    try:
        decode_uploaded_image(data, path.suffix)
    except ValueError as exc:
        raise HTTPException(400, f"The uploaded reference {label} is unreadable. Upload it again.") from exc
    return ReferenceAsset(
        path=path, role="prop", entity_id=None, appearance_state_id=None,
        authority_scope=AuthorityScope.CONTEXTUAL, preserve_facets=(), ignore_facets=(),
        pose=None, content_sha256=hashlib.sha256(data).hexdigest(),
        lineage_parent_sha256=None, label=label, purpose="instruction_context",
    )


def resolve_reference_inputs(project_dir: Path, attachments, *, target=None):
    from novel_to_comic.cast_instructions import resolve_cast_asset

    selected = []
    seen = set()
    for item in attachments:
        if isinstance(item, UploadedReference):
            if item.upload_id in seen:
                raise HTTPException(400, "The same reference image was attached twice.")
            seen.add(item.upload_id)
            selected.append(_resolve_upload(project_dir, item))
            continue
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
        if not path.is_file() or not path.resolve().is_relative_to(series_root(project_dir).resolve()):
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
