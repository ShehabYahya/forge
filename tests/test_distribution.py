import os
from pathlib import Path

import pytest

from forge import __version__
from forge.distribution import (
    DistributionService,
    _platform_target,
    _opencode_config_root,
    program_root,
    runtime_root,
    _sha256_file,
    _write_json,
    _read_json,
    _backup,
    _restore_backup,
)


def test_platform_target_is_nonempty():
    target = _platform_target()
    assert target
    assert "-" in target


def test_program_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "custom-program"))
    assert str(program_root()) == str(tmp_path / "custom-program")


def test_program_root_legacy_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_PROGRAM", raising=False)
    monkeypatch.setenv("FORGE_ALPHA_PROGRAM", str(tmp_path / "custom-program"))
    assert str(program_root()) == str(tmp_path / "custom-program")


def test_runtime_root_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("FORGE_HOME", str(tmp_path / "custom-home"))
    assert str(runtime_root()) == str(tmp_path / "custom-home")


def test_runtime_root_legacy_env_override(monkeypatch, tmp_path):
    monkeypatch.delenv("FORGE_HOME", raising=False)
    monkeypatch.setenv("FORGE_ALPHA_HOME", str(tmp_path / "custom-home"))
    assert str(runtime_root()) == str(tmp_path / "custom-home")


def test_runtime_root_default(monkeypatch):
    monkeypatch.delenv("FORGE_HOME", raising=False)
    monkeypatch.delenv("FORGE_ALPHA_HOME", raising=False)
    rt = runtime_root()
    assert rt.parts[-1] == ".forge" or rt == Path.home() / ".forge"


def test_opencode_config_root_explicit():
    result = _opencode_config_root("/custom/config")
    assert str(result) == "/custom/config"


def test_opencode_config_root_env(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-cfg"))
    result = _opencode_config_root()
    assert str(result) == str(tmp_path / "opencode-cfg")


def test_sha256_file(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello")
    digest = _sha256_file(f)
    assert len(digest) == 64
    assert all(c in "0123456789abcdef" for c in digest)


def test_json_roundtrip(tmp_path):
    path = tmp_path / "test.json"
    data = {"version": "1.0.0", "executable": "bin/forge"}
    _write_json(path, data)
    assert path.exists()
    result = _read_json(path)
    assert result == data


def test_backup_create_and_restore(tmp_path):
    target = tmp_path / "active.json"
    target.write_text("original")
    bk = _backup(target)
    assert bk is not None
    assert bk.exists()
    assert bk.read_text() == "original"

    target.write_text("modified")
    _restore_backup(bk, target)
    assert target.read_text() == "original"
    assert not bk.exists()


def test_backup_nonexistent_returns_none(tmp_path):
    bk = _backup(tmp_path / "nonexistent.json")
    assert bk is None


class TestFreshInstall:
    def test_fresh_install_creates_version_directory_and_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        svc = DistributionService()
        ok = svc.install()
        assert ok

        program = program_root()
        assert (program / "active.json").exists()
        manifest = _read_json(program / "active.json")
        assert "version" in manifest
        assert "executable" in manifest
        assert "plugin" in manifest

        version_dir = program / "versions" / __version__
        assert version_dir.exists()
        assert (version_dir / "manifest.json").exists()
        assert (version_dir / "plugin" / "index.js").exists()
        assert (version_dir / "bin").exists()

        config = _opencode_config_root()
        assert (config / "plugins" / "forge" / "loader.js").exists()

    def test_reinstall_is_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        svc = DistributionService()
        assert svc.install()
        assert svc.install()

        program = program_root()
        manifest = _read_json(program / "active.json")
        assert manifest["version"] == __version__

    def test_doctor_reports_healthy_after_install(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        svc = DistributionService()
        svc.install()

        assert svc.doctor(quiet=True)

    def test_doctor_fails_without_manifest(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        svc = DistributionService()
        assert not svc.doctor(quiet=True)

    def test_doctor_fails_missing_executable(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        program = program_root()
        svc = DistributionService()
        svc.install()

        exe_rel = _read_json(program / "active.json")["executable"]
        (program / exe_rel).unlink()

        assert not svc.doctor(quiet=True)


class TestUninstall:
    def test_uninstall_removes_forge_owned_files(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        svc = DistributionService()
        svc.install()
        legacy_plugin = _opencode_config_root() / "plugins" / "forge-alpha"
        legacy_plugin.mkdir(parents=True)

        svc.uninstall()

        program = program_root()
        active = program / "active.json"
        assert not active.exists()

        config = _opencode_config_root()
        assert not (config / "plugins" / "forge").exists()
        assert not (config / "plugins" / "forge-alpha").exists()

    def test_uninstall_preserves_runtime_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "runtime"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))

        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "tasks.jsonl").write_text("test")

        svc = DistributionService()
        svc.install()
        svc.uninstall()

        assert runtime_dir.exists()
        assert (runtime_dir / "tasks.jsonl").exists()


class TestPurge:
    def test_purge_removes_runtime_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_HOME", str(tmp_path / "runtime"))

        runtime_dir = tmp_path / "runtime"
        runtime_dir.mkdir(parents=True)
        (runtime_dir / "tasks.jsonl").write_text("test")

        svc = DistributionService()
        svc.purge(force=True)
        assert not runtime_dir.exists()
