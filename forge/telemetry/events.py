from __future__ import annotations

from typing import Any


def event(name: str, task_id: str | None, timestamp: str, **fields: Any) -> dict[str, Any]:
    return {"schema_version": 1, "event": name, "task_id": task_id, "timestamp": timestamp, **fields}


def review_completed_event(task_id: str | None, timestamp: str, *, passed: bool,
                           evidence_status: str,
                           agent_step_intent: str | None = None,
                           target_behavior_claim: str | None = None,
                           owner_boundary_claim: str | None = None,
                           proof_plan: str | None = None,
                           **extra: Any) -> dict[str, Any]:
    """Build a ``review_completed`` event carrying the 4 narrative fields plus
    ``claim_evidence_status``. Narrative fields are omitted when ``None`` so
    events stay clean; ``claim_evidence_status`` is always present.
    """
    fields: dict[str, Any] = {"passed": passed, "claim_evidence_status": evidence_status}
    if agent_step_intent is not None:
        fields["agent_step_intent"] = agent_step_intent
    if target_behavior_claim is not None:
        fields["target_behavior_claim"] = target_behavior_claim
    if owner_boundary_claim is not None:
        fields["owner_boundary_claim"] = owner_boundary_claim
    if proof_plan is not None:
        fields["proof_plan"] = proof_plan
    fields.update(extra)
    return event("review_completed", task_id, timestamp, **fields)


def task_finished_event(task_id: str | None, timestamp: str, *, success: bool,
                        commands_run: list[str] | None = None,
                        finish_claim_honesty: str | None = None,
                        claim_evidence_status: str | None = None,
                        injected_memory_cards: list[str] | None = None,
                        review_blocked: bool = False,
                        memory_feedback_status: str | None = None,
                        **extra: Any) -> dict[str, Any]:
    """Build a ``task_finished`` event carrying ``commands_run``,
    ``finish_claim_honesty`` and ``claim_evidence_status`` when provided.
    Optional fields are omitted when ``None``.
    """
    fields: dict[str, Any] = {"success": success}
    if commands_run is not None:
        fields["commands_run"] = commands_run
    if finish_claim_honesty is not None:
        fields["finish_claim_honesty"] = finish_claim_honesty
    if claim_evidence_status is not None:
        fields["claim_evidence_status"] = claim_evidence_status
    if injected_memory_cards:
        fields["injected_memory_cards"] = list(injected_memory_cards)
        fields["review_blocked"] = review_blocked
    if memory_feedback_status is not None:
        fields["memory_feedback_status"] = memory_feedback_status
    fields.update(extra)
    return event("task_finished", task_id, timestamp, **fields)
