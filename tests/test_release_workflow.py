import re
from pathlib import Path


def _workflow_text(name: str) -> str:
    return Path(".github/workflows", name).read_text(encoding="utf-8")


def test_ci_has_python_tests():
    text = _workflow_text("ci.yml")
    assert "python-tests" in text
    assert "pytest" in text


def test_ci_has_prompt_check():
    text = _workflow_text("ci.yml")
    assert "prompt-check" in text


def test_ci_has_plugin_tests():
    text = _workflow_text("ci.yml")
    assert "plugin-tests" in text


def test_ci_has_forbidden_content_check():
    text = _workflow_text("ci.yml")
    assert "forbidden-content" in text


def test_ci_anvil_scan_excludes_historical_docs():
    text = _workflow_text("ci.yml")
    assert "docs/brainstorms/" not in text
    assert "docs/plans/" not in text
    assert "docs/Forge" in text


def test_release_has_version_check():
    text = _workflow_text("release.yml")
    assert "version-check" in text


def test_release_has_five_target_matrix():
    text = _workflow_text("release.yml")
    assert "linux-x64" in text
    assert "linux-arm64" in text
    assert "macos-x64" in text
    assert "macos-arm64" in text
    assert "windows-x64" in text


def test_release_has_publish_job():
    text = _workflow_text("release.yml")
    assert "publish" in text


def test_release_has_smoke_test():
    text = _workflow_text("release.yml")
    assert "Smoke test install" in text
    assert "install" in text.lower()
    assert "doctor" in text.lower()
    assert "uninstall" in text.lower()


def test_release_version_output_used_by_publish():
    text = _workflow_text("release.yml")
    assert "version-check" in text
    assert "publish" in text


def test_release_smoke_windows_uses_forge_exe():
    text = _workflow_text("release.yml")
    assert "forge.exe" in text
    assert "windows-x64" in text


def test_release_smoke_fails_on_missing_executable():
    text = _workflow_text("release.yml")
    assert "exit 1" in text
    assert "ERROR" in text


def test_release_smoke_includes_version_command():
    text = _workflow_text("release.yml")
    assert "version" in text


def test_release_smoke_uses_runner_temp():
    text = _workflow_text("release.yml")
    assert "RUNNER_TEMP" in text


def test_release_smoke_has_unix_and_windows_steps():
    text = _workflow_text("release.yml")
    assert "Smoke test install (Unix)" in text
    assert "Smoke test install (Windows)" in text


def test_release_publish_has_attestation_permissions():
    text = _workflow_text("release.yml")
    assert "id-token: write" in text
    assert "attestations: write" in text


def test_release_publish_has_attestation_action():
    text = _workflow_text("release.yml")
    assert "attest-build-provenance" in text
