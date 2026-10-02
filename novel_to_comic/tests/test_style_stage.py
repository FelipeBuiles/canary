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
    STYLE_VALIDATION_ACTION,
    STYLE_VALIDATION_COMPOSITION,
    PORTFOLIO_ROLES,
    SAMPLE_COUNT,
    NEIGHBOR_COUNT,
    LLM_REQUEST_COUNT,
    StyleSuggestionBatch,
    build_style_sample_request,
    _dedupe_suggestions,
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
)
from novel_to_comic.style_contract import (
    DEFAULT_LETTERING_STANDARD,
    DEFAULT_PAGE_FRAMING_STANDARD,
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
            "palette": f"palette {index}",
            "line_rendering": f"finish {index}",
            "lighting_value": f"lighting {index}",
            "lettering": DEFAULT_LETTERING_STANDARD,
            "lettering_preset": "literary",
            "lettering_design": {"label": "Literary", "roles": LetteringRoles().model_dump()},
            "page_framing": DEFAULT_PAGE_FRAMING_STANDARD,
            "sequential_art_strengths": "Readable action and recurring identities.",
            "story_fit": "Supports the story.",
            "risk": "Detailed finish.",
        })
    return {"medium_restriction_quote": restriction, "proportion_restriction_quote": "", "styles": styles}


# ── declared-medium dedup ────────────────────────────────────────────────────


def test_dedup_preserves_distinct_directions_within_an_author_medium():
    first = _sugg("Earthy", "woodblock print")
    second = _sugg("Luminous", "woodblock print")
    kept = _dedupe_suggestions(
        [first, second, {**second, "label": "Renamed duplicate"}],
        existing_suggestions=[first],
    )
    assert kept == [second]


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
    mock = AsyncMock(return_value=ApiResult(value=_batch(), usage=None))
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
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError):
            asyncio.run(generate_suggestions(Config(), _bible()))


def test_explicit_author_medium_restriction_preserves_narrowed_neighbors():
    batch = _batch(restriction="Use only woodblock prints")
    for candidate in batch["styles"]:
        candidate["visual_logic"] = "graphic"
        candidate["medium"] = "woodblock print"
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(
            Config(), _bible(), custom_direction={
                "id": "direction_1234567890abcdef", "text": "Use only woodblock prints",
            },
        ))
    assert {s["medium"] for s in suggestions} == {"woodblock print"}
    assert {s["visual_logic"] for s in suggestions} == {"graphic"}
    assert {s["style_reference_mode"] for s in suggestions} == {"variation"}


def test_model_cannot_claim_an_unquoted_author_medium_restriction():
    mock = AsyncMock(return_value=ApiResult(value=_batch(restriction="only ink"), usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(ValueError):
            asyncio.run(generate_suggestions(
                Config(), _bible(), custom_direction={"text": "A hopeful mood"},
            ))


def test_generated_production_standards_reject_untyped_objects():
    batch = _batch()
    batch["styles"][0]["lettering"] = {"unrecognized": ["nested", "values"]}
    with pytest.raises(ValueError):
        StyleSuggestionBatch.model_validate(batch)




def test_generate_suggestions_completes_an_undersized_pool():
    complete = _batch()
    first = {**complete, "styles": complete["styles"][:2]}
    second = {**complete, "styles": complete["styles"][2:]}
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None), ApiResult(value=second, usage=None),
    ])
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
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None), ApiResult(value=second, usage=None),
    ])

    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))

    assert mock.await_count == 2
    assert "story_fit_secondary" in mock.await_args_list[1].kwargs["system_prompt"]
    assert [s["role"] for s in suggestions] == list(PORTFOLIO_ROLES)


def test_generate_suggestions_rejects_partial_portfolio():
    mock = AsyncMock(return_value=ApiResult(value=_batch(count=1), usage=None))
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
        "version": STYLE_BRIEF_VERSION,
        "kind": "style_sample_brief",
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


def test_preset_is_required_per_candidate_not_allowed_at_batch_root():
    batch = _batch()
    schema = StyleSuggestionBatch.model_json_schema()
    assert schema['additionalProperties'] is False
    assert 'lettering_preset' not in schema['properties']
    assert 'lettering_preset' in schema['$defs']['StyleSuggestion']['required']
    batch['lettering_preset'] = 'literary'
    with pytest.raises(ValueError, match='Extra inputs'):
        StyleSuggestionBatch.model_validate(batch)
    del batch['lettering_preset']
    del batch['styles'][0]['lettering_preset']
    with pytest.raises(ValueError, match='lettering_preset'):
        StyleSuggestionBatch.model_validate(batch)


def test_root_level_preset_gets_one_schema_correction_without_losing_variants():
    wrong = _batch()
    wrong['lettering_preset'] = 'literary'
    for candidate in wrong['styles']:
        del candidate['lettering_preset']
    corrected = _batch()
    for i, candidate in enumerate(corrected['styles']):
        candidate['lettering_preset'] = ('literary', 'classic', 'pulp', 'minimal')[i % 4]
    expected = {s['label']: s['lettering_preset'] for s in corrected['styles']}
    mock = AsyncMock(side_effect=[ApiResult(value=wrong, usage=None), ApiResult(value=corrected, usage=None)])
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2
    second = mock.await_args_list[1].kwargs
    assert 'INSIDE EACH style' in second['user_content']
    assert 'extra_forbidden' in second['user_content']
    assert second['json_schema']['additionalProperties'] is False
    assert all(s['lettering_preset'] == expected[s['label']] for s in suggestions)
    assert 'lettering_preset' in mock.await_args_list[0].kwargs['system_prompt']


def test_repeated_invalid_style_response_stops_and_does_not_ignore_extra_fields():
    wrong = _batch() | {'lettering_preset': 'literary'}
    mock = AsyncMock(return_value=ApiResult(value=wrong, usage=None))
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='after 2 attempts'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2


def test_style_schema_correction_shares_the_portfolio_completion_budget():
    wrong = _batch() | {'lettering_preset': 'literary'}
    mock = AsyncMock(side_effect=[ApiResult(value=wrong, usage=None), ApiResult(value=_batch(count=1), usage=None)])
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='usable directions'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2


def test_style_provider_failure_is_not_automatically_resubmitted():
    mock = AsyncMock(side_effect=RuntimeError('provider transport failure'))
    with patch('novel_to_comic.clients.text.generate_json', new=mock):
        with pytest.raises(RuntimeError, match='provider transport failure'):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 1


def test_a_complete_but_naturalistic_pool_gets_one_diversity_repair():
    first = _batch()
    for candidate in first["styles"]:
        candidate["proportion_family"] = "naturalistic"
        candidate["character_design"] = "Observational adult proportions, realistic limbs and faces."
    repaired = _batch()
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None), ApiResult(value=repaired, usage=None),
    ])
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2
    assert "proportion families" in mock.await_args_list[1].kwargs["system_prompt"]
    assert len({s["proportion_family"] for s in suggestions} - {"naturalistic"}) >= 3


def test_a_complete_but_realism_heavy_pool_gets_one_balance_repair():
    first = _batch()
    for candidate in first["styles"]:
        candidate["visual_logic"] = "realistic_illustration"
        candidate["template"] += " Render with observational realism."
    mock = AsyncMock(side_effect=[
        ApiResult(value=first, usage=None), ApiResult(value=_batch(), usage=None),
    ])
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2
    assert "at least 4 stylized/graphic" in mock.await_args_list[1].kwargs["system_prompt"]
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 4


def test_photography_is_optional_not_required():
    # A perfectly viable all-illustrated set must not be rejected to make room
    # for a photo. A single optional photo can also coexist with four stylizations.
    for photo in (False, True):
        batch = _batch(count=SAMPLE_COUNT)
        if photo:
            batch["styles"][-1]["visual_logic"] = "photographic"
            batch["styles"][-1]["proportion_family"] = "naturalistic"
        mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
        with patch("novel_to_comic.clients.text.generate_json", new=mock):
            suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible()))
        assert mock.await_count == 1
        assert sum(s["visual_logic"] == "photographic" for s in suggestions) == int(photo)


def test_persistent_anatomy_sameness_fails_within_the_shared_text_budget():
    batch = _batch()
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="No valid portfolio after 2 text attempts"):
            asyncio.run(generate_suggestions(Config(), _bible()))
    assert mock.await_count == 2


def test_medium_restriction_does_not_disable_character_design_diversity():
    batch = _batch(restriction="Use only woodblock prints")
    for candidate in batch["styles"]:
        candidate.update(medium="woodblock print", visual_logic="graphic", proportion_family="naturalistic")
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="proportion families"):
            asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
                "text": "Use only woodblock prints",
            }))
    assert mock.await_count == 2


def test_explicit_proportions_override_only_the_proportion_axis():
    batch = _batch()
    batch["proportion_restriction_quote"] = "Keep naturalistic proportions"
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Keep naturalistic proportions",
        }))
    assert len(suggestions) == NEIGHBOR_COUNT == 5
    assert {s["proportion_family"] for s in suggestions} == {"naturalistic"}
    assert sum(s["visual_logic"] in {"stylized", "graphic"} for s in suggestions) >= 3


def test_explicit_photographic_direction_can_keep_realism_across_neighbors():
    batch = _batch(restriction="Use only photography")
    batch["proportion_restriction_quote"] = "Use only photography"
    for candidate in batch["styles"]:
        candidate.update(visual_logic="photographic", proportion_family="naturalistic")
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Use only photography",
        }))
    assert len(suggestions) == NEIGHBOR_COUNT
    assert {s["visual_logic"] for s in suggestions} == {"photographic"}


def test_proportion_restrictions_must_quote_the_author_not_the_story():
    batch = _batch()
    batch["proportion_restriction_quote"] = "naturalistic bodies"
    mock = AsyncMock(return_value=ApiResult(value=batch, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(ValueError, match="Proportion restriction must quote"):
            asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={"text": "A serious mood"}))
    assert mock.await_count == 2


def test_a_paraphrased_restriction_quote_is_repaired_on_the_shared_attempt():
    misquoted = _batch()
    misquoted["proportion_restriction_quote"] = "natural body proportions"
    repaired = _batch()
    repaired["proportion_restriction_quote"] = "Keep naturalistic proportions"
    for candidate in repaired["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = AsyncMock(side_effect=[
        ApiResult(value=misquoted, usage=None), ApiResult(value=repaired, usage=None),
    ])
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Keep naturalistic proportions",
        }))
    assert mock.await_count == 2
    correction = mock.await_args_list[1].kwargs["user_content"]
    assert "Correct the restriction quotes" in correction
    assert "Proportion restriction must quote" in correction
    assert "natural body proportions" in correction
    assert {s["proportion_family"] for s in suggestions} == {"naturalistic"}


def test_a_restriction_quote_differing_only_in_typography_is_the_authors_own_words():
    quoted = _batch()
    quoted["proportion_restriction_quote"] = "\u201ckeep  naturalistic proportions.\u201d"
    for candidate in quoted["styles"]:
        candidate["proportion_family"] = "naturalistic"
    mock = AsyncMock(return_value=ApiResult(value=quoted, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _ = asyncio.run(generate_suggestions(Config(), _bible(), custom_direction={
            "text": "Please keep naturalistic proportions, always",
        }))
    assert mock.await_count == 1
    assert {s["proportion_family"] for s in suggestions} == {"naturalistic"}


@pytest.mark.parametrize(("quote", "author", "span"), [
    ("keep naturalistic proportions.", "Keep naturalistic proportions", "Keep naturalistic proportions"),
    ("\u201cno anime\u201d", 'Please, "No  anime" at all', "No  anime"),
    ("natural body proportions", "Keep naturalistic proportions", None),
    ("...", "Keep naturalistic proportions", None),
    ("anime", "", None),
])
def test_author_quote_span_returns_only_the_authors_text(quote, author, span):
    from novel_to_comic.stages.s2_style import author_quote_span

    assert author_quote_span(quote, author) == span


def test_proportion_diversity_is_role_compatible_not_just_present_in_the_pool():
    batch = _batch()
    for candidate in batch["styles"]:
        candidate["proportion_family"] = "naturalistic"
    # All the interesting designs compete for just ONE slot. The union of the
    # pool looks diverse, but no one-per-role portfolio can contain four families.
    for family in ("compact", "elongated", "heroic", "geometric"):
        batch["styles"].append({**batch["styles"][0], "proportion_family": family})
    with pytest.raises(RuntimeError, match="proportion families"):
        _select_role_portfolio(batch["styles"], PORTFOLIO_ROLES, require_proportion_diversity=True)


def test_shape_difference_outweighs_surface_wording_difference():
    from novel_to_comic.stages.s2_style import _portfolio_distance

    base = {"proportion_family": "naturalistic", "visual_logic": "stylized",
            "medium": "ink", "palette": "red", "line_rendering": "fine", "lighting_value": "flat"}
    new_finish = {**base, "medium": "oil", "palette": "blue", "line_rendering": "thick", "lighting_value": "rim"}
    new_shape = {**base, "proportion_family": "compact"}
    assert _portfolio_distance(base, new_shape) > _portfolio_distance(base, new_finish)


def test_character_design_is_required_persisted_and_part_of_art_authority(tmp_path):
    from novel_to_comic.stages.s2_style import load_suggestions, save_suggestions
    from novel_to_comic.style_contract import rendering_style_template, style_template_for_suggestion

    batch = _batch()
    raw = batch["styles"][1]
    suggestion = normalize_suggestion(raw)
    save_suggestions(tmp_path, [suggestion], "Test")
    loaded = load_suggestions(tmp_path)[0]
    assert loaded == suggestion
    template = style_template_for_suggestion(loaded)
    assert raw["character_design"] in rendering_style_template(template)
    request = build_style_sample_request(
        Config(style_template=template), _bible(), BRIEF, candidate_id=suggestion["id"],
    )
    assert raw["character_design"] in request.compiled.final_prompt
    assert _bible().characters[0].visual_anchor in request.compiled.final_prompt
    assert "Do not normalize stylized or graphic figures" in request.compiled.final_prompt
    for field, replacement in (("character_design", "Other coherent silhouettes and deliberate exaggerated faces."),
                               ("proportion_family", "elongated"), ("visual_logic", "graphic")):
        changed = normalize_suggestion({**raw, field: replacement})
        assert changed["id"] != suggestion["id"]
    del raw["character_design"]
    with pytest.raises(ValueError, match="character_design"):
        StyleSuggestionBatch.model_validate(batch)


def test_unchanged_saved_direction_does_not_gain_a_new_identity_or_authority():
    from novel_to_comic.style_contract import page_style_template, style_template_for_suggestion

    legacy = _sugg("Existing", "ink")
    assert style_template_for_suggestion(normalize_suggestion(legacy)) == page_style_template(legacy["template"])
    assert normalize_suggestion(normalize_suggestion(legacy)) == normalize_suggestion(legacy)


def test_suggestion_output_budget_fits_a_full_strict_lettering_batch():
    # Strict schemas require every RoleStyle token; the shared 16k default
    # truncated every twelve-candidate batch (finish_reason=length).
    mock = AsyncMock(return_value=ApiResult(value=_batch(), usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        asyncio.run(generate_suggestions(Config(), _bible()))
    budget = mock.call_args.kwargs["max_output_tokens"]
    lettering_chars = len(json.dumps([s["lettering_design"] for s in _batch()["styles"]], indent=6))
    # ~3 JSON chars per token; prose fields add roughly as much again.
    assert budget * 3 >= 2 * lettering_chars


def test_schema_invalid_response_is_repaired_on_the_shared_attempt():
    invalid = {**_batch(), "lettering_preset": "noir"}
    mock = AsyncMock(side_effect=[
        ApiResult(value=invalid, usage=None), ApiResult(value=_batch(), usage=None),
    ])
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        suggestions, _usage = asyncio.run(generate_suggestions(Config(), _bible()))
    assert len(suggestions) == SAMPLE_COUNT
    assert "Correct the previous response" in mock.call_args.kwargs["user_content"]


def test_schema_invalid_final_attempt_fails_without_fabricating_directions():
    invalid = {**_batch(), "lettering_preset": "noir"}
    mock = AsyncMock(return_value=ApiResult(value=invalid, usage=None))
    with patch("novel_to_comic.clients.text.generate_json", new=mock):
        with pytest.raises(RuntimeError, match="did not match the required schema"):
            asyncio.run(generate_suggestions(Config(), _bible()))
