"""Run pytest from CI's cwd while hiding an ignored local frontend build."""

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "web" / "dist"
original_is_dir = Path.is_dir
Path.is_dir = lambda path: False if path == DIST else original_is_dir(path)
os.chdir(ROOT / "novel_to_comic")
raise SystemExit(pytest.main(sys.argv[1:] or ["-x", "-q"]))
