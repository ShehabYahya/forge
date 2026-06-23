# Extraction Ledger

| Old reference | Observed behavior | Alpha requirement | Decision | New owner | Protecting test |
|---|---|---|---|---|---|
| `forge_service/forge_service.py` | Broad service facade | Five narrow operations | rewrite | `forge/service.py` | `test_service_contract.py` |
| `forge_service/task_session.py` | JSONL sessions | Append-only superseding snapshots | port-concept | `forge/persistence.py` | `test_task_persistence.py` |
| `forge_service/finish_service.py` | Completion checks | Fresh review and honest failure | rewrite | `forge/lifecycle.py` | `test_lifecycle.py` |
| `forge_service/workspace.py` | Git and path inspection | Deterministic safe change capture | port-concept | `forge/review/diff.py` | `test_review_diff.py` |
| review regression tests | Claim/evidence regressions | Reported evidence stays reported | port-concept | `forge/review/evidence.py` | `test_review_verdict.py` |
| `forge_service/context_governor.py` | Token/output policy | Lightweight host-native policy without plugin lifecycle state | rewrite | `forge/plugin/opencode/src/governor.ts` | `governor.test.ts` |
| `forge_service/tool_result_store.py` | Restrictive virtualized output handles with a cumulative budget | Full redacted storage with exact line summaries, 240-line and 64,000-character per-call bounds, and no cumulative quota | rewrite | `forge/plugin/opencode/src/compaction.ts` | `compaction.test.ts` |
| plugin `policy.ts` | Broad host policy and task-before-mutation enforcement | Native host permission escalation without copying the MCP shell allowlist or plugin task state machine | rewrite | TypeScript governor | `plugin.test.ts` |
| memory card schema/store/search/injection | Large evolving memory system | Manual deterministic cards only | rewrite | `forge/memory/` | `test_memory_cards.py` |
| `forge_service/plugin_protocol.py` | Plugin bridge protocol | Four hidden forwarding operations | rewrite | `forge/plugin/protocol.py` | `test_plugin_adapter.py` |
| plugin transport and index | Event hooks and per-call backend subprocess | Native OpenCode hooks with no per-call Python transport | rewrite | `forge/plugin/opencode/` | `plugin.test.ts` and runtime probes |
| `forge_mcp/server.py` | Seventeen public tools | Exact five-tool surface | rewrite | `forge/mcp_server.py` | `test_mcp_contract.py` |
| CBS, learning, Goal Mode, retries, OpenHands, benchmarks | Broad orchestration product | Explicitly excluded | leave-behind | none | contract/source scans |

The two expansion APIs are intentionally distinct. Production host output creates session-owned `fo_` handles for `forge_expand_output`. The Python `forge_expand_tool_result` endpoint accepts task-owned `fr_` handles with a 16,000-character per-call and 32,000-character cumulative budget, but the normal production flow does not currently produce those handles. Retaining that endpoint is compatibility debt, not evidence of per-call plugin transport.
