"""Bounded transport to the optional, root-owned Lightsail host agent."""
from __future__ import annotations

import json
import socket

from fastapi import HTTPException

SOCKET_PATH = '/run/canary-host/control.sock'


def host_request(payload: dict) -> dict:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(25)
            client.connect(SOCKET_PATH)
            client.sendall(json.dumps(payload).encode() + b'\n')
            with client.makefile('rb') as stream:
                raw = stream.readline(262145)
            if len(raw) > 262144:
                raise ValueError('oversized_host_response')
            response = json.loads(raw)
        if response.get('ok') is not True:
            raise HTTPException(409, 'Host request failed. Refresh host status before retrying; inspect the host journal if needed.')
        return response['result']
    except (OSError, ValueError, KeyError) as exc:
        raise HTTPException(503, 'Host maintenance is unavailable. The host agent and private socket mount must be installed; during maintenance, wait for Canary to return.') from exc
