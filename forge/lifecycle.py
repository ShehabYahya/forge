from __future__ import annotations

from .task_state import TERMINAL_STATES, TaskSnapshot


class LifecycleError(ValueError):
    pass


def apply_review(task: TaskSnapshot, passed: bool, digest: str | None) -> None:
    if task.state in TERMINAL_STATES:
        raise LifecycleError(f"cannot review terminal task in state {task.state}")
    if task.state not in {"active", "review_blocked", "reviewed"}:
        raise LifecycleError(f"cannot review task in state {task.state}")
    task.state = "reviewed" if passed else "review_blocked"
    task.review_digest = digest if passed else None


def apply_finish(task: TaskSnapshot, *, success: bool, current_digest: str | None,
                 has_changes: bool = True) -> None:
    if task.state == "degraded":
        raise LifecycleError("a degraded outcome cannot be upgraded through normal finish")
    if task.state in TERMINAL_STATES:
        return
    if success:
        # Non-mutation bypass: a task that made no changes may finish successfully
        # without a prior review. Any change requires a passing, fresh review.
        if not has_changes:
            task.state = "completed"
            return
        if task.state != "reviewed":
            raise LifecycleError("successful finish requires a passing review")
        # Prefer per-session transcript digest for concurrent safety.
        # When available, it guards only the session's own files; unrelated
        # concurrent edits in the worktree cannot trigger false staleness.
        # Fall back to total-worktree git digest only when transcript absent.
        review_session_digest = (task.review or {}).get("session_digest")
        current_edited_digest = (task.session_digest or {}).get("edited_files_digest")
        review_edited_digest = (
            review_session_digest.get("edited_files_digest")
            if isinstance(review_session_digest, dict) else None
        )

        if current_edited_digest and review_edited_digest:
            if current_edited_digest != review_edited_digest:
                raise LifecycleError("review is stale; review changes again")
        else:
            if not task.review_digest or task.review_digest != current_digest:
                raise LifecycleError("review is stale; review changes again")

        task.state = "completed"
    else:
        task.state = "failed"


def apply_degraded(task: TaskSnapshot) -> None:
    if task.state in TERMINAL_STATES and task.state != "degraded":
        raise LifecycleError(f"cannot degrade terminal task in state {task.state}")
    task.state = "degraded"

