#!/usr/bin/env python3
"""Download the two pinned pilot models once, using the isolated OCR Python."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
from pathlib import Path

MODELS = {"det": "PP-OCRv5_mobile_det", "rec": "en_PP-OCRv5_mobile_rec"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    cache = output.parent / "cache"
    for key, path in {
        "PADDLE_PDX_CACHE_HOME": cache,
        "HF_HOME": cache / "hf",
        "MODELSCOPE_CACHE": cache / "modelscope",
    }.items():
        os.environ[key] = str(path)
    os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

    # These caches are deliberately local; inference later uses explicit model
    # directories and never needs a model download in the request path.
    from paddlex.inference.utils.official_models import official_models

    output.mkdir(parents=True, exist_ok=True)
    for directory, name in MODELS.items():
        destination = output / directory
        if destination.exists():
            if not all(
                (destination / filename).is_file()
                for filename in ("inference.json", "inference.pdiparams")
            ):
                parser.error(f"Existing model directory is incomplete: {destination}")
        else:
            shutil.copytree(official_models.get_model_path(name), destination)
        print(f"{name}: {destination}")
    metadata = {
        "models": MODELS,
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("paddleocr", "paddlepaddle", "paddlex")
        },
    }
    (output / "models.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
