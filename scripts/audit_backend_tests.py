#!/usr/bin/env python3
"""Rank backend test costs and exact duplicate candidates without running tests.

Pass one JUnit report, or all four CI shard reports, with --junit. Durations
include setup/call/teardown as reported by pytest; sums are work, not parallel
wall time. Duplicate bodies are review candidates, not proof of redundancy:
fixtures, imports and the contract exercised still need a human comparison.
"""

import argparse
import ast
import copy
import json
from collections import defaultdict
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "novel_to_comic/tests"


def inventory(tests=TESTS):
    duplicates = defaultdict(list)
    modules = []
    for path in sorted(set(tests.glob("test_*.py")) | set(tests.glob("*_test.py"))):
        tree = ast.parse(path.read_text(), filename=str(path))
        count = 0

        def visit(body, prefix="", filename=path.name):
            nonlocal count
            for node in body:
                if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                    visit(node.body, prefix + node.name + "::")
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    count += 1
                    candidate = copy.deepcopy(node)
                    candidate.name = "test"
                    if (candidate.body and isinstance(candidate.body[0], ast.Expr)
                            and isinstance(candidate.body[0].value, ast.Constant)
                            and isinstance(candidate.body[0].value.value, str)):
                        candidate.body = candidate.body[1:]
                    # Keep arguments, decorators, identifiers and constants;
                    # normalizing those would produce misleading clone groups.
                    fingerprint = ast.dump(candidate, include_attributes=False)
                    duplicates[fingerprint].append({
                        "test": f"{filename}::{prefix}{node.name}", "line": node.lineno,
                    })

        visit(tree.body)
        modules.append({"file": path.name, "functions": count})
    return {
        "modules": len(modules),
        "functions": sum(module["functions"] for module in modules),
        "duplicate_candidates": [group for group in duplicates.values() if len(group) > 1],
    }


def timings(reports):
    files, functions = {}, {}
    occurrences = defaultdict(list)
    outcomes = defaultdict(int)
    suite_seconds = 0.0
    for report in reports:
        root = ElementTree.parse(report).getroot()
        suite_seconds += sum(float(suite.get("time", "0")) for suite in root.iter("testsuite"))
        for case in root.iter("testcase"):
            classname = case.get("classname", "")
            filename = case.get("file") or classname.split(".Test", 1)[0].replace(".", "/") + ".py"
            # Both repository-root and package-root pytest invocations occur.
            filename = filename.replace("\\", "/").split("tests/")[-1]
            case_name = case.get("name", "")
            test_class = classname.split(".Test", 1)
            if len(test_class) == 2:
                case_name = "Test" + test_class[1].replace(".", "::") + "::" + case_name
            occurrences[filename + "::" + case_name].append(str(report))
            name = case_name.split("[", 1)[0]
            seconds = float(case.get("time", "0"))
            outcome = next((kind for kind in ("error", "failure", "skipped") if case.find(kind) is not None), "passed")
            outcomes[outcome] += 1
            for groups, key in ((files, filename), (functions, filename + "::" + name)):
                row = groups.setdefault(key, {
                    "test": key, "cases": 0, "seconds": 0.0,
                    "max_seconds": 0.0, "skipped": 0, "failed": 0,
                })
                row["cases"] += 1
                row["seconds"] += seconds
                row["max_seconds"] = max(row["max_seconds"], seconds)
                row["skipped"] += outcome == "skipped"
                row["failed"] += outcome in {"error", "failure"}
    return {
        "reports": [str(path) for path in reports],
        "suite_seconds": suite_seconds, "outcomes": dict(outcomes),
        "repeated_cases": [{"test": key, "reports": paths} for key, paths in occurrences.items() if len(paths) > 1],
        "files": sorted(files.values(), key=lambda row: (-row["seconds"], row["test"])),
        "functions": sorted(functions.values(), key=lambda row: (-row["seconds"], row["test"])),
    }


def format_report(data, limit=15):
    lines = [f"Backend inventory: {data['modules']} modules, {data['functions']} test functions (before parametrization)."]
    runtime = data.get("timings")
    if runtime:
        total = sum(runtime["outcomes"].values())
        lines.append(f"JUnit: {total} cases; outcomes {runtime['outcomes']}; {runtime['suite_seconds']:.2f}s summed suite time.")
        lines.append("Durations include fixtures. Summed shard times are not parallel wall time.")
        for label, rows in (
            ("Most expensive modules", runtime["files"]),
            ("Most expensive test functions", runtime["functions"]),
            ("Largest case expansions (review each dimension's distinct contract)",
             sorted(runtime["functions"], key=lambda row: (-row["cases"], -row["seconds"]))),
        ):
            lines.extend(["", label, "  seconds  cases  max case  failed/skipped  test"])
            for row in rows[:limit]:
                lines.append(f"  {row['seconds']:7.2f}  {row['cases']:5}  {row['max_seconds']:8.2f}  "
                             f"{row['failed']:6}/{row['skipped']:<7} {row['test']}")
        repeated = runtime["repeated_cases"]
        lines.extend(["", f"Repeated JUnit identities: {len(repeated)} (check retries or overlapping jobs)"])
        for row in repeated[:limit]:
            lines.append(f"  {row['test']} ({len(row['reports'])} occurrences)")
    lines.extend(["", "Exact duplicate candidates (compare fixtures/imports before removing):"])
    for group in data["duplicate_candidates"]:
        lines.append("  " + " | ".join(f"{item['test']}:{item['line']}" for item in group))
    if not data["duplicate_candidates"]:
        lines.append("  None.")
    if not runtime:
        lines.append("\nAdd --junit REPORT.xml [REPORT.xml ...] for runtime and case-expansion rankings.")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--junit", nargs="+", type=Path, default=[])
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--json", type=Path, help="Save the complete inventory and rankings.")
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit must be positive")
    try:
        data = inventory()
        if args.junit:
            data["timings"] = timings(args.junit)
    except (OSError, ElementTree.ParseError, ValueError) as exc:
        parser.error(str(exc))
    print(format_report(data, args.limit))
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(data, indent=2) + "\n")


if __name__ == "__main__":
    main()
