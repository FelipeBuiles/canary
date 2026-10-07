"""Evidence that the suite's speed tools retain isolation and useful identities."""

import os
from pathlib import Path
import subprocess
import sys
import threading
from types import SimpleNamespace

import pytest

from scripts.audit_backend_tests import format_report, inventory, timings
from tests import browser_support


@pytest.mark.parametrize("workers", [0, 2])
def test_backend_runner_hides_checkout_build_in_every_process_but_keeps_fixture_builds(tmp_path, workers):
    root = Path(__file__).resolve().parents[2]
    # Simulate an existing ignored build without creating or changing repo files.
    (tmp_path / "conftest.py").write_text(f'''
from pathlib import Path
import sys
sys.path.insert(0, {str(root / "novel_to_comic")!r})
from tests.conftest import pytest_addoption, pytest_configure
dist = Path({str(root / "web" / "dist")!r})
original_is_dir = Path.is_dir
Path.is_dir = lambda path: path == dist or original_is_dir(path)
''')
    probe = tmp_path / "test_source_checkout.py"
    probe.write_text(f'''
from pathlib import Path
import pytest
from starlette.routing import Mount
from novel_to_comic.server.app import create_app

@pytest.mark.parametrize("case", range(4))
def test_routes_ignore_local_build(tmp_path, case):
    assert not Path({str(root / "web" / "dist")!r}).is_dir()
    fixture_dist = tmp_path / "web" / "dist"
    fixture_dist.mkdir(parents=True)
    assert fixture_dist.is_dir()
    app = create_app(tmp_path, dev=False)
    assert not any(isinstance(route, Mount) and route.name == "frontend" for route in app.routes)
''')
    env = {key: value for key, value in os.environ.items() if not key.startswith("PYTEST_XDIST_")}
    result = subprocess.run(
        [sys.executable, str(root / "scripts/run_backend_checks.py"),
         str(probe), "--rootdir", str(tmp_path), "-q", "-n", str(workers)],
        cwd=root, env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "4 passed" in result.stdout


def test_inventory_compares_bodies_without_erasing_cases_or_fixtures(tmp_path):
    (tmp_path / "test_sample.py").write_text('''
def test_original(book):
    """The original contract."""
    assert book.value == 1
def test_duplicate(book):
    assert book.value == 1
def test_other_fixture(other_book):
    assert other_book.value == 1
class TestValues:
    def test_other_value(self, book):
        assert book.value == 2
def helper():
    def test_not_collected():
        assert False
''')
    result = inventory(tmp_path)
    assert (result["modules"], result["functions"]) == (1, 4)
    assert [[item["test"] for item in group] for group in result["duplicate_candidates"]] == [
        ["test_sample.py::test_original", "test_sample.py::test_duplicate"],
    ]


def test_junit_groups_parameters_and_keeps_setup_failures_and_skips(tmp_path):
    first, second = tmp_path / "first.xml", tmp_path / "second.xml"
    first.write_text('''<testsuites><testsuite time="9">
      <testcase file="tests/test_a.py" classname="tests.test_a" name="test_value[a]" time="2"/>
      <testcase file="tests/test_a.py" classname="tests.test_a" name="test_value[b]" time="3"><failure/></testcase>
      <testcase file="tests/test_a.py" classname="tests.test_a" name="test_skip" time="0"><skipped/></testcase>
    </testsuite></testsuites>''')
    second.write_text('''<testsuite time="4">
      <testcase classname="novel_to_comic.tests.test_b.TestAPI" name="test_auth" time="1"><error/></testcase>
    </testsuite>''')
    result = timings([first, second])
    assert result["suite_seconds"] == 13
    assert result["outcomes"] == {"passed": 1, "failure": 1, "skipped": 1, "error": 1}
    assert result["functions"][0] == {
        "test": "test_a.py::test_value", "cases": 2, "seconds": 5,
        "max_seconds": 3, "skipped": 0, "failed": 1,
    }
    assert result["functions"][1]["test"] == "test_b.py::TestAPI::test_auth"
    assert not result["repeated_cases"]
    overlapping = tmp_path / "overlapping.xml"
    overlapping.write_text(first.read_text().replace("tests/test_a.py", "novel_to_comic/tests/test_a.py")
                           .replace('classname="tests.test_a"', 'classname="novel_to_comic.tests.test_a"'))
    repeated = timings([first, overlapping])["repeated_cases"]
    assert len(repeated) == 3
    assert repeated[0]["test"] == "test_a.py::test_value[a]"
    assert repeated[0]["reports"] == [str(first), str(overlapping)]
    assert "not parallel wall time" in format_report({**inventory(tmp_path), "timings": result})


@pytest.mark.parametrize("workers", [1, 2])
def test_browser_reuse_closes_contexts_on_failure_and_resources_on_owning_threads(monkeypatch, workers):
    events = []

    class Resource:
        def __init__(self, kind):
            self.kind, self.owner = kind, threading.get_ident()
            events.append(("create", self.kind, self.owner))

        def close(self):
            assert threading.get_ident() == self.owner
            events.append(("close", self.kind, self.owner))

    class Browser(Resource):
        def new_context(self, **options):
            context = Resource("context")
            context.new_page = lambda: options
            return context

    def start():
        manager = Resource("playwright")
        manager.stop = manager.close
        manager.chromium = SimpleNamespace(launch=lambda: Browser("browser"))
        return manager

    monkeypatch.setattr(browser_support, "sync_playwright", lambda: SimpleNamespace(start=start))
    browsers = browser_support.LetteringBrowsers(workers=workers)
    barrier = threading.Barrier(workers)

    def call(fail=False, rendezvous=False):
        with browsers.playwright() as playwright:
            if rendezvous:
                barrier.wait(timeout=5)
            browser = playwright.chromium.launch()
            assert browser.new_page(viewport={"width": 100}) == {"viewport": {"width": 100}}
            if fail:
                raise ValueError("failed layout")
            browser.close()

    try:
        futures = [browsers.pool.submit(call, rendezvous=True) for _ in range(workers)]
        for future in futures:
            future.result(timeout=5)
        with pytest.raises(ValueError, match="failed layout"):
            browsers.pool.submit(call, True).result(timeout=5)
        browsers.pool.submit(call).result(timeout=5)
    finally:
        browsers.close()
    created = [kind for action, kind, _ in events if action == "create"]
    closed = [kind for action, kind, _ in events if action == "close"]
    assert created.count("browser") == closed.count("browser") == workers
    assert created.count("context") == closed.count("context") == workers + 2
    assert closed.count("playwright") == workers


def test_real_browser_reuse_does_not_keep_dom_or_cookies_between_calls():
    browsers = browser_support.LetteringBrowsers(workers=1)

    def call(seed=False):
        with browsers.playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            assert page.evaluate("window.previousTest") is None
            assert browser.context.cookies() == []
            if seed:
                page.evaluate("window.previousTest = 'private page'")
                browser.context.add_cookies([{
                    "name": "private", "value": "previous-test", "domain": "example.test", "path": "/",
                }])
                raise ValueError("failed render")
            browser.close()

    try:
        with pytest.raises(ValueError, match="failed render"):
            browsers.pool.submit(call, True).result(timeout=15)
        browsers.pool.submit(call).result(timeout=15)
    finally:
        browsers.close()
