"""Panel-aware first placement for editable lettering; zero provider calls.

Seeds only. Panels come from the gutters of the base art (``panels.py``); the
speaker side comes from Plan's entity order, never from seeing a face. Draw
never receives Plan's reservation bounds, so they are a hint for which drawn
panel an item belongs to, not a position.

Reading order is kept: balloons in a panel run top to bottom, and a balloon
may sit beside its predecessor only when it is to its right and lower.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

from novel_to_comic.models.page import ComicPage, NormalizedPoint, PinnedGeometry

Side = Literal["left", "right"]
Rect = tuple[float, float, float, float]  # x, y, width, height in page space.

MARGIN_X = 0.02
MARGIN_Y = 0.014
GAP = 0.012
# Speakers' heads sit around the middle of a panel in The Egg's author tails
# (median 0.45 of panel height); left and right speakers near 1/3 and 2/3.
TAIL_DEPTH = 0.42
TAIL_X = {"left": 0.33, "right": 0.65}
FOOTPRINT_WIDTH = {"compact": 0.42, "standard": 0.6, "wide": 0.9, "tall": 0.45}


@dataclass(frozen=True)
class Entry:
    id: str
    role: str
    side: Side | None
    wants_tail: bool
    x: float  # Preferred top-left, before fitting inside the panel.
    y: float
    width: float
    height: float
    tail_hint: NormalizedPoint | None = None  # Plan's own pointer, if any.
    anchor: Rect | None = None  # The speaker's head, when the page read found it.
    avoid: tuple[Rect, ...] = ()  # Every head in the panel.


def usable(page: ComicPage, panels: Sequence[PinnedGeometry]) -> bool:
    """One undivided "panel" on a multi-panel plan means the art has no gutters."""
    return len(panels) >= 2 or len(page.content) == 1


def _contains(panel: PinnedGeometry, x: float, y: float) -> bool:
    return panel.x <= x <= panel.x + panel.width and panel.y <= y <= panel.y + panel.height


def _nearest(panels: Sequence[PinnedGeometry], x: float, y: float) -> int:
    for index, panel in enumerate(panels):
        if _contains(panel, x, y):
            return index
    return min(
        range(len(panels)),
        key=lambda i: max(panels[i].x - x, 0, x - panels[i].x - panels[i].width) ** 2
        + max(panels[i].y - y, 0, y - panels[i].y - panels[i].height) ** 2,
    )


def _seen_at(bounds: PinnedGeometry) -> tuple[float, float]:
    """Where a tight balloon seeded in these bounds shows: near their top-left.

    The engine anchors a tight box at its frame's top-left, so this, not the
    bounds' centre, is where authors saw Plan's reservation on the art.
    """
    return bounds.x + bounds.width / 4, bounds.y + bounds.height / 4


def assign_panels(page: ComicPage, panels: Sequence[PinnedGeometry]) -> dict[str, int]:
    """Drawn panel index per lettering item, never earlier than its predecessor.

    Plan's page-space bounds were written with the layout prose Draw followed,
    and on The Egg they pick the drawn panel more often than Plan's panel
    order does. Items without bounds use Plan's panel order, scaled when the
    art has a different number of panels.
    """
    reservations = {r.lettering_item_id: r for r in page.lettering_reservations or ()}
    planned, drawn = len(page.content), len(panels)
    result, previous = {}, 0
    for part in sorted(page.content, key=lambda part: part.order):
        for item in part.lettering:
            reservation = reservations.get(item.id)
            if reservation is not None and reservation.bounds is not None:
                candidate = _nearest(panels, *_seen_at(reservation.bounds))
            else:
                candidate = round((part.order - 1) * (drawn - 1) / max(1, planned - 1))
            previous = max(previous, min(candidate, drawn - 1))
            result[item.id] = previous
    return result


def speaker_sides(page: ComicPage) -> dict[str, Side | None]:
    """Left/right lean for onscreen speech, from Plan's order of visible speakers.

    A panel that shows two or more of the page's onscreen speakers stages the
    first-cited one left and the last-cited one right. A speaker keeps a side
    learned earlier on the page. Anything else has no lean. This only aims
    tails; it is a staging convention, not an observation of the art.
    """
    onscreen = [
        item
        for part in page.content
        for item in part.lettering
        if item.delivery == "onscreen" and item.speaker_entity_id is not None
    ]
    speakers = {item.speaker_entity_id for item in onscreen}
    learned: dict[str, Side] = {}
    sides: dict[str, Side | None] = {}
    for part in sorted(page.content, key=lambda part: part.order):
        visible = [entity for entity in part.entity_ids if entity in speakers]
        local: dict[str, Side] = {}
        if len(visible) >= 2:
            local = {visible[0]: "left", visible[-1]: "right"}
            learned.update(local)
        for item in part.lettering:
            if item.delivery != "onscreen" or item.speaker_entity_id is None:
                sides[item.id] = None
            else:
                sides[item.id] = local.get(item.speaker_entity_id) or learned.get(
                    item.speaker_entity_id
                )
    return sides


def _inner(panel: PinnedGeometry) -> tuple[float, float, float, float]:
    left, right = panel.x + MARGIN_X, panel.x + panel.width - MARGIN_X
    top, bottom = panel.y + MARGIN_Y, panel.y + panel.height - MARGIN_Y
    if right - left < 0.02 or bottom - top < 0.02:  # Sliver: use the whole panel.
        return panel.x, panel.y, panel.x + panel.width, panel.y + panel.height
    return left, top, right, bottom


def frame_size(reservation, panel: PinnedGeometry) -> tuple[float, float]:
    """Plan's reserved size (or its footprint), no larger than the panel.

    For tight boxes this is an upper bound; the engine shrinks it to the copy.
    """
    left, top, right, bottom = _inner(panel)
    if reservation.bounds is not None:
        width, height = reservation.bounds.width, reservation.bounds.height
    else:
        width = panel.width * FOOTPRINT_WIDTH[reservation.footprint]
        height = max(0.05, reservation.line_budget * 0.026 + 0.018)
    return min(width, right - left), min(height, bottom - top)


def preferred_origin(
    reservation, panels: Sequence[PinnedGeometry], index: int, width: float, height: float
) -> tuple[float, float]:
    """Plan's top-left, carried into the drawn panel it was assigned to.

    Bounds already inside that panel are kept. Bounds seen in another panel
    keep their relative position within the assigned one. Without bounds the
    preferred zone is applied to the panel. Onscreen speech starts at the
    panel's top, above the figures, as authors placed it on The Egg; Plan
    cannot see where heads are, so its vertical zone is not used for speech.
    """
    panel = panels[index]
    left, top, right, bottom = _inner(panel)
    bounds = reservation.bounds
    if bounds is not None:
        source = panels[_nearest(panels, *_seen_at(bounds))]
        x, y = bounds.x, bounds.y
        if source != panel:
            x = panel.x + (bounds.x - source.x) / source.width * panel.width
            y = panel.y + (bounds.y - source.y) / source.height * panel.height
    else:
        vertical, _, horizontal = reservation.preferred_zone.partition("-")
        x = {"left": left, "center": (left + right - width) / 2, "right": right - width}[horizontal]
        y = {"top": top, "middle": (top + bottom - height) / 2, "bottom": bottom - height}[vertical]
    if reservation.speaker_entity_id is not None:  # Plan keeps these onscreen only.
        y = top
    return x, y


def speaker_heads(
    page: ComicPage, panels: Sequence[PinnedGeometry], heads: Sequence, assigned: dict[str, int]
) -> tuple[dict[int, tuple[Rect, ...]], dict[str, Rect]]:
    """Heads per drawn panel, and the speaker's head for each onscreen line.

    A head labelled with the speaker's cast ID wins. An unlabelled head counts
    only when it is the panel's only head and the line's speaker is the only
    one speaking in that panel.
    """
    in_panel: dict[int, list] = {}
    for head in heads:
        index = _nearest(panels, head.x + head.width / 2, head.y + head.height / 2)
        in_panel.setdefault(index, []).append(head)
    voices: dict[int, set[str]] = {}
    for part in page.content:
        for item in part.lettering:
            if item.delivery == "onscreen" and item.speaker_entity_id:
                voices.setdefault(assigned[item.id], set()).add(item.speaker_entity_id)
    anchors: dict[str, Rect] = {}
    for part in page.content:
        for item in part.lettering:
            speaker = item.speaker_entity_id if item.delivery == "onscreen" else None
            local = in_panel.get(assigned[item.id], [])
            if speaker is None or not local:
                continue
            labelled = [h for h in local if h.entity_id == speaker]
            if not labelled and len(local) == 1 and local[0].entity_id is None \
                    and voices.get(assigned[item.id]) == {speaker}:
                labelled = local
            if labelled:
                head = max(labelled, key=lambda h: h.width * h.height)
                anchors[item.id] = (head.x, head.y, head.width, head.height)
    return (
        {index: tuple((h.x, h.y, h.width, h.height) for h in local) for index, local in in_panel.items()},
        anchors,
    )


def layout_page(
    page: ComicPage, panels: Sequence[PinnedGeometry], size_of, heads: Sequence = ()
) -> dict:
    """Arrange every item in its drawn panel; ``size_of(item, reservation, panel)``.

    ``heads`` (the page read's ObservedFigures) centre a speaker's balloon over
    their head and keep every balloon off faces; without them Plan's position
    and the speaker-order lean are used.
    """
    reservations = {r.lettering_item_id: r for r in page.lettering_reservations or ()}
    assigned = assign_panels(page, panels)
    sides = speaker_sides(page)
    avoid, anchors = speaker_heads(page, panels, heads, assigned)
    by_panel: dict[int, list[Entry]] = {}
    for part in sorted(page.content, key=lambda part: part.order):
        for item in part.lettering:
            index, reservation = assigned[item.id], reservations[item.id]
            width, height = size_of(item, reservation, panels[index])
            x, y = preferred_origin(reservation, panels, index, width, height)
            anchor = anchors.get(item.id)
            if anchor is not None:
                x = anchor[0] + anchor[2] / 2 - width / 2
            by_panel.setdefault(index, []).append(Entry(
                id=item.id, role=ROLE[item.kind], side=sides[item.id],
                wants_tail=wants_tail(item), x=x, y=y, width=width, height=height,
                tail_hint=reservation.tail_target, anchor=anchor,
                avoid=avoid.get(index, ()),
            ))
    layout = {}
    for index, entries in by_panel.items():
        layout.update(arrange(panels[index], entries))
    return layout


ROLE = {"dialogue": "speech", "caption": "caption", "thought": "thought", "sfx": "sfx"}


def wants_tail(item) -> bool:
    return item.kind in {"dialogue", "thought"} and item.delivery == "onscreen"


def _overlaps(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> bool:
    return a[0] < b[0] + b[2] and b[0] < a[0] + a[2] and a[1] < b[1] + b[3] and b[1] < a[1] + a[3]


def arrange(
    panel: PinnedGeometry, entries: Sequence[Entry]
) -> dict[str, tuple[PinnedGeometry, NormalizedPoint | None]]:
    """Fit entries (in reading order) inside one panel with the least movement.

    Each keeps its preferred spot when it fits. Otherwise it slides inside the
    panel, below an earlier balloon it would cover, and never above its
    predecessor unless it sits entirely to that balloon's right.
    """
    left, top, right, bottom = _inner(panel)
    placed: list[tuple[float, float, float, float]] = []
    stems: list[tuple[tuple[float, float], tuple[float, float]]] = []
    result = {}
    for entry in entries:
        width = min(entry.width, right - left)
        height = min(entry.height, bottom - top)
        x = max(left, min(entry.x, right - width))
        y = max(top, min(entry.y, bottom - height))
        bounds = (left, top, right, bottom)
        x, y = clear_of(x, y, width, height, entry.avoid, bounds)
        if placed:
            prev = placed[-1]
            y = max(y, prev[1] if x >= prev[0] + prev[2] else prev[1] + prev[3] * 0.5)
            for _ in placed:  # Settle below anything it would cover.
                blocking = [o for o in placed if _overlaps((x, y, width, height), o)]
                if not blocking:
                    break
                y = max(o[1] + o[3] for o in blocking) + GAP
            # Reading order may push it back onto a face: step sideways only.
            x, y = clear_of(x, y, width, height, entry.avoid, bounds, vertical=False)
        y = max(top, min(y, bottom - height))
        placed.append((x, y, width, height))
        rect = PinnedGeometry(
            x=max(0.0, min(1 - width, x)), y=max(0.0, min(1 - height, y)),
            width=width, height=height,
        )
        tail = None
        if entry.wants_tail and entry.anchor is not None:
            tail = toward_head(rect, entry.anchor)
            stems.append(_stem(rect, tail))
        elif entry.wants_tail:
            hint = entry.tail_hint
            # Plan's pointer was written blind to the art; keep it only when it
            # stays in this drawn panel and outside the balloon.
            keep = (
                hint is not None and _contains(panel, hint.x, hint.y)
                and not _contains(rect, hint.x, hint.y)
            )
            tail = hint if keep else _tail(panel, rect, entry.side)
            if tail is not None and not keep and any(
                _crosses(_stem(rect, tail), other) for other in stems
            ):
                tail = _tail(panel, rect, None)  # Crossed tails read as wrong speakers.
            if tail is not None:
                stems.append(_stem(rect, tail))
        result[entry.id] = (rect, tail)
    return result


def clear_of(
    x: float, y: float, width: float, height: float, heads: Sequence[Rect],
    bounds: tuple[float, float, float, float], *, vertical: bool = True,
) -> tuple[float, float]:
    """The nearest spot that covers no face, inside ``bounds``; else unchanged.

    Keep in parity with engine.mjs clearOfHeads.
    """
    if not any(_overlaps((x, y, width, height), head) for head in heads):
        return x, y
    left, top, right, bottom = bounds
    candidates = []
    for hx, hy, hw, hh in heads:
        candidates += [(hx - width - GAP, y), (hx + hw + GAP, y)]
        if vertical:
            candidates += [(x, hy - height - GAP), (x, hy + hh + GAP)]
    fitting = [
        (cx, cy) for cx, cy in candidates
        if left - 1e-9 <= cx and cx + width <= right + 1e-9
        and top - 1e-9 <= cy and cy + height <= bottom + 1e-9
        and not any(_overlaps((cx, cy, width, height), head) for head in heads)
    ]
    if not fitting:
        return x, y
    return min(fitting, key=lambda c: (c[0] - x) ** 2 + (c[1] - y) ** 2)


def toward_head(body: PinnedGeometry, head: Rect) -> NormalizedPoint:
    """Tail tip on the edge of the speaker's head nearest the balloon.

    Keep in parity with engine.mjs tailTowardHead.
    """
    hx, hy, hw, hh = head
    cx, cy = body.x + body.width / 2, body.y + body.height / 2
    px, py = min(max(cx, hx), hx + hw), min(max(cy, hy), hy + hh)
    if _contains(body, px, py):  # Balloon over the head: aim at its middle.
        px, py = hx + hw / 2, hy + hh / 2
    return NormalizedPoint(x=max(0.0, min(1.0, px)), y=max(0.0, min(1.0, py)))


def _stem(body: PinnedGeometry, tail: NormalizedPoint):
    return (body.x + body.width / 2, body.y + body.height / 2), (tail.x, tail.y)


def _crosses(a, b) -> bool:
    def turn(p, q, r):
        return (q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0])
    (p1, p2), (p3, p4) = a, b
    return turn(p1, p2, p3) * turn(p1, p2, p4) < 0 and turn(p3, p4, p1) * turn(p3, p4, p2) < 0


def _tail(panel: PinnedGeometry, body: PinnedGeometry, side: Side | None) -> NormalizedPoint | None:
    """Toward where a speaker's head usually is, outside the body, inside the panel."""
    inset = 0.006
    x = panel.x + panel.width * TAIL_X[side] if side else body.x + body.width / 2
    below = body.y + body.height + 0.02
    y = max(below, panel.y + panel.height * TAIL_DEPTH)
    limit = panel.y + panel.height - inset
    if y > limit:  # No room below the body: point sideways toward the speaker.
        y = min(limit, body.y + body.height * 0.6)
        room_right = panel.x + panel.width - inset - (body.x + body.width)
        room_left = body.x - panel.x - inset
        if side != "left" and room_right >= 0.02:
            x = body.x + body.width + min(0.06, room_right * 0.7)
        elif room_left >= 0.02:
            x = body.x - min(0.06, room_left * 0.7)
        elif room_right >= 0.02:
            x = body.x + body.width + min(0.06, room_right * 0.7)
        else:
            return None
    x = max(panel.x + inset, min(panel.x + panel.width - inset, x))
    return NormalizedPoint(x=max(0.0, min(1.0, x)), y=max(0.0, min(1.0, y)))
