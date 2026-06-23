import json
import tarfile
from pathlib import Path

import pytest

from forge import __version__


@pytest.fixture(scope="module")
def release_bundle(tmp_path_factory):
    from scripts.build_release import build_release
    tmp_path = tmp_path_factory.mktemp("release")
    return build_release(__version__, tmp_path)


def test_build_creates_archive_and_checksum(release_bundle):
    b = release_bundle
    assert b.exists()
    assert b.name.startswith("forge-")
    assert not b.name.startswith("forge-alpha-")
    assert b.name.endswith(".tar.gz")

    sha = b.with_name(b.name.replace(".tar.gz", ".sha256"))
    assert sha.exists()


def test_archive_contains_manifest(release_bundle):
    b = release_bundle
    with tarfile.open(b, "r:gz") as tar:
        names = tar.getnames()
    manifest_entry = [n for n in names if n.endswith("/manifest.json")]
    assert manifest_entry


def test_archive_contains_plugin_and_skill(release_bundle):
    b = release_bundle
    with tarfile.open(b, "r:gz") as tar:
        names = set(tar.getnames())
    assert any("plugin/index.js" in n for n in names)
    assert any("skills/review-memory/SKILL.md" in n for n in names)
    assert any("loader.js" in n for n in names)


def test_manifest_has_required_keys(release_bundle):
    b = release_bundle
    with tarfile.open(b, "r:gz") as tar:
        for member in tar.getmembers():
            if member.name.endswith("manifest.json"):
                content = json.loads(tar.extractfile(member).read())
                break
    assert "version" in content
    assert "platform" in content
    assert "assets" in content
    assert "digests" in content
    assert content["version"] == __version__


def test_manifest_digests_match_assets(release_bundle):
    import hashlib
    b = release_bundle
    with tarfile.open(b, "r:gz") as tar:
        manifest = None
        for member in tar.getmembers():
            if member.name.endswith("manifest.json"):
                manifest_bytes = tar.extractfile(member).read()
                manifest = json.loads(manifest_bytes)
                break
    assert manifest is not None
    for asset_path, expected_digest in manifest["digests"].items():
        with tarfile.open(b, "r:gz") as tar:
            for member in tar.getmembers():
                if member.name.endswith(asset_path):
                    data = tar.extractfile(member).read()
                    actual = hashlib.sha256(data).hexdigest()
                    assert actual == expected_digest, f"digest mismatch for {asset_path}"


def test_checksum_file_matches_archive(release_bundle):
    import hashlib
    b = release_bundle
    sha = b.with_name(b.name.replace(".tar.gz", ".sha256"))
    expected = sha.read_text().split()[0]
    actual = hashlib.sha256(b.read_bytes()).hexdigest()
    assert actual == expected


def test_version_in_archive_name(release_bundle):
    b = release_bundle
    assert __version__ in b.name
    target = b.name.split(f"{__version__}-", 1)[1].replace(".tar.gz", "")
    assert "-" in target
