"""Reuse Chromium processes in tests, with a new context for every renderer call.

The production renderer still executes its real fonts, layout and screenshots.
Playwright objects stay on their owning executor thread; only the expensive
process lifetime differs from production. No page or context is shared.
"""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import logging
from threading import Barrier, current_thread, local
from types import SimpleNamespace

from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)


@contextmanager
def _browser_step(name):
    # Captured logs identify the last unfinished operation on each owning thread.
    name = f"{current_thread().name}: {name}"
    logger.debug("%s: starting", name)
    try:
        yield
    except BaseException:
        logger.exception("%s: failed", name)
        raise
    else:
        logger.debug("%s: finished", name)


class _ContextBrowser:
    def __init__(self, browser):
        self.browser = browser
        self.context = None

    def new_page(self, **options):
        with _browser_step("context creation"):
            self.context = self.browser.new_context(**options)
        with _browser_step("page creation"):
            return self.context.new_page()

    def close(self):
        if self.context is not None:
            with _browser_step("context cleanup"):
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
            with _browser_step("Playwright startup"):
                playwright = sync_playwright().start()
            try:
                with _browser_step("Chromium launch"):
                    browser = playwright.chromium.launch()
            except BaseException:
                with _browser_step("Playwright startup cleanup"):
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
        with _browser_step("worker shutdown rendezvous"):
            barrier.wait(timeout=10)
        if hasattr(self._local, "browser"):
            try:
                with _browser_step("Chromium shutdown"):
                    self._local.browser.close()
            finally:
                with _browser_step("Playwright shutdown"):
                    self._local.playwright.stop()

    def close(self):
        barrier = Barrier(self.workers)
        futures = [self.pool.submit(self._close_worker, barrier) for _ in range(self.workers)]
        try:
            for future in futures:
                future.result(timeout=30)
        finally:
            self.pool.shutdown(wait=True)
