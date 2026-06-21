# Walkthrough

Build and install into a temporary environment:

```bash
cd ~/forge-alpha
python3.12 -m build
tmp=$(mktemp -d)
python3.12 -m venv "$tmp/venv"
"$tmp/venv/bin/pip" install dist/forge_alpha-0.1.0a1-py3-none-any.whl
export HOME="$tmp/home"
mkdir -p "$HOME" "$tmp/repo"
git -C "$tmp/repo" init -q
git -C "$tmp/repo" config user.email walkthrough@example.invalid
git -C "$tmp/repo" config user.name Walkthrough
printf 'base\n' > "$tmp/repo/base.txt"
git -C "$tmp/repo" add base.txt
git -C "$tmp/repo" commit -q -m baseline
```

The MCP command is `$tmp/venv/bin/forge-alpha`. Point one MCP stdio configuration at that command. The packaged OpenCode plugin entry is under the environment's `site-packages/forge/plugin/opencode/dist/index.js`; register that file once. The TypeScript plugin applies host-tool policy and compaction in-process and never creates tasks automatically or blocks all work until a task exists. This differs intentionally from the old `~/Forge` plugin task state machine.

For example, a 2,000-line, 8,893-character command result is replaced with a handle and at most 20 exact ranges such as `L1-L100`, `L101-L200`, and `L1901-L2000`. The agent can call `forge_expand_output(handle="fo_...", start_line=995, end_line=1005)` to retrieve that exact slice. A range or search call returns at most 64,000 content characters; a range is also limited to 240 lines, while search returns at most 20 matches with up to 10 context lines. Calls may be repeated because there is no cumulative quota.

Run a complete lifecycle with an explicitly redirected runtime root:

```bash
"$tmp/venv/bin/python" - "$tmp" <<'PY'
import json
from pathlib import Path
import sys
from forge.service import ForgeService

root = Path(sys.argv[1])
repo = root / "repo"
runtime = root / "home" / ".forge-alpha"
service = ForgeService(runtime_root=runtime)
started = service.forge_start_task("add feature", str(repo), ["feature.py"], "walkthrough-session")
(repo / "feature.py").write_text("answer = 42\n", encoding="utf-8")
reviewed = service.forge_review_changes(started["task_id"], [{"status": "passed", "command": "python -m compileall"}])
finished = service.forge_finish_task(started["task_id"], True, "Added feature", [{"status": "passed"}])
assert reviewed["state"] == "reviewed"
assert finished["state"] == "completed"
print(json.dumps(finished, indent=2))
print((runtime / "tasks.jsonl").read_text())
print((runtime / "telemetry.jsonl").read_text())
PY
```

Demonstrate fallback separately; it remains unverified and lifecycle-incomplete:

```bash
"$tmp/venv/bin/python" - "$tmp" <<'PY'
from pathlib import Path
import sys
from forge.service import ForgeService

root = Path(sys.argv[1])
service = ForgeService(root / "home" / ".forge-alpha")
result = service.forge_submit_outcome(False, "Backend unavailable", "adapter outage", repo_root=str(root / "repo"))
assert result["state"] == "degraded"
assert result["verified"] is False
assert result["lifecycle_complete"] is False
print(result)
PY
```
