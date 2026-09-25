#!/usr/bin/env python3
"""One opt-in Claude Code subscription request per invocation; never writes pipeline artifacts.

Run with the backend environment so the runtime's package imports resolve:

    novel_to_comic/.venv/bin/python scripts/claude_dev_probe.py structured --output-dir ~/claude-probes
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import uuid

_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["title", "panels"],
    "properties": {
        "title": {"type": "string"},
        "panels": {"type": "array", "minItems": 1, "maxItems": 4, "items": {"type": "string"}},
    },
}


async def _probe(args: argparse.Namespace, parser: argparse.ArgumentParser) -> int:
    from novel_to_comic.ai import claude_runtime
    from novel_to_comic.text_models import text_wire

    output = args.output_dir.expanduser().resolve()
    if output.is_relative_to(Path(__file__).resolve().parents[1]):
        parser.error("--output-dir must be outside the repository and pipeline projects")
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / f"{args.probe}-{uuid.uuid4().hex}.json"
    wire = text_wire(args.model)
    limit = 2_048 + wire.thinking_headroom_tokens
    if wire.max_output_tokens:
        limit = min(limit, wire.max_output_tokens)
    report: dict = {"probe": args.probe, "model": args.model, "effort": wire.effort,
                    "max_output_tokens": limit, "report_path": str(report_path)}
    try:
        result = await claude_runtime.run_text(
            model=args.model,
            system_prompt="You adapt short prose into comic panel beats.",
            user_content="Adapt: The lighthouse keeper found a letter in a bottle, addressed to him.",
            json_schema=_SCHEMA if args.probe == "structured" else None,
            effort=wire.effort, max_output_tokens=limit,
        )
        report.update(status="completed", text=result.text, metadata=result.metadata)
        if args.probe == "structured":
            report["parsed"] = json.loads(result.text)
    except claude_runtime.ClaudeRuntimeError as exc:
        report.update(status="failed", error=str(exc), metadata=exc.metadata)
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({key: report.get(key) for key in ("status", "error", "report_path")}, indent=2))
    return 0 if report["status"] == "completed" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="One Claude Code subscription request; writes a JSON report.")
    parser.add_argument("probe", choices=("text", "structured"))
    parser.add_argument("--model", default="claude-opus-5-5")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    return asyncio.run(_probe(args, parser))


if __name__ == "__main__":
    raise SystemExit(main())
