"""Explicit fixtures for Plan's reservation-bearing authoring contract."""

from copy import deepcopy


def staging(panel):
    panel.setdefault("setting", {"location_entity_id": None, "environment_visible": False,
                                 "direction": "Background outside the frame."})
    panel.setdefault("physical_relationships", [])


def reservation(panel_number=None):
    value = {
        "preferred_zone": "top-left",
        "footprint": "standard",
        "line_budget": 3,
        "bounds": None,
        "speaker_entity_id": None,
        "tail_target": None,
    }
    return value if panel_number is None else {"panel_number": panel_number, **value}


def plan_response(draft):
    """Author reservations for legacy story fixtures; production never fills them."""
    value = deepcopy(draft)
    if not isinstance(value, dict):
        return value
    for page in value.get("pages", []):
        if not isinstance(page, dict):
            continue
        for panel in page.get("content", []):
            staging(panel)
            if "lettering_ids" in panel:
                panel.setdefault(
                    "lettering_reservations",
                    [
                        {"lettering_item_id": item_id, **reservation()}
                        for item_id in panel["lettering_ids"]
                    ],
                )
    return value


def detail_response(draft):
    value = deepcopy(draft)
    for page in value["pages"]:
        page["lettering_placements"] = {}
        for number, panel in enumerate(page["content"], 1):
            staging(panel)
            panel.pop("lettering_reservations", None)
            for item_id in panel.pop("lettering_ids", []):
                assert item_id not in page["lettering_placements"], item_id
                page["lettering_placements"][item_id] = reservation(number)
    return value


def with_reservations(page):
    """Canonical hybrid page fixture; source items remain unchanged."""
    from novel_to_comic.models.page import ComicPage

    value = page.model_dump() | {"content_sha256": ""}
    value["lettering_reservations"] = [
        {
            "lettering_item_id": item.id,
            **reservation(),
            "speaker_entity_id": (
                item.speaker_entity_id
                if item.delivery == "onscreen"
                and item.speaker_entity_id in panel.entity_ids
                else None
            ),
        }
        for panel in sorted(page.content, key=lambda part: part.order)
        for item in panel.lettering
    ]
    return ComicPage.model_validate(value)
