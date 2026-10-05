"""Send the declined sphinx prompts straight to OpenAI with moderation=low."""
import asyncio, base64, json, sys, time
from pathlib import Path
sys.path.insert(0, "/Users/jbuiles/Code/canary")
from litellm_handlers.openai_image_stream import _stream_request, completed_image, OpenAIImageStreamError

REQ = Path("/Users/jbuiles/Code/canary/projects/947150d4-7d2f-4726-a018-5539f933ea56/this-happened-before-v3/requests")
GRID = Path(__file__).parent / "sphinx_grid"
manifest = json.loads((REQ / "1988983b2b994525873cd5bda98944cf/manifest.json").read_text())
style = (REQ / manifest["wire_request"]["references"][0]["source_path"]).read_bytes()

async def one(name, prompt_file):
    fields = {"model": "gpt-image-2.5-sunburst", "prompt": (GRID / prompt_file).read_text(),
              "size": "1024x1024", "stream": "true", "partial_images": "0",
              "quality": "medium", "moderation": "low"}
    t = time.perf_counter()
    try:
        event, rid = await _stream_request(endpoint="edits", model=fields["model"], fields=fields,
                                           files=[("image[]", ("reference-0.png", style, "image/png"))],
                                           api_key=None, read_timeout=300)
        (GRID / f"{name}.png").write_bytes(base64.b64decode(completed_image(event, model="x", request_id=rid)))
        row = {"cell": name, "status": "ok", "request_id": rid, "usage": event.get("usage")}
    except OpenAIImageStreamError as exc:
        row = {"cell": name, "status": "failed", "error": str(exc)[:400]}
    row["seconds"] = round(time.perf_counter() - t, 1)
    print(json.dumps(row), flush=True)

async def main():
    await asyncio.gather(one("low.current.1", "sunburst.current.1.prompt.txt"),
                         one("low.current.2", "sunburst.current.1.prompt.txt"),
                         one("low.framed.1", "sunburst.framed.1.prompt.txt"))
asyncio.run(main())
