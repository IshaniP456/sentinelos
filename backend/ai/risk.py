"""Deterministic risk classification; never defer the threshold to the model.

Author: Tishneet
"""

from .validation import validate_plan


def classify_risk(plan):
    """Sum every ordered movement, including movements of the same packages."""
    if not validate_plan(plan)["valid"]:
        raise ValueError("Risk classification requires a structurally valid plan.")
    total = sum(action["count"] for action in plan["actions"])
    elevated = total >= 5
    return {"risk": "ELEVATED" if elevated else "LOW", "approval_required": elevated, "total_packages": total}
