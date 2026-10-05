"""Preview another reference form on a recorded character or state sheet.

``sheet_form`` and ``sheet_formation`` restate a recorded ``figure`` sheet with
the production wording from ``reference_forms``, so an author can compare
layouts before changing a character's ``reference_form`` in the Story Bible.
The rewrite requires the turnaround sections it replaces and fails when the
recorded prompt no longer has them.
"""

from __future__ import annotations

from novel_to_comic import reference_forms

VARIANTS = ("sheet_form", "sheet_formation")
_FORMS = {"sheet_form": "form", "sheet_formation": "formation"}


def _replace_layout(lines: list[str], form: str) -> tuple[list[str], bool]:
    for state, layouts in ((False, reference_forms.CANONICAL_LAYOUTS), (True, reference_forms.STATE_LAYOUTS)):
        recorded = [f"- {line}" for line in layouts["figure"]]
        if recorded[0] in lines:
            index = lines.index(recorded[0])
            if lines[index:index + len(recorded)] != recorded:
                raise ValueError("The recorded sheet layout changed; record a current sheet")
            replacement = [f"- {line}" for line in layouts[form]]
            return [*lines[:index], *replacement, *lines[index + len(recorded):]], state
    raise ValueError("The recorded prompt is not a turnaround character sheet; record a current sheet")


def rewrite(prompt: str, variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError(f"Unknown sheet form variant: {variant}")
    form = _FORMS[variant]
    blocks = prompt.split("\n\n")
    constraints = next((i for i, b in enumerate(blocks) if b.startswith("Constraints\n")), None)
    direction = next((i for i, b in enumerate(blocks) if b.startswith("Scene direction\n")), None)
    if constraints is None or direction is None:
        raise ValueError("The recorded sheet prompt has no constraints or scene direction; record a current sheet")
    lines, state = _replace_layout(blocks[constraints].split("\n"), form)
    performance = f"- {reference_forms.PERFORMANCE['figure']}"
    lines = [f"- {reference_forms.PERFORMANCE[form]}" if line == performance else line for line in lines]
    blocks[constraints] = "\n".join(lines)
    if state:
        swaps = ((reference_forms.STATE_COMPOSITION["figure"], reference_forms.STATE_COMPOSITION[form]),
                 (reference_forms.STATE_DIRECTION["figure"], reference_forms.STATE_DIRECTION[form]))
    else:
        swaps = tuple(zip(reference_forms.CANONICAL_DIRECTION["figure"], reference_forms.CANONICAL_DIRECTION[form]))
    scene = blocks[direction]
    for recorded, replacement in swaps:
        if recorded not in scene:
            raise ValueError("The recorded scene direction changed; record a current sheet")
        scene = scene.replace(recorded, replacement)
    blocks[direction] = scene
    rewritten = "\n\n".join(blocks)
    if not state:
        identity = reference_forms.IDENTITY_DESIGN["figure"]
        if identity not in rewritten:
            raise ValueError("The recorded identity notes changed; record a current sheet")
        rewritten = rewritten.replace(identity, reference_forms.IDENTITY_DESIGN[form])
    return rewritten
