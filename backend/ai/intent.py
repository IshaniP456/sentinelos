"""Conservative deterministic interpretation of the supported movement requests.

Author: Tishneet
"""

import re

from .validation import validate_plan

WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
    "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18,
    "nineteen": 19, "twenty": 20,
}
_COUNT = "(?:[0-9]+|" + "|".join(WORDS) + ")"
_ZONE = r"[a-z][a-z0-9_]*"
_MOVEMENT = re.compile(
    r"move\s+(?P<count>" + _COUNT + r")\s+packages?\s+"
    r"(?:from|out\s+of)\s+(?:zone\s+)?(?P<source>" + _ZONE + r")\s*,?\s*"
    r"(?P<preferred>preferably\s+)?(?:to|into)\s+(?:zone\s+)?"
    r"(?P<destination>" + _ZONE + r")"
    r"(?P<alternative>\s*[.;,]\s*(?:use\s+another\s+zone\s+if\s+necessary|"
    r"another\s+zone\s+is\s+acceptable|use\s+another\s+zone\s+if\s+needed))?\s*\.?",
    re.IGNORECASE,
)


def parse_instruction(instruction):
    """Accept a bounded grammar; ambiguous/extra instructions require clarification.

    A preference alone is not permission to redirect: an explicit alternatives
    clause is required. This deliberately supports the documented demo grammar,
    rather than claiming general natural-language understanding.
    """
    if not isinstance(instruction, str) or len(instruction) > 4000:
        raise ValueError("Provide a supported movement instruction of at most 4000 characters.")
    match = _MOVEMENT.fullmatch(instruction.strip())
    if not match:
        raise ValueError("Clarify the request: move N packages from Zone X to Zone Y; explicitly allow another zone if needed.")
    raw_count = match.group("count").lower()
    count = WORDS[raw_count] if raw_count in WORDS else int(raw_count)
    source, destination = match.group("source").upper(), match.group("destination").upper()
    if count < 1 or source == destination:
        raise ValueError("Specify a positive quantity and distinct source and destination.")
    return {
        "source": source,
        "destination": destination,
        "count": count,
        "flexible": match.group("alternative") is not None,
    }


def check_intent(plan, intent):
    """Check the whole candidate against independently interpreted hard constraints."""
    structural = validate_plan(plan)
    if not structural["valid"]:
        return structural
    errors = []
    for index, action in enumerate(plan["actions"]):
        if action["from"] != intent["source"]:
            errors.append({"code": "INTENT_MISMATCH", "message": "Candidate changes the requested source.", "action_index": index})
        if not intent["flexible"] and action["to"] != intent["destination"]:
            errors.append({"code": "INTENT_MISMATCH", "message": "Candidate changes a required destination.", "action_index": index})
    if sum(action["count"] for action in plan["actions"]) != intent["count"]:
        errors.append({"code": "INTENT_MISMATCH", "message": "Candidate changes the requested total movement.", "action_index": None})
    return {"valid": not errors, "errors": errors}
