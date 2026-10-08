"""Tests for S2 style suggestions (declared-medium dedup) and the style-sample brief."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_to_comic import artifacts
from novel_to_comic.models.lettering import LetteringRoles
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.stages.s2_style import (
    STYLE_BRIEF_VERSION,
    STYLE_PROOF_COPY_VERSION,
    _style_proof_copy_source_key,
    STYLE_VALIDATION_ACTION,
    STYLE_VALIDATION_COMPOSITION,
    PORTFOLIO_ROLES,
    SAMPLE_COUNT,
    NEIGHBOR_COUNT,
    LLM_REQUEST_COUNT,
    StyleProduction,
    StyleSketchBatch,
    build_style_sample_request,
    _dedupe_suggestions,
    _drop_story_specific,
    _select_role_portfolio,
    _style_sample_brief_source_key,
    _style_sample_brief_source,
    ensure_style_sample_brief,
    estimate_style_proof_cost_usd,
    generate_sample_image,
    generate_samples_for_indices,
    generate_suggestions,
    missing_sample_indices,
    normalize_suggestion,
    style_direction_image,
    style_validation_brief,
    _suggestion_story_context,
)
from novel_to_comic.style_contract import (
    DEFAULT_LETTERING_STANDARD,
    DEFAULT_PAGE_FRAMING_STANDARD,
    page_art_style_template,
    style_template_for_suggestion,
)
from novel_to_comic.usage import ApiResult

STORY_COPY = {
    "caption": "Snow fell on the dead city.",
    "speech": "Where is everyone?",
    "shout": "Donut!",
    "thought": "This is wrong.",
    "sfx": "CRUNCH",
    "speaker": "Carl",
    "thinker": "Carl",
}

BRIEF = (
    "Carl, a broad-shouldered man in his late twenties wearing a worn leather "
    "jacket, stands ankle-deep in fresh snow on a dark Seattle street."
)


@pytest.fixture(autouse=True)
def _no_provider_proof_copy(request, monkeypatch):
    """Brief tests stay provider-free; copy tests opt in by name."""
    if "proof_copy" in request.node.name:
        return
    from novel_to_comic.stages import s2_style
    monkeypatch.setattr(s2_style, "generate_style_proof_copy", AsyncMock(return_value=None))


def _bible(character_name: str = "Carl") -> StoryBible:
    return StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name=character_name,
                visual_anchor="1man, adult male, leather jacket",
                age_range="late 20s",
                gender="male",
                distinguishing_features=[],
                default_outfit="",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor="outdoors, snow, winter",
                mood="apocalyptic",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Carl outside.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred",
            )
        ],
        sequences=[],
        props=[],
    )


def _sugg(label: str, medium: str) -> dict:
    return {
        "label": label,
        "medium": medium,
        "template": f"{label}: a vivid forty-word visual direction in this medium.",
    }


def _batch(*, restriction: str = "", count: int = LLM_REQUEST_COUNT) -> dict:
    styles = []
    for index in range(count):
        styles.append({
            **_sugg(f"Direction {index}", f"medium {index}"),
            "visual_logic": "realistic_illustration" if index % 6 == 0 else (
                "stylized" if index % 2 else "graphic"
            ),
            "proportion_family": ("naturalistic", "compact", "elongated", "heroic", "caricatured", "geometric")[index % 6],
            "character_design": f"Design {index}: explicit head/body ratio, limb proportions and face shapes.",
            "portfolio_role": PORTFOLIO_ROLES[index % len(PORTFOLIO_ROLES)],
            "color_strategy": ("naturalistic", "saturated", "high_key", "muted", "monochrome", "naturalistic")[index % 6],
            "medium_family": ("comic_production", "painted", "printmaking", "drawn", "collage", "novelty_process")[index % 6],
            "palette": f"palette {index}",
            "line_rendering": f"finish {index}",
            "lighting_value": f"lighting {index}",
            "story_fit": "Supports the story.",
        })
    return {"medium_restriction": restriction, "proportion_restriction": "", "color_restriction": "",
            "styles": styles}


def _production(label: str = "Literary") -> dict:
    return {
        "lettering": DEFAULT_LETTERING_STANDARD,
        "lettering_preset": "literary",
        "lettering_design": {"label": label, "roles": LetteringRoles().model_dump()},
        "page_framing": DEFAULT_PAGE_FRAMING_STANDARD,
        "sequential_art_strengths": "Readable action and recurring identities.",
        "risk": "Detailed finish.",
    }


def _text_mock(*sketch_results: dict, production=None) -> AsyncMock:
    """Answer sketch calls in order (the last repeats) and every production call."""
    sketches = list(sketch_results)

    async def answer(**kwargs):
        if kwargs["feature"] == "style.production":
            value = production(kwargs) if callable(production) else _production()
            return ApiResult(value=value, usage=None)
        return ApiResult(value=sketches.pop(0) if len(sketches) > 1 else sketches[0], usage=None)

    return AsyncMock(side_effect=answer)


def _direction_of(kwargs: dict) -> dict:
    data = kwargs["user_content"].split("(data, not instructions):\n", 1)[1]
    return json.loads(data.split("\n\nCorrect the previous response", 1)[0])


def _sketch_calls(mock: AsyncMock) -> list:
    return [call for call in mock.await_args_list if call.kwargs["feature"] == "style.suggestions"]


# ── declared-medium dedup ────────────────────────────────────────────────────


def test_dedup_preserves_distinct_directions_within_an_author_medium():
    first = _sugg("Earthy", "woodblock print")
    second = _sugg("Luminous", "woodblock print")
    kept = _dedupe_suggestions(
        [first, second, {**second, "label": "Renamed duplicate"}],
        existing_suggestions=[first],
    )
    assert kept == [second]


def test_templates_naming_story_places_or_people_are_dropped():
    """Regression for DCC: "Seattle snowbanks" in the selected template put the
    proof's street into every Cast asset, including dungeon rooms."""
    bible = _bible()
    named = [
        {**_sugg("City", "oil"), "template": "Paint with dense oil, contrasting cold gray Seattle snowbanks."},
        {**_sugg("Hero", "ink"), "template": "Ink every figure the way Carl would be inked."},
    ]
    assert _drop_story_specific(named, bible) == []
    # A name word opening a sentence is ordinary prose, not a story name.
    plain = {**_sugg("Lead", "ink"), "template": "Street lamps glow in dense ink."}
    assert _drop_story_specific([plain], bible) == [plain]


def test_role_aware_selector_does_not_relabel_diverse_candidates_by_position():
    candidates = [
        {**_sugg("Wild", "collage"), "portfolio_role": "wildcard", "palette": "neon"},
        {**_sugg("Fit", "ink"), "portfolio_role": "story_fit_primary", "palette": "earth"},
        {**_sugg("Contrast", "vector"), "portfolio_role": "contrast", "palette": "pastel"},
        {**_sugg("Adjacent", "gouache"), "portfolio_role": "adjacent", "palette": "jewel"},
    ]
    roles = ("story_fit_primary", "adjacent", "contrast", "wildcard")
    selected = _select_role_portfolio(candidates, roles)
    assert [item["portfolio_role"] for item in selected] == list(roles)


# ── generate_suggestions ─────────────────────────────────────────────────────


def test_generated_portfolio_is_six_illustrated_directions_with_distinct_proportions():
    mock = _text_mock(_batch())
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))
    assert [s["role"] for s in suggestions] == list(PORTFOLIO_ROLES)
    assert len(suggestions) == SAMPLE_COUNT == 6
    assert "realistic_illustration" in {s["visual_logic"] for s in suggestions}
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 4
    assert len({s["proportion_family"] for s in suggestions}) >= 4


def test_missing_realism_fails_without_fabricating_directions():
    batch = _batch()
    for candidate in batch["styles"]:
        candidate["visual_logic"] = "stylized"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError):
            asyncio.run(generate_suggestions(Config(), _bible()))
    # A failed curation never pays for production design.
    assert len(_sketch_calls(mock)) == mock.await_count


def test_explicit_author_medium_restriction_preserves_narrowed_neighbors():
    batch = _batch(restriction="Use only woodblock prints")
    for candidate in batch["styles"]:
        candidate["visual_logic"] = "graphic"
        candidate["medium"] = "woodblock print"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(
            Config(), _bible(), custom_direction={
                "id": "direction_1234567890abcdef", "text": "Use only woodblock prints",
            },
        ))
    assert {s["medium"] for s in suggestions} == {"woodblock print"}
    assert {s["visual_logic"] for s in suggestions} == {"graphic"}
    assert {s["style_reference_mode"] for s in suggestions} == {"variation"}


def test_generated_production_standards_reject_untyped_objects():
    production = _production()
    production["lettering"] = {"unrecognized": ["nested", "values"]}
    with pytest.raises(ValueError):
        StyleProduction.model_validate(production)


def test_sketch_pass_carries_no_production_system():
    batch = _batch()
    batch["styles"][0]["lettering_design"] = _production()["lettering_design"]
    with pytest.raises(ValueError):
        StyleSketchBatch.model_validate(batch)


def test_only_curated_survivors_get_a_production_system_in_parallel():
    in_flight = 0
    peak = 0

    async def answer(**kwargs):
        nonlocal in_flight, peak
        if kwargs["feature"] == "style.suggestions":
            return ApiResult(value=_batch(), usage=None)
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0.01)
        in_flight -= 1
        direction = _direction_of(kwargs)
        return ApiResult(value=_production(direction["label"]), usage=None)

    mock = AsyncMock(side_effect=answer)
    shortlisted = []

    async def on_shortlist(sketches):
        shortlisted.extend(sketches)

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(
            Config(), _bible(), on_shortlist=on_shortlist,
        ))

    productions = [call for call in mock.await_args_list if call.kwargs["feature"] == "style.production"]
    assert len(productions) == SAMPLE_COUNT
    assert peak == SAMPLE_COUNT
    assert [sketch["role"] for sketch in shortlisted] == list(PORTFOLIO_ROLES)
    assert [sketch["label"] for sketch in shortlisted] == [s["label"] for s in suggestions]
    # Each production system is designed for, and merged into, its own direction.
    assert all(s["lettering_design"]["label"] == s["label"] for s in suggestions)
    assert all(s["lettering_preset"] == "literary" for s in suggestions)


def test_production_schema_repair_gets_one_retry_then_fails():
    invalid = {**_production(), "lettering_preset": "baroque"}
    attempts = []

    def production(kwargs):
        attempts.append(kwargs["user_content"])
        return invalid

    mock = _text_mock(_batch(), production=production)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="did not match the required schema"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert any("Validation errors" in content for content in attempts)


def test_production_schema_repair_recovers():
    seen: dict[str, int] = {}

    def production(kwargs):
        label = _direction_of(kwargs)["label"]
        seen[label] = seen.get(label, 0) + 1
        return _production() if seen[label] > 1 else {**_production(), "lettering_preset": "baroque"}

    mock = _text_mock(_batch(), production=production)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(suggestions) == SAMPLE_COUNT
    assert set(seen.values()) == {2}




def test_generate_suggestions_completes_an_undersized_pool():
    complete = _batch()
    first = {**complete, "styles": complete["styles"][:2]}
    second = {**complete, "styles": complete["styles"][2:]}
    mock = _text_mock(first, second)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))
    assert {s["role"] for s in suggestions} == set(PORTFOLIO_ROLES)
    assert len(suggestions) == SAMPLE_COUNT == 6
    assert "realistic_illustration" in {s["visual_logic"] for s in suggestions}
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 4
    assert len({s["proportion_family"] for s in suggestions}) >= 4


def test_generate_suggestions_retries_when_a_required_role_is_missing():
    complete = _batch()
    first = {
        **complete,
        "styles": [
            style for style in complete["styles"]
            if style["portfolio_role"] != "story_fit_secondary"
        ],
    }
    secondary = complete["styles"][1]
    second = {**complete, "styles": [secondary]}
    mock = _text_mock(first, second)

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    sketch_calls = _sketch_calls(mock)
    assert len(sketch_calls) == 2
    assert "story_fit_secondary" in sketch_calls[1].kwargs["system_prompt"]
    assert [s["role"] for s in suggestions] == list(PORTFOLIO_ROLES)


def test_generate_suggestions_rejects_partial_portfolio():
    mock = _text_mock(_batch(count=1))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError):
            asyncio.run(generate_suggestions(Config(), _bible()))


# ── style-sample brief ───────────────────────────────────────────────────────


def test_concurrent_style_proofs_share_one_cached_brief(tmp_path, monkeypatch):
    from novel_to_comic.stages import s2_style

    calls = []

    async def author(*_args):
        calls.append(len(calls))
        await asyncio.sleep(.01)  # allow the competing reader to observe a miss
        return "The character stands beside the door and listens to the quiet room. " * 5

    monkeypatch.setattr(s2_style, "generate_style_sample_brief", author)

    async def run():
        return await asyncio.gather(*(
            ensure_style_sample_brief(Config(), _bible(), tmp_path) for _ in range(6)
        ))

    results = asyncio.run(run())
    assert len(calls) == 1
    assert len(set(results)) == 1
    assert json.loads(artifacts.style_sample_brief_path(tmp_path).read_text())["brief"] == results[0]


def test_ensure_style_sample_brief_generates_then_serves_from_cache(tmp_path):
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))

    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        first = asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))
        second = asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))

    assert first == BRIEF
    assert second == BRIEF
    assert mock.await_count == 1
    cached = json.loads(artifacts.style_sample_brief_path(tmp_path).read_text())
    assert cached["brief"] == BRIEF
    assert "Carl outside." in mock.await_args.kwargs["user_content"]
    assert "The transformation occurred" in mock.await_args.kwargs["user_content"]


def test_style_sample_source_uses_curated_extraction_evidence():
    source = _style_sample_brief_source(_bible())

    assert "1man, adult male, leather jacket" in source
    assert "outdoors, snow, winter" in source
    assert "Carl outside." in source
    assert 'Source anchor: "The transformation occurred"' in source


def test_ensure_style_sample_brief_regenerates_when_bible_changes(tmp_path):
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))

    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        asyncio.run(ensure_style_sample_brief(Config(), _bible("Carl"), tmp_path))
        asyncio.run(ensure_style_sample_brief(Config(), _bible("Donut"), tmp_path))

    assert mock.await_count == 2


def test_ensure_style_sample_brief_cache_key_includes_prompt_model(tmp_path):
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))
    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        asyncio.run(ensure_style_sample_brief(
            Config(prompt_model="gpt-5.6-luna"), _bible(), tmp_path,
        ))
        asyncio.run(ensure_style_sample_brief(
            Config(prompt_model="gpt-5.6-terra"), _bible(), tmp_path,
        ))
    assert mock.await_count == 2


def test_style_direction_image_rejects_tampered_path(tmp_path):
    outside = tmp_path / "secret.png"
    outside.write_bytes(b"secret")
    direction = {
        "id": "direction_0123456789abcdef",
        "image_path": "samples/directions/direction_0123456789abcdef/../../../secret.png",
        "image_sha256": hashlib.sha256(b"secret").hexdigest(),
    }
    assert style_direction_image(tmp_path, direction) is None

    safe_path = artifacts.style_direction_image_path(
        tmp_path, direction["id"], ".png",
    )
    safe_path.parent.mkdir(parents=True, exist_ok=True)
    safe_path.write_bytes(b"changed")
    direction["image_path"] = str(safe_path.relative_to(tmp_path))
    assert style_direction_image(tmp_path, direction) is None
    for bad_digest in (None, "", "ABC", "0" * 63):
        direction["image_sha256"] = bad_digest
        assert style_direction_image(tmp_path, direction) is None


def test_suggestion_id_is_recomputed_from_content_not_trusted_input():
    base = _sugg("Safe", "ink")
    canonical = normalize_suggestion(base)["id"]
    for attempted in ("../../escape", "style_0000000000000000", "/tmp/pwn.png"):
        assert normalize_suggestion({**base, "id": attempted})["id"] == canonical
    assert canonical.startswith("style_") and len(canonical) == 22


def test_style_validation_path_rejects_unsafe_ids(tmp_path):
    with pytest.raises(ValueError):
        artifacts.style_validation_path(tmp_path, "../../escape")
    safe = artifacts.style_validation_path(tmp_path, "style_0123456789abcdef")
    assert safe.parent == (tmp_path / "samples" / "validations").resolve()


def test_style_artifact_paths_reject_symlinked_directories(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "validations").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        artifacts.style_validation_path(tmp_path, "style_0123456789abcdef")

    (tmp_path / "samples" / "validations").unlink()
    (tmp_path / "samples" / "directions").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError):
        artifacts.style_direction_path(tmp_path, "direction_0123456789abcdef")


def test_style_direction_image_rejects_symlinked_direction_base(tmp_path):
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    direction_id = "direction_0123456789abcdef"
    image = outside / direction_id / "reference.png"
    image.parent.mkdir(parents=True)
    image.write_bytes(b"outside")
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "directions").symlink_to(outside, target_is_directory=True)
    direction = {
        "id": direction_id,
        "image_path": f"samples/directions/{direction_id}/reference.png",
        "image_sha256": hashlib.sha256(b"outside").hexdigest(),
    }
    assert style_direction_image(tmp_path, direction) is None


def test_exact_style_proof_estimate_compiles_dimensions_reference_and_brief_cost(tmp_path):
    from PIL import Image

    bible = _bible()
    config = Config(image_model="image-gemini-pro")
    artifacts.story_bible_path(tmp_path).write_text(bible.model_dump_json())
    reference = tmp_path / "reference.png"
    Image.new("RGB", (12, 14), "red").save(reference)
    captured = []

    def fake_image_cost(_model, _count, **kwargs):
        captured.append(kwargs)
        return 0.02

    with (
        patch("novel_to_comic.usage.estimate_text_cost", return_value=0.01) as text_cost,
        patch("novel_to_comic.usage.estimate_image_cost", side_effect=fake_image_cost),
    ):
        referenced = estimate_style_proof_cost_usd(
            config, tmp_path, bible, "Bold ink", "proof",
            style_reference=reference,
        )
        unreferenced = estimate_style_proof_cost_usd(
            config, tmp_path, bible, "Bold ink", "proof-no-ref",
        )
    # Image plus the uncached brief and story proof copy calls.
    assert referenced == pytest.approx(0.04)
    assert unreferenced == pytest.approx(0.04)
    assert text_cost.call_count == 4
    assert captured[0]["ref_count"] == 1
    assert captured[0]["ref_image_sizes"] == [(12, 14)]
    assert captured[1]["ref_count"] == 0
    assert captured[0]["width"] > 0 and captured[0]["height"] > 0
    assert captured[0]["prompt_text"]

    brief_path = artifacts.style_sample_brief_path(tmp_path)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(json.dumps({
        "version": STYLE_BRIEF_VERSION,
        "kind": "style_sample_brief",
        "source_sha256": _style_sample_brief_source_key(config, bible),
        "brief": BRIEF,
    }))
    artifacts.style_proof_copy_path(tmp_path).write_text(json.dumps({
        "version": STYLE_PROOF_COPY_VERSION,
        "source_sha256": _style_proof_copy_source_key(config, bible),
        "copy": STORY_COPY,
    }))
    with (
        patch("novel_to_comic.usage.estimate_text_cost") as cached_text_cost,
        patch("novel_to_comic.usage.estimate_image_cost", return_value=0.02),
    ):
        cached = estimate_style_proof_cost_usd(
            config, tmp_path, bible, "Bold ink", "cached",
        )
    assert cached == pytest.approx(0.02)
    cached_text_cost.assert_not_called()


def test_ensure_style_sample_brief_disabled_skips_llm(tmp_path):
    config = Config(style_sample_brief_enabled=False)
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        assert asyncio.run(ensure_style_sample_brief(config, _bible(), tmp_path)) is None


def test_ensure_style_sample_brief_fails_soft(tmp_path):
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=RuntimeError("gateway down")),
    ):
        assert asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path)) is None
    assert not artifacts.style_sample_brief_path(tmp_path).exists()


def test_generate_sample_image_uses_brief_and_writes_meta(tmp_path):
    async def _fake_execute_frozen_request(*, project_dir, request_id, config, output_path, feature):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"image")
        return ApiResult(value=output_path, usage=None)

    sample_path = tmp_path / "samples" / "style_1.png"
    with patch(
            "novel_to_comic.asset_generation.execute_frozen_request",
        new=AsyncMock(side_effect=_fake_execute_frozen_request),
    ):
        asyncio.run(
            generate_sample_image(
                Config(style_template="Clinical, desaturated visual language."),
                _bible(),
                sample_path,
                brief=BRIEF,
            )
        )

    meta = json.loads((tmp_path / "samples" / "style_1.png.meta.json").read_text())
    assert BRIEF in meta["prompt"]
    assert meta["provenance"]["asset_kind"] == "style_sample"
    assert meta["provenance"]["asset_identity"] == "style_sample:style_1"
    # Slice 06: style proof images use a portrait 4:5 frame.
    assert meta["parameters"]["width"] == 1024
    assert meta["parameters"]["height"] == 1280
    assert "The night held its breath." not in meta["prompt"]
    assert "Software adds them later" in meta["prompt"]
    assert "We keep moving." not in meta["prompt"]
    assert "1man, adult male, leather jacket" in meta["prompt"]
    assert "outdoors, snow, winter" in meta["prompt"]


def test_sample_freshness_uses_compiled_request_fingerprint(tmp_path):
    suggestion = normalize_suggestion(_sugg("A", "gouache"))

    async def _fake_execute_frozen_request(*, project_dir, request_id, config, output_path, feature):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"image")
        return ApiResult(value=output_path, usage=None)

    with patch(
            "novel_to_comic.asset_generation.execute_frozen_request",
        new=AsyncMock(side_effect=_fake_execute_frozen_request),
    ), patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(return_value=ApiResult(value=BRIEF, usage=None)),
    ):
        asyncio.run(generate_samples_for_indices(
            Config(), _bible(), tmp_path, [suggestion], [1],
        ))

    assert missing_sample_indices(
        tmp_path, [suggestion], config=Config(), bible=_bible(),
    ) == []
    changed = {**suggestion, "template": suggestion["template"] + " High-key palette."}
    assert missing_sample_indices(
        tmp_path, [changed], config=Config(), bible=_bible(),
    ) == [1]


def test_fallback_brief_proof_is_fresh_without_brief_cache(tmp_path):
    suggestion = normalize_suggestion(_sugg("Fallback", "ink"))

    async def _fake_execute_frozen_request(*, project_dir, request_id, config, output_path, feature):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"image")
        return ApiResult(value=output_path, usage=None)

    with patch(
            "novel_to_comic.asset_generation.execute_frozen_request",
        new=AsyncMock(side_effect=_fake_execute_frozen_request),
    ):
        asyncio.run(generate_sample_image(
            Config(style_template=suggestion["template"]), _bible(),
            artifacts.style_sample_path(tmp_path, 1),
            candidate_id=suggestion["id"],
        ))
    assert not artifacts.style_sample_brief_path(tmp_path).exists()
    assert missing_sample_indices(
        tmp_path, [suggestion], config=Config(), bible=_bible(),
    ) == []


def test_validation_request_uses_dynamic_structured_action_without_contradiction():
    request = build_style_sample_request(
        Config(style_template="Bold ink"), _bible(), style_validation_brief(_bible()),
        candidate_id="style_validation", subject_action=STYLE_VALIDATION_ACTION,
        composition=STYLE_VALIDATION_COMPOSITION,
    )
    assert STYLE_VALIDATION_ACTION in request.compiled.final_prompt
    assert request.compiled.final_prompt.count(_bible().characters[0].visual_anchor) == 1
    assert "no lettering or borders" not in request.compiled.final_prompt.lower()
    assert "The night held its breath." not in request.compiled.final_prompt
    assert "Software adds them later" in request.compiled.final_prompt



def test_style_proof_uses_story_bible_wardrobe_over_anchor_clothing(tmp_path):
    bible = _bible()
    character = bible.characters[0]
    character.visual_anchor += ", flowing silk robes"
    character.default_outfit = "leather-clad, rogue-like"
    prompt = build_style_sample_request(
        Config(), bible, "A quiet scene.", candidate_id="wardrobe",
    ).compiled.final_prompt
    assert ("Carl current wardrobe (overrides any clothing in the anchor above): "
            "leather-clad, rogue-like") in prompt
    assert "current wardrobe: leather-clad, rogue-like" in _style_sample_brief_source(bible)

    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))
    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        character.default_outfit = "plate armour"
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
    assert mock.await_count == 2

def _mixed_bible() -> StoryBible:
    bible = _bible("Ari")
    animal = bible.characters[0].model_copy(update={
        "id": "char_002", "name": "Button",
        "visual_anchor": "1cat, tortoiseshell persian cat, flat face, fluffy fur",
        "age_range": "adult", "gender": "female",
    })
    unrelated = bible.characters[0].model_copy(update={
        "id": "char_003", "name": "Elsewhere", "visual_anchor": "1creature, stone wings",
    })
    bible.characters.extend([animal, unrelated])
    bible.scenes[0].character_ids = ["char_001", "char_002"]
    bible.scenes[0].summary = "Ari waits beside Button near a tree."
    return bible


@pytest.mark.parametrize("generated", [False, True])
def test_mixed_scene_roster_is_protected_in_generated_and_fallback_proofs(tmp_path, generated):
    from novel_to_comic.style_briefing import style_sample_fallback_brief

    bible = _mixed_bible()
    prose = "Ari waits beside the tree while Button turns toward the light, then both settle into a quiet pause."
    mock = AsyncMock(return_value=ApiResult(value=prose, usage=None))
    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        brief = asyncio.run(ensure_style_sample_brief(
            Config(style_sample_brief_enabled=generated), bible, tmp_path,
        ))
    request = build_style_sample_request(
        Config(), bible, brief or style_sample_fallback_brief(bible), candidate_id="mixed",
    )
    prompt = request.compiled.final_prompt
    for character in bible.characters[:2]:
        assert character.visual_anchor in prompt
    assert bible.characters[2].visual_anchor not in prompt
    assert "exactly 2 distinct listed character" in prompt
    assert "Button" in (brief or style_sample_fallback_brief(bible))
    source = _style_sample_brief_source(bible)
    assert bible.characters[1].visual_anchor in source
    assert bible.characters[2].visual_anchor not in source
    assert "Elsewhere" not in source


def test_style_brief_cache_tracks_selected_animal_identity_and_roster(tmp_path):
    bible = _mixed_bible()
    mock = AsyncMock(return_value=ApiResult(value=BRIEF, usage=None))
    with patch("novel_to_comic.clients.text.generate_text", new=mock):
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        bible.characters[2].visual_anchor = "1creature, copper wings"
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        assert mock.await_count == 1
        bible.characters[1].visual_anchor += ", white paws"
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        assert mock.await_count == 2
        bible.scenes[0].character_ids = ["char_002"]
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        assert mock.await_count == 3
        path = artifacts.style_sample_brief_path(tmp_path)
        cache = json.loads(path.read_text())
        cache["version"] = 4
        path.write_text(json.dumps(cache))
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        assert mock.await_count == 4


def test_overfull_scene_does_not_leak_unanchored_subjects_into_fallback():
    from novel_to_comic.style_briefing import style_sample_fallback_brief

    bible = _mixed_bible()
    for index in (4, 5):
        bible.characters.append(bible.characters[0].model_copy(update={
            "id": f"char_00{index}", "name": f"Other{index}",
        }))
    bible.scenes[0].character_ids = [character.id for character in bible.characters]
    bible.scenes[0].summary = "Button and Elsewhere greet Other4 and Other5."
    brief = style_sample_fallback_brief(bible)
    source = _style_sample_brief_source(bible)
    request = build_style_sample_request(Config(), bible, brief, candidate_id="bounded")
    assert "exactly 1 distinct listed character" in request.compiled.final_prompt
    for name in ("Button", "Elsewhere", "Other4", "Other5"):
        assert name not in brief
        assert name not in source
        assert name not in request.compiled.final_prompt


def test_preset_is_required_per_production_and_never_part_of_a_sketch():
    production_schema = StyleProduction.model_json_schema()
    assert production_schema["additionalProperties"] is False
    assert "lettering_preset" in production_schema["required"]
    missing = _production()
    del missing["lettering_preset"]
    with pytest.raises(ValueError, match="lettering_preset"):
        StyleProduction.model_validate(missing)
    sketch_schema = StyleSketchBatch.model_json_schema()
    assert "lettering_preset" not in sketch_schema["properties"]
    assert "lettering_preset" not in sketch_schema["$defs"]["StyleSketch"]["properties"]
    with pytest.raises(ValueError, match="Extra inputs"):
        StyleSketchBatch.model_validate(_batch() | {"lettering_preset": "literary"})


def test_invalid_sketch_batch_gets_one_schema_correction_without_losing_variants():
    wrong = _batch() | {"lettering_preset": "literary"}
    corrected = _batch()
    mock = _text_mock(wrong, corrected)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    sketch_calls = _sketch_calls(mock)
    assert len(sketch_calls) == 2
    second = sketch_calls[1].kwargs
    assert "Correct the previous response" in second["user_content"]
    assert "extra_forbidden" in second["user_content"]
    assert second["json_schema"]["additionalProperties"] is False
    assert [s["role"] for s in suggestions] == list(PORTFOLIO_ROLES)


def test_repeated_invalid_style_response_stops_and_does_not_ignore_extra_fields():
    wrong = _batch() | {'lettering_preset': 'literary'}
    mock = _text_mock(wrong)
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='after 2 attempts'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2


def test_style_schema_correction_shares_the_portfolio_completion_budget():
    wrong = _batch() | {'lettering_preset': 'literary'}
    mock = _text_mock(wrong, _batch(count=1))
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='usable directions'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2


def test_style_provider_failure_is_not_automatically_resubmitted():
    mock = AsyncMock(side_effect=RuntimeError('provider transport failure'))
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='provider transport failure'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 1


def test_a_complete_but_naturalistic_pool_gets_one_diversity_repair():
    first = _batch()
    for candidate in first["styles"]:
        candidate["proportion_family"] = "naturalistic"
        candidate["character_design"] = "Observational adult proportions, realistic limbs and faces."
    repaired = _batch()
    mock = _text_mock(first, repaired)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2
    assert "proportion families" in _sketch_calls(mock)[1].kwargs["system_prompt"]
    assert len({s["proportion_family"] for s in suggestions} - {"naturalistic"}) >= 3


def test_a_complete_but_realism_heavy_pool_gets_one_balance_repair():
    first = _batch()
    for candidate in first["styles"]:
        candidate["visual_logic"] = "realistic_illustration"
        candidate["template"] += " Render with observational realism."
    mock = _text_mock(first, _batch())
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2
    assert "at least 4 stylized/graphic" in _sketch_calls(mock)[1].kwargs["system_prompt"]
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 4


def test_photography_is_optional_not_required():
    # A perfectly viable all-illustrated set must not be rejected to make room
    # for a photo. A single optional photo can also coexist with four stylizations.
    for photo in (False, True):
        batch = _batch(count=SAMPLE_COUNT)
        if photo:
            batch["styles"][-1]["visual_logic"] = "photographic"
            batch["styles"][-1]["proportion_family"] = "naturalistic"
        mock = _text_mock(batch)
        with patch("novel_to_comic.clients.text.generate_json", new=mock):
            suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
        assert len(_sketch_calls(mock)) == 1
        assert sum(s["visual_logic"] == "photographic" for s in suggestions) == int(photo)


def test_persistent_anatomy_sameness_fails_within_the_shared_text_budget():
    batch = _batch()
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="No valid portfolio after 2 text attempts"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2


def test_medium_restriction_does_not_disable_character_design_diversity():
    batch = _batch(restriction="Use only woodblock prints")
    for candidate in batch["styles"]:
        candidate.update(medium="woodblock print", visual_logic="graphic", proportion_family="naturalistic")
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="proportion families"):
            asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
                "text": "Use only woodblock prints",
            }))
    assert len(_sketch_calls(mock)) == 2


def test_explicit_proportions_override_only_the_proportion_axis():
    batch = _batch()
    batch["proportion_restriction"] = "Keep naturalistic proportions"
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Keep naturalistic proportions",
        }))
    assert len(suggestions) == NEIGHBOR_COUNT == 5
    assert {s["proportion_family"] for s in suggestions} == {"naturalistic"}
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 3


def test_explicit_photographic_direction_can_keep_realism_across_neighbors():
    batch = _batch(restriction="Use only photography")
    batch["proportion_restriction"] = "Use only photography"
    for candidate in batch["styles"]:
        candidate.update(visual_logic="photographic", proportion_family="naturalistic")
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Use only photography",
        }))
    assert len(suggestions) == NEIGHBOR_COUNT
    assert {s["visual_logic"] for s in suggestions} == {"photographic"}


def test_a_paraphrased_restriction_is_accepted_on_the_first_attempt():
    paraphrased = _batch()
    paraphrased["proportion_restriction"] = "natural body proportions"
    for candidate in paraphrased["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = _text_mock(paraphrased)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "people should look like real people, I think?",
        }))
    assert len(_sketch_calls(mock)) == 1
    assert {s["proportion_family"] for s in suggestions} == {"naturalistic"}


def test_a_restriction_without_an_author_direction_keeps_the_default_diversity():
    batch = _batch()
    batch["proportion_restriction"] = "naturalistic bodies"
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="proportion families"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2


def test_a_bleak_low_chroma_pool_is_repaired_rather_than_shipped():
    """Regression for Astronomical: six black-and-gold directions rendered as one sepia page."""
    batch = _batch()
    for candidate in batch["styles"]:
        candidate["color_strategy"] = "muted"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="color strategies"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2
    assert "color strategies" in _sketch_calls(mock)[1].kwargs["system_prompt"]


def test_selected_portfolio_spreads_color_strategies():
    mock = _text_mock(_batch())
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))
    strategies = [s["color_strategy"] for s in suggestions]
    assert len(set(strategies)) >= 4
    assert sum(s in {"monochrome", "spot_color", "muted"} for s in strategies) <= 2


def test_explicit_author_color_restriction_keeps_a_single_strategy():
    batch = _batch()
    batch["color_restriction"] = "Black and white only"
    for candidate in batch["styles"]:
        candidate["color_strategy"] = "monochrome"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Black and white manga",
        }))
    assert {s["color_strategy"] for s in suggestions} == {"monochrome"}


def test_extracted_style_notes_are_context_not_a_palette():
    bible = _bible().model_copy(update={"style_notes": "Decay against a warm golden record."})
    context = _suggestion_story_context(bible)
    assert "not art direction" in context
    assert "Decay against a warm golden record." in context


def test_palette_reaches_the_image_prompt_only_with_a_color_strategy():
    legacy = {"template": "Ink with bold brush.", "palette": "teal and coral"}
    assert "COLOR" not in style_template_for_suggestion(legacy)
    current = style_template_for_suggestion(legacy | {"color_strategy": "saturated"})
    assert "COLOR — saturated: teal and coral" in current
    assert "sepia" in current
    # Palette authority is art direction: page art keeps it, lettering does not own it.
    assert "teal and coral" in page_art_style_template(current)



def test_a_novelty_process_outside_the_wildcard_is_repaired_rather_than_shipped():
    """Cyanotype kept recurring as a story-fit proof; novelty is wildcard-only."""
    batch = _batch()
    for candidate in batch["styles"]:
        if candidate["portfolio_role"] == "story_fit_secondary":
            candidate["medium_family"] = "novelty_process"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="novelty_process only in the wildcard"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(_sketch_calls(mock)) == 2


def test_a_story_fit_comic_production_style_is_required():
    batch = _batch()
    for candidate in batch["styles"]:
        if candidate["medium_family"] == "comic_production":
            candidate["medium_family"] = "painted"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="comic_production medium_family"):
            asyncio.run(generate_suggestions(Config(), _bible()))


def test_an_author_medium_restriction_lifts_the_medium_gate():
    batch = _batch(restriction="Cyanotype only")
    for candidate in batch["styles"]:
        candidate["medium_family"] = "novelty_process"
    mock = _text_mock(batch)
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Cyanotype sun prints",
        }))
    assert {s["medium_family"] for s in suggestions} == {"novelty_process"}


def test_selected_portfolio_has_at_most_one_monochrome_option():
    styles = _batch()["styles"]
    for candidate in styles:
        if candidate["portfolio_role"] in {"adjacent", "wildcard"}:
            candidate["color_strategy"] = "monochrome"
    with pytest.raises(RuntimeError, match="at most one monochrome"):
        _select_role_portfolio(styles, PORTFOLIO_ROLES, require_color_diversity=True)


def test_rare_one_word_mediums_do_not_outscore_comic_native_mediums():
    from novel_to_comic.stages.s2_style import _portfolio_distance
    ink = {"medium": "ink and flat color", "medium_family": "comic_production"}
    wash = {"medium": "ink with watercolor wash", "medium_family": "comic_production"}
    cyanotype = {"medium": "cyanotype", "medium_family": "novelty_process"}
    gouache = {"medium": "gouache", "medium_family": "painted"}
    assert _portfolio_distance(ink, cyanotype) == _portfolio_distance(ink, gouache)
    assert _portfolio_distance(ink, wash) < _portfolio_distance(ink, gouache)


def test_regeneration_rotates_previous_novelty_processes():
    from novel_to_comic.stages.s2_style import _build_avoid_block
    block = _build_avoid_block([
        {"label": "Sun print", "medium": "Cyanotype", "medium_family": "novelty_process"},
        {"label": "Flat ink", "medium": "ink and flat color", "medium_family": "comic_production"},
    ])
    assert "Previously used novelty processes: do not use any of them again: cyanotype." in block


def test_monochrome_styles_render_positively_in_the_image_prompt():
    template = style_template_for_suggestion({
        "template": "Prussian-blue sun print.", "palette": "one blue ink", "color_strategy": "monochrome",
    })
    assert "dark line and tone on a light ground" in template
    assert "blueprint-like" in template
    assert "light ground" not in style_template_for_suggestion({
        "template": "Bold ink.", "palette": "teal and coral", "color_strategy": "saturated",
    })


def _scene(scene_id, character_ids, scene_type="transition", beat="rising_action"):
    return Scene(
        id=scene_id, chapter=1, title=scene_id, location_id="loc_001",
        character_ids=character_ids, summary=f"{scene_id} summary.", scene_type=scene_type,
        narrative_beat=beat, source_start_quote=f"{scene_id} opens.",
    )


def _dramatic_bible(scenes):
    bible = _bible()
    extra = bible.characters[0].model_copy(update={"id": "char_002", "name": "Donut"})
    return bible.model_copy(update={"characters": [*bible.characters, extra], "scenes": scenes})


def test_proof_scene_prefers_an_early_dramatic_turn_with_the_lead():
    """Astronomical's proofs showed a lead standing in a hall; pick a scene with drama."""
    from novel_to_comic.style_briefing import style_sample_selection
    bible = _dramatic_bible([
        _scene("scene_001", ["char_001"], "transition", "exposition"),
        _scene("scene_002", ["char_002"], "action", "inciting_incident"),
        _scene("scene_003", ["char_001", "char_002"], "emotional", "inciting_incident"),
        _scene("scene_004", ["char_001"], "action", "climax"),
    ])
    assert style_sample_selection(bible).scene.id == "scene_003"


def test_proof_scene_never_prefers_the_climax_or_a_late_scene():
    from novel_to_comic.style_briefing import style_sample_selection
    scenes = [_scene("scene_001", ["char_001"], "action", "climax")]
    scenes += [_scene(f"scene_{index:03}", ["char_001"]) for index in range(2, 30)]
    scenes.append(_scene("scene_030", ["char_001"], "action", "rising_action"))
    assert style_sample_selection(_dramatic_bible(scenes)).scene.id == "scene_002"


def test_proof_brief_asks_for_a_charged_moment_ending_on_a_face():
    from novel_to_comic.stages.s2_style import STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT
    assert "quiet" not in STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT
    assert "instant just before a turn" in STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT
    assert "face, large in frame" in STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT
    assert "two depth planes" in STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT


@pytest.mark.parametrize("mode", ["editable", "integrated"])
def test_both_proof_modes_carry_the_legibility_clause(mode):
    from novel_to_comic.stages.s2_style import _style_proof_direction
    config = Config(style_template="Bold ink.", lettering_mode=mode)
    _template, constraints = _style_proof_direction(config, None, _bible())
    assert "focal face so its expression reads at thumbnail size" in constraints


# ── stage run ────────────────────────────────────────────────────────────────


def test_stage_run_authors_the_brief_while_suggestions_are_curated(tmp_path, monkeypatch):
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.stages import s2_style
    from novel_to_comic.state import create_initial_state

    artifacts.write_story_bible(tmp_path, _bible())
    brief_started = asyncio.Event()
    logs = []

    async def brief(*_args):
        brief_started.set()
        return BRIEF

    async def suggestions(config, bible, *, on_shortlist):
        await asyncio.wait_for(brief_started.wait(), 1)
        await on_shortlist([{"label": "Midnight ink", "role": "wildcard"}])
        return [normalize_suggestion(_sugg("Midnight ink", "ink"))], []

    async def samples(config, bible, project_dir, suggestions, indices, *, on_sample_done):
        for index in indices:
            await on_sample_done(index, ApiResult(value=None, usage=None))

    monkeypatch.setattr(s2_style, "ensure_style_sample_brief", brief)
    monkeypatch.setattr(s2_style, "generate_suggestions", suggestions)
    monkeypatch.setattr(s2_style, "generate_samples_for_indices", samples)
    ctx = StageRuntime("style", create_initial_state("test", "novel.txt"), tmp_path,
                       on_event=lambda event: logs.append(event.get("message", "")))
    asyncio.run(s2_style.run(Config(), tmp_path, ctx))
    assert any("Midnight ink" in message for message in logs)
    assert s2_style.load_suggestions(tmp_path)[0]["label"] == "Midnight ink"


def test_failed_curation_cancels_the_early_brief(tmp_path, monkeypatch):
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.stages import s2_style
    from novel_to_comic.state import create_initial_state

    artifacts.write_story_bible(tmp_path, _bible())
    cancelled = asyncio.Event()

    async def brief(*_args):
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            cancelled.set()
            raise

    async def suggestions(config, bible, *, on_shortlist):
        await asyncio.sleep(0)
        raise RuntimeError("No valid portfolio")

    monkeypatch.setattr(s2_style, "ensure_style_sample_brief", brief)
    monkeypatch.setattr(s2_style, "generate_suggestions", suggestions)
    ctx = StageRuntime("style", create_initial_state("test", "novel.txt"), tmp_path)
    with pytest.raises(RuntimeError, match="No valid portfolio"):
        asyncio.run(s2_style.run(Config(), tmp_path, ctx))
    assert cancelled.is_set()


def test_curation_preserves_author_direction_admitted_while_awaiting_model(tmp_path, monkeypatch):
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.stages import s2_style
    from novel_to_comic.state import create_initial_state

    artifacts.write_story_bible(tmp_path, _bible())
    author = normalize_suggestion(_sugg("Author's ink", "ink"))
    generated = normalize_suggestion(_sugg("Midnight ink", "ink"))
    drawn = []

    async def suggestions(config, bible, *, on_shortlist):
        s2_style.save_suggestions(tmp_path, [author], bible.title)
        return [generated], []

    async def samples(config, bible, project_dir, candidates, indices, *, on_sample_done):
        for index in indices:
            drawn.append((index, candidates[index - 1]["id"]))
            await on_sample_done(index, ApiResult(value=None, usage=None))

    monkeypatch.setattr(s2_style, "ensure_style_sample_brief", AsyncMock(return_value=BRIEF))
    monkeypatch.setattr(s2_style, "generate_suggestions", suggestions)
    monkeypatch.setattr(s2_style, "generate_samples_for_indices", samples)
    ctx = StageRuntime("style", create_initial_state("test", "novel.txt"), tmp_path)
    asyncio.run(s2_style.run(Config(), tmp_path, ctx))
    assert [candidate["id"] for candidate in s2_style.load_suggestions(tmp_path)] == [author["id"], generated["id"]]
    assert drawn == [(2, generated["id"])]



# ── story proof copy ─────────────────────────────────────────────────────────


def _source_part(tmp_path, passage: str):
    from novel_to_comic.source_extraction import produce_source_document
    from novel_to_comic.target_artifacts import TargetArtifacts
    from novel_to_comic.workspace import part_workspace

    bible = _bible()
    text = "The transformation occurred. " + passage
    bible.scenes[0].source_start_offset = 0
    bible.scenes[0].source_start_quote = "The transformation occurred."
    produce_source_document(
        TargetArtifacts(part_workspace(tmp_path, bible.scenes[0].part_id)), text, bible,
    )
    return bible


def test_proof_copy_quotes_the_scene_passage_and_is_cached(tmp_path):
    from novel_to_comic.lettering.proof import LABEL_COPY
    from novel_to_comic.stages.s2_style import style_proof_copy

    bible = _source_part(tmp_path, '"Where is everyone?" Carl asked the empty street.')
    mock = AsyncMock(return_value=ApiResult(value={**STORY_COPY, "speech": '"Where is everyone?"'}, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock), patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(return_value=ApiResult(value=BRIEF, usage=None)),
    ):
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
        asyncio.run(ensure_style_sample_brief(Config(), bible, tmp_path))
    assert mock.await_count == 1
    call = mock.await_args.kwargs
    assert call["feature"] == "style.proof_copy"
    assert "Where is everyone?" in call["user_content"]
    assert "- Carl" in call["user_content"]
    copy = style_proof_copy(Config(), bible, tmp_path)
    assert copy != LABEL_COPY
    assert copy.speech == "Where is everyone?"  # stray quotation marks are trimmed


def test_overlong_or_failed_proof_copy_falls_back_to_role_labels(tmp_path):
    from novel_to_comic.lettering.proof import LABEL_COPY
    from novel_to_comic.stages.s2_style import style_proof_copy

    for answer in (
        AsyncMock(return_value=ApiResult(value={**STORY_COPY, "speech": "x" * 80}, usage=None)),
        AsyncMock(side_effect=RuntimeError("gateway down")),
    ):
        with patch("novel_to_comic.clients.text.generate_json", new=answer), patch(
            "novel_to_comic.clients.text.generate_text",
            new=AsyncMock(return_value=ApiResult(value=BRIEF, usage=None)),
        ):
            assert asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path)) == BRIEF
        assert style_proof_copy(Config(), _bible(), tmp_path) == LABEL_COPY
        assert not artifacts.style_proof_copy_path(tmp_path).exists()


def test_proof_copy_lines_need_a_listed_owner(tmp_path):
    from novel_to_comic.lettering.proof import LABEL_COPY
    from novel_to_comic.stages.s2_style import style_proof_copy

    for owners in ({"thinker": "Shoshana"}, {"speaker": None}):
        answer = AsyncMock(return_value=ApiResult(value={**STORY_COPY, **owners}, usage=None))
        with patch("novel_to_comic.clients.text.generate_json", new=answer), patch(
            "novel_to_comic.clients.text.generate_text",
            new=AsyncMock(return_value=ApiResult(value=BRIEF, usage=None)),
        ):
            asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))
        assert style_proof_copy(Config(), _bible(), tmp_path) == LABEL_COPY
    answer = AsyncMock(return_value=ApiResult(value={**STORY_COPY, "speaker": "carl"}, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=answer), patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(return_value=ApiResult(value=BRIEF, usage=None)),
    ):
        asyncio.run(ensure_style_sample_brief(Config(), _bible(), tmp_path))
    assert style_proof_copy(Config(), _bible(), tmp_path).speaker == "Carl"


def test_editable_proof_art_stages_line_owners_and_gates_the_overlay(tmp_path):
    from novel_to_comic.lettering.proof import LABEL_COPY, ProofCopy
    from novel_to_comic.stages.s2_style import proof_copy_for_sample, proof_speaker_staging

    config = Config(lettering_mode="editable")
    bible = _bible()
    unstaged = build_style_sample_request(config, bible, BRIEF, candidate_id="c").compiled.final_prompt
    assert "Speaker staging" not in unstaged
    artifacts.style_proof_copy_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    artifacts.style_proof_copy_path(tmp_path).write_text(json.dumps({
        "version": STYLE_PROOF_COPY_VERSION,
        "source_sha256": _style_proof_copy_source_key(config, bible),
        "copy": {**STORY_COPY, "thinker": "Donut"},
    }))
    copy = ProofCopy.model_validate({**STORY_COPY, "thinker": "Donut"})
    staged = build_style_sample_request(
        config, bible, BRIEF, candidate_id="c", project_dir=tmp_path,
    ).compiled.final_prompt
    assert proof_speaker_staging(copy) in staged
    assert "draw Carl with their head just below the speech space" in staged
    assert "draw Donut with their head just below the thought space" in staged

    def sample(name, prompt):
        path = tmp_path / name
        path.write_bytes(b"png")
        artifacts.asset_meta_path(path).write_text(json.dumps({"prompt": prompt}))
        return path

    # Art drawn before its lines had owners keeps role labels under the pointers.
    assert proof_copy_for_sample(copy, sample("old.png", unstaged)) == LABEL_COPY
    assert proof_copy_for_sample(copy, sample("new.png", staged)) == copy
    other = copy.model_copy(update={"thinker": "Carl"})
    assert proof_copy_for_sample(other, tmp_path / "new.png") == LABEL_COPY


def test_integrated_proof_letters_story_copy_once_cached(tmp_path):
    config = Config(lettering_mode="integrated")
    bible = _bible()
    labelled = build_style_sample_request(config, bible, BRIEF, candidate_id="c").compiled.final_prompt
    assert "We keep moving." not in labelled and "not dialogue" in labelled
    artifacts.style_proof_copy_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    artifacts.style_proof_copy_path(tmp_path).write_text(json.dumps({
        "version": STYLE_PROOF_COPY_VERSION,
        "source_sha256": _style_proof_copy_source_key(config, bible),
        "copy": STORY_COPY,
    }))
    story = build_style_sample_request(
        config, bible, BRIEF, candidate_id="c", project_dir=tmp_path,
    ).compiled.final_prompt
    assert all(json.dumps(STORY_COPY[role]) in story for role in ("caption", "speech", "shout", "thought", "sfx"))
    assert "Carl says the speech and shout, Carl thinks the thought" in story
    # New story copy is new request identity: older proofs become refreshable.
    assert story != labelled
