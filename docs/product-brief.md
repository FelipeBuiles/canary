# Canary — Product Brief

A product brief for Canary, a tool that turns novels into comic books. This document now tracks both **the product we're building toward** and **the current state of the site**, so UI iterations can start from what actually exists.

**Last status review:** May 12, 2026
**Status source:** Current React/FastAPI code in `web/src` and `novel_to_comic/src/novel_to_comic/server`.

---

## 0. Current site status

The site is no longer just a dashboard concept. It has a working React shell, project library, project creation flow, stage rooms, SSE-backed pipeline progress, artifact viewers/editors, generation job polling, and a functional Stage 9 compose editor. It is still an early-MVP local web app: it assumes a local projects directory, local API keys/config, and pipeline artifacts on disk.

### What is done and works now

- **App shell and navigation:** React Router routes for library, new project, settings, dev primitives, and eight user-facing project rooms: Extract, Look & Feel, Cast & Places, Script, Shot Plan, Prompt Review, Generate Panels, and Letter & Compose. These map to nine backend stages because Shot Plan combines `plan` and `storyboard`.
- **Project library:** Lists project directories from the backend, shows project status/cost/furthest stage, tracks running projects, and can request generated project covers once a story bible exists.
- **Pipeline orchestration:** Backend runs one requested stage at a time through `POST /run?stage=...`, can rerun a stage while clearing downstream outputs, retry only failed draw panels, approve checkpoints, reset stale stages, expose stage errors, estimate credit reservations, and stream events over SSE. The pipeline no longer has a stage-less "run all" API path.
- **Story bible room:** Shows title/author/scenes plus editable character and location cards. Saves story bible changes back to `story_bible.json`.
- **Cast room:** Shows character reference sheets, prop refs, and location plates from disk, opens images in a modal, and supports queued regeneration of one character ref, prop ref, or location plate.
- **Style room:** Suggests visual styles, generates sample images, tracks queued/running sample jobs, shows generation metadata, and writes the active style into project config.
- **Adapt room:** Shows screenplay scene summaries and a scene-by-scene screenplay viewer.
- **Storyboard room:** Shows panel breakdowns by scene and supports inline editing for core panel fields such as shot type, camera angle, background description, lighting, mood, and SFX text.
- **Direct room:** Shows prompt summaries by scene, renders prompt lineage/advanced prompt details, and supports prompt editing. Prompt saves rebuild `full_prompt` through the backend renderer.
- **Draw room:** Shows generated panel images by scene/all scenes, synthesizes pending/failed placeholders from prompt and stage state, supports single-panel regeneration, instruction-based regeneration, panel acceptance, version history/restore, polls generation jobs, and opens panel details in a modal.
- **Compose room:** Provides a real page editor over canonical `compose/pages/page_NNN.json`: page navigation, zoom, bubble/SFX selection, drag repositioning, add/delete bubble or SFX, undo/redo, panel image offset edits, page theme/layout/style-var edits, reflow by panels-per-page, generated lettering styles, bubble translation, character voice presets, structural operations, and PDF/CBZ export.
- **Settings:** Supports UI language locally and project-level config edits for output language, dev/demo mode, comic theme, image model, and pipeline tuning. Active `style_template` is selected through the Look & Feel workflow, not generic settings.
- **Backend APIs:** REST endpoints exist for projects, covers, project config, pipeline estimates/run/approve/events/regeneration, story bible, screenplays, layout-plan narration decisions, panels, prompts, images with acceptance/versioning/failure detail, styles, page JSON, previews/files, translations, reflow, credits, billing, and export.
- **Build health:** frontend tests pass, build passes.

### What is partially done

- **Rooms mental model:** The eight-room structure exists in routing and UI, but invalidation/downstream recovery is mostly handled through rerun buttons and backend output clearing rather than a polished dependency UI.
- **Editing:** Several JSON artifacts are editable, but edits do not yet present impact analysis, dirty-state review, or explicit downstream invalidation guidance in the UI.
- **Live progress:** SSE is wired for active runs and stage events now update cached project status immediately across rooms. The app still relies on generation-job polling for queued single-asset work and does not yet have a unified live activity drawer.
- **Cost tracking:** Backend state, project cards, stage estimates, regeneration estimates, credit reservations, and billing pages exist. The UX still needs a clearer end-to-end ledger for estimate/reserved/actual/returned credits.
- **Failure handling:** Failed stages/items are visible in status and Draw placeholders, failed panel diagnostics surface provider-blocked/generation-error detail, and stale stages can be reset through the API. The UX is not yet comprehensive for all failure modes.
- **Localization:** UI language and output language controls exist, and existing page bubbles can be translated to English/Spanish/French. Full multi-language export workflows are still limited.
- **Style system:** Style suggestions/samples/active style work. Style selection is backend-enforced — the pipeline blocks post-style stages until a style is selected (`is_style_selected` gate in `styles.py`). The broader preset gallery/theme variant studio described below is only partly represented.

### What is missing or still roadmap

- Hosted accounts/SaaS, auth, cloud project library, team collaboration, and public share links.
- Batch project management in the web app.
- User face/likeness insertion.
- Cost preview before project start and before expensive actions.
- Pause/cancel controls for active pipeline runs.
- Source prose side-by-side with screenplay/panel outputs.
- Add/remove/reorder panels within a scene from the Storyboard room.
- Arbitrary bulk panel regeneration from the Draw room. Retrying failed draw panels exists, but broader batch selection is still roadmap.
- Full drag-and-drop page layout for panels across pages.
- Persistent version history beyond local undo/redo.
- Print-preview tooling with bleed marks.
- Web gallery publishing and embeddable widgets.
- API key management in the web UI.
- Model picker with cost/quality comparison per stage.
- Commenting, approval workflows, read-only review links, and async collaboration.

---

## 1. Vision

Canary is the end-to-end studio for turning prose fiction into a finished comic book. A reader uploads a novel, makes a handful of creative decisions, and gets back a polished, exportable graphic novel. Behind the scenes a 9-stage pipeline of LLMs and image models does the heavy lifting; in front of the reader is a focused workspace where every stage is reviewable, editable, and re-runnable without losing prior work.


**What makes it different:**
- **Decomposition over magic.** No single "press button, get comic" — every creative decision (style, character look, panel framing, bubble placement) is a deliberate human checkpoint, not a black box.
- **Editable at every stage.** Story bible, screenplay, panels, prompts, images, and final layout are all artifacts the user can inspect, edit, and re-render from.
- **You in the story.** Optional: inject the user's likeness as a character.

---

## 2. One product surface, one engine

### 2.1 The CLI — local bootstrap only

**Audience:** Developers and local operators who need to initialise projects or start the web server.

**Implemented today:**
- `pipeline init` creates a local project, copies the input novel, writes `config.yaml`, `state.json`, and expected artifact folders.
- `pipeline serve` boots the web dashboard.
- All pipeline operations (run, approve, status, export) are HTTP API endpoints — see `server/routers/pipeline.py`.
- The CLI is not a separate product workflow and does not run pipeline stages directly.

**Future role:**
- Keep it narrow: project init, server start, and operational checks. Future batch/headless orchestration should call the HTTP API or a dedicated service layer rather than expanding the CLI into a competing interface.

### 2.2 The Web App

**Audience:** Writers, fans, hobbyists, casual creators, students, indie publishers.

**Implemented today:**
- Local React/Vite app backed by FastAPI.
- Library, upload/create flow, settings, style selection, eight user-facing project rooms, and Stage 9 compose editor.
- Reads/writes real pipeline artifacts from the project directory rather than mock data.
- Streams active pipeline events over SSE, applies stage events to cached project status, and polls generation jobs for image/style/reference regeneration.

**Future role:**
- The default surface for everyone who isn't a developer.
- A focused creative workspace, not a control panel.
- Optimized for review-and-iterate loops, not raw throughput.
- Eventually deployable as a hosted SaaS, with local-first as a power-user mode.

---

## 3. The pipeline as user-facing concept

The backend pipeline has 9 stages. In the product, these appear as 8 **rooms**
because `plan` and `storyboard` are combined into Shot Plan. Users can go back
to a room and rerun the affected backend stage/downstream stages.

| Stage | What the user sees |
|---|---|
| 1. **Extract** | "We read your novel. Here's your story bible — characters, locations, plot beats." Current: story bible viewer/editor exists. |
| 2. **Look & Feel** | "Pick the visual language." Current: style suggestions, samples, active-style selection, and backend style gate exist. |
| 3. **Cast & Places** | "Here's your cast — meet your characters." Current: character sheets and location plates are visible and individually regenerable; uploads/locks are not done. |
| 4. **Script** | "Here's the screenplay version of your novel." Current: scene-by-scene screenplay viewer exists; source prose comparison/editing is not done. |
| 5-6. **Shot Plan** | "Here's how each scene breaks into pages and panels." Current: layout plan plus editable panel cards exist; add/remove/reorder within a scene is not done. |
| 7. **Prompt Review** | "Here's the brief for each panel." Current: prompt inspector/editor exists with lineage display. |
| 8. **Generate Panels** | "Here are your panels." Current: panel gallery, failures/pending states, detail modal, per-panel regen, instruction regen, acceptance, and version restore exist; bulk regen is not done. |
| 9. **Letter & Compose** | "Here's your comic." Current: canonical page JSON editor exists for bubbles, SFX, layout/theme, translation, reflow, structural operations, character voices, and export; full drag-and-drop panel layout and persistent history are not done. |

This rooms-not-buttons mental model is the spine of the future UI.

---

## 4. Future feature areas (UI surfaces to design)

### 4.1 Onboarding & project creation
- Upload a novel (EPUB / TXT / paste).
- Pick or define a **visual style** — gallery of style presets with sample images, plus "describe your own."
- Optional: upload a face for user insertion.
- API key / account setup (cloud) or local key wizard (self-hosted).
- Cost preview ("This novel will cost about $4–6 to fully generate.")

### 4.2 Project dashboard / library
- Multi-project view: a shelf of comics in progress.
- Per-project: thumbnail of cover page, current stage, total cost, last activity.
- Quick actions: resume, duplicate, archive, export.

### 4.3 Pipeline progress & control
- 9-stage backend progress visualization mapped into 8 user-facing rooms.
- Live progress with streaming logs as stages run (already wired via SSE).
- Cost-as-you-go counter.
- Pause / resume / cancel a running stage.
- "Why is this slow?" — show what API calls are in flight.

### 4.4 Story bible editor (stage 1 checkpoint)
- Character cards: name, description, role, **visual anchor** (sacred 60–80-word physical description).
- Location cards: visual anchor (40–60 words).
- Scene list with summaries and excerpts.
- Plot arc visualization.
- Edit any field — system re-runs only the downstream stages affected.

### 4.5 Cast / character reference sheets (stage 2 checkpoint)
- Per character: 4-pose reference sheet (front, three-quarter, side, action).
- Regenerate one pose, all poses, or override with an uploaded image.
- Compare side-by-side with the visual anchor text — does the image match?
- "Lock" a character once approved to prevent accidental regen.
- User insertion: drag a face onto a character card.

### 4.6 Style studio
- Gallery of style presets (cinematic, manga, noir, watercolor, vintage, etc.).
- Each preset shows a 2x2 grid of sample panels in that style.
- Free-text style override with live preview on a single test panel.
- Theme variant picker (matches the CSS theme system: default / noir / manga / vintage / painted).
- Per-page and per-panel theme overrides.

### 4.7 Screenplay & panel review (stages 3–4)
- Two-column layout: original prose on the left, screenplay/panel breakdown on the right.
- Click a panel to see the source paragraph it came from.
- Edit panel descriptions, shot type, camera angle, characters present.
- Add / remove / reorder panels within a scene.
- Re-run a single scene's panels without re-running the whole screenplay stage.

### 4.8 Prompt inspector & editor (stage 5)
- Per-panel: see the assembled image prompt.
- Edit prompt directly, save as draft, regenerate the image.
- Show which character/location visual anchors were injected.
- "Explain this prompt" — surfaces the template variables filled in.

### 4.9 Panel gallery (stage 6 checkpoint)
- Grid of all generated panels for a scene or the whole comic.
- Per panel: regenerate, save alternates (keep multiple versions and pick later), reject.
- Quick filters: "show me only failed panels", "show me panels with character X".
- Bulk regen: select 5 panels, fire off regenerations in parallel.
- Show generation cost per panel.

### 4.10 Visual page editor (stage 9 / compose) — the centerpiece
The drag-and-drop editor is the highest-value UI in the product. Every panel is a canvas; every bubble, caption, and SFX is a draggable, editable element.

- **Page layout:** Choose a layout grid (1–6 panels per page or freeform). Drag panels to reorder, resize, span columns.
- **Speech bubbles:** Drag to reposition. Edit text inline. Change tail direction (toward the speaker). Pick speech / thought / narration variants.
- **SFX:** Drag, rotate, resize. Edit text.
- **Captions:** Narrative text boxes, draggable.
- **Theme override:** Per-page or per-panel theme switch.
- **Live re-render preview:** What you see is what exports.
- **Undo / redo / version history:** For every page.

### 4.11 Export & publish
- Export formats: PDF (print-ready), CBZ (digital comics standard), web gallery (paginated HTML).
- Print preview with bleed marks for physical printing.
- "Publish" — push to a public gallery / shareable link with optional NSFW gating.
- Embeddable widget for blog posts.
- Multi-language export (translate dialogue, regenerate with new text).

### 4.12 User insertion ("you in the story")
- Upload one or more reference photos.
- Pick which character to replace.
- See preview before committing.
- Privacy controls — local-only mode for face data.

### 4.13 Cost & usage
- Real-time cost tracking per stage.
- Budget cap with auto-pause.
- Per-API-key cost breakdown.
- "Cheapest path" mode that swaps to lower-cost models.

### 4.14 Settings & configuration
- API keys management (Gemini, Anthropic, Together, OpenAI).
- Model picker per stage with cost/quality tradeoff display.
- Pipeline tunables (panels per scene, words per bubble, parallelism).
- Theme defaults.
- Auto-checkpoint preferences (which stages should pause).

### 4.15 Collaboration (longer-term)
- Multiple users on one project.
- Comment on a panel ("redraw this — too dark").
- Approval workflow for studios / small teams.
- Read-only review links for showing drafts.

---

## 5. UX principles for designers

1. **Rooms, not screens.** The user moves through 8 user-facing rooms in order; back-navigation is always available; downstream rooms invalidate gracefully when something upstream changes.
2. **Show the artifact, hide the JSON.** The user should never see raw JSON in the default flow. Power users get a "view source" toggle.
3. **Always show cost.** Every action that costs money should show a price tag before commit.
4. **Re-render is cheap, redo from scratch is expensive.** Make per-item regen one click; full pipeline rebuild requires confirmation.
5. **Visual anchors are sacred.** UI must surface them when relevant (character editor, prompt inspector) and never hide them.
6. **The text is composited in post.** Speech bubbles, captions, and SFX live in the page editor, never inside the generated images. The editor is the truth.
7. **Local-first by default.** The web app should run against a local project directory just as well as a hosted account.
8. **Live progress, never opaque waits.** Any stage that takes >5 seconds streams progress and partial results.
9. **Failure is a first-class state.** Failed panels are visible, retryable, and don't block other work.
10. **Mobile is review-only.** Editing is desktop; reading and approving on mobile is fine.

---

## 6. Reference user journeys

### Journey A: "I want a comic of my self-published novel"
1. Upload EPUB → cost preview → pick style preset → start.
2. Wait ~10 minutes; system pauses at story bible. Skim characters, fix one name, approve.
3. System generates character refs. Look at hero — face is wrong. Regenerate. Approve.
4. System generates panels. Browse the gallery. Three panels are off; click regenerate on each.
5. System composes pages. Open the visual editor. Move three speech bubbles. Tweak one SFX.
6. Export PDF. Done.

### Journey B: "I want to be the protagonist of *Pride and Prejudice*"
1. Upload public-domain text.
2. Upload three photos of self.
3. Pick "regency portrait" style preset.
4. At cast checkpoint: drag own face onto Elizabeth. Approve.
5. Continue through pipeline.
6. Export CBZ. Read on phone.

### Journey C: "I'm an indie publisher generating 12 titles a month"
1. Use the API to run pipeline batches or the CLI batch command once implemented.
2. Web app shows all 12 projects on the dashboard.
3. Reviewer in the team opens each, fixes issues, exports.
4. Pipeline runs unattended overnight; reviewer wakes up to a queue of awaiting-review projects.

### Journey D: "I'm trying out the tool with a short story"
1. Paste 3,000 words.
2. Pick style.
3. Watch progress for 4 minutes.
4. Get a 6-page comic.
5. Tweet it.

---

## 7. Out of scope (explicit non-goals)

- Generating new prose (Canary adapts existing fiction; it doesn't write the source novel).
- Animation / video output.
- Live multiplayer editing (real-time cursor sharing). Async collaboration only.
- Hosting reader-facing comic distribution at scale (export-and-share is enough).
- Replacing professional comic artists for major publishers — Canary is for the long tail, not Marvel.

---
