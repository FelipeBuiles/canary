"""Deterministic "restructured" prompts for Labs image comparisons.

Given a prompt the production compiler produced, restate the same request as:

1. a plain description of the picture first (panels in reading order),
2. reference images once, in upload order, with visual anchors, continuity
   guards and approved art direction quoted verbatim,
3. the project's style text verbatim, once,
4. exact lettering verbatim (integrated pages) or an artwork-only rule
   (editable pages),
5. short constraints stated once, without naming the artifacts to avoid.

Production's rendering-fidelity block, authority-chain prose, JSON payload and
off-canvas handles are dropped; ``required_verbatim`` lists the text a
restructured prompt must still carry word for word.
"""

from __future__ import annotations

import json
import re
from typing import Any

from novel_to_comic.compiled_request import STYLE_VARIATION_PREAMBLE, STYLE_WITH_REFERENCE_PREAMBLE
from novel_to_comic.rendering_fidelity import RENDERING_FIDELITY_CONSTRAINTS, RENDERING_FIDELITY_MARKER

_HANDLE = re.compile(r"\b(asset|subject)-([A-Z]+)\b")
_LETTERING = {
    "dialogue": "a speech balloon", "thought": "a thought balloon",
    "caption": "a narration caption", "sfx": "the sound effect",
}


def _handle_index(letters: str) -> int:
    index = 0
    for letter in letters:
        index = index * 26 + ord(letter) - 64
    return index


def page_payload(prompt: str) -> dict[str, Any]:
    """The structured payload every compiled complete-page prompt ends with."""
    start = prompt.index('{"reference_scope"')
    return json.loads(prompt[start:prompt.rindex("}") + 1])


def _style_only(style: str | None) -> str:
    return (style or "").split(RENDERING_FIDELITY_MARKER, 1)[0].strip()


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def required_page_verbatim(prompt: str) -> list[str]:
    payload = page_payload(prompt)
    required: list[str] = []
    for ref in payload["approved_page_references"]:
        required += [ref[key] for key in ("visual_anchor", "continuity_guard", "art_direction") if ref.get(key)]
    required += _paragraphs(_style_only(payload.get("project_style_direction")))
    for panel in (payload.get("exact_lettering") or {}).get("panels", []):
        required += [item["text"] for item in panel["lettering"]]
    return required


def restructure_page_prompt(prompt: str, *, width: int, height: int) -> str:
    payload = page_payload(prompt)
    references = payload["approved_page_references"]
    names: dict[str, str] = {}
    for ref in references:
        names.setdefault(ref["subject"], ref["appearance"])

    def named(text: str | None) -> str:
        return _HANDLE.sub(lambda match: names.get(match.group(0), match.group(0)), text or "").strip()

    page = payload["canonical_comic_page"]
    panels = sorted(page["content"], key=lambda panel: panel["order"])
    shape = _shape(width, height)
    count = len(panels)
    lines = [
        f"A complete {count}-panel comic page on a {shape} {width}×{height} canvas."
        + (f" Rhythm: {named(page.get('rhythm_intent'))}" if page.get("rhythm_intent") else ""),
    ]
    if payload.get("canonical_staging_and_layout"):
        lines.append(f"Layout: {named(payload['canonical_staging_and_layout'])}")
    lines.append("")
    for panel in panels:
        head = ", ".join(part for part in (panel.get("panel_role"), panel.get("camera")) if part)
        text = f"Panel {panel['order']} ({head}): {named(panel['visual_intent'])}"
        for subject in panel["visible_subjects"]:
            acting = subject.get("acting")
            if acting:
                facing = acting["facing"].replace(" (reader's screen direction)", "")
                parts = [f"facing {facing}", f"looking at {named(acting['gaze'])}", named(acting["expression"])]
                if acting.get("gesture"):
                    parts.append(named(acting["gesture"]))
                text += f" {names.get(subject['subject'], subject['subject'])}: {', '.join(parts)}."
        if panel.get("pinned_geometry"):
            geometry = ", ".join(f"{key} {value}" for key, value in panel["pinned_geometry"].items())
            text += f" Keep this panel exactly at {geometry}."
        lines.append(text)

    entries: list[tuple[int, str]] = []
    for ref in references:
        entry = f"{ref['appearance']}: \"{ref['visual_anchor']}\""
        if ref.get("continuity_guard"):
            entry += f" Continuity: \"{ref['continuity_guard']}\""
        if ref.get("art_direction"):
            entry += f" Approved design: \"{ref['art_direction']}\""
        entries.append((_handle_index(ref["image"].split("-", 1)[1]), entry))
    proof = payload.get("selected_style_proof")
    if proof:
        entries.append((_handle_index(proof["image"].split("-", 1)[1]), "The selected style proof."))
    lines += ["", "Reference images, in upload order:"]
    lines += [f"{index}. {entry}" for index, entry in sorted(entries)]
    lines.append(
        "The subject images show what each person, place and object looks like: keep their faces, "
        "builds, clothing and designs, but pose and light everyone for this scene."
    )
    if proof:
        index = _handle_index(proof["image"].split("-", 1)[1])
        lines.append(
            f"Image {index} shows only how to paint: its medium, palette, brushwork and how faces and "
            "bodies are drawn. Do not copy its people, poses, layout or lettering."
        )

    style = _style_only(payload.get("project_style_direction"))
    if style:
        lines += ["", "Style: " + style]

    lines.append("")
    if "exact_lettering" in payload:
        lettered = [panel for panel in payload["exact_lettering"]["panels"] if panel["lettering"]]
        if not lettered:
            lines.append("This page has no lettering: no text, balloons, captions or sound effects.")
        else:
            lines.append(
                "Lettering: letter exactly these strings, each once, in this reading order, "
                "spelled and capitalized exactly as written:"
            )
            for panel in payload["exact_lettering"]["panels"]:
                items = []
                for item in panel["lettering"]:
                    phrase = _LETTERING.get(item["kind"]) or str(item["kind"])
                    speaker = names.get(item.get("speaker_entity_id") or "", item.get("speaker"))
                    if item.get("delivery") == "onscreen" and speaker:
                        phrase += f" with its tail to {speaker}"
                    elif item.get("delivery") == "offscreen":
                        phrase += " from off-panel, with no tail"
                    items.append(f"{phrase}: \"{item['text']}\"")
                lines.append(f"Panel {panel['panel']}: " + ("; then ".join(items) if items else "no lettering."))
            lines.append("No other text, labels or signatures anywhere on the page.")
    else:
        lines.append(
            "Artwork only: draw no speech or thought balloons, captions, sound effects or other "
            "text, and leave no empty spaces for them; lettering is added later. Real signs in "
            "the scene are fine."
        )
    return "\n".join(lines).strip()


def _shape(width: int, height: int) -> str:
    return "portrait" if height > width else "landscape" if width > height else "square"


def asset_sections(prompt: str) -> dict[str, str]:
    """Split a compiled Style or Cast prompt into its titled sections."""
    sections: dict[str, str] = {}
    title = None
    for block in prompt.split("\n\n"):
        head, _, body = block.partition("\n")
        if body and not head.startswith("-"):
            title = head.strip()
            sections[title] = body.strip()
        elif title:
            sections[title] += "\n\n" + block.strip()
    return sections


def _asset_style(sections: dict[str, str]) -> str:
    style = sections.get("Style", "")
    for preamble in (STYLE_WITH_REFERENCE_PREAMBLE, STYLE_VARIATION_PREAMBLE):
        if style.startswith(f"{preamble}: "):
            style = style.removeprefix(f"{preamble}: ")
    return style.strip()


def _style_parts(style: str) -> list[str]:
    parts = re.split(r"(?<=\.)\s+(?=[A-Z][A-Z ]* — )", style)
    return [part.strip() for part in parts if part.strip()]


def _anchors(sections: dict[str, str]) -> list[tuple[str, str, str]]:
    """(name, entity id, anchor) for each protected anchor line."""
    anchors = []
    for line in sections.get("Protected anchors", "").splitlines():
        match = re.match(r"(.+?) \[([^ /\]]+)[^\]]*\]: (.+)", line.strip())
        if match:
            anchors.append((match.group(1), match.group(2), match.group(3)))
    return anchors


def required_asset_verbatim(prompt: str) -> list[str]:
    sections = asset_sections(prompt)
    required = [anchor for _, _, anchor in _anchors(sections)]
    required += _style_parts(_asset_style(sections))
    required += re.findall(r'"([^"]+)"', sections.get("User constraint notes", ""))
    return required


def restructure_asset_prompt(prompt: str, references: list[dict[str, Any]], *, width: int, height: int) -> str:
    """``references``: role, role_label and entity_id per wire reference, in order.

    The canvas line keeps the requested size in the prompt: routes that take no
    size parameter (Codex) only learn it from the text, as with production.
    """
    sections = asset_sections(prompt)
    anchors = _anchors(sections)
    names = {entity: name for name, entity, _ in anchors}
    scene = {}
    subject_lines = []
    for line in sections.get("Scene direction", "").splitlines():
        key, _, value = line.partition(": ")
        if key in {"Composition", "Visual brief"}:
            scene[key] = value.strip()
        elif value:
            subject_lines.append(f"{key}: {value.strip()}")
    lines = [" ".join(part for part in (scene.get("Composition"), scene.get("Visual brief")) if part)]
    lines.append(f"Canvas: {_shape(width, height)} {width}x{height}.")
    lines += subject_lines
    if anchors:
        lines += ["", "Who and what appears:"]
        lines += [f"- {name}: \"{anchor}\"" for name, _, anchor in anchors]
    if references:
        lines += ["", "Reference images, in upload order:"]
        for index, ref in enumerate(references, 1):
            if ref["role"] == "style":
                lines.append(
                    f"{index}. Shows only how to paint: the same medium, brushwork, palette, lighting and "
                    "level of finish. Take only the painting style, not its subjects or layout."
                )
            else:
                subject = names.get(ref.get("entity_id") or "", ref.get("role_label") or ref["role"])
                lines.append(f"{index}. Shows {subject}: keep its identity and design.")
    style = _asset_style(sections)
    if style:
        lines += ["", "Style: " + style]
    fidelity = tuple(constraint.split(":", 1)[0] for constraint in RENDERING_FIDELITY_CONSTRAINTS)
    constraints = [
        line.strip() for line in sections.get("Constraints", "").splitlines()
        if line.strip().startswith("-") and not line.strip("- ").startswith(fidelity)
    ]
    if constraints:
        lines += ["", "Requirements:", *constraints]
    if sections.get("User constraint notes"):
        lines += ["", sections["User constraint notes"]]
    return "\n".join(lines).strip()
