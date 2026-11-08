"""Normalize trusted gateway boundaries without exposing authority. Author: Tishneet."""
from .errors import WorkflowError


NO_COMMIT_ERRORS = {
    "INVALID_REQUEST": "The executor rejected the request format; nothing was committed.",
    "PLAN_VALIDATION_FAILED": "The executor rejected the plan structure; nothing was committed.",
    "VERSION_CONFLICT": "Warehouse changed; evaluate the plan again.",
    "RUN_MISMATCH": "Demo run changed; evaluate the plan again.",
    "AUTHORIZATION_DENIED": "The executor denied current authorization.",
    "SIMULATION_FAILED": "The executor rejected the current inventory projection.",
    "APPROVAL_REQUIRED": "The executor requires approval for this plan.",
    "APPROVAL_INVALID": "The executor rejected the approval binding.",
}

ADMIN_REFUSALS = {
    "VERSION_CONFLICT": ("The gateway refused this operation because current state could not permit it.", 409),
    "FORBIDDEN": ("The gateway refused administrator authorization.", 403),
    "NOT_FOUND": ("The gateway could not find the required resource.", 404),
    "INVALID_REQUEST": ("The gateway rejected the administrative request.", 400),
    "INTERNAL_ERROR": ("The gateway could not configure or perform this operation.", 503),
}


def gateway_failure(error, confirmed_only=False):
    """Read Mariam's GatewayError protocol without importing her implementation.

    Only exact booleans and agreed codes qualify. Never use exception messages,
    signing assertions or response bodies as operator-visible error text.
    """
    no_commit = getattr(error, "no_commit", None)
    code = getattr(error, "code", None)
    if type(no_commit) is not bool or not isinstance(code, str) or code not in ADMIN_REFUSALS:
        return None
    if confirmed_only and not no_commit:
        return None
    if not no_commit:
        return WorkflowError("GATEWAY_UNCONFIRMED", "Gateway outcome is unconfirmed; inspect current state before retrying.", status=502)
    message, status = ADMIN_REFUSALS[code]
    return WorkflowError(code, message, getattr(error, "retryable", False) is True, status)


def normalize_run_id(value):
    """Gateway may unwrap its Lambda response itself; persist only the string."""
    if isinstance(value, dict):
        value = value.get("run_id")
    if not isinstance(value, str) or not value.strip():
        raise WorkflowError("DEPENDENCY_ERROR", "Gateway returned an invalid run identity.", True, 502)
    return value


def execution_approval(record):
    """Use Mariam's executor envelope; storage/public status remain unchanged."""
    if not record["risk"]["approval_required"]:
        return None
    approval = record.get("approval") or {}
    if (approval.get("status") != "APPROVED"
            or not isinstance(approval.get("admin"), str) or not approval["admin"].strip()
            or not isinstance(approval.get("decision_at"), str) or not approval["decision_at"]):
        raise WorkflowError("APPROVAL_INVALID", "A verified, recorded approval is required.")
    return {"approval_id": approval["approval_id"], "plan_id": record["plan_id"],
            "revision": approval["revision"], "fingerprint": approval["fingerprint"],
            "warehouse_version": approval["warehouse_version"], "run_id": approval["run_id"],
            "decision": approval["status"], "admin": approval["admin"],
            "decided_at": approval["decision_at"]}


def confirmed_noncommit_error(result):
    """Preserve agreed error codes and retry flags, never raw backend messages."""
    detail = result.get("error")
    if isinstance(detail, dict) and isinstance(detail.get("code"), str) and detail["code"] in NO_COMMIT_ERRORS:
        code = detail["code"]
        return WorkflowError(code, NO_COMMIT_ERRORS[code], detail.get("retryable") is True,
                             403 if code == "AUTHORIZATION_DENIED" else 409)
    return WorkflowError("EXECUTION_NOT_COMMITTED", "Executor confirmed no inventory commit.")
