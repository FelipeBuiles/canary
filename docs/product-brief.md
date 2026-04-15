# Canary — Product Brief

A product brief for designing the future of Canary, a tool that turns novels into comic books. This document focuses on **the product we're building toward**, not what currently exists. Use it to generate UI iterations.

---

## 1. Vision

Canary is the end-to-end studio for turning prose fiction into a finished comic book. A reader uploads a novel, makes a handful of creative decisions, and gets back a polished, exportable graphic novel. Behind the scenes a 7-stage pipeline of LLMs and image models does the heavy lifting; in front of the reader is a focused workspace where every stage is reviewable, editable, and re-runnable without losing prior work.


**What makes it different:**
- **Decomposition over magic.** No single "press button, get comic" — every creative decision (style, character look, panel framing, bubble placement) is a deliberate human checkpoint, not a black box.
- **Editable at every stage.** Story bible, screenplay, panels, prompts, images, and final layout are all artifacts the user can inspect, edit, and re-render from.
- **You in the story.** Optional: inject the user's likeness as a character.

---

## 2. Two products, one engine

### 2.1 The CLI — `pipeline`

**Audience:** Developers, power users, advanced creators, anyone scripting comic generation in batches.

**Future role:**
- Headless interface to the same engine the web app uses.
- Used for batch generation, CI integration, scripted workflows, server-side orchestration.
- Stays opinionated and minimal — no UI concessions, no progress bars in JSON.
- Becomes the canonical way to script multi-novel runs (e.g. an indie publisher generating 30 titles a month).

**Future commands beyond the current set:**
- `pipeline batch <input_dir>` — run pipeline against every novel in a directory
- `pipeline serve` — boots the web dashboard against one or many projects
- `pipeline cast --face me.png` — register a face for user insertion
- `pipeline publish <project>` — push to a hosted gallery / share link
- `pipeline diff <project> --stage panels` — see what changed since last run
- `pipeline lint` — pre-flight checks (visual anchors, prompts, model availability)

### 2.2 The Web App

**Audience:** Writers, fans, hobbyists, casual creators, students, indie publishers.

**Future role:**
- The default surface for everyone who isn't a developer.
- A focused creative workspace, not a control panel.
- Optimized for review-and-iterate loops, not raw throughput.
- Eventually deployable as a hosted SaaS, with local-first as a power-user mode.

---

## 3. The pipeline as user-facing concept

The pipeline has 7 stages. In the product, each stage is a **room** the user moves through. They can go back to any room and the system re-runs the affected downstream rooms.

| Stage | What the user sees |
|---|---|
| 1. **Extract** | "We read your novel. Here's your story bible — characters, locations, plot beats." Editable. |
| 2. **Cast** | "Here's your cast — meet your characters." Reference sheets per character; user can regenerate or override. |
| 3. **Adapt** | "Here's the screenplay version of your novel." Scene-by-scene prose → screenplay beats. |
| 4. **Storyboard** | "Here's how each scene breaks into panels." Editable shot list per scene. |
| 5. **Direct** | "Here's the brief for each panel." Image prompts, editable. |
| 6. **Draw** | "Here are your panels." Generated images, regen per-panel, alt versions. |
| 7. **Compose** | "Here's your comic." Page layouts with bubbles and SFX. The visual editor lives here. |

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
- 7-stage progress visualization (the seven rooms).
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

### 4.10 Visual page editor (stage 7) — the centerpiece
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

1. **Rooms, not screens.** The user moves through 7 rooms in order; back-navigation is always available; downstream rooms invalidate gracefully when something upstream changes.
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
1. Use CLI: `pipeline batch ./novels/ --style noir --auto-approve safe-stages`.
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

## 8. UI iteration prompts

Use this brief to generate UI iterations in different directions. Suggested frames:

- **"Notion-like"** — calm, content-focused, lots of whitespace, sidebar navigation, inline editing.
- **"Adobe-like"** — dense panels, tool palettes, professional creative-app vibes.
- **"Figma-like"** — canvas-first, floating panels, keyboard shortcuts, multi-cursor feel.
- **"Substack-like"** — writer-first, long-form reading view, minimal chrome.
- **"Game-launcher-like"** — projects as tiles in a library; the comic is a "game" you're producing.
- **"Comic-book-skeuomorphic"** — UI inspired by comic panels and gutters; lean into the medium.

For each frame, design at least: project library, story bible editor, panel gallery, and visual page editor.
