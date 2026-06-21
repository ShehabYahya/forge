# Extraction Ledger

| Old reference | Observed behavior | Alpha requirement | Decision | New owner | Protecting test |
|---|---|---|---|---|---|
| `forge_service/forge_service.py` | Broad service facade | Five narrow operations | rewrite | `forge/service.py` | `test_service_contract.py` |
| `forge_service/task_session.py` | JSONL sessions | Append-only superseding snapshots | port-concept | `forge/persistence.py` | `test_task_persistence.py` |
| `forge_service/finish_service.py` | Completion checks | Fresh review and honest failure | rewrite | `forge/lifecycle.py` | `test_lifecycle.py` |
| `forge_service/workspace.py` | Git and path inspection | Deterministic safe change capture | port-concept | `forge/review/diff.py` | `test_review_diff.py` |
| review regression tests | Claim/evidence regressions | Reported evidence stays reported | port-concept | `forge/review/evidence.py` | `test_review_verdict.py` |
| `forge_service/context_governor.py` | Token/output policy | Conservative capability-aware policy | rewrite | `forge/context/governor.py` | `test_context_governor.py` |
| `forge_service/tool_result_store.py` | Output handles | Bounded task-owned redacted storage | rewrite | `forge/context/result_store.py` | `test_tool_result_store.py` |
| plugin `policy.ts` | Host-side policy | Leave business rules in Python | leave-behind | Python governor | `test_plugin_adapter.py` |
| memory card schema/store/search/injection | Large evolving memory system | Manual deterministic cards only | rewrite | `forge/memory/` | `test_memory_cards.py` |
| `forge_service/plugin_protocol.py` | Plugin bridge protocol | Four hidden forwarding operations | rewrite | `forge/plugin/protocol.py` | `test_plugin_adapter.py` |
| plugin transport and index | Event hooks and policy | Transport-only forwarding | rewrite | `forge/plugin/opencode/` | `test_plugin_adapter.py` |
| existing Anvil skill and parser | Review workflow | Optional inert guidance | rewrite | `forge/skills/anvil/SKILL.md` | `test_review_verdict.py` |
| `forge_mcp/server.py` | Seventeen public tools | Exact five-tool surface | rewrite | `forge/mcp_server.py` | `test_mcp_contract.py` |
| CBS, learning, Goal Mode, retries, OpenHands, benchmarks | Broad orchestration product | Explicitly excluded | leave-behind | none | contract/source scans |

