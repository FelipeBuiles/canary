"""Zero-cost OpenAI-compatible replay service for target-pipeline fixtures."""

from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from PIL import Image, ImageOps


def _json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise HTTPException(404, f"Fixture artifact missing: {path.relative_to(path.parents[1])}")
    return json.loads(path.read_text())


def _page_number(payload: dict[str, Any]) -> int:
    """Read the page marker the OCR request carries for fixture resolution."""

    for message in payload.get("messages") or ():
        content = message.get("content")
        parts = content if isinstance(content, list) else [{"text": content}]
        for part in parts:
            text = part.get("text") if isinstance(part, dict) else None
            match = re.search(r"canary_page_number:\s*(\d+)", str(text or ""))
            if match:
                return int(match.group(1))
    raise HTTPException(422, "Page OCR replay requires a canary_page_number marker")


def _feature(payload: dict[str, Any]) -> str:
    metadata = payload.get("metadata") or {}
    nested = metadata.get("metadata") if isinstance(metadata, dict) else {}
    return str((nested or {}).get("feature") or metadata.get("feature") or "")


class TargetFixtureReplay:
    def __init__(self, project_dir: Path) -> None:
        self.project_dir = project_dir.resolve()
        required = (
            "story_bible.json",
            "brief/adaptation_brief.json",
            "adapt/book.json",
            "plan/book.json",
        )
        missing = [name for name in required if not (self.project_dir / name).is_file()]
        if missing:
            raise ValueError(
                "Target fixture project is missing: " + ", ".join(missing)
            )
        self.images = sorted(self.project_dir.rglob("*.png"))
        if not self.images:
            raise ValueError("Target fixture project has no generated PNG assets")

    def structured(self, feature: str) -> Any:
        if feature == "extract.story_bible":
            return _json(self.project_dir / "story_bible.json")
        if feature == "brief.infer":
            return _json(self.project_dir / "brief" / "adaptation_brief.json")
        if feature == "style.suggestions":
            return _json(
                self.project_dir / "samples" / "style_suggestions.json"
            ).get("suggestions", [])
        if feature == "style.sample_brief":
            return _json(
                self.project_dir / "samples" / "style_sample_brief.json"
            )["brief"]
        if feature in {"adapt.narrative_treatment", "adapt.book"}:
            adaptation = _json(self.project_dir / "adapt" / "book.json")
            if feature == "adapt.narrative_treatment":
                return adaptation["treatment"]
            return {
                "beats": adaptation["beats"],
                "ledger": adaptation["ledger"],
            }
        if feature == "plan.book":
            plan = _json(self.project_dir / "plan" / "book.json")
            pages = []
            for selected in plan["pages"]:
                page = _json(
                    self.project_dir
                    / "plan"
                    / "pages"
                    / f"page_{selected['page_number']:03d}.json"
                )
                for generated in (
                    "revision",
                    "content_sha256",
                    "adaptation_revision",
                    "adaptation_sha256",
                ):
                    page.pop(generated, None)
                for content in page.get("content", ()):
                    # Plan allocates lettering by ID; the fixture stores the
                    # materialized canonical page.
                    content["lettering_ids"] = [
                        item["id"] for item in content.pop("lettering", ())
                    ]
                    content.pop("pinned_geometry", None)
                pages.append(page)
            return {
                "rhythm_summary": plan["rhythm_summary"],
                "pages": pages,
                "editorial_issues": plan.get("editorial_issues", []),
            }
        raise HTTPException(422, f"No target fixture callback for feature {feature!r}")

    def page_ocr(self, page_number: int) -> dict[str, Any]:
        """Replay a flawless render: exactly the canonical lettering, in order."""

        page = _json(
            self.project_dir / "plan" / "pages" / f"page_{page_number:03d}.json"
        )
        by_id = {
            item["id"]: item
            for content in page.get("content", ())
            for item in content.get("lettering", ())
        }
        ordered = [by_id[item_id] for item_id in page["reading_order"] if item_id in by_id]
        total = max(1, len(ordered))
        height = min(1.0, 1 / total)
        return {
            "lettering": [
                {
                    "text": item["text"],
                    "box": {
                        "x": 0.05,
                        "y": min(0.99, round(index * height, 4)),
                        "width": 0.9,
                        "height": round(height * 0.9, 4) or 0.01,
                    },
                }
                for index, item in enumerate(ordered)
            ]
        }

    def image(self, prompt: str, width: int, height: int) -> bytes:
        index = int(hashlib.sha256(prompt.encode()).hexdigest()[:12], 16)
        with Image.open(self.images[index % len(self.images)]) as source:
            rendered = ImageOps.fit(
                source.convert("RGB"),
                (width, height),
                method=Image.Resampling.LANCZOS,
            )
            output = io.BytesIO()
            rendered.save(output, format="PNG")
            return output.getvalue()


def create_app(project_dir: Path) -> FastAPI:
    replay = TargetFixtureReplay(project_dir)
    app = FastAPI()

    @app.get("/health/liveliness")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/chat/completions")
    async def chat(payload: dict[str, Any]) -> dict[str, Any]:
        feature = _feature(payload)
        if feature == "draw.page_ocr":
            value: Any = replay.page_ocr(_page_number(payload))
        else:
            value = replay.structured(feature)
        content = json.dumps(value, ensure_ascii=False)
        return {
            "id": "target-fixture-chat",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": content}}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    @app.post("/v1/images/generations")
    async def image(payload: dict[str, Any]) -> dict[str, Any]:
        size = str(payload.get("size") or "1024x1024").split("x")
        width, height = (int(size[0]), int(size[1]))
        data = replay.image(str(payload.get("prompt") or ""), width, height)
        return {"created": 0, "data": [{"b64_json": base64.b64encode(data).decode()}]}

    return app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=4010, type=int)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(create_app(args.source), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
