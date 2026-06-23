"""Build a reproducible Forge release bundle for the current platform.

Usage:
  python scripts/build_release.py [--version 0.1.0-alpha.1] [--output dist/]
  python scripts/build_release.py --check  # verify build is clean
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DIST = REPO_ROOT / "dist"


def _platform_target() -> str:
    import os
    system = sys.platform
    machine = os.uname().machine if hasattr(os, "uname") else "x86_64"
    if system == "linux":
        arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
        return f"linux-{arch}"
    if system == "darwin":
        arch = "arm64" if machine in ("aarch64", "arm64") else "x64"
        return f"macos-{arch}"
    if system == "win32":
        return "windows-x64"
    return f"{system}-x64"


def _sha256_hex(path: Path) -> str:
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def build_release(version: str, output_dir: Path) -> Path:
    target = _platform_target()
    bin_name = "forge.exe" if sys.platform == "win32" else "forge"
    bundle_name = f"forge-{version}-{target}"
    bundle_dir = output_dir / bundle_name
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir, ignore_errors=True)
    bundle_dir.mkdir(parents=True)

    # -- Plugin bundle (must be pre-built) --
    plugin_src = REPO_ROOT / "forge" / "plugin" / "opencode" / "dist"
    if not (plugin_src / "index.js").exists():
        raise RuntimeError("Plugin not built. Run: npm run build in forge/plugin/opencode/")
    plugin_dst = bundle_dir / "plugin"
    plugin_dst.mkdir()
    for f in plugin_src.iterdir():
        if f.is_file():
            shutil.copy2(f, plugin_dst / f.name)

    # -- Loader --
    loader_src = REPO_ROOT / "forge" / "plugin" / "opencode" / "loader.js"
    if loader_src.exists():
        shutil.copy2(loader_src, bundle_dir / "loader.js")

    # -- Skill --
    skill_src = REPO_ROOT / "forge" / "skills" / "review-memory" / "SKILL.md"
    skill_dst = bundle_dir / "skills" / "review-memory"
    skill_dst.mkdir(parents=True)
    shutil.copy2(skill_src, skill_dst / "SKILL.md")

    # -- License --
    license_src = REPO_ROOT / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, bundle_dir / "LICENSE")

    # -- Install docs --
    install_src = REPO_ROOT / "INSTALL.md"
    if install_src.exists():
        shutil.copy2(install_src, bundle_dir / "INSTALL.md")

    # -- Build the frozen executable using PyInstaller --
    spec = REPO_ROOT / "packaging" / "forge.spec"
    if spec.exists() and importlib.util.find_spec("PyInstaller") is not None:
        subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--distpath",
             str(bundle_dir / "bin"), "--workpath",
             str(output_dir / ".pyinstaller-work"),
             str(spec)],
            check=True, cwd=str(REPO_ROOT),
        )
    else:
        bin_dir = bundle_dir / "bin"
        bin_dir.mkdir(parents=True, exist_ok=True)
        python = sys.executable
        executor = bin_dir / bin_name
        executor.write_text(
            f"#!{python}\n"
            f'import sys; sys.path.insert(0, "{REPO_ROOT}"); sys.argv[0] = "{executor}"\n'
            f"from forge.cli import main\n"
            f"main()\n"
        )
        executor.chmod(0o755)

    # -- Manifest --
    asset_paths: dict[str, str] = {}
    asset_digests: dict[str, str] = {}
    for root, _dirs, files in sorted(bundle_dir.walk(top_down=True)):
        for fname in sorted(files):
            full = root / fname
            rel = str(full.relative_to(bundle_dir))
            asset_paths[rel] = rel
            asset_digests[rel] = _sha256_hex(full)

    manifest = {
        "version": version,
        "platform": target,
        "assets": asset_paths,
        "digests": asset_digests,
    }
    manifest_path = bundle_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    # -- Archive --
    archive_name = f"{bundle_name}.tar.gz"
    archive_path = output_dir / archive_name
    with tarfile.open(archive_path, "w:gz") as tar:
        for fpath in sorted(bundle_dir.rglob("*")):
            if fpath.is_file():
                tar.add(fpath, arcname=f"{bundle_name}/{fpath.relative_to(bundle_dir)}")

    # -- Checksum file --
    checksum_path = output_dir / f"{bundle_name}.sha256"
    archive_digest = _sha256_hex(archive_path)
    checksum_path.write_text(f"{archive_digest}  {archive_name}\n", encoding="utf-8")

    print(f"Release bundle: {archive_path}")
    print(f"Checksum: {archive_digest}")
    return archive_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Forge release bundle")
    parser.add_argument("--version", default=None, help="Version string")
    parser.add_argument("--output", default=str(DIST), help="Output directory")
    args = parser.parse_args()

    from forge import __version__
    version = args.version or __version__

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    bundle = build_release(version, output_dir)
    print(f"Done: {bundle}")


if __name__ == "__main__":
    main()
