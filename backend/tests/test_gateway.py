"""Tests for security.gateway (Tishneet's workflow adapter).

The gateway is routed in-process to Mariam's real Lambda handlers backed by
moto DynamoDB / Secrets Manager / Step Functions, so these cover the full
gateway -> handler -> DynamoDB path. No real AWS calls.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

from core.fingerprint import plan_fingerprint
from data import dynamo, lambdas
from data.schema import DEMO_AGENT_ID, seed_warehouse, table_definitions
from security import gateway as gateway_module
from security.gateway import GatewayError, TrustedGateway, create_gateway

ROUTES = {
    "warehouse": lambdas.warehouse_handler,
    "agent": lambdas.agent_handler,
    "runid": lambdas.runid_handler,
    "execute": lambdas.execute_handler,
    "audit_append": lambdas.audit_append_handler,
    "authorize": lambdas.authorize_handler,
    "revoke": lambdas.revoke_handler,
    "reset": lambdas.reset_handler,
}
REQUIRED_METHODS = ("get_warehouse", "get_agent", "get_run_id", "authorize_plan", "simulate_plan",
                    "execute_plan", "revoke_agent", "reset_demo", "append_audit")


def in_process(calls=None):
    def invoke(function, payload):
        if calls is not None:
            calls.append(function)
        return json.loads(json.dumps(ROUTES[function](json.loads(json.dumps(payload)), None)))
    return invoke


@pytest.fixture
def aws(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "ADMIN_SECRET_ARN", "STATE_MACHINE_ARN",
                "SENTINEL_WAREHOUSE_TABLE", "SENTINEL_AGENTS_TABLE", "SENTINEL_AUDIT_TABLE",
                "SENTINEL_EXECUTIONS_TABLE"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    lambdas.reset_clients()
    with mock_aws():
        client = boto3.client("dynamodb")
        for definition in table_definitions():
            client.create_table(**definition)
        dynamo.seed_if_missing()
        yield monkeypatch
    lambdas.reset_clients()


@pytest.fixture
def api_process(aws):
    """Ishani's API process: has the signing secret and Tishneet's state machine ARN."""
    secret_arn = boto3.client("secretsmanager").create_secret(
        Name="sentinel/admin-assertion-key", SecretString="K" * 64)["ARN"]
    machine = boto3.client("stepfunctions").create_state_machine(
        name="planning", roleArn="arn:aws:iam::123456789012:role/sfn",
        definition=json.dumps({"StartAt": "P", "States": {"P": {"Type": "Pass", "End": True}}}),
    )["stateMachineArn"]
    aws.setenv("ADMIN_SECRET_ARN", secret_arn)   # read by my Lambdas and by the gateway
    aws.setenv("STATE_MACHINE_ARN", machine)
    return machine


def move(source, destination, count):
    return {"type": "move_packages", "from": source, "to": destination, "count": count}


# ------------------------------------------------------ factory and construction


def test_factory_contract_matches_workflow_checks():
    gw = create_gateway(store=object())

    assert gw.name and "FIXTURE" not in gw.name.upper()
    for method in REQUIRED_METHODS:
        assert callable(getattr(gw, method))


def test_construction_and_reads_never_touch_aws_or_the_signing_key(aws, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError(f"unexpected boto3.client{args}")

    monkeypatch.setattr(boto3, "client", forbidden)
    gw = create_gateway(None)          # workflow Lambda: no key, no clients at construction
    gw._invoke_override = in_process()  # reads go through my handlers (already-built clients)

    assert gw.get_warehouse()["version"] == 1
    assert gw._signing_key is None


def test_importable_as_backend_security_gateway_from_repo_root():
    repo_root = Path(__file__).resolve().parents[2]
    code = ("import backend.security.gateway as g; gw = g.create_gateway(None); "
            "print(gw.name, g._simulate_plan.__module__)")
    out = subprocess.run([sys.executable, "-c", code], cwd=repo_root, capture_output=True, text=True,
                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})

    assert out.returncode == 0, out.stderr
    assert "LAMBDA_GATEWAY backend.core.simulator" in out.stdout


# ------------------------------------------------------------------- reads


def test_reads_and_unwrapped_run_id(aws):
    gw = TrustedGateway(invoke=in_process())

    assert gw.get_warehouse() == seed_warehouse()
    assert gw.get_agent()["status"] == "ACTIVE"
    run_id = gw.get_run_id()
    assert isinstance(run_id, str) and run_id == dynamo.get_run_id()


def test_error_objects_become_gateway_errors(aws):
    gw = TrustedGateway(invoke=lambda f, p: {"error": {"code": "NOT_FOUND", "message": "x", "retryable": False}})

    with pytest.raises(GatewayError) as info:
        gw.get_warehouse()
    assert info.value.code == "NOT_FOUND"


def test_missing_run_id_raises(aws):
    with pytest.raises(GatewayError):
        TrustedGateway(invoke=lambda f, p: {"run_id": ""}).get_run_id()


# --------------------------------------------------------- authorize/simulate


def test_authorize_uses_current_agent_status(aws):
    gw = TrustedGateway(invoke=in_process())
    plan = {"actions": [move("A", "C", 3)]}

    assert gw.authorize_plan(plan)["allowed"] is True
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")
    denied = gw.authorize_plan(plan)
    assert denied["allowed"] is False
    assert denied["decisions"][0]["reason_code"] == "AGENT_REVOKED"


def test_authorize_fails_closed_when_reads_fail(aws):
    def broken(function, payload):
        raise RuntimeError("network down")

    result = TrustedGateway(invoke=broken).authorize_plan({"actions": [move("A", "C", 1), move("A", "C", 1)]})

    assert result["allowed"] is False
    assert [d["reason_code"] for d in result["decisions"]] == ["AUTHORIZATION_ERROR"] * 2


def test_simulate_is_in_process(aws):
    gw = TrustedGateway(invoke=lambda f, p: pytest.fail("simulate must not invoke a Lambda"))

    result = gw.simulate_plan({"actions": [move("A", "B", 5)]}, seed_warehouse())

    assert result["passed"] is False and result["violations"][0]["projected"] == 13


# ------------------------------------------------------------------ execute


def test_execute_commits_then_replays_through_gateway(aws):
    gw = TrustedGateway(invoke=in_process())
    kwargs = dict(plan_id="plan-g", revision=1, plan={"actions": [move("A", "C", 3)]},
                  warehouse_version=1, run_id=gw.get_run_id(), approval=None)

    first = gw.execute_plan(**kwargs)
    again = gw.execute_plan(**kwargs)

    assert first["executed"] is True and first["warehouse_version_after"] == 2
    assert again == first
    assert dynamo.get_warehouse()["zones"]["C"]["inventory"] == 8


def test_execute_with_workflow_approval_envelope(aws):
    gw = TrustedGateway(invoke=in_process())
    plan = {"actions": [move("A", "B", 2), move("A", "C", 3)]}
    run_id = gw.get_run_id()
    # Exactly what the workflow's gateway_contracts.execution_approval sends.
    approval = {"approval_id": "approval-abc", "plan_id": "plan-d2", "revision": 2,
                "fingerprint": plan_fingerprint(plan), "warehouse_version": 1, "run_id": run_id,
                "decision": "APPROVED", "admin": "alice@scu.edu", "decided_at": "2026-11-07T23:59:00Z"}

    result = gw.execute_plan(plan_id="plan-d2", revision=2, plan=plan, warehouse_version=1,
                             run_id=run_id, approval=approval)

    assert result["executed"] is True
    assert {z: v["inventory"] for z, v in dynamo.get_warehouse()["zones"].items()} == {"A": 15, "B": 10, "C": 8}


def test_execute_passes_no_commit_and_unconfirmed_responses_through(aws):
    no_commit = {"executed": False, "no_commit": True, "error": {"code": "VERSION_CONFLICT"}}
    unconfirmed = {"error": {"code": "INTERNAL_ERROR", "message": "?", "retryable": True}}

    assert TrustedGateway(invoke=lambda f, p: no_commit).execute_plan(
        plan_id="p", revision=1, plan={}, warehouse_version=1, run_id="r", approval=None) == no_commit
    assert TrustedGateway(invoke=lambda f, p: unconfirmed).execute_plan(
        plan_id="p", revision=1, plan={}, warehouse_version=1, run_id="r", approval=None) == unconfirmed


def test_execute_rejects_unexpected_kwargs():
    with pytest.raises(TypeError):
        TrustedGateway(invoke=lambda f, p: {}).execute_plan(plan_id="p", skip_checks=True)


# -------------------------------------------------------------------- audit


def test_append_audit_is_idempotent_for_workflow_events(aws):
    gw = TrustedGateway(invoke=in_process())
    event = {"plan_id": "plan-abc", "event_id": "plan-abc#000001", "timestamp": "2026-11-07T23:00:00Z",
             "revision": 1, "event_type": "PLAN_SUBMITTED", "outcome": "PENDING", "reason_code": None,
             "message": "Plan submitted"}

    assert gw.append_audit(event) == {"recorded": True, "duplicate": False}
    assert gw.append_audit(event) == {"recorded": True, "duplicate": True}
    assert len(dynamo.list_audit_events("plan-abc")) == 1


def test_recent_audit_interleaves_writers_by_time(aws):
    gw = TrustedGateway(invoke=in_process())
    gw.append_audit({"plan_id": "plan-zzz", "event_id": "plan-zzz#000001", "timestamp": "2026-11-07T22:00:00Z",
                     "revision": 1, "event_type": "PLAN_SUBMITTED", "outcome": "PENDING", "message": "older"})
    dynamo.record_audit_event({"plan_id": "SYSTEM", "event_id": "2026-11-07T23:00:00.000Z#aaaaaaaa",
                               "timestamp": "2026-11-07T23:00:00Z", "event_type": "AGENT_REVOKED",
                               "outcome": "REVOKED", "message": "newer"})

    assert [e["message"] for e in dynamo.list_audit_events()] == ["newer", "older"]


# ------------------------------------------------------ admin actions / signing


def test_revoke_signs_in_api_process(api_process):
    gw = TrustedGateway(invoke=in_process())

    assert gw.revoke_agent("alice@scu.edu")["status"] == "REVOKED"
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"


def test_revoke_without_signing_config_fails_before_any_invoke(aws):
    calls = []
    gw = TrustedGateway(invoke=in_process(calls))

    with pytest.raises(GatewayError) as info:
        gw.revoke_agent("alice@scu.edu")
    assert info.value.code == "INTERNAL_ERROR"
    assert calls == []
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


@pytest.mark.parametrize("admin", ["", "a|b", "x" * 257, None, 5])
def test_bad_admin_identity_is_refused_before_any_invoke(api_process, admin):
    calls = []

    with pytest.raises(GatewayError) as info:
        TrustedGateway(invoke=in_process(calls)).revoke_agent(admin)
    assert info.value.code == "FORBIDDEN"
    assert calls == []


def test_reset_requires_admin(api_process):
    with pytest.raises(GatewayError) as info:
        TrustedGateway(invoke=in_process()).reset_demo(3, {"run_id": "x"})
    assert info.value.code == "FORBIDDEN"


def test_reset_returns_warehouse_state_and_rotates_run(api_process):
    gw = TrustedGateway(invoke=in_process())
    gw.execute_plan(plan_id="plan-1", revision=1, plan={"actions": [move("A", "C", 3)]},
                    warehouse_version=1, run_id=gw.get_run_id(), approval=None)
    old_run = gw.get_run_id()

    state = gw.reset_demo(7, {"run_id": old_run, "active": []}, "alice@scu.edu")

    assert state == seed_warehouse()
    assert gw.get_run_id() != old_run


def test_reset_blocked_while_workflow_execution_running_is_a_guaranteed_refusal(api_process):
    boto3.client("stepfunctions").start_execution(stateMachineArn=api_process, name="plan-live")
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    with pytest.raises(GatewayError) as info:
        TrustedGateway(invoke=in_process()).reset_demo(1, {}, "alice@scu.edu")
    assert info.value.code == "VERSION_CONFLICT" and info.value.retryable is True
    assert info.value.no_commit is True
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"  # nothing was reset


def test_reset_internal_error_is_unconfirmed_not_guaranteed(api_process):
    gw = TrustedGateway(invoke=lambda f, p: {"error": {"code": "INTERNAL_ERROR", "message": "?", "retryable": True}})

    with pytest.raises(GatewayError) as info:
        gw.reset_demo(1, {}, "alice@scu.edu")
    assert info.value.code == "INTERNAL_ERROR" and info.value.no_commit is False


def test_refusals_before_invoke_are_guaranteed(aws):
    gw = TrustedGateway(invoke=lambda f, p: pytest.fail("must not invoke"))

    for call in (lambda: gw.reset_demo(1, {}, None), lambda: gw.reset_demo(1, {}, "a|b"),
                 lambda: gw.revoke_agent("alice@scu.edu")):  # last one: no ADMIN_SECRET_ARN here
        with pytest.raises(GatewayError) as info:
            call()
        assert info.value.no_commit is True


def test_reset_treats_control_snapshot_as_read_only(api_process):
    control = {"run_id": "r1", "active": ["plan-1"]}
    snapshot = json.loads(json.dumps(control))

    TrustedGateway(invoke=in_process()).reset_demo(4, control, "alice@scu.edu")

    assert control == snapshot


def test_gateway_signatures_are_accepted_by_my_verifier(api_process):
    gw = TrustedGateway(invoke=in_process())
    assertion = gw._assertion("RESET_DEMO", "alice@scu.edu")

    from security.admin_assertion import verify
    assert verify(assertion, key=b"K" * 64, expected_action="RESET_DEMO")["admin"] == "alice@scu.edu"
    assert gateway_module.FUNCTIONS["execute"][1] == "sentinel-data-execute"
