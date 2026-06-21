# Installation

Python 3.12 or newer is required.

From source: `python -m pip install -e '.[dev]'`.

From a wheel: run `python -m build`, then `python -m pip install dist/forge_alpha-0.1.0a1-py3-none-any.whl`.

Run the MCP stdio server with `forge-alpha`. The installation is independent and does not read from the old Forge repository.

For OpenCode, register exactly one MCP entry and one plugin entry. Point the MCP command at `forge-alpha` and the plugin entry at `forge/plugin/opencode/dist/index.js` from the installed package or source checkout. Do not register both global and project-local copies of either entry; OpenCode starts one stdio MCP process for each resolved registration.

The repository includes the built plugin. During plugin development, run `npm install`, then `npm run typecheck && npm test && npm run build` from `forge/plugin/opencode/`. Rebuild the Python distribution afterward with the repository virtual environment's `python -m build` so the wheel contains the current bundle.
