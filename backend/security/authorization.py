"""Per-action authorization (contract sections 3.2 and 7).

LOCAL POLICY ENGINE. This is the labeled fallback until Amazon Verified
Permissions is integrated (Phase 4). Every result carries
``"engine": "LOCAL_POLICY"`` so it is never presented as an AWS integration.

Policy (same intent as the planned Cedar policies):
  * only an ACTIVE agent may move packages
  * at most the agent's ``max_transfer`` packages per action
  * never into a restricted zone (HAZMAT)
Anything missing or malformed denies (fail closed). One denied action denies
the whole plan.
"""

from collections.abc import Mapping
from typing import Any

ENGINE = "LOCAL_POLICY"
ALWAYS_RESTRICTED = frozenset({"HAZMAT"})


def authorize_plan(plan: Any, agent: Any, restricted_zones: Any = ()) -> dict[str, Any]:
    """Return an AuthorizationResult: ``{"allowed", "decisions", "engine"}``.

    Args:
        plan: PlanActions.
        agent: the trusted AgentRecord read from DynamoDB (never from the caller).
        restricted_zones: extra restricted zone names from WarehouseState.
    """
    actions = plan.get("actions") if isinstance(plan, Mapping) else None
    if not isinstance(actions, list) or not actions:
        return _result([{"action_index": None, "allowed": False, "reason_code": "AUTHORIZATION_ERROR"}])

    restricted = ALWAYS_RESTRICTED | {z for z in (restricted_zones or ()) if isinstance(z, str)}
    status = agent.get("status") if isinstance(agent, Mapping) else None
    limit = agent.get("max_transfer") if isinstance(agent, Mapping) else None

    decisions = []
    for index, action in enumerate(actions):
        decisions.append({"action_index": index, **_decide(action, status, limit, restricted)})
    return _result(decisions)


def _decide(action: Any, status: Any, limit: Any, restricted: frozenset[str]) -> dict[str, Any]:
    if status != "ACTIVE":
        code = {"REVOKED": "AGENT_REVOKED", "SUSPENDED": "AGENT_SUSPENDED"}.get(status, "AGENT_NOT_ACTIVE")
        return {"allowed": False, "reason_code": code}
    if type(limit) is not int or limit < 1:
        return {"allowed": False, "reason_code": "AUTHORIZATION_ERROR"}
    if not isinstance(action, Mapping):
        return {"allowed": False, "reason_code": "AUTHORIZATION_ERROR"}
    count, destination = action.get("count"), action.get("to")
    if type(count) is not int or count < 1 or not isinstance(destination, str):
        return {"allowed": False, "reason_code": "AUTHORIZATION_ERROR"}
    if count > limit:
        return {"allowed": False, "reason_code": "LIMIT_EXCEEDED"}
    if destination in restricted:
        return {"allowed": False, "reason_code": "RESTRICTED_DESTINATION"}
    return {"allowed": True, "reason_code": "POLICY_ALLOWED"}


def _result(decisions: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "allowed": bool(decisions) and all(d["allowed"] for d in decisions),
        "decisions": decisions,
        "engine": ENGINE,
    }
