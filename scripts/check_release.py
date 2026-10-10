"""Fail-closed pre-push and release checks; also shared by GitHub CI.

Does not activate hooks, install browsers, change live services, or deploy.
"""

import argparse
import os
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


def check_name(args, cwd):
    """Short, stable labels; full commands remain in the log."""
    args = list(map(str, args))
    scope = "web" if Path(cwd) == ROOT / "web" else "root"
    if Path(args[0]).name == "npm":
        task = args[1:3] if args[1] == "run" else args[1:2]
        return f"{scope}: {' '.join(task).removeprefix('run ')}"
    if "pip-audit==2.10.1" in args:
        return "Python vulnerability audit"
    if "export" in args:
        return f"{args[args.index('--project') + 1]}: export locked dependencies"
    if "check" in args and "pip" in args:
        return f"{Path(args[-1]).parents[2].name}: dependency compatibility"
    if "ruff" in args:
        return "backend: Ruff lint"
    if any("run_backend_checks.py" in arg for arg in args):
        return "backend: tests"
    if "pytest" in args:
        return "gateway: tests" if "litellm/tests" in args else "web: built-page contracts"
    if "sync" in args:
        return "gateway: sync locked dependencies"
    scripts = [Path(arg).stem.replace('_', ' ') for arg in args[1:] if arg.endswith('.py')]
    return scripts[0] if scripts else " ".join([Path(args[0]).name, *args[1:]])


def run(args, cwd=ROOT, stdout=None, *, env=None):
    global LOG_DIR, CHECK_COUNT
    if LOG_DIR is None:
        LOG_DIR = Path(tempfile.mkdtemp(prefix="canary-checks-"))
        print(f"Check logs: {LOG_DIR}", flush=True)
    CHECK_COUNT += 1
    label = f"[{CHECK_COUNT:02d}] {check_name(args, cwd)}"
    log = LOG_DIR / f"{CHECK_COUNT:02d}.log"
    started = time.monotonic()
    tty = sys.stdout.isatty() and not VERBOSE
    print(f"  RUN  {label}", flush=True)
    command = shlex.join(map(str, args))
    status = "FAIL"
    try:
        with log.open("w", encoding="utf-8") as output:
            output.write(f"$ {command}\nWorking directory: {cwd}\n\n")
            output.flush()
            with log.open(encoding="utf-8", errors="replace") as reader:
                reader.seek(output.tell())
                with subprocess.Popen(
                    args, cwd=cwd, env=env, stdout=stdout or output,
                    stderr=output if stdout else subprocess.STDOUT,
                ) as process:
                    try:
                        while True:
                            try:
                                code = process.wait(timeout=0.2 if tty or VERBOSE else 10)
                            except subprocess.TimeoutExpired:
                                code = None
                            if VERBOSE:
                                sys.stdout.write(reader.read())
                                sys.stdout.flush()
                            if code is not None:
                                break
                            elapsed = time.monotonic() - started
                            if tty:
                                frame = "|/-\\"[int(elapsed * 5) % 4]
                                print(f"\r\033[2K  {frame}    {label} ({elapsed:.0f}s)", end="", flush=True)
                            elif not VERBOSE:
                                print(f"  ...  {label} ({elapsed:.0f}s)", flush=True)
                    except BaseException:
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
    finally:
        elapsed = time.monotonic() - started
        prefix = "\r\033[2K" if tty else ""
        result = f"{status}  {label} ({elapsed:.1f}s)"
        print(f"{prefix}  {result}", flush=True)
        with (LOG_DIR / "summary.log").open("a", encoding="utf-8") as summary:
            summary.write(f"{result} — {log.name}\n")
        if status == "FAIL":
            if not VERBOSE:
                sys.stderr.write(log.read_text(encoding="utf-8", errors="replace"))
            print(f"Diagnostics: {log}", file=sys.stderr, flush=True)


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
        run([sys.executable, "scripts/check_docs_reliability.py"])
        if name == "fast":
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
    started = time.monotonic()
    try:
        options = parser.parse_args()
        VERBOSE = options.verbose
        component(options.component)
    except (RuntimeError, subprocess.CalledProcessError, OSError) as error:
        print(f"FAIL/BLOCKED: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"PASS: {CHECK_COUNT} checks completed in {time.monotonic() - started:.1f}s")
    print(f"Logs: {LOG_DIR} (not a deployment approval)")
