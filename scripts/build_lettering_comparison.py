"""Rebuild curated comparison composites with the production lettering renderer.

No provider calls and no project writes. See docs/reference/lettering-comparison.md.
Run with novel_to_comic/.venv/bin/python scripts/build_lettering_comparison.py.
"""
from pathlib import Path

from novel_to_comic.lettering.renderer import render_lettered_page, resolve_lettering
from novel_to_comic.models.lettering import LetteringStyle, PageLettering

ROOT = Path(__file__).resolve().parents[1] / "web/public/lettering-comparison"


def main():
    from PIL import Image
    import io

    specimens = (
        ("cthulhu-26", "style.json", ("source", "es")),
        ("cthulhu-25", "style.json", ("source",)),
        ("dcc-3", "dcc-3-style.json", ("source",)),
    )
    for specimen, style_file, locales in specimens:
        style = LetteringStyle.model_validate_json((ROOT / style_file).read_text())
        state = PageLettering.model_validate_json((ROOT / f"{specimen}.json").read_text())
        # The production compositor accepts decoded image data; use PNG here to
        # preserve its base-art media contract while storing compact WebP assets.
        base = io.BytesIO()
        Image.open(ROOT / f"{specimen}-base.webp").save(base, format="PNG")
        for locale in locales:
            resolved = resolve_lettering(state.model_copy(update={"locale": locale}), style)
            png = render_lettered_page(resolved, style, base.getvalue(), 1024, 1536)
            suffix = "editable" if locale == "source" else "editable-es"
            Image.open(io.BytesIO(png)).save(ROOT / f"{specimen}-{suffix}.webp", format="WEBP", quality=92, method=6)
            print(f"{specimen}, {locale}: {len(resolved.elements)} elements, validated fit and glyphs")


if __name__ == "__main__":
    main()
