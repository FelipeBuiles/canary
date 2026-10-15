"""Lossless transport sheets for page references, with explicit source bindings."""

from __future__ import annotations

import hashlib
import io
import json

from PIL import Image, ImageDraw, ImageFont, ImageOps

from novel_to_comic.models.draw import PageReference


MAX_MEMBERS_PER_SHEET = 2
MAX_SHEET_PIXELS = 16_777_216
_LABEL_HEIGHT = 48
_GUTTER = 16


def reference_display_members(reference):
    """Show approved subjects and their existing thumbnails, not packaging JSON."""
    value = reference if isinstance(reference, dict) else reference.model_dump(mode="json")
    if not str(value.get("id", "")).startswith("reference-sheet-"):
        return (value,)
    manifest = json.loads(value["visual_anchor"])
    if manifest.get("format") != "lossless-reference-sheet-v1":
        raise ValueError("Unknown reference sheet format")
    return tuple(PageReference.model_validate(member["authority"]).model_dump(mode="json")
                 for member in manifest["members"])


def pack_page_references(references, images, slots, *, first_order=1):
    """Keep every authority; never crop, rescale, or synthesize subject pixels.

    Packed sheets take upload orders from ``first_order``, after any images
    the caller uploads ahead of the subject authorities.

    Frozen sheet metadata retains the original reference hashes and authorities.
    Prompt bindings map each original subject to its actual uploaded image/region.
    Requests that already fit retain their original bytes and metadata.
    """
    if len(references) != len(images):
        raise ValueError("Reference metadata and images must be one-to-one")
    if any(hashlib.sha256(data).hexdigest() != ref.content_sha256
           for ref, data in zip(references, images, strict=True)):
        raise ValueError("Reference bytes do not match their approved hashes")
    if len(references) <= slots:
        return tuple(references), tuple(images), {}
    if slots < 1 or len(references) > slots * MAX_MEMBERS_PER_SHEET:
        raise ValueError(
            f"This page needs {len(references)} references, exceeding the lossless sheet "
            f"capacity of {max(0, slots) * MAX_MEMBERS_PER_SHEET}. Choose a higher-capacity "
            "Draw model before starting an edition, or revise the book's page composition."
        )
    packed, payloads, bindings = [], [], {}
    offset = 0
    for index in range(slots):
        count = (len(references) - offset + slots - index - 1) // (slots - index)
        members = references[offset:offset + count]
        data = images[offset:offset + count]
        offset += count
        order = index + first_order
        if count == 1:
            packed.append(members[0].model_copy(update={"order": order}))
            payloads.append(data[0])
            bindings[members[0].id] = {"input_order": order}
            continue
        decoded = []
        for raw in data:
            try:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height > MAX_SHEET_PIXELS // MAX_MEMBERS_PER_SHEET:
                        raise ValueError("Approved reference is too large for a lossless sheet; no pixels were discarded.")
                    decoded.append(ImageOps.exif_transpose(image).convert("RGBA"))
            except OSError as exc:
                raise ValueError("Approved reference bytes are not a readable image. Rerun Cast before Draw.") from exc
        width = sum(image.width for image in decoded) + _GUTTER
        height = max(image.height for image in decoded) + _LABEL_HEIGHT
        if width * height > MAX_SHEET_PIXELS:
            raise ValueError("Reference sheet exceeds the lossless pixel budget; no references were dropped.")
        sheet = Image.new("RGBA", (width, height), "white")
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default(size=20)
        x = 0
        manifest = []
        for member, image in zip(members, decoded, strict=True):
            # Labels supplement exact prompt bindings; never cover source pixels.
            label = f"Reference {member.order}: {member.label or member.entity_id}"
            while label and draw.textlength(label, font=font) > image.width - 8:
                label = label[:-1]
            draw.text((x + 4, 8), label, fill="black", font=font)
            sheet.paste(image, (x, _LABEL_HEIGHT))
            bounds = {"x": x, "y": _LABEL_HEIGHT, "width": image.width, "height": image.height}
            # Prompt-facing: where the member sits on the sheet. Its source
            # digest stays in the sheet manifest, where provenance reads it.
            bindings[member.id] = {
                "input_order": order, "region_pixels": bounds,
                "sheet_width": width, "sheet_height": height,
            }
            manifest.append({"authority": member.model_dump(mode="json"), "region_pixels": bounds})
            x += image.width + _GUTTER
        buffer = io.BytesIO()
        sheet.save(buffer, format="PNG")
        encoded = buffer.getvalue()
        digest = hashlib.sha256(encoded).hexdigest()
        packed.append(PageReference(
            id=f"reference-sheet-{digest}", order=order, media_type="image/png",
            content_sha256=digest, entity_id=f"reference-sheet-{order}",
            label=f"Reference sheet {order}",
            visual_anchor=json.dumps({"format": "lossless-reference-sheet-v1", "members": manifest},
                                     ensure_ascii=False, sort_keys=True),
            continuity_guard="Transport packaging only. Preserve each member's separate identity and continuity authority.",
        ))
        payloads.append(encoded)
    return tuple(packed), tuple(payloads), bindings
