"""Bounded, authenticated transport only; host configuration decisions stay on host."""
from __future__ import annotations

import json
import socket

from fastapi import HTTPException

CONTROL = '/run/canary-host/control.sock'
UPLOAD = '/run/canary-host/config-upload.sock'
CODES = frozenset('''invalid_request rejected_busy baseline_changed plan_expired authorization_expired
ci_release_active configuration_operation_active maintenance_active config_not_enabled already_drained
drift_detected observation_stale unsupported_setting ssh_only invalid_setting signature_required signature_invalid
invalid_manifest authorization_used recipient_change_forbidden ops_token_rotation_ssh_only request_id_conflict
plan_not_ready worker_launch_unknown operation_interrupted credential_required public_maintenance_active
configuration_failed upload_too_large invalid_bundle unsafe_permissions
invalid_environment unsupported_environment_value host_loader_update_required invalid_bundle_digest
candidate_identity_unknown candidate_restarted candidate_not_drained candidate_readiness_timeout
start_limit_hit drain_timeout public_verification_failed resume_failed invalid_public_origin
host_agent_unavailable request_outcome_unknown'''.split())


def forward(payload: dict, *, upload: bool = False) -> dict:
    raw = json.dumps(payload, separators=(',', ':')).encode() + b'\n'
    if len(raw) > (3 * 1024 * 1024 if upload else 4096):
        raise HTTPException(413, {'code': 'upload_too_large'})
    attempted = False
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(25)
            client.connect(UPLOAD if upload else CONTROL)
            attempted = True  # Even a failed sendall may have submitted part/all of the request.
            client.sendall(raw)
            with client.makefile('rb') as stream:
                response = stream.readline(262145)
            if len(response) > 262144:
                raise ValueError('oversized')
            result = json.loads(response)
            if not isinstance(result, dict) or not isinstance(result.get('ok'), bool):
                raise ValueError('invalid_response')
            if result['ok']:
                if not isinstance(result.get('result'), dict):
                    raise ValueError('invalid_response')
                return result['result']
            code = result.get('code')
            raise HTTPException(409, {'code': code if code in CODES else 'configuration_failed'})
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise HTTPException(503, {
            'code': 'request_outcome_unknown' if attempted else 'host_agent_unavailable',
            'request_sent': None if attempted else False,
            'request_id': payload.get('request_id'),
        }) from error
