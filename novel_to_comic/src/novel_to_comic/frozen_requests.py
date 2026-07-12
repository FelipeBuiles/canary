"""Immutable, project-scoped storage for submitted provider-wire requests.

The provider wire is the reviewed semantic request.  This module freezes the
wire and the selected reference bytes before a queued image job is published.
The persisted manifest contains only portable request data and relative
content-addressed locators; absolute server paths are reconstructed only after
the caller has already selected an authorized project directory.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, TYPE_CHECKING

from novel_to_comic.provider_wire import ProviderWireError, ProviderWireRequest

if TYPE_CHECKING:
    from novel_to_comic.config import Config
    from novel_to_comic.usage import ApiResult


FROZEN_REQUEST_SCHEMA_VERSION = 1
FROZEN_REQUEST_DISCRIMINATOR = "canary.frozen-request/1"
FROZEN_REQUEST_VERSION = "frozen-generation-request/1"
FROZEN_REQUEST_PREPARATION_VERSION = "frozen-reference-staging/1"
FROZEN_REQUEST_SOURCE_VERSION = "provider-wire/1"

REQUESTS_DIRNAME = "requests"
BLOBS_DIRNAME = "blobs"
MANIFEST_FILENAME = "manifest.json"
STATUS_FILENAME = "status.json"

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_MAX_IDEMPOTENCY_KEY_LENGTH = 512
_BLOB_LOCK = threading.RLock()
_REQUEST_LOCK = threading.RLock()


class FrozenRequestError(ValueError):
    """The request cannot be safely frozen, loaded, or executed."""


class FrozenRequestIntegrityError(FrozenRequestError):
    """A manifest or content-addressed blob failed verification."""


class FrozenRequestNotFound(FrozenRequestError):
    """The request does not exist in the selected project scope."""


class FrozenRequestIdempotencyConflict(FrozenRequestError):
    """An idempotency key was reused for a different provider request."""


@dataclass(frozen=True, slots=True)
class FrozenReferenceSnapshot:
    index: int
    content_sha256: str
    locator: str
    byte_length: int


@dataclass(frozen=True, slots=True)
class FrozenGenerationRequest:
    request_id: str
    created_at: str
    submitted_at: str
    preparation_version: str
    source_version: str
    request_version: str
    status: str
    wire: ProviderWireRequest
    execution_fingerprint: str
    snapshots: tuple[FrozenReferenceSnapshot, ...]
    manifest_sha256: str
    idempotency_key: str | None = None
    result_link: str | None = None
    provenance_link: str | None = None
    job_id: str | None = None


def requests_root(project_dir: Path) -> Path:
    return project_dir / REQUESTS_DIRNAME


def _validated_store_root(project_dir: Path, *, create: bool = False) -> Path:
    root = requests_root(project_dir)
    if root.is_symlink():
        raise FrozenRequestIntegrityError(f"request store must not be a symlink: {root}")
    if root.exists() and not root.is_dir():
        raise FrozenRequestIntegrityError(f"request store is not a directory: {root}")
    if create and not root.exists():
        root.mkdir(parents=True, exist_ok=True)
    if root.exists():
        try:
            root.resolve().relative_to(project_dir.resolve())
        except ValueError as exc:
            raise FrozenRequestIntegrityError(
                f"request store escapes project scope: {root}"
            ) from exc
    return root


@contextmanager
def _store_lock(project_dir: Path):
    """Serialize staging and GC across server processes for one project."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    with _request_store_fds(project_dir, create=True) as request_fd:
        assert request_fd is not None
        try:
            descriptor = os.open(
                ".store.lock",
                os.O_CREAT | os.O_RDWR | nofollow,
                0o600,
                dir_fd=request_fd,
            )
        except OSError as exc:
            raise FrozenRequestIntegrityError(
                f"request-store lock is unreadable or linked: {project_dir}"
            ) from exc
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            yield request_fd
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)


def _validated_blob_root(project_dir: Path, *, create: bool = False) -> Path:
    root = _validated_store_root(project_dir, create=create)
    blobs = root / BLOBS_DIRNAME
    if blobs.is_symlink():
        raise FrozenRequestIntegrityError(f"blob store must not be a symlink: {blobs}")
    if blobs.exists() and not blobs.is_dir():
        raise FrozenRequestIntegrityError(f"blob store is not a directory: {blobs}")
    if create and not blobs.exists():
        blobs.mkdir()
    if blobs.exists():
        try:
            blobs.resolve().relative_to(root.resolve())
        except ValueError as exc:
            raise FrozenRequestIntegrityError(
                f"blob store escapes project scope: {blobs}"
            ) from exc
    return blobs


@contextmanager
def _request_store_fds(project_dir: Path, *, create: bool):
    """Open the project request directory with a no-follow descriptor."""
    project_root = project_dir.resolve()
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    project_fd = request_fd = -1
    try:
        try:
            project_fd = os.open(project_root, directory_flags)
        except FileNotFoundError:
            if not create:
                yield None
                return
            project_root.mkdir(parents=True, exist_ok=True)
            project_fd = os.open(project_root, directory_flags)
        try:
            request_fd = os.open(REQUESTS_DIRNAME, directory_flags, dir_fd=project_fd)
        except FileNotFoundError:
            if not create:
                yield None
                return
            os.mkdir(REQUESTS_DIRNAME, dir_fd=project_fd)
            request_fd = os.open(REQUESTS_DIRNAME, directory_flags, dir_fd=project_fd)
        yield request_fd
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"request store is unreadable, symlinked, or linked: {project_dir}"
        ) from exc
    finally:
        for descriptor in (request_fd, project_fd):
            if descriptor >= 0:
                os.close(descriptor)


@contextmanager
def _request_directory_at(request_store_fd: int, request_id: str):
    """Open one published request directory beneath an opened store."""
    _validate_request_id(request_id)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    try:
        request_fd = os.open(request_id, directory_flags, dir_fd=request_store_fd)
    except FileNotFoundError as exc:
        raise FrozenRequestNotFound(f"frozen request not found: {request_id}") from exc
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"frozen request directory is unreadable, symlinked, or linked: {request_id}"
        ) from exc
    try:
        yield request_fd
    finally:
        os.close(request_fd)


@contextmanager
def _request_directory_fd(project_dir: Path, request_id: str):
    """Open one published request directory without following store links."""
    with _request_store_fds(project_dir, create=False) as request_store_fd:
        if request_store_fd is None:
            raise FrozenRequestNotFound(f"frozen request not found: {request_id}")
        with _request_directory_at(request_store_fd, request_id) as request_fd:
            yield request_fd


@contextmanager
def _blob_fd_at(request_store_fd: int, *, create: bool):
    """Open the blob directory beneath an already-open request store."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    blob_fd: int | None = None
    try:
        try:
            blob_fd = os.open(BLOBS_DIRNAME, directory_flags, dir_fd=request_store_fd)
        except FileNotFoundError:
            if not create:
                yield None
                return
            os.mkdir(BLOBS_DIRNAME, dir_fd=request_store_fd)
            blob_fd = os.open(BLOBS_DIRNAME, directory_flags, dir_fd=request_store_fd)
        yield blob_fd
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            "request/blob store is unreadable, symlinked, or linked"
        ) from exc
    finally:
        if blob_fd is not None:
            os.close(blob_fd)


@contextmanager
def _blob_store_fds(project_dir: Path, *, create: bool):
    """Open the request/blob directories once with no-follow descriptors."""
    with _request_store_fds(project_dir, create=create) as request_fd:
        if request_fd is None:
            yield -1, None
            return
        with _blob_fd_at(request_fd, create=create) as blob_fd:
            yield request_fd, blob_fd


def _read_regular_fd(fd: int, *, label: str, expected_digest: str | None = None) -> bytes:
    file_stat = os.fstat(fd)
    if not stat.S_ISREG(file_stat.st_mode):
        raise FrozenRequestIntegrityError(f"staged file is not a regular file: {label}")
    if file_stat.st_nlink != 1:
        raise FrozenRequestIntegrityError(f"staged file must not be hard-linked: {label}")
    with os.fdopen(os.dup(fd), "rb") as handle:
        data = handle.read()
    if expected_digest is not None:
        actual = hashlib.sha256(data).hexdigest()
        if actual != expected_digest:
            raise FrozenRequestIntegrityError(
                f"staged blob digest mismatch for {label}: expected {expected_digest}, got {actual}"
            )
    return data


def request_directory(project_dir: Path, request_id: str) -> Path:
    _validate_request_id(request_id)
    return requests_root(project_dir) / request_id


def _validated_request_directory(project_dir: Path, request_id: str) -> Path:
    root = _validated_store_root(project_dir)
    directory = root / request_id
    if directory.is_symlink():
        raise FrozenRequestIntegrityError(
            f"frozen request directory must not be a symlink: {directory}"
        )
    if not directory.exists():
        raise FrozenRequestNotFound(f"frozen request not found: {request_id}")
    if not directory.is_dir():
        raise FrozenRequestIntegrityError(f"frozen request is not a directory: {directory}")
    try:
        directory.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise FrozenRequestIntegrityError(
            f"frozen request directory escapes project scope: {directory}"
        ) from exc
    return directory


def manifest_path(project_dir: Path, request_id: str) -> Path:
    return request_directory(project_dir, request_id) / MANIFEST_FILENAME


def status_path(project_dir: Path, request_id: str) -> Path:
    return request_directory(project_dir, request_id) / STATUS_FILENAME


def blob_path(project_dir: Path, digest: str) -> Path:
    _validate_digest(digest)
    return requests_root(project_dir) / BLOBS_DIRNAME / digest


# Explicit alias for callers that prefer the domain name over the storage name.
request_blob_path = blob_path


def _validate_digest(digest: str) -> None:
    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        raise FrozenRequestIntegrityError(f"invalid SHA-256 digest: {digest!r}")


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or not _REQUEST_ID_RE.fullmatch(request_id):
        raise FrozenRequestError(f"invalid frozen request id: {request_id!r}")


def _validate_idempotency_key(key: str | None) -> None:
    if key is not None and (
        not isinstance(key, str)
        or not key
        or len(key) > _MAX_IDEMPOTENCY_KEY_LENGTH
    ):
        raise FrozenRequestError("idempotency_key must be a non-empty short string")


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _canonical_digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _atomic_write_at(parent_fd: int, filename: str, data: bytes) -> None:
    """Atomically replace one regular file relative to an already-open directory."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    temporary_name = f".{filename}.{uuid.uuid4().hex}.tmp"
    temporary_fd = -1
    try:
        temporary_fd = os.open(
            temporary_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=parent_fd,
        )
        with os.fdopen(temporary_fd, "wb") as handle:
            temporary_fd = -1
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(
            temporary_name,
            filename,
            src_dir_fd=parent_fd,
            dst_dir_fd=parent_fd,
        )
        os.fsync(parent_fd)
        temporary_name = ""
    except BaseException:
        if temporary_fd >= 0:
            os.close(temporary_fd)
        if temporary_name:
            try:
                os.unlink(temporary_name, dir_fd=parent_fd)
            except FileNotFoundError:
                pass
        raise


def _stage_blob_at(
    project_dir: Path,
    digest: str,
    data: bytes,
    blob_fd: int,
) -> Path:
    destination = blob_path(project_dir, digest)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    existing_fd = -1
    temporary_name: str | None = None
    try:
        try:
            existing_fd = os.open(digest, os.O_RDONLY | nofollow, dir_fd=blob_fd)
        except FileNotFoundError:
            temporary_name = f".{digest}.{uuid.uuid4().hex}.tmp"
            temporary_fd = os.open(
                temporary_name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
                dir_fd=blob_fd,
            )
            with os.fdopen(temporary_fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(
                temporary_name,
                digest,
                src_dir_fd=blob_fd,
                dst_dir_fd=blob_fd,
            )
            temporary_name = None
            existing_fd = os.open(digest, os.O_RDONLY | nofollow, dir_fd=blob_fd)
        _read_regular_fd(existing_fd, label=str(destination), expected_digest=digest)
    except BaseException:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name, dir_fd=blob_fd)
            except FileNotFoundError:
                pass
        raise
    finally:
        if existing_fd >= 0:
            os.close(existing_fd)
    return destination


def _stage_blob(
    project_dir: Path,
    digest: str,
    data: bytes,
    *,
    request_store_fd: int | None = None,
) -> Path:
    with _BLOB_LOCK:
        if request_store_fd is not None:
            with _blob_fd_at(request_store_fd, create=True) as blob_fd:
                assert blob_fd is not None
                return _stage_blob_at(project_dir, digest, data, blob_fd)
        with _blob_store_fds(project_dir, create=True) as (_, blob_fd):
            assert blob_fd is not None
            return _stage_blob_at(project_dir, digest, data, blob_fd)


def _read_source_snapshot(project_dir: Path, source: Path) -> bytes:
    """Read one project file through no-follow descriptors and one inode."""
    project_root = project_dir.resolve()
    raw_candidate = Path(
        os.path.abspath(source if source.is_absolute() else project_dir / source)
    )
    try:
        if raw_candidate.is_symlink():
            raise FrozenRequestIntegrityError(
                f"selected reference must not be a symlink: {source}"
            )
        candidate = raw_candidate.resolve(strict=False)
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"selected reference is unreadable or linked: {source}"
        ) from exc
    try:
        relative = candidate.relative_to(project_root)
    except ValueError as exc:
        raise FrozenRequestIntegrityError(
            f"selected reference is outside project scope: {source}"
        ) from exc
    if not relative.parts:
        raise FrozenRequestIntegrityError(f"selected reference is not a file: {source}")

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    file_flags = os.O_RDONLY | nofollow
    directory_fds: list[int] = []
    final_fd = -1
    try:
        directory_fds.append(os.open(project_root, directory_flags))
        for component in relative.parts[:-1]:
            directory_fds.append(
                os.open(component, directory_flags, dir_fd=directory_fds[-1])
            )
        final_fd = os.open(relative.parts[-1], file_flags, dir_fd=directory_fds[-1])
        file_stat = os.fstat(final_fd)
        if not stat.S_ISREG(file_stat.st_mode):
            raise FrozenRequestIntegrityError(
                f"selected reference is not a regular file: {source}"
            )
        if file_stat.st_nlink != 1:
            raise FrozenRequestIntegrityError(
                f"selected reference must not be hard-linked: {source}"
            )
        with os.fdopen(final_fd, "rb") as handle:
            final_fd = -1
            return handle.read()
    except FrozenRequestIntegrityError:
        raise
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"selected reference is unreadable or linked: {source}"
        ) from exc
    finally:
        if final_fd >= 0:
            os.close(final_fd)
        for descriptor in reversed(directory_fds):
            os.close(descriptor)


def _portable_wire(
    wire: ProviderWireRequest,
    snapshots: tuple[FrozenReferenceSnapshot, ...],
) -> ProviderWireRequest:
    references = tuple(
        replace(reference, source_path=snapshot.locator)
        for reference, snapshot in zip(wire.references, snapshots, strict=True)
    )
    portable = replace(wire, references=references)
    if portable.recompute_execution_fingerprint() != wire.execution_fingerprint:
        raise FrozenRequestIntegrityError(
            "freezing changed the ProviderWireRequest execution fingerprint"
        )
    return portable


def _transport_wire(
    wire: ProviderWireRequest,
    snapshots: tuple[FrozenReferenceSnapshot, ...],
    project_dir: Path,
) -> ProviderWireRequest:
    references = tuple(
        replace(
            reference,
            source_path=str(requests_root(project_dir) / snapshot.locator),
        )
        for reference, snapshot in zip(wire.references, snapshots, strict=True)
    )
    transport = replace(wire, references=references)
    if transport.recompute_execution_fingerprint() != wire.execution_fingerprint:
        raise FrozenRequestIntegrityError(
            "loading changed the ProviderWireRequest execution fingerprint"
        )
    return transport


def _snapshot_payload(snapshot: FrozenReferenceSnapshot) -> dict[str, Any]:
    return {
        "index": snapshot.index,
        "content_sha256": snapshot.content_sha256,
        "locator": snapshot.locator,
        "byte_length": snapshot.byte_length,
    }


def _manifest_payload(
    *,
    request_id: str,
    created_at: str,
    submitted_at: str,
    preparation_version: str,
    source_version: str,
    request_version: str,
    status: str,
    wire: ProviderWireRequest,
    snapshots: tuple[FrozenReferenceSnapshot, ...],
    idempotency_key: str | None,
) -> dict[str, Any]:
    return {
        "discriminator": FROZEN_REQUEST_DISCRIMINATOR,
        "schema_version": FROZEN_REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "created_at": created_at,
        "submitted_at": submitted_at,
        "preparation_version": preparation_version,
        "source_version": source_version,
        "request_version": request_version,
        "submission_status": status,
        "result_link": None,
        "provenance_link": None,
        "idempotency_key": idempotency_key,
        "execution_fingerprint": wire.execution_fingerprint,
        "wire_request": json.loads(wire.to_json()),
        "reference_snapshots": [_snapshot_payload(snapshot) for snapshot in snapshots],
    }


def _validate_manifest_payload(raw: Any, request_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FrozenRequestIntegrityError("frozen request manifest must be an object")
    stored_digest = raw.get("manifest_sha256")
    if not isinstance(stored_digest, str):
        raise FrozenRequestIntegrityError("frozen request manifest has no digest")
    unsigned = dict(raw)
    unsigned.pop("manifest_sha256", None)
    actual_digest = _canonical_digest(unsigned)
    if actual_digest != stored_digest:
        raise FrozenRequestIntegrityError(
            f"frozen request manifest digest mismatch: expected {stored_digest}, got {actual_digest}"
        )
    if raw.get("discriminator") != FROZEN_REQUEST_DISCRIMINATOR:
        raise FrozenRequestIntegrityError("not a frozen request manifest")
    if raw.get("schema_version") != FROZEN_REQUEST_SCHEMA_VERSION:
        raise FrozenRequestIntegrityError(
            f"unsupported frozen request schema: {raw.get('schema_version')}"
        )
    if raw.get("request_id") != request_id:
        raise FrozenRequestIntegrityError("frozen request id does not match its directory")
    return raw


def _load_manifest_payload_at(request_fd: int, request_id: str) -> dict[str, Any]:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        manifest_fd = os.open(
            MANIFEST_FILENAME,
            os.O_RDONLY | nofollow,
            dir_fd=request_fd,
        )
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"frozen request manifest is unreadable: {request_id}"
        ) from exc
    try:
        try:
            raw = json.loads(
                _read_regular_fd(
                    manifest_fd,
                    label=f"{request_id}/{MANIFEST_FILENAME}",
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenRequestIntegrityError(
                f"invalid frozen request manifest: {request_id}"
            ) from exc
    finally:
        os.close(manifest_fd)
    return _validate_manifest_payload(raw, request_id)


def _load_manifest_payload(project_dir: Path, request_id: str) -> dict[str, Any]:
    with _request_directory_fd(project_dir, request_id) as request_fd:
        return _load_manifest_payload_at(request_fd, request_id)


def _locator_digest(locator: str) -> str:
    parsed = PurePosixPath(locator)
    if (
        parsed.is_absolute()
        or ".." in parsed.parts
        or len(parsed.parts) != 2
        or parsed.parts[0] != BLOBS_DIRNAME
    ):
        raise FrozenRequestIntegrityError(f"invalid frozen snapshot locator: {locator!r}")
    _validate_digest(parsed.parts[1])
    return parsed.parts[1]


def _status_payload_at(request_fd: int, request_id: str) -> dict[str, Any] | None:
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        status_fd = os.open(STATUS_FILENAME, os.O_RDONLY | nofollow, dir_fd=request_fd)
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise FrozenRequestIntegrityError(
            f"frozen request status is unreadable: {request_id}"
        ) from exc
    try:
        try:
            raw = json.loads(
                _read_regular_fd(
                    status_fd,
                    label=f"{request_id}/{STATUS_FILENAME}",
                ).decode("utf-8")
            )
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FrozenRequestIntegrityError(
                f"invalid frozen request status: {request_id}"
            ) from exc
    finally:
        os.close(status_fd)
    if not isinstance(raw, dict):
        raise FrozenRequestIntegrityError("frozen request status must be an object")
    return raw


def _status_payload(project_dir: Path, request_id: str) -> dict[str, Any] | None:
    with _request_directory_fd(project_dir, request_id) as request_fd:
        return _status_payload_at(request_fd, request_id)


def _load_frozen_request_at(
    project_dir: Path,
    request_id: str,
    request_store_fd: int,
    request_fd: int,
) -> FrozenGenerationRequest:
    raw = _load_manifest_payload_at(request_fd, request_id)
    try:
        wire = ProviderWireRequest.from_json(json.dumps(raw["wire_request"]))
        snapshots = tuple(
            FrozenReferenceSnapshot(
                index=int(item["index"]),
                content_sha256=str(item["content_sha256"]),
                locator=str(item["locator"]),
                byte_length=int(item["byte_length"]),
            )
            for item in raw["reference_snapshots"]
        )
    except (KeyError, TypeError, ValueError, ProviderWireError, json.JSONDecodeError) as exc:
        raise FrozenRequestIntegrityError("invalid frozen request contents") from exc

    if len(wire.references) != len(snapshots):
        raise FrozenRequestIntegrityError("wire references and snapshots are not one-to-one")
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    with _blob_fd_at(request_store_fd, create=False) as blob_fd:
        for index, (reference, snapshot) in enumerate(zip(wire.references, snapshots, strict=True)):
            if (
                reference.index != index
                or snapshot.index != index
                or reference.source_path != snapshot.locator
                or reference.content_sha256 != snapshot.content_sha256
            ):
                raise FrozenRequestIntegrityError("frozen reference order or digest does not match manifest")
            _validate_digest(snapshot.content_sha256)
            if _locator_digest(snapshot.locator) != snapshot.content_sha256 or blob_fd is None:
                raise FrozenRequestIntegrityError("frozen snapshot blob is unavailable")
            try:
                snapshot_fd = os.open(
                    snapshot.content_sha256,
                    os.O_RDONLY | nofollow,
                    dir_fd=blob_fd,
                )
            except OSError as exc:
                raise FrozenRequestIntegrityError(
                    f"frozen snapshot blob is unreadable for reference {index}"
                ) from exc
            try:
                data = _read_regular_fd(
                    snapshot_fd,
                    label=snapshot.locator,
                    expected_digest=snapshot.content_sha256,
                )
            finally:
                os.close(snapshot_fd)
            if len(data) != snapshot.byte_length:
                raise FrozenRequestIntegrityError(
                    f"frozen snapshot byte length mismatch for reference {index}"
                )

    execution_fingerprint = raw.get("execution_fingerprint")
    if execution_fingerprint != wire.execution_fingerprint:
        raise FrozenRequestIntegrityError("manifest execution fingerprint mismatch")

    status = raw.get("submission_status", "submitted")
    result_link = raw.get("result_link")
    provenance_link = raw.get("provenance_link")
    job_id = None
    status_override = _status_payload_at(request_fd, request_id)
    if status_override is not None:
        if status_override.get("request_id") != request_id:
            raise FrozenRequestIntegrityError("frozen request status id mismatch")
        status = status_override.get("status", status)
        if status not in {"submitted", "queued", "running", "complete", "failed", "retained"}:
            raise FrozenRequestIntegrityError("invalid frozen request status")
        result_link = _safe_record_link(status_override.get("result_link", result_link))
        provenance_link = _safe_record_link(status_override.get("provenance_link", provenance_link))
        job_id = status_override.get("job_id")

    return FrozenGenerationRequest(
        request_id=request_id,
        created_at=str(raw["created_at"]),
        submitted_at=str(raw["submitted_at"]),
        preparation_version=str(raw["preparation_version"]),
        source_version=str(raw["source_version"]),
        request_version=str(raw["request_version"]),
        status=str(status),
        wire=_transport_wire(wire, snapshots, project_dir),
        execution_fingerprint=str(execution_fingerprint),
        snapshots=snapshots,
        manifest_sha256=str(raw["manifest_sha256"]),
        idempotency_key=raw.get("idempotency_key"),
        result_link=result_link,
        provenance_link=provenance_link,
        job_id=job_id,
    )


def load_frozen_request(project_dir: Path, request_id: str) -> FrozenGenerationRequest:
    """Load, verify, and materialize one request within one authorized project."""
    with _request_store_fds(project_dir, create=False) as request_store_fd:
        if request_store_fd is None:
            raise FrozenRequestNotFound(f"frozen request not found: {request_id}")
        with _request_directory_at(request_store_fd, request_id) as request_fd:
            return _load_frozen_request_at(
                project_dir,
                request_id,
                request_store_fd,
                request_fd,
            )


def _iter_request_ids_at(request_store_fd: int) -> list[str]:
    result: list[str] = []
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
    for name in os.listdir(request_store_fd):
        if name == BLOBS_DIRNAME or name.startswith("."):
            continue
        try:
            request_fd = os.open(name, directory_flags, dir_fd=request_store_fd)
        except OSError as exc:
            raise FrozenRequestIntegrityError(
                f"invalid request store entry: {name}"
            ) from exc
        else:
            os.close(request_fd)
        if _REQUEST_ID_RE.fullmatch(name):
            result.append(name)
    return sorted(result)


def _iter_request_ids(project_dir: Path) -> list[str]:
    with _request_store_fds(project_dir, create=False) as request_store_fd:
        if request_store_fd is None:
            return []
        return _iter_request_ids_at(request_store_fd)


def _find_frozen_request_by_idempotency_key_at(
    project_dir: Path,
    idempotency_key: str,
    request_store_fd: int,
) -> FrozenGenerationRequest | None:
    for request_id in _iter_request_ids_at(request_store_fd):
        with _request_directory_at(request_store_fd, request_id) as request_fd:
            request = _load_frozen_request_at(
                project_dir,
                request_id,
                request_store_fd,
                request_fd,
            )
        if request.idempotency_key == idempotency_key:
            return request
    return None


def find_frozen_request_by_idempotency_key(
    project_dir: Path, idempotency_key: str,
) -> FrozenGenerationRequest | None:
    _validate_idempotency_key(idempotency_key)
    with _request_store_fds(project_dir, create=False) as request_store_fd:
        if request_store_fd is None:
            return None
        return _find_frozen_request_by_idempotency_key_at(
            project_dir,
            idempotency_key,
            request_store_fd,
        )


def submit_frozen_request(
    project_dir: Path,
    wire: ProviderWireRequest,
    *,
    idempotency_key: str | None = None,
    request_id: str | None = None,
    preparation_version: str = FROZEN_REQUEST_PREPARATION_VERSION,
    source_version: str = FROZEN_REQUEST_SOURCE_VERSION,
    request_version: str = FROZEN_REQUEST_VERSION,
) -> FrozenGenerationRequest:
    """Stage selected bytes and atomically publish an immutable request manifest."""
    _validate_idempotency_key(idempotency_key)
    if wire.execution_fingerprint != wire.recompute_execution_fingerprint():
        raise FrozenRequestIntegrityError("ProviderWireRequest execution fingerprint mismatch")

    with _REQUEST_LOCK, _store_lock(project_dir) as request_store_fd:
        if idempotency_key is not None:
            existing = _find_frozen_request_by_idempotency_key_at(
                project_dir,
                idempotency_key,
                request_store_fd,
            )
            if existing is not None:
                if existing.execution_fingerprint != wire.execution_fingerprint:
                    raise FrozenRequestIdempotencyConflict(
                        f"idempotency key {idempotency_key!r} already names a different request"
                    )
                return existing

        frozen_id = request_id or uuid.uuid4().hex
        _validate_request_id(frozen_id)

        snapshots: list[FrozenReferenceSnapshot] = []
        for index, reference in enumerate(wire.references):
            if reference.index != index:
                raise FrozenRequestIntegrityError("ProviderWireRequest reference indices are not contiguous")
            _validate_digest(reference.content_sha256)
            source = Path(reference.source_path)
            data = _read_source_snapshot(project_dir, source)
            actual = hashlib.sha256(data).hexdigest()
            if actual != reference.content_sha256:
                raise FrozenRequestIntegrityError(
                    f"selected reference {index} digest mismatch: expected "
                    f"{reference.content_sha256}, got {actual}"
                )
            _stage_blob(
                project_dir,
                actual,
                data,
                request_store_fd=request_store_fd,
            )
            snapshots.append(
                FrozenReferenceSnapshot(
                    index=index,
                    content_sha256=actual,
                    locator=f"{BLOBS_DIRNAME}/{actual}",
                    byte_length=len(data),
                )
            )

        snapshot_tuple = tuple(snapshots)
        portable_wire = _portable_wire(wire, snapshot_tuple)
        now = datetime.now(UTC).isoformat()
        unsigned = _manifest_payload(
            request_id=frozen_id,
            created_at=now,
            submitted_at=now,
            preparation_version=preparation_version,
            source_version=source_version,
            request_version=request_version,
            status="submitted",
            wire=portable_wire,
            snapshots=snapshot_tuple,
            idempotency_key=idempotency_key,
        )
        manifest = {
            **unsigned,
            "manifest_sha256": _canonical_digest(unsigned),
        }
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | nofollow
        staging_name: str | None = None
        staging_fd = -1
        try:
            try:
                existing_fd = os.open(
                    frozen_id,
                    directory_flags,
                    dir_fd=request_store_fd,
                )
            except FileNotFoundError:
                pass
            except OSError as exc:
                raise FrozenRequestIntegrityError(
                    f"frozen request already exists or is linked: {frozen_id}"
                ) from exc
            else:
                os.close(existing_fd)
                raise FrozenRequestError(f"frozen request already exists: {frozen_id}")

            staging_name = f".staging-{frozen_id}-{uuid.uuid4().hex}"
            os.mkdir(staging_name, dir_fd=request_store_fd)
            staging_fd = os.open(staging_name, directory_flags, dir_fd=request_store_fd)
            _atomic_write_at(
                staging_fd,
                MANIFEST_FILENAME,
                _canonical_bytes(manifest),
            )
            os.replace(
                staging_name,
                frozen_id,
                src_dir_fd=request_store_fd,
                dst_dir_fd=request_store_fd,
            )
            staging_name = None
            os.fsync(request_store_fd)
        except BaseException:
            if staging_fd >= 0:
                try:
                    os.unlink(MANIFEST_FILENAME, dir_fd=staging_fd)
                except FileNotFoundError:
                    pass
            if staging_name is not None:
                try:
                    os.rmdir(staging_name, dir_fd=request_store_fd)
                except FileNotFoundError:
                    pass
            raise
        finally:
            if staging_fd >= 0:
                os.close(staging_fd)

        with _request_directory_at(request_store_fd, frozen_id) as request_fd:
            frozen = _load_frozen_request_at(
                project_dir,
                frozen_id,
                request_store_fd,
                request_fd,
            )

    return frozen


def _safe_record_link(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or "://" in value or "?" in value or "#" in value:
        raise FrozenRequestError("result/provenance links must be opaque relative references")
    parsed = PurePosixPath(value)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise FrozenRequestError("result/provenance links must stay project-scoped")
    return value


def update_frozen_request_status(
    project_dir: Path,
    request_id: str,
    status: str,
    *,
    result_link: str | None = None,
    provenance_link: str | None = None,
    job_id: str | None = None,
) -> None:
    """Update mutable lifecycle metadata without rewriting the frozen manifest."""
    with _REQUEST_LOCK:
        with _request_store_fds(project_dir, create=False) as request_store_fd:
            if request_store_fd is None:
                raise FrozenRequestNotFound(f"frozen request not found: {request_id}")
            with _request_directory_at(request_store_fd, request_id) as request_fd:
                current = _load_frozen_request_at(
                    project_dir,
                    request_id,
                    request_store_fd,
                    request_fd,
                )
                if status not in {"submitted", "queued", "running", "complete", "failed", "retained"}:
                    raise FrozenRequestError(f"invalid frozen request status: {status!r}")
                payload = {
                    "schema_version": FROZEN_REQUEST_SCHEMA_VERSION,
                    "request_id": request_id,
                    "status": status,
                    "updated_at": datetime.now(UTC).isoformat(),
                    "result_link": _safe_record_link(
                        result_link if result_link is not None else current.result_link
                    ),
                    "provenance_link": _safe_record_link(
                        provenance_link if provenance_link is not None else current.provenance_link
                    ),
                    "job_id": job_id if job_id is not None else current.job_id,
                }
                _atomic_write_at(
                    request_fd,
                    STATUS_FILENAME,
                    _canonical_bytes(payload),
                )


async def execute_frozen_request(
    project_dir: Path,
    request_id: str,
    *,
    config: Config,
    output_path: Path,
    feature: str = "image.frozen_request",
) -> ApiResult[Any]:
    """Run the exact persisted wire request; no prompt/reference discovery occurs here."""
    try:
        output_path.resolve(strict=False).relative_to(project_dir.resolve())
    except ValueError as exc:
        raise FrozenRequestError("frozen generation output must stay project-scoped") from exc
    request = load_frozen_request(project_dir, request_id)
    update_frozen_request_status(project_dir, request_id, "running")
    try:
        from novel_to_comic.ai import generate_wire_image

        result = await generate_wire_image(
            config=config,
            wire=request.wire,
            output_path=output_path,
            feature=feature,
        )
    except BaseException:
        update_frozen_request_status(project_dir, request_id, "failed")
        raise

    result_link = None
    try:
        result_link = str(output_path.relative_to(project_dir))
    except ValueError:
        pass
    update_frozen_request_status(
        project_dir, request_id, "complete", result_link=result_link,
    )
    return result


def gc_unreferenced_blobs(project_dir: Path) -> list[str]:
    """Remove only regular content blobs not referenced by a valid request."""
    with _REQUEST_LOCK, _store_lock(project_dir) as request_store_fd:
        nofollow = getattr(os, "O_NOFOLLOW", 0)
        with _blob_fd_at(request_store_fd, create=False) as blob_fd:
            if blob_fd is None:
                return []
            referenced: set[str] = set()
            for request_id in _iter_request_ids_at(request_store_fd):
                with _request_directory_at(request_store_fd, request_id) as request_fd:
                    request = _load_frozen_request_at(
                        project_dir,
                        request_id,
                        request_store_fd,
                        request_fd,
                    )
                    referenced.update(
                        snapshot.locator.removeprefix(f"{BLOBS_DIRNAME}/")
                        for snapshot in request.snapshots
                    )

            removed: list[str] = []
            for name in os.listdir(blob_fd):
                if name in referenced:
                    continue
                try:
                    candidate_fd = os.open(name, os.O_RDONLY | nofollow, dir_fd=blob_fd)
                except OSError:
                    continue
                try:
                    candidate_stat = os.fstat(candidate_fd)
                    if not stat.S_ISREG(candidate_stat.st_mode) or candidate_stat.st_nlink != 1:
                        continue
                    os.unlink(name, dir_fd=blob_fd)
                    removed.append(name)
                finally:
                    os.close(candidate_fd)
            return sorted(removed)


__all__ = [
    "BLOBS_DIRNAME",
    "FROZEN_REQUEST_DISCRIMINATOR",
    "FROZEN_REQUEST_PREPARATION_VERSION",
    "FROZEN_REQUEST_SCHEMA_VERSION",
    "FROZEN_REQUEST_SOURCE_VERSION",
    "FROZEN_REQUEST_VERSION",
    "FrozenGenerationRequest",
    "FrozenReferenceSnapshot",
    "FrozenRequestError",
    "FrozenRequestIdempotencyConflict",
    "FrozenRequestIntegrityError",
    "FrozenRequestNotFound",
    "blob_path",
    "execute_frozen_request",
    "find_frozen_request_by_idempotency_key",
    "gc_unreferenced_blobs",
    "load_frozen_request",
    "manifest_path",
    "request_blob_path",
    "request_directory",
    "requests_root",
    "status_path",
    "submit_frozen_request",
    "update_frozen_request_status",
]
