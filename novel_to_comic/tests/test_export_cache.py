import os
from pathlib import Path

from novel_to_comic.assembly.lettering_style import lettering_style_path
from novel_to_comic.server.routers.export import _export_is_fresh


def _touch(path: Path, timestamp: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}")
    os.utime(path, (timestamp, timestamp))


def test_export_cache_is_stale_when_lettering_style_is_newer(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "comic.pdf"
    _touch(tmp_path / "compose" / "pages" / "page_001.json", 100)
    _touch(export_path, 200)
    _touch(lettering_style_path(tmp_path), 300)

    assert _export_is_fresh(tmp_path, export_path) is False


def test_export_cache_is_fresh_when_lettering_style_is_older(tmp_path: Path) -> None:
    export_path = tmp_path / "exports" / "comic.pdf"
    _touch(tmp_path / "compose" / "pages" / "page_001.json", 100)
    _touch(lettering_style_path(tmp_path), 150)
    _touch(export_path, 200)

    assert _export_is_fresh(tmp_path, export_path) is True
