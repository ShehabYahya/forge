---
description: Review Forge memory cards for the current session
---

Enter Forge memory review mode for this session.

Use the `forge_memory_review` tool to drive the entire workflow:

1. Call `forge_memory_review` with `action: "start"`.
2. Call it with `action: "context"` and inspect active and archived cards.
3. Propose and apply a small concrete batch with `action: "apply_batch"`.
4. Re-read context after each batch.
5. Check `memory_gaps` for terminal tasks with no memory card. For each gap
   with a reusable lesson, apply a `create_memory_card` operation with concrete
   memory text (40-400 chars, include a file path or tool name anchor), a why
   (20+ chars), and the source task id. Use `create_pattern_card` when the
   lesson spans 2+ tasks.
6. Finish with `action: "finish"` and `status: "completed"`.

Do not use `edit`, `write`, or `bash` in maintenance mode. Report backend
rejections exactly. If a maintenance call fails, retry once. If it fails again,
tell the user and finish with `status: "failed"` plus a concrete reason.
