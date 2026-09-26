"""Tests for pipeline config (config.py)."""

import tempfile
from pathlib import Path

import yaml

from novel_to_comic.image_models import GATEWAY_IMAGE_BALANCED
from novel_to_comic.config import (
    Config,
    GATEWAY_IMAGE_FAST,
    GATEWAY_IMAGE_QUALITY,
    GATEWAY_IMAGE_SUNBURST,
    GATEWAY_SOL,
    GATEWAY_LUNA,
    config_for_image_model_alias,
    image_model_aliases,
    LANGUAGE_NAMES,
    is_gpt_image_2,
    is_seedream_model,
    validate_image_model_alias,
    save_config,
    load_config,
)


class TestLanguageNames:
    def test_all_target_languages_known(self):
        assert "en" in LANGUAGE_NAMES
        assert "es" in LANGUAGE_NAMES
        assert "fr" in LANGUAGE_NAMES
        assert LANGUAGE_NAMES["en"] == "English"
        assert LANGUAGE_NAMES["es"] == "Spanish"
        assert LANGUAGE_NAMES["fr"] == "French"


class TestConfigDefaults:
    def test_dev_mode_defaults_to_false(self):
        cfg = Config()
        assert cfg.dev_mode is False

    def test_target_language_defaults_to_en(self):
        cfg = Config()
        assert cfg.target_language == "en"

    def test_style_template_is_populated(self):
        cfg = Config()
        assert len(cfg.style_template) > 0
        assert "noisy grain" in cfg.style_template
        assert "repeated texture fields" in cfg.style_template

    def test_image_quality_defaults_to_medium(self):
        cfg = Config()
        assert cfg.image_quality == "medium"

    def test_cost_limit_default_is_none(self):
        cfg = Config()
        assert cfg.cost_limit_usd is None

    def test_gateway_aliases_are_default_models(self):
        cfg = Config()
        assert cfg.extraction_model == GATEWAY_LUNA
        assert cfg.adapt_model == GATEWAY_SOL
        assert cfg.plan_model == GATEWAY_SOL
        assert cfg.prompt_model == GATEWAY_LUNA
        assert cfg.image_model == GATEWAY_IMAGE_SUNBURST
        assert cfg.draw_model == GATEWAY_IMAGE_SUNBURST

    def test_litellm_defaults_are_populated(self):
        cfg = Config()
        assert cfg.litellm_base_url == "http://localhost:4000"
        assert cfg.litellm_api_key == "sk-local-canary"
        assert cfg.ai_bill_failed_requests == "provider_usage_only"


class TestEffectiveImageModel:
    def test_returns_configured_model_when_not_dev_mode(self):
        cfg = Config(dev_mode=False, image_model="gpt-image-1")
        assert cfg.effective_image_model() == "gpt-image-1"

    def test_dev_mode_does_not_change_selected_model(self):
        cfg = Config(dev_mode=True, image_model="image-sunburst")
        assert cfg.effective_image_model() == "image-sunburst"



class TestImageModelAliases:
    def test_exposes_production_gateway_aliases(self):
        assert image_model_aliases() == ("image-sunburst",)

    def test_validates_supported_alias(self):
        assert validate_image_model_alias(" image-sunburst ") == GATEWAY_IMAGE_SUNBURST

    def test_blank_alias_means_project_default(self):
        assert validate_image_model_alias("") is None
        assert validate_image_model_alias(None) is None

    def test_rejects_raw_provider_model(self):
        try:
            validate_image_model_alias("openai/gpt-image-2")
        except ValueError as exc:
            assert "image_model_alias must be one of" in str(exc)
        else:
            raise AssertionError("raw provider model should be rejected")

    def test_one_shot_alias_copy_does_not_mutate_original(self):
        cfg = Config(image_model=GATEWAY_IMAGE_FAST)
        copied = config_for_image_model_alias(cfg, GATEWAY_IMAGE_SUNBURST)

        assert copied is not cfg
        assert copied.image_model == GATEWAY_IMAGE_SUNBURST
        assert cfg.image_model == GATEWAY_IMAGE_FAST



class TestGptImage2Alias:
    def test_quality_alias_is_gpt_image_2(self):
        assert is_gpt_image_2(GATEWAY_IMAGE_QUALITY) is True

    def test_balanced_alias_is_not_gpt_image_2(self):
        assert is_gpt_image_2(GATEWAY_IMAGE_BALANCED) is False

    def test_direct_provider_model_is_gpt_image_2(self):
        assert is_gpt_image_2("openai/gpt-image-2") is True

    def test_aliases_match_repository_litellm_config(self):
        root = Path(__file__).resolve().parents[2]
        gateway = yaml.safe_load((root / "litellm/config.yaml").read_text())
        routes = {entry["model_name"] for entry in gateway["model_list"]}
        assert set(image_model_aliases()) <= routes



class TestSeedreamModelAlias:
    def test_quality_alias_is_not_seedream(self):
        assert is_seedream_model(GATEWAY_IMAGE_QUALITY) is False

    def test_balanced_alias_is_not_seedream(self):
        assert is_seedream_model(GATEWAY_IMAGE_BALANCED) is False


class TestLanguageHelpers:
    def test_language_code_en(self):
        cfg = Config(target_language="en")
        assert cfg.language_code() == "en"
        assert cfg.language_name() == "English"

    def test_language_code_es(self):
        cfg = Config(target_language="es")
        assert cfg.language_code() == "es"
        assert cfg.language_name() == "Spanish"

    def test_unknown_language_falls_back_to_en(self):
        cfg = Config(target_language="de")
        assert cfg.language_code() == "en"

    def test_generation_language_instruction_en(self):
        cfg = Config(target_language="en")
        instr = cfg.generation_language_instruction()
        assert "English" in instr
        assert "JSON keys" in instr

    def test_generation_language_instruction_es_translates(self):
        cfg = Config(target_language="es")
        instr = cfg.generation_language_instruction()
        assert "Español" in instr or "Spanish" in instr


class TestEffectiveImageConcurrency:
    def test_dev_mode_returns_dev_concurrency(self):
        cfg = Config(dev_mode=True, dev_image_concurrency=3)
        assert cfg.effective_image_concurrency() == 3

    def test_sunburst_route_uses_general_default(self):
        cfg = Config(dev_mode=False, max_concurrent_requests=5)
        assert cfg.effective_image_concurrency() == 5

    def test_explicit_image_concurrency_overrides_provider_default(self):
        cfg = Config(dev_mode=False, image_concurrency=8)
        assert cfg.effective_image_concurrency() == 8

    def test_default_uses_max_concurrent_requests(self):
        cfg = Config(dev_mode=False, max_concurrent_requests=5, image_model="image-sunburst")
        assert cfg.effective_image_concurrency() == 5

    def test_minimum_1(self):
        cfg = Config(dev_mode=False, max_concurrent_requests=0, image_model="image-sunburst")
        assert cfg.effective_image_concurrency() == 1
        cfg = Config(dev_mode=False, image_concurrency=0)
        assert cfg.effective_image_concurrency() == 1


class TestLoadConfig:
    def test_loads_empty_dict_as_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg, env_file = load_config(Path(tmpdir))
        assert cfg.target_language == "en"
        assert env_file is None

    def test_yaml_overrides_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.yaml").write_text(
                "target_language: es\ndev_mode: true\n"
            )
            cfg, env_file = load_config(Path(tmpdir))
        assert cfg.target_language == "es"
        assert cfg.dev_mode is True

    def test_missing_yaml_returns_defaults(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg, env_file = load_config(Path(tmpdir))
        assert cfg.target_language == "en"

    def test_litellm_env_overrides_yaml(self, monkeypatch):
        monkeypatch.setenv("LITELLM_BASE_URL", "http://gateway.local:4000")
        monkeypatch.setenv("LITELLM_API_KEY", "sk-test")
        monkeypatch.setenv("AI_BILL_FAILED_REQUESTS", "never")
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.yaml").write_text(
                "litellm_base_url: http://from-yaml:4000\n"
                "litellm_api_key: sk-yaml\n"
                "ai_bill_failed_requests: estimate_all\n"
            )
            cfg, env_file = load_config(Path(tmpdir))
        assert cfg.litellm_base_url == "http://gateway.local:4000"
        assert cfg.litellm_api_key == "sk-test"
        assert cfg.ai_bill_failed_requests == "never"

    def test_legacy_project_routing_and_credentials_are_ignored(self, monkeypatch):
        for key in ("LITELLM_BASE_URL", "LITELLM_API_KEY", "AI_BILL_FAILED_REQUESTS"):
            monkeypatch.delenv(key, raising=False)
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "config.yaml").write_text(
                "adapt_model: legacy-model\n"
                "image_provider: gemini\n"
                "litellm_base_url: http://untrusted-gateway:4000\n"
                "litellm_api_key: sk-untrusted\n"
                "ai_bill_failed_requests: never\n"
                "extraction_chunk_chars: 12000\n"
            )
            cfg, _ = load_config(Path(tmpdir))
        assert cfg.adapt_model == GATEWAY_SOL
        assert cfg.litellm_base_url == "http://localhost:4000"
        assert cfg.litellm_api_key == "sk-local-canary"
        assert cfg.ai_bill_failed_requests == "provider_usage_only"
        assert cfg.extraction_chunk_chars == 12000


class TestSaveConfig:
    def test_roundtrip(self):
        cfg = Config(dev_mode=True, target_language="fr", extraction_chunk_chars=12000, narrative_max_calls=6)
        with tempfile.TemporaryDirectory() as tmpdir:
            save_config(cfg, Path(tmpdir))
            path = Path(tmpdir) / "config.yaml"
            assert path.exists()
            content = path.read_text()
            assert "fr" in content
            assert "dev_mode: true" in content
            assert "image_model:" not in content
            assert "quality_preset:" not in content
            assert "litellm_api_key:" not in content
            assert "google_cloud_project:" not in content
            assert "flux_guidance_scale:" not in content
            loaded, _ = load_config(Path(tmpdir))
            assert loaded.target_language == "fr"
            assert loaded.extraction_chunk_chars == 12000
            assert loaded.narrative_max_calls == 6


def test_gateway_does_not_multiply_client_retry_attempts():
    gateway_config = Path(__file__).resolve().parents[2] / 'litellm' / 'config.yaml'
    assert yaml.safe_load(gateway_config.read_text())['litellm_settings']['num_retries'] == 0
