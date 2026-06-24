# Detailed installation

This page covers the details behind the quick install in the
[repository-level install guide](../INSTALL.md). For most users the one-command
install is all that is needed.

## Release bundle contents

Each published Forge release bundle contains:

- The native Forge runtime for the target platform and architecture
- The built OpenCode plugin and stable global loader
- The Forge system operating prompt bundled into the plugin
- The `/review-memory` command behavior and the `review-memory` skill
- The license, release manifest, and checksums

One authoritative package version ships all assets together; they cannot be
upgraded independently. The release manifest records the version, target
operating system, target architecture, included assets, and asset digests.

## Platform targets

| Target | Runner |
|---|---|
| `linux-x64` | Ubuntu |
| `linux-arm64` | Ubuntu ARM |
| `macos-x64` | macOS 13 |
| `macos-arm64` | macOS (Apple silicon) |
| `windows-x64` | Windows |

The installer auto-detects Linux/macOS targets. Windows uses `windows-x64`.

## Where things live

| Path | Contents |
|---|---|
| Global OpenCode config | Forge plugin, MCP registration, `/review-memory` command, skill |
| `~/.forge/` | Runtime state: task receipts, telemetry, memory, tool results |
| `~/.forge/config.json` | Optional overrides (a subset of the spec defaults) |

Runtime state is never written into a controlled repository. Redirect the
runtime root with `FORGE_HOME` (or legacy `FORGE_ALPHA_HOME`).

## Environment variables

| Variable | Purpose |
|---|---|
| `FORGE_VERSION` | Pin a version for the bootstrap installer |
| `FORGE_HOME` | Redirect the runtime root away from `~/.forge/` |
| `FORGE_RELEASE_BASE` | Override the GitHub release download base URL |
| `OPENCODE_CONFIG_DIR` | Override the OpenCode config root detected by `forge doctor` |

## Reinstall, upgrade, and rollback

- Reinstalling the same version is idempotent — no duplicate plugin, MCP,
  command, or skill registrations are created.
- Upgrading replaces the complete versioned asset set as one unit; assets from
  different versions are never mixed.
- A failed download, verification, extraction, or configuration step leaves the
  previous working installation usable.

## Verifying integrity

The bootstrap installer verifies every archive against its published SHA-256
checksum before extraction. On mismatch, installation is refused. You can also
compare a downloaded checksum against the published release manifest manually.

## Wheel-based source install

For contributor workflows, the wheel includes the Python package, optional
skills, OpenCode adapter sources, the fallback command asset, and the built
`dist/index.js` plugin entry. Registering that plugin also registers
`/review-memory` through OpenCode configuration.

```bash
python3.12 -m build
python3.12 -m venv .venv
.venv/bin/pip install dist/forge-0.1.0a1-py3-none-any.whl
```

See the [walkthrough](WALKTHROUGH.md) for a complete end-to-end lifecycle run
in a temporary environment, and [CONTRIBUTING.md](../CONTRIBUTING.md) for the
development setup.
