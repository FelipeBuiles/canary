"""Reuse Chromium processes in tests, with a new context for every renderer call.

The production renderer still executes its real fonts, layout and screenshots.
Playwright objects stay on their owning executor thread; only the expensive
process lifetime differs from production. No page or context is shared.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier, local
from types import SimpleNamespace

from playwright.sync_api import sync_playwright


class _ContextBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.context = None

    def new_page(self, **options):
        self.context = self.browser.new_context(**options)
        return self.context.new_page()

    def close(self):
        if self.context is not None:
            self.context.close()
            self.context = None


class LetteringBrowsers:
    def __init__(self, workers=2):
        self.workers = workers
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="test-lettering")
        self._local = local()

    @contextmanager
    def playwright(self):
        if not hasattr(self._local, "browser"):
            playwright = sync_playwright().start()
            try:
                browser = playwright.chromium.launch()
            except BaseException:
                playwright.stop()
                raise
            self._local.playwright = playwright
            self._local.browser = browser
        isolated = _ContextBrowser(self._local.browser)
        try:
            yield SimpleNamespace(chromium=SimpleNamespace(launch=lambda: isolated))
        finally:
            # Also close the context when a call fails before browser.close().
            isolated.close()

    def _close_worker(self, barrier):
        # Occupy both executor threads so each closes its own Playwright objects.
        barrier.wait(timeout=10)
        if hasattr(self._local, "browser"):
            try:
                self._local.browser.close()
            finally:
                self._local.playwright.stop()

    def close(self):
        barrier = Barrier(self.workers)
        futures = [self.pool.submit(self._close_worker, barrier) for _ in range(self.workers)]
        try:
            for future in futures:
                future.result(timeout=30)
        finally:
            self.pool.shutdown(wait=True)
