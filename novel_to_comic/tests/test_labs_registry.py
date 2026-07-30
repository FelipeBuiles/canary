from novel_to_comic.labs.registry import get_entry


def test_seedream_v5_direct_models_use_current_fal_endpoint_ids() -> None:
    assert get_entry("seedream-v5-lite-edit").endpoint == "bytedance/seedream/v5/lite/edit"
    assert get_entry("seedream-v5-pro-edit").endpoint == "bytedance/seedream/v5/pro/edit"


def test_production_quality_labs_entry_uses_gateway_alias() -> None:
    entry = get_entry("gpt-image-2-production-quality")
    assert entry.endpoint == "image-quality"
    assert entry.provider == "litellm"
