"""Provider-free test isolation and shared, real Chromium processes."""
import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--fresh-lettering-browser", action="store_true",
        help="Launch Chromium for every lettering operation, as production does.",
    )


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
