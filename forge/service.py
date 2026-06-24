from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
import hashlib
import os
from pathlib import Path
import subprocess
import time
from typing import Any, Callable

from .config import ForgeConfig, load_config, load_warnings
from .context.result_store import ToolResultStore
from .lifecycle import LifecycleError, apply_degraded, apply_finish, apply_review
from .memory.card_factory import create_card_from_draft
from .memory.feedback_store import FeedbackStore
from .memory.inject import format_brief
from .memory import scoring
from .memory.store import MemoryStore
from .persistence import TaskStore
from .review.baseline import capture_tree, diff_trees, sweep_temp_dir
from .review.diff import RepositoryInspectionError, capture_changes, digest_changes, safe_path, validate_repo
from .review.verdict import review_repository
from .task_state import TERMINAL_STATES, TaskSnapshot, response
from .telemetry.events import event, review_completed_event, task_finished_event
from .telemetry.honesty import derive_honesty
from .telemetry.writer import TelemetryWriter


def default_runtime_root() -> Path:
    override = os.environ.get("FORGE_HOME", "").strip() or os.environ.get("FORGE_ALPHA_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".forge"


class ForgeService:
    def __init__(self, runtime_root: Path | str | None = None,
                 clock: Callable[[], float] = time.time,
                 id_factory: Callable[[str], str] | None = None) -> None:
        self.runtime_root = Path(runtime_root) if runtime_root else default_runtime_root()
        self.clock = clock
        self.id_factory = id_factory or self._make_id
        self.config: ForgeConfig = load_config(self.runtime_root)
        self.config_warnings: list[str] = load_warnings()
        self.tasks = TaskStore(self.runtime_root / "tasks.jsonl")
        self.telemetry = TelemetryWriter(self.runtime_root / "telemetry.jsonl")
        self.memory = MemoryStore(self.runtime_root / "memory")
        self.feedback_store = FeedbackStore(
            self.runtime_root / "memory" / "memory_feedback.jsonl", clock=clock)
        self.results = ToolResultStore(self.runtime_root / "tool-results")
        sweep_temp_dir(self.runtime_root / "tmp")

    def start_task(self, task_text: str, repo_root: str,
                         expected_files: list[str] | None = None,
                         host_session_id: str | None = None,
                         replace_active: bool = False,
                         scope_mode: str = "strict") -> dict[str, Any]:
        if not isinstance(task_text, str) or not task_text.strip():
            return response(None, ok=False, required_next_action="provide a non-empty task_text",
                            error="task_text must be a non-empty string")
        if scope_mode not in {"strict", "warning"}:
            return response(None, ok=False, required_next_action="use strict or warning scope",
                            error="invalid scope_mode")
        try:
            repo = validate_repo(Path(repo_root))
            normalized = self._expected_files(repo, expected_files or [])
        except (OSError, RepositoryInspectionError, ValueError) as exc:
            return response(None, ok=False, required_next_action="provide a valid Git repository root",
                            error=str(exc))
        existing = self._bound_task(host_session_id)
        if existing and not replace_active:
            return self._start_response(existing, idempotent=True)
        if existing and replace_active:
            existing.state = "failed"
            existing.updated_at = self._timestamp()
            existing.terminal_result = response(existing, ok=True,
                                                required_next_action="none; task was replaced",
                                                success=False, summary="replaced by a new task")
            self.tasks.append(existing)
            self._emit("task_replaced", existing.task_id)
        seed = f"{repo}\0{host_session_id or ''}\0{task_text}\0{self.clock()}"
        task = TaskSnapshot(task_id=self.id_factory(seed), state="active", task_text=task_text.strip(),
                            repo_root=str(repo), expected_files=normalized,
                            host_session_id=host_session_id, scope_mode=scope_mode,
                            created_at=self._timestamp(), updated_at=self._timestamp())
        concurrent = self._active_for_repo(str(repo))
        if concurrent and concurrent.task_id != task.task_id:
            if host_session_id and concurrent.host_session_id:
                return response(None, ok=False,
                                required_next_action="finish or replace the active task first",
                                error=f"another active task ({concurrent.task_id}) is modifying "
                                "this repository; start a new task with replace_active=True "
                                "or finish the active task before starting another on the "
                                "same repo")
        try:
            task.baseline_tree_id = capture_tree(repo)
            task.baseline_status = "captured"
        except RepositoryInspectionError as exc:
            task.baseline_status = "unavailable"
            task.baseline_capture_error = str(exc)
        self.tasks.append(task)
        warning = self._emit("task_started", task.task_id)
        result = self._start_response(task, idempotent=False)
        if concurrent and concurrent.task_id != task.task_id:
            result.setdefault("warnings", []).append(
                f"another active task ({concurrent.task_id}) is modifying this repository; "
                "concurrent tasks may interfere"
            )
        if warning:
            result["warnings"].append(warning)
        return result

    def review_changes(self, task_id: str,
                             validation_evidence: list[dict[str, Any]] | None = None,
                             remaining_uncertainty: str | None = None,
                             agent_step_intent: str | None = None,
                             target_behavior_claim: str | None = None,
                             owner_boundary_claim: str | None = None,
                             proof_plan: str | None = None,
                             scope_expansions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            return response(None, ok=False, task_id=task_id, required_next_action="start a task",
                            error="task does not exist")
        if task.state in TERMINAL_STATES:
            return response(task, ok=False, required_next_action="none; task is terminal",
                            error=f"cannot review terminal task in state {task.state}")
        verdict = review_repository(Path(task.repo_root), task.expected_files, task.scope_mode,
                                     validation_evidence, remaining_uncertainty, self.clock,
                                     agent_step_intent=agent_step_intent,
                                     target_behavior_claim=target_behavior_claim,
                                     owner_boundary_claim=owner_boundary_claim,
                                     proof_plan=proof_plan,
                                     baseline_tree_id=task.baseline_tree_id,
                                     scope_expansions=scope_expansions,
                                     session_digest=task.session_digest)

        # Inject the current session digest snapshot into the verdict so that
        # apply_finish can check staleness against the per-session digest.
        if task.session_digest and task.session_digest.get("edited_files_digest"):
            verdict["session_digest"] = {
                "edited_files_digest": task.session_digest["edited_files_digest"],
            }

        try:
            apply_review(task, verdict["passed"], verdict["diff_digest"])
        except LifecycleError as exc:
            return response(task, ok=False, required_next_action="inspect lifecycle state", error=str(exc))
        task.review = verdict
        task.updated_at = self._timestamp()
        self.tasks.append(task)
        review_event = review_completed_event(
            task.task_id, self._timestamp(), passed=verdict["passed"],
            evidence_status=verdict["evidence_status"],
            agent_step_intent=agent_step_intent,
            target_behavior_claim=target_behavior_claim,
            owner_boundary_claim=owner_boundary_claim,
            proof_plan=proof_plan)
        telemetry_warning = self.telemetry.append(review_event)
        warnings = list(verdict["warnings"])
        if telemetry_warning:
            warnings.append(telemetry_warning)
        return response(task, ok=verdict["passed"], warnings=warnings,
                        required_next_action="finish_task" if verdict["passed"] else "resolve blockers and review again",
                        review=verdict)

    def finish_task(self, task_id: str, success: bool, summary: str,
                          validation_evidence: list[dict[str, Any]] | None = None,
                          remaining_issues: list[str] | None = None,
                          commands_run: list[str] | None = None,
                          memory_draft: dict | None = None,
                          memory_feedback: list[dict] | None = None) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            return response(None, ok=False, task_id=task_id, required_next_action="start a task",
                            error="task does not exist")
        if task.state in TERMINAL_STATES:
            if task.terminal_result:
                return deepcopy(task.terminal_result)
            return response(task, ok=False, required_next_action="none; task is terminal")
        if not isinstance(success, bool) or not isinstance(summary, str) or not summary.strip():
            return response(task, ok=False, required_next_action="provide success and a non-empty summary",
                            error="invalid finish request")
        current_digest = None
        has_changes = True
        if success:
            try:
                repo = Path(task.repo_root)
                total_changes = capture_changes(repo)
                current_digest = digest_changes(total_changes)

                # Transcript-based signal (per-session, concurrent-safe).
                edited_files = (task.session_digest or {}).get("edited_files") or []
                # Git-based signal (proxy, concurrent-vulnerable).
                git_has_changes = bool(total_changes)
                if task.baseline_tree_id:
                    try:
                        current_tree_id = capture_tree(repo)
                        task_changes = diff_trees(repo, task.baseline_tree_id, current_tree_id)
                        git_has_changes = bool(task_changes)
                    except (RepositoryInspectionError, subprocess.CalledProcessError):
                        git_has_changes = bool(total_changes)

                # Transcript is advisory only when a reliable baseline exists.
                # When the baseline-aware delta says zero changes, the agent
                # may have edited then reverted — trust git in that case.
                has_changes = git_has_changes
                if not has_changes and not task.baseline_tree_id:
                    # No reliable baseline; transcript is the only per-session signal.
                    has_changes = bool(edited_files)
            except RepositoryInspectionError as exc:
                return response(task, ok=False,
                                required_next_action="restore repository inspectability",
                                error=str(exc))
        try:
            apply_finish(task, success=success, current_digest=current_digest,
                         has_changes=has_changes)
        except LifecycleError as exc:
            return response(task, ok=False, required_next_action="review_changes" if success else "inspect lifecycle",
                            error=str(exc))
        task.updated_at = self._timestamp()
        result = response(task, ok=True, required_next_action="none", success=success,
                          summary=summary.strip(), validation_evidence=validation_evidence or [],
                          remaining_issues=remaining_issues or [], verified=bool(success),
                          lifecycle_complete=True)

        claim_evidence_status, finish_claim_honesty = derive_honesty(success, validation_evidence,
                                                                      session_digest=task.session_digest)

        # Memory card creation from agent-supplied draft. The factory only
        # writes to the store on a valid draft; a no-draft finish never creates
        # memory_cards.json. Card creation failure does NOT affect the task
        # outcome — only appends a warning.
        if memory_draft is not None:
            creation = create_card_from_draft(
                task, task.review, (claim_evidence_status, finish_claim_honesty),
                memory_draft, self.memory, self.config, self._timestamp())
            if creation.get("warning"):
                result.setdefault("warnings", []).append(creation["warning"])

        # Finish-time feedback on injected cards. Required-but-non-blocking.
        injected = set(task.injected_memory_cards or [])
        feedback_status = "not_applicable"
        if memory_feedback is not None:
            feedback_status = "provided"
            for item in memory_feedback:
                if not isinstance(item, dict):
                    continue
                card_id = item.get("card_id")
                rating = item.get("rating")
                reason = item.get("reason", "")
                if not isinstance(card_id, str) or not isinstance(rating, str):
                    continue
                if card_id not in injected:
                    # Feedback for a card that was never injected: skip silently.
                    # The agent cannot rate cards it did not see.
                    continue
                self.feedback_store.append_feedback(task.task_id, card_id, rating, reason)
        elif injected:
            # Feedback was missing while cards were injected — non-blocking
            # hidden telemetry warning (surfaced in the response warnings list
            # so callers can debug, but does not fail the finish).
            result.setdefault("warnings", []).append(
                "memory feedback missing for injected cards")
            feedback_status = "missing"

        task.terminal_result = deepcopy(result)
        self.tasks.append(task)
        finished_event = task_finished_event(
            task.task_id, self._timestamp(), success=success,
            commands_run=commands_run,
            finish_claim_honesty=finish_claim_honesty,
            claim_evidence_status=claim_evidence_status,
            injected_memory_cards=task.injected_memory_cards,
            review_blocked=bool(task.review and not task.review.get("passed", False)),
            memory_feedback_status=feedback_status)
        telemetry_warning = self.telemetry.append(finished_event)
        if telemetry_warning:
            result["warnings"].append(telemetry_warning)
            task.terminal_result = deepcopy(result)
        return result

    def submit_outcome(self, success: bool, summary: str, degraded_reason: str,
                             task_id: str | None = None, repo_root: str | None = None) -> dict[str, Any]:
        if not summary or not degraded_reason:
            return response(None, ok=False, task_id=task_id,
                            required_next_action="provide summary and degraded_reason",
                            error="degraded outcome requires summary and reason")
        if not task_id:
            return response(None, ok=False, required_next_action="provide a valid task_id",
                            error="submit_outcome requires an existing task_id")
        task = self.tasks.get(task_id)
        if task and task.state == "degraded" and task.terminal_result:
            return deepcopy(task.terminal_result)
        if not task:
            return response(None, ok=False, task_id=task_id, required_next_action="start a task first",
                            error="task does not exist")
        try:
            apply_degraded(task)
        except LifecycleError as exc:
            return response(task, ok=False, required_next_action="none; task is terminal", error=str(exc))
        task.updated_at = self._timestamp()
        result = response(task, ok=True, required_next_action="start a new task for verified lifecycle completion",
                          success=success, summary=summary.strip(), degraded_reason=degraded_reason.strip(),
                          verified=False, lifecycle_complete=False)
        task.terminal_result = deepcopy(result)
        self.tasks.append(task)
        warning = self._emit("degraded_outcome_submitted", task.task_id, reported_success=success)
        if warning:
            result["warnings"].append(warning)
        return result

    def expand_tool_result(self, task_id: str, handle: str, start: int = 0,
                                 max_chars: int = 16_000) -> dict[str, Any]:
        task = self.tasks.get(task_id)
        if not task:
            return response(None, ok=False, task_id=task_id, required_next_action="provide an existing task_id",
                            error="task does not exist")
        try:
            expansion = self.results.expand(task_id, handle, start, max_chars)
        except (ValueError, KeyError, PermissionError, OSError) as exc:
            return response(task, ok=False, required_next_action="check handle ownership and bounds", error=str(exc))
        return response(task, ok=True, required_next_action="expand again if incomplete", expansion=expansion)

    def _start_response(self, task: TaskSnapshot, idempotent: bool) -> dict[str, Any]:
        cards = self.memory.read_active()
        feedback_aggregate = scoring.add_outcome_history(
            self.memory.read_feedback_aggregate(), self.telemetry.read_all())
        selected_ids = scoring.select_cards(
            cards, task, feedback_aggregate, self.config.memory.scoring)
        task.injected_memory_cards = list(selected_ids)
        self.tasks.append(task)
        cards_by_id = {c.card_id: c for c in cards}
        selected_cards = [cards_by_id[cid] for cid in selected_ids if cid in cards_by_id]
        ranked = [(0, c) for c in selected_cards]
        context = {"task_text": task.task_text, "repo_root": task.repo_root,
                   "expected_files": task.expected_files, "scope_mode": task.scope_mode,
                   "memory_brief": format_brief(ranked),
                   "memory_card_count": len(selected_ids),
                   "baseline_status": task.baseline_status}
        warnings = list(self.tasks.warnings)
        memory_warnings = self.memory.corruption_warnings
        if memory_warnings:
            warnings.extend(f"memory: {w}" for w in memory_warnings)
        if self.config_warnings:
            warnings.extend(self.config_warnings)
            self.config_warnings = []
        return response(task, ok=True, warnings=warnings,
                        required_next_action="work, then review_changes", prepared_context=context,
                        idempotent=idempotent)

    def _expected_files(self, repo: Path, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            path = safe_path(repo, value)
            if path.exists() or path.is_symlink():
                safe_path(repo, value, must_exist=True)
            normalized.append(path.relative_to(repo).as_posix())
        return sorted(set(normalized))

    def _bound_task(self, session_id: str | None) -> TaskSnapshot | None:
        if not session_id:
            return None
        return next((task for task in reversed(self.tasks.all())
                     if task.host_session_id == session_id and task.state not in TERMINAL_STATES), None)

    def _active_for_repo(self, repo_root: str | None) -> TaskSnapshot | None:
        if not repo_root:
            return None
        try:
            target = str(Path(repo_root).expanduser().resolve(strict=True))
        except OSError:
            return None
        return next((task for task in reversed(self.tasks.all())
                     if task.repo_root == target and task.state not in TERMINAL_STATES), None)

    def _emit(self, name: str, task_id: str | None, **fields: Any) -> str | None:
        return self.telemetry.append(event(name, task_id, self._timestamp(), **fields))

    def _timestamp(self) -> str:
        return datetime.fromtimestamp(self.clock(), UTC).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _make_id(seed: str) -> str:
        return "task_" + hashlib.sha256(seed.encode()).hexdigest()[:24]
