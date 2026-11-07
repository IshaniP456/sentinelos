"""Mocked tests for data.lambdas (moto: DynamoDB, Secrets Manager, Step Functions). No real AWS."""

import json
import re
import secrets
import time
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from data import dynamo, lambdas
from data.schema import DEMO_AGENT_ID, seed_agent, seed_warehouse, table_definitions, table_names
from security.admin_assertion import sign

SIGNING_KEY = "S" * 64
HANDLERS = [
    lambdas.warehouse_handler,
    lambdas.agent_handler,
    lambdas.audit_handler,
    lambdas.revoke_handler,
    lambdas.reset_handler,
    lambdas.runid_handler,
    lambdas.execute_handler,
    lambdas.audit_append_handler,
]


# ---------------------------------------------------------------------- fixtures


@pytest.fixture
def aws(monkeypatch):
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "SENTINEL_WAREHOUSE_TABLE",
                "SENTINEL_AGENTS_TABLE", "SENTINEL_AUDIT_TABLE", "SENTINEL_AGENT_ID",
                "ADMIN_SECRET_ARN", "STATE_MACHINE_ARN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    lambdas.reset_clients()
    with mock_aws():
        yield monkeypatch
    lambdas.reset_clients()


@pytest.fixture
def stack(aws):
    """Tables (seeded), signing secret, and an idle state machine, wired via env vars."""
    client = boto3.client("dynamodb")
    for definition in table_definitions():
        client.create_table(**definition)
    dynamo.seed_if_missing()
    secret_arn = boto3.client("secretsmanager").create_secret(
        Name="sentinel/admin-assertion-key", SecretString=SIGNING_KEY
    )["ARN"]
    machine_arn = boto3.client("stepfunctions").create_state_machine(
        name="sentinel-planning",
        definition=json.dumps({"StartAt": "Wait", "States": {"Wait": {"Type": "Pass", "End": True}}}),
        roleArn="arn:aws:iam::123456789012:role/sfn",
    )["stateMachineArn"]
    aws.setenv("ADMIN_SECRET_ARN", secret_arn)
    aws.setenv("STATE_MACHINE_ARN", machine_arn)
    yield {"dynamodb": client, "machine_arn": machine_arn}


def assertion(action, admin="alice@scu.edu", issued_at=None, key=SIGNING_KEY.encode(), nonce=None):
    issued_at = int(time.time()) if issued_at is None else issued_at
    nonce = nonce or secrets.token_hex(16)
    return {
        "admin": admin,
        "action": action,
        "issued_at": issued_at,
        "nonce": nonce,
        "signature": sign(key, action, admin, issued_at, nonce),
    }


def assert_error(result, code, retryable=None):
    assert set(result) == {"error"}, result
    assert set(result["error"]) == {"code", "message", "retryable"}
    assert result["error"]["code"] == code
    assert isinstance(result["error"]["message"], str) and result["error"]["message"]
    if retryable is not None:
        assert result["error"]["retryable"] is retryable


def warehouse_with_d1_applied():
    item = {**seed_warehouse(), "version": 2}
    item["zones"]["A"]["inventory"] = 17
    item["zones"]["C"]["inventory"] = 8
    boto3.resource("dynamodb").Table(table_names()["warehouse"]).put_item(Item=item)


# ----------------------------------------------------------------- warehouse


@pytest.mark.parametrize("event", [{}, None, {"warehouse_id": "other"}])
def test_warehouse_handler_returns_warehouse_state(stack, event):
    assert lambdas.warehouse_handler(event, None) == seed_warehouse()


# --------------------------------------------------------------------- agent


def test_agent_handler_returns_configured_agent(stack):
    assert lambdas.agent_handler({}, None) == seed_agent()


def test_agent_handler_ignores_caller_supplied_agent_id(stack):
    assert lambdas.agent_handler({"agent_id": "someone-else"}, None)["agent_id"] == DEMO_AGENT_ID


# --------------------------------------------------------------------- audit


def test_audit_handler_returns_events_envelope(stack):
    first = dynamo.record_audit_event({"plan_id": "plan-001", "event_id": "2026-11-07T20:00:00.000Z#01",
                                       "event_type": "PLAN_SUBMITTED", "outcome": "PENDING", "message": "m"})
    second = dynamo.record_audit_event({"plan_id": "plan-002", "event_id": "2026-11-07T20:00:01.000Z#02",
                                        "event_type": "PLAN_SUBMITTED", "outcome": "PENDING", "message": "m"})

    assert lambdas.audit_handler({}, None) == {"events": [second, first]}
    assert lambdas.audit_handler({"plan_id": None}, None) == {"events": [second, first]}
    assert lambdas.audit_handler({"plan_id": ""}, None) == {"events": [second, first]}
    assert lambdas.audit_handler({"plan_id": "plan-001"}, None) == {"events": [first]}


def test_audit_handler_rejects_non_string_plan_id(stack):
    assert_error(lambdas.audit_handler({"plan_id": 5}, None), "INVALID_REQUEST")


# -------------------------------------------------------------------- revoke


def test_revoke_with_valid_assertion_revokes_and_audits(stack):
    result = lambdas.revoke_handler({"admin_assertion": assertion("REVOKE_AGENT")}, None)

    assert result == {**seed_agent(), "status": "REVOKED"}
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "REVOKED"
    events = {e["event_type"]: e for e in dynamo.list_audit_events("SYSTEM")}
    assert events["AGENT_REVOKED"]["admin"] == "alice@scu.edu"
    assert events["ADMIN_ACTION_AUTHORIZED"]["admin"] == "alice@scu.edu"


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({}, id="no-assertion"),
        pytest.param({"admin": "admin"}, id="plain-admin-string"),
        pytest.param({"admin": "alice@scu.edu", "admin_assertion": "alice"}, id="assertion-not-object"),
        pytest.param({"admin_assertion": assertion("RESET_DEMO")}, id="assertion-for-other-action"),
        pytest.param({"admin_assertion": assertion("REVOKE_AGENT", key=b"W" * 64)}, id="wrong-key"),
        pytest.param({"admin_assertion": assertion("REVOKE_AGENT", issued_at=int(time.time()) - 120)},
                     id="expired"),
        pytest.param({"admin_assertion": {**assertion("REVOKE_AGENT"), "admin": "mallory"}},
                     id="tampered-admin"),
        pytest.param(None, id="null-event"),
    ],
)
def test_unauthorized_revoke_fails_and_changes_nothing(stack, event):
    assert_error(lambdas.revoke_handler(event, None), "FORBIDDEN", retryable=False)

    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"
    assert [e["event_type"] for e in dynamo.list_audit_events("SYSTEM")] == []


def test_revoke_fails_closed_when_secret_not_configured(stack, monkeypatch):
    monkeypatch.delenv("ADMIN_SECRET_ARN")
    lambdas.reset_clients()

    assert_error(lambdas.revoke_handler({"admin_assertion": assertion("REVOKE_AGENT")}, None), "FORBIDDEN")
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


def test_revoke_fails_closed_when_secret_unreadable(stack, monkeypatch):
    monkeypatch.setenv("ADMIN_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:missing")
    lambdas.reset_clients()

    assert_error(lambdas.revoke_handler({"admin_assertion": assertion("REVOKE_AGENT")}, None), "FORBIDDEN")
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


def test_replayed_assertion_is_rejected(stack):
    signed = assertion("REVOKE_AGENT")
    assert lambdas.revoke_handler({"admin_assertion": signed}, None)["status"] == "REVOKED"
    dynamo.update_agent_status(DEMO_AGENT_ID, "ACTIVE")

    assert_error(lambdas.revoke_handler({"admin_assertion": signed}, None), "FORBIDDEN")
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"


# --------------------------------------------------------------------- reset


def test_reset_with_valid_assertion_and_no_running_plans_restores_seed(stack):
    warehouse_with_d1_applied()
    dynamo.update_agent_status(DEMO_AGENT_ID, "REVOKED")

    result = lambdas.reset_handler({"admin_assertion": assertion("RESET_DEMO")}, None)

    assert result == seed_warehouse()
    assert dynamo.get_warehouse() == seed_warehouse()
    assert dynamo.get_agent(DEMO_AGENT_ID)["status"] == "ACTIVE"
    reset_event = next(e for e in dynamo.list_audit_events("SYSTEM") if e["event_type"] == "DEMO_RESET")
    assert reset_event["admin"] == "alice@scu.edu"


def test_reset_blocked_while_a_plan_is_running(stack):
    boto3.client("stepfunctions").start_execution(stateMachineArn=stack["machine_arn"], name="plan-abc")
    warehouse_with_d1_applied()

    result = lambdas.reset_handler({"admin_assertion": assertion("RESET_DEMO")}, None)

    assert_error(result, "VERSION_CONFLICT", retryable=True)
    assert dynamo.get_warehouse()["version"] == 2


def test_reset_blocked_when_workflow_check_not_configured(stack, monkeypatch):
    monkeypatch.delenv("STATE_MACHINE_ARN")
    warehouse_with_d1_applied()

    assert_error(lambdas.reset_handler({"admin_assertion": assertion("RESET_DEMO")}, None),
                 "VERSION_CONFLICT", retryable=True)
    assert dynamo.get_warehouse()["version"] == 2


@pytest.mark.parametrize(
    "event",
    [
        pytest.param({"admin": "admin"}, id="plain-admin-string"),
        pytest.param({"admin_assertion": assertion("REVOKE_AGENT")}, id="revoke-assertion-reused-for-reset"),
    ],
)
def test_unauthorized_reset_fails_and_changes_nothing(stack, event):
    warehouse_with_d1_applied()

    assert_error(lambdas.reset_handler(event, None), "FORBIDDEN")
    assert dynamo.get_warehouse()["version"] == 2


# ---------------------------------------------------------- failures/errors


def test_missing_records_return_not_found(stack):
    stack["dynamodb"].delete_item(TableName=table_names()["agents"], Key={"agent_id": {"S": DEMO_AGENT_ID}})

    assert_error(lambdas.agent_handler({}, None), "NOT_FOUND", retryable=False)
    assert_error(
        lambdas.revoke_handler({"admin_assertion": assertion("REVOKE_AGENT")}, None), "NOT_FOUND"
    )


@pytest.mark.parametrize("handler", [lambdas.warehouse_handler, lambdas.agent_handler, lambdas.audit_handler])
def test_missing_tables_return_controlled_internal_error(aws, handler):
    result = handler({}, None)

    assert_error(result, "INTERNAL_ERROR", retryable=False)
    assert "ResourceNotFound" not in result["error"]["message"]  # no AWS internals leaked


def test_throttling_returns_retryable_error(stack, monkeypatch):
    def throttled(*_args, **_kwargs):
        raise dynamo.DataAccessError("x", aws_code="ProvisionedThroughputExceededException", retryable=True)

    monkeypatch.setattr(dynamo, "get_warehouse", throttled)

    assert_error(lambdas.warehouse_handler({}, None), "INTERNAL_ERROR", retryable=True)


def test_unexpected_exception_returns_generic_error_without_details(stack, monkeypatch):
    def boom(*_args, **_kwargs):
        raise RuntimeError("internal secret detail")

    monkeypatch.setattr(dynamo, "get_warehouse", boom)
    result = lambdas.warehouse_handler({}, None)

    assert_error(result, "INTERNAL_ERROR")
    assert "secret detail" not in result["error"]["message"]


def test_dynamodb_client_error_during_revoke_is_controlled(stack, monkeypatch):
    def denied(*_args, **_kwargs):
        raise dynamo.DataAccessError("x", aws_code="AccessDeniedException", retryable=False)

    monkeypatch.setattr(dynamo, "update_agent_status", denied)

    assert_error(lambdas.revoke_handler({"admin_assertion": assertion("REVOKE_AGENT")}, None),
                 "INTERNAL_ERROR", retryable=False)


@pytest.mark.parametrize("handler", HANDLERS, ids=lambda h: h.__name__)
@pytest.mark.parametrize("event", [None, "text", [], 5, {"unexpected": True}])
def test_handlers_never_raise_and_return_json(stack, handler, event):
    result = handler(event, None)

    assert isinstance(result, dict)
    assert json.loads(json.dumps(result)) == result


def test_no_handler_leaks_the_signing_key(stack):
    outputs = [h({"admin_assertion": assertion("REVOKE_AGENT")}, None) for h in HANDLERS]
    outputs.append(lambdas.audit_handler({}, None))

    assert SIGNING_KEY not in json.dumps(outputs)


# ------------------------------------------------------------ template sanity


def test_every_template_handler_exists():
    template = (Path(__file__).parent.parent / "data" / "template.yaml").read_text()
    handlers = re.findall(r"Handler:\s*data\.lambdas\.(\w+)", template)

    assert sorted(handlers) == sorted(h.__name__ for h in HANDLERS)
    for name in handlers:
        assert callable(getattr(lambdas, name))


# ------------------------------------------------------------- runid / execute


def test_runid_handler_returns_current_run(stack):
    assert lambdas.runid_handler({}, None) == {"run_id": dynamo.get_run_id()}


def _execute_event(**overrides):
    event = {
        "plan_id": "plan-1",
        "revision": 1,
        "plan": {"actions": [{"type": "move_packages", "from": "A", "to": "C", "count": 3}]},
        "warehouse_version": 1,
        "run_id": dynamo.get_run_id(),
        "approval": None,
    }
    event.update(overrides)
    return event


def test_execute_handler_commits_and_replays(stack):
    first = lambdas.execute_handler(_execute_event(), None)
    again = lambdas.execute_handler(_execute_event(), None)

    assert first["executed"] is True and first["warehouse_version_after"] == 2
    assert again == first
    assert dynamo.get_warehouse()["zones"]["C"]["inventory"] == 8


def test_execute_handler_no_commit_shape(stack):
    result = lambdas.execute_handler(_execute_event(warehouse_version=7), None)

    assert result["executed"] is False and result["no_commit"] is True
    assert result["error"]["code"] == "VERSION_CONFLICT"
    assert dynamo.get_warehouse()["version"] == 1


@pytest.mark.parametrize("event", [{}, {"plan_id": "p"}, None, "text"])
def test_execute_handler_rejects_malformed_requests_without_commit(stack, event):
    result = lambdas.execute_handler(event, None)

    assert result["no_commit"] is True and result["error"]["code"] == "INVALID_REQUEST"
    assert dynamo.get_warehouse()["version"] == 1


def test_execute_handler_rejects_unexpected_fields(stack):
    result = lambdas.execute_handler(_execute_event(skip_checks=True), None)

    assert result["no_commit"] is True and result["error"]["code"] == "INVALID_REQUEST"


def test_execute_handler_infra_failure_is_unconfirmed_not_no_commit(stack):
    stack["dynamodb"].delete_table(TableName=table_names()["executions"])

    result = lambdas.execute_handler(_execute_event(), None)

    assert_error(result, "INTERNAL_ERROR", retryable=True)
    assert "no_commit" not in result
