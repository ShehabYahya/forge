# Forge Alpha

Forge Alpha is a narrow Python 3.12 runtime control layer for coding agents. Python owns task lifecycle, deterministic Git review, local memory selection, context policy, and telemetry. Host plugins only forward events and apply returned decisions.

The normal lifecycle is `forge_start_task` → work → `forge_review_changes` → `forge_finish_task`. Successful completion requires a passing review whose digest still matches the repository. `forge_submit_outcome` is a visibly degraded, unverified fallback.

## Install

```bash
python3.12 -m venv .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
python -m pytest -q
forge-alpha --help
```

Runtime state defaults to `~/.forge-alpha/` and can be redirected through `ForgeService(runtime_root=...)`. Runtime state is never written to a controlled repository.

Limits: Forge Alpha does not execute tools, sandbox processes, claim semantic correctness, learn from outcomes, or enforce the optional Anvil skill. See [the contract](docs/FORGE_ALPHA_CONTRACT.md) and [installation guide](INSTALL.md).

