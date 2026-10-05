from novel_to_comic.content_triggers import find_content_triggers


def _prompt(anchor: str, style: str = "flat inks", direction: str = "") -> str:
    sections = [
        "Constraints\n- no nudity or gore beyond what the story states",
        f"Secondary style notes\n{style}",
        f"Protected anchors\nSphinx [prop / canonical]: {anchor}",
    ]
    if direction:
        sections.append(f"Your art direction\n{direction}")
    return "\n\n".join(sections)


def test_names_the_phrase_its_category_and_where_it_was():
    [trigger] = find_content_triggers(_prompt("wooden sphinx carving, bare womanly torso blending into a lioness body"))
    assert trigger["phrase"] == "bare womanly torso"
    assert (trigger["category"], trigger["source"]) == ("nudity", "description")
    assert "sphinx carving, bare womanly torso blending" in trigger["context"]


def test_ignores_fixed_system_sections_and_ordinary_wording():
    assert find_content_triggers(_prompt("wooden sphinx carving, carved head, crouching lioness body")) == []


def test_reports_each_phrase_once_in_source_order_across_sections():
    found = find_content_triggers(_prompt(
        "naked warrior, severed arm, naked again", style="bloody splatter inks", direction="make it seductive"))
    assert [(item["phrase"], item["source"]) for item in found] == [
        ("bloody", "style"), ("naked", "description"), ("severed", "description"), ("seductive", "direction")]
