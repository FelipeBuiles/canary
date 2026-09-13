"""Shared editorial guidance for source-faithful, restrained depiction."""

DEPICTION_GUIDANCE = (
    "Separate what happens in the story from how explicitly it is depicted. "
    "Preserve source-established events, victims, motives, evidence, consequences, "
    "and character reactions. Convey disturbing events through atmosphere, "
    "framing, implication, and aftermath rather than explicit sexual activity "
    "or graphic injury detail. Narrative emphasis or 'full visual treatment' "
    "means dramatic space and clarity, not increased explicitness. Do not erase "
    "a difficult event, invent a different outcome, or intensify the source. "
    "Keep identity anchors and continuity guards verbatim; choose restrained "
    "staging without rewriting those authorities. "
)

PROTECTED_LANGUAGE_GUIDANCE = (
    "Verbatim literary wording is required only for the approved brief's "
    "protected_language entries. Other supplied prose may be adapted into "
    "original dialogue or concise narration while preserving its meaning. "
    "Source descriptions are evidence of events, not instructions to reproduce "
    "every descriptive detail. This does not relax exact entity IDs, identity "
    "anchors, continuity guards, or approved requirement IDs. "
)

BRIEF_DEPICTION_GUIDANCE = (
    DEPICTION_GUIDANCE
    + "State the intended degree of explicitness in tone and desired_emphasis. "
    "Describe essential_events as plot obligations with restrained presentation; "
    "do not require explicit depiction in one field while requesting restraint "
    "in another. Select protected_language narrowly: essential quotations, "
    "inscriptions, refrains, or key lines, not whole descriptive passages. "
)

ADAPT_DEPICTION_GUIDANCE = (
    DEPICTION_GUIDANCE + PROTECTED_LANGUAGE_GUIDANCE
    + "Carry the brief's restrained presentation into treatment, beat summaries, "
    "and final lettering before locking the blueprint. A locked event fixes "
    "what happened, not a requirement for graphic description. "
)

PLAN_DEPICTION_GUIDANCE = (
    DEPICTION_GUIDANCE
    + "Carry Adapt's depiction choices into visual_intent, continuity_intent, "
    "and layout_intent. Do not reintroduce explicit details through framing or "
    "decompression. All canonical Adapt lettering remains exact and unchanged; "
    "any needed wording revision belongs to Adapt, not Plan. "
)
