"""Phase 4: Amazon Verified Permissions + Cedar.

A fake Verified Permissions client evaluates the REAL policy files in
security/cedar/ with the Cedar engine (cedarpy), so these tests exercise the
exact policies that get deployed. No real AWS calls. Install: --with cedarpy
"""

import json
import re
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

cedarpy = pytest.importorskip("cedarpy")

from data import dynamo, lambdas  # noqa: E402
from data.executor import execute_plan  # noqa: E402
from data.schema import DEMO_AGENT_ID, table_definitions  # noqa: E402
from security import authorization  # noqa: E402
from security.avp import authorize_plan_avp  # noqa: E402

CEDAR_DIR = Path(__file__).resolve().parents[1] / "security" / "cedar"
POLICIES = "\n".join(p.read_text() for p in sorted(CEDAR_DIR.glob("*.cedar")))
SCHEMA = json.loads((CEDAR_DIR / "schema.json").read_text())
TEMPLATE = (Path(__file__).resolve().parents[1] / "data" / "template.yaml").read_text()
ACTIVE = {"agent_id": DEMO_AGENT_ID, "status": "ACTIVE", "role": "INVENTORY_MANAGER", "max_transfer": 10}


def _value(v):
    (kind, inner), = v.items()
    return inner


class CedarBackedAvp:
    """Mimics verifiedpermissions.batch_is_authorized using cedarpy and the real policies."""

    def __init__(self):
        self.calls = []

    def batch_is_authorized(self, policyStoreId, entities, requests):
        self.calls.append({"policyStoreId": policyStoreId, "requests": requests})
        cedar_entities = [
            {"uid": {"__entity": {"type": e["identifier"]["entityType"], "id": e["identifier"]["entityId"]}},
             "attrs": {k: _value(v) for k, v in e.get("attributes", {}).items()}, "parents": []}
            for e in entities["entityList"]
        ]
        results = []
        for r in requests:
            uid = lambda ref, t, i: f'{ref[t]}::"{ref[i]}"'  # noqa: E731
            request = {
                "principal": uid(r["principal"], "entityType", "entityId"),
                "action": uid(r["action"], "actionType", "actionId"),
                "resource": uid(r["resource"], "entityType", "entityId"),
                "context": {k: _value(v) for k, v in r["context"]["contextMap"].items()},
            }
            decision = cedarpy.is_authorized(request, POLICIES, cedar_entities, schema=SCHEMA).decision
            results.append({"request": r, "decision": "ALLOW" if decision == cedarpy.Decision.Allow else "DENY",
                            "determiningPolicies": [], "errors": []})
        return {"results": results}


def move(source, destination, count):
    return {"type": "move_packages", "from": source, "to": destination, "count": count}


def plan(*actions):
    return {"actions": list(actions)}


def avp(p, agent=ACTIVE, client=None, restricted=("HAZMAT",)):
    return authorize_plan_avp(p, agent, list(restricted), client=client or CedarBackedAvp(),
                              policy_store_id="ps-test", agent_id=DEMO_AGENT_ID, warehouse_id="demo-warehouse")


# --------------------------------------------------------------- policy files


def test_policies_pass_strict_schema_validation():
    result = cedarpy.validate_policies(POLICIES, SCHEMA)

    assert result.validation_passed, [str(e) for e in result.errors]


def test_template_deploys_exactly_these_policies_and_schema():
    squash = lambda text: re.sub(r"\s+", " ", text).strip()  # noqa: E731
    for policy_file in CEDAR_DIR.glob("*.cedar"):
        assert squash(policy_file.read_text()) in squash(TEMPLATE), policy_file.name
    assert squash(json.dumps(SCHEMA, indent=2)) in squash(TEMPLATE)
    assert TEMPLATE.count("SENTINEL_AUTHZ_ENGINE: VERIFIED_PERMISSIONS") == 2  # execute + authorize


def _raw_cedar(status, count, destination, restricted=False, max_transfer=10):
    """Evaluate the deployed policy text directly, with no local-policy overlay."""
    entities = [
        {"uid": {"__entity": {"type": "Sentinel::Agent", "id": DEMO_AGENT_ID}},
         "attrs": {"status": status, "max_transfer": max_transfer}, "parents": []},
        {"uid": {"__entity": {"type": "Sentinel::Warehouse", "id": "demo-warehouse"}}, "attrs": {}, "parents": []},
    ]
    request = {"principal": f'Sentinel::Agent::"{DEMO_AGENT_ID}"', "action": 'Sentinel::Action::"MovePackages"',
               "resource": 'Sentinel::Warehouse::"demo-warehouse"',
               "context": {"count": count, "destination": destination, "restricted_destination": restricted}}
    return cedarpy.is_authorized(request, POLICIES, entities, schema=SCHEMA).decision == cedarpy.Decision.Allow


@pytest.mark.parametrize(
    "status, count, destination, restricted, max_transfer, expected",
    [
        ("ACTIVE", 1, "C", False, 10, True),
        ("ACTIVE", 10, "C", False, 10, True),
        ("ACTIVE", 11, "C", False, 10, False),          # contract limit is 10 per action
        ("ACTIVE", 11, "C", False, 50, False),          # even if the record allowed more
        ("ACTIVE", 6, "C", False, 5, False),            # and never above the agent's own limit
        ("ACTIVE", 0, "C", False, 10, False),
        ("ACTIVE", 1, "HAZMAT", False, 10, False),
        ("ACTIVE", 1, "COLD", True, 10, False),
        ("REVOKED", 1, "C", False, 10, False),
        ("SUSPENDED", 1, "C", False, 10, False),
        ("active", 1, "C", False, 10, False),           # exact status match only
    ],
)
def test_cedar_policies_alone_enforce_the_rules(status, count, destination, restricted, max_transfer, expected):
    assert _raw_cedar(status, count, destination, restricted, max_transfer) is expected


# ----------------------------------------------------- decisions (contract §7)


@pytest.mark.parametrize(
    "agent_status, action, allowed, reason",
    [
        ("ACTIVE", move("A", "C", 3), True, "POLICY_ALLOWED"),
        ("ACTIVE", move("A", "C", 10), True, "POLICY_ALLOWED"),
        ("ACTIVE", move("A", "C", 11), False, "LIMIT_EXCEEDED"),
        ("ACTIVE", move("A", "HAZMAT", 1), False, "RESTRICTED_DESTINATION"),
        ("REVOKED", move("A", "C", 1), False, "AGENT_REVOKED"),
        ("SUSPENDED", move("A", "C", 1), False, "AGENT_SUSPENDED"),
    ],
)
def test_contract_section_7_decisions(agent_status, action, allowed, reason):
    result = avp(plan(action), agent={**ACTIVE, "status": agent_status})

    assert result["engine"] == "VERIFIED_PERMISSIONS"
    assert result["allowed"] is allowed
    assert result["decisions"] == [{"action_index": 0, "allowed": allowed, "reason_code": reason}]


def test_restricted_zone_from_warehouse_state_is_forbidden():
    result = avp(plan(move("A", "COLD", 1)), restricted=("HAZMAT", "COLD"))

    assert result["allowed"] is False
    assert result["decisions"][0]["reason_code"] == "RESTRICTED_DESTINATION"


def test_one_call_per_plan_and_one_denial_denies_all():
    client = CedarBackedAvp()
    result = avp(plan(move("A", "C", 1), move("A", "HAZMAT", 1), move("A", "B", 1)), client=client)

    assert len(client.calls) == 1 and len(client.calls[0]["requests"]) == 3
    assert result["allowed"] is False
    assert [d["allowed"] for d in result["decisions"]] == [True, False, True]


def test_request_shape_uses_trusted_attributes():
    client = CedarBackedAvp()
    avp(plan(move("A", "C", 4)), client=client)

    [request] = client.calls[0]["requests"]
    assert request["principal"] == {"entityType": "Sentinel::Agent", "entityId": DEMO_AGENT_ID}
    assert request["action"] == {"actionType": "Sentinel::Action", "actionId": "MovePackages"}
    assert request["context"]["contextMap"]["count"] == {"long": 4}


# ------------------------------------------------------------------ fail closed


class Raising:
    def batch_is_authorized(self, **kwargs):
        raise RuntimeError("AccessDenied / throttled / network")


class WrongCount:
    def batch_is_authorized(self, **kwargs):
        return {"results": []}


class AlwaysAllow:
    def batch_is_authorized(self, requests, **kwargs):
        return {"results": [{"decision": "ALLOW", "errors": []} for _ in requests]}


class AllowWithErrors:
    def batch_is_authorized(self, requests, **kwargs):
        return {"results": [{"decision": "ALLOW", "errors": [{"errorDescription": "bad"}]} for _ in requests]}


@pytest.mark.parametrize("client", [Raising(), WrongCount()], ids=["aws-error", "mismatched-results"])
def test_aws_failures_deny_every_action(client):
    result = avp(plan(move("A", "C", 1), move("A", "C", 1)), client=client)

    assert result["allowed"] is False
    assert [d["reason_code"] for d in result["decisions"]] == ["AUTHORIZATION_ERROR"] * 2


def test_allow_with_evaluation_errors_is_denied():
    assert avp(plan(move("A", "C", 1)), client=AllowWithErrors())["allowed"] is False


def test_avp_allow_is_overruled_when_local_policy_denies():
    result = avp(plan(move("A", "HAZMAT", 1)), client=AlwaysAllow())

    assert result["allowed"] is False
    assert result["decisions"][0]["reason_code"] == "RESTRICTED_DESTINATION"


@pytest.mark.parametrize("agent", [None, {"status": "ACTIVE"}, {"status": None, "max_transfer": 10},
                                   {"status": "ACTIVE", "max_transfer": "10"}])
def test_missing_trusted_attributes_deny_without_calling_aws(agent):
    client = CedarBackedAvp()
    result = avp(plan(move("A", "C", 1)), agent=agent, client=client)

    assert result["allowed"] is False and client.calls == []


@pytest.mark.parametrize("bad", [None, {}, plan(), plan(move("A", "C", 0)), plan(move("A", "C", True)),
                                 plan({"type": "move_packages", "from": "A", "count": 1})])
def test_malformed_plans_deny_without_calling_aws(bad):
    client = CedarBackedAvp()

    assert avp(bad, client=client)["allowed"] is False
    assert client.calls == []


# --------------------------------------------------------------- engine switch


@pytest.fixture
def clean_engine(monkeypatch):
    monkeypatch.delenv("SENTINEL_AUTHZ_ENGINE", raising=False)
    monkeypatch.delenv("SENTINEL_POLICY_STORE_ID", raising=False)
    authorization.set_avp_client(None)
    yield monkeypatch
    authorization.set_avp_client(None)


def test_default_engine_is_labeled_local_policy(clean_engine):
    assert authorization.authorize(plan(move("A", "C", 1)), ACTIVE)["engine"] == "LOCAL_POLICY"


def test_avp_engine_without_policy_store_denies(clean_engine):
    clean_engine.setenv("SENTINEL_AUTHZ_ENGINE", "VERIFIED_PERMISSIONS")

    result = authorization.authorize(plan(move("A", "C", 1)), ACTIVE)

    assert result["allowed"] is False and result["engine"] == "VERIFIED_PERMISSIONS"


def test_unknown_engine_denies(clean_engine):
    clean_engine.setenv("SENTINEL_AUTHZ_ENGINE", "YOLO")

    assert authorization.authorize(plan(move("A", "C", 1)), ACTIVE)["allowed"] is False


def test_avp_engine_never_falls_back_to_local_on_error(clean_engine):
    clean_engine.setenv("SENTINEL_AUTHZ_ENGINE", "VERIFIED_PERMISSIONS")
    clean_engine.setenv("SENTINEL_POLICY_STORE_ID", "ps-test")
    authorization.set_avp_client(Raising())

    result = authorization.authorize(plan(move("A", "C", 1)), ACTIVE)

    assert result["allowed"] is False and result["decisions"][0]["reason_code"] == "AUTHORIZATION_ERROR"


# ------------------------------------------------- executor + Lambda with AVP


@pytest.fixture
def avp_db(clean_engine):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "SENTINEL_WAREHOUSE_TABLE", "SENTINEL_AGENTS_TABLE",
                "SENTINEL_AUDIT_TABLE", "SENTINEL_EXECUTIONS_TABLE"):
        clean_engine.delenv(var, raising=False)
    clean_engine.setenv("AWS_ACCESS_KEY_ID", "testing")
    clean_engine.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    clean_engine.setenv("AWS_DEFAULT_REGION", "us-east-1")
    clean_engine.setenv("SENTINEL_AUTHZ_ENGINE", "VERIFIED_PERMISSIONS")
    clean_engine.setenv("SENTINEL_POLICY_STORE_ID", "ps-test")
    client = CedarBackedAvp()
    authorization.set_avp_client(client)
    lambdas.reset_clients()
    with mock_aws():
        ddb = boto3.client("dynamodb")
        for definition in table_definitions():
            ddb.create_table(**definition)
        dynamo.seed_if_missing()
        yield client
    lambdas.reset_clients()


def _execute(p, plan_id="plan-1"):
    return execute_plan(plan_id=plan_id, revision=1, plan=p, warehouse_version=dynamo.get_warehouse()["version"],
                        run_id=dynamo.get_run_id(), approval=None)


def test_executor_commits_via_verified_permissions(avp_db):
    result = _execute(plan(move("A", "C", 3)))

    assert result["executed"] is True
    assert len(avp_db.calls) == 1
    [event] = dynamo.list_audit_events("plan-1")
    assert event["details"]["authorization_engine"] == "VERIFIED_PERMISSIONS"


def test_executor_denies_revoked_agent_via_verified_permissions(avp_db):
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    result = _execute(plan(move("A", "C", 1)))

    assert result["no_commit"] is True and result["error"]["code"] == "AUTHORIZATION_DENIED"
    assert result["authorization"]["engine"] == "VERIFIED_PERMISSIONS"
    assert result["authorization"]["decisions"][0]["reason_code"] == "AGENT_REVOKED"
    assert dynamo.get_warehouse()["version"] == 1


def test_executor_denies_when_verified_permissions_is_down(avp_db):
    authorization.set_avp_client(Raising())

    result = _execute(plan(move("A", "C", 1)))

    assert result["no_commit"] is True and result["error"]["code"] == "AUTHORIZATION_DENIED"
    assert dynamo.get_warehouse()["version"] == 1


def test_authorize_lambda_uses_verified_permissions(avp_db):
    allowed = lambdas.authorize_handler({"plan": plan(move("A", "C", 3))}, None)
    limit = lambdas.authorize_handler({"plan": plan(move("A", "C", 11))}, None)

    assert allowed["allowed"] is True and allowed["engine"] == "VERIFIED_PERMISSIONS"
    assert limit["decisions"][0]["reason_code"] == "LIMIT_EXCEEDED"


def test_authorize_lambda_denies_on_data_failure(avp_db, monkeypatch):
    def broken(*a, **k):
        raise dynamo.DataAccessError("x", aws_code="ThrottlingException", retryable=True)

    monkeypatch.setattr(dynamo, "get_agent", broken)
    result = lambdas.authorize_handler({"plan": plan(move("A", "C", 1), move("A", "B", 1))}, None)

    assert result["allowed"] is False
    assert [d["reason_code"] for d in result["decisions"]] == ["AUTHORIZATION_ERROR"] * 2
