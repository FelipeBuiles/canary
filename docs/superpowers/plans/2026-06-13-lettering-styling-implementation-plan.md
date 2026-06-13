# Comic Lettering & Styling Implementation Plan

## Status

Complete (2026-06-13) — all ten slices shipped. 448 backend + 199 web tests
green, `ruff check src/` clean, production build clean. Spec:
`docs/superpowers/specs/2026-06-13-lettering-styling-design.md`.

Deviation from spec: the Book one-time reveal "seen" flag is stored in
localStorage (per-device) rather than server-side project state.

## Goal

Make comic styling automatic and unified behind one project-level
`LetteringStyle` (Approach A), with a live preview at Look, a one-time reveal at
Book, AI typeface selection from curated OFL pairs, and surface polish.
Forward-looking only — old fields/endpoints are removed, not migrated.

## Success Criteria

- Selecting a style at Look generates a `LetteringStyle` with a real rationale and
  a live preview; no manual button hunt.
- Look preview and rendered Book pages are identical (same project object).
- Noir vs manga render in visibly different fonts.
- One-time Book reveal; the `MATCH LETTERING` dropdown item is gone.
- Restyle preserves per-bubble manual edits.
- Thought bubbles render as scallops in canvas and PDF.
- `theme_tokens.json` is the single definition of base vars, themes, font pairs.
- `uv run pytest` and `npm test` green; app verified in preview.

## Implementation Sequence

### Slice 1: Single-source theme tokens

- Create `novel_to_comic/src/novel_to_comic/assembly/theme_tokens.json` holding
  `base` (the current `_BASE_VARS`), `themes` (the 5), and `font_pairs` (6 ids →
  `--letter-font`/`--display-font`).
- Replace `_BASE_VARS`/`THEMES` literals in `html_renderer.py` with a loader over
  the JSON; add `FONT_PAIRS`.
- Verify: `uv run pytest tests/` (existing render tests still pass).

### Slice 2: Font assets (curated OFL pairs)

- Acquire OFL/Apache TTFs for the 5 new moods (finalize one display + one body
  family each from the spec's candidates). Bundle into
  `novel_to_comic/src/novel_to_comic/fonts/` and `web/public/static/fonts/`.
- `golden-age` reuses the existing Bangers + Comic Neue.
- If network fetch of fonts is unavailable, wire the full system with
  `golden-age` functional and the other pairs configured, and leave a single
  documented "drop in TTF" step. (Tracked as the one external dependency.)

### Slice 3: `LetteringStyle` model + removals

- Add `LetteringStyle` Pydantic model + `assembly/lettering_style.json`
  load/save helpers (mirror `character_voices`).
- Remove `ComicPage.theme` / `ComicPage.style_vars`; remove `config.comic_theme`.
- Verify: `uv run pytest tests/`.

### Slice 4: AI generation + endpoints

- Extend `_generate_lettering_style` to return/validate `theme` + `font_pair` and
  keep `label`/`rationale`; extend `_fallback_lettering_style` with a font pick.
- Add `style_template_hash` caching + `reroll`.
- Add `GET/POST(generate)/PUT /projects/{p}/lettering-style`; remove `set-theme`
  and per-page `style-vars/generate`. Trigger generation on `setActiveStyle`.
- Verify: backend tests for model, validation, fallback, endpoints.

### Slice 5: Backend render

- `html_renderer` loads the project `LetteringStyle`; `_vars_css(ls.theme,
  FONT_PAIRS[ls.font_pair] | ls.vars)`; remove `resolve_theme`/`detect_theme`.
- Switch hardcoded `font-family` to `var(--letter-font…)`/`var(--display-font…)`;
  add `@font-face` for bundled fonts; `await document.fonts.ready` before
  snapshot. `s8_compose` stops resolving theme.
- Verify: render a sample page to PNG; fonts apply.

### Slice 6: Frontend tokens + render

- `npm run sync-tokens` → `web/src/generated/theme_tokens.json`; parity test;
  wire into `dev`/`build`.
- `themes.ts` loads the JSON; add `FONT_PAIRS`; font vars in `comic-page.css` +
  `@font-face`.
- `useLetteringStyle(project)` query + `api/pages`/`types` updates;
  `ComicPageCanvas` reads the project object; remove page `theme`/`style_vars`.
- Verify: `npm test`.

### Slice 7: Look station UX

- Replace the `<Select>` with the "Page & lettering" section: live mini-preview,
  rationale, "Match my style" default + preset chips + re-roll; loading state.
- Verify in preview: pick a style → preview + rationale appear.

### Slice 8: Book station UX

- One-time reveal (server-side `lettering_reveal_seen` flag); `Lettering: [label]`
  header chip + popover (re-roll / preset / change at Look); remove
  `MATCH LETTERING` from the regenerate menu.
- Verify in preview.

### Slice 9: Polish

- Thought-bubble scallops via CSS `mask` (both renderers); export "Ready to
  print" panel + burst; themeable page texture wash.
- Verify in preview + PDF export.

### Slice 10: Regression + verification

- `uv run pytest tests/`, `npm test`, `ruff check`. Replace fixtures referencing
  removed fields. End-to-end verify in the running app.

## Risk Controls

- Font assets are the one external dependency (Slice 2); the system degrades to
  `golden-age` if a pair's files are missing.
- Token parity test prevents Python/TS drift.
- Per-bubble overrides are independent of `LetteringStyle`, so restyles never
  clobber manual edits.

## Final Verification Checklist

- [ ] Style pick → preview + rationale at Look
- [ ] Look preview matches Book pages
- [ ] Distinct fonts across moods
- [ ] One-time Book reveal; no `MATCH LETTERING` dropdown item
- [ ] Restyle preserves manual bubble edits
- [ ] Scallop thought bubbles in canvas + PDF
- [ ] `theme_tokens.json` single source; parity test green
- [ ] pytest + npm test + ruff green
