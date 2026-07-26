"""Clean-cutover gates for the single compiled image request lifecycle."""

from __future__ import annotations

import ast
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src" / "novel_to_comic"
HANDLERS = Path(__file__).resolve().parents[2] / "litellm_handlers"


def _async_functions(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
    }


def test_raw_prompt_and_mutable_path_transport_is_removed():
    assert "generate_image" not in _async_functions(SRC / "ai" / "client.py")
    assert "generate" not in _async_functions(
        SRC / "ai" / "providers" / "litellm_http.py"
    )


def test_panel_provenance_has_no_unreachable_duplicate_writer():
    source = (SRC / "panel_generation.py").read_text()
    assert "unreachable legacy" not in source.lower()
    assert "retained only as a source reference" not in source.lower()


def test_project_labs_import_does_not_seed_old_full_prompt_comparison():
    source = (SRC / "server" / "routers" / "labs.py").read_text()
    assert '"prompt_variant_b": p.full_prompt' not in source


def test_reve_handler_requires_wire_and_has_no_provider_prompt_mutations():
    source = (HANDLERS / "reve_provider.py").read_text()
    assert source.count("Reve image requests require canary_wire_request") == 2
    assert "final_prompt[:8000]" not in source
    assert "image[:4]" not in source
    assert '"Reference images:' not in source


def test_vertex_handler_requires_a_frozen_request_and_has_no_raw_prompt_fallback():
    source = (HANDLERS / "vertex_multimodal.py").read_text()
    assert (
        "Vertex image requests require a frozen wire or complete-page request"
        in source
    )
    assert "canary_complete_page_request" in source
    assert "The following reference images guide this illustration" not in source
