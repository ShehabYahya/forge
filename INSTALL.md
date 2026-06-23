# Installation

For the recommended global installation:

**Linux / macOS:**
```bash
curl -fsSL https://github.com/username/forge/releases/latest/download/install.sh | bash
```

**Windows (PowerShell):**
```powershell
irm https://github.com/username/forge/releases/latest/download/install.ps1 | iex
```

The installer downloads the platform-native bundle, verifies its checksum, installs all Forge assets globally into OpenCode, and runs diagnostics. Re-running the same command upgrades to the requested version.

To pin a version, set `FORGE_VERSION` before running the installer.

## Source installation (for contributors)

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
forge mcp
```

## Plugin development

Run `npm install`, then `npm run typecheck && npm test && npm run build` from `forge/plugin/opencode/`.

## Uninstall

```bash
forge uninstall
```

Runtime data at `~/.forge/` is preserved by default. To remove it as well:

```bash
forge purge
```

## Diagnostics

```bash
forge doctor
```

See `docs/TROUBLESHOOTING.md` for common problems.
