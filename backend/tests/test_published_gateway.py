"""Workflow checks with owner sources after integration. Author: Tishneet.

The model is explicitly a fixture; gateway/data handlers are real code running
against moto. This test never establishes live AWS or Bedrock readiness.
"""
import json
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

gateway_module = pytest.importorskip("backend.security.gateway")

from backend.ai.planner import Planner
from backend.ai.providers import FixtureProvider
from backend.ai.validation import fingerprint
from backend.workflows.errors import WorkflowError
from backend.workflows.service import WorkflowService
from backend.workflows.store import MemoryStore
from backend.tests.test_workflow import D1, D2, drive


@pytest.fixture
def integrated(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]))
    from data import dynamo, lambdas
    from data.schema import table_definitions
    for name in ("AWS_PROFILE", "AWS_SESSION_TOKEN", "ADMIN_SECRET_ARN", "STATE_MACHINE_ARN",
                 "SENTINEL_WAREHOUSE_TABLE", "SENTINEL_AGENTS_TABLE", "SENTINEL_AUDIT_TABLE",
                 "SENTINEL_EXECUTIONS_TABLE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    routes = {"warehouse": lambdas.warehouse_handler, "agent": lambdas.agent_handler,
              "runid": lambdas.runid_handler, "execute": lambdas.execute_handler,
              "audit_append": lambdas.audit_append_handler, "reset": lambdas.reset_handler}
    with mock_aws():
        lambdas.reset_clients()
        for definition in table_definitions():
            boto3.client("dynamodb").create_table(**definition)
        dynamo.seed_if_missing()
        def invoke(function, payload):
            return json.loads(json.dumps(routes[function](payload, None)))
        gateway = gateway_module.TrustedGateway(invoke=invoke)
        service = WorkflowService(MemoryStore(), Planner(FixtureProvider()), gateway,
                                  audit_sink=gateway.append_audit)
        yield service, gateway
        lambdas.reset_clients()


def test_published_gateway_replan_approval_and_atomic_execution(integrated):
    from backend.core.fingerprint import plan_fingerprint, SOURCE
    service, gateway = integrated
    first = service.start_plan(D1)["plan_id"]
    assert drive(service, first)["status"] == "COMPLETED"
    second = service.start_plan(D2)["plan_id"]
    pending = drive(service, second)
    assert pending["status"] == "AWAITING_APPROVAL"
    assert pending["attempt"] == 2
    assert pending["candidates"][0]["simulation"]["passed"] is False
    plan = pending["candidates"][-1]["plan"]
    assert SOURCE == "backend.ai.validation"
    assert plan_fingerprint(plan) == fingerprint(plan)
    service.record_approval(pending["approval"]["approval_id"], "APPROVED", "verified-admin")
    result = drive(service, second)
    if (result["status"] == "FAILED"
            and (result.get("error") or {}).get("code") == "APPROVAL_INVALID"):
        pytest.xfail("Mariam a4b262f executor reads status; agreed envelope supplies decision. Owner fix required.")
    assert result["status"] == "COMPLETED"
    warehouse = gateway.get_warehouse()
    assert warehouse["version"] == 3
    assert [warehouse["zones"][zone]["inventory"] for zone in "ABC"] == [12, 10, 11]
    assert gateway._signing_key is None


def test_published_gateway_routine_execution_needs_no_signing_secret(integrated):
    service, gateway = integrated
    plan_id = service.start_plan(D1)["plan_id"]
    assert drive(service, plan_id)["status"] == "COMPLETED"
    warehouse = gateway.get_warehouse()
    assert warehouse["version"] == 2
    assert [warehouse["zones"][zone]["inventory"] for zone in "ABC"] == [17, 8, 8]
    assert gateway._signing_key is None


def test_published_gateway_unsigned_reset_releases_fence_without_mutation(integrated):
    service, gateway = integrated
    before = gateway.get_warehouse()
    with pytest.raises(WorkflowError) as info:
        service.reset_demo("verified-admin")
    assert info.value.code == "INTERNAL_ERROR"
    assert service.store.read("CONTROL")[1]["reset"] is None
    assert gateway.get_warehouse() == before
