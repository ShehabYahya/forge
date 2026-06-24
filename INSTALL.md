# Installation

Forge ships as self-contained, platform-native release bundles that install
globally into OpenCode. No Python, npm, virtual environment, or source checkout
is required for normal use.

## Global install (recommended)

**Linux / macOS:**

```bash
curl -fsSL https://github.com/username/forge/releases/latest/download/install.sh | bash
```

**Windows (PowerShell):**

```powershell
irm https://github.com/username/forge/releases/latest/download/install.ps1 | iex
```

The installer:

1. Detects your platform and architecture.
2. Downloads the matching release archive and its SHA-256 checksum.
3. Verifies the archive against the checksum (refuses on mismatch).
4. Extracts and delegates durable installation to the verified native
   executable, which merges Forge into your global OpenCode configuration.
5. Runs diagnostics.

Re-running the same command upgrades to the requested version. Pin a version
with `FORGE_VERSION`:

```bash
FORGE_VERSION=0.1.0-alpha.1 curl -fsSL https://github.com/username/forge/releases/latest/download/install.sh | bash
```

> Replace `username` with the published GitHub owner before tagging a release.

### What the installer changes

- Adds the Forge plugin, MCP server registration, the `/review-memory` command,
  and the `review-memory` skill to your **global** OpenCode configuration.
- Backs up and atomically applies configuration changes — a failed install
  leaves the prior configuration intact.
- Preserves unrelated OpenCode settings and comments.
- Writes nothing into your repositories. Runtime data lives under `~/.forge/`.

### Verify the install

```bash
forge doctor
```

`doctor` checks version consistency, executable availability, plugin discovery,
skill discovery, global MCP configuration, and runtime startup. It exits
non-zero on failure.

## From source (contributors)

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
forge mcp
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full development setup, the
plugin build, and the checks that must pass before a pull request.

## Plugin development

```bash
cd forge/plugin/opencode
npm install
npm run typecheck && npm test && npm run build
```

The bundled `dist/index.js` is the plugin entry OpenCode loads. The verified
development sequence is: TypeScript type checking, the plugin test suite, plugin
bundling, then rebuilding the Python wheel.

## Uninstall

Remove the Forge integration only (runtime data is preserved):

```bash
forge uninstall
```

Remove runtime data as well:

```bash
forge purge            # prompts for confirmation
forge purge --force    # skip the prompt
```

## Diagnostics

```bash
forge doctor
```

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for common problems and
fixes.
