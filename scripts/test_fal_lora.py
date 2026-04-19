import asyncio
import base64
import io
import json
import os
import time
import zipfile
from pathlib import Path
import httpx
from dotenv import load_dotenv
from PIL import Image

# Load Canary environment
load_dotenv(Path(__file__).parent.parent / ".env")
FAL_KEY = os.getenv("FAL_KEY")
FAL_LORA_STEPS = int(os.getenv("FAL_LORA_STEPS", "700"))

PROJECT_NAME = "one-of-these-days"
PROJECT_DIR = Path(__file__).parent.parent / "projects" / PROJECT_NAME
TEST_OUT_DIR = PROJECT_DIR / "tests" / "lora"


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


def api_error_message(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"{exc.response.status_code} - {exc.response.text}"
    return str(exc)


def build_dataset_data_uri(char_dir: Path) -> str:
    """Slices a character's 4-panel sheet.png and returns a ZIP data URI."""
    sheet_path = char_dir / "sheet.png"
    if not sheet_path.exists():
        raise FileNotFoundError(f"Missing {sheet_path}")

    # Open the 4-panel grid and slice it into 4 separate images
    with Image.open(sheet_path) as img:
        w, h = img.size
        w2, h2 = w // 2, h // 2

        slices = [
            img.crop((0, 0, w2, h2)),         # Top-Left (Front)
            img.crop((w2, 0, w, h2)),         # Top-Right (Side/3-Quarter)
            img.crop((0, h2, w2, h)),         # Bottom-Left (Action)
            img.crop((w2, h2, w, h))          # Bottom-Right (Expression)
        ]

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i, slice_img in enumerate(slices):
            img_buf = io.BytesIO()
            slice_img.save(img_buf, format="PNG")
            zip_file.writestr(f"slice_{i}.png", img_buf.getvalue())

    zip_bytes = zip_buffer.getvalue()
    encoded = base64.b64encode(zip_bytes).decode()
    return f"data:application/zip;base64,{encoded}"

async def train_lora(client: httpx.AsyncClient, dataset_url: str, trigger_word: str) -> str:
    """Triggers Fal.ai fast training and polls for the resulting LoRA URL."""
    print(f"   ↳ Starting LoRA training for {trigger_word} ({FAL_LORA_STEPS} steps)...")
    submit_resp = await client.post(
        "https://queue.fal.run/fal-ai/flux-lora-fast-training",
        json={
            "images_data_url": dataset_url,
            "trigger_word": trigger_word,
            "steps": FAL_LORA_STEPS,
            "data_archive_format": "zip",
        }
    )
    submit_resp.raise_for_status()
    req_id = submit_resp.json()["request_id"]
    
    status_url = f"https://queue.fal.run/fal-ai/flux-lora-fast-training/requests/{req_id}/status"
    while True:
        await asyncio.sleep(5)
        status_resp = await client.get(status_url)
        status_resp.raise_for_status()
        status_data = status_resp.json()
        if status_data["status"] == "COMPLETED":
            result_resp = await client.get(f"https://queue.fal.run/fal-ai/flux-lora-fast-training/requests/{req_id}")
            result_resp.raise_for_status()
            result = result_resp.json()
            # fal.ai response shape varies — try known keys
            if "diffusers_lora_file" in result and isinstance(result["diffusers_lora_file"], dict):
                return result["diffusers_lora_file"]["url"]
            if "diffusers_lora_file" in result:
                return result["diffusers_lora_file"]
            if "lora_file" in result:
                return result["lora_file"]["url"] if isinstance(result["lora_file"], dict) else result["lora_file"]
            # Fallback: print what we got so we can fix the key
            print(f"   ⚠️ Unexpected result keys: {list(result.keys())}")
            print(f"   Full response: {json.dumps(result, indent=2)[:500]}")
            raise KeyError(f"Could not find LoRA file URL in result. Keys: {list(result.keys())}")
        elif status_data["status"] == "FAILED":
            raise RuntimeError(f"Training failed: {status_data}")


async def wait_for_generation(client: httpx.AsyncClient, req_id: str) -> str:
    while True:
        await asyncio.sleep(2)
        status_resp = await client.get(f"https://queue.fal.run/fal-ai/flux-lora/requests/{req_id}/status")
        status_resp.raise_for_status()
        status_data = status_resp.json()
        if status_data["status"] == "COMPLETED":
            result = await client.get(f"https://queue.fal.run/fal-ai/flux-lora/requests/{req_id}")
            result.raise_for_status()
            return result.json()["images"][0]["url"]
        elif status_data["status"] == "FAILED":
            raise RuntimeError(f"Generation failed: {status_data}")


async def download_image(client: httpx.AsyncClient, image_url: str) -> bytes:
    image_resp = await client.get(image_url)
    image_resp.raise_for_status()
    return image_resp.content

async def main():
    if not FAL_KEY:
        print("❌ Error: FAL_KEY not found in .env")
        return

    TEST_OUT_DIR.mkdir(parents=True, exist_ok=True)
    prompts_dir = PROJECT_DIR / "prompts"

    # 1. Select one single-character panel and one multi-character panel.
    selected_panels = select_test_panels(prompts_dir)
    unique_chars = sorted({char for _, _, chars in selected_panels for char in chars})

    if not selected_panels:
        print("❌ No valid panels found.")
        return

    print(f"✅ Found {len(selected_panels)} controlled panel(s), containing {len(unique_chars)} unique characters.")
    metrics = []

    async with httpx.AsyncClient(timeout=300.0, headers={"Authorization": f"Key {FAL_KEY}"}) as client:
        # 2. Train LoRAs for all involved characters
        lora_registry = {}
        for char_id in unique_chars:
            char_dir = PROJECT_DIR / "refs" / char_id
            if not char_dir.exists() or not (char_dir / "sheet.png").exists():
                print(f"⚠️ Missing reference sheet.png for {char_id}")
                continue
            
            trigger = f"canary_{char_id}"
            train_started = time.perf_counter()
            try:
                dataset_url = build_dataset_data_uri(char_dir)
                lora_url = await train_lora(client, dataset_url, trigger)
                train_latency = time.perf_counter() - train_started
                lora_registry[char_id] = {"url": lora_url, "trigger": trigger}
                print(f"   ✅ LoRA Ready: {trigger}")
                metrics.append({
                    "backend": "fal_lora",
                    "phase": "training",
                    "character": char_id,
                    "status": "succeeded",
                    "latency_seconds": round(train_latency, 2),
                    "steps": FAL_LORA_STEPS,
                })
            except (httpx.HTTPError, RuntimeError) as exc:
                print(f"   ❌ Training failed for {char_id}: {api_error_message(exc)}")
                metrics.append({
                    "backend": "fal_lora",
                    "phase": "training",
                    "character": char_id,
                    "status": "failed",
                    "latency_seconds": round(time.perf_counter() - train_started, 2),
                    "steps": FAL_LORA_STEPS,
                    "error": api_error_message(exc),
                })

        # 3. Generate panels using the trained LoRAs
        for pf, data, chars in selected_panels:
            prompt_text = production_prompt(data)
            missing_loras = [char_id for char_id in chars if char_id not in lora_registry]
            if missing_loras:
                print(f"⚠️ Skipping {pf.name}: missing LoRAs for {', '.join(missing_loras)}")
                metrics.append({
                    "backend": "fal_lora",
                    "phase": "generation",
                    "prompt_file": str(pf.relative_to(PROJECT_DIR)),
                    "characters": chars,
                    "status": "skipped_missing_lora",
                    "missing_loras": missing_loras,
                })
                continue

            # Assemble required LoRAs and inject trigger words
            loras = []
            for char_id in chars:
                loras.append({"path": lora_registry[char_id]["url"], "scale": 0.85})
                # Naively append trigger word to prompt to ensure activation
                prompt_text += f" ({lora_registry[char_id]['trigger']})"

            print(f"\\n🚀 Generating {pf.name} (Loras: {len(loras)})")
            
            payload = {
                "prompt": prompt_text,
                "seed": 42, # Match Replicate's seed
                "num_inference_steps": 25,
                "loras": loras,
                "output_format": "png"
            }

            started = time.perf_counter()
            try:
                resp = await client.post("https://queue.fal.run/fal-ai/flux-lora", json=payload)
                resp.raise_for_status()
                img_url = await wait_for_generation(client, resp.json()["request_id"])
                image_bytes = await download_image(client, img_url)

                out_name = output_name(pf, chars)
                out_path = TEST_OUT_DIR / out_name
                out_path.write_bytes(image_bytes)
                print(f"   ✅ Saved: {out_path.relative_to(PROJECT_DIR)}")
                metrics.append({
                    "backend": "fal_lora",
                    "phase": "generation",
                    "prompt_file": str(pf.relative_to(PROJECT_DIR)),
                    "characters": chars,
                    "loras_used": [item["path"] for item in loras],
                    "status": "succeeded",
                    "latency_seconds": round(time.perf_counter() - started, 2),
                })
            except (httpx.HTTPError, RuntimeError, KeyError, IndexError) as exc:
                print(f"   ❌ Generation failed: {api_error_message(exc)}")
                metrics.append({
                    "backend": "fal_lora",
                    "phase": "generation",
                    "prompt_file": str(pf.relative_to(PROJECT_DIR)),
                    "characters": chars,
                    "loras_used": [item["path"] for item in loras],
                    "status": "failed",
                    "latency_seconds": round(time.perf_counter() - started, 2),
                    "error": api_error_message(exc),
                })

    metrics_path = TEST_OUT_DIR / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, indent=2))
    print(f"✅ Metrics saved: {metrics_path.relative_to(PROJECT_DIR)}")

if __name__ == "__main__":
    asyncio.run(main())
