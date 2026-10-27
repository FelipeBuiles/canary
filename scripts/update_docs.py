#!/usr/bin/env python3
"""Auto-regenerates docs/reference/models.md, api-routes.md, and config-fields.md
from source. Run manually or via the Claude Code Stop hook.

Stage-contracts.md is manually maintained and intentionally excluded.
"""

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SRC = ROOT / "novel_to_comic" / "src" / "novel_to_comic"
REFS = ROOT / "docs" / "reference"


# ---------------------------------------------------------------------------
# Config fields
# ---------------------------------------------------------------------------

def _extract_config_fields() -> list[dict]:
    """Parse config.py for Pydantic field definitions."""
    source = (SRC / "config.py").read_text()
    tree = ast.parse(source)

    fields = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                if not isinstance(item.target, ast.Name):
                    continue

                name = item.target.id
                type_str = ast.unparse(item.annotation)

                default = "required"
                if item.value is not None:
                    raw = ast.unparse(item.value)
                    if len(raw) > 60:
                        raw = raw[:57] + "..."
                    default = f"`{raw}`"

                match = re.search(
                    rf"^\s*{re.escape(name)}\s*:.*?(?:#\s*(.+))?$",
                    source,
                    re.MULTILINE,
                )
                comment = match.group(1).strip() if match and match.group(1) else ""

                fields.append({"name": name, "type": type_str, "default": default, "comment": comment})
    return fields


def write_config_fields_doc(fields: list[dict]) -> None:
    lines = [
        "# Config Fields Reference\n",
        "_Auto-generated from `config.py`. Do not edit manually._\n\n",
        "## Priority (highest → lowest)\n",
        "1. Shell environment variables\n",
        "2. Nearest `.env` file (walked up from project_dir)\n",
        "3. Project-owned values in `config.yaml` (model routes and gateway credentials are ignored)\n",
        "4. Pydantic field defaults\n\n",
        "Production stage models are overlaid from operator settings when a job config is created. "
        "Load with `load_config(project_dir) → (Config, env_file_path)`.\n\n",
        "## Fields\n\n",
        "| Field | Type | Default | Notes |\n",
        "|-------|------|---------|-------|\n",
    ]
    for f in fields:
        lines.append(f"| `{f['name']}` | `{f['type']}` | {f['default']} | {f['comment']} |\n")

    out = REFS / "config-fields.md"
    out.write_text("".join(lines).rstrip() + "\n")
    print(f"  wrote {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def _extract_models() -> dict[str, list[dict]]:
    """Parse models/*.py for Pydantic model classes and their fields."""
    result = {}
    for path in sorted((SRC / "models").glob("*.py")):
        source = path.read_text()
        tree = ast.parse(source)

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [ast.unparse(b) for b in node.bases]
            if not any("Model" in b or "BaseModel" in b for b in bases):
                continue

            fields = []
            for item in node.body:
                if not isinstance(item, ast.AnnAssign):
                    continue
                if not isinstance(item.target, ast.Name):
                    continue

                name = item.target.id
                type_str = ast.unparse(item.annotation)
                default = ""
                if item.value is not None:
                    raw = ast.unparse(item.value)
                    if len(raw) > 50:
                        raw = raw[:47] + "..."
                    default = f"`{raw}`"

                fields.append({"name": name, "type": type_str, "default": default})

            if fields:
                result[node.name] = {"fields": fields, "file": path.name}

    return result


def write_models_doc(models: dict) -> None:
    lines = [
        "# Models Reference\n\n",
        "_Auto-generated from `models/*.py`. Do not edit manually._\n\n",
        "These Pydantic models define the current pipeline's typed contracts. "
        "See [Stage Contracts](stage-contracts.md) for artifact paths, "
        "ownership, and revision boundaries.\n\n",
    ]

    for class_name, info in models.items():
        lines.append(f"## {class_name} _({info['file']})_\n\n")
        lines.append("| Field | Type | Default |\n")
        lines.append("|-------|------|---------|\n")
        for f in info["fields"]:
            lines.append(f"| `{f['name']}` | `{f['type']}` | {f['default']} |\n")
        lines.append("\n")

    out = REFS / "models.md"
    out.write_text("".join(lines).rstrip() + "\n")
    print(f"  wrote {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

def _extract_routes() -> list[dict]:
    """Parse server/routers/*.py for FastAPI route decorators.

    prefix_map must match the router mounts in server/app.py exactly.
    """
    routes = []
    router_dir = SRC / "server" / "routers"

    # These must stay in sync with the include_router() calls in server/app.py.
    # Series routes mount at /api/projects/{project}; part routes add
    # /parts/{part_id}. pipeline.py, stages.py and files.py mount at both.
    part = "/api/projects/{project}/parts/{part_id}"
    prefix_map = {
        "account_models.py": "/api/account",
        "auth.py": "/api/auth",
        "backoffice.py": "/api/ops/backoffice",
        "operator_billing.py": "/api/ops/billing",
        "projects.py": "/api/projects",
        "publications.py": part,
        "pipeline.py": "/api/projects/{project}",
        "pages.py": part,
        "lettering.py": part,  # included by pages.py
        "export.py": f"{part}/export",
        "editorial.py": part,
        "notes.py": part,
        "files.py": "/api/projects/{project}",
        "parts.py": "/api/projects/{project}",
        "story_bible.py": "/api/projects/{project}",
        "cast_assets.py": "/api/projects/{project}",
        "styles.py": "/api/projects/{project}",
        "cold_open.py": "/api/projects/{project}",
        "config.py": "/api/projects/{project}/config",
        "stages.py": "/api/projects/{project}",   # NO /data/ — mounted at project root
    }

    for path in sorted([*router_dir.glob("*.py"), SRC / "server" / "auth.py"]):
        if path.name == "__init__.py":
            continue
        source = path.read_text()
        prefix = prefix_map.get(path.name, f"/api/{path.stem}")

        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not (isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Attribute)
                        and isinstance(decorator.func.value, ast.Name) and decorator.args
                        and isinstance(decorator.args[0], ast.Constant)
                        and isinstance(decorator.args[0].value, str)):
                    continue
                router_name, method = decorator.func.value.id, decorator.func.attr
                if router_name not in {"router", "owner_router", "public_router", "ops_router"} or method not in {"get", "post", "put", "patch", "delete"}:
                    continue
                route_path = decorator.args[0].value
                route_prefix = prefix
                if path.name == "publications.py":
                    route_prefix = {"router": prefix, "owner_router": "/api/projects/{project}",
                                    "public_router": "/api/public/books", "ops_router": "/api/ops/publications"}[router_name]
                routes.append({"method": method.upper(),
                               "path": route_prefix + route_path if route_path != "/" else route_prefix,
                               "func": node.name, "file": path.name})

    return routes


def write_api_routes_doc(routes: list[dict]) -> None:
    lines = [
        "# API Routes Reference\n\n",
        "_Auto-generated from `server/routers/*.py`. Do not edit manually._\n\n",
        "Base URL: `http://localhost:8000` (dev). Replace `{project}` with the project directory name.\n\n",
        "Routes from `pipeline.py`, `stages.py` and `files.py` serve under both "
        "`/api/projects/{project}` (the series) and `/api/projects/{project}/parts/{part_id}` "
        "(one part).\n\n",
        "## Routes\n\n",
        "| Method | Path | Handler | File |\n",
        "|--------|------|---------|------|\n",
    ]
    for r in routes:
        lines.append(f"| `{r['method']}` | `{r['path']}` | `{r['func']}` | `{r['file']}` |\n")

    lines += [
        "\n## SSE Streaming\n\n",
        "`GET /api/projects/{project}/events` (or a part's `/parts/{part_id}/events`, "
        "which also carries series events) — Server-sent events stream. "
        "Connect before `POST /run` to receive stage progress. "
        "Event schema: `{type, stage, done, total, message, level}`. "
        "See `events.py` for the full schema.\n",
    ]

    out = REFS / "api-routes.md"
    out.write_text("".join(lines).rstrip() + "\n")
    print(f"  wrote {out.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def main() -> None:
    force = "--force" in sys.argv
    print("Updating reference docs...")

    import subprocess
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    changed = result.stdout.strip().splitlines()
    result2 = subprocess.run(
        ["git", "diff", "--name-only"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    changed += result2.stdout.strip().splitlines()
    changed_set = set(changed)

    def touched(pattern: str) -> bool:
        return any(pattern in f for f in changed_set)

    force_all = force or not changed_set

    if force_all or touched("config.py"):
        write_config_fields_doc(_extract_config_fields())

    if force_all or touched("models/"):
        write_models_doc(_extract_models())

    if force_all or touched("server/routers/") or touched("server/app.py") or touched("server/auth.py"):
        write_api_routes_doc(_extract_routes())

    if not (force_all or touched("config.py") or touched("models/") or touched("server/")):
        print("  no relevant changes detected — nothing to update")

    print("Done.")


if __name__ == "__main__":
    main()
