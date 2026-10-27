"""Provider-free wire fingerprints captured before the text route split."""
import hashlib
import json
from pathlib import Path

import pytest

from novel_to_comic.ai.text_requests import build_text_request
from novel_to_comic.config import Config
from novel_to_comic.text_models import TEXT_MODELS, text_wire


@pytest.mark.parametrize("model", [model.id for model in TEXT_MODELS])
@pytest.mark.parametrize("structured", [False, True])
@pytest.mark.parametrize("vision", [False, True])
def test_provider_payload_matches_pre_split_fingerprint(model, structured, vision):
    if vision and not text_wire(model).vision:
        with pytest.raises(ValueError, match="Vision is not enabled"):
            build_text_request(
                config=Config(), model=model, system_prompt="s", user_content="u", temperature=.3,
                max_output_tokens=2048, json_mode=True, feature="adapt.book",
                image_attachments=((b"image", "image/png"),), metadata={},
            )
        return
    schema = {"title": "WireProof", "type": "object", "properties": {"value": {"type": "string"}}, "required": ["value"]}
    request = build_text_request(
        config=Config(), model=model, system_prompt="Read carefully.", user_content="The story.",
        temperature=.3, max_output_tokens=2048, json_mode=True, feature="adapt.book",
        json_schema=schema if structured else None,
        image_attachments=((b"image", "image/png"),) if vision else (), metadata={},
    )
    payload = {k: v for k, v in request.payload.items() if k != "metadata"}
    expected = json.loads((Path(__file__).parent / "fixtures/text_request_fingerprints.json").read_text())
    assert hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest() == expected[f"{model}:{structured}:{vision}"]
