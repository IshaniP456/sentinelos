"""Amazon Verified Permissions authorization (Phase 4; contract section 7).

Every action of a plan is checked with one BatchIsAuthorized call against the
Cedar policies in ``security/cedar/`` (deployed to the policy store by the
SAM template):

  principal  Sentinel::Agent::"<agent_id>"   attributes status, max_transfer (from DynamoDB)
  action     Sentinel::Action::"MovePackages"
  resource   Sentinel::Warehouse::"<warehouse_id>"
  context    count, destination, restricted_destination

Fail closed: a malformed plan, missing trusted attributes, an AWS error, or a
response that does not line up with the requests denies every action.

Reason codes come from the local policy's explanation of the same action.
If Verified Permissions allows an action the local policy would deny, the
action is denied anyway (defense in depth) and the mismatch is logged.
"""

import logging
from collections.abc import Mapping
from typing import Any

from .authorization import ALWAYS_RESTRICTED, authorize_plan as local_authorize

logger = logging.getLogger(__name__)

ENGINE = "VERIFIED_PERMISSIONS"
AGENT_TYPE = "Sentinel::Agent"
WAREHOUSE_TYPE = "Sentinel::Warehouse"
ACTION = {"actionType": "Sentinel::Action", "actionId": "MovePackages"}


def authorize_plan_avp(
    plan: Any,
    agent: Any,
    restricted_zones: Any = (),
    *,
    client: Any,
    policy_store_id: str,
    agent_id: str,
    warehouse_id: str,
) -> dict[str, Any]:
    """Return an AuthorizationResult decided by Verified Permissions."""
    actions = plan.get("actions") if isinstance(plan, Mapping) else None
    if not isinstance(actions, list) or not actions or not all(_well_formed(a) for a in actions):
        return deny_all(actions, "AUTHORIZATION_ERROR")
    if not isinstance(agent, Mapping) or not isinstance(agent.get("status"), str) \
            or type(agent.get("max_transfer")) is not int:
        return deny_all(actions, "AUTHORIZATION_ERROR")

    restricted = ALWAYS_RESTRICTED | {z for z in (restricted_zones or ()) if isinstance(z, str)}
    principal = {"entityType": AGENT_TYPE, "entityId": agent_id}
    resource = {"entityType": WAREHOUSE_TYPE, "entityId": warehouse_id}
    entities = {
        "entityList": [
            {"identifier": principal,
             "attributes": {"status": {"string": agent["status"]},
                            "max_transfer": {"long": agent["max_transfer"]}}},
            {"identifier": resource, "attributes": {}},
        ]
    }
    requests = [
        {"principal": principal, "action": ACTION, "resource": resource,
         "context": {"contextMap": {"count": {"long": a["count"]},
                                    "destination": {"string": a["to"]},
                                    "restricted_destination": {"boolean": a["to"] in restricted}}}}
        for a in actions
    ]

    try:
        response = client.batch_is_authorized(
            policyStoreId=policy_store_id, entities=entities, requests=requests
        )
        results = response.get("results")
        if not isinstance(results, list) or len(results) != len(requests):
            raise ValueError("BatchIsAuthorized results do not match the requests")
    except Exception:
        logger.exception("Verified Permissions call failed; denying (fail closed)")
        return deny_all(actions, "AUTHORIZATION_ERROR")

    local = local_authorize(plan, agent, restricted_zones)["decisions"]
    decisions = []
    for index, (result, explanation) in enumerate(zip(results, local)):
        avp_allows = result.get("decision") == "ALLOW" and not result.get("errors")
        if avp_allows and explanation["allowed"]:
            decisions.append({"action_index": index, "allowed": True, "reason_code": "POLICY_ALLOWED"})
            continue
        if avp_allows:
            logger.error("Verified Permissions allowed action %d that local policy denies (%s); denying",
                         index, explanation["reason_code"])
        reason = explanation["reason_code"] if not explanation["allowed"] else "POLICY_DENIED"
        decisions.append({"action_index": index, "allowed": False, "reason_code": reason})
    return {"allowed": all(d["allowed"] for d in decisions), "decisions": decisions, "engine": ENGINE}


def deny_all(actions: Any, reason: str, engine: str = ENGINE) -> dict[str, Any]:
    """A fail-closed result denying every action (or one placeholder if there are none)."""
    count = len(actions) if isinstance(actions, list) and actions else 0
    decisions = ([{"action_index": i, "allowed": False, "reason_code": reason} for i in range(count)]
                 or [{"action_index": None, "allowed": False, "reason_code": reason}])
    return {"allowed": False, "decisions": decisions, "engine": engine}


def _well_formed(action: Any) -> bool:
    return (isinstance(action, Mapping) and type(action.get("count")) is int and action["count"] >= 1
            and isinstance(action.get("to"), str) and bool(action["to"]))
