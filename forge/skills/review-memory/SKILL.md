---
name: review-memory
description: Disciplined Forge memory maintenance using the hidden review backend.
---

# Review Memory

Use this workflow when maintaining Forge memory cards through `/review-memory`.

1. Start maintenance mode with `forge_memory_review` using `action: "start"`.
2. Read the current state with `action: "context"`.
3. Plan the smallest coherent batch. Prefer a few precise operations over a large rewrite.
4. Apply the batch with `action: "apply_batch"` and an explicit JSON array.
5. Re-read context and confirm whether the result improved the memory set.
6. Finish with `action: "finish"` and `status: "completed"` when done.

Rules:

- Do not use `edit`, `write`, or `bash` while maintenance mode is active.
- Use backend validation and rejection reasons as authoritative.
- Do not fabricate archived, merged, or edited outcomes.
- Keep edits concrete. Avoid generic guidance.

Failure handling:

1. If a maintenance call fails, retry once.
2. If the retry fails, tell the user what failed.
3. Exit cleanly with `forge_memory_review` using `action: "finish"`, `status: "failed"`, and a concrete `reason`.
4. Never claim the batch was applied when the backend rejected it.
