# Canary — Product Brief

A product brief for Canary, a tool that turns novels into comic books. This document now tracks both **the product we're building toward** and **the current state of the site**, so UI iterations can start from what actually exists.

**Last status review:** April 22, 2026  
**Status source:** Current React/FastAPI code in `web/src` and `novel_to_comic/src/novel_to_comic/server`.

---

## 0. Current site status

The site is no longer just a dashboard concept. It has a working React shell, project library, project creation flow, per-stage rooms, SSE-backed pipeline progress, artifact viewers/editors, generation job polling, and a functional Stage 7 page editor. It is still an early-MVP local web app: it assumes a local projects directory, local API keys/config, and pipeline artifacts on disk.

### What is done and works now

- **App shell and navigation:** React Router routes for library, new project, settings, dev primitives, and project rooms: Extract, Cast, Adapt, Storyboard, Direct, Draw, Compose, and Styles.
- **Project library:** Lists project directories from the backend, shows project status/cost/furthest stage, tracks running projects, and can request generated project covers once a story bible exists.
- **Pipeline orchestration:** Backend can run the full pipeline or a specific stage, rerun a stage while clearing downstream outputs, approve checkpoints, reset stale stages, expose stage errors, and stream events over SSE.
- **Story bible room:** Shows title/author/scenes plus editable character and location cards. Saves story bible changes back to `story_bible.json`.
- **Cast room:** Shows character reference sheets and location plates from disk, opens images in a modal, and supports queued regeneration of one character ref or one location plate.
- **Style room:** Suggests visual styles, generates sample images, tracks queued/running sample jobs, shows generation metadata, and writes the active style into project config.
- **Adapt room:** Shows screenplay scene summaries and a scene-by-scene screenplay viewer.
- **Storyboard room:** Shows panel breakdowns by scene and supports inline editing for core panel fields such as shot type, camera angle, background description, lighting, mood, and SFX text.
- **Direct room:** Shows prompt summaries by scene, renders prompt lineage/advanced prompt details, and supports prompt editing. Prompt saves rebuild `full_prompt` through the backend renderer.
- **Draw room:** Shows generated panel images by scene/all scenes, synthesizes pending/failed placeholders from prompt and stage state, supports single-panel regeneration, polls generation jobs, and opens panel details in a modal.
- **Compose room:** Provides a real page editor over canonical `assembly/pages/page_NNN.json`: page navigation, zoom, bubble/SFX selection, drag repositioning, add/delete bubble or SFX, undo/redo, panel image offset edits, page theme/layout/style-var edits, reflow by panels-per-page, generated lettering styles, bubble translation, and PDF/CBZ export.
- **Settings:** Supports UI language locally and project-level config edits for output language, dev/demo mode, comic theme, style template, and image model.
- **Backend APIs:** REST endpoints exist for projects, project config, pipeline run/approve/events, story bible, screenplays, panels, prompts, images, styles, page JSON, previews/files, translations, reflow, and export.
- **Build health:** frontend tests pass, build passes.

### What is partially done

- **Rooms mental model:** The eight-room structure exists in routing and UI, but invalidation/downstream recovery is mostly handled through rerun buttons and backend output clearing rather than a polished dependency UI.
- **Editing:** Several JSON artifacts are editable, but edits do not yet present impact analysis, dirty-state review, or explicit downstream invalidation guidance in the UI.
- **Live progress:** SSE is wired for active runs and the wizard consumes it. Existing project rooms mostly rely on status polling, rerun buttons, and job polling rather than a unified live activity drawer.
- **Cost tracking:** Backend state and project cards expose total/stage costs, but the site does not yet show action-level cost previews, budget caps, or per-panel pricing.
- **Failure handling:** Failed stages/items are visible in status and Draw placeholders, and stale stages can be reset through the API. The UX is not yet comprehensive for all failure modes.
- **Localization:** UI language and output language controls exist, and existing page bubbles can be translated to English/Spanish/French. Full multi-language export workflows are still limited.
- **Style system:** Style suggestions/samples/active style work. Style selection is backend-enforced — the pipeline blocks post-extract stages until a style is selected (`is_style_selected` gate in `styles.py`). The broader preset gallery/theme variant studio described below is only partly represented.

### What is missing or still roadmap

- Hosted accounts/SaaS, auth, cloud project library, team collaboration, and public share links.
- Batch project management in the web app.
- User face/likeness insertion.
- Cost preview before project start and before expensive actions.
- Pause/cancel controls for active pipeline runs.
- Source prose side-by-side with screenplay/panel outputs.
- Add/remove/reorder panels within a scene from the Storyboard room.
- Save and choose alternate generated panel versions.
- Bulk panel regeneration from the Draw room.
- Full drag-and-drop page layout for panels across pages.
- Persistent version history beyond local undo/redo.
- Print-preview tooling with bleed marks.
- Web gallery publishing and embeddable widgets.
- API key management in the web UI.
- Model picker with cost/quality comparison per stage.
- Commenting, approval workflows, read-only review links, and async collaboration.

---

## 1. Vision

Canary is the end-to-end studio for turning prose fiction into a finished comic book. A reader uploads a novel, makes a handful of creative decisions, and gets back a polished, exportable graphic novel. Behind the scenes an 8-stage pipeline of LLMs and image models does the heavy lifting; in front of the reader is a focused workspace where every stage is reviewable, editable, and re-runnable without losing prior work.


**What makes it different:**
- **Decomposition over magic.** No single "press button, get comic" — every creative decision (style, character look, panel framing, bubble placement) is a deliberate human checkpoint, not a black box.
- **Editable at every stage.** Story bible, screenplay, panels, prompts, images, and final layout are all artifacts the user can inspect, edit, and re-render from.
- **You in the story.** Optional: inject the user's likeness as a character.

---

## 2. Two products, one engine
not so sure about this part anymore, maybe better to focus solely on the web app as the user facing part

### 2.1 The CLI — `novel_to_comic`

**Audience:** Developers, power users, advanced creators, anyone scripting comic generation in batches.

**Implemented today:**
- `novel_to_comic init` creates a local project, copies the input novel, writes `config.yaml`, `state.json`, and expected artifact folders.
- `novel_to_comic serve` boots the web dashboard.
- All pipeline operations (run, approve, status, export) are HTTP API endpoints — see `server/routers/pipeline.py`.
- The CLI remains the most direct way to run local projects without the React site.

**Future role:**
- Headless interface to the same engine the web app uses.
- Used for batch generation, CI integration, scripted workflows, server-side orchestration.
- Stays opinionated and minimal — no UI concessions, no progress bars in JSON.
- Becomes the canonical way to script multi-novel runs (e.g. an indie publisher generating 30 titles a month).

**Future commands beyond the current set:**
- `novel_to_comic batch <input_dir>` — run pipeline against every novel in a directory
- `novel_to_comic cast --face me.png` — register a face for user insertion
- `novel_to_comic publish <project>` — push to a hosted gallery / share link
- `novel_to_comic diff <project> --stage panels` — see what changed since last run
- `novel_to_comic lint` — pre-flight checks (visual anchors, prompts, model availability)

### 2.2 The Web App

**Audience:** Writers, fans, hobbyists, casual creators, students, indie publishers.

**Implemented today:**
- Local React/Vite app backed by FastAPI.
- Library, upload/create flow, settings, style selection, seven project rooms, and Stage 7 page editor.
- Reads/writes real pipeline artifacts from the project directory rather than mock data.
- Streams active pipeline events over SSE and polls generation jobs for image/style/reference regeneration.

**Future role:**
- The default surface for everyone who isn't a developer.
- A focused creative workspace, not a control panel.
- Optimized for review-and-iterate loops, not raw throughput.
- Eventually deployable as a hosted SaaS, with local-first as a power-user mode.

---

## 3. The pipeline as user-facing concept

The pipeline has 8 stages. In the product, each stage is a **room** the user moves through. They can go back to any room and the system re-runs the affected downstream rooms.

| Stage | What the user sees |
|---|---|
| 1. **Extract** | "We read your novel. Here's your story bible — characters, locations, plot beats." Current: story bible viewer/editor exists. |
| 2. **Cast** | "Here's your cast — meet your characters." Current: character refs and location plates are visible and individually regenerable; uploads/locks are not done. |
| 3. **Adapt** | "Here's the screenplay version of your novel." Current: scene-by-scene screenplay viewer exists; source prose comparison/editing is not done. |
| 4. **Plan** | "Here's the page layout plan for each scene." Current: layout planning with panel breakdown exists. |
| 5. **Storyboard** | "Here's how each scene breaks into panels." Current: editable panel cards exist; add/remove/reorder is not done. |
| 6. **Direct** | "Here's the brief for each panel." Current: prompt inspector/editor exists with lineage display. |
| 7. **Draw** | "Here are your panels." Current: panel gallery, failures/pending states, detail modal, and per-panel regen exist; alternates/bulk regen are not done. |
| 8. **Compose** | "Here's your comic." Current: canonical page JSON editor exists for bubbles, SFX, layout/theme, translation, reflow, and export; full drag-and-drop panel layout and persistent history are not done. |

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
- 8-stage progress visualization (the eight rooms).
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
- Show which RAG-retrieved scene context was used.
- "Explain this prompt" — surfaces the template variables filled in.

### 4.9 Panel gallery (stage 6 checkpoint)
- Grid of all generated panels for a scene or the whole comic.
- Per panel: regenerate, save alternates (keep multiple versions and pick later), reject.
- Quick filters: "show me only failed panels", "show me panels with character X".
- Bulk regen: select 5 panels, fire off regenerations in parallel.
- Show generation cost per panel.

### 4.10 Visual page editor (stage 8 / compose) — the centerpiece
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

1. **Rooms, not screens.** The user moves through 8 rooms in order; back-navigation is always available; downstream rooms invalidate gracefully when something upstream changes.
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
