"""Retain Anthropic stop_details in the pinned LiteLLM response mapping.

Only response metadata changes. No request policies, retries, or fallbacks.
Fail closed if the pinned mapping changes so upgrades require inspection.
"""
from importlib.util import find_spec
from pathlib import Path
import sys


def patch_source(source: str, kind: str) -> str:
    marker = "# Canary: retain Anthropic refusal details."
    if marker in source:
        return source
    if kind == "transformation":
        old = '        context_management = completion_response.get("context_management")'
        new = '''        # Canary: retain Anthropic refusal details.
        if completion_response.get("stop_details") is not None:
            provider_specific_fields["stop_details"] = completion_response["stop_details"]

''' + old
    elif kind == "handler":
        old = '                finish_reason, usage, container = self._handle_message_delta(chunk)'
        new = old + '''
                # Canary: retain Anthropic refusal details.
                stop_details = chunk.get("delta", {}).get("stop_details")
                if stop_details is not None:
                    provider_specific_fields["stop_details"] = stop_details'''
    else:
        raise ValueError(f"Unknown Anthropic mapping: {kind}")
    if source.count(old) != 1:
        raise RuntimeError(f"LiteLLM {kind} changed; review the Anthropic refusal patch")
    return source.replace(old, new)


if __name__ == "__main__":
    spec = find_spec("litellm")
    assert spec is not None and spec.origin is not None
    for kind in ("transformation", "handler"):
        relative = Path(f"litellm/llms/anthropic/chat/{kind}.py")
        targets = {Path(entry) / relative for entry in sys.path}
        targets.add(Path(spec.origin).parent / f"llms/anthropic/chat/{kind}.py")
        for target in targets:
            if target.is_file():
                target.write_text(patch_source(target.read_text(), kind))
