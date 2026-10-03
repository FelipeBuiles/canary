"""Safety contracts at the Codex boundary, using no SDK, server, or network."""
import asyncio
import base64
import hashlib
import io
import json
import sys
import tomllib
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from PIL import Image

from novel_to_comic.ai import codex_runtime as runtime


def _png(color="red", size=(17, 23)):
    output = io.BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return output.getvalue()


class _Record(SimpleNamespace):
    pass


@pytest.fixture
def sdk(monkeypatch, tmp_path):
    """Implement the supported low-level protocol, not generation or API fallback."""
    generated = ModuleType("openai_codex.generated.v2_all")
    for name in (
        "AgentMessageThreadItem", "ChatgptAccount", "ConfigReadResponse",
        "ErrorNotification", "ImageGenerationThreadItem", "ItemCompletedNotification",
        "ItemStartedNotification", "ThreadTokenUsageUpdatedNotification", "TurnCompletedNotification",
        "ModelProviderCapabilitiesReadResponse", "ExperimentalFeatureListResponse",
    ):
        setattr(generated, name, type(name, (_Record,), {}))
    state = SimpleNamespace(
        types=generated, events=[], turns=[], interrupts=[], threads=[],
        config_change=lambda config: None, chatgpt=True,
        models=[_Record(model="exact-model", input_modalities=["text", "image"],
                        service_tiers=[_Record(id="priority")])],
        thread_model=None, thread_provider=None, thread_service_tier=None, notification_reads=0,
        plan="plus", capabilities={"image_generation": True, "namespace_tools": True},
        feature_pages={None: _Record(data=[_Record(name="image_generation", enabled=True)], next_cursor=None)},
        parent_run=runtime._run,
    )

    class Client:
        def __init__(self, config):
            self.config = config

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def initialize(self):
            pass

        async def request(self, method, params, *, response_model):
            if method == "modelProvider/capabilities/read":
                return _Record(**state.capabilities, model_dump=lambda **kwargs: dict(state.capabilities))
            if method == "experimentalFeature/list":
                return state.feature_pages[params["cursor"]]
            assert method == "config/read"
            config = tomllib.loads("\n".join(self.config.launch_args_override))
            state.config_change(config)
            return _Record(config=_Record(model_dump=lambda **kwargs: config))

        async def account_read(self, params):
            account = generated.ChatgptAccount(plan_type=state.plan) if state.chatgpt else _Record(type="apiKey")
            return _Record(account=_Record(root=account))

        async def model_list(self, **kwargs):
            return _Record(data=state.models)

        async def thread_start(self, params):
            state.threads.append(params)
            return _Record(
                model=state.thread_model or params["model"],
                model_provider=state.thread_provider or params["modelProvider"],
                service_tier=state.thread_service_tier or params["serviceTier"],
                instruction_sources=[], thread=_Record(id="thread-1"),
                sandbox=_Record(root=_Record(type="readOnly", network_access=False)),
            )

        async def turn_start(self, thread_id, inputs, params):
            state.turns.append((thread_id, inputs, params))
            return _Record(turn=_Record(id="turn-1"))

        async def next_turn_notification(self, turn_id):
            state.notification_reads += 1
            if not state.events:
                raise AssertionError("Runtime requested another event after the terminal result")
            event = state.events.pop(0)
            if isinstance(event, BaseException):
                raise event
            return _Record(payload=event)

        async def turn_interrupt(self, thread_id, turn_id):
            state.interrupts.append((thread_id, turn_id))
            if getattr(state, "cancel_interrupt", False):
                raise asyncio.CancelledError()

    modules = {
        "openai_codex": ModuleType("openai_codex"),
        "openai_codex.async_client": ModuleType("openai_codex.async_client"),
        "openai_codex.client": ModuleType("openai_codex.client"),
        "openai_codex.generated": ModuleType("openai_codex.generated"),
        "openai_codex.generated.v2_all": generated,
    }
    modules["openai_codex.async_client"].AsyncCodexClient = Client
    modules["openai_codex.client"].CodexConfig = _Record
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    # These are fake client arguments, never a bundled CLI or OS sandbox launch.
    monkeypatch.setattr(runtime, "_sdk_launch", lambda overrides: overrides)

    async def execute(request):
        state.request = request
        evidence = {"submitted": False, "indeterminate": False, "events": [], "funding": "codex_subscription"}
        evidence["execution_fingerprint"] = runtime.EXECUTION_FINGERPRINT
        try:
            return await runtime._execute(tmp_path, request, evidence)
        except runtime.CodexRuntimeError as exc:
            # The real child serializes this evidence into its error envelope.
            exc.metadata = {**evidence, **exc.metadata}
            raise

    monkeypatch.setattr(runtime, "_run", execute)
    return state


def _generate(**kwargs):
    return asyncio.run(runtime.run_image(
        reasoning_model="exact-model", prompt="A red square", references=(), request_id="request-1", **kwargs,
        reference_roles=(), reference_instructions=(),
    ))


def _image_event(sdk, *, data=None, encoded=None, status="completed", saved_path=None, item_id="image-1"):
    item = sdk.types.ImageGenerationThreadItem(
        id=item_id, type="imageGeneration", status=status,
        result=encoded if encoded is not None else base64.b64encode(data or _png()).decode(),
        revised_prompt="A red square", saved_path=_Record(root=str(saved_path)) if saved_path is not None else None,
    )
    return sdk.types.ItemCompletedNotification(item=_Record(root=item))


def _usage(sdk):
    return sdk.types.ThreadTokenUsageUpdatedNotification(
        token_usage=_Record(total=_Record(input_tokens=31, output_tokens=7)),
    )


def _completed(sdk):
    return sdk.types.TurnCompletedNotification(turn=_Record(status=_Record(value="completed")))


def test_decoded_image_dimensions_and_digest_are_authoritative():
    data = _png(size=(13, 29))
    info = runtime.validate_image_bytes(data, "image/png")
    assert (info["width"], info["height"], info["mime"]) == (13, 29, "image/png")
    assert info["sha256"] == hashlib.sha256(data).hexdigest()
    assert info["bytes"] == len(data)


@pytest.mark.parametrize("case", ["empty", "oversized", "mime", "truncated", "pixel_limit"])
def test_invalid_reference_bytes_never_reach_sdk(monkeypatch, case):
    data, mime = _png(), "image/png"
    if case == "empty":
        data = b""
    elif case == "oversized":
        monkeypatch.setattr(runtime, "MAX_IMAGE_BYTES", len(data) - 1)
    elif case == "mime":
        mime = "image/jpeg"
    elif case == "truncated":
        data = data[:40]
    else:
        # A real compressed image exceeding the decoded-pixel boundary.
        output = io.BytesIO()
        Image.new("1", (8001, 5000)).save(output, format="PNG")
        data = output.getvalue()

    async def forbidden(request):
        pytest.fail("Invalid reference crossed the submission boundary")

    monkeypatch.setattr(runtime, "_run", forbidden)
    with pytest.raises(runtime.CodexRuntimeError, match="invalid_image"):
        asyncio.run(runtime.run_image(
            reasoning_model="exact-model", prompt="draw", references=((data, mime),), request_id="r",
            reference_roles=("style",), reference_instructions=("Rendering only.",),
        ))


@pytest.mark.parametrize("change", ["selector", "overflow"])
def test_unavailable_selector_and_reference_overflow_fail_before_submit(monkeypatch, change):
    async def forbidden(request):
        pytest.fail("Unsupported request reached the runtime")

    monkeypatch.setattr(runtime, "_run", forbidden)
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        asyncio.run(runtime.run_image(
            reasoning_model="exact-model", prompt="draw", request_id="r",
            references=((_png(), "image/png"),) * 6 if change == "overflow" else (),
            reference_roles=("style",) * 6 if change == "overflow" else (),
            reference_instructions=("Rendering only.",) * 6 if change == "overflow" else (),
            requested_model="gpt-image-2.5" if change == "selector" else "gpt-image-2",
        ))
    assert failure.value.code == ("reference_limit_exceeded" if change == "overflow" else "unsupported_image_selector")


@pytest.mark.parametrize("boundary", [
    "account", "model", "thread_model", "thread_provider", "paid_endpoint",
    "retries", "shell", "free_plan", "image_capability", "namespace_capability", "image_modality",
])
def test_effective_auth_model_and_tool_conflicts_never_start_turn(sdk, boundary):
    if boundary == "account":
        sdk.chatgpt = False
    elif boundary == "free_plan":
        sdk.plan = "free"
    elif boundary == "image_capability":
        sdk.capabilities["image_generation"] = False
    elif boundary == "namespace_capability":
        sdk.capabilities["namespace_tools"] = False
    elif boundary == "image_modality":
        sdk.models = [_Record(model="exact-model", input_modalities=["text"],
                              service_tiers=[_Record(id="priority")])]
    elif boundary == "model":
        sdk.models = [_Record(model="exact-model-newer", input_modalities=["image"])]
    elif boundary == "thread_model":
        sdk.thread_model = "exact-model-newer"
    elif boundary == "thread_provider":
        sdk.thread_provider = "openai"
    elif boundary == "paid_endpoint":
        sdk.config_change = lambda config: config.update(openai_base_url="https://api.openai.com/v1")
    elif boundary == "retries":
        sdk.config_change = lambda config: config["model_providers"][runtime.PROVIDER].update(request_max_retries=1)
    else:
        sdk.config_change = lambda config: config["features"].update(shell_tool=True)
    with pytest.raises(runtime.CodexRuntimeError):
        _generate()
    assert sdk.turns == []


@pytest.mark.parametrize("enabled", [False, None])
def test_effective_image_feature_must_be_enabled_before_turn(sdk, enabled):
    sdk.feature_pages[None] = _Record(
        data=[] if enabled is None else [_Record(name="image_generation", enabled=enabled)],
        next_cursor=None,
    )
    with pytest.raises(runtime.CodexRuntimeError, match="effective_image_generation_unavailable") as failure:
        _generate()
    assert failure.value.metadata["submitted"] is False
    assert sdk.turns == []


def test_effective_tool_reenabled_on_later_feature_page_blocks_turn(sdk):
    sdk.feature_pages[None].next_cursor = "page-2"
    sdk.feature_pages["page-2"] = _Record(
        data=[_Record(name="shell_tool", enabled=True)], next_cursor=None,
    )
    with pytest.raises(runtime.CodexRuntimeError, match="effective_tool_isolation_failed") as failure:
        _generate()
    assert failure.value.metadata["submitted"] is False
    assert sdk.turns == []


@pytest.mark.parametrize("shell_enabled", [False, None, True])
def test_unified_exec_flag_is_safe_only_with_effective_shell_tool_off(sdk, shell_enabled):
    request = {
        "kind": "image", "model": "exact-model", "prompt": "", "references": [],
        "operation": "create", "reference_authorities": [], "request_id": "preflight",
        "preflight_only": True,
    }
    sdk.feature_pages[None].data = [
        _Record(name="image_generation", enabled=True),
        _Record(name="unified_exec", enabled=True),
    ]
    if shell_enabled is not None:
        sdk.feature_pages[None].data.append(_Record(name="shell_tool", enabled=shell_enabled))
    if shell_enabled is False:
        result = asyncio.run(runtime._run(request))
        assert result["metadata"]["effective_features"]["unified_exec"] is True
    else:
        with pytest.raises(runtime.CodexRuntimeError, match="effective_tool_isolation_failed") as failure:
            asyncio.run(runtime._run(request))
        assert failure.value.metadata["enabled_tool_conflicts"] == (
            ["unified_exec"] if shell_enabled is None else ["shell_tool", "unified_exec"]
        )
    assert sdk.turns == []


def test_first_terminal_image_returns_without_agent_prose_or_regeneration(sdk):
    data = _png(size=(13, 29))
    sdk.events = [_usage(sdk), _image_event(sdk, data=data)]
    result = _generate()
    assert result.image_bytes == data
    assert (result.input_tokens, result.output_tokens) == (31, 7)
    assert result.metadata["actual_image_model"] is None
    assert result.metadata["indeterminate"] is False
    assert result.metadata["image"]["width"] == 13
    assert result.metadata["image"]["height"] == 29
    assert sdk.interrupts == [("thread-1", "turn-1")]
    assert len(sdk.turns) == 1
    assert sdk.notification_reads == 2


@pytest.mark.parametrize("artifact", ["base64", "bytes", "failed", "missing"])
def test_unusable_terminal_image_retains_usage_without_regeneration(sdk, artifact):
    sdk.events = [_usage(sdk)]
    if artifact == "missing":
        sdk.events.append(_completed(sdk))
    elif artifact == "base64":
        sdk.events.append(_image_event(sdk, encoded="not base64!"))
    elif artifact == "bytes":
        sdk.events.append(_image_event(sdk, data=b"not an image"))
    else:
        sdk.events.append(_image_event(sdk, status="failed"))
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate()
    assert failure.value.code == {
        "missing": "image_output_missing", "base64": "invalid_image_base64",
        "bytes": "invalid_image_bytes", "failed": "image_tool_failed",
    }[artifact]
    assert failure.value.metadata["submitted"] is True
    assert (failure.value.metadata["input_tokens"], failure.value.metadata["output_tokens"]) == (31, 7)
    assert len(sdk.turns) == 1
    if artifact != "missing":
        assert sdk.interrupts


@pytest.mark.parametrize("result,classification", [
    ('{"error":{"code":"content_policy_violation","message":"Scene declined"}}', "provider_blocked"),
    ("Image generation failed: service unavailable", "service_unavailable"),
    ("Image generation failed for an unknown reason", "generation_error"),
])
def test_failed_image_retains_tool_reason_without_retry(sdk, result, classification):
    from novel_to_comic.image_failure import classify_image_failure

    sdk.events = [_usage(sdk), _image_event(sdk, status="failed", encoded=result)]
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate()
    error = failure.value
    assert error.code == "image_tool_failed"
    assert error.metadata["image_tool_status"] == "failed"
    assert error.metadata["image_tool_error"]["message"] in str(error)
    assert error.metadata["image_tool_error"]["result_sha256"] == hashlib.sha256(result.encode()).hexdigest()
    assert classify_image_failure(error) == classification
    assert error.metadata["submitted"] is True
    assert (error.metadata["input_tokens"], error.metadata["output_tokens"]) == (31, 7)
    assert len(sdk.turns) == 1
    assert sdk.notification_reads == 2
    assert sdk.interrupts == [("thread-1", "turn-1")]


def test_silent_failed_image_is_classified_as_provider_block(sdk):
    from novel_to_comic.image_failure import classify_image_failure

    sdk.events = [_usage(sdk), _image_event(sdk, status="failed", encoded="")]
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate()
    error = failure.value
    assert error.code == "image_tool_failed"
    assert error.metadata["image_tool_error"]["result_kind"] == "empty"
    assert "silently rejected" in str(error)
    assert classify_image_failure(error) == "provider_blocked"
    assert len(sdk.turns) == 1


def test_failed_image_usage_limit_is_rate_limited(sdk):
    from novel_to_comic.image_failure import classify_image_failure

    item = sdk.types.ImageGenerationThreadItem(
        id="image-1", type="imageGeneration", status="failed", result="", revised_prompt=None,
        saved_path=None,
        failure=_Record(root=_Record(type="usageLimitExceeded", limit_id="images", resets_at=1790000000)),
    )
    sdk.events = [_usage(sdk), sdk.types.ItemCompletedNotification(item=_Record(root=item))]
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate()
    error = failure.value
    assert error.metadata["image_tool_failure"] == {"type": "usageLimitExceeded", "resets_at": 1790000000}
    assert "silently rejected" not in str(error)
    assert classify_image_failure(error) == "rate_limited"


@pytest.mark.parametrize("result", [
    "Failure: A red square sk-private-token https://private.example/token\nprivate tail",
    json.dumps({"error": {"message": "Failure: A red square sk-private-token"}, "request": "private body"}),
    json.dumps({"request": "private body"}),
    base64.b64encode(_png()).decode(),
    "data:image/png;base64," + base64.b64encode(_png()).decode(),
])
def test_failed_image_diagnostics_exclude_payloads(sdk, result):
    sdk.events = [_image_event(sdk, status="failed", encoded=result)]
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate()
    diagnostic = failure.value.metadata["image_tool_error"]
    encoded = json.dumps(diagnostic)
    for private in ("A red square", "sk-private-token", "https://private.example", "private tail", "private body", base64.b64encode(_png()).decode()):
        assert private not in encoded
    assert len(diagnostic.get("message", "")) <= 512


def test_failed_image_reason_survives_child_and_parent(sdk, monkeypatch, supported_host, tmp_path):
    sdk.events = [_image_event(sdk, status="failed", encoded=json.dumps({
        "error": {"code": "content_policy_violation", "message": "Scene declined"},
    }))]
    persisted = []

    class Process:
        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        root = Path(kwargs["cwd"])
        await runtime._child(root)
        persisted.append(json.loads((root / "result.json").read_text()))
        return Process()

    monkeypatch.setattr(runtime, "_run", sdk.parent_run)
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda package: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(runtime.CodexRuntimeError, match="content_policy_violation: Scene declined") as failure:
        _generate()
    assert persisted[0]["metadata"]["image_tool_error"] == failure.value.metadata["image_tool_error"]
    assert failure.value.metadata["thread_id"] == "thread-1"
    assert failure.value.metadata["tool_id"] == "image-1"
    assert len(sdk.turns) == 1


@pytest.mark.parametrize("phase", ["final_answer", None])
@pytest.mark.parametrize("reason_kind", ["safe", "long", "absent", "redacted"])
@pytest.mark.parametrize("diagnostics", [False, True])
def test_missing_image_reason_survives_child_and_parent(
    sdk, monkeypatch, supported_host, tmp_path, phase, reason_kind, diagnostics,
):
    reason = "Image generation failed due to a tool parameter constraint."
    private = "sk-test-credential-never-persist"
    text = {
        "safe": f"{reason} A red square {private} https://private-host/?token=private-token",
        "long": reason + " more context" * 100,
        "absent": None,
        "redacted": f"Authorization: Bearer {private}",
    }[reason_kind]
    sdk.events = [
        _usage(sdk),
        sdk.types.ItemCompletedNotification(item=_Record(root=_Record(
            id="user-1", type="userMessage", text="private user transcript",
        ))),
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="commentary-1", type="agentMessage", phase=_Record(value="commentary"),
            text="private commentary transcript",
        ))),
    ]
    if text is not None:
        sdk.events.append(sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="final-1", type="agentMessage", phase=_Record(value=phase) if phase else None, text=text,
        ))))
    sdk.events.append(_completed(sdk))
    child_errors = []
    persisted = []
    execute = runtime._execute

    async def capture_execute(*args):
        try:
            return await execute(*args)
        except runtime.CodexRuntimeError as exc:
            child_errors.append(exc)
            raise

    class Process:
        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        root = Path(kwargs["cwd"])
        await runtime._child(root)
        persisted.extend((root / name).read_text() for name in ("evidence.json", "result.json"))
        return Process()

    monkeypatch.setattr(runtime, "_run", sdk.parent_run)
    monkeypatch.setattr(runtime, "_execute", capture_execute)
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda package: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        _generate(diagnostics=diagnostics)
    for exc in (*child_errors, failure.value):
        assert exc.code == "image_output_missing"
        assert "Codex returned no image" in str(exc)
        assert "provider_error" not in exc.metadata
        if reason_kind in ("safe", "long"):
            assert reason in exc.metadata["assistant_response_diagnostic"]
            assert len(exc.metadata["assistant_response_diagnostic"]) <= 512
            assert exc.metadata["assistant_response_diagnostic"] in str(exc)
        else:
            assert "assistant_response_diagnostic" not in exc.metadata
            assert "Assistant response" not in str(exc)
        assert exc.metadata["submitted"] is True
        assert exc.metadata["indeterminate"] is False
        assert exc.metadata["turn_status"] == "completed"
        assert (exc.metadata["input_tokens"], exc.metadata["output_tokens"]) == (31, 7)
        assert exc.metadata["image_tool_usage_available"] is False
    exposed = "\n".join(persisted + [str(exc) + json.dumps(exc.metadata) for exc in (*child_errors, failure.value)])
    for forbidden in (
        private, "A red square", "private-host", "private-token",
        "private user transcript", "private commentary transcript", "Authorization",
    ):
        assert forbidden not in exposed
    assert len(child_errors) == len(sdk.turns) == 1
    assert sdk.interrupts == []


@pytest.mark.parametrize("reference_count", [0, 1, 5])
def test_image_tool_arguments_exclude_application_metadata(sdk, reference_count):
    data = _png()
    sdk.events = [_image_event(sdk, data=data)]
    result = asyncio.run(runtime.run_image(
        reasoning_model="exact-model", prompt="A red square",
        references=((data, "image/png"),) * reference_count, request_id="request-1",
        reference_roles=("style",) * reference_count,
        reference_instructions=("Use rendering style only.",) * reference_count,
    ))
    specification = json.loads(sdk.turns[0][1][0]["text"])
    arguments = specification["image_tool_arguments"]
    assert arguments == (
        {"prompt": "A red square", "num_last_images_to_include": reference_count}
        if reference_count else {"prompt": "A red square"}
    )
    assert len(sdk.turns[0][1]) == reference_count + 1
    assert result.image_bytes == data
    assert len(sdk.turns) == 1


@pytest.mark.parametrize("escape", ["outside", "sibling_prefix", "symlink"])
def test_saved_artifact_provenance_must_resolve_inside_image_store(sdk, tmp_path, escape):
    store = Path.home() / ".codex" / "generated_images"
    store.mkdir(parents=True)
    outside = tmp_path / "outside.png"
    outside.write_bytes(_png())
    if escape == "outside":
        saved = outside
    elif escape == "sibling_prefix":
        saved = store.with_name("generated_images_other") / "image.png"
    else:
        saved = store / "linked.png"
        saved.symlink_to(outside)
    sdk.events = [_usage(sdk), _image_event(sdk, saved_path=saved)]
    with pytest.raises(runtime.CodexRuntimeError, match="image_saved_path_escape") as failure:
        _generate()
    assert failure.value.metadata["submitted"] is True
    assert failure.value.metadata["output_tokens"] == 7
    assert sdk.interrupts
    assert len(sdk.turns) == 1


def test_reference_evidence_preserves_order_and_byte_identity(sdk):
    refs = ((_png("blue"), "image/png"), (_png("red"), "image/png"))
    sdk.events = [_image_event(sdk, saved_path=Path.home() / ".codex/generated_images/image.png")]
    result = asyncio.run(runtime.run_image(
        reasoning_model="exact-model", prompt="draw", references=refs, request_id="r",
        reference_roles=("style", "subject"),
        reference_instructions=("Rendering only.", "Canonical anatomy."),
    ))
    assert [(ref["index"], ref["sha256"]) for ref in result.metadata["references"]] == [
        (index, hashlib.sha256(data).hexdigest()) for index, (data, _) in enumerate(refs)
    ]
    assert result.metadata["saved_path"] == str(Path.home() / ".codex/generated_images/image.png")


@pytest.mark.parametrize("will_retry", [False, True])
def test_error_notification_preserves_usage_and_does_not_retry(sdk, will_retry):
    sdk.events = [_usage(sdk), sdk.types.ErrorNotification(will_retry=will_retry)]
    with pytest.raises(runtime.CodexRuntimeError, match="runtime_turn_error") as failure:
        _generate()
    assert failure.value.metadata["input_tokens"] == 31
    assert failure.value.metadata["output_tokens"] == 7
    assert failure.value.metadata["submitted"] is True
    assert failure.value.metadata["indeterminate"] is True
    assert len(sdk.turns) == 1
    assert sdk.interrupts


@pytest.mark.parametrize("terminal", ["error_notification", "failed_turn"])
@pytest.mark.parametrize("message_format", ["plain", "http_envelope", "long"])
def test_provider_reason_survives_child_and_parent_without_secrets(
    sdk, monkeypatch, supported_host, tmp_path, terminal, message_format,
):
    reason = "Invalid schema for response_format: additionalProperties must be false."
    secret = "sk-test-credential-never-persist"
    prompt = "private novel passage never persist"
    error = _Record(
        message=f"{reason} Authorization: Bearer {secret}\n"
                f"Request body: {{\"prompt\": \"{prompt}\", \"cookie\": \"private-cookie\"}}",
        additional_details="raw HTTP body private-additional-details",
        codex_error_info=_Record(root=(
            _Record(value="badRequest") if terminal == "error_notification" else
            _Record(http_connection_failed=_Record(http_status_code=400))
        )),
    )
    if message_format == "http_envelope":
        error.message = "unexpected status 400 Bad Request: " + json.dumps({
            "error": {"message": error.message, "private": "private-http-body"},
            "prompt": prompt, "credentials": secret,
        }) + ", url: https://private-host/?token=private-url-token"
    elif message_format == "long":
        error.message = reason + " extra diagnostic context" * 100
    event = (
        sdk.types.ErrorNotification(will_retry=False, error=error)
        if terminal == "error_notification" else
        sdk.types.TurnCompletedNotification(turn=_Record(status=_Record(value="failed"), error=error))
    )
    sdk.events = [_usage(sdk), event]
    child_errors = []
    persisted = []
    execute = runtime._execute

    async def capture_execute(*args):
        try:
            return await execute(*args)
        except runtime.CodexRuntimeError as exc:
            child_errors.append(exc)
            raise

    class Process:
        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        root = Path(kwargs["cwd"])
        await runtime._child(root)
        persisted.extend((root / name).read_text() for name in ("evidence.json", "result.json"))
        return Process()

    monkeypatch.setattr(runtime, "_run", sdk.parent_run)
    monkeypatch.setattr(runtime, "_execute", capture_execute)
    monkeypatch.setattr(runtime.importlib.metadata, "version", lambda package: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, "gettempdir", lambda: str(tmp_path))
    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        asyncio.run(runtime.run_text(model="exact-model", system_prompt="Private instructions", user_content=prompt))
    expected_code = "runtime_turn_error" if terminal == "error_notification" else "turn_not_completed"
    assert failure.value.code == child_errors[0].code == expected_code
    for exc in (child_errors[0], failure.value):
        assert reason in str(exc)
        diagnostic = exc.metadata["provider_error"]
        assert reason in diagnostic["message"]
        assert len(diagnostic["message"]) <= 512
        assert diagnostic["code"] == ("badRequest" if terminal == "error_notification" else "httpConnectionFailed")
        if terminal == "failed_turn":
            assert diagnostic["http_status_code"] == 400
        assert exc.metadata["input_tokens"] == 31
        assert exc.metadata["submitted"] is True
    exposed = "\n".join(persisted + [str(exc) + json.dumps(exc.metadata) for exc in child_errors + [failure.value]])
    for forbidden in (
        secret, prompt, "private-cookie", "private-additional-details", "Request body",
        "private-http-body", "private-url-token", "private-host",
    ):
        assert forbidden not in exposed
    assert len(sdk.turns) == 1
    assert sdk.notification_reads == 2
    assert sdk.interrupts == [("thread-1", "turn-1")]


def test_text_result_preserves_raw_schema_failure_for_consumer(sdk):
    # Schema requests must not turn malformed model output into fabricated JSON.
    raw = '{"transcription":'
    sdk.events = [
        _usage(sdk),
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="message-1", type="agentMessage", phase=None, text=raw,
        ))),
        _completed(sdk),
    ]
    result = asyncio.run(runtime.run_text(
        model="exact-model", system_prompt="Transcribe", user_content="Read this image",
        json_schema={"type": "object", "properties": {"transcription": {"type": "string"}}},
        image_attachments=((_png(), "image/png"),),
    ))
    assert result.text == raw
    with pytest.raises(json.JSONDecodeError):
        json.loads(result.text)
    assert (result.input_tokens, result.output_tokens) == (31, 7)
    assert result.metadata["references"][0]["sha256"] == hashlib.sha256(_png()).hexdigest()
    assert len(sdk.turns) == 1


@pytest.mark.parametrize("model", ("gpt-6.1-sol", "gpt-6-sol", "gpt-6-luna"))
def test_gpt6_text_selection_uses_exact_catalog_model(sdk, model):
    sdk.models = [_Record(model=model, input_modalities=["text", "image"],
                          service_tiers=[_Record(id="priority")])]
    sdk.events = [
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="message-1", type="agentMessage", phase=None, text="ready",
        ))),
        _completed(sdk),
    ]
    result = asyncio.run(runtime.run_text(model=model, system_prompt="Reply", user_content="Ready?"))
    assert result.text == "ready"
    assert result.model == model
    assert sdk.threads[0]["model"] == model
    assert sdk.threads[0]["modelProvider"] == runtime.PROVIDER


@pytest.fixture
def supported_host(monkeypatch):
    # Simulated host/child in this process; no actual sandbox enforcement.
    monkeypatch.setattr(runtime.os, "getppid", lambda: runtime.os.getpid())
    monkeypatch.setattr(runtime, "sys", SimpleNamespace(platform="darwin", executable=sys.executable))
    monkeypatch.setattr(runtime, "_parent_environment", lambda: {})
    original_is_file = Path.is_file
    monkeypatch.setattr(
        Path, "is_file",
        lambda path: str(path) == "/usr/bin/sandbox-exec" or original_is_file(path),
    )


@pytest.mark.parametrize("interruption", ["timeout", "cancel"])
@pytest.mark.parametrize("persisted", [False, True])
def test_parent_interruption_keeps_indeterminate_submission_evidence(monkeypatch, supported_host, interruption, persisted):
    terminated = []
    evidence = {
        "submitted": True, "indeterminate": True, "input_tokens": 31,
        "output_tokens": 7, "turn_id": "turn-1", "funding": "codex_subscription",
    }

    class Process:
        async def wait(self):
            if interruption == "cancel":
                raise asyncio.CancelledError()
            raise asyncio.TimeoutError()

    async def spawn(*args, **kwargs):
        if persisted:
            (Path(kwargs["cwd"]) / "evidence.json").write_text(json.dumps(evidence))
        return Process()

    async def terminate(process):
        terminated.append(process)

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(runtime, "_terminate", terminate)
    error = asyncio.CancelledError if interruption == "cancel" else runtime.CodexRuntimeError
    with pytest.raises(error) as failure:
        _generate()
    metadata = failure.value.metadata
    assert metadata["indeterminate"] is True
    assert metadata["submitted"] is (True if persisted else None)
    assert metadata["process_group_terminated"] is True
    assert len(terminated) == 1
    if persisted:
        assert (metadata["input_tokens"], metadata["output_tokens"]) == (31, 7)
        assert metadata["turn_id"] == "turn-1"
    if interruption == "timeout":
        assert failure.value.code == "runtime_timeout"


def test_unsupported_host_cannot_submit_without_os_isolation(monkeypatch):
    monkeypatch.setattr(runtime, "sys", SimpleNamespace(platform="linux"))

    async def forbidden(*args, **kwargs):
        pytest.fail("Unsupported host attempted to launch the generation child")

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", forbidden)
    with pytest.raises(runtime.CodexRuntimeError, match="unsupported_process_isolation_platform"):
        _generate()


def test_completed_image_survives_cancellation_during_interrupt(sdk, tmp_path):
    data = _png()
    sdk.cancel_interrupt = True
    sdk.events = [_usage(sdk), _image_event(sdk, data=data)]
    with pytest.raises(asyncio.CancelledError):
        _generate()
    recovered = runtime._read_completed(tmp_path, sdk.request)
    assert recovered is not None
    assert base64.b64decode(recovered["image"]) == data
    assert (recovered["input_tokens"], recovered["output_tokens"]) == (31, 7)
    assert recovered["metadata"]["indeterminate"] is False
    assert len(sdk.turns) == 1


@pytest.fixture
def completed_child(monkeypatch, supported_host):
    state = SimpleNamespace(outcome="timeout", corrupt=None, launches=0, terminated=0)
    data = _png()
    state.image = data

    class Process:
        async def wait(self):
            if state.outcome == "cancel":
                raise asyncio.CancelledError()
            if state.outcome == "timeout":
                raise asyncio.TimeoutError()
            return 0

    async def spawn(*args, **kwargs):
        state.launches += 1
        root = Path(kwargs["cwd"])
        request = json.loads((root / "request.json").read_text())
        metadata = {
            "submitted": True, "indeterminate": False,
            "execution_fingerprint": runtime.EXECUTION_FINGERPRINT,
            "thread_id": "thread-1", "turn_id": "turn-1", "input_tokens": 31, "output_tokens": 7,
            "turn_status": "completed", "image_status": "completed",
            "image": runtime.validate_image_bytes(data),
        }
        result = {
            "model": request["model"], "image": base64.b64encode(data).decode(),
            "text": '{"transcription":"CANARY"}', "input_tokens": 31, "output_tokens": 7,
            "metadata": metadata,
        }
        checkpoint_request = dict(request)
        if state.corrupt == "prompt":
            checkpoint_request["prompt"] = "a different generation"
        elif state.corrupt == "model":
            result["model"] = "other-model"
        elif state.corrupt == "bytes":
            result["image"] = base64.b64encode(b"not an image").decode()
        elif state.corrupt == "digest":
            metadata["image"]["sha256"] = "0" * 64
        elif state.corrupt == "indeterminate":
            metadata["indeterminate"] = True
        elif state.corrupt == "saved_path":
            metadata["saved_path"] = str(root / "outside.png")
        runtime._save_completed(root, checkpoint_request, result)
        (root / "evidence.json").write_text(json.dumps(metadata))
        if state.outcome == "child_timeout":
            (root / "result.json").write_text(json.dumps({"error": "runtime_timeout", "metadata": metadata}))
        return Process()

    async def terminate(process):
        state.terminated += 1

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(runtime, "_terminate", terminate)
    return state


@pytest.mark.parametrize("kind", ["image", "text"])
@pytest.mark.parametrize("outcome", ["timeout", "child_timeout"])
def test_timeout_recovers_completed_result_without_resubmission(completed_child, kind, outcome):
    completed_child.outcome = outcome
    if kind == "image":
        result = _generate()
        assert result.image_bytes == completed_child.image
    else:
        result = asyncio.run(runtime.run_text(model="exact-model", system_prompt="transcribe", user_content="read"))
        assert json.loads(result.text) == {"transcription": "CANARY"}
    assert (result.input_tokens, result.output_tokens) == (31, 7)
    assert result.metadata["recovered_after_timeout"] is True
    assert result.metadata["indeterminate"] is False
    assert completed_child.launches == 1
    assert completed_child.terminated == (1 if outcome == "timeout" else 0)


def test_cancellation_remains_cancellation_with_completed_result_evidence(completed_child):
    completed_child.outcome = "cancel"
    with pytest.raises(asyncio.CancelledError) as failure:
        _generate()
    metadata = failure.value.metadata
    assert metadata["completed_result_available"] is True
    assert metadata["completed_result_metadata"]["image"]["sha256"] == hashlib.sha256(completed_child.image).hexdigest()
    assert metadata["completed_result_metadata"]["output_tokens"] == 7
    assert completed_child.launches == 1
    assert completed_child.terminated == 1


@pytest.mark.parametrize("corrupt", ["prompt", "model", "bytes", "digest", "indeterminate", "saved_path"])
def test_timeout_does_not_accept_wrong_or_unvalidated_checkpoint(completed_child, corrupt):
    completed_child.corrupt = corrupt
    with pytest.raises(runtime.CodexRuntimeError, match="runtime_timeout"):
        _generate()
    assert completed_child.launches == 1
    assert completed_child.terminated == 1


@pytest.mark.parametrize(("state_id", "edit_parent_indices"), [(None, ()), ("flooded", ()), ("flooded", (1,))])
def test_compiled_location_authorities_reach_fresh_thread_as_creation_or_parent_edit(
    sdk, monkeypatch, tmp_path, state_id, edit_parent_indices,
):
    from dataclasses import replace
    from novel_to_comic import asset_generation, codex_dev
    from novel_to_comic.ai.providers import codex_dev as provider
    from novel_to_comic.asset_generation import compile_non_panel_request, reference_plan_for_assets
    from novel_to_comic.config import Config
    from novel_to_comic.image_references import AuthorityScope, ReferenceAsset
    from novel_to_comic.stages.s3_cast import _location_generation_input

    route = codex_dev.CodexRoute(reasoning_model="exact-model", image_model="gpt-image-2")
    for module in (codex_dev, asset_generation, provider):
        monkeypatch.setattr(module, "route_for", lambda kind, model: route)
    config = Config(image_model="image-gpt-2")
    references = []
    for index, role in enumerate(("style", "location_plate") if state_id else ("style",)):
        data = _png("blue" if index == 0 else "red")
        path = tmp_path / f"authority-{index}.png"
        path.write_bytes(data)
        references.append(ReferenceAsset(
            path=path, role=role, entity_id="loc_stairs" if index else None,
            appearance_state_id=state_id if index else None,
            authority_scope=AuthorityScope.CONTEXTUAL,
            preserve_facets=("architecture",) if index else (),
            ignore_facets=("water level",) if index else (),
            pose=None, content_sha256=hashlib.sha256(data).hexdigest(),
            lineage_parent_sha256=None, label=role,
        ))
    anchor = "underground staircase, ornate wrought-iron railings, glowing warm light"
    location = SimpleNamespace(id="loc_stairs", name="Staircase", visual_anchor=anchor)
    request = compile_non_panel_request(
        config, replace(_location_generation_input(config, location), edit_parent_indices=edit_parent_indices),
        reference_plan=reference_plan_for_assets(config, references),
    )
    sdk.events = [_image_event(sdk, saved_path=Path.home() / ".codex/generated_images/location.png")]
    result = asyncio.run(provider.CodexDevImageProvider().generate_wire(
        wire=request.wire, config=config, event_id="location", metadata={},
    ))
    payload = json.loads(sdk.turns[0][1][0]["text"])
    specification = payload["image_specification"]
    assert specification["operation"] == ("edit" if edit_parent_indices else "create")
    assert payload["image_tool_arguments"]["num_last_images_to_include"] == len(references)
    assert anchor in payload["image_tool_arguments"]["prompt"]
    assert [(authority["role"], authority["edit_parent"]) for authority in specification["reference_authorities"]] == (
        [("style", False), ("location_plate", bool(edit_parent_indices))] if state_id else [("style", False)]
    )
    assert [authority["instruction"] for authority in specification["reference_authorities"]] == [
        ref.instruction for ref in request.wire.references
    ]
    assert [ref["sha256"] for ref in result.raw_response["codex_runtime"]["references"]] == [
        ref.content_sha256 for ref in references
    ]
    assert len(sdk.threads) == 1


def test_content_filter_runtime_error_is_a_refusal_with_original_evidence():
    from novel_to_comic.ai.errors import AIRefusalError
    evidence = {"provider_error": {"message": "stream disconnected before completion: Incomplete response returned, reason: content_filter"},
                "funding": "codex_subscription", "input_tokens": 31, "output_tokens": 7}
    error = runtime._runtime_error("runtime_turn_error", evidence)
    assert isinstance(error, AIRefusalError)
    assert isinstance(error, runtime.CodexRuntimeError)
    assert error.metadata == evidence
    assert error.response_data is None
    assert not isinstance(runtime._runtime_error("runtime_timeout", evidence), AIRefusalError)
    assert not isinstance(runtime._runtime_error("runtime_turn_error", {"provider_error": {"message": "connection lost"}}), AIRefusalError)


def test_text_stream_recovery_keeps_listening_to_the_same_turn(sdk):
    sdk.events = [
        sdk.types.ErrorNotification(will_retry=True, error=_Record(
            message="stream disconnected before completion: Transport error: network error: error decoding response body")),
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="text-1", type="agentMessage", phase=None, text='{"ok": true}'))),
        _usage(sdk), _completed(sdk),
    ]
    result = asyncio.run(runtime.run_text(model="exact-model", system_prompt="Extract", user_content="Story"))
    assert result.text == '{"ok": true}'
    assert len(sdk.turns) == 1
    assert result.metadata["events"][0]["will_retry"] is True
    assert result.input_tokens == 31


def test_text_allows_bounded_stream_recovery_but_images_never_retry(tmp_path):
    text = runtime._config(tmp_path, {"kind": "text"}, "restricted")
    image = runtime._config(tmp_path, {"kind": "image"}, "restricted")
    assert text["model_providers"][runtime.PROVIDER]["stream_max_retries"] == 2
    assert image["model_providers"][runtime.PROVIDER]["stream_max_retries"] == 0
    assert image["model_providers"][runtime.PROVIDER]["request_max_retries"] == 0


@pytest.mark.parametrize("kind,will_retry", [("text", False), ("image", True), ("image", False)])
def test_terminal_text_errors_and_all_image_errors_remain_failures(sdk, kind, will_retry):
    sdk.events = [sdk.types.ErrorNotification(will_retry=will_retry, error=_Record(
        message="stream disconnected before completion: Transport error: network error: error decoding response body"))]
    with pytest.raises(runtime.CodexRuntimeError, match="runtime_turn_error"):
        if kind == "image":
            _generate()
        else:
            asyncio.run(runtime.run_text(model="exact-model", system_prompt="Extract", user_content="Story"))
    assert len(sdk.turns) == 1
    assert sdk.notification_reads == 1
    assert sdk.interrupts == [("thread-1", "turn-1")]


def test_child_text_reconnect_can_complete_beyond_image_deadline(sdk, monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'TIMEOUT_SECONDS', 0.01)
    monkeypatch.setattr(runtime, 'TEXT_TIMEOUT_SECONDS', 1)
    monkeypatch.setattr(runtime.importlib.metadata, 'version', lambda package: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, 'gettempdir', lambda: str(tmp_path))
    execute = runtime._execute

    async def delayed_execute(root, request, evidence):
        await asyncio.sleep(0.02)
        return await execute(root, request, evidence)

    monkeypatch.setattr(runtime, '_execute', delayed_execute)
    sdk.events = [
        sdk.types.ErrorNotification(will_retry=True, error=_Record(message='Reconnecting... 1/2')),
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id='text-1', type='agentMessage', phase=None, text='{"ok": true}'))),
        _completed(sdk),
    ]
    (tmp_path / 'request.json').write_text(json.dumps({
        'kind': 'text', 'model': 'exact-model', 'system_prompt': 'Extract',
        'prompt': 'Story', 'schema': None, 'references': [],
    }))
    asyncio.run(runtime._child(tmp_path))
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['text'] == '{"ok": true}'
    assert result['metadata']['timeout_seconds'] == 1
    assert result['metadata']['execution_elapsed_seconds'] >= 0.02
    assert result['metadata']['events'][0]['elapsed_seconds'] >= 0
    assert len(sdk.turns) == 1


def test_child_text_still_has_absolute_deadline(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime, 'TEXT_TIMEOUT_SECONDS', 0.01)
    monkeypatch.setattr(runtime.importlib.metadata, 'version', lambda package: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, 'gettempdir', lambda: str(tmp_path))

    async def stalled_execute(root, request, evidence):
        evidence.update(submitted=True, indeterminate=True)
        await asyncio.Future()

    monkeypatch.setattr(runtime, '_execute', stalled_execute)
    (tmp_path / 'request.json').write_text(json.dumps({'kind': 'text'}))
    asyncio.run(runtime._child(tmp_path))
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['error'] == 'runtime_timeout'
    assert result['metadata']['timeout_owner'] == 'child'
    assert result['metadata']['indeterminate'] is True
    assert 'Canary stopped the request after 0.01 seconds' in str(
        runtime._runtime_error(result['error'], result['metadata']))


def test_sdk_rpc_rejection_keeps_its_safe_reason_through_child_and_database(monkeypatch, tmp_path):
    from openai_codex.errors import InvalidParamsError
    from novel_to_comic.ai.usage_payloads import compact_metadata

    prompt = 'private source passage'
    reason = 'Request rejected: text exceeds the input limit.'
    calls = []
    async def rejected(root, request, evidence):
        calls.append(request)
        evidence.update(submitted=None, indeterminate=True)
        raise InvalidParamsError(-32602, reason + ' Authorization: Bearer sk-private-credential',
                                 data={'prompt': prompt, 'secret': 'private-data'})
    monkeypatch.setattr(runtime, '_execute', rejected)
    monkeypatch.setattr(runtime.importlib.metadata, 'version', lambda _: runtime.SDK_VERSION)
    monkeypatch.setattr(runtime.tempfile, 'gettempdir', lambda: str(tmp_path))
    (tmp_path / 'request.json').write_text(json.dumps({'kind': 'text', 'prompt': prompt}))
    asyncio.run(runtime._child(tmp_path))
    result = json.loads((tmp_path / 'result.json').read_text())
    assert result['error'] == 'sdk_execution_failed'
    assert result['metadata']['exception_type'] == 'InvalidParamsError'
    assert len(calls) == 1
    assert reason in str(runtime._runtime_error(result['error'], result['metadata']))
    stored = compact_metadata({'codex_runtime': result['metadata']})
    assert stored['codex_runtime']['provider_error'] == {'rpc_code': -32602, 'message': reason}
    serialized = json.dumps(result) + json.dumps(stored)
    assert prompt not in serialized and 'sk-private' not in serialized and 'private-data' not in serialized


@pytest.mark.parametrize('kind,deadline', [('text', 915), ('image', 315)])
def test_parent_deadline_leaves_child_cleanup_time(monkeypatch, supported_host, kind, deadline):
    observed = []
    real_wait_for = asyncio.wait_for

    async def wait_for(awaitable, timeout):
        observed.append(timeout)
        return await real_wait_for(awaitable, timeout)

    class Process:
        async def wait(self):
            return 0

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr(runtime.asyncio, 'create_subprocess_exec', spawn)
    monkeypatch.setattr(runtime.asyncio, 'wait_for', wait_for)
    with pytest.raises(runtime.CodexRuntimeError, match='child_result_missing'):
        asyncio.run(runtime._run({'kind': kind, 'model': 'exact-model'}))
    assert observed == [deadline]


def test_queued_codex_calls_report_execution_only_after_the_runtime_lock(supported_host, monkeypatch):
    # Kaitlin Out of Space: five Plan batches were "admitted" while one ran;
    # progress must not call a request in flight while it waits for the lock.
    from novel_to_comic.ai.context import execution_observer

    started: list[str] = []

    class Spawned(Exception):
        pass

    async def spawn(*args, **kwargs):
        raise Spawned

    monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)

    async def exercise():
        await runtime._LOCK.acquire()
        with execution_observer(lambda: started.append("queued call")):
            waiting = asyncio.create_task(runtime._run({"kind": "text", "model": "gpt-6-luna"}))
            await asyncio.sleep(0.01)
            assert started == []
            runtime._LOCK.release()
            with pytest.raises(Spawned):
                await waiting
        assert started == ["queued call"]

    asyncio.run(exercise())


def test_repeated_cancellation_drains_runtime_before_releasing_lock(monkeypatch, supported_host):
    async def scenario():
        waiting, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()

        class Process:
            async def wait(self):
                waiting.set()
                await asyncio.Future()

        async def spawn(*args, **kwargs):
            return Process()

        async def terminate(process):
            cleaning.set()
            await release.wait()

        monkeypatch.setattr(runtime.asyncio, "create_subprocess_exec", spawn)
        monkeypatch.setattr(runtime, "_terminate", terminate)
        monkeypatch.setattr(runtime, "_LOCK", asyncio.Lock())
        task = asyncio.create_task(runtime._run({"kind": "text", "model": "test"}))
        await waiting.wait()
        task.cancel()
        await cleaning.wait()
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        assert runtime._LOCK.locked()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not runtime._LOCK.locked()

    asyncio.run(scenario())


def test_parent_loss_interrupts_then_kills_only_owned_session(monkeypatch):
    async def scenario():
        events = []
        monkeypatch.setattr(runtime.os, "getppid", lambda: 1)
        monkeypatch.setattr(runtime.os, "getpgrp", lambda: 12345)
        monkeypatch.setattr(runtime.os, "killpg", lambda group, sig: events.append((group, sig)))
        async def grace(seconds):
            events.append(seconds)
        monkeypatch.setattr(runtime.asyncio, "sleep", grace)
        await runtime._watch_parent(99, SimpleNamespace(cancel=lambda: events.append("cancel")))
        assert events == ["cancel", 5, (12345, runtime.signal.SIGKILL)]
    asyncio.run(scenario())


def test_orphaned_child_refuses_before_sdk_submission(monkeypatch, tmp_path):
    monkeypatch.setattr(runtime.os, "getppid", lambda: 1)
    (tmp_path / "request.json").write_text(json.dumps({"kind": "text", "parent_pid": 99}))
    asyncio.run(runtime._child(tmp_path))
    result = json.loads((tmp_path / "result.json").read_text())
    assert result["error"] == "runtime_parent_exited"
    assert result["metadata"]["submitted"] is False


def test_explicit_model_capacity_is_actionable_without_resubmission():
    evidence = {"submitted": True, "indeterminate": False,
                "provider_error": {"message": "Selected model is at capacity. Please try a different model."}}
    error = runtime._runtime_error("runtime_turn_error", evidence)
    assert error.code == "runtime_capacity"
    assert "Retry the same model later" in str(error)
    assert error.metadata == evidence
    # A model-authored statement or unrelated failure must not become capacity.
    assert runtime._runtime_error("text_output_missing", evidence).code == "text_output_missing"


@pytest.mark.parametrize("effort", ["low", "medium", "high"])
def test_text_reasoning_is_pinned_in_runtime_config(sdk, effort):
    observed = []
    sdk.config_change = lambda config: observed.append(config.get("model_reasoning_effort"))
    sdk.events = [
        sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="message-1", type="agentMessage", phase=None, text="ready"))),
        _completed(sdk),
    ]
    result = asyncio.run(runtime.run_text(model="exact-model", system_prompt="Reply", user_content="Hello", effort=effort))
    assert result.text == "ready"
    assert observed and all(value == effort for value in observed)


@pytest.mark.parametrize("kind", ["text", "image"])
def test_fast_service_tier_is_pinned_and_recorded_for_every_call(sdk, kind):
    observed = []
    sdk.config_change = lambda config: observed.append(
        (config["service_tier"], config["features"]["fast_mode"]))
    if kind == "image":
        sdk.events = [_image_event(sdk)]
        result = _generate()
    else:
        sdk.events = [sdk.types.ItemCompletedNotification(item=_Record(root=sdk.types.AgentMessageThreadItem(
            id="message-1", type="agentMessage", phase=None, text="ready"))), _completed(sdk)]
        result = asyncio.run(runtime.run_text(model="exact-model", system_prompt="Reply", user_content="Hello"))
    assert observed == [("priority", True), ("priority", True)]
    assert sdk.threads[0]["model"] == "exact-model"
    assert sdk.threads[0]["serviceTier"] == "priority"
    assert sdk.turns[0][2]["serviceTier"] == "priority"
    assert result.metadata["requested_service_tier"] == "priority"
    assert result.metadata["service_tier"] == "priority"
    assert result.metadata["thread_checks"]["service_tier_matches"] is True


@pytest.mark.parametrize("kind", ["text", "image"])
@pytest.mark.parametrize("tiers", [None, [], ["default"]])
def test_fast_service_tier_must_be_advertised_before_submission(sdk, kind, tiers):
    sdk.models[0].service_tiers = None if tiers is None else [_Record(id=tier) for tier in tiers]
    with pytest.raises(runtime.CodexRuntimeError, match="fast_mode_unsupported") as failure:
        if kind == "image":
            _generate()
        else:
            asyncio.run(runtime.run_text(model="exact-model", system_prompt="Reply", user_content="Hello"))
    assert failure.value.metadata["submitted"] is False
    assert sdk.threads == []
    assert sdk.turns == []


@pytest.mark.parametrize("kind", ["text", "image"])
@pytest.mark.parametrize("boundary", ["config_tier", "fast_feature", "thread_tier"])
def test_fast_service_tier_drift_never_starts_a_turn(sdk, kind, boundary):
    if boundary == "config_tier":
        sdk.config_change = lambda config: config.update(service_tier="default")
    elif boundary == "fast_feature":
        sdk.config_change = lambda config: config["features"].update(fast_mode=False)
    else:
        sdk.thread_service_tier = "default"
    with pytest.raises(runtime.CodexRuntimeError) as failure:
        if kind == "image":
            _generate()
        else:
            asyncio.run(runtime.run_text(model="exact-model", system_prompt="Reply", user_content="Hello"))
    assert failure.value.metadata["submitted"] is False
    if boundary == "thread_tier":
        assert failure.value.metadata["requested_service_tier"] == "priority"
        assert failure.value.metadata["service_tier"] == "default"
    assert sdk.turns == []


@pytest.mark.parametrize('metadata, expected', [
    ({'last_notification_elapsed_seconds': 880.4, 'output_tokens': 41000}, 'Model activity until 880s (41000 output tokens).'),
    ({'last_notification_elapsed_seconds': 3.2}, 'Model activity until 3s.'),
    ({'submitted': True}, 'The model sent no activity after the request was submitted.'),
])
def test_text_timeout_says_whether_the_model_was_still_working(metadata, expected):
    error = runtime.CodexRuntimeError('runtime_timeout', {'timeout_seconds': 900, **metadata})
    assert str(error).startswith('runtime_timeout: Canary stopped the request after 900 seconds')
    assert expected in str(error)


def test_failure_diagnostics_keep_runtime_timing_without_request_content(tmp_path, monkeypatch):
    from novel_to_comic.server.diagnostics import record_diagnostic
    monkeypatch.setenv('CANARY_LOCAL_DIAGNOSTICS', '1')
    error = runtime.CodexRuntimeError('runtime_timeout', {
        'timeout_seconds': 900, 'submitted': True, 'last_notification_elapsed_seconds': 12.5,
        'output_tokens': 300, 'events': [{'type': 'reasoning'}] * 30,
        'revised_prompt': 'private prompt text', 'saved_path': '/private/path.png'})
    record_diagnostic(tmp_path, 'stage_failed', stage='extract', error=error)
    record = json.loads((tmp_path / '.canary/diagnostics.jsonl').read_text())
    evidence = record['runtime_evidence']
    assert evidence['last_notification_elapsed_seconds'] == 12.5 and evidence['output_tokens'] == 300
    assert len(evidence['events']) == 20
    assert 'private prompt text' not in json.dumps(record) and '/private/path.png' not in json.dumps(record)
