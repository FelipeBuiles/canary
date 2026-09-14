"""Express existing panel fixtures using the detail writer's assignment contract."""

from copy import deepcopy


def detail_response(draft):
    value = deepcopy(draft)
    for page in value["pages"]:
        page["lettering_placements"] = {}
        for number, panel in enumerate(page["content"], 1):
            for item_id in panel.pop("lettering_ids", []):
                assert item_id not in page["lettering_placements"], item_id
                page["lettering_placements"][item_id] = number
    return value
