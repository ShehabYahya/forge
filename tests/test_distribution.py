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
    verify_manifest,
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


# -------------------------------------------------- manifest verification


class TestVerifyManifest:
    def _make_version_dir(self, tmp_path, files=None):
        vd = tmp_path / "version"
        vd.mkdir(parents=True, exist_ok=True)
        digests = {}
        files = files or {"plugin/index.js": "plugin code\n", "bin/forge": "#!/bin/sh\n"}
        for rel, content in files.items():
            fpath = vd / rel
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(content, encoding="utf-8")
            digests[rel] = _sha256_file(fpath)
        manifest = {"version": "1.0.0", "platform": "linux-x64",
                    "assets": {k: k for k in digests}, "digests": digests}
        _write_json(vd / "manifest.json", manifest)
        return vd

    def test_valid_manifest_passes(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        ok, errors, warnings = verify_manifest(vd)
        assert ok
        assert errors == []
        assert warnings == []

    def test_missing_manifest_fails(self, tmp_path):
        vd = tmp_path / "empty"
        vd.mkdir(parents=True, exist_ok=True)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("manifest not found" in e for e in errors)

    def test_missing_file_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        (vd / "plugin" / "index.js").unlink()
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("missing file" in e for e in errors)

    def test_digest_mismatch_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        (vd / "plugin" / "index.js").write_text("tampered\n", encoding="utf-8")
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("digest mismatch" in e for e in errors)

    def test_absolute_path_in_manifest_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        manifest["digests"]["/etc/passwd"] = "a" * 64
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("unsafe" in e for e in errors)

    def test_path_traversal_in_manifest_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        manifest["digests"]["../../../etc/passwd"] = "a" * 64
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("unsafe" in e for e in errors)

    def test_backslash_path_traversal_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        manifest["digests"]["..\\..\\etc\\passwd"] = "a" * 64
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("unsafe" in e for e in errors)

    def test_malformed_digest_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        manifest["digests"]["plugin/index.js"] = "short"
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("malformed" in e for e in errors)

    def test_no_digests_warns_but_passes(self, tmp_path):
        vd = tmp_path / "legacy"
        vd.mkdir(parents=True, exist_ok=True)
        (vd / "bin").mkdir()
        (vd / "bin" / "forge").write_text("#!/bin/sh\n")
        manifest = {"version": "1.0.0", "platform": "linux-x64",
                    "assets": {"bin/forge": "bin/forge"}}
        _write_json(vd / "manifest.json", manifest)
        ok, errors, warnings = verify_manifest(vd)
        assert ok
        assert errors == []
        assert any("no digests" in w for w in warnings)

    def test_malformed_json_fails(self, tmp_path):
        vd = tmp_path / "bad"
        vd.mkdir(parents=True, exist_ok=True)
        (vd / "manifest.json").write_text("{bad json", encoding="utf-8")
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("malformed" in e for e in errors)

    def test_extra_files_not_checked(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        (vd / "__pycache__").mkdir()
        (vd / "__pycache__" / "junk.pyc").write_text("junk\n")
        ok, errors, _ = verify_manifest(vd)
        assert ok
        assert errors == []

    def test_directory_in_manifest_does_not_crash(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        (vd / "somedir").mkdir()
        manifest["digests"]["somedir"] = "a" * 64
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok
        assert any("missing file" in e for e in errors)

    def test_rooted_backslash_path_fails(self, tmp_path):
        vd = self._make_version_dir(tmp_path)
        manifest = _read_json(vd / "manifest.json")
        manifest["digests"]["\\Windows\\system32"] = "a" * 64
        _write_json(vd / "manifest.json", manifest)
        ok, errors, _ = verify_manifest(vd)
        assert not ok


class TestDoctorManifestVerification:
    def test_doctor_fails_on_modified_plugin(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))
        svc = DistributionService()
        svc.install()
        version = __version__
        version_dir = program_root() / "versions" / version
        plugin_file = version_dir / "plugin" / "index.js"
        plugin_file.write_text("tampered\n", encoding="utf-8")
        assert not svc.doctor(quiet=True)

    def test_doctor_passes_after_clean_install(self, tmp_path, monkeypatch):
        monkeypatch.setenv("FORGE_PROGRAM", str(tmp_path / "program"))
        monkeypatch.setenv("OPENCODE_CONFIG_DIR", str(tmp_path / "opencode-config"))
        svc = DistributionService()
        svc.install()
        assert svc.doctor(quiet=True)
