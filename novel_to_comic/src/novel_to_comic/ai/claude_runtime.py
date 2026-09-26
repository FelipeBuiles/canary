"""Optional, single-turn Claude Code transport; never an API fallback.

Runs the locally installed ``claude`` CLI in print mode against the developer's
claude.ai subscription login. Text only: Claude Code has no image generation.
The process gets an allowlisted environment (never ``ANTHROPIC_*``), an empty
working directory, no tools, no MCP servers, no user/project settings, no
CLAUDE.md, and no session persistence. Authentication is checked before the
prompt is sent and the effective session is checked against Claude Code's init
event; any mismatch fails closed. No credential files are inspected.

Claude Opus 5.5 request quirks this transport keeps in step with the API route
(``text_models.py``): thinking is always on and is never configured here;
effort is sent explicitly because the model's default is ``medium``; the output
limit includes the thinking headroom; and structured output relies on Claude
Code's own schema support because forced ``tool_choice`` is a 400 on this model.
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import signal
import tempfile
from typing import Any

from novel_to_comic.ai.errors import AIRefusalError

EXECUTION_VERSION = "canary-claude-cli-v1"
PROVIDER = "canary_claude_subscription"
TEXT_TIMEOUT_SECONDS = 900
PREFLIGHT_TIMEOUT_SECONDS = 30
# One subscription session executes at a time (``_LOCK`` in-process, an flock
# across processes). Callers size their work to this, not to their own limits.
PARALLEL_CALLS = 1
TERMINATE_GRACE_SECONDS = 5
MAX_LINE_BYTES = 64 * 1024 * 1024
MAX_EVENTS = 512
EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})
# USER is required for the macOS keychain lookup that holds the OAuth login.
_ENV_KEYS = ("HOME", "USER", "PATH", "LANG", "LC_ALL")
# Only the structured-output tool Claude Code adds for --json-schema may exist.
_STRUCTURED_OUTPUT_TOOL = re.compile(r"(?i)^structured_?output$")
# Claude Code's local answer when its stored token is missing or unreadable.
_LOGIN_REQUIRED = re.compile(r"(?i)^\s*(not logged in|invalid api key|please run /login)")
_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class ClaudeTextResult:
    text: str
    input_tokens: int | None
    output_tokens: int | None
    cache_read_input_tokens: int | None
    cache_creation_input_tokens: int | None
    model: str | None
    metadata: dict[str, Any]


class ClaudeRuntimeError(RuntimeError):
    """Sanitized failure with submission/usage evidence, including ambiguity."""

    def __init__(self, code: str, metadata: dict[str, Any] | None = None):
        self.code = code
        self.metadata = metadata or {}
        provider = self.metadata.get("provider_error", {})
        reason = provider.get("message") if isinstance(provider, dict) else None
        if code == "runtime_timeout" and self.metadata.get("timeout_seconds"):
            super().__init__(f"{code}: Canary stopped the request after "
                             f"{self.metadata['timeout_seconds']} seconds without a completed result.")
        else:
            super().__init__(f"{code}: {reason}" if reason else code)


class ClaudeRuntimeRefusalError(ClaudeRuntimeError, AIRefusalError):
    """Explicit model refusal retaining Claude Code submission and usage evidence."""


def _diagnostic(message: Any, request: dict[str, Any]) -> str | None:
    # One redaction policy for both subscription transports.
    from novel_to_comic.ai.codex_runtime import _diagnostic_message

    return _diagnostic_message(message, request)


def _parent_environment() -> dict[str, str]:
    from novel_to_comic import codex_dev as authority

    try:
        authority.validate_local_runtime()
    except authority.CodexRoutingError:
        raise ClaudeRuntimeError("local_runtime_forbidden") from None
    env = {key: value for key in _ENV_KEYS if (value := authority.process_setting(key)) is not None}
    # Background traffic (autoupdate, telemetry, error reporting) is not part
    # of the measured request.
    env.update(CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1", DISABLE_AUTOUPDATER="1")
    return env


def _executable(env: dict[str, str]) -> str:
    import shutil

    path = shutil.which("claude", path=env.get("PATH"))
    if path is None:
        raise ClaudeRuntimeError("cli_unavailable")
    return path


def _user_message(prompt: str, references: tuple[tuple[bytes, str], ...]) -> dict[str, Any]:
    from novel_to_comic.ai.codex_runtime import CodexRuntimeError, validate_image_bytes

    content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
    for data, mime in references:
        try:
            validate_image_bytes(data, mime)
        except CodexRuntimeError as exc:
            raise ClaudeRuntimeError(exc.code) from exc
        content.append({"type": "image", "source": {
            "type": "base64", "media_type": mime, "data": base64.b64encode(data).decode("ascii"),
        }})
    return {"type": "user", "message": {"role": "user", "content": content},
            "parent_tool_use_id": None}


def _argv(executable: str, request: dict[str, Any]) -> list[str]:
    args = [
        executable, "--print",
        "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
        "--model", request["model"],
        "--system-prompt", request["system_prompt"],
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "local",
        "--safe-mode",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--permission-mode", "dontAsk",
    ]
    if request["effort"] is not None:
        args += ["--effort", request["effort"]]
    if request["schema"] is not None:
        args += ["--json-schema", json.dumps(request["schema"], separators=(",", ":"))]
    return args


async def _terminate(process: asyncio.subprocess.Process) -> None:
    # The child owns its own session. No unrelated process IDs are addressed.
    try:
        os.kill(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=TERMINATE_GRACE_SECONDS)
    except asyncio.TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


async def _preflight(executable: str, env: dict[str, str], cwd: Path, evidence: dict[str, Any]) -> None:
    """Reject non-subscription logins before any prompt leaves the machine.

    ``auth status`` reads the stored account, not the token: a claude.ai
    account whose token is missing or unreadable still reports logged in.
    That case surfaces from the turn itself (see ``_completed``).
    """

    async def run(*args: str) -> bytes:
        process = await asyncio.create_subprocess_exec(
            executable, *args, cwd=cwd, env=env, start_new_session=True,
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), PREFLIGHT_TIMEOUT_SECONDS)
        except BaseException:
            await asyncio.shield(_terminate(process))
            raise
        return stdout

    version = (await run("--version")).decode("utf-8", "replace").strip()
    evidence["cli_version"] = version.split(" ", 1)[0][:32] if version else None
    try:
        status = json.loads(await run("auth", "status", "--json"))
    except ValueError:
        raise ClaudeRuntimeError("auth_status_unreadable") from None
    if not isinstance(status, dict):
        raise ClaudeRuntimeError("auth_status_unreadable")
    # Only non-identifying fields are retained.
    evidence["auth"] = {key: status.get(key) for key in ("loggedIn", "authMethod", "apiProvider", "subscriptionType")}
    if status.get("loggedIn") is not True or status.get("authMethod") != "claude.ai":
        raise ClaudeRuntimeError("claude_subscription_auth_required", evidence)
    if status.get("apiProvider") != "firstParty":
        raise ClaudeRuntimeError("effective_provider_conflict", evidence)


def _check_init(event: dict[str, Any], request: dict[str, Any], evidence: dict[str, Any]) -> None:
    tools = event.get("tools") or []
    servers = event.get("mcp_servers") or []
    evidence["init_checks"] = {
        "model": event.get("model"), "api_key_source": event.get("apiKeySource"),
        "tools": [str(tool)[:64] for tool in tools][:32],
        "mcp_server_count": len(servers), "permission_mode": event.get("permissionMode"),
    }
    if event.get("apiKeySource") not in (None, "none"):
        # An API key would bill the account instead of the subscription.
        raise ClaudeRuntimeError("effective_api_key_conflict", evidence)
    if event.get("model") != request["model"]:
        raise ClaudeRuntimeError("effective_model_conflict", evidence)
    if servers:
        raise ClaudeRuntimeError("mcp_isolation_failed", evidence)
    def allowed(name):
        return request["schema"] is not None and bool(_STRUCTURED_OUTPUT_TOOL.match(str(name)))

    if any(not allowed(tool) for tool in tools):
        raise ClaudeRuntimeError("effective_tool_isolation_failed", evidence)


def _model_usage(result: dict[str, Any], model: str, evidence: dict[str, Any]) -> dict[str, int | None]:
    """Token usage of the requested model; auxiliary models stay evidence."""
    raw_by_model = result.get("modelUsage")
    by_model: dict[str, Any] = raw_by_model if isinstance(raw_by_model, dict) else {}
    auxiliary = {name: usage for name, usage in by_model.items() if name != model}
    if auxiliary:
        evidence["auxiliary_model_usage"] = auxiliary
    selected = by_model.get(model)
    if isinstance(selected, dict):
        fields = {"input_tokens": "inputTokens", "output_tokens": "outputTokens",
                  "cache_read_input_tokens": "cacheReadInputTokens",
                  "cache_creation_input_tokens": "cacheCreationInputTokens"}
        return {name: _tokens(selected.get(key)) for name, key in fields.items()}
    raw_usage = result.get("usage")
    usage: dict[str, Any] = raw_usage if isinstance(raw_usage, dict) else {}
    if auxiliary:
        # The aggregate would attribute another model's tokens to this one.
        return dict.fromkeys(("input_tokens", "output_tokens", "cache_read_input_tokens",
                              "cache_creation_input_tokens"))
    return {name: _tokens(usage.get(name)) for name in (
        "input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}


def _tokens(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _refusal(event: dict[str, Any]) -> bool:
    message = event.get("message")
    return isinstance(message, dict) and message.get("stop_reason") == "refusal"


async def run_text(*, model: str, system_prompt: str, user_content: str,
                   json_schema: dict[str, Any] | None = None,
                   image_attachments: tuple[tuple[bytes, str], ...] = (),
                   effort: str | None = None,
                   max_output_tokens: int | None = None) -> ClaudeTextResult:
    from novel_to_comic.ai.anthropic_schema import anthropic_output_schema

    if not re.fullmatch(r"claude-[a-z0-9][a-z0-9-]{0,63}", model):
        raise ClaudeRuntimeError("invalid_model_selector")
    if effort is not None and effort not in EFFORTS:
        raise ClaudeRuntimeError("invalid_effort")
    if max_output_tokens is not None and (type(max_output_tokens) is not int or max_output_tokens <= 0):
        raise ClaudeRuntimeError("invalid_max_output_tokens")
    request = {
        "model": model, "system_prompt": system_prompt, "prompt": user_content,
        "effort": effort, "max_output_tokens": max_output_tokens,
        # The same normalization the API route sends as output_config.format.
        "schema": anthropic_output_schema(json_schema) if json_schema is not None else None,
    }
    message = _user_message(user_content, image_attachments)
    result = await _run(request, message)
    return ClaudeTextResult(
        result["text"], result["input_tokens"], result["output_tokens"],
        result["cache_read_input_tokens"], result["cache_creation_input_tokens"],
        result["model"], result["metadata"],
    )


async def _run(request: dict[str, Any], message: dict[str, Any]) -> dict[str, Any]:
    import fcntl

    async with _LOCK:
        # Parent-only: request context stays in this process.
        from novel_to_comic.ai.context import notify_execution_started

        evidence: dict[str, Any] = {
            "execution_version": EXECUTION_VERSION, "transport_profile": PROVIDER,
            "funding": "claude_subscription", "submitted": False, "indeterminate": False,
            "model": request["model"], "effort": request["effort"] or "model_default",
            "max_output_tokens": request["max_output_tokens"],
            "structured_output": "cli_json_schema" if request["schema"] is not None else None,
            "references": len(message["message"]["content"]) - 1,
            "timeout_seconds": TEXT_TIMEOUT_SECONDS, "events": {},
        }
        lock_path = Path(tempfile.gettempdir()) / f"canary-claude-{os.getuid()}.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ClaudeRuntimeError("runtime_busy") from None
            notify_execution_started()
            with tempfile.TemporaryDirectory(prefix="canary-claude-") as temp:
                return await _execute(Path(temp).resolve(), request, message, evidence)
        finally:
            os.close(lock_fd)


async def _execute(root: Path, request: dict[str, Any], message: dict[str, Any],
                   evidence: dict[str, Any]) -> dict[str, Any]:
    workspace = root / "workspace"
    workspace.mkdir()
    env = _parent_environment()
    executable = _executable(env)
    await _preflight(executable, env, workspace, evidence)
    if request["max_output_tokens"] is not None:
        env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"] = str(request["max_output_tokens"])
    stderr_path = root / "stderr.log"
    started = asyncio.get_running_loop().time()
    with stderr_path.open("wb") as stderr:
        process = await asyncio.create_subprocess_exec(
            *_argv(executable, request), cwd=workspace, env=env, start_new_session=True,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=stderr,
            limit=MAX_LINE_BYTES,
        )
    result: dict[str, Any] | None = None
    try:
        evidence.update(submitted=None, indeterminate=True)
        assert process.stdin is not None and process.stdout is not None
        process.stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        await process.stdin.drain()
        # EOF ends the session after this single turn.
        process.stdin.close()
        evidence["submitted"] = True
        result = await asyncio.wait_for(_read_turn(process, request, evidence), TEXT_TIMEOUT_SECONDS)
        await asyncio.wait_for(process.wait(), TERMINATE_GRACE_SECONDS)
    except asyncio.TimeoutError:
        await asyncio.shield(_terminate(process))
        evidence["process_group_terminated"] = True
        if result is not None:
            # The turn completed; only process exit lagged.
            evidence["recovered_after_timeout"] = True
        else:
            _record_stderr(stderr_path, request, evidence)
            raise ClaudeRuntimeError("runtime_timeout", evidence) from None
    except asyncio.CancelledError as exc:
        await asyncio.shield(_terminate(process))
        evidence["process_group_terminated"] = True
        exc.metadata = evidence
        raise
    except BaseException:
        await asyncio.shield(_terminate(process))
        evidence["process_group_terminated"] = True
        _record_stderr(stderr_path, request, evidence)
        raise
    finally:
        evidence["execution_elapsed_seconds"] = round(asyncio.get_running_loop().time() - started, 3)
    assert result is not None
    evidence["exit_code"] = process.returncode
    return result


def _record_stderr(path: Path, request: dict[str, Any], evidence: dict[str, Any]) -> None:
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - 4096))
            tail = handle.read().decode("utf-8", "replace").strip().splitlines()
    except OSError:
        return
    diagnostic = _diagnostic(tail[-1] if tail else None, request)
    if diagnostic:
        evidence["stderr_diagnostic"] = diagnostic


async def _read_turn(process: asyncio.subprocess.Process, request: dict[str, Any],
                     evidence: dict[str, Any]) -> dict[str, Any]:
    assert process.stdout is not None
    initialized = False
    refused = False
    served_models: set[str] = set()
    count = 0
    while True:
        line = await process.stdout.readline()
        if not line:
            raise ClaudeRuntimeError("result_missing", evidence)
        try:
            event = json.loads(line)
        except ValueError:
            raise ClaudeRuntimeError("invalid_stream_event", evidence) from None
        if not isinstance(event, dict):
            raise ClaudeRuntimeError("invalid_stream_event", evidence)
        kind = f"{event.get('type')}:{event.get('subtype')}" if event.get("subtype") else str(event.get("type"))
        kind = kind[:64]
        evidence["events"][kind] = evidence["events"].get(kind, 0) + 1
        count += 1
        if count > MAX_EVENTS:
            raise ClaudeRuntimeError("event_limit_exceeded", evidence)
        if event.get("type") == "system" and event.get("subtype") == "init":
            _check_init(event, request, evidence)
            evidence["session_id"] = event.get("session_id")
            initialized = True
        elif event.get("type") == "assistant":
            if not initialized:
                raise ClaudeRuntimeError("init_missing", evidence)
            model = (event.get("message") or {}).get("model")
            # Claude Code labels its own local notices "<synthetic>".
            if isinstance(model, str) and model != "<synthetic>":
                served_models.add(model)
            refused = refused or _refusal(event)
        elif event.get("type") == "result":
            return _completed(event, request, evidence, served_models, refused)


def _completed(event: dict[str, Any], request: dict[str, Any], evidence: dict[str, Any],
               served_models: set[str], refused: bool) -> dict[str, Any]:
    evidence.update(indeterminate=False, turn_status=event.get("subtype"))
    for field in ("duration_ms", "duration_api_ms", "num_turns"):
        if type(event.get(field)) is int:
            evidence[field] = event[field]
    cost = event.get("total_cost_usd")
    # Claude Code's own API-rate estimate; nothing was charged for it.
    evidence["cli_reported_cost_usd"] = cost if isinstance(cost, (int, float)) else None
    usage = _model_usage(event, request["model"], evidence)
    evidence["usage"] = usage
    evidence["served_models"] = sorted(served_models)
    if served_models - {request["model"]}:
        raise ClaudeRuntimeError("effective_model_conflict", evidence)
    if refused:
        evidence["provider_error"] = {"code": "refusal"}
        raise ClaudeRuntimeRefusalError("model_refusal", evidence)
    if event.get("is_error") and not served_models and _LOGIN_REQUIRED.match(str(event.get("result") or "")):
        # Claude Code answers locally when it holds no usable token; nothing
        # reached the provider, so the call was never submitted.
        evidence.update(submitted=False, provider_error={
            "code": "not_logged_in",
            "message": "Claude Code has no usable claude.ai token. Run `claude auth login` in a "
                       "terminal (as the user running the server), then retry.",
        })
        raise ClaudeRuntimeError("claude_subscription_auth_required", evidence)
    if event.get("is_error") or event.get("subtype") != "success":
        diagnostic: dict[str, Any] = {"code": str(event.get("subtype"))[:64]}
        errors = event.get("errors")
        reason = _diagnostic(errors[0] if isinstance(errors, list) and errors else event.get("result"), request)
        if reason:
            diagnostic["message"] = reason
        evidence["provider_error"] = diagnostic
        raise ClaudeRuntimeError("turn_not_completed", evidence)
    structured = event.get("structured_output")
    if request["schema"] is not None and structured is not None:
        text = json.dumps(structured, ensure_ascii=False)
        evidence["structured_output_source"] = "structured_output"
    else:
        text = event.get("result")
        if request["schema"] is not None:
            # The caller's schema validation still decides; no request is repeated.
            evidence["structured_output_source"] = "result_text"
    if not isinstance(text, str) or not text:
        raise ClaudeRuntimeError("text_output_missing", evidence)
    return {"text": text, "model": request["model"], "metadata": evidence, **usage}
