#!/usr/bin/env python3
"""Check mechanically verifiable documentation contracts.

This intentionally avoids judging prose. It catches high-risk drift in stage
metadata, CLI entry points, generated-reference markers, and local links.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PY_ROOT = ROOT / "novel_to_comic" / "src" / "novel_to_comic"


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def source_contracts(failures: list[str]) -> tuple[list[str], set[str], set[str]]:
    state = ast.parse((PY_ROOT / "state.py").read_text())
    stages: list[str] | None = None
    checkpoints: set[str] | None = None
    for node in state.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            name = getattr(node.targets[0], "id", None)
            if name == "STAGE_NAMES" and isinstance(node.value, ast.List):
                stages = [elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)]
            if name == "CHECKPOINT_STAGES" and isinstance(node.value, ast.Set):
                checkpoints = {elt.value for elt in node.value.elts if isinstance(elt, ast.Constant)}
    if stages is None or checkpoints is None:
        fail("Could not read STAGE_NAMES/CHECKPOINT_STAGES from state.py", failures)
        return [], set(), set()

    registry_text = (PY_ROOT / "stages" / "__init__.py").read_text()
    module_names = re.findall(r"\b(s\d+_[a-z_]+)\b", registry_text.split("REGISTRY", 1)[0])
    registered: set[str] = set()
    for module_name in dict.fromkeys(module_names):
        module_path = PY_ROOT / "stages" / f"{module_name}.py"
        if not module_path.exists():
            fail(f"stage registry references missing module {module_name}", failures)
            continue
        stage_match = re.search(r"STAGE\s*=\s*Stage\(\s*name=\s*[\"']([^\"']+)", module_path.read_text())
        if stage_match:
            registered.add(stage_match.group(1))
    if registered != set(stages):
        fail(f"stage registry names are {sorted(registered)}, expected {stages}", failures)
    return stages, checkpoints, registered


def check_stage_table(path: Path, stages: list[str], checkpoints: set[str], failures: list[str]) -> None:
    text = path.read_text()
    rows = re.findall(r"^\|\s*(\d+)\s*\|.*?`([a-z_]+)`.*?\|\s*(Yes|No)\s*\|", text, re.M)
    documented = [name for _, name, _ in sorted(rows, key=lambda row: int(row[0]))]
    if documented != stages:
        fail(f"{path.relative_to(ROOT)} stage table is {documented}, expected {stages}", failures)
    documented_checkpoints = {name for _, name, answer in rows if answer == "Yes"}
    if documented_checkpoints != checkpoints:
        fail(f"{path.relative_to(ROOT)} checkpoints are {documented_checkpoints}, expected {checkpoints}", failures)


def check_cli(failures: list[str]) -> None:
    tree = ast.parse((PY_ROOT / "cli.py").read_text())
    commands: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if any(isinstance(dec, ast.Call) and getattr(dec.func, "attr", None) == "command" for dec in node.decorator_list):
                commands.add(node.name)
    expected = {"init", "serve"}
    if commands != expected:
        fail(f"cli.py commands are {commands}, expected {expected}", failures)


def check_generated_markers(failures: list[str]) -> None:
    expected = {
        ROOT / "docs/reference/api-routes.md": "server/routers/*.py",
        ROOT / "docs/reference/config-fields.md": "config.py",
        ROOT / "docs/reference/models.md": "models/*.py",
    }
    for path, marker in expected.items():
        if marker not in path.read_text():
            fail(f"{path.relative_to(ROOT)} lost generated-source marker {marker!r}", failures)


def check_local_links(failures: list[str]) -> None:
    paths = [ROOT / "AGENTS.md", ROOT / "CLAUDE.md", ROOT / "CONTEXT.md", *((ROOT / "docs").rglob("*.md"))]
    pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
    for path in paths:
        if not path.is_file():
            if path.name != "CLAUDE.md":
                fail(f"Required documentation missing: {path.relative_to(ROOT)}", failures)
            continue
        for target in pattern.findall(path.read_text()):
            target = target.split("#", 1)[0]
            if not target or "://" in target or target.startswith("mailto:"):
                continue
            candidate = (path.parent / target).resolve()
            if not candidate.exists():
                fail(f"{path.relative_to(ROOT)} links to missing {target}", failures)


def main() -> int:
    failures: list[str] = []
    stages, checkpoints, _ = source_contracts(failures)
    if stages:
        check_stage_table(ROOT / "docs/reference/stage-contracts.md", stages, checkpoints, failures)
        check_stage_table(ROOT / "docs/reference/agent-context.md", stages, checkpoints, failures)
    check_cli(failures)
    check_generated_markers(failures)
    check_local_links(failures)
    if failures:
        print("Documentation reliability check failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Documentation reliability check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
