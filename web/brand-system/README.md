# Scenewright Panel Frame S

This package generates the complete Panel Frame S identity from one TypeScript geometry source. The AI-generated references are retained only for side-by-side visual direction; none of their pixels appear in an output asset.

## Commands

Run from `web/`:

```sh
npm run brand:build
npm run brand:check
npm run brand:preview
```

The build writes SVG, PNG, ICO, and contact-sheet outputs to `web/public/brand/scenewright-panel-frame/`. It also publishes the approved favicon set and Apple touch icon to `web/public/`, where the product consumes them. The preview opens at `/brand-system/preview/` on the local Vite server.

## Source hierarchy

- `src/geometry.ts` — canonical palette, 100-unit geometry, micro geometry, and reusable SVG primitives.
- `src/build.ts` — deterministic asset, favicon, icon, and contact-sheet generation.
- `src/validate.ts` — output, SVG safety, dimensions, palette, ICO contents, and consecutive-build determinism checks.
- `preview/` — editable live-text identity specimen and debug view.
- `references/` — source concept images labeled `REFERENCE ONLY` in the specimen.

## Typography status

No locally licensed Anybody font file was found. The symbol system is production-ready, but the wordmark and lockups are marked `live-text-provisional` and intentionally isolated for replacement. The local specimen uses the same hosted Anybody family as the current application title typography; its offline fallback is a generic sans-serif. Supply a licensed Anybody font and convert the final wordmark to paths before print production.

Do not use the production wordmark SVG as proof of final letter spacing until that outlined pass is complete.
