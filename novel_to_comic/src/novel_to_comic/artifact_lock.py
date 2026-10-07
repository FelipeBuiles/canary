"""Reentrant process/thread-safe serialization of production artifact mutations.

Lock files live outside stage output directories so invalidation cannot unlink a
held lock. This is a filesystem lock, not a second generation lifecycle.
"""

from __future__ import annotations

import fcntl
import threading
from contextlib import contextmanager
from functools import wraps
from pathlib import Path

_registry_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}
_local = threading.local()


@contextmanager
def production_lock(project_dir: Path):
    # A series is the artifact transaction boundary. Part writes and shared
    # look/style writes must never acquire independent locks in reverse order.
    # Provider execution remains outside this short commit/read lock.
    from .workspace import series_root
    project_dir = series_root(Path(project_dir)).resolve()
    key = str(project_dir.resolve())
    with _registry_guard:
        lock = _thread_locks.setdefault(key, threading.RLock())
    with lock:
        held = getattr(_local, "held", set())
        if key in held:
            yield
            return
        path = project_dir / ".locks" / "production.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            _local.held = held | {key}
            try:
                yield
            finally:
                _local.held = held
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def locked_mutation(function):
    """Works on TargetArtifacts methods or functions whose first arg is one."""

    @wraps(function)
    def locked(artifacts, *args, **kwargs):
        with production_lock(artifacts.project_dir):
            return function(artifacts, *args, **kwargs)

    return locked
