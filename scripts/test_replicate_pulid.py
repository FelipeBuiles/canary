import asyncio
import base64
import json
import os
import io
import time
from pathlib import Path
import httpx
from dotenv import load_dotenv
from PIL import Image

# Load Canary environment
load_dotenv(Path(__file__).parent.parent / ".env")
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY")
REPLICATE_MODEL = "bytedance/flux-pulid"
REPLICATE_VERSION = "8baa7ef2255075b46f4d91cd238c21d31181b3e6a864463f967960bb0112525b"

PROJECT_NAME = "one-of-these-days"  # Change this to target a different project
PROJECT_DIR = Path(__file__).parent.parent / "projects" / PROJECT_NAME
TEST_OUT_DIR = PROJECT_DIR / "tests" / "pulid"


def production_prompt(data: dict) -> str:
    style = data.get("style", "").strip()
    body = data.get("full_prompt", "").strip()
    return f"{style}\n\n{body}" if style else body


def panel_characters(data: dict) -> list[str]:
    return [s.get("character_id") for s in data.get("subjects", []) if s.get("character_id")]


def output_name(prompt_path: Path, chars: list[str]) -> str:
    kind = "multi" if len(chars) > 1 else "single"
    return f"{prompt_path.parent.name}_{prompt_path.stem}_{kind}.png"


def select_test_panels(prompts_dir: Path) -> list[tuple[Path, dict, list[str]]]:
    single = None
    multi = None
    for pf in sorted(prompts_dir.rglob("*.json")):
        try:
            data = json.loads(pf.read_text())
        except Exception:
            continue

        chars = panel_characters(data)
        if len(chars) == 1 and single is None:
            single = (pf, data, chars)
        elif len(chars) > 1 and multi is None:
            multi = (pf, data, chars)

        if single and multi:
            break

    return [item for item in (single, multi) if item]

async def main():
    if not REPLICATE_API_KEY:
        print("❌ Error: REPLICATE_API_KEY not found in .env")
        return

    TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)
    prompts_dir = PROJECT_DIR / "prompts"
    
    if not prompts_dir.exists():
        print(f"❌ Prompts directory not found at {prompts_dir}")
        return

    selected_panels = select_test_panels(prompts_dir)

    if not selected_panels:
        print("❌ No valid panel prompts with characters found.")
        return

    print(f"✅ Found {len(selected_panels)} controlled panel(s) to test.")
    metrics = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        headers = {
            "Authorization": f"Bearer {REPLICATE_API_KEY}",
            "Content-Type": "application/json",
            "Prefer": "wait"
        }

        for pf, data, chars in selected_panels:
            prompt_text = production_prompt(data)

            # Identify the primary character to anchor
            primary_char = chars[0]
            ref_img_path = PROJECT_DIR / "refs" / primary_char / "sheet.png"
            
            if not ref_img_path.exists():
                print(f"⚠️ Skipping {pf.name}: Missing reference sheet {ref_img_path}")
                continue

            print(f"\\n🚀 Generating {pf.name} (Characters: {', '.join(chars)})")
            
            # Load the 4-panel sheet and slice out the top-left quadrant for the face reference
            img = Image.open(ref_img_path)
            w, h = img.size
            # Crop the top-left panel
            front_face = img.crop((0, 0, w // 2, h // 2))
            
            buf = io.BytesIO()
            front_face.save(buf, format="PNG")
            b64_img = base64.b64encode(buf.getvalue()).decode()
            data_uri = f"data:image/png;base64,{b64_img}"

            payload = {
                "version": REPLICATE_VERSION,
                "input": {
                    "prompt": prompt_text,
                    "main_face_image": data_uri,
                    "width": data.get("width", 768),
                    "height": data.get("height", 1344),
                    "output_format": "png",
                    "seed": 42,  # Fixed seed for comparability
                    "num_steps": 20,
                    "start_step": 4,
                    "guidance_scale": 4,
                    "id_weight": 1,
                    "true_cfg": 1,
                    "max_sequence_length": 512,
                    "negative_prompt": (
                        "bad quality, worst quality, text, signature, watermark, extra limbs, "
                        "low resolution, deformed face, blurry"
                    ),
                    "num_outputs": 1,
                }
            }

            # Submit to Replicate
            print(f"   ↳ Submitting to Replicate ({REPLICATE_MODEL})...")
            started = time.perf_counter()
            resp = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers=headers,
                json=payload
            )
            
            if resp.status_code != 201:
                print(f"   ❌ API Error: {resp.status_code} - {resp.text}")
                metrics.append({
                    "backend": "replicate_pulid",
                    "model": REPLICATE_MODEL,
                    "version": REPLICATE_VERSION,
                    "prompt_file": str(pf.relative_to(PROJECT_DIR)),
                    "characters": chars,
                    "primary_character": primary_char,
                    "status": "api_error",
                    "latency_seconds": round(time.perf_counter() - started, 2),
                    "http_status": resp.status_code,
                    "error": resp.text,
                })
                continue

            prediction = resp.json()
            pred_url = prediction["urls"]["get"]
            
            # Poll until completion
            while prediction["status"] not in ["succeeded", "failed", "canceled"]:
                await asyncio.sleep(2)
                poll_resp = await client.get(pred_url, headers=headers)
                prediction = poll_resp.json()
            latency = time.perf_counter() - started
            
            if prediction["status"] == "succeeded":
                output_url = prediction["output"][0]
                img_resp = await client.get(output_url)
                
                out_name = output_name(pf, chars)
                out_path = TEST_OUT_DIR / out_name
                out_path.write_bytes(img_resp.content)
                print(f"   ✅ Saved: {out_path.relative_to(PROJECT_DIR)}")
            else:
                print(f"   ❌ Generation failed: {prediction.get('error')}")

            metrics.append({
                "backend": "replicate_pulid",
                "model": REPLICATE_MODEL,
                "version": REPLICATE_VERSION,
                "prompt_file": str(pf.relative_to(PROJECT_DIR)),
                "characters": chars,
                "primary_character": primary_char,
                "status": prediction["status"],
                "latency_seconds": round(latency, 2),
                "prediction_metrics": prediction.get("metrics"),
                "error": prediction.get("error"),
            })

    metrics_path = TEST_OUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"✅ Metrics saved: {metrics_path.relative_to(PROJECT_DIR)}")

if __name__ == "__main__":
    asyncio.run(main())
