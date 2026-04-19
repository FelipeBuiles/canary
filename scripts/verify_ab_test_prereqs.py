import argparse
import json
import os
from pathlib import Path


CURRENT_PROMPT_VERSION = 3
OFFSCREEN_MARKERS = (
    "off-screen",
    "off screen",
    "off-panel",
    "off panel",
    "unseen speaker",
    "unseen voice",
    "voice-only",
    "voice only",
    "heard but not seen",
    "not physically shown",
    "never physically shown",
)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def env_keys(project_dir: Path) -> dict[str, str]:
    values = dict(os.environ)
    for env_path in (Path.cwd() / ".env", project_dir / ".env"):
        if not env_path.exists():
            continue
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return values


def panel_characters(prompt_data: dict) -> list[str]:
    return [
        subject.get("character_id")
        for subject in prompt_data.get("subjects", [])
        if subject.get("character_id")
    ]


def production_prompt(prompt_data: dict) -> str:
    style = prompt_data.get("style", "").strip()
    body = prompt_data.get("full_prompt", "").strip()
    return f"{style}\n\n{body}" if style else body


def select_test_panels(prompt_files: list[Path]) -> list[tuple[Path, dict, list[str]]]:
    single = None
    multi = None
    for path in prompt_files:
        try:
            data = load_json(path)
        except Exception:
            continue

        chars = panel_characters(data)
        if len(chars) == 1 and single is None:
            single = (path, data, chars)
        elif len(chars) > 1 and multi is None:
            multi = (path, data, chars)

        if single and multi:
            break

    return [item for item in (single, multi) if item]


def rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify prerequisites for Canary A/B consistency tests.")
    parser.add_argument(
        "--project",
        default="projects/one-of-these-days",
        help="Project directory to verify. Defaults to projects/one-of-these-days.",
    )
    args = parser.parse_args()

    repo = Path.cwd()
    project_dir = Path(args.project)
    if not project_dir.is_absolute():
        project_dir = repo / project_dir

    errors: list[str] = []
    warnings: list[str] = []

    print(f"Project: {project_dir}")
    if not project_dir.exists():
        errors.append(f"Project directory does not exist: {project_dir}")
        return finish(errors, warnings)

    story_bible_path = project_dir / "story_bible.json"
    if not story_bible_path.exists():
        errors.append("Missing story_bible.json. Run extract and approve/review it first.")
        return finish(errors, warnings)

    story_bible = load_json(story_bible_path)
    characters = story_bible.get("characters", [])
    character_by_id = {character.get("id"): character for character in characters}
    print(f"Story bible characters: {len(characters)}")

    for character in characters:
        char_id = character.get("id", "<missing>")
        name = character.get("name", char_id)
        anchor = character.get("visual_anchor", "")
        anchor_lower = anchor.lower()
        if not anchor:
            errors.append(f"{char_id} {name}: missing visual_anchor.")
        if "same character, same appearance." not in anchor_lower:
            errors.append(f"{char_id} {name}: visual_anchor missing consistency suffix.")
        if anchor_lower.startswith("1boy") and any(token in anchor_lower for token in ("adult", "mature", "40s", "30s", "50s")):
            errors.append(f"{char_id} {name}: adult-looking anchor starts with 1boy.")
        if anchor_lower.startswith("1girl") and any(token in anchor_lower for token in ("adult", "mature", "40s", "30s", "50s")):
            errors.append(f"{char_id} {name}: adult-looking anchor starts with 1girl.")
        if any(marker in anchor_lower for marker in OFFSCREEN_MARKERS):
            errors.append(f"{char_id} {name}: off-screen marker still present in visual character anchor.")

    prompts_dir = project_dir / "prompts"
    if not prompts_dir.exists():
        errors.append("Missing prompts/. Run screenplay, panels, and prompts before A/B tests.")
        return finish(errors, warnings)

    prompt_files = sorted(prompts_dir.rglob("*.json"))
    print(f"Prompt files: {len(prompt_files)}")
    if not prompt_files:
        errors.append("No prompt JSON files found under prompts/.")
        return finish(errors, warnings)

    prompt_chars: set[str] = set()
    stale_prompts: list[str] = []
    missing_prompt_fields: list[str] = []
    missing_subject_lists: list[str] = []
    missing_anchor_in_prompt: list[str] = []

    for path in prompt_files:
        data = load_json(path)
        version = data.get("prompt_version", 1)
        if version < CURRENT_PROMPT_VERSION:
            stale_prompts.append(f"{rel(path, project_dir)} has prompt_version {version}")
        if not data.get("style") or not data.get("full_prompt"):
            missing_prompt_fields.append(rel(path, project_dir))
        if "subjects" not in data or not isinstance(data.get("subjects"), list):
            missing_subject_lists.append(rel(path, project_dir))

        full_prompt = data.get("full_prompt", "")
        for subject in data.get("subjects", []):
            char_id = subject.get("character_id")
            if not char_id:
                continue
            prompt_chars.add(char_id)
            character = character_by_id.get(char_id)
            if not character:
                errors.append(f"{rel(path, project_dir)} references unknown character_id {char_id}.")
                continue
            anchor = character.get("visual_anchor", "")
            identity = subject.get("identity", "")
            if anchor and (anchor not in identity or anchor not in full_prompt):
                missing_anchor_in_prompt.append(f"{rel(path, project_dir)} missing full anchor for {char_id}")

    if stale_prompts:
        errors.extend(stale_prompts[:10])
        if len(stale_prompts) > 10:
            errors.append(f"{len(stale_prompts) - 10} more stale prompts omitted.")
    if missing_prompt_fields:
        errors.extend(f"{path} missing style/full_prompt." for path in missing_prompt_fields[:10])
        if len(missing_prompt_fields) > 10:
            errors.append(f"{len(missing_prompt_fields) - 10} more prompts with missing fields omitted.")
    if missing_subject_lists:
        errors.extend(f"{path} missing subjects list." for path in missing_subject_lists[:10])
        if len(missing_subject_lists) > 10:
            errors.append(f"{len(missing_subject_lists) - 10} more prompts with missing subjects lists omitted.")
    if missing_anchor_in_prompt:
        errors.extend(missing_anchor_in_prompt[:10])
        if len(missing_anchor_in_prompt) > 10:
            errors.append(f"{len(missing_anchor_in_prompt) - 10} more prompt anchor misses omitted.")

    refs_dir = project_dir / "refs"
    missing_refs = sorted(
        char_id for char_id in prompt_chars
        if not (refs_dir / char_id / "sheet.png").exists()
    )
    if missing_refs:
        errors.append(f"Missing refs/<char_id>/sheet.png for prompt characters: {', '.join(missing_refs)}")

    selected = select_test_panels(prompt_files)
    print("Controlled panel selection:")
    for path, data, chars in selected:
        kind = "multi" if len(chars) > 1 else "single"
        print(f"  {kind}: {rel(path, project_dir)} -> {', '.join(chars)}")
        if not production_prompt(data):
            errors.append(f"{rel(path, project_dir)} selected for test has empty production prompt.")

    if not any(len(chars) == 1 for _, _, chars in selected):
        errors.append("No single-character prompt found for the controlled test set.")
    if not any(len(chars) > 1 for _, _, chars in selected):
        errors.append("No multi-character prompt found for the controlled test set.")

    selected_chars = sorted({char for _, _, chars in selected for char in chars})
    print(f"Selected test characters: {', '.join(selected_chars) if selected_chars else '(none)'}")

    keys = env_keys(project_dir)
    if not keys.get("REPLICATE_API_KEY"):
        warnings.append("REPLICATE_API_KEY not found in shell, repo .env, or project .env.")
    if not keys.get("FAL_KEY"):
        warnings.append("FAL_KEY not found in shell, repo .env, or project .env.")

    return finish(errors, warnings)


def finish(errors: list[str], warnings: list[str]) -> int:
    if warnings:
        print("\nWarnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if errors:
        print("\nPrerequisite check failed:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print("\nPrerequisite check passed. You can run the A/B scripts.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
