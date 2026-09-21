"""Creation choices must bind generation, costs, and editability consistently."""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from novel_to_comic.config import Config, load_config, save_config, COMPLETE_PAGE_GATEWAY_MODEL
from novel_to_comic.models.draw import RetryProvenance
from novel_to_comic.page_drawing import (
    compile_page_generation_request, complete_page_adapter,
    current_page_capability_profile, ensure_current_page_edition,
    select_book_edition,
)
from novel_to_comic.server.routers.config import update_config
from novel_to_comic.server.routers.lettering import _require_editable_style
from novel_to_comic.lettering.service import LetteringConflict
from novel_to_comic.target_artifacts import TargetArtifacts
from .test_complete_page_draw import _page, _inventory, _reference_files


@pytest.mark.parametrize('model', [COMPLETE_PAGE_GATEWAY_MODEL, 'image-sunburst', 'image-flare', 'image-muse'])
def test_each_mode_binds_same_model_and_prices_but_distinct_frozen_requests(tmp_path, model):
    editable = Config(draw_model=model, lettering_mode='editable')
    integrated = Config(draw_model=model, lettering_mode='integrated')
    ep = current_page_capability_profile(editable)
    ip = current_page_capability_profile(integrated)
    assert ep.model == ip.model
    assert ep.price_per_page_usd == ip.price_per_page_usd
    assert ep.max_image_references == ip.max_image_references
    assert ep.output_width == ip.output_width
    assert not ep.exact_visible_lettering and ip.exact_visible_lettering
    assert ep.id != ip.id
    requests = []
    for config, profile in [(editable, ep), (integrated, ip)]:
        edition = select_book_edition(edition_id='test', profile=profile)
        compiled = compile_page_generation_request(
            _page(), edition, _inventory(), _reference_files(tmp_path),
            style_template='Ink drawing.\n\nPOST-PRODUCTION LETTERING DESIGN — software-only-sentinel',
            retry=RetryProvenance(attempt=1),
        )
        requests.append(compiled.request)
        assert 'software-only-sentinel' not in compiled.request.prompt
        prepared = complete_page_adapter(config).prepare(compiled)
        assert prepared.request_sha256 == compiled.request.request_sha256
        ensure_current_page_edition(TargetArtifacts(tmp_path), edition, config)
        with pytest.raises(ValueError, match='different page profile'):
            ensure_current_page_edition(TargetArtifacts(tmp_path), edition, integrated if config is editable else editable)
    assert requests[0].request_sha256 != requests[1].request_sha256
    text = _page().content[0].lettering[0].text
    assert text not in requests[0].prompt
    assert text in requests[1].prompt


@pytest.mark.parametrize('mode', ['integrated', 'editable'])
def test_mode_round_trips_and_cannot_be_switched_through_settings(tmp_path, mode):
    config = Config(lettering_mode=mode)
    save_config(config, tmp_path)
    assert load_config(tmp_path)[0].lettering_mode == mode
    with pytest.raises(HTTPException) as error:
        update_config({'lettering_mode': 'editable' if mode == 'integrated' else 'integrated'}, MagicMock(), (tmp_path, config, MagicMock()), 'user')
    assert error.value.status_code == 409
    assert load_config(tmp_path)[0].lettering_mode == mode
    if mode == 'integrated':
        with pytest.raises(LetteringConflict, match='integrated lettering'):
            _require_editable_style(TargetArtifacts(tmp_path))
    else:
        _require_editable_style(TargetArtifacts(tmp_path))


def test_invalid_mode_is_rejected():
    with pytest.raises(ValidationError):
        Config(lettering_mode='automatic-conversion')


def test_retained_integrated_edition_controls_presentation_not_default_config(tmp_path):
    from novel_to_comic.models.draw import BookEdition
    from novel_to_comic.page_drawing import production_page_capability_profile
    from novel_to_comic.server.routers.config import get_config
    from novel_to_comic.config import COMPLETE_PAGE_PROFILE_ID

    retained = production_page_capability_profile().model_copy(update={
        'id': COMPLETE_PAGE_PROFILE_ID, 'exact_visible_lettering': True,
    })
    edition = BookEdition(revision=1, id='retained', capability_profile=retained)
    artifacts = TargetArtifacts(tmp_path)
    artifacts.write_book_edition(edition)
    assert get_config((tmp_path, Config(), None))['lettering_mode'] == 'integrated'
    # Presentation does not silently reauthorize old editions for generation.
    with pytest.raises(ValueError, match='different page profile'):
        ensure_current_page_edition(artifacts, edition, Config(lettering_mode='integrated'))


def test_config_does_not_commit_if_edition_is_invalid(tmp_path):
    from novel_to_comic.target_artifacts import ArtifactInvalid

    config = Config()
    save_config(config, tmp_path)
    before = (tmp_path / 'config.yaml').read_bytes()
    path = TargetArtifacts(tmp_path).book_edition_path
    path.parent.mkdir(parents=True)
    path.write_text('{}')
    with pytest.raises(ArtifactInvalid):
        update_config({'target_language': 'es'}, MagicMock(), (tmp_path, config, None), 'user')
    assert (tmp_path / 'config.yaml').read_bytes() == before
