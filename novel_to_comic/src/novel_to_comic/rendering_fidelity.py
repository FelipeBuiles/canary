"""Shared, medium-preserving surface guidance compiled BEFORE request freezing.

This is a prompting mitigation, not a denoiser or a claim that artifacts can be
reliably detected from pixels. Intentional grain, stippling, distress and other
selected textures remain art direction. Never append this in a transport: the
exact prompt, its budget and its hashes must include it before submission.
"""

RENDERING_FIDELITY_MARKER = "RENDERING FIDELITY — v1"

RENDERING_FIDELITY_CONSTRAINTS: tuple[str, ...] = (
    "Surface fidelity: preserve the selected medium and deliberate texture, including "
    "authored grain, granulation, stippling, hatching or distress. Keep marks material-specific "
    "and subordinate to readable forms; maintain coherent tonal areas where the selected "
    "style calls for them. Do not smooth away intentional marks or change the chosen medium.",
    "Detail hierarchy: keep focal contours legible at the intended viewing size. Vary mark "
    "scale with material and depth rather than spreading the same high-contrast speckles, "
    "cellular mottling or worm-like patches across unrelated surfaces. This targets "
    "unrequested digital artifacts, not explicitly chosen artistic texture.",
    "Reference fidelity means intentional design and medium, not incidental pixel defects. "
    "For a new image, reconstruct surfaces without amplifying noise or compression artifacts "
    "in supplied references. For an edit, keep untouched artwork and composition unchanged; "
    "confine surface cleanup to the authorized change. Never add another grain layer merely "
    "because a reference or edit parent is already textured.",
)

RENDERING_FIDELITY_BLOCK = (
    RENDERING_FIDELITY_MARKER + "\n" + "\n".join(RENDERING_FIDELITY_CONSTRAINTS)
)
