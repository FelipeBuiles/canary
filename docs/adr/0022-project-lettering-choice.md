# ADR 0022: Choose integrated or editable lettering at project creation

Status: Accepted, implemented 2026-09-20. Supersedes the editable-only new-project
policy of ADR 0021; its independent lettering and immutable artwork contracts remain.

Integrated lettering can produce a more visually cohesive page, while editable
lettering permits exact text corrections and translation without changing artwork.
New-project creation therefore asks explicitly for a mode and shows prepared,
labeled comparisons before submission. The choice is creation-only in this release:
switching requires a new project and new page generation, not raster conversion.

Both modes use the selected Draw model and its cost/reference limits. Integrated
mode gets a distinct versioned profile; existing edition profiles remain immutable,
and retained legacy profiles are not reauthorized for generation. Integrated pages
use canonical copy in Draw and export their original raster. Editable pages keep
text-free Draw, independent display lettering, and provider-free composition.

The public samples are controlled presentation studies made from reference-guided
clean art and manually matched software placement. They establish what the real
lettering renderer produces on that prepared art, not automatic reservation quality,
a same-model benchmark, or parity across every story, style, model, and language.
