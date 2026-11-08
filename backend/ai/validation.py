"""Independent structural validation and canonical candidate fingerprints.

Author: Tishneet
"""

import hashlib
import json
import re

ZONE = re.compile(r"^[A-Z][A-Z0-9_]*$")
ACTION_KEYS = {"type", "from", "to", "count"}


def validate_plan(plan):
    """Return contract-shaped errors without trusting model-provided claims."""
    errors = []

    def reject(code, message, index=None):
        errors.append({"code": code, "message": message, "action_index": index})

    if not isinstance(plan, dict) or set(plan) != {"actions"}:
        reject("INVALID_PLAN", "Plan must contain exactly the actions property.")
        return {"valid": False, "errors": errors}
    actions = plan["actions"]
    if not isinstance(actions, list) or not 1 <= len(actions) <= 10:
        reject("INVALID_PLAN", "actions must contain between 1 and 10 entries.")
        return {"valid": False, "errors": errors}
    for index, action in enumerate(actions):
        if not isinstance(action, dict) or set(action) != ACTION_KEYS:
            reject("INVALID_ACTION", "Action requires exactly type, from, to, count.", index)
            continue
        if action["type"] != "move_packages":
            reject("INVALID_ACTION", "Only move_packages is supported.", index)
        for field in ("from", "to"):
            if not isinstance(action[field], str) or not ZONE.fullmatch(action[field]):
                reject("INVALID_ZONE", field + " must be an uppercase zone label.", index)
        if action["from"] == action["to"]:
            reject("INVALID_ACTION", "Source and destination must differ.", index)
        if type(action["count"]) is not int or action["count"] < 1:
            reject("INVALID_COUNT", "count must be a positive JSON integer, excluding booleans.", index)
    return {"valid": not errors, "errors": errors}


def fingerprint(plan):
    """Hash validated, canonical JSON; dictionary property order is irrelevant."""
    result = validate_plan(plan)
    if not result["valid"]:
        raise ValueError("Cannot fingerprint an invalid plan.")
    canonical = json.dumps(plan, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
