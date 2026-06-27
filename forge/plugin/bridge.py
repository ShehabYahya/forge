from __future__ import annotations

import json
import signal
import sys
from typing import Any

from ..service import ForgeService
from .protocol import PluginProtocolBackend

_shutting_down = False


def _handle_signal(signum: int, frame: object) -> None:
    global _shutting_down
    _shutting_down = True


def _error_response(message: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "ok": False,
        "decision": "block",
        "reason": message,
        "replacement_output": None,
        "user_message": f"Forge bridge error: {message}",
        "capability_limited": True,
        "payload": {},
    }


def run_bridge() -> None:
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)
    service = ForgeService()
    backend = PluginProtocolBackend(service)
    for raw in sys.stdin:
        if _shutting_down:
            break
        if not raw.strip():
            continue
        try:
            wire = json.loads(raw)
            if not isinstance(wire, dict):
                raise ValueError("request must be a JSON object")
            response = backend.handle(wire)
        except Exception as exc:  # pragma: no cover - defensive bridge wrapper
            response = _error_response(str(exc))
        sys.stdout.write(json.dumps(response) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_bridge()
