"""Per-action authorization (contract sections 3.2 and 7).

Two engines, chosen by ``authorize()`` from SENTINEL_AUTHZ_ENGINE:
  * VERIFIED_PERMISSIONS: Amazon Verified Permissions + Cedar (security/avp.py).
    This is what the deployed Lambdas use.
  * LOCAL_POLICY: ``authorize_plan`` below, a labeled fallback with the same
    intent. Results carry ``"engine": "LOCAL_POLICY"`` so it is never
    presented as an AWS integration. It also supplies reason codes for
    Verified Permissions decisions.

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


# ------------------------------------------------------------- engine choice

_avp_client: Any = None


def set_avp_client(client: Any) -> None:
    """Override (or reset with None) the Verified Permissions client. Used by tests."""
    global _avp_client
    _avp_client = client


def authorize(
    plan: Any,
    agent: Any,
    restricted_zones: Any = (),
    *,
    agent_id: str = "inventory-agent-01",
    warehouse_id: str = "demo-warehouse",
) -> dict[str, Any]:
    """Authorize with the configured engine.

    ``SENTINEL_AUTHZ_ENGINE``:
      * ``LOCAL_POLICY`` (default): this module's labeled fallback.
      * ``VERIFIED_PERMISSIONS``: Amazon Verified Permissions using
        ``SENTINEL_POLICY_STORE_ID``. If that is missing or AWS fails, every
        action is denied; it never silently falls back to the local policy.
    Any other value denies everything.
    """
    import os

    engine = os.environ.get("SENTINEL_AUTHZ_ENGINE", "LOCAL_POLICY")
    if engine == ENGINE:
        return authorize_plan(plan, agent, restricted_zones)

    from .avp import ENGINE as AVP_ENGINE, authorize_plan_avp, deny_all

    actions = plan.get("actions") if isinstance(plan, Mapping) else None
    if engine != AVP_ENGINE:
        return deny_all(actions, "AUTHORIZATION_ERROR", engine=str(engine))
    store = os.environ.get("SENTINEL_POLICY_STORE_ID")
    if not store:
        return deny_all(actions, "AUTHORIZATION_ERROR")
    global _avp_client
    if _avp_client is None:
        import boto3

        _avp_client = boto3.client("verifiedpermissions")
    return authorize_plan_avp(plan, agent, restricted_zones, client=_avp_client,
                              policy_store_id=store, agent_id=agent_id, warehouse_id=warehouse_id)
