"""Run pytest from CI's cwd while hiding an ignored local frontend build."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT / "novel_to_comic")
# A pytest option reaches xdist workers too; a patch in this process would not.
raise SystemExit(pytest.main(["--hide-web-dist", *(sys.argv[1:] or ["-x", "-q"])]))
