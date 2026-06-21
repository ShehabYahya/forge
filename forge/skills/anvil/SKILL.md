---
name: anvil
description: Optional disciplined implementation and review workflow.
---

# Anvil

Agents may elect to use Anvil for work that benefits from explicit review discipline. Forge Alpha does not select it, inject its full text, block on it, or change lifecycle or governor decisions because of it.

1. Classify the request: explanation, diagnosis, implementation, or review.
2. Plan the smallest coherent change and list observable acceptance checks.
3. Review the plan for ownership, boundary, migration, and rollback gaps.
4. Implement within the declared scope and preserve unrelated work.
5. Audit the resulting diff, including failure paths and packaging effects.
6. Report evidence as observed or reported; never upgrade reported evidence into observation.

When a structured verdict is requested, place exactly one of these values on the first line: `APPROVE`, `APPROVE_WITH_NOTES`, `REQUEST_CHANGES`, `REJECT`, or `REVIEW_FAILED`. Malformed output is `REVIEW_FAILED`.

