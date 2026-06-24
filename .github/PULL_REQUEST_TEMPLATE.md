## Summary

What does this change do, in one or two sentences?

## Type

- [ ] feat
- [ ] fix
- [ ] docs
- [ ] chore
- [ ] test
- [ ] refactor

## Scope impact (check any that apply)

- [ ] Changes the public MCP tool surface (five-tool contract)
- [ ] Changes `docs/Forge Native Operating.md` (the system prompt source)
- [ ] Changes the contract (`docs/FORGE_CONTRACT.md`)
- [ ] Changes lifecycle, review, or memory behavior
- [ ] Adds a new config setting (`tests/test_config.py` updated)
- [ ] None of the above

## Verification

Commands run before opening this PR:

```text
python -m pytest -q
python scripts/generate_forge_system.py --check
# in forge/plugin/opencode:
npm run typecheck && npm test && npm run build
```

## Notes

Anything reviewers should know. If this is a breaking change within the `0.x`
alpha series, call it out explicitly.
