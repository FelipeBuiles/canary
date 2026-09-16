"""Execute the browser's exact layout/SVG implementation in isolated Chromium."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path

from playwright.sync_api import Error as PlaywrightError, sync_playwright

from novel_to_comic.models.lettering import LetteringStyle, PageLettering

ENGINE_VERSION = "lettering-svg-v3"
_ROOT = Path(__file__).parent
_FONT_ROOT = _ROOT.parent / "fonts"
# Every call runs outside any caller's asyncio loop. Each isolated browser is
# closed even on failure; no project content survives in a shared browser page.
_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="canary-lettering")


@lru_cache(maxsize=1)
def _source() -> str:
    # The server executes the same local module and coverage table as Vite,
    # inlined because its isolated browser deliberately disallows all requests.
    engine = (_ROOT / "engine.mjs").read_text().replace(
        'import { FONT_COVERAGE } from "./font-coverage.mjs";', ""
    )
    return (_ROOT / "font-coverage.mjs").read_text() + "\n" + engine


@lru_cache(maxsize=1)
def _fonts() -> str:
    # These names are application constants, never user-supplied filesystem paths.
    files = {
        "Comic Neue": "ComicNeue-Bold.ttf",
        "EB Garamond": "EBGaramond-SemiBold.ttf",
        "Bangers": "Bangers-Regular.ttf",
        "Special Elite": "SpecialElite-Regular.ttf",
        "M PLUS 1p": "MPLUS1p-Bold.ttf",
        "Fredoka": "Fredoka-SemiBold.ttf",
        "Orbitron": "Orbitron-Bold.ttf",
        "Bungee": "Bungee-Regular.ttf",
    }
    return "\n".join(
        f'@font-face{{font-family:"{name}";src:url(data:font/ttf;base64,'
        f'{base64.b64encode((_FONT_ROOT / filename).read_bytes()).decode()}) format("truetype");}}'
        for name, filename in files.items()
    )


def _browser_call(
    operation: str,
    state: dict,
    style: dict,
    image: bytes | None,
    width: int,
    height: int,
) -> dict | bytes:
    try:
        return _isolated_browser_call(operation, state, style, image, width, height)
    except PlaywrightError as exc:
        raise ValueError(
            "Lettering renderer is unavailable. Install the pinned Playwright Chromium and retry; no artwork regeneration is required."
        ) from exc


def _isolated_browser_call(
    operation: str,
    state: dict,
    style: dict,
    image: bytes | None,
    width: int,
    height: int,
) -> dict | bytes:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            page = browser.new_page(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            # All fonts and pixels are inline. No URL from text/state can fetch
            # anything, and incidental SVG/image requests cannot leave Chromium.
            page.route("**/*", lambda route: route.abort())
            page.set_content(
                '<!doctype html><meta charset="utf-8"><style>'
                + _fonts()
                + "</style><style>html,body{margin:0;padding:0;overflow:hidden} "
                "#art,#overlay{position:absolute;inset:0;width:100%;height:100%}</style>"
                '<img id="art" alt=""><div id="overlay"></div>'
            )
            page.add_script_tag(
                type="module",
                content=_source()
                + "\nwindow.lettering={resolvePage,renderOverlay,canvasMeasure,loadFonts};",
            )
            page.wait_for_function("window.lettering")
            page.evaluate("async () => await window.lettering.loadFonts()")
            args = {"state": state, "style": style}
            if operation == "resolve":
                return page.evaluate(
                    "({state,style}) => window.lettering.resolvePage(state,style,window.lettering.canvasMeasure())",
                    args,
                )
            if image is None:
                raise ValueError("composition requires base art")
            page.evaluate(
                "async src => { const image=document.getElementById('art'); image.src=src; await image.decode(); }",
                "data:image/png;base64," + base64.b64encode(image).decode(),
            )
            page.evaluate(
                "({state,style}) => {document.getElementById('overlay').innerHTML=window.lettering.renderOverlay(state,style)}",
                args,
            )
            return page.screenshot(type="png", animations="disabled")
        finally:
            browser.close()


def resolve_lettering(state: PageLettering, style: LetteringStyle) -> PageLettering:
    value = _POOL.submit(
        _browser_call,
        "resolve",
        state.model_dump(mode="json"),
        style.model_dump(mode="json"),
        None,
        1000,
        1500,
    ).result()
    value["content_sha256"] = ""
    value["style_sha256"] = style.content_sha256
    return PageLettering.model_validate(value)


def render_lettered_page(
    state: PageLettering, style: LetteringStyle, image: bytes, width: int, height: int
) -> bytes:
    if state.style_sha256 != style.content_sha256:
        raise ValueError(
            "Lettering style changed. Open Lettering and save the reflowed page."
        )
    if abs(state.canvas_aspect_ratio - width / height) > 1e-8:
        raise ValueError(
            "Artwork proportions changed. Open Lettering and save its new layout."
        )
    for element in state.elements:
        if element.hidden:
            continue
        resolved = element.resolved
        if resolved is None or resolved.engine_version != ENGINE_VERSION:
            raise ValueError(
                "Lettering needs layout. Open Lettering and save the page."
            )
        if resolved.warnings:
            raise ValueError(
                f"Lettering {element.id} needs attention ({', '.join(resolved.warnings)}). Open Lettering to complete its copy or select a supported font."
            )
        if resolved.overflow:
            raise ValueError(
                f"Lettering {element.id} does not fit. Widen its box or shorten its copy in Lettering."
            )
        if (
            resolved.locale != state.locale
            or resolved.text
            != element.text_by_locale.get(
                state.locale, element.text_by_locale["source"]
            )
        ):
            raise ValueError(
                "Lettering copy changed without a resolved layout. Save it in Lettering."
            )
    return _POOL.submit(
        _browser_call,
        "render",
        state.model_dump(mode="json"),
        style.model_dump(mode="json"),
        image,
        width,
        height,
    ).result()
