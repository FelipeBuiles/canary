"""Bounded checksum reuse for unchanged local files and open downloads.

Size alone or mtime alone cannot establish integrity. Reuse a computed digest
only for the same device/inode, size, nanosecond mtime and nanosecond ctime.
Atomic replacement and in-place changes (even restored mtime) invalidate it.
Recent files are always hashed: kernel timestamps can share a coarse clock tick.
The cache is process-local; every process verifies bytes on its first read.
"""

from collections import OrderedDict
import hashlib
import os
from pathlib import Path
import threading
from time import time_ns

_digests = OrderedDict()
_guard = threading.Lock()
_MAX_FILES = 4096
_QUIET_NS = 2_000_000_000


def _identity(stream):
    stat = os.fstat(stream.fileno())
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)


def verified_stream(stream, expected_sha256: str, *, byte_size: int | None = None) -> bool:
    identity = _identity(stream)
    if byte_size is not None and identity[2] != byte_size:
        return False
    # Nanosecond fields need not advance for writes in the same filesystem tick.
    # Only reuse settled POSIX timestamps; a recent edit requires actual bytes.
    cacheable = 0 < identity[4] and max(identity[3:]) < time_ns() - _QUIET_NS
    with _guard:
        digest = _digests.get(identity) if cacheable else None
        if digest is not None:
            _digests.move_to_end(identity)
        elif not cacheable:
            _digests.pop(identity, None)
    if digest is None:
        stream.seek(0)
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if _identity(stream) != identity:
            return False
        if cacheable:
            with _guard:
                _digests[identity] = digest
                _digests.move_to_end(identity)
                while len(_digests) > _MAX_FILES:
                    _digests.popitem(last=False)
    return _identity(stream) == identity and digest == expected_sha256


def verified_file(path: Path, expected_sha256: str, *, byte_size: int | None = None) -> bool:
    try:
        with path.open("rb") as stream:
            return verified_stream(stream, expected_sha256, byte_size=byte_size)
    except OSError:
        return False
