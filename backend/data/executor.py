"""Safe plan executor (Phase 3; contract sections 3.5, 6, 8; PRD FR08, FR09).

``execute_plan`` is the only code path that changes inventory. It takes the
exact keyword inputs of Tishneet's workflow gateway and, immediately before
writing, re-checks everything against current trusted state:

  1. Replay: a committed (plan_id, revision) returns its original result.
  2. Run identity and warehouse version must match what was evaluated.
  3. Plan structure (via the simulator's structural pass).
  4. Authorization with the CURRENT agent record (labeled local policy until
     Verified Permissions lands in Phase 4).
  5. Approval for ELEVATED plans (total >= 5): APPROVED and bound to the same
     revision, fingerprint, warehouse version, and run.
  6. Simulation against CURRENT inventory.

Then one DynamoDB transaction writes everything or nothing:
  * warehouse zones + version+1, only if version and run_id are unchanged
  * agent must still be ACTIVE (a revoke that lands first cancels the commit)
  * a unique (plan_id, revision) execution marker
  * a PLAN_EXECUTED audit event

Outcomes:
  * committed:   ExecutionResult (``executed: true``)
  * no commit:   ``{"executed": false, "no_commit": true, "error": {...}}``.
                 Guaranteed: nothing was written.
  * anything else raises ``DataError``. Callers must treat that as
    UNCONFIRMED and replay the same (plan_id, revision) to find out.
"""

import json
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from core.fingerprint import plan_fingerprint
from core.simulator import simulate_plan
from data import dynamo
from data.dynamo import _aws, _aws_code, _build_audit_event, _from_dynamo, _table, _to_dynamo, audit_item
from data.schema import DEFAULT_WAREHOUSE_ID, DEMO_AGENT_ID, table_names
from security.authorization import authorize_plan

APPROVAL_THRESHOLD = 5
STRUCTURAL_CODES = frozenset({"INVALID_PLAN", "INVALID_ACTION", "INVALID_COUNT", "INVALID_WAREHOUSE_STATE"})
REJECTED_CODES = frozenset({"AUTHORIZATION_DENIED", "APPROVAL_REQUIRED", "APPROVAL_INVALID"})
RETRYABLE_CODES = frozenset({"VERSION_CONFLICT"})


def execute_plan(
    *,
    plan_id: Any,
    revision: Any,
    plan: Any,
    warehouse_version: Any,
    run_id: Any,
    approval: Any = None,
    agent_id: str = DEMO_AGENT_ID,
    warehouse_id: str = DEFAULT_WAREHOUSE_ID,
) -> dict[str, Any]:
    """Execute one validated plan revision exactly once. See module docstring."""
    problem = _check_inputs(plan_id, revision, warehouse_version, run_id, approval)
    if problem:
        return _no_commit(plan_id, revision, "INVALID_REQUEST", problem)

    execution_id = f"{plan_id}#{revision}"
    prior = _read_marker(execution_id)
    if prior is not None:
        return prior

    warehouse, current_run, agent = _read_state(warehouse_id, agent_id)

    if current_run != run_id:
        return _no_commit(plan_id, revision, "RUN_MISMATCH",
                          "The demo was reset after this plan was evaluated. Evaluate it again.")
    if warehouse["version"] != warehouse_version:
        return _no_commit(plan_id, revision, "VERSION_CONFLICT",
                          "Warehouse changed since this plan was evaluated. Evaluate it again.",
                          expected_version=warehouse_version, current_version=warehouse["version"])

    simulation = simulate_plan(plan, warehouse)
    structural = [v for v in simulation["violations"] if v["code"] in STRUCTURAL_CODES]
    if structural:
        return _no_commit(plan_id, revision, "PLAN_VALIDATION_FAILED", structural[0]["message"],
                          violations=structural)

    authorization = authorize_plan(plan, agent, warehouse.get("restricted_zones"))
    if not authorization["allowed"]:
        denied = next(d for d in authorization["decisions"] if not d["allowed"])
        return _no_commit(plan_id, revision, "AUTHORIZATION_DENIED",
                          f"Action {_human_index(denied)} denied: {denied['reason_code']}.",
                          authorization=authorization)

    total = sum(action["count"] for action in plan["actions"])
    if total >= APPROVAL_THRESHOLD:
        approval_problem = _check_approval(approval, plan_id, revision, plan, warehouse_version, run_id)
        if approval_problem:
            code, message = approval_problem
            return _no_commit(plan_id, revision, code, message)

    if not simulation["passed"]:
        return _no_commit(plan_id, revision, "SIMULATION_FAILED", simulation["reason"],
                          violations=simulation["violations"])

    return _commit(
        execution_id=execution_id,
        plan_id=plan_id,
        revision=revision,
        run_id=run_id,
        agent_id=agent_id,
        warehouse=warehouse,
        projected=simulation["projected_state"],
        total=total,
        approval=approval if total >= APPROVAL_THRESHOLD else None,
        engine=authorization["engine"],
    )


# ------------------------------------------------------------------- reads


def _read_marker(execution_id: str) -> dict[str, Any] | None:
    """Return the original ExecutionResult if this revision already committed."""
    with _aws("execute_plan replay check"):
        item = _table("executions").get_item(
            Key={"execution_id": execution_id}, ConsistentRead=True
        ).get("Item")
    return None if item is None else json.loads(item["result_json"])


def _read_state(warehouse_id: str, agent_id: str) -> tuple[dict[str, Any], str | None, dict[str, Any]]:
    """Strongly consistent reads of the warehouse (with run_id) and the agent."""
    warehouse, run_id = dynamo.get_warehouse_record(warehouse_id)
    agent = dynamo.get_agent(agent_id)
    return warehouse, run_id, agent


# ------------------------------------------------------------------ checks


def _check_inputs(plan_id: Any, revision: Any, version: Any, run_id: Any, approval: Any) -> str | None:
    if not isinstance(plan_id, str) or not plan_id.strip() or "#" in plan_id:
        return "plan_id must be a non-empty string without '#'."
    if type(revision) is not int or revision < 1:
        return "revision must be an integer >= 1."
    if type(version) is not int or version < 1:
        return "warehouse_version must be an integer >= 1."
    if not isinstance(run_id, str) or not run_id:
        return "run_id must be a non-empty string."
    if approval is not None and not isinstance(approval, Mapping):
        return "approval must be an object or null."
    return None


def _check_approval(
    approval: Any, plan_id: str, revision: int, plan: Any, version: int, run_id: str
) -> tuple[str, str] | None:
    """Return (code, message) if the approval does not authorize this exact plan.

    Agreed envelope (built by the workflow's execution_approval):
    {approval_id, plan_id, revision, fingerprint, warehouse_version, run_id,
     decision, admin, decided_at}. Every binding field must match.
    """
    if approval is None:
        return "APPROVAL_REQUIRED", "Plans moving 5 or more packages need administrator approval."
    if approval.get("decision") != "APPROVED":
        return "APPROVAL_INVALID", "Approval decision is not APPROVED."
    admin = approval.get("admin")
    if not isinstance(admin, str) or not admin.strip():
        return "APPROVAL_INVALID", "Approval does not identify the deciding administrator."
    decided_at = approval.get("decided_at")
    if not isinstance(decided_at, str) or not decided_at.strip():
        return "APPROVAL_INVALID", "Approval does not record when it was decided."
    if approval.get("plan_id") != plan_id:
        return "APPROVAL_INVALID", "Approval was given for a different plan."
    if approval.get("revision") != revision:
        return "APPROVAL_INVALID", "Approval was given for a different plan revision."
    if approval.get("fingerprint") != plan_fingerprint(plan):
        return "APPROVAL_INVALID", "Approved plan does not match the plan being executed."
    if approval.get("warehouse_version") != version:
        return "APPROVAL_INVALID", "Approval was given for a different warehouse version."
    if approval.get("run_id") != run_id:
        return "APPROVAL_INVALID", "Approval belongs to an earlier demo run."
    return None


# ------------------------------------------------------------------ commit


def _commit(
    *,
    execution_id: str,
    plan_id: str,
    revision: int,
    run_id: str,
    agent_id: str,
    warehouse: dict[str, Any],
    projected: dict[str, Any],
    total: int,
    approval: Mapping[str, Any] | None,
    engine: str,
) -> dict[str, Any]:
    before = warehouse["version"]
    after_state = {**warehouse, "version": before + 1, "zones": projected}
    result = {
        "plan_id": plan_id,
        "revision": revision,
        "executed": True,
        "status": "COMPLETED",
        "warehouse_version_before": before,
        "warehouse_version_after": before + 1,
        "warehouse": after_state,
    }
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    audit = _build_audit_event(
        {
            "plan_id": plan_id,
            "revision": revision,
            "event_type": "PLAN_EXECUTED",
            "outcome": "COMPLETED",
            "message": f"Executed {total} package move(s); warehouse version {before} -> {before + 1}.",
            "details": {"warehouse_version_before": before, "warehouse_version_after": before + 1,
                        "authorization_engine": engine},
            **({"admin": approval["admin"]} if approval else {}),
        }
    )
    names = table_names()
    items = [
        {
            "Update": {
                "TableName": names["warehouse"],
                "Key": {"warehouse_id": warehouse["warehouse_id"]},
                "UpdateExpression": "SET #z = :zones, #v = :next, #last = :exec",
                "ConditionExpression": "#v = :expected AND #run = :run",
                "ExpressionAttributeNames": {"#z": "zones", "#v": "version", "#run": "run_id",
                                             "#last": "last_execution"},
                "ExpressionAttributeValues": _to_dynamo({":zones": projected, ":next": before + 1,
                                                         ":expected": before, ":run": run_id,
                                                         ":exec": execution_id}),
            }
        },
        {
            "ConditionCheck": {
                "TableName": names["agents"],
                "Key": {"agent_id": agent_id},
                "ConditionExpression": "#s = :active",
                "ExpressionAttributeNames": {"#s": "status"},
                "ExpressionAttributeValues": {":active": "ACTIVE"},
            }
        },
        {
            "Put": {
                "TableName": names["executions"],
                "Item": {"execution_id": execution_id, "plan_id": plan_id, "revision": revision,
                         "run_id": run_id, "executed_at": now, "result_json": json.dumps(result)},
                "ConditionExpression": "attribute_not_exists(execution_id)",
            }
        },
        {
            "Put": {
                "TableName": names["audit"],
                "Item": audit_item(audit),
                "ConditionExpression": "attribute_not_exists(plan_id) AND attribute_not_exists(event_id)",
            }
        },
    ]
    with _aws("execute_plan commit"):
        try:
            dynamo._dynamodb().meta.client.transact_write_items(TransactItems=items)
        except ClientError as exc:
            if _aws_code(exc) != "TransactionCanceledException":
                raise
            reasons = [r.get("Code") for r in exc.response.get("CancellationReasons", [])]
            outcome = _explain_cancellation(reasons, execution_id, plan_id, revision, run_id, warehouse)
            if outcome is None:
                raise
            return outcome
    return result


def _explain_cancellation(
    reasons: list[str | None], execution_id: str, plan_id: str, revision: int,
    run_id: str, warehouse: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Map a cancelled transaction (nothing written) to a no-commit result, or None if unknown."""
    failed = [i for i, code in enumerate(reasons) if code == "ConditionalCheckFailed"]
    if not failed:
        return None
    if 2 in failed:  # someone committed this exact revision first
        prior = _read_marker(execution_id)
        if prior is not None:
            return prior
    if 1 in failed:
        return _no_commit(plan_id, revision, "AUTHORIZATION_DENIED",
                          "Agent was revoked before the commit; nothing was written.")
    if 0 in failed:
        _state, current_run = dynamo.get_warehouse_record(warehouse["warehouse_id"])
        if current_run != run_id:
            return _no_commit(plan_id, revision, "RUN_MISMATCH",
                              "The demo was reset during execution; nothing was written.")
        return _no_commit(plan_id, revision, "VERSION_CONFLICT",
                          "Warehouse changed during execution; nothing was written. Evaluate again.")
    return None


# ----------------------------------------------------------------- results


def _no_commit(plan_id: Any, revision: Any, code: str, message: str, **details: Any) -> dict[str, Any]:
    """A guaranteed no-commit outcome (nothing was written)."""
    return {
        "plan_id": plan_id if isinstance(plan_id, str) else None,
        "revision": revision if type(revision) is int else None,
        "executed": False,
        "no_commit": True,
        "status": "REJECTED" if code in REJECTED_CODES else "FAILED",
        "error": {"code": code, "message": message, "retryable": code in RETRYABLE_CODES},
        **_from_dynamo(details),
    }


def _human_index(decision: Mapping[str, Any]) -> str:
    index = decision.get("action_index")
    return str(index + 1) if isinstance(index, int) else "?"
