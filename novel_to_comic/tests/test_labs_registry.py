from novel_to_comic.labs.registry import get_entry


def test_seedream_v5_direct_models_use_current_fal_endpoint_ids() -> None:
    assert get_entry("seedream-v5-lite-edit").endpoint == "bytedance/seedream/v5/lite/edit"
    assert get_entry("seedream-v5-pro-edit").endpoint == "bytedance/seedream/v5/pro/edit"


def test_production_gpt_image_entry_uses_gateway_alias() -> None:
    entry = get_entry("gpt-image-2-production")
    assert entry.endpoint == "image-gpt-2"
    assert entry.provider == "litellm"


def test_all_labs_gateway_endpoints_exist_in_gateway_config() -> None:
    from pathlib import Path
    import yaml
    from novel_to_comic.labs.registry import load_registry

    gateway = Path(__file__).resolve().parents[2] / "litellm" / "config.yaml"
    aliases = {entry["model_name"] for entry in yaml.safe_load(gateway.read_text())["model_list"]}
    for entry in load_registry():
        if entry.provider == "litellm":
            assert entry.endpoint in aliases, entry.id
