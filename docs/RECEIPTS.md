# Forge Receipts

Forge receipts are the product surface. They turn "the agent says it is done"
into an inspectable record of what happened.

A receipt is not a proof of perfect code. It is proof of the workflow facts Forge
can observe: task scope, changed files, review freshness, validation evidence,
warnings, remaining uncertainty, and memory candidates.

## What A Receipt Answers

- What task did the agent start?
- Which files were session-captured as changed?
- Did those changes stay inside declared scope?
- Was review run after the final edit?
- Was validation merely reported, or did Forge observe evidence?
- What risks or unsupported claims remain?
- What should be remembered for future tasks?

## Example: Clean Completion

```text
Forge Receipt

Task: Fix config loading bug
Outcome: completed, validation observed

Changed files:
- forge/config.py
- tests/test_config.py

Scope:
- Declared: forge/config.py, tests/test_config.py
- Extra files: none
- Review freshness: fresh after final edit

Validation:
- pytest tests/test_config.py -q: observed passed
- Ran after last edit: yes

Review:
- Session log: inspected
- Scope: passed
- Syntax: passed
- Remaining uncertainty: not tested on Windows

Memory:
- 1 candidate lesson recorded for future tasks
```

## Example: Stale Review

```text
Forge Receipt

Task: Update install docs
Outcome: blocked

Changed files:
- README.md
- INSTALL.md

Scope:
- Declared: README.md, INSTALL.md
- Extra files: none
- Review freshness: stale

Blocking issue:
- Files changed after the last passing review.

Required next action:
- Run review again after the final edit, then finish.
```

## Example: Degraded Outcome

```text
Forge Receipt

Task: Apply plugin migration
Outcome: degraded, unverified

Reason:
- Backend unavailable before normal review could complete.

Changed files:
- Unknown to Forge

Validation:
- Not observed

Required next action:
- Inspect the worktree manually before trusting the result.
```

## Draft And Seal

`forge_review_changes` creates the draft proof. It inspects the host session log,
checks scope and syntax, records validation evidence, and saves the session
digest used to detect later edits.

`forge_finish_task` seals the receipt. A successful finish requires a passing
review and the same current session digest. If the host logs another edit after
review, the receipt cannot be sealed as completed until review runs again. If
session evidence is unavailable, Forge cannot seal a successful receipt and the
task must degrade.

## What Forge Can And Cannot Prove

Forge can prove workflow facts:

- the task was started
- the host session logged changes in specific files
- the task delta was in or out of declared scope
- review was fresh or stale at finish time
- validation evidence was reported or observed
- the final result was completed, failed, or degraded

Forge cannot prove full semantic correctness. Passing tests may still be weak,
irrelevant, or incomplete. The receipt makes that uncertainty visible instead of
letting the final answer hide it.

Mutation-capable shell commands (e.g. ``sed -i``, ``rm``, ``git checkout``)
without a corresponding edit/write tool call in the session are flagged as
capture uncertainty in the receipt. Outside-session concurrent changes are
intentionally not treated as task-owned by default.
