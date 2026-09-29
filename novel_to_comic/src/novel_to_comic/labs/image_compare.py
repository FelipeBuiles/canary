"""Image comparisons on a project's own requests: any model, route or prompt.

An item is one Style/Cast request the project recorded, or one planned Draw
page. An arm is an image target (model and route) plus a prompt variant:

- ``production``: what Canary sends. Pages are compiled now, by today's
  compiler, for the arm's target; Style/Cast items use the recorded prompt.
- ``restructured``: the same request restated by ``prompt_restructure``.

Every arm of an item uses the same references in the same order; only the
target and prompt differ. Each cell is one submission to exactly one route: no
fallback and no retry. Calls run without a user in the AI request context, so
they are operator-funded (API) or use the local Codex subscription allowance.

A failed cell can be retried by hand. Each cell records an input fingerprint
(prompt, size, target and reference bytes); a retry recomputes it and refuses
to submit if anything changed, so a retry resends exactly the same request.

Subscription calls report no billable usage. Their ``api_equivalent_usd`` prices
the same request at API rates so arms can be compared on cost; see
``api_equivalent_usd`` for what that approximation includes.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

from novel_to_comic.ai.context import ai_request_context
from novel_to_comic.config import Config, load_config
from novel_to_comic.image_route_fallback import FAL_SUNBURST_GATEWAY_MODEL, OPENAI_SUNBURST_GATEWAY_MODEL
from novel_to_comic.usage import UsageRecord, calculate_cost_breakdown, estimate_image_cost

from . import prompt_restructure, storage

KIND = "image_compare"
PROMPTS = ("production", "restructured")
_CONCURRENCY = {"api": 3, "codex_subscription": 2}
_ASSET_LABELS = {
    "style_sample": "Style proof", "style_calibration": "Style board", "character_ref": "Character sheet",
    "location_plate": "Location plate", "prop_ref": "Prop", "project_cover": "Cover",
}


@dataclass(frozen=True)
class ImageTarget:
    id: str
    label: str
    provider: str
    funding: Literal["api", "codex_subscription"]
    available: bool
    # How requests reach it: a Sunburst gateway route, or a Codex selector.
    gateway_model: str | None = None
    codex_selector: str | None = None


def image_targets() -> list[ImageTarget]:
    from novel_to_comic.model_catalog import codex_models

    targets = [
        ImageTarget("sunburst-openai", "GPT Image 2.5 Sunburst", "OpenAI API", "api", True,
                    gateway_model=OPENAI_SUNBURST_GATEWAY_MODEL),
        ImageTarget("sunburst-fal", "GPT Image 2.5 Sunburst", "FAL API", "api", True,
                    gateway_model=FAL_SUNBURST_GATEWAY_MODEL),
    ]
    targets += [
        ImageTarget(model["id"], f"GPT Image 2 via {model['id'].rsplit('/', 1)[1]}", "Codex subscription",
                    "codex_subscription", bool(model["available"]), codex_selector=model["id"])
        for model in codex_models() if model["kind"] == "image"
    ]
    return targets


def get_target(target_id: str) -> ImageTarget:
    for target in image_targets():
        if target.id == target_id:
            if not target.available:
                raise ValueError(f"{target.label} ({target.provider}) is not available in this server process")
            return target
    raise ValueError(f"Unknown image target: {target_id}")


@dataclass(frozen=True)
class Prepared:
    prompt: str
    width: int
    height: int
    references: int
    missing_verbatim: list[str]
    submit: Any  # async (output_path) -> UsageRecord
    reference_sha256: tuple[str, ...] = ()

    def fingerprint(self, target: ImageTarget) -> str:
        """Identifies the exact request: target, prompt, size and reference bytes in order."""
        payload = json.dumps([target.id, self.prompt, self.width, self.height, list(self.reference_sha256)])
        return hashlib.sha256(payload.encode()).hexdigest()

    def api_equivalent_usd(self, quality: str | None) -> float:
        """This request priced at API rates, as settled for a completed Sunburst call.

        Uses the measured Sunburst token consumption for the requested size and
        quality, ~1,200 input tokens per reference and the prompt's estimated
        text tokens. Sizes without a measurement (Codex pages ask for 1696x2528)
        scale the output cost of the measured size nearest in aspect by pixel
        area. GPT Image 2 has the same published rate card ($5 text in, $8 image
        in, $30 out per million tokens), so Codex cells are priced as if GPT
        Image 2 consumed as many tokens as Sunburst: an approximation. The Codex
        reasoning model's own tokens are not reported and not included.
        """
        width, height = _measured_size(quality, self.width, self.height)

        def cost(**kwargs: Any) -> float:
            return estimate_image_cost(OPENAI_SUNBURST_GATEWAY_MODEL, 1, quality=quality, width=width,
                                       height=height, basis="expected", **kwargs)

        output = cost(ref_count=0, prompt_text="")
        scale = (self.width * self.height) / (width * height)
        return cost(ref_count=self.references, prompt_text=self.prompt) + output * (scale - 1)

    def estimate_usd(self, target: ImageTarget, quality: str | None) -> float | None:
        """Operator API spend only; subscription calls spend allowance, not dollars."""
        return self.api_equivalent_usd(quality) if target.funding == "api" else None


def _measured_size(quality: str | None, width: int, height: int) -> tuple[int, int]:
    """The requested size if its consumption is measured, else the measured size nearest in aspect."""
    from novel_to_comic.usage import get_pricing_resolver

    spec = get_pricing_resolver()._overrides["model_overrides"]["gpt-image-2.5-sunburst"]
    sizes = [tuple(map(int, size.split("x")))
             for size in spec["expected_image_tokens_by_quality_and_size"].get((quality or "medium").lower(), {})]
    if (width, height) in sizes or not sizes:
        return width, height
    return min(sizes, key=lambda size: abs(size[0] / size[1] - width / height))


# ── Style & Cast requests ────────────────────────────────────────────────────

class AssetItem:
    """A Style or Cast request recorded in the project's request store."""

    def __init__(self, project_dir: Path, request_id: str) -> None:
        from novel_to_comic.provider_wire import ProviderWireRequest

        path = project_dir / "requests" / request_id / "manifest.json"
        manifest = json.loads(path.read_text())
        self._requests_dir = path.parent.parent
        self.wire = ProviderWireRequest.from_json(json.dumps(manifest["wire_request"]))
        self.quality = dict(self.wire.controls).get("quality") or "medium"

    def _reference_roles(self) -> list[dict[str, Any]]:
        return [{"role": ref.role, "role_label": ref.role_label, "entity_id": ref.entity_id}
                for ref in self.wire.references]

    def prepare(self, config: Config, target: ImageTarget, variant: str) -> Prepared:
        recorded = self.wire.prompt_parts[0]
        prompt = recorded if variant == "production" else prompt_restructure.restructure_asset_prompt(
            recorded, self._reference_roles(), width=self.wire.width, height=self.wire.height,
        )
        missing = [text for text in prompt_restructure.required_asset_verbatim(recorded) if text not in prompt]
        wire = self._wire_for(target, prompt, restructured=variant != "production")

        async def submit(output_path: Path) -> UsageRecord:
            from novel_to_comic.ai.client import generate_wire_image_on_route

            result = await generate_wire_image_on_route(
                config=config, wire=wire, gateway_model=wire.requested_alias or "",
                output_path=output_path, feature="labs.image_compare",
            )
            if result.usage is None:
                raise RuntimeError("The image route returned no usage")
            return result.usage

        return Prepared(prompt, wire.width, wire.height, len(wire.references), missing, submit,
                        tuple(ref.content_sha256 for ref in wire.references))

    def _wire_for(self, target: ImageTarget, prompt: str, *, restructured: bool):
        references = []
        for ref in self.wire.references:
            ref = replace(ref, source_path=str(self._requests_dir / ref.source_path))
            if restructured:
                # Codex sends each reference's instruction too; keep B's plain wording there.
                ref = replace(ref, instruction=(
                    "Shows only how to paint; not its subjects or layout." if ref.role == "style"
                    else "Shows what this subject looks like; keep its identity and design."
                ))
            references.append(ref)
        wire = replace(self.wire, prompt_parts=(prompt,), references=tuple(references))
        if target.codex_selector:
            from novel_to_comic.ai import codex_runtime
            from novel_to_comic.codex_dev import route_for
            from novel_to_comic.image_models import ImageRoute, image_model_profile

            route = route_for("image", target.codex_selector)
            if route is None:
                raise ValueError(f"{target.label} is not enabled in this server process")
            profile = image_model_profile(target.codex_selector)
            if len(references) > profile.max_references:
                raise ValueError(f"{target.label} accepts at most {profile.max_references} references; "
                                 f"this request has {len(references)}")
            wire = replace(
                wire, provider_key="codex-dev", requested_alias=target.codex_selector,
                configured_provider_model=route.image_model, expected_route=ImageRoute.CODEX_BUILTIN.value,
                structured_aspect=None,
                controls=tuple(sorted((("reasoning_model", route.reasoning_model),
                                       *codex_runtime.image_execution_controls()))),
            )
        else:
            from novel_to_comic.image_models import describe_image_model

            sunburst = describe_image_model("image-sunburst")
            wire = replace(wire, provider_key=sunburst.provider_key, requested_alias=target.gateway_model,
                           configured_provider_model=sunburst.provider_model,
                           controls=(("quality", self.quality),))
        return replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())


# ── Draw pages ───────────────────────────────────────────────────────────────

class PageItem:
    """One planned page, compiled now for the arm's target."""

    def __init__(self, project_dir: Path, page_number: int) -> None:
        self._project_dir = project_dir
        self.page_number = page_number
        self.quality = "medium"

    def _compile(self, config: Config):
        from novel_to_comic.models.draw import RetryProvenance
        from novel_to_comic.page_drawing import (
            compile_page_generation_request,
            current_page_capability_profile,
            select_book_edition,
        )
        from novel_to_comic.stages.s5_plan import approved_reference_files, approved_visual_inventory
        from novel_to_comic.style_reference import require_style_reference
        from novel_to_comic.target_artifacts import TargetArtifacts

        profile = current_page_capability_profile(config)
        compiled = compile_page_generation_request(
            TargetArtifacts(self._project_dir).read_page(self.page_number),
            select_book_edition(edition_id="labs", profile=profile),
            approved_visual_inventory(self._project_dir), approved_reference_files(self._project_dir),
            retry=RetryProvenance(attempt=1), style_template=config.style_template,
            style_reference_path=require_style_reference(self._project_dir, config.style_template),
        )
        return profile, compiled

    def prepare(self, config: Config, target: ImageTarget, variant: str) -> Prepared:
        from novel_to_comic.models.draw import FrozenPageGenerationRequest
        from novel_to_comic.page_drawing import CompiledPageGeneration

        config = config.model_copy(update={"draw_model": target.codex_selector or "image-sunburst"})
        profile, compiled = self._compile(config)
        request = compiled.request
        production = request.prompt
        prompt = production if variant == "production" else prompt_restructure.restructure_page_prompt(
            production, width=request.output_width, height=request.output_height,
        )
        missing = [text for text in prompt_restructure.required_page_verbatim(production) if text not in prompt]
        request = FrozenPageGenerationRequest.model_validate(
            {**request.model_dump(mode="json"), "prompt": prompt, "request_sha256": ""},
        )
        compiled = CompiledPageGeneration(request, compiled.reference_bytes, None)

        async def submit(output_path: Path) -> UsageRecord:
            from novel_to_comic import page_drawing

            if target.codex_selector:
                adapter = page_drawing.complete_page_adapter(config, profile)
                result = await adapter.generate(adapter.prepare(compiled))
            else:
                transport = (page_drawing.sunburst_openai_page_transport if target.id == "sunburst-openai"
                             else page_drawing.sunburst_fal_page_transport)(config, profile)
                result = await transport.generate(page_drawing.prepare_frozen_page_request(
                    request, compiled.reference_bytes, profile,
                ))
            output_path.write_bytes(result.image_bytes)
            return result.usage

        return Prepared(prompt, request.output_width, request.output_height, len(request.references),
                        missing, submit,
                        tuple(hashlib.sha256(data).hexdigest() for data in compiled.reference_bytes))


# ── Listing and running ──────────────────────────────────────────────────────

def list_items(project_dir: Path) -> list[dict[str, Any]]:
    """Recorded Style/Cast requests (latest per output) and planned Draw pages."""
    from novel_to_comic.target_artifacts import TargetArtifacts

    latest: dict[str, dict[str, Any]] = {}
    for manifest_path in sorted((project_dir / "requests").glob("*/manifest.json")):
        status_path = manifest_path.with_name("status.json")
        try:
            status = json.loads(status_path.read_text()) if status_path.exists() else {}
            manifest = json.loads(manifest_path.read_text())
            wire = manifest["wire_request"]
        except (OSError, ValueError, KeyError):
            continue
        if status.get("status") != "complete" or not status.get("result_link"):
            continue
        kind = manifest.get("request_context", {}).get("asset_kind", "asset")
        entry = {
            "id": f"asset:{manifest_path.parent.name}", "kind": "asset",
            "label": f"{_ASSET_LABELS.get(kind, kind)} · {status['result_link']}",
            "recorded_at": manifest.get("submitted_at") or manifest.get("created_at"),
            "recorded_route": wire.get("provider_key"), "references": len(wire.get("references") or []),
            "preview": status["result_link"],
        }
        current = latest.get(status["result_link"])
        if current is None or (entry["recorded_at"] or "") > (current["recorded_at"] or ""):
            latest[status["result_link"]] = entry
    items = sorted(latest.values(), key=lambda item: item["label"])
    target = TargetArtifacts(project_dir)
    if target.plan_path.exists():
        for page in target.read_plan().pages:
            content = target.read_page(page.page_number).content
            items.append({
                "id": f"page:{page.page_number}", "kind": "page",
                "label": f"Page {page.page_number} · {len(content)} panel{'s' if len(content) != 1 else ''}",
            })
    return items


def load_item(project_dir: Path, item_id: str) -> AssetItem | PageItem:
    kind, _, key = item_id.partition(":")
    if kind == "asset" and key == Path(key).name:
        return AssetItem(project_dir, key)
    if kind == "page" and key.isdigit():
        return PageItem(project_dir, int(key))
    raise ValueError(f"Unknown item: {item_id}")


def validate_arms(arms: list[dict[str, str]]) -> list[dict[str, str]]:
    if not 2 <= len(arms) <= 4:
        raise ValueError("Choose between two and four arms")
    clean = []
    for arm in arms:
        target, prompt = str(arm.get("target") or ""), str(arm.get("prompt") or "")
        get_target(target)
        if prompt not in PROMPTS:
            raise ValueError(f"Prompt must be one of: {', '.join(PROMPTS)}")
        clean.append({"target": target, "prompt": prompt})
    if len({(arm["target"], arm["prompt"]) for arm in clean}) != len(clean):
        raise ValueError("Each arm must differ in model, route or prompt")
    return clean


def preview(project_dir: Path, item_id: str, arms: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Exactly what each arm would send for one item. Nothing is submitted."""
    from novel_to_comic.text_utils import clean_exception_message

    config, _ = load_config(project_dir)
    item = load_item(project_dir, item_id)
    out = []
    for arm in arms:
        target = get_target(arm["target"])
        try:
            prepared = item.prepare(config, target, arm["prompt"])
            out.append({"prompt": prepared.prompt, "chars": len(prepared.prompt),
                        "width": prepared.width, "height": prepared.height, "references": prepared.references,
                        "missing_verbatim": prepared.missing_verbatim,
                        "estimated_cost_usd": prepared.estimate_usd(target, item.quality),
                        "api_equivalent_usd": prepared.api_equivalent_usd(item.quality), "error": None})
        except Exception as exc:  # noqa: BLE001 - shown to the operator before any spend
            out.append({"error": clean_exception_message(exc)})
    return out


def estimate(project_dir: Path, items: list[str], arms: list[dict[str, str]]) -> dict[str, Any]:
    """Prepare every cell offline: total API estimate, call split and pre-spend errors."""
    from novel_to_comic.text_utils import clean_exception_message

    config, _ = load_config(project_dir)
    total, calls, problems = 0.0, {"api": 0, "subscription": 0}, []
    for item_id in items:
        item = load_item(project_dir, item_id)
        for index, arm in enumerate(arms):
            target = get_target(arm["target"])
            try:
                prepared = item.prepare(config, target, arm["prompt"])
            except Exception as exc:  # noqa: BLE001 - reported before any spend
                problems.append({"item": item_id, "arm": index, "error": clean_exception_message(exc)})
                continue
            calls["api" if target.funding == "api" else "subscription"] += 1
            total += prepared.estimate_usd(target, item.quality) or 0.0
            if prepared.missing_verbatim:
                problems.append({"item": item_id, "arm": index,
                                 "error": f"B drops {len(prepared.missing_verbatim)} verbatim item(s)"})
    return {"estimated_cost_usd": round(total, 4), "calls": calls, "problems": problems}


def cell_id(item_id: str, arm_index: int) -> str:
    return f"{item_id.replace(':', '-')}.arm{arm_index + 1}"


async def run_cell(user_root: Path, run_id: str, project: str, item_id: str, arm_index: int,
                   arm: dict[str, str], *, retry_of: dict[str, Any] | None = None) -> None:
    """Submit one cell once. ``retry_of`` is the failed cell being retried, if any."""
    from novel_to_comic.text_utils import clean_exception_message

    identifier = cell_id(item_id, arm_index)
    target = get_target(arm["target"])
    attempts = []
    if retry_of is not None:
        attempts = [*retry_of.get("attempts", []), {
            key: retry_of.get(key) for key in ("started_at", "latency_ms", "error", "input_sha256")
        }]
    cell: dict[str, Any] = {
        "item": item_id, "arm": arm_index, "target": target.id, "prompt": arm["prompt"],
        "funding": target.funding, "status": "running", "started_at": storage.now(), "attempts": attempts,
    }
    storage.write_cell(user_root, run_id, identifier, cell)
    started = time.perf_counter()
    try:
        project_dir = user_root / project
        config, _ = load_config(project_dir)
        item = load_item(project_dir, item_id)
        prepared = item.prepare(config, target, arm["prompt"])
        fingerprint = prepared.fingerprint(target)
        prompt_path = storage.run_file(user_root, run_id, f"prompts/{identifier}.txt")
        if retry_of is not None:
            _require_same_request(retry_of, fingerprint, prepared.prompt, prompt_path)
        prompt_path.parent.mkdir(parents=True, exist_ok=True)
        prompt_path.write_text(prepared.prompt)
        cell |= {"prompt_file": f"prompts/{identifier}.txt", "prompt_chars": len(prepared.prompt),
                 "requested_size": f"{prepared.width}x{prepared.height}", "input_sha256": fingerprint,
                 "estimated_cost_usd": prepared.estimate_usd(target, item.quality),
                 "api_equivalent_usd": prepared.api_equivalent_usd(item.quality)}
        output = storage.run_file(user_root, run_id, f"images/{identifier}.png")
        output.parent.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        with ai_request_context(stage="labs", project_name=f"labs/{run_id}"):
            usage = await prepared.submit(output)
    except Exception as exc:
        storage.write_cell(user_root, run_id, identifier, cell | {
            "status": "failed", "error": clean_exception_message(exc),
            "latency_ms": int((time.perf_counter() - started) * 1000),
        })
        return
    cost = calculate_cost_breakdown(usage)
    storage.write_cell(user_root, run_id, identifier, cell | {
        "status": "ok", "image": f"images/{identifier}.png", "output_size": _png_size(output),
        "latency_ms": int((time.perf_counter() - started) * 1000),
        "cost_usd": cost.cost_usd, "cost_source": cost.source,
        "usage": usage.model_dump(include={"input_tokens", "output_tokens", "input_image_tokens",
                                           "image_output_tokens", "funding"}),
    })


class ChangedInputError(ValueError):
    """A retry would no longer send the request the run recorded."""


def _require_same_request(previous: dict[str, Any], fingerprint: str, prompt: str, prompt_path: Path) -> None:
    recorded = previous.get("input_sha256")
    same_prompt = prompt_path.exists() and prompt_path.read_text() == prompt
    if (recorded and recorded != fingerprint) or (not recorded and not same_prompt):
        raise ChangedInputError(
            "The project's inputs for this cell changed since the run; start a new run to compare them"
        )


def _png_size(path: Path) -> str | None:
    header = path.read_bytes()[:24] if path.exists() else b""
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    return f"{int.from_bytes(header[16:20], 'big')}x{int.from_bytes(header[20:24], 'big')}"


def failed_cells(user_root: Path, run_id: str, cell_ids: list[str] | None) -> list[dict[str, Any]]:
    """The failed cells to retry: the named ones, or every failed cell."""
    run = storage.read_run(user_root, run_id)
    if run is None or run.get("kind") != KIND:
        raise ValueError("Run not found")
    failed = [cell for cell in run["cells"] if cell.get("status") == "failed"]
    if cell_ids is None:
        return failed
    selected = [cell for cell in failed if cell["cell_id"] in set(cell_ids)]
    if len(selected) != len(set(cell_ids)):
        raise ValueError("Only failed cells can be retried")
    return selected


async def retry(user_root: Path, run_id: str, cells: list[dict[str, Any]]) -> None:
    run = storage.read_run(user_root, run_id) or {}
    spec = run.get("spec") or {}
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in _CONCURRENCY.items()}

    async def bounded(cell: dict[str, Any]) -> None:
        arm = spec["arms"][int(cell["arm"])]
        async with semaphores[get_target(arm["target"]).funding]:
            await run_cell(user_root, run_id, spec["project"], cell["item"], int(cell["arm"]), arm,
                           retry_of=cell)

    await asyncio.gather(*(bounded(cell) for cell in cells))


async def run(user_root: Path, run_id: str, project: str, items: list[str], arms: list[dict[str, str]]) -> None:
    semaphores = {funding: asyncio.Semaphore(limit) for funding, limit in _CONCURRENCY.items()}

    async def bounded(item_id: str, index: int, arm: dict[str, str]) -> None:
        async with semaphores[get_target(arm["target"]).funding]:
            await run_cell(user_root, run_id, project, item_id, index, arm)

    await asyncio.gather(*(bounded(item_id, index, arm) for item_id in items for index, arm in enumerate(arms)))
