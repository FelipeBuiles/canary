"""Fail-closed pre-push and release checks; also shared by GitHub CI.

Does not activate hooks, install browsers, change live services, or deploy.
"""

import argparse
import atexit
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "novel_to_comic"
VERBOSE = False


def executable(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"BLOCKED: required executable {name} is unavailable")
    return path


LOG_DIR = None
CHECK_COUNT = 0
# Components first run with PLANNING set to list their checks, so progress
# knows the whole gate (and blocked prerequisites fail) before anything runs.
PLANNING = False
PLAN = []
SECTION = "Checks"
SECTIONS = {
    "audit-app": "App dependencies",
    "audit-gateway": "Gateway dependencies",
    "backend": "Backend",
    "web": "Web",
    "web-contracts": "Web",
    "root": "Root package",
    "gateway-tests": "Gateway",
    "gateway": "Gateway",
    "database": "Database",
    "docker": "Docker image",
}
UI = None
DURATIONS = {}
HISTORY = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "canary/check-durations.json"
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


def check_name(args, cwd):
    """Short, stable labels shown under their section; full commands remain in the log."""
    args = list(map(str, args))
    tool = Path(args[0]).name
    focused = any(arg.startswith(("tests/", "src/__tests__/")) for arg in args)
    if tool == "npm":
        task = args[2] if args[1] == "run" else args[1]
        name = {
            "ls": "dependency tree",
            "audit": "npm audit",
            "audit:production": "production audit",
            "lint": "ESLint",
            "build": "build + prerender",
            "test": "Vitest",
        }.get(task, task)
        return f"{name} (focused)" if focused else name
    if tool == "psql":
        return f"apply {Path(args[-1]).name}"
    if tool == "docker":
        return "docker build"
    if "pip-audit==2.10.1" in args:
        return "vulnerability audit"
    if "export" in args:
        return "export locked requirements"
    if "check" in args and "pip" in args:
        return "installed packages compatible"
    if "ruff" in args:
        return "Ruff"
    if "sync" in args:
        return "sync locked environment"
    if "pytest" in args or any("run_backend_checks.py" in arg for arg in args):
        if "tests/test_public_site.py" in args:
            return "built-page contracts"
        if any("postgres" in arg for arg in args):
            return "Postgres tests"
        return "pytest (focused)" if focused else "pytest"
    scripts = [Path(arg).stem for arg in args[1:] if arg.endswith(".py")]
    if scripts:
        stem = scripts[0]
        named = {"check_docs_reliability": "docs reliability", "smoke_gateway": "smoke test image"}
        return named.get(stem, f"{stem.removeprefix('patch_').replace('_', ' ')} patch")
    return shlex.join(args)


def outcome(text):
    """One meaningful phrase from a check's log: counts, not exit codes."""
    text = ANSI.sub("", text)
    if match := re.search(r"Tests\s+(.+?)\s*\(\d+\)", text):  # Vitest
        files = re.search(r"Test Files\s+.*?\((\d+)\)", text)
        return match[1].replace(" | ", " · ") + (f" · {files[1]} files" if files else "")
    if match := re.search(r"^=*\s*(\d+ (?:passed|failed|errors?|skipped)\b.*?) in [\d.]+s", text, re.MULTILINE):
        return match[1].replace(", ", " · ")  # pytest
    if "No known vulnerabilities found" in text:
        return "no known vulnerabilities"
    if match := re.search(r"found (\d+) vulnerabilit", text):
        return "no vulnerabilities" if match[1] == "0" else f"{match[1]} vulnerabilities"
    if match := re.search(r"(\d+) problems?", text):  # ESLint
        return match[0]
    if "All checks passed" in text:
        return "no issues"
    if match := re.search(r"Prerendered (\d+) public pages", text):
        startup = re.search(r"Startup JavaScript: [^,]+, ([\d.]+ KB) gzip", text)
        return f"{match[1]} pages" + (f" · {startup[1]} gzip startup" if startup else "")
    if match := re.search(r"Checked (\d+) packages", text):
        return f"{match[1]} packages"
    if match := re.search(r"Resolved (\d+) packages", text):
        return f"{match[1]} packages"
    return ""


def log_tail(path, size=4096):
    try:
        with path.open("rb") as file:
            file.seek(max(0, path.stat().st_size - size))
            return ANSI.sub("", file.read().decode("utf-8", "replace"))
    except OSError:
        return ""


def duration(seconds):
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{int(seconds // 60)}m{int(seconds % 60):02d}s"


def step_keys(plan):
    seen, keys = {}, []
    for section, name in plan:
        key = f"{section}/{name}"
        seen[key] = seen.get(key, 0) + 1
        keys.append(key if seen[key] == 1 else f"{key}#{seen[key]}")
    return keys


class Step:
    def __init__(self, index, section, name, key, log):
        self.index, self.section, self.name, self.key, self.log = index, section, name, key, log


class PlainUI:
    """Line-oriented output for CI, git GUIs and --verbose: stable and greppable."""

    def __init__(self, title, plan, history):
        self.title, self.total = title, len(plan)
        self.interval = 0.2 if VERBOSE else 10

    def label(self, step):
        return f"[{step.index:02d}/{self.total:02d}] {step.section} · {step.name}"

    def begin(self):
        if os.environ.get("CANARY_CHECK_CONTEXT") == "pre-push":
            print("[pre-push] Running the complete local checks; a failure blocks this push.")
        print(f"{self.title}: {self.total} checks. Logs: {LOG_DIR}", flush=True)

    def start(self, step):
        print(f"  RUN   {self.label(step)}", flush=True)

    def tick(self, step, elapsed):
        if not VERBOSE:
            print(f"  ...   {self.label(step)} ({elapsed:.0f}s)", flush=True)

    def finish(self, step, status, elapsed, detail):
        suffix = f" — {detail}" if detail else ""
        print(f"  {status:<5} {self.label(step)} ({elapsed:.1f}s){suffix}", flush=True)
        if status == "FAIL":
            if not VERBOSE:
                sys.stderr.write(step.log.read_text(encoding="utf-8", errors="replace"))
            print(f"Diagnostics: {step.log}", file=sys.stderr, flush=True)

    def passed(self, elapsed):
        print(f"PASS: {CHECK_COUNT} checks completed in {elapsed:.1f}s")
        print(f"Logs: {LOG_DIR} (not a deployment approval)")

    def blocked(self, message, elapsed):
        print(f"FAIL/BLOCKED: {message}", file=sys.stderr)


class LiveUI:
    """Interactive terminals: sections, live step and overall progress, short failure tails."""

    interval = 0.1
    SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    TAIL_LINES = 40

    def __init__(self, title, plan, history):
        self.title, self.plan = title, plan
        self.expected = [history.get(key) for key in step_keys(plan)]
        self.known = all(value is not None for value in self.expected)
        self.color = "NO_COLOR" not in os.environ
        self.name_width = min(30, max(len(name) for _, name in plan))
        self.section, self.live, self.frame, self.hidden = None, [], 0, False
        self.spent, self.results, self.failed = 0.0, [], None
        self.started = time.monotonic()

    @property
    def width(self):
        """Re-read every paint: a wrapped live line would break the in-place redraw."""
        return max(40, min(shutil.get_terminal_size().columns, 100)) - 1

    @staticmethod
    def clip(text, width):
        return text if len(text) <= width else text[: max(width - 1, 0)] + "…"

    def style(self, text, *codes):
        return f"\x1b[{';'.join(codes)}m{text}\x1b[0m" if self.color and codes and text else text

    def bar(self, fraction, width, color):
        filled = round(max(0.0, min(fraction, 1.0)) * width)
        return self.style("━" * filled, color) + self.style("─" * (width - filled), "2")

    def row(self, icon, name, right, text="", text_style=("2",), fraction=None, name_style=()):
        """One aligned check line: icon, name, detail text or a progress bar, elapsed time."""
        width = self.width
        right = right.rjust(13 if width >= 80 else 6)
        name_width = min(self.name_width, max(8, width - 7 - len(right) - 16))
        room = width - 7 - name_width - 2 - len(right)
        if fraction is not None and room >= 10:
            middle = self.bar(fraction, room - 6, "36") + f" {fraction * 100:3.0f}% "
        else:
            text = self.clip(text, room)
            middle = self.style(text, *text_style) + " " * (room - len(text))
        name = self.clip(name, name_width).ljust(name_width)
        return f"    {icon}  {self.style(name, *name_style)}  {middle}{self.style(right, '2')}"

    def paint(self, permanent=(), live=()):
        out = ""
        if self.live:
            # A resize re-wraps the previous live lines; count the rows they occupy now.
            columns = max(shutil.get_terminal_size().columns, 1)
            rows = sum(max(1, -(-length // columns)) for length in self.live)
            out += "\r" + (f"\x1b[{rows - 1}A" if rows > 1 else "") + "\x1b[J"
        out += "".join(line + "\n" for line in permanent)
        out += "\n".join(live)
        self.live = [len(ANSI.sub("", line)) for line in live]
        sys.stdout.write(out)
        sys.stdout.flush()

    def overall(self, done, current=0.0, expected=None, fraction=None):
        elapsed = time.monotonic() - self.started
        width = self.width
        info = f"  {done}/{len(self.plan)}  ·  {duration(elapsed)}"
        if self.known:
            pending = sum(self.expected[done + (expected is not None):])
            left = max((expected or 0) - current, 0) + pending
            fraction = (self.spent + current) / max(self.spent + current + left, 1e-9)
            info += f"  ·  ~{duration(left)} left"
        else:
            fraction = (done + (fraction or 0)) / len(self.plan)
        info = self.clip(info, width - 12)
        return "  " + self.bar(fraction, width - 2 - len(info), "38;5;220") + self.style(info, "2")

    def begin(self):
        estimate = f"  ·  ~{duration(sum(self.expected))}" if self.known else ""
        context = "pre-push · " if os.environ.get("CANARY_CHECK_CONTEXT") == "pre-push" else ""
        header = (
            "  " + self.style("canary", "1", "38;5;220") + self.style(f"  {context}{self.title}", "1")
            + self.style(f"  ·  {len(self.plan)} checks{estimate}", "2")
        )
        sys.stdout.write("\x1b[?25l")
        self.hidden = True
        atexit.register(self.show_cursor)
        self.paint(["", header], ["", self.overall(0)])

    def start(self, step):
        permanent = []
        if step.section != self.section:
            self.section = step.section
            permanent = ["", "  " + self.style(step.section, "1")]
        self.paint(permanent, self.running(step, 0.0))

    def running(self, step, elapsed):
        self.frame += 1
        expected = self.expected[step.index - 1] if step.index <= len(self.expected) else None
        tail = log_tail(step.log) if elapsed > 0.5 else ""
        percents = re.findall(r"\[\s*(\d+)%\]", tail)
        fraction = int(percents[-1]) / 100 if percents else None
        if fraction is None and expected and expected >= 2:
            fraction = min(elapsed / expected, 0.95)
        right = duration(elapsed)
        if expected and expected >= 2 and self.width >= 80:
            right += f" / ~{duration(expected)}"
        spinner = self.style(self.SPINNER[self.frame % len(self.SPINNER)], "36")
        lines = [self.row(spinner, step.name, right, fraction=fraction, name_style=("1",))]
        status = next(
            (line.strip() for line in reversed(tail.splitlines()) if len(re.findall(r"[A-Za-z]", line)) >= 3),
            "",
        )
        if status and not percents:
            lines.append("       " + self.style(self.clip("↳ " + status, self.width - 7), "2"))
        return [*lines, "", self.overall(step.index - 1, elapsed, expected, fraction)]

    def tick(self, step, elapsed):
        self.paint((), self.running(step, elapsed))

    def finish(self, step, status, elapsed, detail):
        self.spent += elapsed
        self.results.append((step, elapsed))
        if status == "PASS":
            line = self.row(self.style("✓", "32"), step.name, duration(elapsed), detail)
            self.paint([line], ["", self.overall(step.index)])
            return
        self.failed = step
        reason = "interrupted" if status == "STOP" else detail or "failed"
        line = self.row(self.style("✗", "1", "31"), step.name, duration(elapsed), reason, ("31",), name_style=("1", "31"))
        block = [line]
        if status == "FAIL":
            lines = step.log.read_text(encoding="utf-8", errors="replace").rstrip().splitlines()
            shown = lines[-self.TAIL_LINES:]
            caption = f"last {len(shown)} of {len(lines)} lines" if len(lines) > len(shown) else "log"
            block += ["", "  " + self.style("╭─ ", "31") + self.style(f"{step.name}", "1") + self.style(f"  {caption}", "2")]
            block += [self.style("  │ ", "31") + line.expandtabs(4) for line in shown]
            block += ["  " + self.style("╰─ ", "31") + self.style("full log  ", "2") + str(step.log)]
        self.paint(block, ())

    def show_cursor(self):
        if self.hidden:
            self.hidden = False
            sys.stdout.write("\x1b[?25h")
            sys.stdout.flush()

    def summary(self, lines):
        self.paint(["", *lines, ""], ())
        self.show_cursor()

    def passed(self, elapsed):
        slowest = sorted(self.results, key=lambda item: -item[1])[:3]
        names = [step.name for step, _ in self.results]
        slowest = "  ·  ".join(
            f"{step.name if names.count(step.name) == 1 else step.section + ' ' + step.name} {duration(time)}"
            for step, time in slowest
        )
        self.summary([
            "  " + self.style(f"✓ All {CHECK_COUNT} checks passed in {duration(elapsed)}", "1", "32"),
            self.style(self.clip(f"    slowest  {slowest}", self.width), "2"),
            self.style(f"    logs     {LOG_DIR}  (not a deployment approval)", "2"),
        ])

    def blocked(self, message, elapsed):
        ran = len(self.results)
        if self.failed:
            verdict = "Push blocked" if os.environ.get("CANARY_CHECK_CONTEXT") == "pre-push" else "Blocked"
            rest = len(self.plan) - ran
            headline = f"✗ {verdict}: {self.failed.section} · {self.failed.name} failed after {duration(elapsed)}"
            detail = f"    {ran - 1} passed  ·  {rest} not run  ·  rerun with --verbose to stream output"
        else:
            headline, detail = f"✗ {message}", f"    {ran} passed before stopping"
        self.summary(["  " + self.style(headline, "1", "31"), self.style(detail, "2"),
                      self.style(f"    logs     {LOG_DIR}", "2")])


def run(args, cwd=ROOT, stdout=None, *, env=None):
    global CHECK_COUNT
    section, name = SECTION, check_name(args, cwd)
    if PLANNING:
        PLAN.append((section, name))
        return
    CHECK_COUNT += 1
    keys = step_keys([*PLAN[: CHECK_COUNT - 1], (section, name)])
    step = Step(CHECK_COUNT, section, name, keys[-1], LOG_DIR / f"{CHECK_COUNT:02d}.log")
    started = time.monotonic()
    UI.start(step)
    command = shlex.join(map(str, args))
    status, code = "FAIL", None
    try:
        with step.log.open("w", encoding="utf-8") as output:
            output.write(f"$ {command}\nWorking directory: {cwd}\n\n")
            output.flush()
            with step.log.open(encoding="utf-8", errors="replace") as reader:
                reader.seek(output.tell())
                with subprocess.Popen(
                    args, cwd=cwd, env=env, stdout=stdout or output,
                    stderr=output if stdout else subprocess.STDOUT,
                ) as process:
                    try:
                        while True:
                            try:
                                code = process.wait(timeout=UI.interval)
                            except subprocess.TimeoutExpired:
                                code = None
                            if VERBOSE:
                                sys.stdout.write(reader.read())
                                sys.stdout.flush()
                            if code is not None:
                                break
                            UI.tick(step, time.monotonic() - started)
                    except BaseException as error:
                        if isinstance(error, KeyboardInterrupt):
                            status = "STOP"
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise
            if code:
                raise subprocess.CalledProcessError(code, args)
        status = "PASS"
        DURATIONS[step.key] = time.monotonic() - started
    finally:
        elapsed = time.monotonic() - started
        detail = outcome(log_tail(step.log, 16384))
        if status == "FAIL" and not detail and code:
            detail = f"exit {code}"
        UI.finish(step, status, elapsed, detail)
        with (LOG_DIR / "summary.log").open("a", encoding="utf-8") as summary:
            summary.write(f"{status}  [{step.index:02d}] {section} · {name} ({elapsed:.1f}s) — {step.log.name}\n")


def audit(project):
    uv = executable("uv")
    run([uv, "pip", "check", "--python", str(ROOT / project / ".venv/bin/python")])
    with tempfile.TemporaryDirectory(prefix="canary-audit-") as folder:
        requirements = Path(folder) / "requirements.txt"
        with requirements.open("wb") as output:
            run(
                [
                    uv,
                    "export",
                    "--project",
                    project,
                    "--locked",
                    "--no-dev",
                    "--no-emit-project",
                    *(["--extra", "web"] if project == "novel_to_comic" else []),
                ],
                stdout=output,
            )
        run(
            [
                uv,
                "tool",
                "run",
                "pip-audit==2.10.1",
                "-r",
                str(requirements),
                "--require-hashes",
                "--disable-pip",
            ]
        )


def backend(args):
    run(
        [
            executable("uv"),
            "run",
            "--locked",
            "--extra",
            "web",
            "--extra",
            "dev",
            "python",
            str(ROOT / "scripts/run_backend_checks.py"),
            *args,
        ],
        APP,
    )


def require_web_build():
    if PLANNING:  # The build itself is an earlier check in this gate.
        return
    dist = ROOT / "web/dist"
    required = [
        "index.html", "public-pages.json", "public/home.html", "public/es.html",
        "public/fr.html", "public/pricing.html", "public/legal-terms.html",
    ]
    missing = [name for name in required if not (dist / name).is_file()]
    if missing:
        raise RuntimeError(
            "BLOCKED: built web contracts require npm run build in web; missing "
            + ", ".join(missing)
        )


def component(name):
    global SECTION
    SECTION = SECTIONS.get(name, SECTION)
    if name == "audit-app":
        audit("novel_to_comic")
    elif name == "audit-gateway":
        audit("litellm")
    elif name == "backend":
        run([executable("uv"), "run", "--locked", "--extra", "dev", "ruff", "check", "."], APP)
        workers = os.environ.get("CANARY_BACKEND_WORKERS", str(min(4, os.cpu_count() or 1)))
        backend(["-x", "-q", "-n", workers, "--dist", "worksteal"])
    elif name == "web":
        npm = executable("npm")
        for args in [
            ["ls", "--all"],
            ["run", "audit:production"],
            ["audit", "--audit-level=high"],
            ["run", "lint"],
            ["run", "build"],
        ]:
            run([npm, *args], ROOT / "web")
        component("web-contracts")
        SECTION = "Web"
        run([npm, "test", *(["--", "--silent=false"] if VERBOSE else [])], ROOT / "web")
    elif name == "web-contracts":
        require_web_build()
        run([
            executable("uv"), "run", "--locked", "--extra", "web", "--extra", "dev",
            "python", "-m", "pytest", "tests/test_public_site.py", "tests/test_spa_static.py", "-q",
        ], APP)
    elif name == "root":
        for args in [["ls", "--all"], ["audit", "--audit-level=high"]]:
            run([executable("npm"), *args])
    elif name == "gateway-tests":
        uv = executable("uv")
        run([uv, "sync", "--project", "litellm", "--locked"])
        python = str(ROOT / "litellm/.venv/bin/python")
        for script in [
            "litellm/patch_http_errors.py",
            "litellm/patch_anthropic_refusals.py",
            "litellm/patch_model_response.py",
        ]:
            run([python, script])
        run([python, "-m", "pytest", "litellm/tests", "-q"])
    elif name == "gateway":
        component("gateway-tests")
        docker = executable("docker")
        run(
            [
                docker,
                "build",
                "-f",
                "litellm/Dockerfile",
                "-t",
                "canary-gateway-check",
                ".",
            ]
        )
        run([sys.executable, "scripts/smoke_gateway.py", "canary-gateway-check"])
    elif name == "database":
        url = os.environ.get("CREDIT_TEST_DATABASE_URL", "")
        parsed = urlsplit(url)
        if (
            parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.path != "/canary_test"
            or os.environ.get("CANARY_DISPOSABLE_DATABASE") != "1"
        ):
            raise RuntimeError(
                "BLOCKED: database checks require explicitly disposable loopback /canary_test and CANARY_DISPOSABLE_DATABASE=1"
            )
        psql = executable("psql")
        env = os.environ.copy()
        # Keep connection credentials out of command arguments and logs.
        env.update(
            PGHOST=parsed.hostname,
            PGPORT=str(parsed.port or 5432),
            PGUSER=unquote(parsed.username or "postgres"),
            PGPASSWORD=unquote(parsed.password or ""),
            PGDATABASE="canary_test",
        )
        for file in [
            "novel_to_comic/tests/fixtures/security_database_bootstrap.sql",
            "docs/supabase-schema.sql",
            "docs/supabase-schema.sql",
        ]:
            run(
                [psql, "-v", "ON_ERROR_STOP=1", "-f", file],
                cwd=ROOT,
                env=env,
            )
        backend(
            [
                "-q",
                "tests/test_credit_ledger_postgres.py",
                "tests/test_project_data_api_postgres.py",
                "tests/test_purchase_outbox_postgres.py",
                "tests/test_account_outbox_postgres.py",
                "tests/test_tester_tracker_postgres.py",
            ]
        )
    elif name == "docker":
        run(
            [
                executable("docker"),
                "build",
                "-t",
                "canary-release-check",
                "--build-arg",
                "VITE_SUPABASE_URL=https://ci-smoke.supabase.co",
                "--build-arg",
                "VITE_SUPABASE_PUBLISHABLE_KEY=sb_publishable_ci_smoke",
                "--build-arg",
                "VITE_CANARY_ENV=production",
                ".",
            ]
        )
    elif name in {"fast", "local", "full"}:
        for item in ["audit-app", "audit-gateway"]:
            component(item)
        SECTION = "Docs"
        run([sys.executable, "scripts/check_docs_reliability.py"])
        if name == "fast":
            SECTION = "Backend"
            run([executable("uv"), "run", "--locked", "ruff", "check", "."], APP)
            backend(
                [
                    "-q",
                    "tests/test_publications.py",
                    "tests/test_auth.py",
                    "tests/test_security_boundary_contracts.py",
                    "tests/test_lifecycle_events.py",
                    "tests/test_observability.py",
                    "tests/test_generation_jobs.py",
                    "tests/test_durable_queue.py",
                    "tests/test_pipeline_failure_boundaries.py",
                ]
            )
            SECTION = "Web"
            for args in [
                ["run", "audit:production"],
                ["audit", "--audit-level=high"],
                [
                    "test",
                    "--",
                    *(["--silent=false"] if VERBOSE else []),
                    "src/__tests__/telemetry.test.ts",
                    "src/__tests__/authContext.test.ts",
                    "src/__tests__/authForms.test.tsx",
                    "src/__tests__/pagesRoom.test.tsx",
                    "src/__tests__/pageArtwork.test.tsx",
                    "src/__tests__/publicMetadata.test.tsx",
                    "src/__tests__/publicBook.test.tsx",
                    "src/__tests__/sampleLibraryPage.test.tsx",
                ],
                ["run", "lint"],
                ["run", "build"],
            ]:
                run([executable("npm"), *args], ROOT / "web")
            component("root")
        elif name == "local":
            for item in ["backend", "web", "root", "gateway-tests"]:
                component(item)
        else:
            # Validate disposal target before spending time on expensive suites.
            parsed = urlsplit(os.environ.get("CREDIT_TEST_DATABASE_URL", ""))
            if (
                parsed.hostname not in {"localhost", "127.0.0.1"}
                or parsed.path != "/canary_test"
                or os.environ.get("CANARY_DISPOSABLE_DATABASE") != "1"
            ):
                raise RuntimeError(
                    "BLOCKED: full release requires explicit disposable loopback canary_test database"
                )
            for item in ["database", "backend", "web", "root", "gateway", "docker"]:
                component(item)
    else:
        raise RuntimeError(f"Unknown component: {name}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose", action="store_true",
        help="Stream all check output, including passing frontend test diagnostics.",
    )
    parser.add_argument(
        "component",
        nargs="?",
        default="fast",
        choices=[
            "fast",
            "local",
            "full",
            "audit-app",
            "audit-gateway",
            "backend",
            "web",
            "web-contracts",
            "root",
            "gateway",
            "gateway-tests",
            "database",
            "docker",
        ],
    )
    options = parser.parse_args()
    VERBOSE = options.verbose
    started = time.monotonic()
    try:
        PLANNING = True
        component(options.component)
        PLANNING = False
        try:
            history = json.loads(HISTORY.read_text())
        except (OSError, ValueError):
            history = {}
        LOG_DIR = Path(tempfile.mkdtemp(prefix="canary-checks-"))
        live = sys.stdout.isatty() and not VERBOSE and os.environ.get("TERM") != "dumb"
        UI = (LiveUI if live else PlainUI)(f"{options.component} checks", PLAN, history)
        UI.begin()
        component(options.component)
    except (RuntimeError, subprocess.CalledProcessError, OSError, KeyboardInterrupt) as error:
        message = "interrupted" if isinstance(error, KeyboardInterrupt) else str(error)
        if UI is None:
            print(f"FAIL/BLOCKED: {message}", file=sys.stderr)
        else:
            UI.blocked(message, time.monotonic() - started)
        raise SystemExit(130 if isinstance(error, KeyboardInterrupt) else 1)
    finally:
        if DURATIONS:
            try:
                HISTORY.parent.mkdir(parents=True, exist_ok=True)
                HISTORY.write_text(json.dumps({**history, **DURATIONS}, indent=1, sort_keys=True))
            except OSError:
                pass
    UI.passed(time.monotonic() - started)
