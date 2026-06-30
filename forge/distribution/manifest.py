"""Manifest hashing and atomic JSON read/write helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    chunk_size = 65536
    with open(path, "rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    result = json.loads(raw)
    if not isinstance(result, dict):
        raise ValueError(f"{path} is not a JSON object")
    return result


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def _backup(path: Path) -> Path | None:
    if not path.exists():
        return None
    backup = path.with_suffix(path.suffix + ".forge-backup")
    shutil.copy2(path, backup)
    return backup


def _restore_backup(backup: Path | None, target: Path) -> None:
    if backup is None or not backup.exists():
        return
    shutil.copy2(backup, target)
    backup.unlink(missing_ok=True)


def verify_manifest(version_dir: Path) -> tuple[bool, list[str], list[str]]:
    """Verify installed files against bundled manifest.json digests.

    This covers post-extraction integrity; archive-level tamper protection
    rests on the archive checksum and GitHub artifact attestation.

    Returns ``(ok, errors, warnings)``. A version directory whose manifest
    has no ``digests`` field (legacy source install) is treated as
    integrity-unverified: ``ok`` is ``True`` with a warning so callers do
    not silently claim digest verification.
    """
    errors: list[str] = []
    warnings: list[str] = []
    manifest_path = version_dir / "manifest.json"
    if not manifest_path.exists():
        return False, ["manifest not found"], warnings
    try:
        manifest = _read_json(manifest_path)
    except (ValueError, OSError) as exc:
        return False, [f"manifest malformed: {exc}"], warnings
    digests = manifest.get("digests")
    if not digests or not isinstance(digests, dict):
        warnings.append("manifest has no digests; integrity not verified")
        return True, errors, warnings
    for rel_path, expected_digest in digests.items():
        rel_path = str(rel_path)
        normalized = rel_path.replace("\\", "/")
        if not rel_path or Path(rel_path).is_absolute() or ".." in Path(normalized).parts:
            errors.append(f"unsafe manifest key: {rel_path}")
            continue
        if not isinstance(expected_digest, str) or len(expected_digest) != 64:
            errors.append(f"malformed digest for {rel_path}")
            continue
        file_path = version_dir / normalized
        if not file_path.is_file():
            errors.append(f"missing file: {rel_path}")
            continue
        try:
            actual = _sha256_file(file_path)
        except OSError as exc:
            errors.append(f"cannot read {rel_path}: {exc}")
            continue
        if actual != expected_digest:
            errors.append(f"digest mismatch for {rel_path}")
    return (len(errors) == 0), errors, warnings
