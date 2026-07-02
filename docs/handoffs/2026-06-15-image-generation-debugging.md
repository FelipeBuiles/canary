# Handoff — Debugging Image-Generation Failures (`draw` stage)

**Date:** 2026-06-15
**Purpose:** Start a fresh session to debug two classes of image-generation
failure. This doc carries the *approach and architecture* only — no need to
replay the prior session.

## What you're debugging

1. **Model-failed-response** — the `draw` stage produces no image: the provider
   returns an empty/blocked candidate, a refusal, or an error; the panel falls
   back / gets flagged.
2. **Fidelity** — an image *is* produced but ignores the reference guides
   (character sheets, location plates) or the character description (wrong face/
   hair/wardrobe, or the wrong appearance-timeline state — e.g. silver hands
   when the panel should show stumps).

These mirror the text-side failures we just fixed in the `direct` stage; the
**same methodology applies**. Read "Methodology" before touching code.

---

## Methodology that worked (reuse this — it's the point of the handoff)

1. **Diagnostics-first. Never guess at a provider failure — make it report its
   reason.** The single highest-leverage move on the text side was surfacing
   `finish_reason` + safety feedback on the empty-response path. Before that,
   "safety block" vs "thinking-budget exhaustion" vs "refusal" all looked
   identical in logs. After, every failure self-explained. **Do the equivalent
   for images first** (see Class A below) — don't start changing models/prompts
   blind.

2. **The gateway-reload gotcha (cost us two wasted runs).** `litellm/config.yaml`
   and `litellm_handlers/` are bind-mounted **read-only** into the
   `canary-litellm-1` container and read **at startup**. Editing them does
   nothing until `docker compose restart litellm`. `docker compose up -d` will
   NOT reload (compose spec unchanged). After any gateway change:
   ```bash
   docker compose restart litellm
   curl -s -o /dev/null -w "%{http_code}\n" http://localhost:4000/health/liveliness  # expect 200
   docker compose logs litellm --tail 20   # expect "Application startup complete"
   ```
   The pipeline **server** (`pipeline serve`) is separate and does NOT autoreload
   under `--dev` either — restart it to pick up Python changes.

3. **Inspect what actually ran via `ai_usage_events` (Supabase).** Every gateway
   call is logged with model, tokens, latency, status, errors, and raw
   `usage_json`. The gateway echoes the *alias* (e.g. `image-balanced`) not the
   resolved Vertex model, so use behavioral **fingerprints** (token/error
   signatures) when the name is ambiguous. Query template:
   ```python
   # cd novel_to_comic && uv run python - <<'PY'
   import os, pathlib
   from collections import Counter
   for line in pathlib.Path("/Users/jbuiles/Code/canary/.env").read_text().splitlines():
       line=line.strip()
       if not line or line.startswith("#") or "=" not in line: continue
       if line.lower().startswith("export "): line=line[7:]
       k,v=line.split("=",1); os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
   from novel_to_comic.server.db import get_db
   rows=(get_db().table("ai_usage_events")
       .select("created_at,feature,model_alias,provider_model,output_tokens,image_count,latency_ms,status,error_type,error_message,usage_json")
       .like("feature","image.%").order("created_at",desc=True).limit(80).execute().data)
   print("statuses:", Counter(r["status"] for r in rows))
   print("error_types:", Counter(r.get("error_type") for r in rows if r.get("error_type")))
   for r in rows[:10]:
       print(r["created_at"], r["feature"], r["status"], r.get("error_type"), str(r.get("error_message"))[:120])
   PY
   ```
   Image features are `image.generate` and `image.generate_multi_ref`.

4. **Reproduce a single call cheaply against the live gateway** instead of
   re-running the whole stage. The master key is in `/Users/jbuiles/Code/canary/.env`
   (`LITELLM_API_KEY` / `LITELLM_MASTER_KEY`, same value). For text we curled
   `POST localhost:4000/v1/chat/completions`. For images the cleanest repro is a
   tiny Python script calling `flux.generate_image_multi_ref(...)` (it owns the
   ref/aspect plumbing) on one real panel's `ImagePrompt` loaded from
   `direct/<scene>/panel_NNN.json`. **Image calls cost real credits** — do one,
   not a batch.

---

## Architecture map — image generation path

```
s7_draw.py (draw stage: orchestration, retry, aspect check, panel flags)
  └─ clients/flux.py :: generate_image_multi_ref(refs=[RefImage(path, role)], layout)
       └─ ai/finalisation.py / ai_generate_image  → gateway POST (vertex-multimodal/...)
            └─ litellm_handlers/vertex_multimodal.py  (CUSTOM provider)
                 client.models.generate_content(
                     contents = [aspect instr, prompt, "<refs:>", role_label, Part, ...],
                     config = GenerateContentConfig(response_modalities=["IMAGE"],
                                                     safety_settings=_SAFETY_OFF))
                 → _extract_image(response)   # raises if no image bytes
```

**Active model (verify per run):**
- Project `config.yaml`: `image_provider: gemini`, `image_model: image-balanced`
  → `image-balanced` = `vertex-multimodal/gemini-3-pro-image-preview`.
- **BUT `fallback_image_model: image-fast` and the server runs `--dev`** →
  the draw stage may actually use `image-fast` =
  `vertex-multimodal/gemini-3.1-flash-image-preview` (weaker). **Confirm which
  one ran via `ai_usage_events`** before judging fidelity — dev mode silently
  swapping to the fast model is a prime fidelity suspect.

**Reference images** are assembled in `prompting.py::build_planned_panel_prompt_spec`
into `ImagePrompt.reference_image_paths`:
- Flagged appearance **state** refs (`refs/<char>/states/<state_id>/{front,three_quarter,gesture}.png`)
  **replace** the canonical crops when the active state is `visually_significant`;
  otherwise canonical `refs/<char>/...` crops are used.
- Location plates: `plates/<loc>/states/<id>.png` (per-state) or `plates/<loc>.png`.
- The handler role-labels each ref ("this is <name>; use ONLY this reference for
  <name>'s face, hair, costume…") — see `vertex_multimodal.py` ~lines 280-300.

**Prompt text** sent with the refs is `ImagePrompt.visual_brief` (now generated
reasoning-free on Flash-Lite — clean prose) or the deterministic
`distilled_prompt` fallback. Either way it carries the **resolved appearance
anchor** (stumps/silver/etc.) from the appearance timeline.

---

## Class A — model-failed-response: where to look

- **No image returned:** `vertex_multimodal.py::_extract_image` (line ~558)
  raises `ValueError("Vertex response did not contain image bytes: <response>")`.
  It dumps the whole response object, so `finish_reason`/`safety_ratings` are
  *in there* but unparsed. **RECOMMENDED FIRST STEP:** parse and surface
  `candidate.finish_reason` + `response.prompt_feedback` / `safety_ratings`
  cleanly in that error (exactly what we did for text at
  `ai/client.py:837`). That turns blind image failures into self-explaining ones.
- **Aspect mismatch:** handler raises `shape_mismatch` (~line 162) when the
  returned image's aspect is outside tolerance; `s7_draw.py` wraps it as
  `AspectMismatchError`. Distinct from a content failure.
- **Other exceptions** → `ctx.record_item_failed(...)` → `draw/panel_flags.json`
  (review-by-exception; flags never block compose). `draw` supports
  `retry_failed=true`.
- **Safety:** we set `safety_settings=_SAFETY_OFF` in the handler
  (`_SAFETY_OFF`, top of `vertex_multimodal.py`) to match the text models.
  **This is UNVERIFIED for image generation** — image models may handle
  safety differently, and some categories (child safety, certain violence) may
  not be disablable. Verify the cutting/violence panels actually render.

## Class B — fidelity: hypotheses to test (in rough priority)

1. **Wrong model in dev mode.** Confirm `image-balanced` (gemini-3-pro-image)
   vs the `--dev` `image-fast` (gemini-3.1-flash-image) actually ran. Fidelity
   differs a lot. (`ai_usage_events` / try a non-dev run.)
2. **Text ↔ ref contradiction.** If a canonical "normal hands" ref is bound but
   the brief says "stumps," the model resolves it arbitrarily — this was the
   *original* appearance bug. Verify per-state refs exist AND are the ones
   bound for the active state (check `reference_image_paths` on the panel JSON
   and that the files exist). The appearance-timeline image-side payoff is
   **untested** end-to-end.
3. **Ref labeling / count.** Inspect the handler's role labels and how many
   refs are bound per panel; too many or mislabeled refs dilute identity.
4. **Brief quality.** Briefs are now clean Flash-Lite prose — but confirm they
   lead with the character's full physical description before action (the system
   prompt requires it; binding appearance to the right character matters when
   multiple characters share a panel).

To debug fidelity, regenerate ONE panel while varying a single factor (model,
ref set, ref ordering) and compare — same approach we used to compare Flash vs
Flash-Lite text quality.

---

## Already done this session (do NOT redo)

- **Gateway safety:** `safety_settings: OFF` on all Vertex **text** models
  (`extract-*`, `panel-*`, `prompt-*`) via a YAML anchor, AND on the **image**
  handler (`_SAFETY_OFF` in `vertex_multimodal.py`). Text verified live; **image
  unverified**.
- **Reasoning removed for prompt assembly:** `prompt-balanced` repointed to
  `gemini-3.1-flash-lite` (Flash couldn't fully disable thinking; it leaked CoT
  into briefs / exhausted the token budget). `reasoning_effort: "disable"` on all
  `prompt-*`. `direct` now runs 56/56 clean.
- **`clean_cascade` bug fix:** the cascade listed stage name `"adapt"` instead of
  the `screenplays/` dir, so re-extracts left stale screenplays → downstream ran
  on mismatched scene IDs. Fixed in `stages/__init__.py` + `s4_screenplay.py`.
- **Diagnostics added:** empty-response now reports `finish_reason`/
  `reasoning_tokens` (`ai/client.py`); rejected briefs report length+snippet
  (`prompt_assembly.py`); refusals report their reason (`_refusal_reason`).
- **Frontend:** re-added "↺ Rerun <step>" to the auto-step `InspectDrawer`
  (`rerunStageForDrawer` in `lib/stations.ts`).

## Target project state

- `the-girl-without-hands` — projects dir UUID `63f06b92-a5c6-4f5b-b0e5-c330abe49982`,
  API project id `a13feb57-a122-4315-ac0b-0867a8ec44ee`.
- `direct` complete (56/56 clean briefs). **`draw` is PENDING — this is the next
  stage to run** and where you'll reproduce the failures. Running it costs image
  credits.
- The story has canonical violence (hand-severing) and an appearance timeline
  (real hands → stumps → silver → restored) with per-state refs — good stress
  test for both failure classes.

## Open questions to resolve

- Is `safety_settings: OFF` actually honored for the Vertex **image** models, or
  do violent panels still come back imageless?
- Is `--dev` quietly using `image-fast` instead of `image-balanced`? (fidelity)
- Are the per-state refs (stumps/silver) generated by `s3_cast` AND bound at draw
  time, so images track the timeline? (untested in images)

## Key files

- Draw stage: `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- Image client: `novel_to_comic/src/novel_to_comic/clients/flux.py`
- Image finalize: `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- **Custom image handler (start here for Class A diagnostics):** `litellm_handlers/vertex_multimodal.py`
- Prompt+ref assembly: `novel_to_comic/src/novel_to_comic/prompting.py` (`build_planned_panel_prompt_spec`)
- Gateway model routing + safety: `litellm/config.yaml`
- Usage events / text diagnostics pattern to mirror: `novel_to_comic/src/novel_to_comic/ai/client.py`
- Ref/plate path helpers: `novel_to_comic/src/novel_to_comic/artifacts.py`
- Appearance-timeline design (refs/states): `docs/superpowers/specs/2026-06-14-appearance-timeline-design.md`
- Pipeline API (run/rerun/retry_failed): `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
