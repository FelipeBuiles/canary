"""The complete gate must exercise production HTML on a fresh checkout."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def checks(monkeypatch, tmp_path):
    spec = spec_from_file_location("release_checks", ROOT / "scripts/check_release.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "APP", tmp_path / "novel_to_comic")
    monkeypatch.setattr(module, "executable", lambda name: name)
    module.LOG_DIR = tmp_path / "logs"
    module.LOG_DIR.mkdir()
    module.UI = module.PlainUI("test checks", [("Checks", "check")], {})
    return module


def build_fixture(root, *, pricing=True):
    dist = root / "web/dist"
    (dist / "public").mkdir(parents=True)
    for name in ("index.html", "public-pages.json", "public/home.html", "public/es.html",
                 "public/fr.html", "public/legal-terms.html"):
        (dist / name).write_text("fixture")
    if pricing:
        (dist / "public/pricing.html").write_text("fixture")


def test_built_contracts_reject_missing_build_before_invoking_tools(checks, monkeypatch):
    monkeypatch.setattr(checks, "run", lambda *args, **kwargs: pytest.fail("Must not run against missing HTML"))
    with pytest.raises(RuntimeError, match="npm run build"):
        checks.component("web-contracts")


def test_web_rejects_incomplete_build_before_frontend_can_skip_hydration(checks, monkeypatch):
    invoked = []

    def run(args, *positional, **kwargs):
        invoked.append(args)
        if args == ["npm", "run", "build"]:
            build_fixture(checks.ROOT, pricing=False)

    monkeypatch.setattr(checks, "run", run)
    with pytest.raises(RuntimeError, match="public/pricing.html"):
        checks.component("web")
    assert not any("pytest" in args or "test" in args for args in invoked)


@pytest.mark.parametrize("verbose", [False, True])
def test_web_builds_before_serving_and_hydrating_production_html(checks, monkeypatch, verbose):
    invoked = []
    monkeypatch.setattr(checks, "VERBOSE", verbose)

    def run(args, *positional, **kwargs):
        invoked.append(args)
        if args == ["npm", "run", "build"]:
            build_fixture(checks.ROOT)

    monkeypatch.setattr(checks, "run", run)
    checks.component("web")
    build = next(i for i, args in enumerate(invoked) if args == ["npm", "run", "build"])
    contracts = next(i for i, args in enumerate(invoked) if "pytest" in args)
    hydration = next(i for i, args in enumerate(invoked) if args[:2] == ["npm", "test"])
    assert build < contracts < hydration
    assert "--hide-web-dist" not in invoked[contracts]
    assert "tests/test_public_site.py" in invoked[contracts]
    assert "tests/test_spa_static.py" in invoked[contracts]
    assert ("--silent=false" in invoked[hydration]) is verbose


@pytest.mark.parametrize("verbose", [False, True])
@pytest.mark.parametrize("exit_code", [0, 7])
def test_check_output_is_logged_and_failure_stays_fatal(checks, capsys, verbose, exit_code):
    import subprocess
    import sys

    checks.VERBOSE = verbose
    checks.UI = checks.PlainUI("test checks", [("Checks", "check")], {})
    args = [sys.executable, "-c", (
        "import sys; print('stdout evidence'); print('stderr evidence', file=sys.stderr); "
        f"sys.exit({exit_code})"
    )]
    if exit_code:
        with pytest.raises(subprocess.CalledProcessError) as failure:
            checks.run(args, cwd=checks.ROOT)
        assert failure.value.returncode == exit_code
    else:
        checks.run(args, cwd=checks.ROOT)
    terminal = capsys.readouterr()
    log = (checks.LOG_DIR / "01.log").read_text()
    assert "stdout evidence\n" in log and "stderr evidence\n" in log
    status = "FAIL" if exit_code else "PASS"
    assert f"{status}  [01/01]" in terminal.out
    assert f"{status}  [01]" in (checks.LOG_DIR / "summary.log").read_text()
    assert ("stdout evidence\n" in terminal.out + terminal.err) == (verbose or bool(exit_code))


def test_export_stdout_remains_machine_readable(checks, capsys):
    import sys

    destination = checks.ROOT / "requirements.txt"
    with destination.open("wb") as output:
        checks.run([sys.executable, "-c", (
            "import sys; print('package==1.0'); print('export diagnostic', file=sys.stderr)"
        )], cwd=checks.ROOT, stdout=output)
    assert destination.read_text() == "package==1.0\n"
    assert "export diagnostic\n" in (checks.LOG_DIR / "01.log").read_text()
    assert "export diagnostic\n" not in capsys.readouterr().out


def test_missing_command_records_failure(checks, capsys):
    with pytest.raises(FileNotFoundError):
        checks.run([str(checks.ROOT / "missing-executable")], cwd=checks.ROOT)
    assert "FAIL  [01/01]" in capsys.readouterr().out
    assert "FAIL  [01]" in (checks.LOG_DIR / "summary.log").read_text()


def test_planning_lists_every_check_in_sections_without_running(checks, monkeypatch):
    monkeypatch.setattr(checks.subprocess, "Popen", lambda *a, **k: pytest.fail("Planning must not run"))
    checks.PLANNING = True
    checks.component("local")
    sections = [section for section, _ in checks.PLAN]
    assert sections[0] == "App dependencies" and sections[-1] == "Gateway"
    assert ("Backend", "pytest") in checks.PLAN
    assert ("Web", "built-page contracts") in checks.PLAN
    assert ("Web", "Vitest") in checks.PLAN
    assert checks.CHECK_COUNT == 0


@pytest.mark.parametrize(("log", "expected"), [
    ("1 failed, 3024 passed, 53 skipped in 76.72s (0:01:16)", "1 failed · 3024 passed · 53 skipped"),
    ("\x1b[2m      Tests \x1b[22m \x1b[1m\x1b[32m1072 passed\x1b[39m (1072)\n"
     " Test Files  138 passed (138)", "1072 passed · 138 files"),
    ("No known vulnerabilities found", "no known vulnerabilities"),
    ("found 0 vulnerabilities", "no vulnerabilities"),
    ("Prerendered 11 public pages\nStartup JavaScript: 866 KB raw, 238.8 KB gzip", "11 pages · 238.8 KB gzip startup"),
    ("Checked 101 packages in 2ms", "101 packages"),
    ("nothing recognizable", ""),
])
def test_outcome_summarizes_logs(checks, log, expected):
    assert checks.outcome(log) == expected


def test_live_progress_redraws_in_place_and_shows_failure_tail(checks, capsys, monkeypatch):
    import sys

    monkeypatch.setattr(checks.shutil, "get_terminal_size", lambda: __import__("os").terminal_size((60, 20)))
    plan = [("Backend", "Ruff"), ("Backend", "pytest")]
    checks.PLAN[:] = plan
    checks.UI = checks.LiveUI("local checks", plan, {"Backend/Ruff": 0.1, "Backend/pytest": 50})
    checks.UI.begin()
    checks.run([sys.executable, "-c", "print('All checks passed!')"], cwd=checks.ROOT)
    with pytest.raises(checks.subprocess.CalledProcessError):
        checks.run([sys.executable, "-c", "print('tests/x.py ..F [ 40%]'); print('1 failed in 1s'); raise SystemExit(1)"],
                   cwd=checks.ROOT)
    checks.UI.blocked("", 1.0)
    out = capsys.readouterr().out
    assert "\x1b[J" in out and "~50s left" in out
    assert "no issues" in out and "1 failed" in out
    assert "╭─ " in out and "tests/x.py ..F [ 40%]" in out
    assert "1 passed  ·  0 not run" in out
    live = checks.UI.running(checks.Step(2, "Backend", "pytest", "Backend/pytest", checks.LOG_DIR / "02.log"), 3.0)
    assert all(len(checks.ANSI.sub("", line)) < 60 for line in live)
    assert "40%" in live[0]
