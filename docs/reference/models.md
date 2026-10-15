# Models Reference

_Auto-generated from `models/*.py`. Do not edit manually._

These Pydantic models define the current pipeline's typed contracts. See [Stage Contracts](stage-contracts.md) for artifact paths, ownership, and revision boundaries.

## RevisionedArtifact _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `revision` | `int` | `Field(ge=1)` |
| `content_sha256` | `str` | `''` |

## NarrativeTreatment _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `causal_spine` | `tuple[str, ...]` | `Field(min_length=1)` |
| `character_arcs` | `tuple[str, ...]` | `()` |
| `essential_events` | `tuple[str, ...]` | `()` |
| `essential_event_ids` | `tuple[str, ...]` | `()` |
| `character_turns` | `tuple[str, ...]` | `()` |
| `character_turn_ids` | `tuple[str, ...]` | `()` |
| `reveals` | `tuple[str, ...]` | `()` |
| `reactions` | `tuple[str, ...]` | `()` |
| `consequences` | `tuple[str, ...]` | `()` |
| `transitions` | `tuple[str, ...]` | `()` |
| `aftermath` | `tuple[str, ...]` | `()` |
| `motifs` | `tuple[str, ...]` | `()` |
| `relative_emphasis` | `tuple[str, ...]` | `()` |

## LetteringItem _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `kind` | `Literal['dialogue', 'thought', 'caption', 'sfx']` |  |
| `text` | `str` | `Field(min_length=1)` |
| `speaker` | `str | None` | `None` |
| `speaker_entity_id` | `str | None` | `None` |
| `delivery` | `Literal['onscreen', 'offscreen', 'narration', 'quoted_text', 'display'] | None` | `None` |
| `source_unit_ids` | `tuple[str, ...]` | `()` |

## AppearanceChange _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `entity_id` | `str` | `Field(min_length=1)` |
| `from_state_id` | `str | None` | `None` |
| `to_state_id` | `str` | `Field(min_length=1)` |
| `description` | `str` | `Field(min_length=1)` |

## ContinuityTransition _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `dimension` | `Literal['time', 'place', 'knowledge', 'emotional_state']` |  |
| `scope_id` | `str` | `Field(min_length=1, description='Stable charact...` |
| `from_state` | `str` | `Field(min_length=1)` |
| `to_state` | `str` | `Field(min_length=1)` |
| `description` | `str` | `Field(min_length=1)` |

## AdaptedBeat _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `order` | `int` | `Field(ge=1)` |
| `summary` | `str` | `Field(min_length=1)` |
| `narrative_function` | `Literal['establisher', 'initial', 'prolongation', 'peak', 'release', 'transition']` |  |
| `story_functions` | `tuple[Literal['causal_event', 'reveal', 'reaction', 'consequence', 'transition', 'aftermath', 'character_turn'], ...]` | `()` |
| `brief_requirement_ids` | `tuple[str, ...]` | `()` |
| `source_unit_ids` | `tuple[str, ...]` | `Field(min_length=1)` |
| `entity_ids` | `tuple[str, ...]` | `()` |
| `lettering` | `tuple[LetteringItem, ...]` | `()` |
| `transitions` | `tuple[ContinuityTransition, ...]` | `()` |
| `appearance_changes` | `tuple[AppearanceChange, ...]` | `()` |

## AdaptationLedgerEntry _(adaptation.py)_

| Field | Type | Default |
|-------|------|---------|
| `source_unit_id` | `str` | `Field(min_length=1)` |
| `disposition` | `Literal['depicted', 'dialogue', 'thought', 'caption', 'visual_motif', 'compressed_into', 'intentionally_omitted']` |  |
| `adapted_beat_ids` | `tuple[str, ...]` | `()` |
| `reason` | `str | None` | `None` |
| `preserved_function` | `str` | `Field(min_length=1)` |

## StoryPosition _(appearance.py)_

| Field | Type | Default |
|-------|------|---------|
| `scene_id` | `str` |  |
| `beat` | `Optional[int]` | `None` |

## Transition _(appearance.py)_

| Field | Type | Default |
|-------|------|---------|
| `label` | `str` |  |
| `depicted_at` | `Optional[StoryPosition]` | `None` |
| `cause` | `Optional[str]` | `None` |

## AppearanceState _(appearance.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `label` | `str` |  |
| `visual_anchor` | `str` |  |
| `visually_significant` | `bool` | `False` |
| `baseline_affect` | `Optional[str]` | `None` |
| `canonical_equivalent` | `bool` | `False` |
| `continuity_guard` | `Optional[str]` | `None` |
| `changed_facets` | `tuple[Literal['age', 'hair', 'face', 'build', 'anatomy', 'clothing', 'damage', 'weather', 'light', 'water_level', 'architecture', 'landmarks', 'materials', 'atmosphere', 'shape', 'contents', 'color'], ...]` | `Field(default=(), description='Every facet this...` |
| `replaces_identity` | `bool` | `False` |
| `reference_form` | `Optional[ReferenceForm]` | `Field(default=None, description="Characters onl...` |

## StateActivation _(appearance.py)_

| Field | Type | Default |
|-------|------|---------|
| `state_id` | `str` |  |
| `at` | `StoryPosition` |  |
| `transition` | `Optional[Transition]` | `None` |

## ChapterNote _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `label` | `str` | `Field(min_length=1)` |
| `synopsis` | `str` | `Field(min_length=1)` |

## DigestCharacter _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | `Field(min_length=1)` |
| `aliases` | `list[str]` | `[]` |
| `role` | `str` | `Field(min_length=1)` |
| `presence` | `Literal['central', 'supporting', 'passing']` |  |

## DigestThread _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | `Field(min_length=1)` |
| `status` | `Literal['opens', 'advances', 'resolves']` |  |
| `note` | `str` | `Field(min_length=1)` |

## PartDigest _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `synopsis` | `str` | `Field(min_length=1)` |
| `chapters` | `list[ChapterNote]` | `[]` |
| `characters` | `list[DigestCharacter]` | `[]` |
| `threads` | `list[DigestThread]` | `[]` |
| `motifs` | `list[str]` | `[]` |

## BookAct _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `number` | `int` | `Field(ge=1)` |
| `title` | `str` | `Field(min_length=1)` |
| `summary` | `str` | `Field(min_length=1)` |
| `first_part` | `str` |  |
| `last_part` | `str` |  |

## BookThread _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `''` |
| `title` | `str` | `Field(min_length=1)` |
| `summary` | `str` | `Field(min_length=1)` |
| `opens_in` | `str` |  |
| `resolves_in` | `str | None` | `None` |

## BookCharacter _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `name` | `str` | `Field(min_length=1)` |
| `aliases` | `list[str]` | `[]` |
| `role` | `str` | `Field(min_length=1)` |
| `prominence` | `Literal['principal', 'recurring', 'minor']` |  |
| `first_part` | `str` |  |
| `last_part` | `str` |  |

## BookMapPart _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `part_id` | `str` |  |
| `text_sha256` | `str` | `Field(pattern='^[0-9a-f]{64}$')` |
| `synopsis` | `str` | `Field(min_length=1)` |
| `role` | `str` | `Field(min_length=1)` |

## BookMap _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `version` | `Literal[1]` | `1` |
| `synopsis` | `str` | `Field(min_length=1)` |
| `parts` | `list[BookMapPart]` | `Field(min_length=1)` |
| `acts` | `list[BookAct]` | `Field(min_length=1)` |
| `threads` | `list[BookThread]` | `[]` |
| `characters` | `list[BookCharacter]` | `[]` |
| `themes` | `list[str]` | `[]` |
| `motifs` | `list[str]` | `[]` |

## PartRole _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `part_id` | `str` |  |
| `role` | `str` | `Field(min_length=1)` |

## BookSynthesis _(book_map.py)_

| Field | Type | Default |
|-------|------|---------|
| `synopsis` | `str` | `Field(min_length=1)` |
| `acts` | `list[BookAct]` | `Field(min_length=1)` |
| `parts` | `list[PartRole]` | `Field(min_length=1)` |
| `threads` | `list[BookThread]` | `[]` |
| `characters` | `list[BookCharacter]` | `[]` |
| `themes` | `list[str]` | `[]` |
| `motifs` | `list[str]` | `[]` |

## CropOCRLine _(crop_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` | `Field(min_length=1)` |
| `confidence` | `float` | `Field(ge=0, le=1, allow_inf_nan=False)` |
| `box` | `tuple[int, int, int, int]` |  |

## CropOCRRead _(crop_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `observation_id` | `str` |  |
| `status` | `Literal['read', 'no_region', 'over_budget', 'unavailable', 'pending', 'outcome_unknown']` |  |
| `crop_sha256` | `str | None` | `None` |
| `bounds` | `tuple[int, int, int, int] | None` | `None` |
| `lines` | `tuple[CropOCRLine, ...]` | `()` |
| `primary_text` | `str` |  |
| `verdict` | `Literal['agrees', 'disagrees', 'inconclusive']` | `'inconclusive'` |

## CropOCRReport _(crop_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `Literal[2]` | `2` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `comic_page_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `input_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `reader_fingerprint` | `str` |  |
| `minimum_confidence` | `float` | `Field(ge=0, le=1)` |
| `status` | `Literal['agrees', 'disagrees', 'inconclusive']` |  |
| `complete` | `bool` | `True` |
| `readings` | `tuple[CropOCRRead, ...]` | `()` |

## PageCapabilityProfile _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `provider` | `str` | `Field(min_length=1)` |
| `model` | `str` | `Field(min_length=1)` |
| `complete_page_generation` | `Literal[True]` | `True` |
| `exact_visible_lettering` | `bool` | `True` |
| `max_image_references` | `int` | `Field(ge=0)` |
| `reference_ordering` | `Literal['ordered']` |  |
| `editing_modes` | `tuple[Literal['instructed', 'region_targeted'], ...]` | `()` |
| `output_width` | `int` | `Field(gt=0)` |
| `output_height` | `int` | `Field(gt=0)` |
| `output_media_type` | `Literal['image/png']` | `'image/png'` |
| `max_prompt_characters` | `int` | `Field(gt=0)` |
| `retry_semantics` | `Literal['bounded_submission']` |  |
| `max_attempts` | `int` | `Field(default=3, ge=1)` |
| `price_per_page_usd` | `Decimal` | `Field(default=Decimal('0'), ge=0)` |
| `price_per_reference_usd` | `Decimal` | `Field(default=Decimal('0'), ge=0)` |

## PageReference _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `order` | `int` | `Field(ge=1)` |
| `media_type` | `str` | `Field(min_length=1)` |
| `content_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `visual_anchor` | `str` | `Field(min_length=1)` |
| `entity_id` | `str | None` | `Field(min_length=1)` |
| `appearance_state_id` | `str | None` | `None` |
| `label` | `str` | `''` |
| `continuity_guard` | `str` | `''` |
| `identity` | `str` | `Field(default='', exclude_if=lambda value: not ...` |

## RetryProvenance _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `attempt` | `int` | `Field(ge=1)` |
| `retries_request_sha256` | `str | None` | `Field(default=None, min_length=64, max_length=64)` |

## FrozenPageGenerationRequest _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `request_sha256` | `str` | `''` |
| `page_number` | `int` | `Field(ge=1)` |
| `comic_page_revision` | `int` | `Field(ge=1)` |
| `comic_page_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `edition_id` | `str` | `Field(min_length=1)` |
| `edition_revision` | `int` | `Field(ge=1)` |
| `edition_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `profile_id` | `str` | `Field(min_length=1)` |
| `profile_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `provider` | `str` | `Field(min_length=1)` |
| `model` | `str` | `Field(min_length=1)` |
| `prompt` | `str` | `Field(min_length=1)` |
| `lettering` | `tuple[LetteringItem, ...]` |  |
| `references` | `tuple[PageReference, ...]` | `()` |
| `written_identities` | `tuple[ApprovedVisualReference, ...]` | `Field(default=(), exclude_if=lambda value: not ...` |
| `output_width` | `int` | `Field(gt=0)` |
| `output_height` | `int` | `Field(gt=0)` |
| `output_media_type` | `Literal['image/png']` |  |
| `estimated_cost_usd` | `Decimal` | `Field(ge=0)` |
| `artifact_kind` | `Literal['complete_page']` | `'complete_page'` |
| `retry` | `RetryProvenance` |  |
| `correction` | `PageRenderCorrection | None` | `None` |

## PageRenderSelection _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `revision` | `int` | `Field(ge=1)` |
| `image_sha256` | `str` | `Field(pattern='^[0-9a-f]{64}$')` |

## PageRenderRevision _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` | `Field(ge=1)` |
| `revision` | `int` | `Field(ge=1)` |
| `parent_revision` | `int | None` | `Field(default=None, ge=1)` |
| `comic_page_revision` | `int` | `Field(ge=1)` |
| `comic_page_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `request_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `width` | `int` | `Field(gt=0)` |
| `height` | `int` | `Field(gt=0)` |
| `provider` | `str` | `Field(min_length=1)` |
| `model` | `str` | `Field(min_length=1)` |
| `latency_ms` | `int` | `Field(ge=0)` |
| `cost_usd` | `Decimal | None` | `Field(ge=0)` |

## CompletePageProviderResult _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `artifact_kind` | `Literal['complete_page']` |  |
| `image_bytes` | `bytes` | `Field(min_length=1)` |
| `media_type` | `Literal['image/png']` |  |
| `width` | `int` | `Field(gt=0)` |
| `height` | `int` | `Field(gt=0)` |
| `latency_ms` | `int` | `Field(ge=0)` |
| `provider_request_id` | `str | None` | `None` |
| `actual_provider_model` | `str | None` | `Field(min_length=1)` |
| `usage` | `UsageRecord` |  |
| `response_metadata` | `dict[str, object] | None` | `None` |

## PageGenerationProvenance _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `render` | `PageRenderRevision` |  |
| `usage` | `UsageRecord` |  |
| `provider_request_id` | `str | None` | `None` |
| `response_metadata` | `dict[str, object] | None` | `None` |
| `ai_trace_id` | `str | None` | `None` |

## PageGenerationFailure _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` | `Field(ge=1)` |
| `request_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `failed_at` | `datetime` |  |
| `phase` | `Literal['generation', 'analysis']` | `'generation'` |
| `classification` | `str` | `Field(min_length=1)` |
| `recoverable` | `bool` |  |
| `user_message` | `str` | `Field(min_length=1)` |
| `error` | `str` | `Field(min_length=1)` |

## ObservedRegion _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `polygon` | `tuple[tuple[float, float], ...]` | `Field(min_length=3)` |

## OCRTextObservation _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `text` | `str` | `Field(min_length=1)` |
| `detected_region_id` | `str | None` | `None` |
| `role` | `Literal['comic_lettering', 'incidental_text']` | `'comic_lettering'` |

## ObservedFigure _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `entity_id` | `str | None` | `None` |
| `x` | `float` | `Field(ge=0, le=1)` |
| `y` | `float` | `Field(ge=0, le=1)` |
| `width` | `float` | `Field(gt=0, le=1)` |
| `height` | `float` | `Field(gt=0, le=1)` |

## OCRExtraction _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `lettering` | `tuple[OCRTextObservation, ...]` | `()` |
| `incidental_text` | `tuple[OCRTextObservation, ...]` | `()` |
| `observed_regions` | `tuple[ObservedRegion, ...]` | `()` |
| `observed_reading_order` | `tuple[str, ...]` | `()` |
| `reading_order_proven` | `bool` | `False` |
| `figures` | `tuple[ObservedFigure, ...]` | `()` |

## OCRProviderResponse _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `int` | `1` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `request_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `response` | `object` |  |
| `raw_response` | `str | None` | `None` |
| `parser_version` | `str` | `'page_ocr_v2'` |
| `usage` | `UsageRecord` |  |

## RawOCRObservation _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `int` | `1` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `extraction` | `OCRExtraction` |  |
| `usage` | `UsageRecord | None` | `None` |
| `figures_read` | `bool` | `False` |

## LetteringMatch _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `lettering_item_id` | `str` | `Field(min_length=1)` |
| `observation_id` | `str` | `Field(min_length=1)` |
| `canonical_text` | `str` | `Field(min_length=1)` |
| `observed_text` | `str` | `Field(min_length=1)` |

## RenderAnalysis _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `validator_version` | `str` | `'legacy'` |
| `comic_page_sha256` | `str` | `''` |
| `reading_order_proven` | `bool` | `False` |
| `punctuation_policy` | `Literal['typographic_lettering_v2']` | `'typographic_lettering_v2'` |
| `recognized_lettering` | `dict[str, str]` | `Field(default_factory=dict)` |
| `ocr_observations` | `tuple[OCRTextObservation, ...]` | `()` |
| `incidental_text` | `tuple[OCRTextObservation, ...]` | `()` |
| `lettering_matches` | `tuple[LetteringMatch, ...]` | `()` |
| `observed_regions` | `tuple[ObservedRegion, ...]` | `()` |
| `observed_reading_order` | `tuple[str, ...]` | `()` |
| `invariant_failures` | `tuple[InvariantFailure, ...]` | `()` |
| `editorial_issues` | `tuple[EditorialIssue, ...]` | `()` |
| `evidence` | `tuple[str, ...]` | `()` |
| `crop_verification` | `CropOCRReport | None` | `None` |
| `analysis_usage` | `UsageRecord | None` | `None` |

## AnnotationPoint _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `x` | `float` | `Field(ge=0, le=1)` |
| `y` | `float` | `Field(ge=0, le=1)` |

## CorrectionAnnotation _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(default='', max_length=120)` |
| `kind` | `Literal['pin', 'rectangle', 'highlight', 'freehand', 'arrow', 'ellipse', 'text']` |  |
| `points` | `tuple[AnnotationPoint, ...]` | `Field(min_length=1, max_length=64)` |
| `note` | `str` | `Field(default='', max_length=500)` |
| `label` | `str | None` | `Field(default=None, max_length=120)` |

## CorrectionChange _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1, max_length=120)` |
| `issue_id` | `str | None` | `Field(default=None, min_length=1)` |
| `instruction` | `str` | `Field(min_length=1, max_length=1000)` |
| `annotations` | `tuple[CorrectionAnnotation, ...]` | `Field(default=(), max_length=24)` |

## PageRenderCorrection _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `issue_ids` | `tuple[str, ...]` | `Field(default=())` |
| `page_number` | `int` | `Field(ge=1)` |
| `comic_page_revision` | `int` | `Field(ge=1)` |
| `comic_page_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `parent_render_revision` | `int` | `Field(ge=1)` |
| `parent_render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `mode` | `Literal['instructed', 'region_targeted']` |  |
| `instruction` | `str` | `Field(min_length=1)` |
| `detected_region_ids` | `tuple[str, ...]` | `()` |
| `resolved_regions` | `tuple[ObservedRegion, ...]` | `()` |
| `depiction` | `Literal['canonical', 'less_graphic']` | `'canonical'` |
| `retained_instructions` | `tuple[str, ...]` | `()` |
| `changes` | `tuple[CorrectionChange, ...]` | `Field(default=(), max_length=24)` |
| `note` | `str` | `Field(default='', max_length=1000)` |
| `context_beat_ids` | `tuple[str, ...]` | `()` |
| `context_source_unit_ids` | `tuple[str, ...]` | `()` |
| `context_selected_source_unit_ids` | `tuple[str, ...]` | `()` |
| `context_adaptation_revision` | `int | None` | `Field(default=None, ge=1)` |
| `context_adaptation_sha256` | `str | None` | `Field(default=None, min_length=64, max_length=64)` |
| `context_digest` | `str` | `''` |
| `context_truncated` | `bool` | `False` |
| `artifact_kind` | `Literal['complete_page']` | `'complete_page'` |

## PageCorrectionIntent _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `issue_id` | `str` | `Field(min_length=1)` |
| `page_number` | `int` | `Field(ge=1)` |
| `parent_render_revision` | `int` | `Field(ge=1)` |
| `mode` | `Literal['instructed', 'region_targeted']` |  |
| `instruction` | `str` | `Field(min_length=1)` |
| `detected_region_ids` | `tuple[str, ...]` | `()` |
| `artifact_kind` | `Literal['complete_page']` | `'complete_page'` |

## AdaptCopyCorrectionRequest _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `issue_id` | `str` | `Field(min_length=1)` |
| `page_number` | `int` | `Field(ge=1)` |
| `owner_stage` | `Literal['adapt']` | `'adapt'` |
| `requested_change` | `str` | `Field(min_length=1)` |
| `source_unit_ids` | `tuple[str, ...]` | `()` |
| `adapted_beat_ids` | `tuple[str, ...]` | `()` |
| `lettering_item_ids` | `tuple[str, ...]` | `()` |
| `requires_replan` | `Literal[True]` | `True` |

## PageIssueSummary _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `unresolved_issue_ids` | `tuple[str, ...]` | `()` |
| `blocking_issue_ids` | `tuple[str, ...]` | `()` |
| `accepted_editorial_issue_ids` | `tuple[str, ...]` | `()` |

## PageIssue _(draw.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `issue_type` | `str` | `Field(min_length=1)` |
| `classification` | `Literal['invariant_failure', 'editorial_issue']` | `'editorial_issue'` |
| `correction_kind` | `Literal['render_fidelity', 'copy_change']` | `'render_fidelity'` |
| `correction_owner` | `Literal['adapt', 'draw']` | `'draw'` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `evidence` | `tuple[str, ...]` | `Field(min_length=1)` |
| `requested_correction` | `str` | `Field(min_length=1)` |
| `source_unit_ids` | `tuple[str, ...]` | `()` |
| `adapted_beat_ids` | `tuple[str, ...]` | `()` |
| `lettering_item_ids` | `tuple[str, ...]` | `()` |
| `detected_region_ids` | `tuple[str, ...]` | `()` |
| `entity_ids` | `tuple[str, ...]` | `()` |
| `appearance_state_ids` | `tuple[str, ...]` | `()` |
| `status` | `Literal['open', 'revised', 'accepted', 'resolved', 'dismissed']` |  |
| `resolution_revision` | `int | None` | `Field(default=None, ge=1)` |
| `dismissal_reason` | `str | None` | `None` |

## PreflightDiagnostic _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `owner_stage` | `StageName` |  |
| `code` | `str` | `Field(min_length=1)` |
| `message` | `str` | `Field(min_length=1)` |
| `artifact_ids` | `tuple[str, ...]` | `()` |
| `evidence` | `tuple[str, ...]` | `Field(min_length=1)` |

## PreflightPage _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` | `Field(ge=1)` |
| `comic_page_revision` | `int` | `Field(ge=1)` |
| `comic_page_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `analysis_render_revision` | `int | None` | `Field(default=None, ge=1)` |
| `width` | `int | None` | `Field(default=None, gt=0)` |
| `height` | `int | None` | `Field(default=None, gt=0)` |
| `trim_width` | `int | None` | `Field(default=None, gt=0)` |
| `trim_height` | `int | None` | `Field(default=None, gt=0)` |
| `bleed_px` | `int` | `Field(default=0, ge=0)` |
| `color_profile` | `str | None` | `None` |
| `lettering_revision` | `int | None` | `None` |
| `lettering_sha256` | `str | None` | `None` |
| `lettering_placement_review_needed` | `bool` | `False` |
| `composite_identity` | `str | None` | `None` |
| `normalized_image_sha256` | `str | None` | `Field(default=None, min_length=64, max_length=64)` |
| `invariant_failures` | `tuple[InvariantFailure, ...]` | `()` |
| `diagnostics` | `tuple[PreflightDiagnostic, ...]` | `()` |
| `unresolved_editorial_issue_ids` | `tuple[str, ...]` | `()` |
| `accepted_editorial_issue_ids` | `tuple[str, ...]` | `()` |

## FinishProductionSpec _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `canvas_width` | `int` | `Field(gt=0)` |
| `canvas_height` | `int` | `Field(gt=0)` |
| `bleed_px` | `int` | `Field(default=0, ge=0)` |
| `dpi` | `int` | `Field(default=300, gt=0)` |
| `color_profile` | `Literal['sRGB']` | `'sRGB'` |
| `jpeg_quality` | `int` | `Field(default=88, ge=70, le=95)` |

## DrawCorrectionRequest _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `owner_stage` | `Literal['draw']` | `'draw'` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int | None` | `Field(default=None, ge=1)` |
| `failure_codes` | `tuple[str, ...]` | `Field(min_length=1)` |
| `issue_ids` | `tuple[str, ...]` | `()` |
| `requested_correction` | `str` | `Field(min_length=1)` |
| `artifact_kind` | `Literal['complete_page']` | `'complete_page'` |

## ExportPackage _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `format` | `Literal['pdf', 'cbz']` |  |
| `relative_path` | `str` | `Field(min_length=1)` |
| `content_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `byte_size` | `int` | `Field(gt=0)` |
| `page_numbers` | `tuple[int, ...]` | `Field(min_length=1)` |

## FinishPreflight _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `edition_revision` | `int` | `Field(ge=1)` |
| `edition_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `validator_version` | `int` | `Field(default=1, ge=1)` |
| `production` | `FinishProductionSpec | None` | `None` |
| `pages` | `tuple[PreflightPage, ...]` | `Field(min_length=1)` |
| `correction_requests` | `tuple[DrawCorrectionRequest, ...]` | `()` |
| `packages` | `tuple[ExportPackage, ...]` | `()` |
| `packaging_failures` | `tuple[InvariantFailure, ...]` | `()` |

## FinishResult _(finish.py)_

| Field | Type | Default |
|-------|------|---------|
| `preflight` | `FinishPreflight` |  |
| `packages` | `tuple[ExportPackage, ...]` | `()` |

## PromptAnchor _(generation.py)_

| Field | Type | Default |
|-------|------|---------|
| `kind` | `Literal['character', 'location', 'prop']` |  |
| `entity_id` | `str` |  |
| `name` | `str` |  |
| `appearance_state_id` | `str | None` | `None` |
| `text` | `str` |  |
| `continuity_guard` | `str | None` | `None` |

## PromptSubject _(generation.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `str | None` | `None` |
| `name` | `str` |  |
| `identity` | `str` |  |
| `action` | `str` | `''` |
| `expression` | `str` | `''` |
| `baseline_affect` | `str | None` | `None` |
| `wardrobe` | `str` | `''` |
| `position` | `str` | `''` |
| `appearance_state_id` | `str | None` | `None` |
| `appearance_state_canonical_equivalent` | `bool` | `False` |
| `appearance_locked` | `bool` | `False` |
| `appearance_guard` | `str | None` | `None` |
| `reference_form` | `ReferenceForm` | `'figure'` |

## RoleStyle _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `font` | `FontName` | `'EB Garamond'` |
| `font_weight` | `Literal[400, 700]` | `400` |
| `min_font_size` | `float` | `Field(default=16, ge=12, le=100)` |
| `max_font_size` | `float` | `Field(default=17, ge=12, le=180)` |
| `line_height` | `float` | `Field(default=1.05, ge=0.9, le=2)` |
| `align` | `Literal['left', 'center', 'right']` | `'center'` |
| `color` | `Color` | `'#181818'` |
| `fill` | `Color` | `'#ffffff'` |
| `stroke` | `Color` | `'#181818'` |
| `stroke_width` | `float` | `Field(default=1.6, ge=0, le=12)` |
| `padding` | `float` | `Field(default=11, ge=0, le=40)` |
| `corner_radius` | `float` | `Field(default=12, ge=0, le=80)` |
| `shape` | `Literal['box', 'round', 'balloon', 'ellipse', 'cloud', 'whisper', 'burst', 'wavy', 'electric', 'none']` | `Field(default='balloon', description='balloon: ...` |
| `letter_spacing` | `float` | `Field(default=0, ge=-1, le=12)` |
| `text_stroke` | `Color` | `'transparent'` |
| `text_stroke_width` | `float` | `Field(default=0, ge=0, le=12)` |
| `text_case` | `Literal['as_written', 'upper']` | `Field(default='as_written', description='upper:...` |
| `tail_width` | `float` | `Field(default=1, ge=0.4, le=2.5, description='B...` |
| `halo_color` | `Color` | `'transparent'` |
| `halo_width` | `float` | `Field(default=0, ge=0, le=16, description='Oute...` |
| `shadow` | `Literal['none', 'drop', 'extrude']` | `Field(default='none', description='drop: offset...` |
| `shadow_color` | `Color` | `'#181818'` |
| `shadow_x` | `float` | `Field(default=4, ge=-40, le=40)` |
| `shadow_y` | `float` | `Field(default=4, ge=-40, le=40)` |
| `gradient_color` | `Color` | `Field(default='transparent', description='Lette...` |
| `warp` | `Literal['none', 'arc', 'wave']` | `'none'` |
| `warp_amount` | `float` | `Field(default=0.5, ge=-1, le=1, description='Wa...` |
| `jitter` | `float` | `Field(default=0, ge=0, le=1, description='Seede...` |
| `skew` | `float` | `Field(default=0, ge=-30, le=30, description='Le...` |

## LetteringRoles _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `caption` | `RoleStyle` | `Field(default_factory=lambda: RoleStyle(font='E...` |
| `speech` | `RoleStyle` | `Field(default_factory=RoleStyle)` |
| `thought` | `RoleStyle` | `Field(default_factory=lambda: RoleStyle(shape='...` |
| `sfx` | `RoleStyle` | `Field(default_factory=lambda: RoleStyle(font='B...` |

## LetteringDesign _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `label` | `str` | `Field(min_length=1, max_length=100)` |
| `roles` | `DesignedLetteringRoles` |  |

## ResolvedLineMetrics _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `x` | `float` |  |
| `baseline` | `float` |  |
| `width` | `float` | `Field(ge=0)` |
| `ascent` | `float` | `Field(ge=0)` |
| `descent` | `float` | `Field(ge=0)` |
| `glyph_x` | `tuple[float, ...] | None` | `Field(default=None, max_length=401)` |

## ResolvedLettering _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `engine_version` | `str` |  |
| `locale` | `str` |  |
| `text` | `str` | `Field(max_length=10000)` |
| `lines` | `tuple[str, ...]` | `Field(max_length=500)` |
| `font_size` | `float` | `Field(ge=12, le=180)` |
| `line_height` | `float` | `Field(gt=0, le=360)` |
| `height` | `float` | `Field(gt=0, le=1)` |
| `width` | `float | None` | `Field(default=None, gt=0, le=1)` |
| `line_metrics` | `tuple[ResolvedLineMetrics, ...]` | `Field(default=(), max_length=500)` |
| `overflow` | `bool` |  |
| `warnings` | `tuple[str, ...]` | `()` |

## LetteringElement _(lettering.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1, max_length=100, pattern='^[...` |
| `source_lettering_item_id` | `str | None` | `Field(default=None, max_length=100)` |
| `role` | `RoleName` |  |
| `text_by_locale` | `dict[Locale, Annotated[str, Field(max_length=10000)]]` |  |
| `translation_sources` | `dict[Locale, Annotated[str, Field(max_length=10000)]]` | `Field(default_factory=dict)` |
| `suggested_placement` | `PinnedGeometry` |  |
| `placement` | `PinnedGeometry` |  |
| `hidden` | `bool` | `False` |
| `style_override` | `RoleStyle | None` | `None` |
| `tail_target` | `NormalizedPoint | None` | `None` |
| `suggested_tail_target` | `NormalizedPoint | None` | `None` |
| `tail_bend` | `float` | `Field(default=0, ge=-1, le=1)` |
| `link_to` | `str | None` | `Field(default=None, max_length=100)` |
| `rotation` | `float` | `Field(default=0, ge=-180, le=180)` |
| `scale` | `float` | `Field(default=1, ge=0.25, le=3)` |
| `z_index` | `int` | `Field(default=0, ge=-1000, le=1000)` |
| `tight_box` | `bool` | `True` |
| `resolved` | `ResolvedLettering | None` | `None` |

## ApprovedPageRange _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `minimum` | `int` | `Field(ge=1)` |
| `maximum` | `int` | `Field(ge=1)` |
| `approved` | `Literal[True]` | `True` |

## ApprovedVisualReference _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `entity_id` | `str` | `Field(min_length=1)` |
| `appearance_state_id` | `str | None` | `None` |
| `visual_anchor` | `str` | `Field(min_length=1)` |
| `approved` | `Literal[True]` | `True` |
| `label` | `str` | `''` |
| `continuity_guard` | `str` | `''` |
| `kind` | `Literal['character', 'location', 'prop', 'object'] | None` | `None` |
| `identity` | `str` | `''` |
| `requires_image` | `bool` | `True` |

## ApprovedVisualReferenceInventory _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `references` | `tuple[ApprovedVisualReference, ...]` | `()` |

## PinnedGeometry _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `x` | `float` | `Field(ge=0, le=1)` |
| `y` | `float` | `Field(ge=0, le=1)` |
| `width` | `float` | `Field(gt=0, le=1)` |
| `height` | `float` | `Field(gt=0, le=1)` |

## NormalizedPoint _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `x` | `float` | `Field(ge=0, le=1)` |
| `y` | `float` | `Field(ge=0, le=1)` |

## LetteringReservationIntent _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `preferred_zone` | `Literal['top-left', 'top-center', 'top-right', 'middle-left', 'middle-right', 'bottom-left', 'bottom-center', 'bottom-right']` |  |
| `footprint` | `Literal['compact', 'standard', 'wide', 'tall']` |  |
| `line_budget` | `int` | `Field(ge=1, le=30)` |
| `bounds` | `PinnedGeometry | None` | `None` |
| `speaker_entity_id` | `str | None` | `None` |
| `tail_target` | `NormalizedPoint | None` | `None` |

## AuthorGeometryPin _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `beat_id` | `str` | `Field(min_length=1)` |
| `geometry` | `PinnedGeometry` |  |

## PanelCamera _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `shot` | `Literal['extreme_close_up', 'close_up', 'medium_close_up', 'medium', 'medium_wide', 'wide', 'extreme_wide', 'insert']` |  |
| `angle` | `Literal['eye_level', 'low_angle', 'high_angle', 'overhead', 'worms_eye', 'dutch']` |  |

## CharacterActing _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `entity_id` | `str` | `Field(min_length=1)` |
| `facing` | `Literal['toward_viewer', 'three_quarter_left', 'three_quarter_right', 'profile_left', 'profile_right', 'away_from_viewer']` |  |
| `gaze` | `str` | `Field(min_length=1)` |
| `expression` | `str` | `Field(min_length=1)` |
| `gesture` | `str` | `''` |

## PageContent _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `order` | `int` | `Field(ge=1)` |
| `beat_ids` | `tuple[str, ...]` | `Field(min_length=1)` |
| `panel_role` | `Literal['establishing', 'standard', 'detail', 'reaction', 'action', 'transition', 'splash', 'inset']` | `'standard'` |
| `visual_intent` | `str` | `Field(min_length=1)` |
| `lettering` | `tuple[LetteringItem, ...]` | `()` |
| `entity_ids` | `tuple[str, ...]` | `()` |
| `appearance_states` | `dict[str, str]` | `Field(default_factory=dict)` |
| `pinned_geometry` | `PinnedGeometry | None` | `None` |
| `camera` | `PanelCamera | None` | `None` |
| `acting` | `tuple[CharacterActing, ...]` | `()` |

## PlannedPageRevision _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `page_number` | `int` | `Field(ge=1)` |
| `revision` | `int` | `Field(ge=1)` |
| `content_sha256` | `str` | `Field(min_length=64, max_length=64)` |

## PlanReviewDraft _(page.py)_

| Field | Type | Default |
|-------|------|---------|
| `adaptation_sha256` | `str` | `Field(min_length=64, max_length=64)` |
| `rhythm_summary` | `str` |  |
| `pages` | `tuple[ComicPage, ...]` | `Field(min_length=1)` |

## PartRecord _(parts.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `ordinal` | `int` | `Field(ge=1)` |
| `title` | `str` | `Field(min_length=1, max_length=200)` |
| `text_sha256` | `str` | `Field(pattern='^[0-9a-f]{64}$')` |
| `characters` | `int` | `Field(ge=1)` |
| `created_at` | `str` | `Field(min_length=1)` |
| `origin` | `str` | `''` |

## PartManifest _(parts.py)_

| Field | Type | Default |
|-------|------|---------|
| `version` | `Literal[1]` | `1` |
| `revision` | `int` | `Field(default=1, ge=1)` |
| `parts` | `tuple[PartRecord, ...]` | `Field(min_length=1)` |

## SourceUnit _(source.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `ordinal` | `int` | `Field(ge=1)` |
| `start_offset` | `int` | `Field(ge=0)` |
| `end_offset` | `int` | `Field(gt=0)` |
| `text` | `str` | `Field(min_length=1)` |

## SourceContextReference _(source.py)_

| Field | Type | Default |
|-------|------|---------|
| `label` | `str` | `Field(min_length=1)` |
| `unit_ids` | `tuple[str, ...]` | `Field(min_length=1)` |

## SourceScene _(source.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `title` | `str` | `Field(min_length=1)` |
| `first_unit_id` | `str` | `Field(min_length=1)` |
| `last_unit_id` | `str` | `Field(min_length=1)` |
| `context` | `tuple[SourceContextReference, ...]` | `()` |

## SourceDocument _(source.py)_

| Field | Type | Default |
|-------|------|---------|
| `text` | `str` | `Field(min_length=1)` |
| `source_sha256` | `str` | `''` |
| `units` | `tuple[SourceUnit, ...]` | `Field(min_length=1)` |
| `scenes` | `tuple[SourceScene, ...]` | `Field(min_length=1)` |

## CharacterRelationship _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `character_id` | `str` |  |
| `relationship` | `str` |  |

## Character _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `age_range` | `str` | `Field(description='Stated age or source-describ...` |
| `gender` | `str` |  |
| `stature` | `str` | `Field(default='', description="Source-stated bo...` |
| `distinguishing_features` | `list[str]` | `Field(description='Source-stated intrinsic anat...` |
| `baseline_affect` | `str | None` | `None` |
| `default_outfit` | `str` |  |
| `relationships` | `list[CharacterRelationship]` | `[]` |
| `first_appearance_scene` | `str` |  |
| `appearance_states` | `list[AppearanceState]` | `[]` |
| `appearance_timeline` | `list[StateActivation]` | `[]` |
| `aliases` | `list[str]` | `[]` |
| `origin` | `EntityOrigin` | `'extracted'` |
| `identity_kind` | `Literal['individual', 'interchangeable', 'group']` | `Field(default='individual', description="Indivi...` |
| `cast_required` | `bool` | `Field(default=False, description='Needs a dedic...` |
| `reference_form` | `ReferenceForm` | `Field(default='figure', description=REFERENCE_F...` |

## Location _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` | `Field(description='Base-state physical tags, us...` |
| `time_of_day` | `Optional[str]` | `None` |
| `mood` | `str` |  |
| `appearance_states` | `list[AppearanceState]` | `[]` |
| `appearance_timeline` | `list[StateActivation]` | `[]` |
| `aliases` | `list[str]` | `[]` |
| `origin` | `EntityOrigin` | `'extracted'` |

## TransientObject _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `appears_in_beats` | `list[int]` | `[]` |

## Scene _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `part_id` | `str` | `FIRST_PART_ID` |
| `chapter` | `int` |  |
| `title` | `str` |  |
| `location_id` | `str | None` |  |
| `character_ids` | `list[str]` |  |
| `summary` | `str` |  |
| `scene_type` | `str` |  |
| `narrative_beat` | `str` |  |
| `source_start_quote` | `str` |  |
| `source_start_offset` | `int | None` | `Field(default=None, ge=0)` |
| `transient_objects` | `list[TransientObject]` | `[]` |

## StorySequence _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `part_id` | `str` | `FIRST_PART_ID` |
| `number` | `int` | `Field(ge=1)` |
| `title` | `str` |  |
| `scenes` | `list[str]` |  |
| `turn` | `Optional[str]` | `None` |

## Prop _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` |  |
| `name` | `str` |  |
| `visual_anchor` | `str` |  |
| `first_appearance_scene` | `Optional[str]` | `None` |
| `appearance_states` | `list[AppearanceState]` | `[]` |
| `appearance_timeline` | `list[StateActivation]` | `[]` |
| `aliases` | `list[str]` | `[]` |
| `origin` | `EntityOrigin` | `'extracted'` |

## RemovedRecord _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `entity` | `dict[str, Any]` |  |
| `scene_ids` | `list[str]` | `[]` |
| `incoming` | `list[tuple[str, CharacterRelationship]]` | `[]` |

## ExcludedEntity _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `kind` | `Literal['character', 'location', 'prop']` |  |
| `name` | `str` |  |
| `aliases` | `list[str]` | `[]` |
| `removed` | `RemovedRecord | None` | `None` |

## StoryBible _(story_bible.py)_

| Field | Type | Default |
|-------|------|---------|
| `revision` | `int` | `Field(default=1, ge=1)` |
| `title` | `str` |  |
| `author` | `str` |  |
| `total_scenes` | `int` |  |
| `characters` | `list[Character]` |  |
| `locations` | `list[Location]` |  |
| `scenes` | `list[Scene]` |  |
| `sequences` | `list[StorySequence]` |  |
| `style_notes` | `Optional[str]` | `None` |
| `props` | `list[Prop]` | `[]` |
| `excluded_entities` | `list[ExcludedEntity]` | `[]` |

## TextractCrop _(textract_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `observation_id` | `str` |  |
| `status` | `Literal['ready', 'no_region', 'over_budget', 'unavailable']` |  |
| `bounds` | `tuple[int, int, int, int] | None` | `None` |
| `sha256` | `str | None` | `Field(default=None, pattern='^[a-f0-9]{64}$')` |
| `width` | `int` | `Field(default=0, ge=0)` |
| `height` | `int` | `Field(default=0, ge=0)` |

## TextractPlan _(textract_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `Literal[1]` | `1` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(pattern='^[a-f0-9]{64}$')` |
| `input_sha256` | `str` | `Field(pattern='^[a-f0-9]{64}$')` |
| `crops` | `tuple[TextractCrop, ...]` |  |

## TextractAttempt _(textract_ocr.py)_

| Field | Type | Default |
|-------|------|---------|
| `schema_version` | `Literal[1]` | `1` |
| `attempt_id` | `str` | `Field(pattern='^[a-f0-9]{32}$')` |
| `page_number` | `int` | `Field(ge=1)` |
| `render_revision` | `int` | `Field(ge=1)` |
| `render_image_sha256` | `str` | `Field(pattern='^[a-f0-9]{64}$')` |
| `recognition_sha256` | `str` | `Field(pattern='^[a-f0-9]{64}$')` |
| `crop_sha256` | `str` | `Field(pattern='^[a-f0-9]{64}$')` |
| `model` | `str` |  |
| `region` | `str` |  |
| `started_at` | `float` |  |
| `expires_at` | `float` |  |
| `finished_at` | `float | None` | `None` |
| `status` | `Literal['submitting', 'succeeded', 'failed', 'outcome_unknown']` |  |
| `estimated_units` | `Literal[1]` | `1` |
| `unit_price_usd` | `str` |  |
| `pricing_snapshot` | `str` |  |
| `charged_credits` | `Literal[0]` | `0` |
| `response` | `dict[str, Any] | None` | `None` |
| `error_code` | `str | None` | `None` |

## _ValidationResult _(validation.py)_

| Field | Type | Default |
|-------|------|---------|
| `id` | `str` | `Field(min_length=1)` |
| `owner_stage` | `StageName` |  |
| `code` | `str` | `Field(min_length=1)` |
| `message` | `str` | `Field(min_length=1)` |
| `source_unit_ids` | `tuple[str, ...]` | `()` |
| `artifact_ids` | `tuple[str, ...]` | `()` |
| `evidence` | `tuple[str, ...]` | `Field(min_length=1)` |

## ValidationAttempt _(validation.py)_

| Field | Type | Default |
|-------|------|---------|
| `attempt` | `int` | `Field(ge=1)` |
| `invariant_codes` | `tuple[str, ...]` | `()` |
| `editorial_codes` | `tuple[str, ...]` | `()` |

## StageValidation _(validation.py)_

| Field | Type | Default |
|-------|------|---------|
| `owner_stage` | `StageName` |  |
| `attempts` | `int` | `Field(default=1, ge=1)` |
| `invariant_failures` | `tuple[InvariantFailure, ...]` | `()` |
| `editorial_issues` | `tuple[EditorialIssue, ...]` | `()` |
| `recommendations` | `tuple[str, ...]` | `()` |
| `attempt_history` | `tuple[ValidationAttempt, ...]` | `()` |
