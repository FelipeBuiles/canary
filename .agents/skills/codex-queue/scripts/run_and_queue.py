#!/usr/bin/env python3
"""Run a detached command and queue one terminal callback to its Codex session."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_status(path: Path, status: dict[str, Any]) -> None:
    fd, temporary_name = tempfile.mkstemp(
        prefix=".status-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(status, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def append(path: Path, content: str) -> None:
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()


def validate_queue_cli() -> str:
    codex = shutil.which("codex")
    if not codex:
        raise RuntimeError("codex CLI is not available on PATH")
    try:
        result = subprocess.run(
            [codex, "queue", "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"cannot validate codex queue: {exc}") from exc
    if result.returncode or "--thread" not in result.stdout or "--message" not in result.stdout:
        raise RuntimeError("codex queue must support --thread and --message")
    return codex


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a detached command and queue its terminal result."
    )
    parser.add_argument("--thread", required=True, help="exact originating session ID/name")
    parser.add_argument("--cwd", required=True, help="explicit command working directory")
    parser.add_argument("--job-dir", required=True, help="new directory for job artifacts")
    parser.add_argument("--label", required=True, help="short job label")
    parser.add_argument("--follow-up", required=True, help="next authorized action")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument(
        "--connectivity-exit-code",
        type=int,
        action="append",
        default=[],
        help="nonzero watcher exit code that specifically means lost connectivity",
    )
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--codex-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("provide a command after --")
    if not args.thread.strip():
        parser.error("--thread cannot be empty")
    if args.timeout_seconds is not None and args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    return args


def paths(args: argparse.Namespace) -> tuple[Path, Path, Path, Path]:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.is_dir():
        raise ValueError(f"working directory does not exist: {cwd}")
    job_dir = Path(args.job_dir).expanduser()
    if not job_dir.is_absolute():
        job_dir = cwd / job_dir
    job_dir = job_dir.resolve()
    return cwd, job_dir, job_dir / "status.json", job_dir / "output.log"


def notify(args: argparse.Namespace, codex: str, job_dir: Path,
           outcome: str, exit_code: int | None, status_path: Path) -> None:
    queue_path = job_dir / "queue.log"
    code_text = f" (exit code {exit_code})" if exit_code is not None else ""
    message = (
        f"Job {job_dir.name} ({args.label}) reached terminal outcome: {outcome}{code_text}. "
        f"Artifacts: {job_dir}. Read status.json and output.log before continuing. "
        f"Next authorized action: {args.follow_up}"
    )
    notification = "failed"
    try:
        with queue_path.open("a", encoding="utf-8") as log:
            log.write(f"=== callback attempt {now()} ===\n")
            log.write(f"message: {message}\n")
            result = subprocess.run(
                [codex, "queue", "--thread", args.thread, "--message", message],
                cwd=args.cwd,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=30,
                check=False,
            )
            log.write(f"exit_code: {result.returncode}\n")
            notification = "sent" if result.returncode == 0 else "failed"
    except (OSError, subprocess.TimeoutExpired) as exc:
        append(queue_path, f"callback delivery error: {exc}\n")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status["notification"] = notification
    status["notification_attempted_at"] = now()
    write_status(status_path, status)


def finish(args: argparse.Namespace, codex: str, job_dir: Path, status_path: Path,
           outcome: str, exit_code: int | None) -> None:
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({"outcome": outcome, "exit_code": exit_code, "finished_at": now()})
    write_status(status_path, status)
    notify(args, codex, job_dir, outcome, exit_code, status_path)


def stop_process_group(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=5)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass


def run_worker(args: argparse.Namespace) -> int:
    cwd, job_dir, status_path, output_path = paths(args)
    status = json.loads(status_path.read_text(encoding="utf-8"))
    status.update({"worker_pid": os.getpid(), "started_at": now(), "outcome": "running"})
    write_status(status_path, status)
    codex = args.codex_path or validate_queue_cli()
    child: subprocess.Popen[bytes] | None = None
    cancelled = False

    def on_signal(_signum: int, _frame: Any) -> None:
        nonlocal cancelled
        cancelled = True
        if child is not None:
            stop_process_group(child)

    signal.signal(signal.SIGTERM, on_signal)
    signal.signal(signal.SIGINT, on_signal)
    append(output_path, f"=== started {now()} ===\n=== cwd: {cwd} ===\n")
    append(output_path, f"=== argv: {json.dumps(args.command)} ===\n")

    try:
        with output_path.open("ab") as output:
            try:
                child = subprocess.Popen(
                    args.command,
                    cwd=cwd,
                    stdin=subprocess.DEVNULL,
                    stdout=output,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    close_fds=True,
                )
            except OSError as exc:
                append(output_path, f"[command launch error] {exc}\n")
                outcome, exit_code = "launch_error", None
            else:
                deadline = time.monotonic() + args.timeout_seconds if args.timeout_seconds else None
                timed_out = False
                while child.poll() is None:
                    if cancelled:
                        break
                    if deadline is not None and time.monotonic() >= deadline:
                        timed_out = True
                        stop_process_group(child)
                        break
                    time.sleep(0.1)
                if child.poll() is None:
                    stop_process_group(child)
                exit_code = child.returncode
                outcome = (
                    "cancelled" if cancelled else "timed_out" if timed_out
                    else "succeeded" if exit_code == 0
                    else "lost_connectivity"
                    if exit_code in args.connectivity_exit_code
                    else "failed"
                )
    except Exception as exc:
        append(output_path, f"[worker error] {exc}\n")
        outcome, exit_code = "failed", None

    finish(args, codex, job_dir, status_path, outcome, exit_code)
    return 0 if outcome == "succeeded" else 1


def dispatch(args: argparse.Namespace) -> int:
    cwd, job_dir, status_path, output_path = paths(args)
    codex = validate_queue_cli()
    if job_dir.exists():
        raise ValueError(f"refusing to overwrite existing job directory: {job_dir}")
    job_dir.mkdir(parents=True)
    (job_dir / "queue.log").touch()
    output_path.touch()
    write_status(status_path, {
        "job_id": job_dir.name,
        "label": args.label,
        "command": args.command,
        "cwd": str(cwd),
        "job_dir": str(job_dir),
        "worker_pid": None,
        "started_at": None,
        "finished_at": None,
        "outcome": "dispatching",
        "exit_code": None,
        "notification": "pending",
        "artifacts": {
            "output": str(output_path),
            "status": str(status_path),
            "queue": str(job_dir / "queue.log"),
        },
    })

    command = [
        sys.executable, str(Path(__file__).resolve()), "--worker",
        "--thread", args.thread, "--cwd", str(cwd), "--job-dir", str(job_dir),
        "--label", args.label, "--follow-up", args.follow_up,
        "--codex-path", codex,
    ]
    if args.timeout_seconds is not None:
        command += ["--timeout-seconds", str(args.timeout_seconds)]
    for exit_code in args.connectivity_exit_code:
        command += ["--connectivity-exit-code", str(exit_code)]
    command += ["--", *args.command]
    try:
        worker = subprocess.Popen(
            command, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True,
        )
    except OSError as exc:
        append(output_path, f"[worker launch error] {exc}\n")
        finish(args, codex, job_dir, status_path, "launch_error", None)
        return 1

    print(f"launched pid={worker.pid} job_dir={job_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_worker(args) if args.worker else dispatch(args)
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"codex-queue: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
