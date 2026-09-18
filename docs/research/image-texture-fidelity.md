# Image texture fidelity: investigation and mitigation

Reviewed: 2026-09-18. Scope: GPT Image 2 / 2.5, Style/Cast and hybrid full-page Draw.
Status: prompting mitigation implemented; provider-free regression coverage; **live visual efficacy not established**. No paid image requests were made for this investigation.

## Finding

The supplied fairy/abbey screenshots show repeated, high-contrast mottling across sky, masonry, foliage and some figures. The useful description is **unwanted over-texturing / texture amplification**, not a diagnosis of a specific model-internal defect. Intended watercolor granulation and paper texture can coexist with this unwanted pattern. The objection is its scale, contrast and uniform spread across unrelated materials, not the existence of texture.

The attachments are PNG screenshots, 1639×2048 and 1360×2048. They are not accompanied by original provider rasters, frozen requests, reference images, response metadata or correction lineage. Consequently they cannot establish the originating model snapshot, quality setting, input endpoint, compression history or editing depth. They are also different compositions, not an A/B experiment. Their aspect ratios resemble a style proof and a complete page, but that is not sufficient to assign production provenance.

Do not call this a proven diffusion, VAE, upscaling, JPEG, or OpenAI edit-endpoint bug. There is no model-internal evidence here. The investigation did not find an authoritative diagnosis of this exact GPT Image 2.5 symptom.

## What the implementation actually does

Inspected baseline: commit `60b54f40a63db1c60311b0f6b7b8bc4856afe806`.

| Question | Verified implementation / consequence |
| --- | --- |
| Does `edits` mean a previous page is being edited? | No. Both [asset transport](../../novel_to_comic/src/novel_to_comic/ai/providers/litellm_http.py) and [Draw transport](../../novel_to_comic/src/novel_to_comic/page_drawing.py) choose `/v1/images/edits` whenever image inputs exist. A new reference-conditioned page uses it too. An actual correction has an explicit parent in its frozen contract. |
| Is full-page Draw accidentally using medium quality? | The OpenAI complete-page transport explicitly requests `quality="high"`, `output_format="png"`, and the frozen width/height. Generic asset `Config.image_quality` defaults to `medium`; that is a separate path and is not evidence of the setting used for either screenshot. |
| Is Canary enlarging the full-page response? | Draw validates decoded dimensions against its frozen profile and does not resize a successful result to fit. Non-PNG formats are normalized to PNG, not upscaled. Browser/screenshot scaling must still be checked against the saved original. |
| Is LiteLLM definitely dropping `quality` or `size` for OpenAI edits? | No such defect was established. The pinned [OpenAI edit mapper][litellm-edit] explicitly supports both; the [dispatcher][litellm-main] collects named parameters before invoking that mapper. The custom-provider size workaround elsewhere in Draw is not evidence of the same bug in the OpenAI route. An execution trace is still needed to prove what the running deployment sent. |
| Can bad reference texture become an authority? | The [semantic compiler](../../novel_to_comic/src/novel_to_comic/compiled_request.py) makes approved style imagery authoritative for mark-making, wash behavior and rendering density. This is correct for intentional style, but previously had no shared distinction between intended texture and incidental digital defects. This is a plausible propagation mechanism, not demonstrated causation for the attachments. |
| Are references being secretly recompressed here? | [Wire reference materialization](../../novel_to_comic/src/novel_to_comic/provider_wire.py) checks content digests and reads original bytes. No reference denoising/resampling was added in this PR. |

OpenAI's edit reference itself includes an example creating a **new** composition from several input images. Using edits for reference conditioning is therefore not inherently a pipeline error.[api-edit]

## Ranked hypotheses and discriminating evidence

**Reference/style over-amplification — plausible, high investigative value.** Inspect the approved style proof first, then calibration/subject/location references, then the first page. A noisy proof may repeatedly demonstrate exactly the marks the model is told to preserve. Matching palette and medium is not the same as preserving every incidental pixel pattern. The new policy makes that distinction explicit without substituting a different style.

**Serial editing drift — plausible, currently unconfirmed.** Compare explicit parent hashes and revisions, not endpoint names. If an unchanged sky gets progressively more mottled after successive corrections, accumulated redraw is supported as an explanation. A bad first reference-conditioned generation does not require a serial-edit explanation. Compare a correction from the last clean approved parent with one from the newest degraded parent, retaining the same authorized final intent.

**Resolution/detail-budget mismatch — plausible.** A complete page has to fit panels, figures, ruins, foliage and atmospheric washes into one raster. Small subjects may receive texture instead of legible form. Inspect the original at intended reading size and at native pixels; an enlarged screenshot can make an existing problem more conspicuous. This does not prove that increasing resolution fixes it.

**Prompt/style intent — plausible.** Check the actual selected style and owner addenda for deliberate dense stippling, heavy granulation, aged paper, distressed printing or uniform texture. Do not delete those words from protected anchors or silently rewrite a selected style. If they are the unwanted artistic instruction, the owner should change and re-approve it.

**Encoding/display defect — check, not the leading visual explanation.** Compare the original, application display and screenshot. A PNG wrapper does not prove that an earlier stage never used JPEG. Converting an already damaged raster to PNG prevents a further lossy encoding; it does not reconstruct lost detail.

## Implemented mitigation

[rendering_fidelity.py](../../novel_to_comic/src/novel_to_comic/rendering_fidelity.py) owns one shared surface-fidelity policy:

- Keep texture intentional, material-specific and subordinate to readable forms, while retaining the selected medium and deliberate grain, stipple, hatching or distress.
- Maintain a hierarchy of detail instead of distributing the same high-contrast speckles or cellular patches over every surface.
- On a new image, reconstruct intended materials without amplifying incidental defects in references. On a correction, cleanup remains limited to the authorized change; untouched artwork is not permission for global smoothing.

[generate_system_constraints](../../novel_to_comic/src/novel_to_comic/generation_prompt.py) includes the policy in the protected semantic constraint section for Style/Cast assets, before prompt budgeting and request hashing. This covers style proofs as well as downstream references: applying a page-only negative instruction would leave the upstream style-authority risk unaddressed.

[page_art_style_template](../../novel_to_comic/src/novel_to_comic/style_contract.py) includes the same policy in newly compiled hybrid page prompts. Projection is idempotent; framing remains selected framing; post-production lettering instructions remain excluded. The stored selected style is not rewritten. Legacy baked page templates and already frozen requests are not retroactively modified.

No provider parameter, model, output dimensions, reference bytes/order, retry count, paid fallback, edition profile or artifact schema is changed. This is deliberately **not** an automatic cleanup filter. The added prompt has a small input-token cost; it does not request more images or raise quality/resolution tiers. Normal prompt-size validation still applies.

## Additional mitigations and tradeoffs

### Fix the source of the visual authority first

When the original proof already contains unwanted mottling, create and approve a cleaner proof with the desired palette, line language and material texture. Review affected downstream references before spending on pages. Do not silently replace an approved image, mutate its bytes in place, discard identity references, or rewrite historical hashes. A newly accepted proof is a new authority/revision.

For a rejected result, prefer the last clean authorized parent over repeatedly editing the newest degraded output. Retain the complete authorized correction intent; starting from an older parent must not undo earlier accepted changes. This is an author decision, not an automatic retry.

### Test model and quality independently

OpenAI positions Sunburst for its strongest image/editing capability and supports a dated snapshot. Token pricing is not a fixed price per accepted page, and the older GPT Image 2 calculator does not estimate 2.5 consumption.[sunburst]

The current API supports `xhigh` and `max` for 2.5.[api-edit] These are **experiments**, not default fixes. OpenAI cautions that higher quality does not guarantee improvement, recommends comparing complete edit sequences, and emphasizes measuring cost per accepted result.[prompting] Keep model, references, prompt and dimensions fixed while testing one quality change. Then compare Sunburst versus Flare separately. Do not change both and attribute the improvement to one.

Draw locks its profile at edition creation. Changing the generic asset quality configuration does not upgrade an existing Draw edition. A different Draw resolution/quality needs an explicit supported profile and a separate test edition, not a hidden override in the transport. This PR does not add that product surface.

### Test a larger native raster only as a separate experiment

A candidate same-aspect test is 1536×2304 versus 1024×1536: 2.25 times the pixels, calculated from the dimensions. The candidate is below the documented 3,686,400-pixel experimental threshold and uses multiples of 16. It must still pass the selected provider's live contract and Canary's profile validation.[generation]

More pixels may improve small contours or may simply produce more texture. Compare both at the **same final reading size**, as well as with unresampled crops. Do not claim that a post-generation upscale is equivalent to requesting a larger native image.

### Do not treat generic API fields as confirmed per-model noise controls

The generic edit reference exposes `input_fidelity`.[api-edit] Canary's OpenAI page adapter deliberately omits it with a GPT 2.5 rejection comment. This investigation did not perform a paid compatibility probe. The PR therefore neither reintroduces `input_fidelity="low"` nor treats it as a supported artifact cure. Similarly, unsupported seed, guidance-scale or denoising-strength controls must not be smuggled through `extra_body`.

PNG is the documented default. `output_compression` applies to JPEG/WebP, not PNG.[generation] Preserve native output and inspect response metadata; do not add a PNG compression-quality knob or assume it can remove synthesized mottling.

### Region masks and post-processing are separate product changes

Current region-targeted Draw guidance describes regions in the prompt; it is not a deterministic unchanged-pixel guarantee. A future mask/composite implementation could preserve the exterior exactly, but must explicitly own mask coordinates, edge feathering, changes crossing boundaries, the raw provider result and derived-image provenance. Do not silently composite a current whole-page correction: it could clip an authorized moving subject or shadow.

A global blur/denoiser would reduce both unwanted texture and intended ink, paper and fine anatomy. A generative upscaler could invent detail. Neither is installed automatically here. Any future filter should be opt-in, selective, reversible and applied to a derived artifact before lettering, with the original retained.

## Zero-cost inspection tool

[compare_image_fidelity.py](../../scripts/compare_image_fidelity.py) produces a new local HTML report, native-pixel PNG crops and a JSON manifest. It has no provider calls, no automatic quality score, no source writes and no overwrite mode. Only its clearly labeled navigation previews are resized.

```bash
python scripts/compare_image_fidelity.py \
  --image baseline=/path/to/original-baseline.png \
  --image candidate=/path/to/original-candidate.png \
  --request baseline=/path/to/baseline-request.json \
  --request candidate=/path/to/candidate-request.json \
  --region sky=0.40,0.03,0.35,0.15 \
  --region masonry=0.40,0.16,0.30,0.18 \
  --output /tmp/canary-fidelity-comparison-01
```

Omit `--request` when only images are available. Supplied request JSON is treated as **declared metadata**, not authenticated production evidence or proof that the image came from it. It separates prompt-only generation, reference-conditioned generation and explicit parent editing, and records input counts, hashes, dimensions and declared quality where present. It does not infer Draw quality from a missing field or claim a Codex HTTP endpoint. Pair report metadata with the actual usage/provenance record and request ID to establish production linkage.

Region coordinates are normalized `x,y,width,height` from the top left. Compare corresponding content, not arbitrary coordinates from different compositions. Native display means one raster pixel per CSS pixel at 100% browser zoom; Retina scaling still exists. ICC profiles are retained, EXIF orientation is not reapplied to derived crops, and originals remain authoritative for color review.

## Visual acceptance protocol (not executed)

First inspect existing original rasters, references, frozen requests and lineage with zero generation calls. Preserve those artifacts. Separate the two supplied screenshots from any genuine baseline/candidate experiment.

For an explicitly budgeted initial pilot, choose three representative cases: a dark painterly page, a brighter simpler page, and an intentionally heavily textured style proof. Generate each once on the baseline compiler and once on this PR with the same model, settings, reference bytes/order and approved source intent: six intentional requests, not automated retries. Use separate test projects as needed; do not edit a frozen request into a new submission. This is screening, not a reliable success-rate estimate.

If promising, repeat independent requests before making an efficacy claim. There is no seed-based pairing assumed. Add edit-chain and clean-parent comparisons as separate conditions. A prompt-only generation without references can be informative, but changes the conditioning task: it cannot alone prove that the edits endpoint caused degradation.

Blind-review native crops and final reading-size pages for unwanted texture, contour/face/hand legibility, preservation of intended medium, identity/scene continuity, and lettering quiet-space adherence. A smoother but stylistically wrong or less accurate page fails. Record accepted/attempted images, actual usage cost, latency and edit depth. Texture energy or a generic no-reference sharpness score is not a trustworthy automatic pass/fail criterion for watercolor, woodcut and stippled art.

The release gate is a convincing visual comparison with no loss of intended style or continuity. Unit/compiler tests establish wiring and invariants, **not** that an image model obeys the policy. Existing noisy images are not repaired by merging this PR; new renders and any source-proof replacement require explicit author action.

## Primary sources

[api-edit]: https://developers.openai.com/api/reference/resources/images/methods/edit
[prompting]: https://developers.openai.com/api/docs/guides/image-prompting
[generation]: https://developers.openai.com/api/docs/guides/image-generation
[sunburst]: https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst
[litellm-edit]: https://github.com/BerriAI/litellm/blob/v1.83.14-stable/litellm/llms/openai/image_edit/transformation.py
[litellm-main]: https://github.com/BerriAI/litellm/blob/v1.83.14-stable/litellm/images/main.py
