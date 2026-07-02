"""Resolve which appearance a character has at a given panel.

Character appearance changes mid-story (The Girl Without Hands: real hands →
stumps → silver → restored). Each change is a ``StateActivation`` at a
``StoryPosition``. This module answers one question — "what does this character
look like in this panel?" — by position lookup, with no fuzzy text matching.
That explicitness is what makes the old "washing her hands" → silver-hands-prop
leak structurally impossible.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from novel_to_comic.models.appearance import (
    AppearanceState,
    StateActivation,
    StoryPosition,
)

# Beat ids are formatted by s5_layout_plan._beat_id as "<scene_id>:beat_<NNN>".
# We recover the scene-relative beat ordinal from the trailing number group so
# this stays robust to the exact id format.
_TRAILING_INT_RE = re.compile(r"(\d+)(?!.*\d)")


@dataclass(frozen=True)
class ResolvedAppearance:
    """The look to use for one character in one panel."""

    state_id: Optional[str]  # None = the character's base look
    anchor: str  # self-contained appearance text to use
    state: Optional[AppearanceState]  # the active state, or None for base


def _position_key(position: StoryPosition, scene_order: Sequence[str]) -> tuple[int, int]:
    """Total order over story positions: (scene rank, beat). Unknown scenes
    sort last; ``beat=None`` (scene start) sorts before any numbered beat."""
    try:
        scene_rank = list(scene_order).index(position.scene_id)
    except ValueError:
        scene_rank = len(scene_order)
    return (scene_rank, position.beat or 0)


def _beat_ordinal(beat_id: str) -> Optional[int]:
    match = _TRAILING_INT_RE.search(beat_id or "")
    return int(match.group(1)) if match else None


def panel_position(panel, scene_order: Sequence[str]) -> StoryPosition:
    """The story position of a panel: its scene plus the LAST beat it covers.

    A panel reflects the end-state of the action it covers, so we use the
    maximum beat ordinal among ``panel.beat_ids``. Panels with no beat ids
    resolve to scene start.
    """
    ordinals = [
        o for o in (_beat_ordinal(b) for b in getattr(panel, "beat_ids", []) or []) if o is not None
    ]
    return StoryPosition(scene_id=panel.scene_id, beat=max(ordinals) if ordinals else None)


def active_state(
    base_anchor: str,
    states: Sequence[AppearanceState],
    timeline: Sequence[StateActivation],
    position: StoryPosition,
    scene_order: Sequence[str],
) -> ResolvedAppearance:
    """Return the appearance active at ``position``.

    Picks the activation with the greatest position ``<=`` ``position``; ties
    resolve to the later entry in ``timeline``. Falls back to the base look
    when no activation qualifies or an activation names an unknown state.
    """
    catalog = {s.id: s for s in states}
    pos_key = _position_key(position, scene_order)

    best_key: Optional[tuple[int, int]] = None
    best_act: Optional[StateActivation] = None
    for activation in timeline:
        key = _position_key(activation.at, scene_order)
        if key <= pos_key and (best_key is None or key >= best_key):
            best_key = key
            best_act = activation

    if best_act is None:
        return ResolvedAppearance(state_id=None, anchor=base_anchor, state=None)

    state = catalog.get(best_act.state_id)
    if state is None:
        return ResolvedAppearance(state_id=None, anchor=base_anchor, state=None)
    return ResolvedAppearance(state_id=state.id, anchor=state.visual_anchor, state=state)
