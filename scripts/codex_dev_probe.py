#!/usr/bin/env python3
"""One opt-in Codex generation per invocation; never writes pipeline artifacts."""
from __future__ import annotations

import argparse
import asyncio
import io
import importlib.util
import json
from pathlib import Path
import sys
import uuid


def _runtime():
    path = Path(__file__).resolve().parents[1] / "novel_to_comic/src/novel_to_comic/ai/codex_runtime.py"
    spec = importlib.util.spec_from_file_location("canary_codex_probe_runtime", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


async def _probe(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    runtime = _runtime()
    output = args.output_dir.expanduser().resolve()
    repository = Path(__file__).resolve().parents[1]
    if output.is_relative_to(repository):
        parser.error("--output-dir must be outside the repository and pipeline projects")
    if args.probe == "edit" and args.source_image is None:
        parser.error("edit requires --source-image from a previous generated result")
    if args.probe != "edit" and args.source_image is not None:
        parser.error("--source-image applies only to edit")
    output.mkdir(parents=True, exist_ok=True)
    run_id = uuid.uuid4().hex
    report_path = output / f"{args.probe}-{run_id}.json"
    report = {"probe": args.probe, "reasoning_model": args.reasoning_model,
              "generation_intent": not args.preflight_only, "generation_attempted": False, "report_path": str(report_path),
              "runtime_image_store": "~/.codex/generated_images",
              "hard_controls": ["ChatGPT typed auth", "gpt-image-2 source selector",
                                "restricted workspace reads", "network/shell/MCP/apps/plugins disabled",
                                "runtime transport retries zero"],
              "prompt_only_controls": ["one image tool invocation", "reference use/order",
                                       "dimensions", "quality", "prompt fidelity"],
              "actual_image_model": None}
    try:
        if args.preflight_only:
            result = await runtime._run({"kind": "image", "model": args.reasoning_model,
                "prompt": "", "references": [], "request_id": run_id, "preflight_only": True})
            report.update(status="completed", metadata=result["metadata"])
        elif args.probe == "structured-text":
            from PIL import Image, ImageDraw, ImageFont

            card = Image.new("RGB", (640, 180), "white")
            drawing = ImageDraw.Draw(card)
            font = ImageFont.load_default(size=72)
            drawing.text((80, 40), "CANARY", font=font, fill="black")
            buffer = io.BytesIO()
            card.save(buffer, format="PNG")
            attachment = buffer.getvalue()
            input_path = output / f"structured-text-{run_id}-input.png"
            input_path.write_bytes(attachment)
            report["vision_input"] = runtime.validate_image_bytes(attachment, "image/png")
            report["vision_input_path"] = str(input_path)
            schema = {"type": "object", "properties": {"text": {"type": "string"}},
                      "required": ["text"], "additionalProperties": False}
            result = await runtime.run_text(model=args.reasoning_model,
                system_prompt="Return only a JSON object matching the supplied schema. Do not use tools.",
                user_content="Transcribe the word visible in the attached image exactly.",
                json_schema=schema, image_attachments=((attachment, "image/png"),))
            artifact = output / f"structured-text-{run_id}.txt"
            artifact.write_text(result.text, encoding="utf-8")
            report.update(artifact_path=str(artifact), metadata=result.metadata,
                          schema_valid=json.loads(result.text) == {"text": "CANARY"})
            if not report["schema_valid"]:
                report["status"] = "invalid_structured_output"
            else:
                report["status"] = "completed"
        else:
            refs = ()
            prompt = "Create a simple square illustration: a red ceramic mug on a plain cream background. No text."
            if args.probe == "edit":
                source = args.source_image.expanduser().resolve()
                if not source.is_file() or source.stat().st_size > runtime.MAX_IMAGE_BYTES:
                    raise runtime.CodexRuntimeError("invalid_source_image")
                data = source.read_bytes()
                source_info = runtime.validate_image_bytes(data)
                refs = ((data, source_info["mime"]),)
                report["source_image"] = source_info
                prompt = "Edit the provided image: change only the red mug to blue, preserving composition and background."
            result = await runtime.run_image(reasoning_model=args.reasoning_model, prompt=prompt,
                references=refs, requested_model="gpt-image-2", request_id=run_id, diagnostics=True,
                reference_roles=("edit_parent",) if refs else (),
                reference_instructions=("Preserve composition and background.",) if refs else (),
                edit_parent_indices=(0,) if refs else ())
            info = runtime.validate_image_bytes(result.image_bytes)
            suffix = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}[info["mime"]]
            artifact = output / f"{args.probe}-{run_id}{suffix}"
            artifact.write_bytes(result.image_bytes)
            report.update(status="completed", artifact_path=str(artifact), image=info,
                          metadata=result.metadata, human_visual_review_required=True)
    except runtime.CodexRuntimeError as exc:
        report.update(status="failed", error=exc.code, metadata=exc.metadata)
    except (ValueError, OSError) as exc:
        report.update(status="failed", error=type(exc).__name__)
    report["generation_attempted"] = report.get("metadata", {}).get("submitted", False)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report.get("status") == "completed" else 2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe", choices=("structured-text", "image", "edit"),
                        help="Explicitly authorize one fresh allowance-consuming turn")
    parser.add_argument("--output-dir", type=Path, help="Explicit non-pipeline output area outside this repository")
    parser.add_argument("--preflight-only", action="store_true",
                        help="Inspect isolated image capability gates without starting any turn")
    parser.add_argument("--source-image", type=Path, help="Previous generated image used by the edit probe")
    parser.add_argument("--reasoning-model", help="Explicit target (default: text gpt-5.6-terra; image/edit gpt-5.5)")
    args = parser.parse_args()
    if args.probe is None:
        parser.print_help()
        return 0
    if args.output_dir is None:
        parser.error("--probe requires --output-dir")
    if args.preflight_only and args.probe != "image":
        parser.error("--preflight-only requires --probe image")
    if args.reasoning_model is None:
        args.reasoning_model = "gpt-5.6-terra" if args.probe == "structured-text" else "gpt-5.5"
    return asyncio.run(_probe(args, parser))


if __name__ == "__main__":
    raise SystemExit(main())
