from novel_to_comic.labs.registry import get_entry


def test_sunburst_entry_uses_the_production_gateway_alias() -> None:
    entry = get_entry("sunburst")
    assert entry.endpoint == "image-sunburst"
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
