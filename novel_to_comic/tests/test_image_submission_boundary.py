"""Image submission stays behind ``ai.image_submission``'s two entry points."""
import ast
from pathlib import Path

SOURCE = Path(__file__).parents[1] / "src" / "novel_to_comic"
PACKAGE = "novel_to_comic.ai.image_submission"


def _imports(path: Path) -> list[tuple[str, str]]:
    return [
        (node.module or "", alias.name)
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    ]


def test_page_drawing_reaches_no_ai_client_private():
    tree = ast.parse((SOURCE / "page_drawing.py").read_text())
    imported = [name for module, name in _imports(SOURCE / "page_drawing.py")
                if module == "novel_to_comic.ai.client" or (module == "novel_to_comic.ai" and name == "client")]
    private_attributes = [
        node.attr for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr.startswith("_")
        and isinstance(node.value, ast.Name) and node.value.id in {"client", "ai_client"}
    ]
    assert imported == [] and private_attributes == []


def test_only_the_package_imports_its_private_modules():
    outside = [
        (str(path.relative_to(SOURCE)), module, name)
        for path in SOURCE.rglob("*.py") if "image_submission" not in path.parts
        for module, name in _imports(path)
        if module.startswith(PACKAGE + "._") or (module == PACKAGE and name.startswith("_"))
    ]
    assert outside == []
