"""Readiness policy from explicit route metadata, also visible in the API schema."""

from dataclasses import dataclass, replace
import json
from starlette.routing import compile_path


@dataclass(frozen=True)
class ActionPolicy:
    spends: bool = False
    dispatches: bool = False
    paid_stages: tuple[str, ...] | None = None
    paid_body_field: str | None = None
    replay: bool = True


def request_policy(request, body: bytes = b"") -> ActionPolicy:
    policies = getattr(request.app.state, "action_policies", None)
    if policies is None:
        policies = []
        for path, methods in request.app.openapi()["paths"].items():
            for method, schema in methods.items():
                if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                    rules = schema.get("x-canary-action", {})
                    policies.append(
                        (method.upper(), compile_path(path)[0], ActionPolicy(**rules))
                    )
        request.app.state.action_policies = policies
    for method, path, policy in policies:
        match = path.fullmatch(request.url.path)
        if method != request.method or match is None:
            continue
        if policy.paid_stages is not None and match.groupdict().get("stage") not in policy.paid_stages:
            policy = replace(policy, spends=False, dispatches=False)
        if policy.paid_body_field:
            try:
                value = json.loads(body)
            except ValueError:
                value = None
            if isinstance(value, dict) and value.get(policy.paid_body_field, False) is False:
                policy = replace(policy, spends=False, dispatches=False, replay=False)
        return policy
    return ActionPolicy()
