"""Route x wording grid for the declined sphinx prop reference.

Reuses Labs' submission path (AssetItem._wire_for + generate_wire_image_on_route):
one submission per cell, no fallback, no retry.
"""
import asyncio
import json
import sys
import time
from pathlib import Path

from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.ai.client import generate_wire_image_on_route
from novel_to_comic.config import load_config
from novel_to_comic.labs.image_compare import AssetItem, get_target

PROJECT = Path("/Users/jbuiles/Code/canary/projects/947150d4-7d2f-4726-a018-5539f933ea56/this-happened-before-v3")
REQUEST = "1988983b2b994525873cd5bda98944cf"
OUT = Path(__file__).parent / "sphinx_grid"

OLD = "bare womanly torso blending into a panther or lioness body"
NEW = ("sculpted woman's head and upper body in smooth carved wood, flowing into a crouching "
       "panther or lioness body, classical sphinx form")
ANCHOR_END = "spring-loaded needle and hollow interior\n"
FRAMING = ("Subject nature: Wooden Sphinx Figurine is an inanimate carved wooden object, a classical "
           "sphinx statuette. Any human or animal form on it is sculpted wood, not a living person.\n")

TARGETS = {"codex": "codex-dev/image/gpt-5.5", "sunburst": "sunburst-openai"}
REPEATS = {"codex": 2, "sunburst": 1}


def prompts(recorded: str) -> dict[str, str]:
    assert OLD in recorded and ANCHOR_END in recorded
    return {
        "current": recorded,
        "reworded": recorded.replace(OLD, NEW),
        "framed": recorded.replace(ANCHOR_END, ANCHOR_END + FRAMING),
    }


async def cell(config, item, route, wording, prompt, rep, sem, dry):
    target = get_target(TARGETS[route])
    wire = item._wire_for(target, prompt, restructured=False)
    name = f"{route}.{wording}.{rep}"
    (OUT / f"{name}.prompt.txt").write_text(prompt)
    if dry:
        return {"cell": name, "dry": True}
    async with sem[route]:
        started = time.perf_counter()
        try:
            with ai_request_context(stage="labs", project_name="labs/sphinx-grid"):
                result = await generate_wire_image_on_route(
                    config=config, wire=wire, gateway_model=wire.requested_alias or "",
                    output_path=OUT / f"{name}.png", feature="labs.image_compare",
                )
            usage = result.usage
            row = {"cell": name, "status": "ok", "cost_usd": getattr(usage, "cost_usd", None)}
        except Exception as exc:  # noqa: BLE001
            row = {"cell": name, "status": "failed", "error": f"{type(exc).__name__}: {exc}"[:600]}
        row["seconds"] = round(time.perf_counter() - started, 1)
        print(json.dumps(row), flush=True)
        return row


async def main(dry: bool):
    OUT.mkdir(exist_ok=True)
    config, _ = load_config(PROJECT)
    item = AssetItem(PROJECT, REQUEST)
    variants = prompts(item.wire.prompt_parts[0])
    sem = {"codex": asyncio.Semaphore(2), "sunburst": asyncio.Semaphore(3)}
    rows = await asyncio.gather(*(
        cell(config, item, route, wording, prompt, rep, sem, dry)
        for route in TARGETS for wording, prompt in variants.items() for rep in range(1, REPEATS[route] + 1)
    ))
    (OUT / "results.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    asyncio.run(main(dry="--dry" in sys.argv))
