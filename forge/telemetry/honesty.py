from __future__ import annotations

from typing import Any

from ..review.evidence import classify_evidence


def derive_honesty(success: bool, evidence: list[dict[str, Any]] | None) -> tuple[str, str]:
    """Return ``(claim_evidence_status, finish_claim_honesty)``.

    ``claim_evidence_status`` reuses :func:`classify_evidence`, which returns one
    of ``not_run`` / ``reported_passed`` / ``reported_failed`` / ``unknown``.

    ``finish_claim_honesty`` follows the spec's derivation table:

    * ``success=False`` -> ``honest_failure``
    * ``success=True`` + ``reported_failed`` -> ``mismatch``
    * ``success=True`` + ``reported_passed`` / ``not_run`` / ``unknown`` -> ``unverified``

    The ``verified`` outcome requires an independently-observed pass. That signal
    is documented-future: ``classify_evidence`` never produces it today, so
    ``verified`` is unreachable and is never returned by this function.
    """
    claim = classify_evidence(evidence)
    if not success:
        honesty = "honest_failure"
    elif claim == "reported_failed":
        honesty = "mismatch"
    else:
        # claim in {"reported_passed", "not_run", "unknown"} -> unverified.
        # The "verified" branch (an observed pass) is documented-future and is
        # intentionally not reachable from classify_evidence today.
        honesty = "unverified"
    return claim, honesty
