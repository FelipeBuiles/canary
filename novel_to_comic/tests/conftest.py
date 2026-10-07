"""Keep provider admission history independent between provider-free tests."""
import pytest


@pytest.fixture(autouse=True)
def isolated_ai_admission(monkeypatch):
    from novel_to_comic.ai import admission
    monkeypatch.setattr(admission, "_controller", admission.new_controller())
