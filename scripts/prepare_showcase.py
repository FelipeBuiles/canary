#!/usr/bin/env python3
"""Prepare finished projects for the public showcase; never runs paid generation."""

import argparse
from pathlib import Path
import re
import shutil
import sys
import tempfile

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "novel_to_comic" / "src"))

from novel_to_comic.server import publications, showcase
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import load_state


def prepare(project: Path, destination: Path, metadata: publications.PublicationInput):
    previous = destination / "book.json"
    with tempfile.TemporaryDirectory(prefix="scenewright-showcase-") as temporary:
        staging = Path(temporary)
        if previous.exists():
            book = showcase.ShowcaseBook.model_validate_json(previous.read_text())
            publications.write_json(
                publications.owner_path(staging, "showcase", "book"), {"id": book.id}
            )
        record = publications.publish(
            staging, project, "showcase", "book", metadata,
            StageRuntime("finish", load_state(project), project),
        )
        record.pop("featured")
        # Why a language stayed private is for the author, not the public manifest.
        record.pop("unpublished_locales", None)
        for pages in [record["pages"], *(t["pages"] for t in record.get("translations", ()))]:
            for page in pages:
                page.pop("url")
        book = showcase.ShowcaseBook.model_validate(record)
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            publications.root(staging) / book.id / book.version,
            destination / book.version,
        )
        publications.write_json(previous, book.model_dump(exclude_none=True))
        return book


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path, nargs="?")
    parser.add_argument("--folder", help="Showcase folder name; alphabetic order is homepage order")
    parser.add_argument("--title")
    parser.add_argument("--author")
    parser.add_argument("--description", default="")
    parser.add_argument("--check", action="store_true", help="Validate all packaged showcase books")
    args = parser.parse_args()
    if args.check:
        books = showcase.books()
        print(f"Validated {len(books)} showcase books ({sum(len(b['pages']) for b, _ in books)} pages).")
        return
    if not all((args.project, args.folder, args.title, args.author)):
        parser.error("project, --folder, --title, and --author are required unless using --check")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", args.folder):
        parser.error("--folder must contain only lowercase letters, numbers, and hyphens")
    book = prepare(
        args.project.resolve(), showcase.root() / args.folder,
        publications.PublicationInput(
            title=args.title, author=args.author, description=args.description, allow_feature=True,
        ),
    )
    print(f"Prepared {book.title}: {len(book.pages)} pages in {showcase.root() / args.folder}")
    print(f"Reader: /read/{book.id}")


if __name__ == "__main__":
    main()
