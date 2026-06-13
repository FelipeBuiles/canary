# Comic Lettering & Styling Design

## Problem

The visual styling of an assembled comic page — dialogue, narration, thought
bubbles, SFX, panel borders, backgrounds, page paper — is driven by ~30 CSS
custom properties resolved through two independent, overlapping tracks, and the
good one is hidden:

- **Keyword preset (automatic, crude).** `detect_theme()` keyword-matches the
  style template into 5 buckets and runs automatically during compose
  (`s8_compose.py:342`). Surfaced only as a tiny `<Select>` at the bottom of the
  Look room (`StyleRoom.tsx:476`).
- **AI lettering match (manual, smart).** `_generate_lettering_style()`
  (`pages.py:257`) reads the actual style and picks bespoke borders, caption /
  bubble / SFX colors, radii, and padding. It is the real "it thought of
  everything" moment — but it is **never called by the pipeline**, only by a
  button buried two levels deep in the `⟳ REGENERATE ▾` dropdown
  (`ComposeHeader.tsx:58`). The `label` + `rationale` it generates are discarded
  (`pages.py:290`).

The two tracks compute the same variables, don't know about each other, and a
third vestigial path (`set-theme`, `pages.py:630`) sets per-page `cp.theme`
directly. Fonts are fixed (Bangers + Comic Neue) regardless of style: a noir book
and a manga book letter identically. The final Book/Export surfaces are flat.

## Goals

- Make great styling **automatic** for every book — the AI lettering match runs
  without the user hunting for it.
- Preserve and amplify the **wow moment** ("how it thought of everything") by
  surfacing it as a live preview at Look and a one-time reveal at Book.
- Collapse the three overlapping styling mechanisms into **one source of truth**.
- Extend the match to **typeface**, so different styles genuinely feel different.
- Polish the comic surfaces: real thought-bubble scallops, an export ceremony,
  page texture, and a single source for the theme tokens.

## Non-Goals

- No backward compatibility or migration for existing projects. Forward-looking
  changes only — old fields are removed, not tolerated.
- Not redesigning the panel layout algorithm, page geometry, or draw stage.
- Not building a free-form font picker over arbitrary web fonts. The font set is
  a bounded curated list.
- Not changing the credit/billing model beyond folding one small text call into
  the existing style step.

## Decisions (settled during brainstorming)

- **Scope:** all four work items ship in one spec, built together.
- **Where the wow lands:** both — a live preview + rationale at the Look station
  when the style is locked, and a one-time reveal at the Book station on first
  entry. This requires the match to run at style-lock time (before pages exist),
  so the result is stored at project level.
- **Typeface:** a curated set of open-licensed (SIL OFL / Apache) font pairs; the
  AI picks the best-matching pair id.
- **Architecture:** Approach A — one project-level `LetteringStyle` object,
  merged at render time (not baked into page files). Guarantees the Look preview
  and the Book pages read the same object and cannot drift.

## Data Model

### `LetteringStyle` (new, project-level)

Persisted at `projects/<name>/assembly/lettering_style.json` (mirrors the
existing `assembly/character_voices.json` pattern). Pydantic model:

```
LetteringStyle:
  mode:        "auto" | "preset"      # user intent — survives art-style changes
  preset:      str | None             # when mode == "preset" (one of the 5)
  theme:       str                    # resolved base anchor (one of the 5 presets)
  font_pair:   str                    # curated pair id, e.g. "golden-age"
  vars:        dict[str, str]         # sanitized CSS-var overrides
  label:       str                    # "Noir Lettering"
  rationale:   str                    # the wow sentence, surfaced in UI
  source:      "ai" | "fallback" | "preset"
  style_template_hash: str            # staleness key for auto mode
  generated_at: str                   # ISO timestamp
```

### Resolution order (render time), lowest → highest

`BASE_VARS` → `THEMES[theme]` → `FONT_PAIRS[font_pair]` → `LetteringStyle.vars`
→ per-bubble manual overrides.

### Removed (forward-looking, no back-compat)

- `ComicPage.theme` and `ComicPage.style_vars` (`comic_page.py:319-322`) are
  deleted. Per-bubble overrides on `Bubble` remain (top layer).
- `config.comic_theme` is removed; intent now lives in `lettering_style.json`.
- The `set-theme` endpoint (`pages.py:630`) and the per-page
  `style-vars/generate` endpoint (`pages.py:590`) are removed, replaced by the
  lettering-style endpoints below.
- `resolve_theme` / `detect_theme` in `html_renderer.py` are removed; the base
  anchor is chosen once at generation time and stored as `LetteringStyle.theme`.

### Themeable fonts

Two new CSS variables make fonts part of the merged var set:

- `--letter-font` — body lettering (captions, speech, thought bubbles).
- `--display-font` — SFX and speaker labels.

Every hardcoded `font-family` in the comic CSS switches to
`var(--letter-font, 'Comic Neue', …)` / `var(--display-font, 'Bangers', …)`,
keeping today's fonts as the fallback chain. `FONT_PAIRS[id]` provides the two
var values for each pair.

## Generation & the AI Pass

### Trigger

On `setActiveStyle` (selecting a style card at Look). If `mode == "auto"` and
the style template changed (compared via `style_template_hash`), generate a fresh
`LetteringStyle`; otherwise reuse the cached object. Generation is one cheap text
call, so the preview + rationale are ready in the Look room.

### The call

Extends `_generate_lettering_style()` (`pages.py:257`) to also choose `theme` and
`font_pair`:

- System prompt gains the curated pair list (id + one-line mood) and asks for
  `{label, rationale, theme, font_pair, vars}`, JSON only.
- `vars` pass through `STYLE_VAR_ALLOWLIST` + `_sanitize_style_vars` as today.
  `theme` and `font_pair` are validated against the known id sets; an invalid
  value falls back to the keyword pick.
- `label` + `rationale` are **kept** and stored (today discarded at
  `pages.py:290`).

### Modes & regeneration

- `mode="auto"`: AI result. Re-runs only when the style template changes or on an
  explicit re-roll (a fresh take, slightly higher temperature).
- `mode="preset"`: user picked one of the 5 named presets directly; `theme` is
  set to that preset, `vars` come from the preset table plus that preset's default
  font pair; no AI call; `source="preset"`.
- Per-element manual edits live on the `Bubble`, separate from `LetteringStyle`,
  so re-matching or switching style **never destroys manual work**.

### Fallback

`_fallback_lettering_style()` (already keyword-based) is extended to also pick a
fallback `font_pair`. Used on AI failure / offline. `source="fallback"`.

### Endpoints

Replace the removed per-page endpoints with project-level ones:

- `GET  /projects/{p}/lettering-style` → current object (Look preview, canvas,
  Book reveal).
- `POST /projects/{p}/lettering-style/generate` → run/refresh the auto match.
  Body: `{reroll?: bool}`.
- `PUT  /projects/{p}/lettering-style` → set `mode` / `preset` (preset selection
  from the Look UI).

### Billing

Same `ai_request_context` + `debit_model_usage`, under `stage="style"`. One small
text call folded into the style step's estimate.

## Render Pipeline

Both render paths read the one project-level object.

- **Backend** (`html_renderer.py:964`): load `lettering_style.json`; replace
  `_vars_css(cp.theme, cp.style_vars)` with `_vars_css(ls.theme, FONT_PAIRS[ls.font_pair] | ls.vars)`.
  `s8_compose` stops calling `resolve_theme` / `write_theme_css` and reads the
  project object instead.
- **Frontend** (`ComicPageCanvas.tsx:29`): a new `useLetteringStyle(project)`
  query feeds the canvas; merge becomes
  `{ ...resolveThemeVars(ls.theme), ...FONT_PAIRS[ls.font_pair], ...sanitizeStyleVars(ls.vars) }`.
  Page-level `theme` / `style_vars` reads are deleted.

### Single-source tokens

`BASE_VARS` + `THEMES` + the new `FONT_PAIRS` are defined once in canonical
`novel_to_comic/src/novel_to_comic/assembly/theme_tokens.json`. Python loads it
directly. The web build syncs it to `web/src/generated/theme_tokens.json` via an
`npm run sync-tokens` step wired into `dev` and `build`. A parity test asserts the
synced copy matches the canonical file, so `themes.ts` and the Python literals can
never drift. `themes.ts` and the Python `_BASE_VARS` / `THEMES` become thin
loaders over the JSON.

The `sync-tokens` copy (rather than a Vite path-alias import from the Python tree)
keeps each build self-contained for CI/Docker.

### Font bundling

Curated faces are added in both locations the renderers load from:

- `novel_to_comic/src/novel_to_comic/fonts/` → `@font-face` in the backend
  `_STATIC_CSS` (PNG / PDF).
- `web/public/static/fonts/` → `@font-face` in `comic-page.css` (live canvas).

The headless render must `await document.fonts.ready` before snapshotting so a
newly-selected pair never renders in a fallback face; verify and add if missing.

## Curated Font Pairs

Six moods, each a display/SFX face + a body-lettering face, all open-licensed
(SIL OFL or Apache) so they bundle freely and render offline. The `font_pair` id
is what the AI picks and what is stored.

| id | mood | display candidate | body candidate |
|----|------|-------------------|----------------|
| `golden-age` | classic four-color (default, unchanged) | Bangers | Comic Neue |
| `manga` | clean ink, screentone | Bungee / Russo One | M PLUS Rounded 1c / Varela Round |
| `horror` | gritty, dripping | Creepster / Nosifer | Special Elite / Cutive Mono |
| `painterly` | watercolor, literary | Caveat / Shrikhand | EB Garamond / Crimson Text |
| `kids` | rounded, friendly | Fredoka / Baloo 2 | Comic Neue / Quicksand |
| `sci-fi` | technical, angular | Orbitron / Audiowide | Exo 2 / Rajdhani |

The implementation plan finalizes exactly one display + one body family per mood
from these candidates, verifying license and comic-legibility at panel sizes.
Criteria are fixed here; the choice is a plan deliverable, not an open question.

## UX Surfaces

### Look station (`StyleRoom.tsx:476`)

The buried `<Select>` is replaced by a "Page & lettering" section (built from the
`SectionHeader` + `EntityCard` composites, 0px corners per Living Ink) that
appears once a style is active:

- **Live mini-preview**: a small rendered panel showing a caption + speech bubble
  + thought bubble + an SFX in the resolved lettering style (real colors, real
  font pair). While generation runs it shows a "tuning lettering…" state
  (`FlowingDotsPlaceholder`).
- **Rationale**: the AI's `label` + `rationale` as plain copy.
- **Default = "Match my style ✨"** with a re-roll (↺). The 5 named presets sit
  beside it as selectable swatch chips; picking one switches `mode="preset"` and
  updates the preview instantly (no AI call). Before a style is locked, the
  section reads "Pick a style to see its lettering."

### Book station (`ComposeRoom.tsx` / `ComposeHeader.tsx`)

- **One-time reveal** on first entry after compose completes — a Burst /
  Narrator-Tag ceremony card stating "Your pages are lettered to match — *label*.
  *rationale*". Dismissible; shown once per book (a `lettering_reveal_seen` flag
  in project state, server-side, so it doesn't re-fire on revisit or another
  device).
- The hidden `⟳ REGENERATE ▾` → `MATCH LETTERING` item is removed. In its place,
  a visible `Lettering: [label]` chip in the header opens a popover: re-roll,
  switch preset, or "Change at Look" — all editing the same `LetteringStyle`. The
  Regenerate menu keeps only whole-book compose re-run.

### Manual escape hatch

`PropertyPanel` per-element overrides and character voices are untouched and
remain the top layer; they **survive a restyle** (stored on the `Bubble`, not in
`LetteringStyle`). The popover notes: "Per-bubble tweaks stay put when you change
the book's lettering."

## Polish

- **Thought-bubble scallops**: replace the dashed rounded-rect
  (`comic-page.css:226`) with real cloud scallops via a CSS `mask`
  (radial-gradient puffs) so it renders identically in headless Chromium (PDF)
  and the canvas — no separate SVG path to maintain. Theme-controlled (manga =
  solid cloud, others = classic), with small trailing thought-circles for the
  tail.
- **Export ceremony**: build on `ExportBurst`. The Export tab gets a "Ready to
  print" framing panel (page / panel / lettering counts already computed in
  `PreviewMode.tsx:79`); the burst + download fire on success. The lettering
  reveal stays at Book entry so the two ceremonies don't collide.
- **Page texture**: a subtle, themeable paper-grain / Ben-Day wash under the
  panels on `--page-bg`, low-opacity per the DESIGN.md accessibility note (muted
  or off for noir). Renders in PDF.

## Error Handling

- AI generation fails / offline → `_fallback_lettering_style` (keyword vars +
  fallback font pair), `source="fallback"`; Look shows a quiet "Tuned from your
  style" with re-roll to retry. Style selection is never blocked.
- No `lettering_style.json` at render (style never locked) → renderer defaults to
  the `golden-age` / `default` base so pages always render.
- Font load failure → the CSS fallback chain (current fonts) keeps lettering
  legible.
- `sync-tokens` drift → the parity test fails CI.

## Tests

- **Backend**: `LetteringStyle` model + `_sanitize_style_vars` (extend existing);
  `theme` / `font_pair` validation; keyword fallback including font; merge /
  precedence order; render reads the project object; the three new endpoints.
- **Frontend**: token-parity test (synced copy == canonical); `themes` merge
  including fonts; `useLetteringStyle` query; StyleRoom preview + preset
  switching; Book reveal once-only; thought-scallop snapshot.
- Fixtures referencing `cp.theme` / `cp.style_vars` / `comic_theme` are replaced
  (nothing reads them anymore).

## Acceptance Criteria

- Selecting a style at Look produces a `LetteringStyle` and a live preview with a
  real rationale, with no manual button hunt.
- The Look preview and the rendered Book pages are visually identical because both
  read the same project-level object.
- A noir style and a manga style render in visibly different fonts.
- The Book shows a one-time lettering reveal on first entry; the `MATCH LETTERING`
  dropdown item no longer exists.
- Changing the style or preset re-resolves the base look but preserves per-bubble
  manual edits.
- Thought bubbles render as cloud scallops in both the canvas and the exported
  PDF.
- `theme_tokens.json` is the only definition of base vars, themes, and font
  pairs; the parity test guards it.
