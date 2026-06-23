import io
import json
import subprocess
import sys
from pathlib import Path

from forge import __version__
from forge.cli import build_parser, main


def test_no_command_defaults_to_mcp(monkeypatch):
    called = False
    def fake_mcp():
        nonlocal called
        called = True
    monkeypatch.setattr("forge.cli._mcp", fake_mcp)
    main(["mcp"])
    assert called


def test_explicit_mcp(monkeypatch):
    called = False
    def fake_mcp():
        nonlocal called
        called = True
    monkeypatch.setattr("forge.cli._mcp", fake_mcp)
    main(["mcp"])
    assert called


def test_explicit_bridge(monkeypatch):
    called = False
    def fake_bridge():
        nonlocal called
        called = True
    monkeypatch.setattr("forge.cli._bridge", fake_bridge)
    main(["bridge"])
    assert called


def test_version_command(capsys):
    main(["version"])
    out = capsys.readouterr().out.strip()
    assert out == __version__


def test_version_flag(capsys):
    import pytest
    with pytest.raises(SystemExit):
        main(["--version"])
    out = capsys.readouterr().out.strip()
    assert __version__ in out


def test_unknown_command_returns_nonzero():
    result = subprocess.run(
        [sys.executable, "-m", "forge.cli", "nonexistent"],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert "invalid" in result.stderr.lower()


def test_bridge_mode_accepts_newline_delimited_requests(monkeypatch):
    from forge.plugin.bridge import run_bridge

    request = json.dumps({"schema_version": 1, "operation": "get_active_task",
                          "payload": {"host_session_id": "test"}})
    original_stdin = sys.stdin
    output = io.StringIO()
    try:
        sys.stdin = io.StringIO(request + "\n")
        monkeypatch.setattr(sys, "stdout", output)
        sys.stderr = io.StringIO()
        run_bridge()
    finally:
        sys.stdin = original_stdin
    result = output.getvalue().strip()
    assert result
    parsed = json.loads(result)
    assert "schema_version" in parsed


def test_cli_help_contains_subcommands():
    parser = build_parser()
    assert parser.prog == "forge"
    help_text = parser.format_help()
    for cmd in ("mcp", "bridge", "version", "install", "doctor", "uninstall", "purge"):
        assert cmd in help_text


def test_install_command_args():
    parser = build_parser()
    args = parser.parse_args(["install", "--version", "1.0.0", "--config-root", "/tmp/cfg"])
    assert args.version == "1.0.0"
    assert args.config_root == "/tmp/cfg"


def test_doctor_command_args():
    parser = build_parser()
    args = parser.parse_args(["doctor", "--config-root", "/tmp/cfg"])
    assert args.config_root == "/tmp/cfg"
