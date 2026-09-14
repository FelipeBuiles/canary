# OCR alternatives for comic lettering

**Status: Proposed.** Research checked 2026-09-14. No alternative engine was
executed, no paid calls were made, and no comic accuracy comparison is claimed.
This note evaluates candidate interfaces, not current Canary behavior.

## Recommendation

Make automated lettering review advisory until it demonstrates useful precision
on saved Canary pages. A checker error or refusal means “not checked,” not an
artwork defect. Retain human review and distinguish a suspected discrepancy from
a confirmed error. Replacing a model alone cannot fix an overly strict gate.

If automated review remains useful, evaluate Google Cloud Vision document text
detection first as a hosted candidate, or PaddleOCR's conventional OCR pipeline
as a local candidate. Azure Read is a reasonable additional candidate when Azure
is already available. This ordering is an implementation judgment, not an
accuracy ranking. Another general multimodal model can be a comparison baseline;
do not assume a larger model will justify mandatory verification.

## What the dedicated interfaces provide

| Candidate | Documented output | Implication for evaluation |
| --- | --- | --- |
| Google Cloud Vision `DOCUMENT_TEXT_DETECTION` | Page/block/paragraph/word/symbol hierarchy; bounding boxes and confidence fields in the response schema. | Can preserve local text evidence and show the exact disputed region. [Tutorial](https://docs.cloud.google.com/vision/docs/fulltext-annotations), [response schema](https://docs.cloud.google.com/vision/docs/reference/rest/v1/AnnotateImageResponse). |
| Azure Document Intelligence Read | Printed and handwritten text as lines and words, word polygons and confidence. | Can highlight individual words and retain uncertainty. [Read documentation](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/read?view=doc-intel-4.0.0). |
| PaddleOCR general OCR pipeline | Detected polygons, recognized text, recognition scores, configurable filtering, and local Python inference. | Can run a reproducible local extraction experiment without a hosted generative-model call; deployment and model setup remain necessary. Pin package and model versions rather than using changing defaults. [Pipeline documentation](https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html). |

These schemas do not establish comic-specific accuracy or guarantee correct
balloon grouping, speaker assignment, panel boundaries, or reading order.
Treat mapping words into Adapt's lettering units as a separate inference problem.
An OCR confidence score is not evidence that the entire page is correct; a high
recognition score also cannot prove no text was missed during detection.

## A narrower task worth testing

1. Extract visible text without supplying expected dialogue to the recognizer.
   Keep positions and uncertainty. Compare the extracted evidence with Adapt
   separately, so the transcription is not encouraged to repeat its answer key.
2. Match text regions to expected lettering units while tolerating wrapping,
   whitespace and typography. Preserve substantive differences such as missing
   words, names and negation. Do not mark wrong wording correct with broad fuzzy
   matching.
3. Report a small set of reviewable discrepancies with image crops and expected
   versus observed text. Missing detections, ambiguous grouping and provider
   failures should remain inconclusive rather than fail the artwork.
4. Evaluate saved pages that humans have transcribed, including known false
   positives, stylized sound effects, small lettering, multiple balloons and
   pages with real mistakes. Measure issue precision, real-error recall,
   inconclusive rate, review time, latency and cost. Character accuracy alone
   does not measure whether the checker creates useful review work.

The value threshold is whether confirmed errors caught outweigh false alarms and
review effort. If the small evaluation cannot demonstrate that, leave automated
OCR off by default. Even successful text recognition cannot certify composition,
identity continuity or other visual quality.
