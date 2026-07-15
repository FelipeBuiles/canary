import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[2]))

from litellm_handlers.fal_provider import _fal_endpoint


def test_bytedance_partner_endpoint_keeps_provider_namespace() -> None:
    assert _fal_endpoint("bytedance/seedream/v5/pro/edit") == (
        "bytedance/seedream/v5/pro/edit"
    )


def test_fal_owned_endpoint_gets_fal_namespace() -> None:
    assert _fal_endpoint("flux-2-pro/edit") == "fal-ai/flux-2-pro/edit"
