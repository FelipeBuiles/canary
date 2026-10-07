"""Opt-in CPU verification of mismatching observations on saved base art.

The first read and canonical copy remain unchanged. Local readers receive only
cropped pixels. Disagreement and weak/absent evidence never certify lettering.
"""

from __future__ import annotations

import atexit
import base64
import hashlib
import io
import json
import math
import os
import select
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from pathlib import Path
from typing import Protocol

from PIL import Image

from novel_to_comic.models.crop_ocr import (
    CropOCRLine,
    CropOCRRead,
    CropOCRReport,
    assemble_crop_lines,
)
from novel_to_comic.text_utils import normalize_display_text

CROP_POLICY = "blind_crops_v1"
MAX_CROPS = 6
MAX_CROP_PIXELS = 3_000_000
MAX_PAGE_PIXELS = 24_000_000
MINIMUM_CONFIDENCE = 0.95  # Experimental threshold, not a calibrated probability.
PAGE_TIMEOUT_SECONDS = 30
WORKER_PATH = Path(__file__).with_name("crop_ocr_worker.py")


def _runtime_identity(python: str) -> bytes:
    """Fingerprint optional packages without loading their models into the API."""
    probe = (
        "import importlib.metadata as m, json, sys; "
        "print(json.dumps([sys.version, "
        "{name: m.version(name) for name in ('paddleocr','paddlepaddle','paddlex')}], sort_keys=True))"
    )
    try:
        return subprocess.run(
            [python, "-c", probe],
            check=True,
            capture_output=True,
            timeout=5,
        ).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        raise ValueError(
            "The configured Python must have the optional PaddleOCR packages installed"
        ) from exc


class CropReader(Protocol):
    fingerprint: str

    def read(self, image: bytes, *, timeout: float) -> tuple[CropOCRLine, ...]: ...


class PaddleCropReader:
    """One serialized, persistent CPU process, isolated from the API event loop."""

    def __init__(self, python: str, models: Path) -> None:
        self.python, self.models = python, models
        identity = hashlib.sha256(f"{CROP_POLICY}:{python}".encode())
        identity.update(_runtime_identity(python))
        identity.update(Path(__file__).read_bytes())
        identity.update(WORKER_PATH.read_bytes())
        identity.update((Path(__file__).parent / "models" / "crop_ocr.py").read_bytes())
        for name in ("det", "rec"):
            directory = models / name
            files = sorted(path for path in directory.rglob("*") if path.is_file())
            if not files:
                raise ValueError(f"Missing local OCR model files: {directory}")
            for path in files:
                identity.update(str(path.relative_to(models)).encode())
                identity.update(path.read_bytes())
        self.fingerprint = identity.hexdigest()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
        self._output = b""
        atexit.register(self.close)

    def close(self) -> None:
        with self._lock:
            self._stop_process()

    def _stop_process(self) -> None:
        process, self._process = self._process, None
        self._output = b""
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()

    def _answer(self, deadline: float) -> dict:
        assert self._process is not None and self._process.stdout is not None
        while (remaining := deadline - time.monotonic()) > 0:
            while b"\n" in self._output:
                line, self._output = self._output.split(b"\n", 1)
                try:
                    answer = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if isinstance(answer, dict):
                    return answer
            if not select.select([self._process.stdout], [], [], remaining)[0]:
                break
            chunk = os.read(self._process.stdout.fileno(), 65536)
            if not chunk:
                raise RuntimeError("Local OCR worker exited")
            self._output += chunk
            if len(self._output) > 1_000_000:
                raise RuntimeError("Local OCR worker exceeded the response budget")
        raise TimeoutError("Local OCR time budget exhausted")

    def _send(self, data: bytes, deadline: float) -> None:
        assert self._process is not None and self._process.stdin is not None
        descriptor = self._process.stdin.fileno()
        remaining_data = memoryview(data)
        while remaining_data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not select.select([], [descriptor], [], remaining)[1]:
                raise TimeoutError("Local OCR time budget exhausted")
            try:
                written = os.write(descriptor, remaining_data[:65536])
            except BlockingIOError:
                continue
            remaining_data = remaining_data[written:]

    def read(self, image: bytes, *, timeout: float) -> tuple[CropOCRLine, ...]:
        deadline = time.monotonic() + timeout
        if not self._lock.acquire(timeout=max(0, timeout)):
            raise TimeoutError("Local OCR worker is busy")
        try:
            if self._process is None:
                cache = Path(
                    os.environ.get(
                        "CANARY_CROP_OCR_CACHE",
                        str(Path(tempfile.gettempdir()) / "canary-crop-ocr"),
                    )
                )
                environment = dict(os.environ)
                environment.update(
                    {
                        "PADDLE_PDX_CACHE_HOME": str(cache),
                        "HF_HOME": str(cache / "hf"),
                        "MODELSCOPE_CACHE": str(cache / "modelscope"),
                        "PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK": "True",
                        "OMP_NUM_THREADS": "1",
                        "OPENBLAS_NUM_THREADS": "1",
                    }
                )
                self._process = subprocess.Popen(
                    [self.python, "-u", str(WORKER_PATH), "--models", str(self.models)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=environment,
                )
                assert self._process.stdin is not None
                os.set_blocking(self._process.stdin.fileno(), False)
                if self._answer(deadline) != {"ready": True}:
                    raise RuntimeError("Local OCR worker could not initialize")
            assert self._process.stdin is not None
            self._send(
                (
                    json.dumps({"image": base64.b64encode(image).decode()}) + "\n"
                ).encode(),
                deadline,
            )
            answer = self._answer(deadline)
            if "error" in answer:
                raise RuntimeError("Local OCR crop read failed")
            return assemble_crop_lines(
                tuple(CropOCRLine.model_validate(line) for line in answer["lines"])
            )
        except Exception:
            self._stop_process()
            raise
        finally:
            self._lock.release()


_configuration_lock = threading.Lock()
_configured_reader: PaddleCropReader | None = None
_configured_options: tuple[str, str] | None = None


def reader_from_environment() -> CropReader | None:
    """Operator opt-in only; ordinary installs never import or download Paddle."""
    global _configured_reader, _configured_options
    if os.environ.get("CANARY_CROP_OCR_ENABLED", "").lower() not in {"1", "true"}:
        return None
    models = os.environ.get("CANARY_CROP_OCR_MODELS", "")
    if not models:
        raise ValueError(
            "CANARY_CROP_OCR_MODELS must contain local det/ and rec/ models"
        )
    options = (os.environ.get("CANARY_CROP_OCR_PYTHON", sys.executable), models)
    with _configuration_lock:
        if options != _configured_options or _configured_reader is None:
            if _configured_reader is not None:
                _configured_reader.close()
            _configured_reader = None
            _configured_options = None
            _configured_reader = PaddleCropReader(options[0], Path(models))
            _configured_options = options
        return _configured_reader


def validator_version(base: str, reader: CropReader | None) -> str:
    return base if reader is None else f"{base}:crop:{reader.fingerprint}:{CROP_POLICY}"


def verify_mismatches(
    *, page, render, extraction, artifacts, reader: CropReader
) -> CropOCRReport:
    """Read only unmatched comic text. Persist lineage and both independent reads."""
    identity = hashlib.sha256(
        json.dumps(
            {
                "image": render.image_sha256,
                "page": page.content_sha256,
                "extraction": extraction.model_dump(mode="json"),
                "reader": reader.fingerprint,
                "policy": CROP_POLICY,
                "max_crops": MAX_CROPS,
                "max_pixels": MAX_CROP_PIXELS,
                "max_page_pixels": MAX_PAGE_PIXELS,
                "minimum_confidence": MINIMUM_CONFIDENCE,
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    from novel_to_comic.target_artifacts import ArtifactMissing

    image_bytes = artifacts.read_render(page.page_number, render.revision)
    if hashlib.sha256(image_bytes).hexdigest() != render.image_sha256:
        raise ValueError("Crop OCR render bytes do not match lineage")
    try:
        report = artifacts.read_crop_ocr(page.page_number, render.revision, identity)
        if (
            report.render_image_sha256 != render.image_sha256
            or report.comic_page_sha256 != page.content_sha256
            or report.input_sha256 != identity
            or report.reader_fingerprint != reader.fingerprint
        ):
            raise ValueError("Saved crop OCR belongs to different inputs")
        return report
    except ArtifactMissing:
        pass

    remaining = Counter(
        normalize_display_text(item.text)
        for part in page.content
        for item in part.lettering
    )
    disputed = []
    for observation in extraction.lettering:
        text = normalize_display_text(observation.text)
        if remaining[text] > 0:
            remaining[text] -= 1
        else:
            disputed.append(observation)
    reads = []
    deadline = time.monotonic() + PAGE_TIMEOUT_SECONDS
    regions = {region.id: region for region in extraction.observed_regions}
    # Geometry has already been captured; no detector call is needed to find crops.
    image, image_status = None, "over_budget"
    if disputed:
        try:
            with Image.open(io.BytesIO(image_bytes)) as opened:
                if opened.width * opened.height <= MAX_PAGE_PIXELS:
                    image = opened.convert("RGB")
        except (OSError, Image.DecompressionBombError):
            image_status = "unavailable"
    for index, observation in enumerate(disputed):
        if image is None:
            reads.append(
                CropOCRRead(observation_id=observation.id, status=image_status)
            )
            continue
        if index >= MAX_CROPS or time.monotonic() >= deadline:
            reads.append(
                CropOCRRead(observation_id=observation.id, status="over_budget")
            )
            continue
        # Tight regions remain separate from the panel used to prove reading order.
        region = regions.get(observation.id.replace("ocr_", "region_", 1))
        if region is None:
            reads.append(CropOCRRead(observation_id=observation.id, status="no_region"))
            continue
        xs, ys = zip(*region.polygon, strict=True)
        bounds = (
            max(0, math.floor((min(xs) - 0.01) * image.width)),
            max(0, math.floor((min(ys) - 0.01) * image.height)),
            min(image.width, math.ceil((max(xs) + 0.01) * image.width)),
            min(image.height, math.ceil((max(ys) + 0.01) * image.height)),
        )
        left, top, right, bottom = bounds
        if (
            right <= left
            or bottom <= top
            or (right - left) * (bottom - top) > MAX_CROP_PIXELS
        ):
            reads.append(
                CropOCRRead(
                    observation_id=observation.id, status="over_budget", bounds=bounds
                )
            )
            continue
        buffer = io.BytesIO()
        image.crop(bounds).save(buffer, format="PNG")
        crop = buffer.getvalue()
        try:
            lines = reader.read(crop, timeout=max(0, deadline - time.monotonic()))
            status = "read"
        except Exception:
            lines, status = (), "unavailable"
        reads.append(
            CropOCRRead(
                observation_id=observation.id,
                status=status,
                crop_sha256=hashlib.sha256(crop).hexdigest(),
                bounds=bounds,
                lines=lines,
            )
        )
    primary = {
        observation.id: normalize_display_text(observation.text)
        for observation in disputed
    }
    good = [
        read
        for read in reads
        if read.status == "read"
        and read.lines
        and all(line.confidence >= MINIMUM_CONFIDENCE for line in read.lines)
    ]
    status = (
        "disagrees"
        if any(
            normalize_display_text(read.text) != primary[read.observation_id]
            for read in good
        )
        else "agrees"
        if good and len(good) == len(reads)
        else "inconclusive"
    )
    report = CropOCRReport(
        page_number=page.page_number,
        render_revision=render.revision,
        render_image_sha256=render.image_sha256,
        comic_page_sha256=page.content_sha256,
        input_sha256=identity,
        reader_fingerprint=reader.fingerprint,
        minimum_confidence=MINIMUM_CONFIDENCE,
        status=status,
        readings=tuple(reads),
    )
    artifacts.write_crop_ocr(report)
    return report
