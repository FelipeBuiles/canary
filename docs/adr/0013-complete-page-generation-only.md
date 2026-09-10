# ADR 0013: Complete-page generation only

**Status:** Accepted  
**Date:** 2026-07-25

## Decision

Draw generates complete lettered comic pages as the only production rendering
path. Every initial generation, retry, or targeted correction produces a new
complete page-render revision tied to a canonical ComicPage revision.

Canary does not retain panel-by-panel generation and deterministic page
assembly as a production fallback. Models that cannot reliably generate the
required complete page are unavailable to Draw through capability gating.

One page-generation model and capability profile is fixed for an entire book
edition. Draw does not silently route individual pages or corrections to
different providers. If the selected model cannot produce a valid correction
within its allowed attempts, Canary surfaces the failure. Choosing another
model creates an explicitly regenerated edition rather than a mixed-provider
book.

The submission-attempt budget applies within one authorized action, not across
the page's lifetime. An explicit user retry authorizes a new action with the
same edition profile and preserves the previous request in its retry lineage.
The lineage attempt number is an audit counter, not a provider capability
limit. Draw currently submits once per action and never automatically retries
an ambiguous image call. A saved unfinished result must be recovered before
new page input can be submitted.

Panel images may be derived by cropping a completed page for review,
accessibility, analysis, or issue localization. A crop is evidence about its
page render; it is not an independently generated asset, a replacement panel,
or an input to page assembly.

## Consequences

The migration deletes the parallel panel-rendering architecture, including
per-panel generation modes, aspect requests, retry chains, prompt files,
acceptance state, replacement-panel assembly, crop-fit status, and fallback
selection between page and panel pipelines.

Targeted model editing remains allowed when a provider supports it, but its
output contract is always a complete revised page. Render provenance records
the parent page revision and correction request.

Finish never implements a deterministic creative fallback. It may normalize
production properties and coordinate correction requests, but only Draw
creates revised artwork or lettering pixels.
