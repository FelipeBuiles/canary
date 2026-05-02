# Graph Report - canary  (2026-05-02)

## Corpus Check
- 210 files · ~145,933 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1632 nodes · 2905 edges · 47 communities detected
- Extraction: 71% EXTRACTED · 29% INFERRED · 0% AMBIGUOUS · INFERRED: 845 edges (avg confidence: 0.76)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 108|Community 108]]
- [[_COMMUNITY_Community 109|Community 109]]
- [[_COMMUNITY_Community 110|Community 110]]
- [[_COMMUNITY_Community 111|Community 111]]

## God Nodes (most connected - your core abstractions)
1. `Config` - 81 edges
2. `apiFetch()` - 65 edges
3. `save_state()` - 26 edges
4. `create_initial_state()` - 26 edges
5. `StageState` - 24 edges
6. `get_db()` - 24 edges
7. `Bubble` - 24 edges
8. `generate_image()` - 21 edges
9. `run()` - 20 edges
10. `begin_stage()` - 19 edges

## Surprising Connections (you probably didn't know these)
- `test_fast_image_alias_estimates_reference_input_images()` --calls--> `provider_usd_to_credits()`  [INFERRED]
  novel_to_comic/tests/test_usage.py → novel_to_comic/src/novel_to_comic/server/credits.py
- `regen_panel_with_instruction()` --calls--> `instruction_rewrite_system_prompt()`  [INFERRED]
  novel_to_comic/src/novel_to_comic/server/routers/pipeline.py → novel_to_comic/src/novel_to_comic/prompt_instructions.py
- `test_generate_panel_writes_failure_metadata()` --calls--> `Config`  [INFERRED]
  novel_to_comic/tests/test_image_failure_meta.py → novel_to_comic/src/novel_to_comic/config.py
- `test_panel_estimate_counts_actual_uploaded_references()` --calls--> `Config`  [INFERRED]
  novel_to_comic/tests/test_image_failure_meta.py → novel_to_comic/src/novel_to_comic/config.py
- `test_list_images_marks_failure_metadata_as_failed_even_with_existing_image()` --calls--> `list_images()`  [INFERRED]
  novel_to_comic/tests/test_image_failure_meta.py → novel_to_comic/src/novel_to_comic/server/routers/stages.py

## Communities

### Community 0 - "Community 0"
Cohesion: 0.03
Nodes (117): build_style_sample_prompt(), Render a compact style-evaluation prompt shared by CLI and API routes., Record cost from a non-stage API call (style samples, cover, etc.).      Adds th, Atomically write pipeline state to state.json.      Writes to a temp file first,, record_misc_usage(), save_state(), history(), pricing_reference() (+109 more)

### Community 1 - "Community 1"
Cohesion: 0.03
Nodes (98): PanelGeometry, PanelBreakdown, make_progress(), Structured event system for pipeline stages.  Each stage ``run()`` function acce, Return a Progress appropriate for the execution mode.      When ``on_event`` is, Progress stand-in that discards all output.      Used when ``on_event`` is provi, _SilentProgress, apply_narration_decision_patch() (+90 more)

### Community 2 - "Community 2"
Cohesion: 0.03
Nodes (95): browser_context(), _bubble_html(), build_page_html(), detect_theme(), _e(), _font_face(), _panel_html(), _playwright_browser_install_message() (+87 more)

### Community 3 - "Community 3"
Cohesion: 0.04
Nodes (28): Config, _find_env_file(), load_config(), Pipeline configuration loaded from config.yaml + .env., Resolve the effective text model for a pipeline stage.          Priority: dev_mo, Walk up the directory tree from start, returning the first .env found., Load config from config.yaml, then overlay .env / shell env vars.      Priority, # NOTE: All three presets currently resolve to the same gateway aliases. (+20 more)

### Community 4 - "Community 4"
Cohesion: 0.04
Nodes (77): BaseModel, Pydantic data models for the pipeline., LayoutPlan, LayoutPlanBeatRef, LayoutPlanMetadata, LLMNarrationDecisionSpec, LLMPanelSpec, NarrationDecision (+69 more)

### Community 5 - "Community 5"
Cohesion: 0.02
Nodes (18): useGenerationJobs(), useProjectStatus(), useReflowSinglePage(), useRunPipeline(), useStageEstimate(), useStoryBible(), useStyles(), TryLayoutsModal() (+10 more)

### Community 6 - "Community 6"
Cohesion: 0.05
Nodes (65): createCheckout(), getPackages(), apiFetch(), getProjectConfig(), updateProjectConfig(), getBalance(), getCreditHistory(), getPricingReference() (+57 more)

### Community 7 - "Community 7"
Cohesion: 0.06
Nodes (59): AIRefusalError, _base_url(), _chat_completion(), _content_summary(), _decode_image_response(), _error_json(), _extract_response_cost(), _extract_usage() (+51 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (34): Enum, approve_stage(), begin_stage(), create_initial_state(), get_stale_stages(), is_stale(), load_state(), PipelineState (+26 more)

### Community 9 - "Community 9"
Cohesion: 0.06
Nodes (53): ImagePrompt, PromptSubject, Pydantic models for image prompts., apply_instruction_patch(), _clean_patch_value(), _enforce_prompt_invariants(), instruction_rewrite_system_prompt(), instruction_rewrite_user_content() (+45 more)

### Community 10 - "Community 10"
Cohesion: 0.06
Nodes (55): balance(), estimate_stage_cost(), Return the estimated credit reservation for running a stage., Return the estimated credit reservation for running a stage., Return the estimated credit cost to regenerate one panel image., Return the estimated credit cost to regenerate one panel image., regen_panel_estimate(), credits_per_provider_usd() (+47 more)

### Community 11 - "Community 11"
Cohesion: 0.06
Nodes (36): Exception, ArtifactMissing, asset_failure_path(), asset_matches_meta(), asset_meta_path(), character_ref_meta_path(), character_ref_sheet_path(), compose_page_path() (+28 more)

### Community 12 - "Community 12"
Cohesion: 0.08
Nodes (34): archived_panel_version_count(), _failure_meta_path(), _image_dimensions(), _image_fingerprint(), list_panel_versions(), _meta_path(), _next_version_number(), panel_image_path() (+26 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (34): CostBreakdown, get_pricing_resolver(), _load_json(), _load_yaml(), PricingResolver, Cached LiteLLM model pricing and cost calculation helpers., Estimate input cost for reference images in image edit operations.          Chec, Fetch LiteLLM's public cost map into the local cache file.      This is intentio (+26 more)

### Community 14 - "Community 14"
Cohesion: 0.11
Nodes (21): Bubble, CharacterVoice, ComicPage, PagePanel, Comic page layout data model.  ComicPage is the canonical editing surface for st, One panel cell on a comic page., One assembled comic page.      This is what ``pipeline export --from-json`` read, Per-character bubble style preset applied automatically at render time. (+13 more)

### Community 15 - "Community 15"
Cohesion: 0.13
Nodes (18): handleAddBubble(), handleAddSfx(), handleDeleteElement(), handleDragEnd(), handleGeneratePageStyle(), handlePanelReframeDragEnd(), handleRedo(), handleResetPanelFrame() (+10 more)

### Community 16 - "Community 16"
Cohesion: 0.15
Nodes (25): _asset_meta_common(), _cast_identity_lock(), _character_ref_meta(), _character_ref_prompt(), _character_ref_style_ref(), _character_signature(), _crop_sheet_to_poses(), _file_sha256() (+17 more)

### Community 17 - "Community 17"
Cohesion: 0.1
Nodes (25): _extract_with_retry(), _find_quote_position(), _is_offscreen_character(), _looks_adult(), _normalize_character_anchor_tags(), _normalize_narrative_arcs(), _normalize_result(), Stage 1: Novel → Story Bible JSON.  Reads the full novel and makes one long-cont (+17 more)

### Community 18 - "Community 18"
Cohesion: 0.12
Nodes (8): clean(), Shared text helpers for prompt composition and indexing., Truncate to *limit* characters on a word boundary., Collapse whitespace and strip a string., shorten(), Tests for text utilities (text_utils.py)., TestClean, TestShorten

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (15): bool_env(), Shared environment variable helpers., Read a boolean from an environment variable., configure_logging(), Logging helpers for the web server., Configure concise terminal logs for `pipeline serve`., request_log_middleware(), _should_log_request() (+7 more)

### Community 20 - "Community 20"
Cohesion: 0.32
Nodes (15): _bool_env(), _current_trace_id(), _finish_span(), _full_prompts_enabled(), image_payload_summary(), _is_sensitive_key(), log_call_end(), log_call_start() (+7 more)

### Community 21 - "Community 21"
Cohesion: 0.2
Nodes (9): ComicPageCanvas(), getLayout(), resolveGridPlacement(), PanelCell(), normalizePct(), normalizePx(), resolveThemeVars(), sanitizeStyleVars() (+1 more)

### Community 22 - "Community 22"
Cohesion: 0.27
Nodes (11): _annotate_transition_beats(), _build_user_content(), _is_offscreen_character(), _localized_system_prompt(), _normalize_screenplay(), _process_scene(), Stage 4: Scene text → Screenplay format  Converts prose scenes into observable-a, Process a single scene into a screenplay. (+3 more)

### Community 23 - "Community 23"
Cohesion: 0.23
Nodes (10): _client(), export_url(), r2_configured(), Cloudflare R2 upload helper for user-facing exports (PDFs, CBZs).  R2 is optiona, Return the public R2 URL for an export file without uploading., Upload an export file to R2 and return its public URL., upload_export(), download_export() (+2 more)

### Community 24 - "Community 24"
Cohesion: 0.2
Nodes (3): handleContinue(), handleContinueClick(), handleRun()

### Community 25 - "Community 25"
Cohesion: 0.21
Nodes (4): handleGenerate(), handleInstructionRegen(), handleQuickRedo(), runCreditAction()

### Community 26 - "Community 26"
Cohesion: 0.25
Nodes (10): create_checkout(), _handle_checkout_completed(), list_packages(), Stripe Checkout and webhook for credit purchases., Return available credit packages — used by the frontend to render buy buttons., Receive Stripe events. Must use raw request body for signature verification., _stripe(), _stripe_dict() (+2 more)

### Community 27 - "Community 27"
Cohesion: 0.29
Nodes (10): _extract_config_fields(), _extract_models(), _extract_routes(), main(), Parse server/routers/*.py for FastAPI route decorators.      prefix_map must mat, Parse config.py for Pydantic field definitions., Parse models/*.py for Pydantic model classes and their fields., write_api_routes_doc() (+2 more)

### Community 28 - "Community 28"
Cohesion: 0.31
Nodes (6): GenerationJob, _failing_runner(), _OneJobQueue, _run_single_job_worker(), test_generation_job_failure_does_not_log_traceback_by_default(), test_generation_job_failure_traceback_can_be_enabled()

### Community 29 - "Community 29"
Cohesion: 0.22
Nodes (3): clean(), renderPanelPromptBody(), saveStructuredPatch()

### Community 30 - "Community 30"
Cohesion: 0.44
Nodes (8): env_keys(), finish(), load_json(), main(), panel_characters(), production_prompt(), rel(), select_test_panels()

### Community 32 - "Community 32"
Cohesion: 0.43
Nodes (5): canUseStorage(), readShowDevContent(), redactDevParameters(), redactDevText(), writeShowDevContent()

### Community 35 - "Community 35"
Cohesion: 0.6
Nodes (5): main(), output_name(), panel_characters(), production_prompt(), select_test_panels()

### Community 36 - "Community 36"
Cohesion: 0.5
Nodes (2): ProjectCard(), resolveStatus()

### Community 38 - "Community 38"
Cohesion: 0.6
Nodes (3): handleKeyDown(), revert(), save()

### Community 40 - "Community 40"
Cohesion: 0.5
Nodes (2): buildDisplayPage(), PageEditor()

### Community 41 - "Community 41"
Cohesion: 0.5
Nodes (2): _defaultProviderForModel(), handleSubmit()

### Community 43 - "Community 43"
Cohesion: 0.5
Nodes (2): AuthGuard(), useAuth()

### Community 44 - "Community 44"
Cohesion: 0.67
Nodes (2): normalizeShotType(), ShotDiagram()

### Community 45 - "Community 45"
Cohesion: 0.67
Nodes (2): BubbleElement(), resolveTailDirection()

### Community 49 - "Community 49"
Cohesion: 0.67
Nodes (2): Pipeline stages — each stage is a pure function from files to files., Stage

### Community 66 - "Community 66"
Cohesion: 1.0
Nodes (2): clearReconnectTimer(), closeCurrentSource()

### Community 67 - "Community 67"
Cohesion: 1.0
Nodes (1): Novel-to-Comic Pipeline: Convert novels into graphic novels.

### Community 108 - "Community 108"
Cohesion: 1.0
Nodes (1): Accept a comma-separated string in place of a list.

### Community 109 - "Community 109"
Cohesion: 1.0
Nodes (1): Accept 'Act 1', 'act_1', 'ACT 2', etc. in place of a bare integer.

### Community 110 - "Community 110"
Cohesion: 1.0
Nodes (1): Accept missing title — will be filled in by normalizer if needed.

### Community 111 - "Community 111"
Cohesion: 1.0
Nodes (1): Accept a single scene id string in place of a list.

## Knowledge Gaps
- **262 isolated node(s):** `Tests for comic page models (models/comic_page.py).`, `Tests for pipeline state machine (state.py).`, `Tests for pipeline config (config.py).`, `Tests for event system (events.py).`, `Tests for image prompt composition.` (+257 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **Thin community `Community 36`** (5 nodes): `CoverShape()`, `ProjectCard()`, `resolveStatus()`, `statusClass()`, `ProjectCard.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 40`** (5 nodes): `buildDisplayPage()`, `closest()`, `getVisualPanelPosition()`, `PageEditor()`, `PageEditor.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 41`** (5 nodes): `UploadStep.tsx`, `_defaultProviderForModel()`, `formatBytes()`, `handleModelChange()`, `handleSubmit()`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 43`** (4 nodes): `AuthGuard()`, `useAuth()`, `AuthGuard.tsx`, `useAuth.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 44`** (4 nodes): `normalizeShotType()`, `renderSilhouette()`, `ShotDiagram()`, `ShotDiagram.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 45`** (4 nodes): `BubbleElement()`, `bubbleStyle()`, `resolveTailDirection()`, `BubbleElement.tsx`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 49`** (3 nodes): `__init__.py`, `Pipeline stages — each stage is a pure function from files to files.`, `Stage`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 66`** (3 nodes): `clearReconnectTimer()`, `closeCurrentSource()`, `pipeline.ts`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 67`** (2 nodes): `Novel-to-Comic Pipeline: Convert novels into graphic novels.`, `__init__.py`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 108`** (1 nodes): `Accept a comma-separated string in place of a list.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 109`** (1 nodes): `Accept 'Act 1', 'act_1', 'ACT 2', etc. in place of a bare integer.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 110`** (1 nodes): `Accept missing title — will be filled in by normalizer if needed.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.
- **Thin community `Community 111`** (1 nodes): `Accept a single scene id string in place of a list.`
  Too small to be a meaningful cluster - may be noise or needs more connections extracted.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `Config` connect `Community 3` to `Community 2`, `Community 4`, `Community 7`, `Community 8`, `Community 9`, `Community 13`, `Community 28`?**
  _High betweenness centrality (0.073) - this node is a cross-community bridge._
- **Why does `ArtifactMissing` connect `Community 11` to `Community 1`, `Community 4`, `Community 14`, `Community 9`?**
  _High betweenness centrality (0.032) - this node is a cross-community bridge._
- **Why does `project_layout_plan_to_pages()` connect `Community 1` to `Community 2`, `Community 14`?**
  _High betweenness centrality (0.027) - this node is a cross-community bridge._
- **Are the 64 inferred relationships involving `Config` (e.g. with `_FakeResponse` and `_FakeAsyncClient`) actually correct?**
  _`Config` has 64 INFERRED edges - model-reasoned connections that need verification._
- **Are the 68 inferred relationships involving `str` (e.g. with `.__init__()` and `_relative_to_project()`) actually correct?**
  _`str` has 68 INFERRED edges - model-reasoned connections that need verification._
- **Are the 64 inferred relationships involving `apiFetch()` (e.g. with `getBalance()` and `getCreditHistory()`) actually correct?**
  _`apiFetch()` has 64 INFERRED edges - model-reasoned connections that need verification._
- **Are the 23 inferred relationships involving `save_state()` (e.g. with `.test_save_and_load_roundtrip()` and `.test_all_eight_stages_present_after_load()`) actually correct?**
  _`save_state()` has 23 INFERRED edges - model-reasoned connections that need verification._