# Page details and change requests

Mode: Operate / Read. Keep the artwork primary and make an occasional revision straightforward.

## Changes
- Reader image reserves a visible loading area with no border around an unsized image, removing the brief vertical-line artifact. Failed loads offer explicit retry; source changes restore the loading state.
- Modal revision metadata is reduced to the displayed artwork revision; lighter view navigation and absent unavailable next-finding control reduce noise.
- Change editor starts with a labelled request field, focused on entry. Review changes incorporates typed wording directly, so adding to a list is optional.
- Only a fresh matching review exposes Generate revision, alongside the credit estimate and warnings. References and compiled instructions remain available in a disclosure.
- Request summaries wrap, selection targets are larger, and desktop editing has more room.
- Pending wording persists under the exact render target. Explicit stale-draft copying carries it as an unselected request without annotations.

## Verification
360 frontend tests across 64 files pass; production build and lint pass. New coverage checks image loading/error/retry/source changes, direct-input inclusion exactly once, preview freshness, queued locking, and pending-wording persistence and target isolation. Existing paid submission, annotation history, and draft tests remain passing. Independent review found no new blockers and identified pending-text loss, which was fixed and tested.

Desktop reader, mobile editor, and credit-confirmation fixtures inspected. Browser preview used existing project artwork with illustrative correction wording and a locally mocked estimate; no generation was submitted. Temporary fixture and copied assets removed. Detector found no issues. Existing DESIGN.md remains authoritative.

Previews: ../review/page-modal-reading.png, ../review/page-modal-changes-mobile.png, ../review/page-modal-confirmation.png.
