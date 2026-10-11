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


def write_location_style_board(config, project_dir):
    """A current board made from the selected proof, as a Cast run leaves it."""
    from novel_to_comic.asset_generation import persist_non_panel_provenance
    from novel_to_comic.stages import s3_cast
    from novel_to_comic.usage import ApiResult, UsageRecord

    proof = s3_cast._cast_asset_style_ref(config, s3_cast._find_style_ref(project_dir, config.style_template))
    board = s3_cast._location_style_board_path(project_dir)
    board.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 27), "gray").save(board)
    persist_non_panel_provenance(
        request=s3_cast._location_style_board_request(config, project_dir, proof), output_path=board,
        project_dir=project_dir, request_id="board",
        result=ApiResult(value=board, usage=UsageRecord(provider="test", model="test", operation="image")),
    )
    assert s3_cast._location_style_board(config, project_dir) == board
    return board
