"""Provider-free test isolation and shared, real Chromium processes."""
from pathlib import Path

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--hide-web-dist", action="store_true",
        help="Ignore the checkout's frontend build, matching source-only CI.",
    )
    parser.addoption(
        "--fresh-lettering-browser", action="store_true",
        help="Launch Chromium for every lettering operation, as production does.",
    )


def pytest_configure(config):
    if not config.getoption("--hide-web-dist"):
        return
    dist = Path(__file__).resolve().parents[2] / "web" / "dist"
    original_is_dir = Path.is_dir
    patch = pytest.MonkeyPatch()
    patch.setattr(Path, "is_dir", lambda path: path != dist and original_is_dir(path))
    config.add_cleanup(patch.undo)


@pytest.fixture(scope="session", autouse=True)
def lettering_browsers(request):
    if request.config.getoption("--fresh-lettering-browser"):
        yield
        return
    from novel_to_comic.lettering import renderer
    from .browser_support import LetteringBrowsers

    browsers = LetteringBrowsers()
    try:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(renderer, "_POOL", browsers.pool)
            patch.setattr(renderer, "sync_playwright", browsers.playwright)
            yield
    finally:
        browsers.close()


@pytest.fixture(autouse=True)
def isolated_ai_admission(monkeypatch):
    from novel_to_comic.ai import admission
    monkeypatch.setattr(admission, "_controller", admission.new_controller())


@pytest.fixture(autouse=True)
def isolated_runtime_settings():
    """Settings come from the environment alone unless a test supplies stored values."""
    from novel_to_comic import runtime_settings
    runtime_settings.use_loader(lambda: None)
    yield
    runtime_settings.use_loader(lambda: None)
