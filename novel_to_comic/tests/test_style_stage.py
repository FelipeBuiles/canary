"""Tests for S2 style suggestions (declared-medium dedup) and the style-sample brief."""

import asyncio
import hashlib
import json
from unittest.mock import AsyncMock, patch

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic.models.story_bible import Character, Location, Scene, StoryBible
from novel_to_comic.stages.s2_style import (
    STYLE_VALIDATION_ACTION,
    STYLE_VALIDATION_COMPOSITION,
    SAMPLE_COUNT,
    _build_avoid_block,
    build_style_sample_request,
    _dedupe_suggestions,
    _select_portfolio,
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
)
from novel_to_comic.style_contract import (
    DEFAULT_LETTERING_STANDARD,
    DEFAULT_PAGE_FRAMING_STANDARD,
    style_template_for_suggestion,
)
from novel_to_comic.usage import ApiResult

BRIEF = (
    "Carl, a broad-shouldered man in his late twenties wearing a worn leather "
    "jacket, stands ankle-deep in fresh snow on a dark Seattle street."
)


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
        narrative_arcs=[],
        props=[],
    )


def _sugg(label: str, medium: str) -> dict:
    return {
        "label": label,
        "medium": medium,
        "template": f"{label}: a vivid forty-word visual direction in this medium.",
    }


# ── declared-medium dedup ────────────────────────────────────────────────────


def test_dedupe_drops_repeated_declared_medium():
    kept = _dedupe_suggestions(
        [_sugg("A", "woodblock print"), _sugg("B", "gouache"), _sugg("C", "woodblock print")]
    )
    assert [s["label"] for s in kept] == ["A", "B"]


def test_dedupe_treats_refined_medium_as_duplicate():
    kept = _dedupe_suggestions([_sugg("A", "etching"), _sugg("B", "copper etching")])
    assert [s["label"] for s in kept] == ["A"]

    # Sharing one token without refinement is not a collision — the LLM's
    # curation pass owns family-level judgement, not the safety net.
    kept = _dedupe_suggestions([_sugg("A", "woodblock print"), _sugg("B", "screen print")])
    assert [s["label"] for s in kept] == ["A", "B"]


def test_dedupe_respects_existing_pool():
    kept = _dedupe_suggestions(
        [_sugg("New", "gouache"), _sugg("Other", "charcoal")],
        existing_suggestions=[_sugg("Old", "gouache")],
    )
    assert [s["label"] for s in kept] == ["Other"]


def test_dedupe_keeps_legacy_and_drops_malformed():
    # Legacy suggestions (pre-medium) never collide; empty templates are dropped.
    kept = _dedupe_suggestions(
        [
            {"label": "Empty", "medium": "ink", "template": "  "},
            {"label": "Legacy", "template": "a style with no declared medium yet."},
            _sugg("Inked", "ink"),
        ],
        existing_suggestions=[{"label": "OldLegacy", "template": "older style."}],
    )
    assert [s["label"] for s in kept] == ["Legacy", "Inked"]


def test_build_avoid_block_lists_used_mediums():
    assert _build_avoid_block([]) == ""

    block = _build_avoid_block([_sugg("A", "Woodblock Print"), _sugg("B", "gouache")])
    assert "ALREADY been suggested" in block
    assert "woodblock print" in block
    assert "gouache" in block


def test_portfolio_selector_prefers_palette_and_finish_variance_over_gray_wall():
    gray = [
        {**_sugg(f"Gray {i}", f"medium {i}"), "palette": "desaturated gray",
         "line_rendering": "soft painterly", "lighting_value": "low key muted"}
        for i in range(3)
    ]
    vivid = [
        {**_sugg(f"Vivid {i}", f"vivid medium {i}"), "palette": palette,
         "line_rendering": line, "lighting_value": light}
        for i, (palette, line, light) in enumerate([
            ("scarlet cyan gold", "crisp geometric blocks", "high key graphic"),
            ("violet lime black", "scratchy crosshatch", "hard chiaroscuro"),
            ("coral teal cream", "clean ligne claire", "sunlit open values"),
            ("indigo ochre white", "torn collage edges", "flat poster values"),
            ("magenta orange navy", "bold dry brush", "neon rim light"),
        ])
    ]
    selected = _select_portfolio(gray + vivid)
    assert selected[0]["label"] == "Gray 0"  # preserve strongest model-ranked fit
    assert sum(item["label"].startswith("Vivid") for item in selected) == 4


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


def test_generate_suggestions_dedupes_and_trims_to_sample_count():
    mediums = [
        "woodblock print", "gouache", "35mm photography", "cut-paper collage",
        "charcoal", "woodblock print", "oil paint", "gouache",
    ]
    raw = [_sugg(f"S{i}", m) for i, m in enumerate(mediums)]
    mock = AsyncMock(return_value=ApiResult(value=raw, usage=None))

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    assert [s["label"] for s in suggestions] == ["S0", "S1", "S2", "S3", "S4"]
    assert len(suggestions) == SAMPLE_COUNT
    assert mock.await_count == 1
    assert [s["role"] for s in suggestions] == [
        "story_fit_primary", "story_fit_secondary", "adjacent", "contrast", "wildcard",
    ]
    assert all(s["id"].startswith("style_") for s in suggestions)


def test_generate_suggestions_receives_story_substance_and_custom_direction():
    raw = [_sugg(f"S{i}", f"medium {i}") for i in range(8)]
    mock = AsyncMock(return_value=ApiResult(value=raw, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        asyncio.run(generate_suggestions(
            Config(), _bible(), custom_direction={"text": "Luminous jewel tones"},
        ))
    content = mock.await_args.kwargs["user_content"]
    assert "Carl outside." in content
    assert "Seattle Street" in content
    assert "1man, adult male, leather jacket" in content
    assert "Luminous jewel tones" in content
    system = mock.await_args.kwargs["system_prompt"]
    assert "lettering" in system
    assert "page_framing" in system


def test_suggestion_carries_one_explicit_book_wide_production_standard():
    suggestion = normalize_suggestion({
        **_sugg("Etched dread", "etching"),
        "lettering": "Sentence case in one condensed grotesk; ivory balloons.",
        "page_framing": "Full bleed on every page with straight black gutters.",
    })

    selected = style_template_for_suggestion(suggestion)

    assert "LETTERING STANDARD — Sentence case in one condensed grotesk" in selected
    assert "PAGE FRAMING STANDARD — Full bleed on every page" in selected


def test_legacy_suggestion_receives_safe_consistent_production_defaults():
    suggestion = normalize_suggestion(_sugg("Legacy", "ink"))

    assert suggestion["lettering"] == DEFAULT_LETTERING_STANDARD
    assert suggestion["page_framing"] == DEFAULT_PAGE_FRAMING_STANDARD


def test_generate_suggestions_retries_with_expanded_avoid_pool():
    first = [_sugg("A", "gouache"), _sugg("B", "ink"), _sugg("C", "gouache")]
    second = [
        _sugg("D", "gouache"),  # repeats a kept medium — dropped by safety net
        _sugg("E", "charcoal"),
        _sugg("F", "35mm photography"),
        _sugg("G", "woodblock print"),
    ]
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None),
        ApiResult(value=second, usage=None),
    ])

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    assert [s["label"] for s in suggestions] == ["A", "B", "E", "F", "G"]
    assert mock.await_count == 2
    retry_system = mock.await_args.kwargs["system_prompt"]
    assert "ALREADY been suggested" in retry_system
    assert "gouache" in retry_system
    assert "ink" in retry_system


def test_generate_suggestions_fails_instead_of_completing_partial_portfolio():
    mock = AsyncMock(return_value=ApiResult(value=[_sugg("Only", "gouache")], usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="5 are required"):
            asyncio.run(generate_suggestions(Config(), _bible()))


# ── style-sample brief ───────────────────────────────────────────────────────


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
            Config(prompt_model="prompt-fast"), _bible(), tmp_path,
        ))
        asyncio.run(ensure_style_sample_brief(
            Config(prompt_model="prompt-quality"), _bible(), tmp_path,
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
    config = Config(image_model="image-balanced")
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
    assert referenced == pytest.approx(0.03)
    assert unreferenced == pytest.approx(0.03)
    assert text_cost.call_count == 2
    assert captured[0]["ref_count"] == 1
    assert captured[0]["ref_image_sizes"] == [(12, 14)]
    assert captured[1]["ref_count"] == 0
    assert captured[0]["width"] > 0 and captured[0]["height"] > 0
    assert captured[0]["prompt_text"]

    brief_path = artifacts.style_sample_brief_path(tmp_path)
    brief_path.parent.mkdir(parents=True, exist_ok=True)
    brief_path.write_text(json.dumps({
        "source_sha256": _style_sample_brief_source_key(config, bible),
        "brief": BRIEF,
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
    assert meta["parameters"]["width"] == 819
    assert meta["parameters"]["height"] == 1024
    assert "exactly 1 distinct listed character" in meta["prompt"]
    assert "one coherent complete comic page" in meta["prompt"]
    assert "The night held its breath." in meta["prompt"]
    assert "We keep moving." in meta["prompt"]
    assert "LETTERING STANDARD —" in meta["prompt"]
    assert "PAGE FRAMING STANDARD —" in meta["prompt"]
    assert "no text, captions, speech balloons" not in meta["prompt"]
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
        Config(style_template="Bold ink"), _bible(), "Carl lunges across the snowy street.",
        candidate_id="style_validation", subject_action=STYLE_VALIDATION_ACTION,
        composition=STYLE_VALIDATION_COMPOSITION,
    )
    assert request.input.prompt.subjects[0].action == STYLE_VALIDATION_ACTION
    assert STYLE_VALIDATION_COMPOSITION in request.compiled.final_prompt
    assert "quiet characteristic action" not in request.compiled.final_prompt
    assert "exactly 1 distinct listed character" in request.compiled.final_prompt
    assert "The night held its breath." in request.compiled.final_prompt
