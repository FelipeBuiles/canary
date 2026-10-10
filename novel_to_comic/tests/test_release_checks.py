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
    assert f"{status}  [01]" in terminal.out
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
    assert "FAIL  [01]" in capsys.readouterr().out
    assert "FAIL  [01]" in (checks.LOG_DIR / "summary.log").read_text()
