# Remaining pages polish

Mode: Operate / Experience. Extend Living Ink to the remaining visitor and studio entry points. DESIGN.md remains authoritative.

Library keeps its existing cover cards and first-run invitation, replaces the decorative route card with a production count, and adds title/author search with result feedback and a recoverable empty state. The mobile heading is compact, and new-production dialogs can scroll within short viewports.

Sign-in, signup and password recovery gain clearer form hierarchy, focus states, pending guards and recoverable transport errors. Password reset keeps its existing session gate and minimum length, with confirmation before updating. Legal pages use readable paper styling, active document navigation and a comfortable reading measure; legal text and dates are unchanged. The missing-page screen provides a clear route back. Homepage changes focus on readable labels, mobile touch targets and sticky-header anchor offsets, preserving its composition and copy.

Labs receives readable labels, clearer section hierarchy, accessible input labels, keyboard-scrollable results, and retry states for load failures. Experiment payloads and paid actions are unchanged. Development-only Backoffice and PrimitiveReference are outside this user-facing pass.

Desktop/mobile fixtures inspected for Library, sign-in, homepage and Labs; mobile signup, legal and 404 also inspected. Password reset session/confirmation flow is covered by mocked tests. Previews are ../review/final-*.png. No authentication, generation, purchasing or destructive actions were submitted during preview. Temporary preview files removed. Design detector returned no findings for Library, auth, homepage, legal, 404 and Labs.

Verification: 382 frontend tests across 68 files pass, including search, auth recovery/session guards, and Labs retry regressions. Production build, lint, and diff checks pass.
