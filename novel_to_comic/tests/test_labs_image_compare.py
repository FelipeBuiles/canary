"""Labs image comparisons: arms differ only in target and prompt, one call each."""
import asyncio
import hashlib
import json
from dataclasses import asdict, replace
from types import MappingProxyType

import httpx
import pytest

from novel_to_comic import codex_dev, page_drawing
from novel_to_comic.ai import client
from novel_to_comic.ai.context import ai_request_context, current_ai_request_context
from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.ai.providers.codex_dev import validate_codex_wire
from novel_to_comic.ai.providers.litellm_http import serialize_wire_request
from novel_to_comic.config import Config
from novel_to_comic.labs import image_compare, storage
from novel_to_comic.models.draw import CompletePageProviderResult, RetryProvenance
from novel_to_comic.page_drawing import (
    compile_page_generation_request,
    openai_page_capability_profile,
    page_image_quality,
    select_book_edition,
    sunburst_fallback_page_capability_profile,
)
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_DISCRIMINATOR,
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireReference,
    ProviderWireRequest,
)
from novel_to_comic.usage import ApiResult, UsageRecord, calculate_cost_breakdown, estimate_image_cost
from tests.test_complete_page_draw import _inventory, _page, _reference_files

OPENAI = "image-sunburst-openai"
PRODUCTION = {"target": "sunburst-openai", "prompt": "production"}
RESTRUCTURED = {"target": "sunburst-openai", "prompt": "restructured"}
PROMPT = """Constraints
- exactly 1 distinct listed character

Style
Ink and flat colour.

Protected anchors
Ada [char_001 / canonical]: 1woman, adult female, tall

Scene direction
Visual brief: Ada at a window."""


def _usage() -> UsageRecord:
    return UsageRecord(provider="openai", model=OPENAI, provider_model="gpt-image-2.5-sunburst",
                       operation="image", input_tokens=100, output_tokens=343, image_count=1,
                       input_text_tokens=100, input_image_tokens=0, cached_text_tokens=0,
                       cached_image_tokens=0, image_output_tokens=343)


def _record(requests, request_id, *, result, submitted_at, status="complete"):
    blob = b"\x89PNG " + request_id.encode()
    digest = hashlib.sha256(blob).hexdigest()
    (requests / "blobs").mkdir(parents=True, exist_ok=True)
    (requests / "blobs" / digest).write_bytes(blob)
    reference = ProviderWireReference(
        index=0, source_path=f"blobs/{digest}", content_sha256=digest, role="style",
        role_label="style:selected style", instruction="sole visual rendering style authority",
        provider_binding="0", entity_id=None, appearance_state_id=None, authority_scope="contextual",
        preserve_facets=("medium",), ignore_facets=("people",),
    )
    wire = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR, schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias="image-sunburst", expected_route="gpt_image_2", provider_key="fal-queue",
        configured_provider_model="fal-queue/openai/gpt-image-2.5/sunburst", prompt_parts=(PROMPT,),
        references=(reference,), width=1024, height=1024, structured_aspect=None,
        controls=(("quality", "medium"),), compiled_request_sha256="c" * 64, execution_fingerprint="",
    )
    wire = replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())
    (requests / request_id).mkdir()
    (requests / request_id / "manifest.json").write_text(json.dumps({
        "wire_request": json.loads(wire.to_json()), "submitted_at": submitted_at,
        "request_context": {"asset_kind": "character_ref"},
    }))
    (requests / request_id / "status.json").write_text(json.dumps({"status": status, "result_link": result}))
    return wire


@pytest.fixture
def root(tmp_path):
    user_root = tmp_path / "user"
    project = user_root / "story"
    project.mkdir(parents=True)
    (project / "config.yaml").write_text('litellm_base_url: "http://gateway"\n')
    requests = project / "requests"
    _record(requests, "old", result="refs/char_001/sheet.png", submitted_at="2026-09-01")
    _record(requests, "new", result="refs/char_001/sheet.png", submitted_at="2026-09-20")
    _record(requests, "failed", result=None, submitted_at="2026-09-21", status="failed")
    return user_root


def _run(root, item, arm, index=0):
    run = storage.create_run(root, kind=image_compare.KIND, label="t", spec={})

    async def as_a_signed_in_request():
        with ai_request_context(user_id="user-1"):
            await image_compare.run_cell(root, run["run_id"], "story", item, index, arm)

    asyncio.run(as_a_signed_in_request())
    return run["run_id"], storage.read_run(root, run["run_id"])["cells"][0]


def test_items_offer_the_latest_completed_request_per_output(root):
    items = image_compare.list_items(root / "story")

    assert [item["id"] for item in items] == ["asset:new"]
    assert items[0]["label"] == "Character sheet · refs/char_001/sheet.png"


def test_a_sunburst_arm_changes_only_the_prompt_route_and_reference_paths(root):
    item = image_compare.AssetItem(root / "story", "new")
    recorded = item.wire
    wire = item._wire_for(image_compare.get_target("sunburst-fal"), "New prompt", restructured=False)

    assert wire.prompt_parts == ("New prompt",)
    assert (wire.provider_key, wire.requested_alias, wire.configured_provider_model) == (
        "openai-fal", "image-sunburst", "gpt-image-2.5-sunburst")
    assert wire.execution_fingerprint == wire.recompute_execution_fingerprint()
    assert [replace(ref, source_path="") for ref in wire.references] == [
        replace(ref, source_path="") for ref in recorded.references]
    changed = {"prompt_parts", "provider_key", "requested_alias", "configured_provider_model",
               "references", "execution_fingerprint"}
    assert {k: v for k, v in asdict(wire).items() if k not in changed} == {
        k: v for k, v in asdict(recorded).items() if k not in changed}


def test_restructured_arms_also_simplify_per_reference_instructions(root):
    item = image_compare.AssetItem(root / "story", "new")
    wire = item._wire_for(image_compare.get_target("sunburst-openai"), "B", restructured=True)

    assert wire.references[0].instruction == "Shows only how to paint; not its subjects or layout."


def test_flare_is_an_openai_target_with_the_same_prompt_and_references(root):
    item = image_compare.AssetItem(root / "story", "new")
    target = image_compare.get_target("flare-openai")
    sunburst = item.prepare(None, image_compare.get_target("sunburst-openai"), "production")
    flare = item.prepare(None, target, "production")
    wire = item._wire_for(target, PROMPT, restructured=False)
    params, files = serialize_wire_request(wire)

    assert target.provider == "OpenAI API" and target.funding == "api"
    assert wire.provider_key == "openai" and wire.requested_alias == "image-flare"
    assert wire.configured_provider_model == "openai/gpt-image-2.5-flare"
    assert flare.prompt == sunburst.prompt == PROMPT
    assert flare.reference_sha256 == sunburst.reference_sha256
    assert (flare.width, flare.height) == (sunburst.width, sunburst.height)
    assert flare.fingerprint(target) != sunburst.fingerprint(image_compare.get_target("sunburst-openai"))
    assert json.loads(params["canary_wire_request"])["controls"] == [["quality", "medium"]]
    assert params["size"] == "1024x1024" and params["quality"] == "medium"
    assert [part[1][1] for part in files] == [b"\x89PNG new"]
    assert image_compare.validate_arms([PRODUCTION, {"target": "flare-openai", "prompt": "production"}])


def test_flare_estimates_use_its_allowance_and_completed_cost_uses_its_tokens(root):
    target = image_compare.get_target("flare-openai")
    item = image_compare.AssetItem(root / "story", "new")
    prepared = item.prepare(None, target, "production")
    expected = estimate_image_cost("image-flare", 1, quality=item.quality, width=1024, height=1024,
                                   ref_count=1, prompt_text=PROMPT)

    assert prepared.estimate_usd(target, item.quality) == expected > 0.25
    usage = _usage().model_copy(update={
        "model": "image-flare", "provider_model": "openai/gpt-image-2.5-flare",
        "input_image_tokens": 1200, "input_tokens": 1300, "image_output_tokens": 901, "output_tokens": 901,
    })
    actual = calculate_cost_breakdown(usage)
    assert actual.cost_usd == pytest.approx(100 * 5e-6 + 1200 * 8e-6 + 901 * 3e-5)
    assert actual.cost_usd != expected and actual.source != "unknown_pricing"


def test_flare_rejects_reference_overflow_before_spend(root):
    item = image_compare.AssetItem(root / "story", "new")
    item.wire = replace(item.wire, references=tuple(
        replace(item.wire.references[0], index=index, provider_binding=str(index)) for index in range(17)
    ))
    with pytest.raises(ValueError, match="at most 16 references"):
        item.prepare(None, image_compare.get_target("flare-openai"), "production")


@pytest.fixture
def codex(monkeypatch):
    monkeypatch.setattr(codex_dev, "_PROCESS", MappingProxyType({
        **codex_dev._PROCESS, "CANARY_CODEX_DEV_ENABLED": "1", "CANARY_ENV": "development",
        "ENV": None, "FLY_APP_NAME": None, "FLY_MACHINE_ID": None,
        "RENDER": None, "RAILWAY_ENVIRONMENT": None, "K_SERVICE": None, "VERCEL": None,
    }))
    monkeypatch.setattr(codex_dev, "_SETTINGS_ERROR", None)
    return next(target for target in image_compare.image_targets() if target.codex_selector)


def test_a_codex_arm_builds_a_wire_codex_accepts_before_submitting(root, codex):
    item = image_compare.AssetItem(root / "story", "new")
    wire = item._wire_for(codex, "B", restructured=True)

    assert codex.funding == "codex_subscription"
    assert wire.provider_key == "codex-dev" and wire.requested_alias == codex.codex_selector
    validate_codex_wire(wire)


def test_a_codex_arm_rejects_reference_overflow_before_spend(root, codex):
    item = image_compare.AssetItem(root / "story", "new")
    item.wire = replace(item.wire, references=tuple(
        replace(item.wire.references[0], index=index, provider_binding=str(index)) for index in range(8)
    ))

    with pytest.raises(ValueError, match="at most"):
        item._wire_for(codex, "B", restructured=False)


def test_each_cell_submits_once_to_its_route_without_a_user(root, monkeypatch):
    seen = {}

    async def submit(**kwargs):
        seen.update(kwargs, user=current_ai_request_context().user_id, calls=seen.get("calls", 0) + 1)
        kwargs["output_path"].write_bytes(b"png")
        return ApiResult(value=kwargs["output_path"], usage=_usage())

    monkeypatch.setattr(client, "generate_wire_image_on_route", submit)

    run_id, cell = _run(root, "asset:new", RESTRUCTURED)

    assert seen["calls"] == 1 and seen["user"] is None and seen["gateway_model"] == OPENAI
    assert cell["status"] == "ok" and cell["cost_usd"] > 0 and cell["funding"] == "api"
    prompt = storage.run_file(root, run_id, cell["prompt_file"]).read_text()
    assert prompt == seen["wire"].prompt_parts[0] and prompt.startswith("Ada at a window.")


@pytest.mark.parametrize("target", ["sunburst-openai", "flare-openai"])
def test_a_failed_cell_is_recorded_and_never_retried(root, monkeypatch, target):
    calls = []

    async def submit(**kwargs):
        calls.append(kwargs)
        raise AITransportError("outcome unknown", phase="ambiguous_submission")

    monkeypatch.setattr(client, "generate_wire_image_on_route", submit)

    _, cell = _run(root, "asset:new", {"target": target, "prompt": "production"})

    assert len(calls) == 1
    assert cell["status"] == "failed" and "outcome unknown" in cell["error"] and "cost_usd" not in cell


@pytest.mark.parametrize("target,factory", [
    ("sunburst-openai", "sunburst_openai_page_transport"),
    ("sunburst-fal", "sunburst_fal_page_transport"),
    ("flare-openai", "complete_page_adapter"),
])
def test_page_arms_use_only_their_own_route(root, tmp_path, monkeypatch, target, factory):
    profile = (openai_page_capability_profile("gpt-image-2.5-flare", quality="medium")
               if target == "flare-openai" else sunburst_fallback_page_capability_profile())
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id="labs", profile=profile), _inventory(),
        _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    monkeypatch.setattr(image_compare.PageItem, "_compile", lambda self, config: (profile, compiled))
    sent = []

    class Transport:
        def prepare(self, compiled):
            return page_drawing.prepare_frozen_page_request(compiled.request, compiled.reference_bytes, profile)

        async def generate(self, prepared):
            sent.append(prepared)
            return CompletePageProviderResult(
                artifact_kind="complete_page", image_bytes=b"page", media_type="image/png",
                width=prepared.width, height=prepared.height, latency_ms=5,
                actual_provider_model=f"openai/{profile.model}", usage=_usage(),
            )

    monkeypatch.setattr(page_drawing, factory, lambda config, profile: Transport())
    for other in {"sunburst_openai_page_transport", "sunburst_fal_page_transport", "complete_page_adapter"} - {factory}:
        monkeypatch.setattr(page_drawing, other, lambda *a: pytest.fail("used the other route"))

    _, cell = _run(root, "page:1", {"target": target, "prompt": "restructured"})

    assert cell["status"] == "ok" and len(sent) == 1
    assert sent[0].prompt.startswith("A complete ") and sent[0].references == compiled.request.references


@pytest.mark.parametrize("lettering_mode", ["editable", "integrated"])
def test_flare_page_compiles_with_medium_quality_and_its_own_identity(root, tmp_path, monkeypatch, lettering_mode):
    from novel_to_comic import style_reference
    from novel_to_comic.stages import s5_plan
    from novel_to_comic.target_artifacts import TargetArtifacts

    monkeypatch.setattr(TargetArtifacts, "read_page", lambda self, number: _page())
    monkeypatch.setattr(s5_plan, "approved_visual_inventory", lambda path: _inventory())
    reference_files = _reference_files(tmp_path)
    monkeypatch.setattr(s5_plan, "approved_reference_files", lambda path: reference_files)
    monkeypatch.setattr(style_reference, "require_style_reference", lambda *args: None)
    config = Config(draw_model="image-flare", lettering_mode=lettering_mode)
    profile, compiled = image_compare.PageItem(root / "story", 1)._compile(config)

    assert profile.model == compiled.request.model == "gpt-image-2.5-flare"
    assert profile.provider == compiled.request.provider == "openai"
    assert compiled.request.profile_sha256 == profile.content_sha256
    assert profile.exact_visible_lettering == (lettering_mode == "integrated")
    assert page_image_quality(profile.id, profile.provider) == "medium"
    assert page_drawing.complete_page_adapter(config, profile)._gateway_model == "image-flare"
    assert page_drawing.complete_page_adapter(config, profile).prepare(compiled)
    assert page_image_quality(openai_page_capability_profile("gpt-image-2.5-flare").id, "openai") == "high"
    _, sunburst = image_compare.PageItem(root / "story", 1)._compile(
        config.model_copy(update={"draw_model": "image-sunburst"}),
    )
    assert compiled.request.prompt == sunburst.request.prompt
    assert compiled.request.references == sunburst.request.references
    assert compiled.reference_bytes == sunburst.reference_bytes


def test_flare_page_submits_its_model_quality_and_references_once(root, tmp_path, monkeypatch):
    import base64
    import io

    from PIL import Image

    profile = openai_page_capability_profile("gpt-image-2.5-flare", quality="medium")
    compiled = compile_page_generation_request(
        _page(), select_book_edition(edition_id="labs", profile=profile), _inventory(),
        _reference_files(tmp_path), retry=RetryProvenance(attempt=1),
    )
    monkeypatch.setattr(image_compare.PageItem, "_compile", lambda self, config: (profile, compiled))
    output = io.BytesIO()
    Image.new("RGB", (1024, 1536)).save(output, format="PNG")
    sent = []

    async def post(url, **kwargs):
        sent.append(kwargs)
        return httpx.Response(200, request=httpx.Request("POST", url), json={
            "model": "openai/gpt-image-2.5-flare",
            "data": [{"b64_json": base64.b64encode(output.getvalue()).decode()}],
            "usage": {"input_tokens": 1200, "output_tokens": 901,
                      "input_tokens_details": {"image_tokens": 1000, "text_tokens": 200}},
        })

    monkeypatch.setattr(client, "_post_with_retry", post)
    _, cell = _run(root, "page:1", {"target": "flare-openai", "prompt": "production"})

    assert cell["status"] == "ok" and len(sent) == 1
    fields = sent[0]["data"]
    assert fields["model"] == "image-flare" and fields["quality"] == "medium"
    assert fields["prompt"] == compiled.request.prompt
    assert fields["size"] == "1024x1536" and sent[0]["retry_ambiguous"] is False
    assert [file[1][1] for file in sent[0]["files"]] == list(compiled.reference_bytes)
    assert json.loads(fields["canary_wire_request"])["controls"][0] == ["quality", "medium"]
    assert cell["cost_usd"] == pytest.approx(200 * 5e-6 + 1000 * 8e-6 + 901 * 3e-5)


@pytest.mark.parametrize("arms,message", [
    ([PRODUCTION], "two and four"),
    ([PRODUCTION, PRODUCTION], "must differ"),
    ([PRODUCTION, {"target": "sunburst-openai", "prompt": "freestyle"}], "Prompt must be"),
    ([PRODUCTION, {"target": "dall-e", "prompt": "production"}], "Unknown image target"),
])
def test_invalid_arms_are_rejected(arms, message):
    with pytest.raises(ValueError, match=message):
        image_compare.validate_arms(arms)


def _fail_then_succeed(monkeypatch):
    calls = []

    async def submit(**kwargs):
        calls.append(kwargs["wire"])
        if len(calls) == 1:
            raise AITransportError("codex timed out", phase="ambiguous_submission")
        kwargs["output_path"].write_bytes(b"\x89PNG\r\n\x1a\n" + b"\0\0\0\rIHDR" + (768).to_bytes(4, "big")
                                          + (1024).to_bytes(4, "big"))
        return ApiResult(value=kwargs["output_path"], usage=_usage())

    monkeypatch.setattr(client, "generate_wire_image_on_route", submit)
    return calls


def _retry(root, run_id, cell_ids=None):
    cells = image_compare.failed_cells(root, run_id, cell_ids)
    asyncio.run(image_compare.retry(root, run_id, cells))
    return storage.read_run(root, run_id)["cells"][0]


def _spec_run(root, arm):
    run = storage.create_run(root, kind=image_compare.KIND, label="t",
                             spec={"project": "story", "items": ["asset:new"], "arms": [arm, PRODUCTION]})
    asyncio.run(image_compare.run_cell(root, run["run_id"], "story", "asset:new", 0, arm))
    return run["run_id"]


def test_retrying_a_failed_cell_resends_the_same_request_and_keeps_the_failure(root, monkeypatch):
    calls = _fail_then_succeed(monkeypatch)
    run_id = _spec_run(root, RESTRUCTURED)
    failed = storage.read_run(root, run_id)["cells"][0]

    cell = _retry(root, run_id)

    assert len(calls) == 2 and calls[0] == calls[1]
    assert cell["status"] == "ok" and cell["input_sha256"] == failed["input_sha256"]
    assert cell["output_size"] == "768x1024" and cell["requested_size"] == "1024x1024"
    assert [attempt["error"] for attempt in cell["attempts"]] == [failed["error"]]


def test_a_retry_refuses_to_submit_when_the_project_inputs_changed(root, monkeypatch):
    calls = _fail_then_succeed(monkeypatch)
    run_id = _spec_run(root, PRODUCTION)
    manifest = root / "story" / "requests" / "new" / "manifest.json"
    data = json.loads(manifest.read_text())
    wire = ProviderWireRequest.from_json(json.dumps(data["wire_request"]))
    wire = replace(wire, prompt_parts=(PROMPT + "\nEdited.",))
    data["wire_request"] = json.loads(replace(
        wire, execution_fingerprint=wire.recompute_execution_fingerprint()).to_json())
    manifest.write_text(json.dumps(data))

    cell = _retry(root, run_id)

    assert len(calls) == 1
    assert cell["status"] == "failed" and "changed since the run" in cell["error"]


def test_only_failed_cells_can_be_retried(root, monkeypatch):
    _fail_then_succeed(monkeypatch)
    run_id = _spec_run(root, PRODUCTION)
    _retry(root, run_id)

    assert image_compare.failed_cells(root, run_id, None) == []
    with pytest.raises(ValueError, match="Only failed cells"):
        image_compare.failed_cells(root, run_id, [image_compare.cell_id("asset:new", 0)])


def test_subscription_cells_carry_an_api_equivalent_cost(root, codex, monkeypatch):
    item = image_compare.AssetItem(root / "story", "new")
    api = item.prepare(None, image_compare.get_target("sunburst-openai"), "production")
    sub = item.prepare(None, codex, "production")

    assert sub.estimate_usd(codex, item.quality) is None
    assert sub.api_equivalent_usd(item.quality) == api.estimate_usd(
        image_compare.get_target("sunburst-openai"), item.quality) > 0


def test_unmeasured_sizes_scale_the_nearest_measured_size_by_area():
    def prepared(width, height):
        return image_compare.Prepared("", width, height, 0, [], None)

    measured = prepared(1024, 1536).api_equivalent_usd("medium")
    codex_page = prepared(1696, 2528).api_equivalent_usd("medium")

    assert codex_page == pytest.approx(measured * (1696 * 2528) / (1024 * 1536))
    assert codex_page < 0.05  # never the $0.25 reservation allowance
