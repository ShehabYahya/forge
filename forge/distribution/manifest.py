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
