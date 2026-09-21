"""Small selected-proof fixture for provider-free project tests."""

import json

from PIL import Image

from novel_to_comic.config import Config


def write_style_proof(project_dir, style_template=None):
    samples = project_dir / "samples"
    samples.mkdir(parents=True, exist_ok=True)
    (samples / "style_suggestions.json").write_text(json.dumps({
        "suggestions": [{"template": Config().style_template if style_template is None else style_template}],
    }))
    proof = samples / "style_1.png"
    Image.new("RGB", (32, 40), "orange").save(proof)
    return proof
