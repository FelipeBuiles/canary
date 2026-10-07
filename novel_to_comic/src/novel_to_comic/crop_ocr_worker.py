"""CPU-only PaddleOCR subprocess. Input is image bytes, never canonical copy.

The parent owns artifacts and comparison; this process owns one model instance.
Dependencies and model files are optional and must be installed before startup.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import io
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", required=True)
    args = parser.parse_args()
    from pathlib import Path

    # Keep library progress output away from the JSON-lines protocol.
    with contextlib.redirect_stdout(sys.stderr):
        import numpy as np
        from paddleocr import PaddleOCR
        from PIL import Image

        models = Path(args.models)
        reader = PaddleOCR(
            device="cpu",
            cpu_threads=1,
            enable_mkldnn=False,
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_detection_model_dir=str(models / "det"),
            text_recognition_model_name="en_PP-OCRv5_mobile_rec",
            text_recognition_model_dir=str(models / "rec"),
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
        )
    print(json.dumps({"ready": True}), flush=True)
    for request in sys.stdin:
        try:
            data = json.loads(request)
            image = Image.open(
                io.BytesIO(base64.b64decode(data["image"], validate=True))
            ).convert("RGB")
            with contextlib.redirect_stdout(sys.stderr):
                results = list(reader.predict(np.asarray(image)))
            lines = []
            for result in results:
                for text, score, box in zip(
                    result["rec_texts"],
                    result["rec_scores"],
                    result["rec_boxes"],
                    strict=True,
                ):
                    if text.strip():
                        lines.append(
                            {
                                "text": text,
                                "confidence": float(score),
                                "box": [int(value) for value in box],
                            }
                        )
            print(json.dumps({"lines": lines}, ensure_ascii=False), flush=True)
        except Exception:
            # An unsuccessful local read must never become a successful empty read.
            print(json.dumps({"error": "crop_read_failed"}), flush=True)


if __name__ == "__main__":
    main()
