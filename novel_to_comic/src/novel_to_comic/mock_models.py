"""Local OpenAI-compatible replay service for zero-cost UI demos.

The service replays structured text and image material from an existing Canary
project. It intentionally sits behind the ordinary AI HTTP boundary so stage
lifecycle, persistence, retries, events, and UI behavior remain real.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from PIL import Image, ImageOps


_SCENE_RE = re.compile(r"\bscene_\d{3}\b", re.IGNORECASE)


def _json(path: Path) -> Any:
    return json.loads(path.read_text())


def _feature(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") or {}
    nested = metadata.get("metadata") if isinstance(metadata, dict) else {}
    return str((nested or {}).get("feature") or metadata.get("feature") or "")


def _scene_id(text: str) -> str:
    match = _SCENE_RE.search(text)
    if not match:
        raise HTTPException(422, "Mock fixture could not identify a scene_id in the request")
    return match.group(0).lower()


def _plan_response(project_dir: Path, scene_id: str) -> dict[str, Any]:
    plan = _json(project_dir / "plan" / "layout_plan.json")
    scene_panels = [p for p in plan.get("planned_panels", []) if p.get("scene_id") == scene_id]
    panels: list[dict[str, Any]] = []
    panel_index: dict[str, int] = {}
    for index, panel in enumerate(scene_panels, start=1):
        panel_id = str(panel["panel_id"])
        panel_index[panel_id] = index
        beat_indices = [
            int(str(beat_id).rsplit("_", 1)[-1])
            for beat_id in panel.get("beat_ids", [])
        ]
        panels.append({
            "beat_indices": beat_indices,
            "characters_present": panel.get("characters_present", []),
            "character_actions": panel.get("character_actions", {}),
            "character_expressions": panel.get("character_expressions", {}),
            "key_objects": panel.get("key_objects", []),
            "visual_requirements": panel.get("visual_requirements", []),
            "shot_type": panel.get("shot_type", "medium"),
            "camera_angle": panel.get("camera_angle", "eye-level"),
            "camera_note": panel.get("camera_note", ""),
            "lighting": panel.get("lighting", "fixture lighting"),
            "mood": panel.get("mood", "neutral"),
            "background_description": panel.get("background_description", ""),
            "use_scene_location": panel.get("use_scene_location", True),
            "importance": panel.get("importance", "standard"),
            "shape_intent": panel.get("shape_intent", "rect"),
            "transition_out": panel.get("transition_out"),
            "page_break_after": False,
        })
    decisions = []
    for decision in plan.get("narration_decisions", []):
        if decision.get("scene_id") != scene_id:
            continue
        decisions.append({
            "beat_index": decision["beat_index"],
            "decision": decision["decision"],
            "mode": decision.get("mode"),
            "panel_index": panel_index.get(decision.get("panel_id")),
            "preferred_zone": decision.get("preferred_zone", "top"),
            "decision_reason": decision.get("decision_reason", "Replayed fixture decision."),
        })
    if not panels:
        raise HTTPException(404, f"No planned panels in fixture for {scene_id}")
    # A saved project may predate today's panel-density caps. Run the same
    # deterministic recovery used by Stage 5 so replay remains valid as the
    # planner contract tightens, without spending three mock retry attempts.
    from novel_to_comic.models.layout_plan import LLMNarrationDecisionSpec, LLMPanelSpec
    from novel_to_comic.models.panel import Screenplay
    from novel_to_comic.stages.s5_layout_plan import _autosplit_overflow_panels

    screenplay = Screenplay.model_validate_json(
        (project_dir / "screenplays" / f"{scene_id}.json").read_text()
    )
    panel_specs = [LLMPanelSpec.model_validate(item) for item in panels]
    decision_specs = [LLMNarrationDecisionSpec.model_validate(item) for item in decisions]
    panel_specs, decision_specs, _split_count = _autosplit_overflow_panels(
        panel_specs, decision_specs, screenplay.beats,
    )
    return {
        "panels": [item.model_dump(mode="json") for item in panel_specs],
        "narration_decisions": [item.model_dump(mode="json") for item in decision_specs],
    }


class FixtureReplay:
    def __init__(self, project_dir: Path):
        self.project_dir = project_dir.resolve()
        required = ("story_bible.json", "samples/style_suggestions.json", "plan/layout_plan.json")
        missing = [name for name in required if not (self.project_dir / name).is_file()]
        if missing:
            raise ValueError(f"Mock fixture project is missing: {', '.join(missing)}")
        self._prompt_images: dict[str, Path] = {}
        self._images: list[Path] = []
        for meta_path in self.project_dir.rglob("*.png.meta.json"):
            image_path = Path(str(meta_path)[:-len(".meta.json")])
            if not image_path.is_file():
                continue
            self._images.append(image_path)
            try:
                meta = _json(meta_path)
            except (OSError, ValueError):
                continue
            prompt = meta.get("prompt")
            if isinstance(prompt, str) and prompt:
                self._prompt_images[hashlib.sha256(prompt.encode()).hexdigest()] = image_path
        if not self._images:
            raise ValueError("Mock fixture project has no generated PNG assets")
        self._images.sort()

    def text(self, payload: dict[str, Any]) -> str:
        feature = _feature(payload)
        messages = payload.get("messages") or []
        user = str(messages[-1].get("content") or "") if messages else ""
        if feature == "extract.story_bible":
            value = _json(self.project_dir / "story_bible.json")
        elif feature == "style.suggestions":
            value = _json(self.project_dir / "samples" / "style_suggestions.json").get("suggestions", [])
        elif feature == "style.sample_brief":
            value = _json(self.project_dir / "samples" / "style_sample_brief.json")["brief"]
        elif feature == "adapt.screenplay":
            value = _json(self.project_dir / "screenplays" / f"{_scene_id(user)}.json")
        elif feature == "plan.scene_layout":
            value = _plan_response(self.project_dir, _scene_id(user))
        elif feature == "prompt.visual_brief":
            value = (
                "A solitary investigator studies weathered papers beneath a shaded desk lamp "
                "while deep architectural shadows gather behind him and the room remains still."
            )
        elif feature == "compose.lettering_style":
            path = self.project_dir / "assembly" / "lettering_style.json"
            source = _json(path) if path.is_file() else {}
            value = {
                "label": source.get("label", "Cthulhu Replay Lettering"),
                "rationale": source.get("rationale", "High-contrast lettering for the replay art."),
                "theme": source.get("theme", "noir"),
                "font_pair": source.get("font_pair", "horror"),
                "vars": source.get("vars", {}),
            }
        elif feature == "compose.translate_text":
            marker = "Items:\n"
            try:
                items = json.loads(user.split(marker, 1)[1])
            except (IndexError, ValueError):
                items = []
            # Preserve fixture lettering while exercising the translation
            # callback, page traversal, parsing, and persistence paths.
            value = {"items": [
                {"id": item.get("id"), "text": item.get("text", "")}
                for item in items if isinstance(item, dict) and item.get("id")
            ]}
        else:
            raise HTTPException(422, f"No text fixture callback for feature {feature!r}")
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False)

    def image(self, prompt: str, width: int, height: int) -> bytes:
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()
        source = self._prompt_images.get(prompt_hash)
        if source is None:
            index = int(prompt_hash[:12], 16) % len(self._images)
            source = self._images[index]
        with Image.open(source) as image:
            rendered = ImageOps.fit(image.convert("RGB"), (width, height), method=Image.Resampling.LANCZOS)
            output = io.BytesIO()
            rendered.save(output, format="PNG", optimize=True)
            return output.getvalue()


def _dimension(payload: dict[str, Any], key: str, fallback: int) -> int:
    value = payload.get(key)
    try:
        return max(256, min(4096, int(value)))
    except (TypeError, ValueError):
        return fallback


def create_app(project_dir: Path) -> FastAPI:
    replay = FixtureReplay(project_dir)
    app = FastAPI(title="Canary Mock Model Replay", docs_url=None, redoc_url=None)

    @app.get("/health/liveliness")
    async def health() -> dict[str, str]:
        return {"status": "ok", "fixture": replay.project_dir.name}

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> dict[str, Any]:
        payload = await request.json()
        text = replay.text(payload)
        return {
            "id": f"mock-{hashlib.sha256(text.encode()).hexdigest()[:16]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "canary-mock",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": text}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            "_hidden_params": {"response_cost": 0.0},
        }

    async def image_payload(request: Request) -> dict[str, Any]:
        content_type = request.headers.get("content-type", "")
        if content_type.startswith("multipart/form-data"):
            form = await request.form()
            payload = {key: value for key, value in form.items() if isinstance(value, str)}
            raw_metadata = payload.get("metadata")
            if raw_metadata:
                try:
                    payload["metadata"] = json.loads(raw_metadata)
                except ValueError:
                    pass
        else:
            payload = await request.json()
        prompt = str(payload.get("prompt") or "")
        width = _dimension(payload, "canary_requested_width", 1024)
        height = _dimension(payload, "canary_requested_height", 1024)
        image_bytes = replay.image(prompt, width, height)
        return {
            "created": int(time.time()),
            "model": "canary-mock",
            "data": [{"b64_json": base64.b64encode(image_bytes).decode()}],
            "usage": {"cost": 0.0},
            "_hidden_params": {"response_cost": 0.0},
        }

    app.post("/v1/images/generations")(image_payload)
    app.post("/v1/images/edits")(image_payload)
    return app


def app_from_env() -> FastAPI:
    raw = os.environ.get("CANARY_MOCK_FIXTURE_PROJECT", "").strip()
    if not raw:
        raise RuntimeError("Set CANARY_MOCK_FIXTURE_PROJECT to a completed Canary project directory")
    return create_app(Path(raw))


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Canary's local zero-cost model replay service")
    parser.add_argument("--source", required=True, type=Path, help="Existing Canary project to replay")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4010, type=int)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args.source), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
