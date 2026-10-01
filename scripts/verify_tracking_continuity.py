"""Real installed Chromium, synthetic fixtures, all external requests blocked.

Checks attribution through reload/new-tab/OAuth URL construction and actual
artwork load/error callbacks. This does not prove production signup/payment,
provider quality, or real user acceptance. Own loopback Vite is always stopped.
"""
import json
import os
import subprocess
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "http://127.0.0.1:18766"
env = {k: v for k, v in os.environ.items() if not any(s in k for s in ("POSTHOG", "STRIPE", "SUPABASE", "OPENAI", "LITELLM"))}
env.update(VITE_SUPABASE_URL=ORIGIN, VITE_SUPABASE_PUBLISHABLE_KEY="fixture-only")
checks = []
with open("/tmp/canary-tracking-browser-vite.log", "w") as log:
    server = subprocess.Popen(["node", "node_modules/vite/bin/vite.js", "--host", "127.0.0.1", "--port", "18766", "--strictPort"], cwd=ROOT / "web", env=env, stdout=log, stderr=log)
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Fixture server failed; inspect local log")
            try:
                if httpx.get(ORIGIN, trust_env=False).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(.1)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context()
                def intercept(route):
                    request = route.request
                    if urlsplit(request.url).netloc != "127.0.0.1:18766":
                        route.abort()
                    elif "/auth/v1/" in request.url or "/api/" in request.url:
                        route.fulfill(status=200, content_type="application/json", body="{}")
                    elif "/synthetic-art.png" in request.url:
                        route.fulfill(status=200, content_type="image/png", path=str(ROOT / "web/public/favicon.png"))
                    elif "/failed-art.png" in request.url:
                        route.fulfill(status=500, body="fixture failure")
                    else:
                        route.continue_()
                context.route("**/*", intercept)
                page = context.new_page()
                page.goto(ORIGIN + "/login?utm_source=reddit&utm_campaign=controlled&token=SYNTHETIC_SECRET")
                acquisition = "async () => (await import('/src/telemetry.ts')).getAcquisition()"
                assert page.evaluate(acquisition) == {"source": "reddit", "campaign": "controlled"}
                checks.append("initial bounded attribution")
                page.goto(ORIGIN + "/signup")
                assert page.evaluate(acquisition) == {"source": "reddit", "campaign": "controlled"}
                page.reload()
                assert page.evaluate(acquisition) == {"source": "reddit", "campaign": "controlled"}
                checks.append("navigation and reload continuity")
                tab = context.new_page()
                tab.goto(ORIGIN + "/login")
                assert tab.evaluate(acquisition) == {"source": "reddit", "campaign": "controlled"}
                checks.append("new-tab continuity")
                callback = tab.evaluate("""async () => {
                  const auth=await import('/src/lib/authContext.ts'); const telemetry=await import('/src/telemetry.ts');
                  return auth.authCallbackUrl(new URLSearchParams('token=SYNTHETIC_SECRET'), telemetry.getAcquisition());
                }""")
                assert "source=reddit" in callback and "campaign=controlled" in callback and "SYNTHETIC_SECRET" not in callback
                checks.append("bounded OAuth callback attribution")
                assert "SYNTHETIC_SECRET" not in tab.evaluate("JSON.stringify(localStorage)")
                checks.append("no secrets or persisted PostHog identity")
                # Render the actual component in Chromium, without customer APIs.
                tab.evaluate("""async () => {
                  const reactModule = await import('/node_modules/.vite/deps/react.js'); const React=reactModule.default ?? reactModule;
                  const clientModule=await import('/node_modules/.vite/deps/react-dom_client.js'); const createRoot=clientModule.createRoot ?? clientModule.default.createRoot;
                  const {I18nProvider}=await import('/src/i18n.tsx');
                  const {PageArtwork}=await import('/src/components/pages/PageArtwork.tsx');
                  const mount=document.createElement('div'); document.body.append(mount);
                  window.loadedArtwork=0; window.artRoot=createRoot(mount);
                  window.showArtwork=src=>window.artRoot.render(React.createElement(I18nProvider, null,
                    React.createElement(PageArtwork, {src, alt:'Synthetic fixture artwork', onLoaded:()=>window.loadedArtwork++})));
                  window.showArtwork('/failed-art.png');
                }""")
                tab.get_by_role("alert").filter(has_text="The page image could not be loaded.").wait_for()
                assert tab.evaluate("window.loadedArtwork") == 0
                checks.append("failed artwork emits no loaded milestone")
                # A generated fixture SVG is local synthetic content only.
                context.route("**/synthetic-art.png", lambda route: route.fulfill(status=200, content_type="image/svg+xml", body='<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"><rect width="4" height="4"/></svg>'))
                tab.evaluate("window.showArtwork('/synthetic-art.png')")
                tab.wait_for_function("window.loadedArtwork === 1")
                checks.append("actual Chromium image load callback")
                print(json.dumps({"passed": checks, "browser": browser.version, "external_requests": "blocked", "production_writes": 0}))
            finally:
                browser.close()
    finally:
        server.terminate()
        server.wait(timeout=10)
