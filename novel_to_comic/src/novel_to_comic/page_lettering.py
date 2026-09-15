"""Provider-free lettering: measured layout, one SVG language, independent saves."""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import re
import unicodedata
from functools import lru_cache
from html import escape
from pathlib import Path

from PIL import Image, ImageFont

from novel_to_comic.models.lettering import (
    LetteringElementState,
    LetteringReservation,
    LetteringStyle,
    PageLettering,
    PageReservations,
    ReservationIntent,
    ResolvedText,
    RoleStyle,
)
from novel_to_comic.models.page import ComicPage, PinnedGeometry

COMPOSITOR_VERSION = "lettering-svg-1"
FONT_DIR = Path(__file__).parent / "fonts"


def digest(value) -> str:
    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()


def canonical_items(page: ComicPage):
    return {item.id: item for panel in page.content for item in panel.lettering}


def reservations_for_page(
    page: ComicPage, intents: dict[str, ReservationIntent] | None = None
) -> PageReservations:
    """Compile Plan hints without modifying the retained ComicPage schema.

    Existing semantic plans can seed coarse reservations deterministically. No
    panel raster authority is invented: rough regions are explicitly suggestions.
    """
    items = canonical_items(page)
    order = [key for key in page.reading_order if key in items]
    if intents is not None and set(intents) != set(items):
        raise ValueError(
            "every page lettering ID needs exactly one reservation; no foreign IDs"
        )
    result = []
    panels = sorted(page.content, key=lambda p: p.order)
    for index, panel in enumerate(panels):
        for offset, item in enumerate(panel.lettering):
            default = ReservationIntent(
                preferred_zone="top_left" if offset % 2 == 0 else "top_right",
                line_budget=max(1, min(30, math.ceil(len(item.text) / 26))),
                footprint="wide" if len(item.text) > 130 else "standard",
                speaker_entity_id=item.speaker_entity_id
                if item.speaker_entity_id in panel.entity_ids
                else None,
            )
            intent = intents[item.id] if intents is not None else default
            if (
                intent.speaker_entity_id
                and intent.speaker_entity_id not in panel.entity_ids
            ):
                raise ValueError(
                    "reservation speaker must be visible in its assigned panel"
                )
            if (
                intent.speaker_entity_id
                and intent.speaker_entity_id != item.speaker_entity_id
            ):
                raise ValueError("reservation cannot change the canonical speaker")
            if intent.tail_target and (
                item.kind not in {"dialogue", "thought"} or item.delivery != "onscreen"
            ):
                raise ValueError(
                    "only onscreen speech/thought reservations have visible tails"
                )
            result.append(
                LetteringReservation(
                    **intent.model_dump(),
                    lettering_item_id=item.id,
                    panel=panel.order,
                    order=order.index(item.id) + 1,
                )
            )
    return PageReservations(
        revision=1,
        page_number=page.page_number,
        comic_page_sha256=page.content_sha256,
        elements=sorted(result, key=lambda e: e.order),
    )


def style_preset(name: str, direction: str = "") -> LetteringStyle:
    style = LetteringStyle(preset=name, direction=direction)
    overrides = {
        "noir": {
            "font": "SpecialElite-Regular",
            "color": "#ffffff",
            "fill": "#202020",
            "outline": "#ffffff",
        },
        "manga": {"font": "MPLUS1p-Bold", "color": "#111111", "fill": "#ffffff"},
        "vintage": {
            "font": "EBGaramond-SemiBold",
            "fill": "#f5e9cc",
            "color": "#241d16",
        },
    }
    if name in overrides:
        style = style.model_copy(
            update={
                "caption": RoleStyle(**(style.caption.model_dump() | overrides[name]))
            }
        )
    return style


def initial_style(direction: str = "") -> LetteringStyle:
    name = next(
        (key for key in ("noir", "manga", "vintage") if key in direction.lower()),
        "literary",
    )
    return style_preset(name, direction)


def seed_lettering(
    page: ComicPage,
    reservations: PageReservations,
    style: LetteringStyle,
    aspect: float,
) -> PageLettering:
    if reservations.comic_page_sha256 != page.content_sha256:
        raise ValueError("lettering reservations are stale; rerun Plan")
    items = canonical_items(page)
    if {r.lettering_item_id for r in reservations.elements} != set(items):
        raise ValueError("lettering reservations do not match this page; rerun Plan")
    panels = sorted(page.content, key=lambda p: p.order)
    elements = []
    for reservation in reservations.elements:
        item = items[reservation.lettering_item_id]
        panel = next(p for p in panels if p.order == reservation.panel)
        row = panels.index(panel)
        area = panel.pinned_geometry or PinnedGeometry(
            x=0.035,
            y=0.035 + row * 0.93 / len(panels),
            width=0.93,
            height=0.93 / len(panels),
        )
        width = min(
            area.width * 0.92, 0.58 if reservation.footprint == "wide" else 0.35
        )
        height = min(
            area.height * 0.85,
            max(0.07, reservation.line_budget * 0.022 / aspect + 0.025),
        )
        offset = [i.id for i in panel.lettering].index(item.id)
        x = (
            area.x + 0.008
            if reservation.preferred_zone.endswith("left")
            else (
                area.x + area.width - width - 0.008
                if reservation.preferred_zone.endswith("right")
                else area.x + (area.width - width) / 2
            )
        )
        y = area.y + 0.008 + (offset // 2) * (height + 0.01)
        if reservation.preferred_zone.startswith("bottom"):
            y = area.y + area.height - height - 0.008
        bounds = reservation.bounds or PinnedGeometry(
            x=max(0, min(1 - width, x)),
            y=max(0, min(1 - height, y)),
            width=width,
            height=height,
        )
        elements.append(
            LetteringElementState(
                id=item.id,
                source_lettering_item_id=item.id,
                kind=item.kind,
                suggested_placement=bounds,
                placement=bounds,
                tail_target=reservation.tail_target,
                z_index=reservation.order,
            )
        )
    state = PageLettering(
        revision=1,
        page_number=page.page_number,
        comic_page_sha256=page.content_sha256,
        style=style,
        elements=elements,
    )
    return resolve_lettering(state, page, aspect)


def display_copy(
    element: LetteringElementState, state: PageLettering, page: ComicPage
) -> str:
    if state.locale in element.copies:
        return element.copies[state.locale]
    if state.locale:
        raise ValueError(
            f"Missing {state.locale} copy for {element.id}; enter a translation or switch locale"
        )
    item = canonical_items(page).get(element.source_lettering_item_id)
    return item.text if item else element.copies.get("", "")


@lru_cache(maxsize=256)
def _font(name: str, size: int):
    # Model allowlist prevents path traversal. Supersampling supports half-unit sizes.
    return ImageFont.truetype(str(FONT_DIR / f"{name}.ttf"), size)


@lru_cache(maxsize=8192)
def _has_glyph(name: str, character: str) -> bool:
    if character.isspace() or unicodedata.category(character) in {"Cf", "Mn", "Me"}:
        return True
    font = _font(name, 64)
    return bytes(font.getmask(character)) != bytes(font.getmask("\uffff"))


def _measure(text: str, style: RoleStyle, size: float) -> float:
    return (
        _font(style.font, round(size * 4)).getlength(text) / 4
        + max(0, len(text) - 1) * style.letter_spacing
    )


def _balanced_lines(
    text: str, style: RoleStyle, size: float, width: float, max_lines: int
):
    """Balanced whole-word wrapping with an explicit global line budget.

    Keep a solution for each line count: keeping only the cheapest suffix can
    incorrectly reject text that has a less-ragged but shorter feasible layout.
    Paragraph boundaries are hard breaks; CJK character boundaries are allowed.
    """
    if max_lines < 1:
        return None
    max_lines = min(80, max_lines)
    options = {0: (0.0, ())}
    for paragraph in text.split("\n"):
        matches = list(
            re.finditer(
                r"[\u3000-\u9fff\uac00-\ud7af]|[^\s\u3000-\u9fff\uac00-\ud7af]+",
                paragraph,
            )
        )
        tokens = [match.group() for match in matches]
        if len(tokens) > 500:
            return None
        if not tokens:
            paragraph_options = {1: (0.0, ("",))}
        else:
            n = len(tokens)
            edges = []
            for start in range(n):
                row = []
                for end in range(start + 1, min(n, start + 80) + 1):
                    line = re.sub(
                        r"\s+",
                        " ",
                        paragraph[matches[start].start() : matches[end - 1].end()],
                    )
                    used = _measure(line, style, size)
                    if used > width:
                        break
                    penalty = (width - used) ** 2
                    if end == n and end - start == 1 and n > 2:
                        penalty += width**2 * 0.7
                    row.append((end, line, penalty))
                edges.append(row)
            # No long-word splitting; expose genuine overflow to the author.
            if any(not row for row in edges):
                return None
            states = {0: (0.0, ())}
            paragraph_options = {}
            for count in range(1, min(max_lines, n) + 1):
                next_states = {}
                for start, (cost, lines) in states.items():
                    if start == n:
                        continue
                    for end, line, penalty in edges[start]:
                        candidate = (cost + penalty, (*lines, line))
                        if end not in next_states or candidate[0] < next_states[end][0]:
                            next_states[end] = candidate
                if n in next_states:
                    paragraph_options[count] = next_states[n]
                states = next_states
                if not states:
                    break
        combined = {}
        for previous_count, (previous_cost, previous_lines) in options.items():
            for count, (cost, lines) in paragraph_options.items():
                total = previous_count + count
                if total > max_lines:
                    continue
                candidate = (previous_cost + cost, (*previous_lines, *lines))
                if total not in combined or candidate[0] < combined[total][0]:
                    combined[total] = candidate
        options = combined
        if not options:
            return None
    return min(options.values(), key=lambda candidate: candidate[0])[1]


@lru_cache(maxsize=16)
def _font_sha(name: str) -> str:
    return hashlib.sha256((FONT_DIR / f"{name}.ttf").read_bytes()).hexdigest()


def layout_signature(element, state, page, aspect):
    style = element.style_override or getattr(state.style, element.kind)
    return digest(
        [
            COMPOSITOR_VERSION,
            _font_sha(style.font),
            aspect,
            state.locale,
            state.style.model_dump(),
            element.model_dump(exclude={"resolved"}),
            canonical_items(page).get(element.source_lettering_item_id).text
            if element.source_lettering_item_id in canonical_items(page)
            else None,
        ]
    )


def resolve_lettering(
    state: PageLettering, page: ComicPage, aspect: float
) -> PageLettering:
    if not math.isfinite(aspect) or not 0.1 <= aspect <= 10:
        raise ValueError("invalid page aspect ratio")
    if (
        state.comic_page_sha256 != page.content_sha256
        or state.page_number != page.page_number
    ):
        raise ValueError(
            "lettering belongs to an older Plan; explicitly reseed it before editing"
        )
    items = canonical_items(page)
    source_ids = {
        e.source_lettering_item_id for e in state.elements if e.source_lettering_item_id
    }
    if source_ids != set(items):
        raise ValueError(
            "source lettering must occur exactly once; hide an element instead of deleting its source link"
        )
    resolved = []
    for element in state.elements:
        signature = layout_signature(element, state, page, aspect)
        if element.resolved.signature == signature:
            resolved.append(element)
            continue
        style = element.style_override or getattr(state.style, element.kind)
        box = element.placement
        inset = style.padding + (
            box.width * 1000 / element.scale * 0.09
            if element.kind in {"dialogue", "thought"}
            else 0
        )
        width = box.width * 1000 / element.scale - 2 * inset
        height = box.height * 1000 * aspect / element.scale - 2 * style.padding
        reason = ""
        try:
            text = display_copy(element, state, page).replace("\r\n", "\n")
        except ValueError as exc:
            text, reason = "", str(exc)
        unsupported = sorted({ch for ch in text if not _has_glyph(style.font, ch)})
        if unsupported:
            reason = (
                reason
                or "Selected font does not cover these characters: "
                + " ".join(unsupported[:12])
            )
        if not text.strip() and not element.hidden:
            reason = reason or "Enter display copy or hide this element"
        lines = None
        # Fit feasibility is monotone in font size. Binary search bounded half-unit
        # steps instead of doing hundreds of shaping passes for oversized copy.
        sizes = [
            style.min_size + i * 0.5
            for i in range(int((style.max_size - style.min_size) / 0.5) + 1)
        ]
        if sizes[-1] < style.max_size:
            sizes.append(style.max_size)
        low, high = 0, len(sizes) - 1
        size = style.min_size
        while low <= high:
            mid = (low + high) // 2
            candidate_size = sizes[mid]
            candidate = (
                _balanced_lines(
                    text,
                    style,
                    candidate_size,
                    width,
                    max(0, int(height / (candidate_size * style.line_height))),
                )
                if width > 0 and height > 0
                else None
            )
            if candidate is not None:
                size, lines, low = candidate_size, candidate, mid + 1
            else:
                high = mid - 1
        if lines is None:
            size, lines = style.min_size, tuple(text.split("\n"))
            reason = (
                reason
                or "Text does not fit at minimum readable size; enlarge the box, shorten copy or hide it"
            )
        body_height = (
            len(lines) * size * style.line_height + 2 * style.padding
        ) * element.scale
        # Rotation/scale never silently clip an export at the page edge.
        angle = math.radians(element.rotation)
        bw = box.width * 1000
        bh = min(body_height, box.height * aspect * 1000)
        rx, ry = (
            (abs(bw * math.cos(angle)) + abs(bh * math.sin(angle))) / 2,
            (abs(bw * math.sin(angle)) + abs(bh * math.cos(angle))) / 2,
        )
        cx, cy = (box.x + box.width / 2) * 1000, box.y * aspect * 1000 + bh / 2
        if (
            cx - rx < -0.01
            or cx + rx > 1000.01
            or cy - ry < -0.01
            or cy + ry > 1000 * aspect + 0.01
        ):
            reason = (
                reason or "Rotated lettering extends beyond the page; move it inward"
            )
        layout = ResolvedText(
            lines=lines,
            widths=tuple(_measure(line, style, size) for line in lines),
            font_size=size,
            body_height=body_height / (1000 * aspect),
            overflow=bool(reason) and not element.hidden,
            reason=reason,
            signature=signature,
        )
        resolved.append(element.model_copy(update={"resolved": layout}))
    return PageLettering(
        **(
            state.model_dump(exclude={"content_sha256", "elements"})
            | {"elements": resolved}
        )
    )


@lru_cache(maxsize=16)
def _font_data(name):
    return base64.b64encode((FONT_DIR / f"{name}.ttf").read_bytes()).decode()


def _rounded_boundary(dx, dy, half_width, half_height):
    """Ray intersection with the actual rounded speech body, not its AABB."""
    length = math.hypot(dx, dy) or 1
    ux, uy = abs(dx) / length, abs(dy) / length
    radius = min(half_width, half_height)
    distance = min(half_width / (ux or 1e-12), half_height / (uy or 1e-12))
    px, py = ux * distance, uy * distance
    corner_x, corner_y = half_width - radius, half_height - radius
    if px > corner_x and py > corner_y:
        projection = ux * corner_x + uy * corner_y
        discriminant = projection**2 - corner_x**2 - corner_y**2 + radius**2
        distance = projection + math.sqrt(max(0, discriminant))
    return math.copysign(ux * distance, dx), math.copysign(uy * distance, dy)


def overlay_svg(
    state: PageLettering, aspect: float, *, embed_fonts: bool = True
) -> str:
    """Canonical standalone overlay; editor and export consume identical bytes.

    Only allowlisted font IDs, numeric geometry and escaped text enter markup.
    User copy cannot introduce scripts, remote assets, CSS or SVG attributes.
    """

    def n(value):
        return f"{value:.3f}".rstrip("0").rstrip(".") or "0"

    visible = sorted(
        (e for e in state.elements if not e.hidden), key=lambda e: e.z_index
    )
    fonts = sorted(
        {(e.style_override or getattr(state.style, e.kind)).font for e in visible}
    )
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 {n(aspect * 1000)}" width="100%" height="100%" aria-hidden="true"><defs><style>'
    ]
    for font in fonts:
        source = (
            f"data:font/ttf;base64,{_font_data(font)}"
            if embed_fonts
            else f"/static/fonts/{font}.ttf?v={_font_sha(font)}"
        )
        out.append(
            f'@font-face{{font-family:"{font}";src:url({source}) format("truetype");font-weight:400;}}'
        )
    out.append("</style></defs>")
    for e in visible:
        s = e.style_override or getattr(state.style, e.kind)
        x, y, w = (
            e.placement.x * 1000,
            e.placement.y * aspect * 1000,
            e.placement.width * 1000,
        )
        h = e.resolved.body_height * aspect * 1000
        cx, cy = x + w / 2, y + h / 2
        out.append(
            f'<g data-lettering-id="{escape(e.id, quote=True)}" transform="rotate({n(e.rotation)} {n(cx)} {n(cy)})">'
        )
        body = f'fill="{s.fill}" stroke="{s.outline}" stroke-width="{n(s.border)}" stroke-linejoin="round"'
        if e.kind == "thought":
            points = [
                (
                    cx
                    + (w / 2)
                    * (0.975 + 0.025 * math.cos(t * 12))
                    * math.copysign(abs(math.cos(t)) ** 0.5, math.cos(t)),
                    cy
                    + (h / 2)
                    * (0.975 + 0.025 * math.cos(t * 12))
                    * math.copysign(abs(math.sin(t)) ** 0.5, math.sin(t)),
                )
                for t in [i * math.tau / 80 for i in range(81)]
            ]
            path = "M" + " L".join(f"{n(a)} {n(b)}" for a, b in points) + "Z"
            out.append(f'<path d="{path}" {body}/>')
        elif e.kind != "sfx":
            radius = min(w / 2, h / 2) if e.kind == "dialogue" else s.radius
            out.append(
                f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{n(radius)}" {body}/>'
            )
        if e.tail_target and e.kind in {"dialogue", "thought"}:
            tx, ty = e.tail_target.x * 1000, e.tail_target.y * aspect * 1000
            # Tail targets remain in page space even when the balloon rotates.
            angle = math.radians(-e.rotation)
            px, py = tx - cx, ty - cy
            tx, ty = (
                cx + px * math.cos(angle) - py * math.sin(angle),
                cy + px * math.sin(angle) + py * math.cos(angle),
            )
            dx, dy = tx - cx, ty - cy
            bx, by = _rounded_boundary(dx, dy, w / 2, h / 2)
            ax, ay = cx + bx, cy + by
            if math.hypot(dx, dy) > math.hypot(bx, by):
                if e.kind == "thought":
                    for fraction, radius in ((0.2, 5), (0.5, 3.5), (0.8, 2)):
                        out.append(
                            f'<circle cx="{n(ax + (tx - ax) * fraction)}" cy="{n(ay + (ty - ay) * fraction)}" r="{radius}" {body}/>'
                        )
                else:
                    theta = math.atan2(dy, dx)
                    spread = math.atan2(6, math.hypot(bx, by) or 1)
                    a1, b1 = _rounded_boundary(
                        math.cos(theta - spread), math.sin(theta - spread), w / 2, h / 2
                    )
                    a2, b2 = _rounded_boundary(
                        math.cos(theta + spread), math.sin(theta + spread), w / 2, h / 2
                    )
                    root1, root2 = (
                        f"{n(cx + a1)} {n(cy + b1)}",
                        f"{n(cx + a2)} {n(cy + b2)}",
                    )
                    out.append(
                        f'<path d="M{root1} L{n(tx)} {n(ty)} L{root2} Z" fill="{s.fill}"/>'
                    )
                    out.append(
                        f'<path d="M{root1} L{n(tx)} {n(ty)} L{root2}" fill="none" stroke="{s.outline}" stroke-width="{n(s.border)}"/>'
                    )
        size = e.resolved.font_size * e.scale
        inset = s.padding * e.scale + (
            w * 0.09 if e.kind in {"dialogue", "thought"} else 0
        )
        anchor = {"left": "start", "center": "middle", "right": "end"}[s.align]
        text_x = {"left": x + inset, "center": cx, "right": x + w - inset}[s.align]
        for index, (line, width) in enumerate(
            zip(e.resolved.lines, e.resolved.widths, strict=True)
        ):
            if not line:
                continue
            # Center actual glyph bounds within the declared line cell. This avoids
            # assuming that every curated font shares the same Latin baseline.
            top, bottom = _font(s.font, round(size * 4)).getbbox(line, anchor="ls")[
                1::2
            ]
            baseline = (
                y
                + s.padding * e.scale
                + (size * s.line_height - (bottom - top) / 4) / 2
                - top / 4
                + index * size * s.line_height
            )
            out.append(
                f'<text x="{n(text_x)}" y="{n(baseline)}" text-anchor="{anchor}" font-family="{s.font}" font-size="{n(size)}" fill="{s.color}" stroke="{s.outline}" stroke-width="{n(s.stroke)}" paint-order="stroke fill" textLength="{n(width * e.scale)}" lengthAdjust="spacingAndGlyphs">{escape(line)}</text>'
            )
        out.append("</g>")
    out.append("</svg>")
    return "".join(out)


def composite_identity(image: bytes, state: PageLettering) -> str:
    fonts = sorted(
        {
            (e.style_override or getattr(state.style, e.kind)).font
            for e in state.elements
            if not e.hidden
        }
    )
    return digest(
        [
            hashlib.sha256(image).hexdigest(),
            state.content_sha256,
            state.locale,
            COMPOSITOR_VERSION,
            [_font_sha(font) for font in fonts],
        ]
    )


def compose_page(image: bytes, state: PageLettering) -> bytes:
    """Render the exact saved overlay using the existing local Chromium runtime."""
    from playwright.sync_api import sync_playwright

    with Image.open(io.BytesIO(image)) as art:
        width, height = art.size
    overflow = [e.id for e in state.elements if e.resolved.overflow and not e.hidden]
    if overflow:
        raise ValueError("Fix lettering overflow before export: " + ", ".join(overflow))
    svg = overlay_svg(state, height / width)
    art_url = "data:image/png;base64," + base64.b64encode(image).decode()
    html = f'<html><head><style>html,body{{margin:0;width:{width}px;height:{height}px;overflow:hidden}}img,svg{{position:absolute;inset:0;width:100%;height:100%}}</style></head><body><img src="{art_url}"/>{svg}</body></html>'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        try:
            context = browser.new_context(
                viewport={"width": width, "height": height}, device_scale_factor=1
            )
            context.route("**/*", lambda route: route.abort())
            page = context.new_page()
            page.set_content(html, wait_until="load")
            page.evaluate(
                "async () => { await document.fonts.ready; await Promise.all([...document.images].map(i => i.decode())); }"
            )
            return page.screenshot(type="png", animations="disabled")
        finally:
            browser.close()
