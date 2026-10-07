# Local crop OCR experiment

**Status: Current, experimental and disabled by default.** The pilot adds a
provider-free PaddleOCR second read. Production dependencies and deployment
configuration do not enable it.

## What is being tested

The existing page reader is a blind vision-model transcription. Its typed
observations contain text and geometry, **no recognition confidence score**.
The validator compares those observations with canonical copy. A mismatch is
therefore the trigger for this pilot; a model-generated confidence number would
not establish transcription accuracy.

Integrated and retained baked editions can opt into a second read of each
unmatched observation's tight region, cropped from the saved base artwork at
its original resolution. Paddle receives only pixels: neither the canonical
copy nor the first transcription. Hybrid editions keep their existing
unwanted-lettering check and skip this canonical-copy experiment.

The pilot uses the English PP-OCRv5 mobile detector and recognizer, pinned by
`scripts/ocr-experiment-requirements.txt`. Paddle returns detected boxes, text
and recognition scores. Fragments on the same physical row are joined left to
right; each row retains its weakest fragment's score. The experimental 0.95
cutoff is a gating heuristic, not a calibrated probability. Each unmatched
observation gets its own verdict: a strong close-up read that differs from the
first read **disagrees** (the finding is uncertain); a matching one **agrees**
(the possible difference stands). Low scores, no readable text, missing
regions, exceeded budgets and reader failures are inconclusive. The page status
is `disagrees` when any line disagrees, `agrees` only when every line agrees,
and otherwise `inconclusive`. Unmatched observations come from the validator's
own exact-match comparison; a page whose only finding is missing text has
nothing to read close up and gets no crop evidence.

Both transcriptions remain evidence; the primary observations and canonical
copy are unchanged. The pilot neither resolves findings nor certifies artwork.
The UI shows each line's first read, close-up read and verdict, with an
uncertain title when needed.
Matching observations do not start the native worker. The pilot cannot detect
an error where the first read already matches canonical copy incorrectly.

## Run locally

From the repository root, prepare an isolated environment and download the
models once. These commands require network access only for setup:

```sh
uv venv --python novel_to_comic/.venv/bin/python work/ocr-experiment/.venv
uv pip install --python work/ocr-experiment/.venv/bin/python -r scripts/ocr-experiment-requirements.txt
work/ocr-experiment/.venv/bin/python scripts/prepare_crop_ocr_models.py --output work/ocr-experiment/models
```

Write a manifest with human-labelled saved artwork. `box` is normalized
`[x, y, width, height]` around one lettering region. `expected` is script copy;
`actual` is a human transcription of the pixels and defaults to `expected`.
`primary` is the first reader's captured output. For a deliberate artwork typo,
`actual` should differ from `expected`. These labels are for offline scoring
and crop selection, never input to Paddle:

```json
[
  {
    "id": "caption-1",
    "image": "/absolute/path/to/saved-artwork.png",
    "box": [0.1, 0.1, 0.8, 0.2],
    "expected": "Jimmy Robbons was always nuts on mountain climbing.",
    "actual": "Jimmy Robbons was always nuts on mountain climbing.",
    "primary": "Jimmy Robbins was always nuts on mountain climbing."
  }
]
```

Run without a gateway, development server or provider requests:

```sh
CANARY_CROP_OCR_CACHE="$PWD/work/ocr-experiment/cache" \
  novel_to_comic/.venv/bin/python scripts/ocr_crop_experiment.py \
  --manifest work/ocr-experiment/manifest.json \
  --models work/ocr-experiment/models \
  --python "$PWD/work/ocr-experiment/.venv/bin/python" \
  --output work/ocr-experiment/run-1
```

The output directory holds typed crop reports, original image copies,
`results.json` and child-process CPU/RAM metrics. Source artwork and projects
are untouched. Identical inputs reuse reports, including inconclusive reports.
Use a fresh output directory for an intentional new offline attempt.

For a provider-free resource and contention test, use the same prepared inputs
with the load harness. It verifies lazy startup and report reuse, then measures
fresh serial reads, 1/4/16 simultaneous pages, one/six crops per page, and a
90-second sustained run. Multi-crop cases repeat a known region and are workload
fixtures, not additional accuracy examples:

```sh
CANARY_CROP_OCR_CACHE="$PWD/work/ocr-experiment/cache" \
  novel_to_comic/.venv/bin/python scripts/ocr_crop_benchmark.py \
  --manifest work/ocr-experiment/pilot-manifest.json \
  --models work/ocr-experiment/models \
  --python "$PWD/work/ocr-experiment/.venv/bin/python" \
  --output work/ocr-experiment/benchmark-1 \
  --label local-host
```

Use a fresh output directory; the harness refuses an existing one so cached
reports cannot masquerade as new inference. `--worker /path/to/shadow_worker.py`
can compare an experimental worker without changing the app; its source bytes
are included in the reader fingerprint. Native startup failure stops the load
test after its pilot, with diagnostic reports and metrics preserved.

To enable the already-implemented app integration on a future local server
start, set these variables in the backend environment:

```sh
CANARY_CROP_OCR_ENABLED=1
CANARY_CROP_OCR_MODELS=/absolute/path/to/work/ocr-experiment/models
CANARY_CROP_OCR_PYTHON=/absolute/path/to/work/ocr-experiment/.venv/bin/python
CANARY_CROP_OCR_CACHE=/absolute/path/to/work/ocr-experiment/cache
```

Saved first-pass evidence can be revalidated with the existing free Pages text
check recovery. The validator version includes the worker code, model files,
runtime package versions and crop policy, so enabling the pilot reuses paid
observations while adding local evidence. Existing author dismissals survive
an evidence refresh.

## Bounds and deployment implications

There is one persistent, serialized native worker **per backend process**,
with one CPU thread. Imports and models live in that subprocess, and validation
runs off the API event loop. A page gets at most six crops, 3 million pixels
per crop, 24 million pixels per source image, and a 30-second read budget
including queue wait. Worker startup has its own 120-second budget and restarts
the request clock. A stalled worker is killed. Busy, failed or timed-out reads
are retryable: their report is not saved, the analysis is marked
`:crop-incomplete` (still shown as checked) and the next provider-free
revalidation repeats only the close-up pass. Size and geometry limits are final.
A failed optional configuration is remembered per setting and logged once. Optional dependency/configuration failures preserve the
original checker.

On Lightsail this would be ordinary CPU inference. It requires a Linux CPU
wheel/runtime, model files provisioned in the image or a mounted read-only
directory, and a writable temporary cache. Runtime downloading is unnecessary.
The current read-only container can use `/tmp` for that cache. Its single-owner
API process also hosts the job worker, so the 16 concurrent operations share
one crop reader. CPU and memory headroom must be measured before enabling it.
No GPU or external inference
endpoint is required. Burst CPU limits still apply to the instance.

Native dependencies, offline read-only-container startup and contention were
tested on the existing Lightsail host on October 7, 2026. The stock image lacks
`libgomp.so.1`; an isolated Linux OCR runtime also needs Debian `libgomp1`.
With that library supplied, the pinned models initialize offline. The original
worker settings exceed the page read budget under concurrency; see the
[measured hardware evidence](../reviews/2026-10-07-ocr-lightsail-benchmark.md)
for resource limits, workload outcomes and deployment implications.
The Python environment occupies about 832 MB on the pilot Mac; model
files occupy about 12 MB. There is no additional per-image provider charge,
but memory and sustained CPU are material deployment costs.

## Local evidence — October 6, 2026

The reported screenshot was used with the primary transcription captured from
its UI, without repeating the paid first pass. Paddle read the complete caption
correctly, including **Robbons**, and disagreed with **Robbins**. A synthetic
caption actually spelling the name **Robbins** was also read correctly and
kept flagged against the script. A synthetic correct caption disagreed with
the simulated misread, and already matching copy skipped the crop worker.

| Case | Close-up result | Worker assessment | Time |
|---|---|---|---|
| Reported screenshot | Robbons, full caption correct | Disagrees | 4.02 s, including startup |
| Synthetic actual spelling error | Robbins, full caption correct | Agrees with first read | 1.98 s |
| Synthetic false positive | Robbons, full caption correct after whitespace normalization | Disagrees | 1.88 s |
| Matching copy | No second read needed | No crop requested | Under 1 ms |

Peak native child RSS was about **876 MB**, with 7.47 CPU seconds across the
three reads plus initialization. These are Mac measurements, not Lightsail
benchmarks. The small English sample demonstrates this failure mode and
preservation of a real typo; it does not establish general accuracy, a calibrated
confidence threshold or performance on stylized balloons and other languages.
The [Linux resource benchmark](../reviews/2026-10-07-ocr-lightsail-benchmark.md)
is now recorded. Broader human-labelled artwork, a deployment-ready optional
runtime and acceptable contention behavior are still required before production
enablement.

Paddle's [official OCR pipeline documentation](https://www.paddleocr.ai/latest/en/version3.x/pipeline_usage/OCR.html)
describes CPU execution and `rec_texts`, `rec_scores` and box outputs.
