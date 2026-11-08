"""Plan fingerprint shared with the workflow.

An approval binds to this hash, so both sides must compute it identically.
Single source of truth: Tishneet's ``backend/ai/validation.py::fingerprint``.
It is used whenever it is importable (after the team merge). Until then, the
byte-identical local copy below is used; a test compares the two directly.

Algorithm: SHA-256 of the complete PlanActions object as canonical JSON
(sorted keys, compact separators, ASCII escaping, UTF-8). Action order is
preserved; property order inside objects is not significant.
"""

import hashlib
import json
from typing import Any


def _local_fingerprint(plan: Any) -> str:
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


try:  # repository root on the path (workflow Lambda, merged tests)
    from backend.ai.validation import fingerprint as _workflow_fingerprint
except ImportError:
    try:  # backend/ on the path (Mariam's Lambdas after the merge)
        from ai.validation import fingerprint as _workflow_fingerprint
    except ImportError:
        _workflow_fingerprint = None

SOURCE = "backend.ai.validation" if _workflow_fingerprint else "local copy"


def plan_fingerprint(plan: Any) -> str:
    """Return the hex SHA-256 fingerprint of a validated PlanActions object.

    Callers must validate the plan first (the executor does); Tishneet's
    function raises ValueError for an invalid plan.
    """
    if _workflow_fingerprint is not None:
        return _workflow_fingerprint(plan)
    return _local_fingerprint(plan)
