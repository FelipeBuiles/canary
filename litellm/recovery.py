"""Durable *process* recovery budget; never reads or mutates paid work.

This is deliberately separate from jobs. Fly restarts nonzero container exits;
this guard bounds those restarts even across container replacement. A healthy
supervisor clears the budget only after continuous local web health. Operators
may explicitly reset an exhausted budget after diagnosis with ``reset``.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time


def read_state(path: Path) -> dict:
    if not path.exists():
        return {}
    value = json.loads(path.read_text())
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("invalid recovery state; operator inspection required")
    return value


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    with temporary.open("w") as stream:
        json.dump(state, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def transition(state: dict, event: str, *, now: float, limit: int = 3,
               backoff: float = 2, backoff_max: float = 30,
               stable_seconds: float = 300, release: str = "unknown") -> tuple[dict, float]:
    state = dict(state)
    state.update(schema=1, last_observed_at=now)
    delay = 0.0
    if event == "begin":
        if state.get("running"):
            state["restart_count"] = state.get("restart_count", 0) + 1
            state["last_exit_reason"] = "unexpected_exit"
        count = state.get("restart_count", 0)
        if state.get("budget_exhausted") or count > limit:
            state.update(budget_exhausted=True, running=False)
        else:
            delay = min(backoff_max, backoff * 2 ** (count - 1)) if count else 0
            state.update(running=True, boot_started_at=now, healthy_since=None,
                         release=release, budget_exhausted=False)
    elif event == "healthy":
        since = state.get("healthy_since")
        if since is None:
            state["healthy_since"] = now
        elif now - since >= stable_seconds:
            state["restart_count"] = 0
    elif event == "unhealthy":
        state["healthy_since"] = None
    elif event == "crash":
        state["last_exit_reason"] = "unexpected_exit"
        if state.get("restart_count", 0) >= limit:
            state["budget_exhausted"] = True
    elif event == "stop":
        state.update(running=False, last_exit_reason="intentional_stop")
    elif event == "reset":
        state.update(running=False, restart_count=0, budget_exhausted=False,
                     last_exit_reason="operator_reset")
    elif event.startswith("gateway_"):
        state["gateway_status"] = event.removeprefix("gateway_")
    else:
        raise ValueError("unknown recovery event")
    return state, delay


def main() -> int:
    path = Path(os.environ.get("CANARY_RECOVERY_STATE", "/projects/.ops/recovery.json"))
    try:
        event = sys.argv[1]
        state = read_state(path)
        reset_id = os.environ.get("CANARY_RECOVERY_RESET_ID", "")
        if event == "begin" and reset_id and reset_id != state.get("last_reset_id"):
            state, _ = transition(state, "reset", now=time.time())
            state["last_reset_id"] = reset_id
        state, delay = transition(
            state, event, now=time.time(),
            limit=int(os.environ.get("CANARY_RESTART_LIMIT", "3")),
            backoff=float(os.environ.get("CANARY_RESTART_BACKOFF_SECONDS", "2")),
            backoff_max=float(os.environ.get("CANARY_RESTART_BACKOFF_MAX_SECONDS", "30")),
            stable_seconds=float(os.environ.get("CANARY_RESTART_STABLE_SECONDS", "300")),
            release=os.environ.get("FLY_IMAGE_REF", "unknown"),
        )
        save_state(path, state)
    except (OSError, ValueError, IndexError, TypeError):
        # Fail closed without dumping file contents or environment secrets.
        print("[recovery] cannot safely read/write recovery state; inspect durable state", file=sys.stderr)
        return 75
    if event == "begin" and state.get("budget_exhausted"):
        print("[recovery] restart budget exhausted; operator diagnosis and reset required", file=sys.stderr)
        return 75
    if event == "begin":
        print(delay)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
