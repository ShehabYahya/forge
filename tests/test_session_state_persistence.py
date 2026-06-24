"""Persistence of session-mode and maintenance-owner state across bridge restarts."""

from __future__ import annotations

import json

from forge.plugin.protocol import (
    SESSION_MODE_MEMORY_REVIEW,
    SESSION_MODE_NORMAL,
    PluginProtocolBackend,
)


def _wire(operation: str, payload: dict) -> dict:
    return {"schema_version": 1, "operation": operation, "payload": payload}


def test_session_state_persists_across_backend_restart(service, repo):
    backend = PluginProtocolBackend(service)
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert result["ok"] is True
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    assert backend._maintenance_owner == "host"

    # Simulate a bridge restart: brand-new backend on the same service, no start call.
    restarted = PluginProtocolBackend(service)
    assert restarted.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    assert restarted._maintenance_owner == "host"

    # Finishing on the restarted backend reverts to normal and persists to disk.
    finished = restarted.handle(_wire("finish_memory_maintenance",
                                      {"host_session_id": "host", "status": "completed"}))
    assert finished["ok"] is True
    assert restarted.session_mode("host") == SESSION_MODE_NORMAL
    assert restarted._maintenance_owner is None

    state_path = service.runtime_root / "plugin_session_state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["session_modes"] == {}
    assert data["maintenance_owner"] is None

    # A third backend (another restart) loads the cleared state.
    third = PluginProtocolBackend(service)
    assert third.session_mode("host") == SESSION_MODE_NORMAL
    assert third._maintenance_owner is None


def test_reload_refreshes_in_memory_state(service, repo):
    backend = PluginProtocolBackend(service)
    backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW

    # Another backend writes a different state to disk.
    other = PluginProtocolBackend(service)
    other.handle(_wire("finish_memory_maintenance",
                       {"host_session_id": "host", "status": "completed"}))

    # The first backend still has stale in-memory state until reload().
    assert backend.session_mode("host") == SESSION_MODE_MEMORY_REVIEW
    backend.reload()
    assert backend.session_mode("host") == SESSION_MODE_NORMAL
    assert backend._maintenance_owner is None


def test_corrupt_state_file_treated_as_empty(service, repo):
    state_path = service.runtime_root / "plugin_session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("{this is not valid json", encoding="utf-8")

    backend = PluginProtocolBackend(service)
    assert backend.session_mode("host") == SESSION_MODE_NORMAL
    assert backend._maintenance_owner is None
    assert backend._session_modes == {}


def test_legacy_state_without_since_auto_heals(service, repo):
    """Simulate a pre-upgrade stuck lock: maintenance_owner set but no
    maintenance_owner_since → self-heal on next start."""
    state_path = service.runtime_root / "plugin_session_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "session_modes": {"host": "memory_review"},
        "maintenance_owner": "host",
    }), encoding="utf-8")

    # The legacy stuck lock should be auto-reclaimed (since absent → stale).
    backend = PluginProtocolBackend(service)
    assert backend._maintenance_owner == "host"
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "new_host"}))
    assert result["ok"] is True
    assert result["payload"]["lease_state"] == "reclaimed"
    assert backend._maintenance_owner == "new_host"
    assert backend.session_mode("host") == SESSION_MODE_NORMAL


def test_persisted_epoch_since_survives_round_trip(service, repo):
    """Verify maintenance_owner_since and maintenance_epoch are persisted and reloaded."""
    backend = PluginProtocolBackend(service)
    result = backend.handle(_wire("start_memory_maintenance", {"host_session_id": "host"}))
    assert result["ok"] is True
    epoch = result["payload"]["epoch"]
    assert isinstance(epoch, int)
    assert epoch > 0

    state_path = service.runtime_root / "plugin_session_state.json"
    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["maintenance_owner"] == "host"
    assert isinstance(data["maintenance_owner_since"], (int, float))
    assert data["maintenance_epoch"] == epoch

    # Reload on a new backend.
    restarted = PluginProtocolBackend(service)
    assert restarted._maintenance_epoch == epoch
    assert restarted._maintenance_owner_since is not None
